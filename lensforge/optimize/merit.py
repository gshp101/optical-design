"""The merit function editor.

A :class:`MeritFunction` is an ordered list of operand rows.  Each row has an
operand type (see :mod:`lensforge.optimize.operands`), parameters, a target,
a weight and a bound:

* ``bound="="``: the value should equal the target,
* ``bound=">"`` / ``"<"``: one-sided boundary (no contribution when satisfied).
  The ``..GT`` / ``..LT`` / ``MN..`` / ``MX..`` operands set this by default.

Weights: ``> 0`` adds the row to the merit function; ``0`` evaluates it for
display only; ``< 0`` makes the row a hard constraint that the damped least
squares optimiser satisfies exactly via Lagrange multipliers.  A merit
function with a single (non-BLNK) row always uses weight 1 for it
(:meth:`MeritFunction.auto_weight`), since weight 0 would leave nothing to
optimise.

The merit value is the usual weighted RMS

    MF^2 = sum_i W_i (V_i - T_i)^2 / sum_i W_i

so a merit function made only of a default RMS-spot block equals the
field-weighted RMS spot radius.
"""

from __future__ import annotations

import inspect
import math
from dataclasses import dataclass, field as dc_field
from typing import Dict, List, Optional, Sequence

import numpy as np

from .operands import DEFAULT_BOUND, OPERAND_INFO, OPERANDS, Block, EvalContext, OperandError


@dataclass
class Operand:
    type: str
    target: float = 0.0
    weight: float = 1.0
    bound: Optional[str] = None
    params: Dict = dc_field(default_factory=dict)
    comment: str = ""

    def __post_init__(self):
        self.type = self.type.upper()
        if self.type not in OPERANDS:
            raise KeyError(f"Unknown operand {self.type!r}; see lensforge.optimize.OPERAND_INFO")
        if self.bound is None:
            self.bound = DEFAULT_BOUND[self.type]
        if self.bound not in ("=", ">", "<"):
            raise ValueError("bound must be '=', '>' or '<'")

    @property
    def hard(self) -> bool:
        return self.weight < 0

    def compute(self, ctx) -> Block:
        v = OPERANDS[self.type](ctx, **self.params)
        if not isinstance(v, Block):
            v = Block(np.array([float(v)]))
        return v

    def errors(self, values: np.ndarray) -> np.ndarray:
        """Signed deviation from the target, zero where a boundary is satisfied."""
        e = values - self.target
        if self.bound == ">":
            e = np.minimum(e, 0.0)
        elif self.bound == "<":
            e = np.maximum(e, 0.0)
        return e

    def to_dict(self):
        if self.type == "USER":
            raise TypeError("USER operands hold Python functions and cannot be serialised")
        return {"type": self.type, "target": self.target, "weight": self.weight, "bound": self.bound,
                "params": dict(self.params), "comment": self.comment}

    def describe(self) -> str:
        p = ", ".join(f"{k}={v!r}" if not callable(v) else f"{k}={getattr(v, '__name__', 'fn')}"
                      for k, v in self.params.items())
        return f"{self.type}({p})"


def _scalar(row, b) -> float:
    """One number per row for display and row references: the value itself, the
    weighted RMS of a block, or the extreme value of a boundary block."""
    v = b.values
    if v.size == 0:
        return 0.0
    if v.size == 1:
        return float(v[0])
    if np.sum(b.norm) > 0:
        return float(np.sqrt(np.sum(b.weights * v**2) / np.sum(b.norm)))
    return float(v.min() if row.bound == ">" else v.max() if row.bound == "<" else v.mean())


@dataclass
class MeritEvaluation:
    value: float                 # the merit function (inf if something failed)
    rows: List[Block]            # raw results per row (None if not computed)
    scalars: List[float]         # scalar value per row (RMS for blocks)
    contributions: np.ndarray    # fraction of MF^2 per row
    error: Optional[str] = None


class MeritFunction:
    """Ordered list of :class:`Operand` rows (a merit function editor)."""

    def __init__(self, rows: Sequence[Operand] = (), wizard: Optional[Dict] = None):
        self.rows: List[Operand] = list(rows)
        #: the :func:`default_merit` options that built the default rows (None if not built by it);
        #: saved with the lens so the wizard reopens with the same settings
        self.wizard: Optional[Dict] = None if wizard is None else dict(wizard)

    # -- editing ---------------------------------------------------------------
    def add(self, type: str, target: float = 0.0, weight: float = 1.0, bound: Optional[str] = None,
            comment: str = "", **params) -> Operand:
        """Append a row, e.g. ``mf.add("EFFL", 100, 1)`` or ``mf.add("REAY", 0, 1, surf=5, hy=1, py=1)``."""
        row = Operand(type, target, weight, bound, params, comment)
        self.rows.append(row)
        return row

    def insert(self, index: int, type: str, target: float = 0.0, weight: float = 1.0, bound=None,
               comment: str = "", **params) -> Operand:
        row = Operand(type, target, weight, bound, params, comment)
        self.rows.insert(index, row)
        return row

    def auto_weight(self) -> bool:
        """Give a lone row weight 1: a merit function with a single row of weight 0
        would always be 0, so optimisation could not change anything.  Returns
        True if the weight was changed."""
        if len(self.rows) == 1 and self.rows[0].type != "BLNK" and self.rows[0].weight == 0:
            self.rows[0].weight = 1.0
            return True
        return False

    def remove(self, index: int):
        del self.rows[index]

    def clear(self):
        self.rows.clear()

    def extend(self, other: "MeritFunction"):
        """Append the rows of another merit function (row references are shifted)."""
        shift = len(self.rows)
        for r in other.rows:
            p = dict(r.params)
            if r.type in ("SUMM", "DIFF", "PROD", "DIVI", "ABSO", "SQRT", "OSUM", "MAXX", "MINN", "OPGT",
                          "OPLT", "OPVA"):
                for k in ("a", "b"):
                    if k in p:
                        p[k] += shift
            self.rows.append(Operand(r.type, r.target, r.weight, r.bound, p, r.comment))
        return self

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, i):
        return self.rows[i]

    def __iter__(self):
        return iter(self.rows)

    def copy(self) -> "MeritFunction":
        return MeritFunction([Operand(r.type, r.target, r.weight, r.bound, dict(r.params), r.comment)
                              for r in self.rows], self.wizard)

    # -- evaluation ------------------------------------------------------------
    def _compute(self, system):
        mc = getattr(system, "multiconfig", None)
        switching = mc is not None and any(r.type == "CONF" for r in self.rows)
        if not switching:
            return self._compute_rows(system, None)
        # CONF rows switch the lens to another configuration; afterwards it is put back as it was
        start = mc.current
        mc.capture(system)
        try:
            return self._compute_rows(system, mc)
        finally:
            if mc.current != start:
                mc.apply(system, start)

    def _compute_rows(self, system, mc):
        ctx = EvalContext(system)
        blocks, scalars = [], []
        err = None
        for r in self.rows:
            try:
                if r.type == "CONF" and mc is not None:
                    k = int(r.params.get("cfg", 1))
                    if not 1 <= k <= mc.n_configs:
                        raise OperandError(f"configuration {k} does not exist (1 to {mc.n_configs})")
                    if k != mc.current:
                        mc.apply(system, k)
                        values = ctx.values
                        ctx = EvalContext(system)  # cached traces belong to the previous configuration
                        ctx.values = values
                b = r.compute(ctx)
                if not np.all(np.isfinite(b.values)):
                    raise OperandError("non-finite value")
            except (OperandError, ValueError, ZeroDivisionError, FloatingPointError, RuntimeError,
                    IndexError, NotImplementedError, TypeError) as e:  # TypeError: misspelt parameter
                err = f"row {len(blocks)} ({r.type}): {e}"
                blocks.append(None)
                scalars.append(math.nan)
                ctx.values.append(math.nan)
                continue
            s = _scalar(r, b)
            blocks.append(b)
            scalars.append(s)
            ctx.values.append(s)
        return blocks, scalars, err

    def residuals(self, system):
        """Return (r, c, ok): weighted soft residuals with ||r||^2 = MF^2, hard-constraint
        errors ``c`` (one per element of rows with negative weight, zero when a
        one-sided bound is satisfied) and False if any row failed."""
        blocks, _, err = self._compute(system)
        if err is not None:
            return None, None, False
        num, den, hard = [], 0.0, []
        for r, b in zip(self.rows, blocks):
            e = r.errors(b.values)
            if r.weight > 0:
                num.append(np.sqrt(r.weight * b.weights) * e)
                den += r.weight * float(np.sum(b.norm))
            elif r.weight < 0:
                hard.append(e)
        rv = np.concatenate(num) if num else np.zeros(0)
        if den <= 0:
            den = 1.0
        return rv / math.sqrt(den), (np.concatenate(hard) if hard else np.zeros(0)), True

    def value(self, system) -> float:
        r, _, ok = self.residuals(system)
        return float(np.sqrt(np.sum(r * r))) if ok else math.inf

    def evaluate(self, system) -> MeritEvaluation:
        blocks, scalars, err = self._compute(system)
        num = np.zeros(len(self.rows))
        den = 0.0
        for k, (r, b) in enumerate(zip(self.rows, blocks)):
            if b is None or r.weight <= 0:
                continue
            e = r.errors(b.values)
            num[k] = r.weight * np.sum(b.weights * e * e)
            den += r.weight * float(np.sum(b.norm))
        den = den if den > 0 else 1.0
        total = num.sum()
        value = math.inf if err else math.sqrt(total / den)
        contrib = num / total if total > 0 else num
        return MeritEvaluation(value, blocks, scalars, contrib, err)

    def table(self, system, show_all: bool = True) -> str:
        """Text listing like a merit function editor."""
        ev = self.evaluate(system)
        lines = [f"{'#':>3} {'Type':5} {'Parameters':42} {'Bnd':>3} {'Target':>12} {'Weight':>8} "
                 f"{'Value':>13} {'% Contrib':>9}"]
        for k, r in enumerate(self.rows):
            if not show_all and r.weight == 0:
                continue
            v = ev.scalars[k]
            p = r.describe()[len(r.type) + 1:-1]
            if len(p) > 42:
                p = p[:39] + "..."
            lines.append(f"{k:>3} {r.type:5} {p:42} {r.bound:>3} {r.target:>12.6g} {r.weight:>8.4g} "
                         f"{v:>13.6g} {100 * ev.contributions[k]:>9.3f}")
        lines.append(f"Merit function: {ev.value:.8g}" + (f"   ({ev.error})" if ev.error else ""))
        return "\n".join(lines)

    # -- serialisation ---------------------------------------------------------
    def to_dict(self):
        d = {"rows": [r.to_dict() for r in self.rows]}
        if self.wizard:
            d["wizard"] = dict(self.wizard)
        return d

    @classmethod
    def from_dict(cls, d):
        mf = cls([Operand(r["type"], r.get("target", 0.0), r.get("weight", 1.0), r.get("bound"),
                          dict(r.get("params", {})), r.get("comment", "")) for r in d["rows"]], d.get("wizard"))
        mf.auto_weight()
        return mf

    def __repr__(self):
        return f"MeritFunction({len(self.rows)} rows)"


#: operand types that the default merit function writes (replaced when it is rebuilt)
DEFAULT_MERIT_TYPES = ("RAYS", "OPDS", "ANGS", "MTFA", "CONF")
BOUNDARY_TYPES = ("MNCG", "MXCG", "MNEG", "MXEG", "MNCA", "MXCA", "MNEA", "MXEA")

#: criteria of :func:`default_merit` (``kind``), with the operand each one writes
CRITERIA = {"spot": ("RAYS", "Spot radius"), "spot_x": ("RAYS", "Spot X"), "spot_y": ("RAYS", "Spot Y"),
            "spot_xy": ("RAYS", "Spot X + Y"), "wavefront": ("OPDS", "Wavefront"),
            "angular": ("ANGS", "Angular radius"), "angular_x": ("ANGS", "Angular X"),
            "angular_y": ("ANGS", "Angular Y"), "angular_xy": ("ANGS", "Angular X + Y"),
            "mtf": ("MTFA", "MTF")}
REFERENCES = ("centroid", "chief", "unreferenced")
PUPILS = ("gaussian", "rectangular")
OPTIMIZATION_TYPES = ("rms", "ptv")


def is_default_row(row) -> bool:
    """True for rows written by :func:`default_merit` (image-quality blocks, CONF
    headers, the "Default merit" BLNK header and the thickness boundaries)."""
    return (row.type in DEFAULT_MERIT_TYPES or row.type in BOUNDARY_TYPES
            or (row.type == "BLNK" and row.comment.startswith("Default merit")))


def default_merit(system, kind: str = "spot", reference: str = "centroid", rings: int = 3, arms: int = 6,
                  frequency: Optional[float] = None, fields: Optional[Sequence[int]] = None,
                  wavelengths: Optional[Sequence[int]] = None, symmetric: Optional[bool] = None,
                  glass_min: Optional[float] = None, glass_max: Optional[float] = None,
                  glass_edge: Optional[float] = None, air_min: Optional[float] = None,
                  air_max: Optional[float] = None, air_edge: Optional[float] = None,
                  boundary_weight: float = 1.0, configs: Optional[Sequence[int]] = None,
                  config_weights: Optional[Sequence[float]] = None, *, optimization: str = "rms",
                  component: Optional[str] = None, pupil: str = "gaussian", grid: int = 6,
                  obscuration: float = 0.0, delete_vignetted: bool = True, field_weighting: str = "system",
                  wavelength_weighting: str = "system", weight: float = 1.0,
                  glass_max_edge: Optional[float] = None, air_max_edge: Optional[float] = None,
                  boundary_surfaces: Optional[Sequence[int]] = None) -> MeritFunction:
    """Default merit function (the "optimisation wizard").

    Image quality:

    * ``optimization``: "rms" (root-mean-square over the pupil) or "ptv"
      (peak-to-valley: the largest ray error, or the wavefront's max - min).
    * ``kind`` (criterion): "spot" (transverse ray error, radial), "spot_x",
      "spot_y" or "spot_xy" (x and y separately), "wavefront" (OPD in waves),
      "angular" / "angular_x" / "angular_y" / "angular_xy" (image-space ray
      angles in radians, for afocal systems) or "mtf" (1 - average MTF at
      ``frequency`` cycles per lens unit; RMS only).  ``component`` overrides
      the suffix ("radial", "x", "y", "xy").
    * ``reference``: "centroid", "chief" (ray) or "unreferenced" (spot: the
      image-surface origin; wavefront: OPD as traced, nothing removed).
    * Pupil integration: ``pupil="gaussian"`` (Gaussian quadrature, ``rings``
      x ``arms`` rays) or "rectangular" (``grid`` x ``grid`` array); an
      ``obscuration`` (fraction of the pupil radius) leaves out the centre.
    * ``symmetric``: True assumes symmetry about the y-z plane (half pupil),
      False samples the whole pupil, None decides at each evaluation.
    * ``delete_vignetted``: True leaves out rays that surface apertures stop
      (the usual choice); False traces every ray ignoring apertures.
    * ``field_weighting`` / ``wavelength_weighting``: "system" (the weights in
      the Fields / Wavelengths dialogs) or "equal".  ``fields`` /
      ``wavelengths`` choose a subset (indices).  ``weight`` scales every
      image-quality row.

    Boundaries: ``glass_min`` / ``glass_max`` / ``glass_edge`` /
    ``glass_max_edge`` and the ``air_...`` equivalents add MNCG / MXCG / MNEG
    / MXEG / MNCA / MXCA / MNEA / MXEA rows of weight ``boundary_weight`` over
    ``boundary_surfaces=(first, last)`` (default: all surfaces).

    For a multi-configuration lens the image-quality rows are repeated for
    every configuration (or those listed in ``configs``), each group headed by
    a ``CONF`` row and scaled by its ``config_weights`` entry; pass
    ``configs=[]`` for the current configuration only.  Boundary rows apply
    to the configuration the lens shows.

    The options are kept in the result's :attr:`MeritFunction.wizard` (and
    saved with the lens).  :func:`apply_default_merit` also handles the rows
    the lens already has.
    """
    opts = {k: v for k, v in locals().items() if k != "system"}
    for k in ("fields", "wavelengths", "configs", "config_weights", "boundary_surfaces"):
        if opts[k] is not None:
            opts[k] = list(opts[k])
    defaults = {k: p.default for k, p in inspect.signature(default_merit).parameters.items()}
    opts = {k: v for k, v in opts.items() if k == "kind" or v != defaults[k]}  # what differs from the defaults
    kind = kind.lower()
    if kind not in CRITERIA:
        raise ValueError("kind must be one of " + ", ".join(repr(k) for k in CRITERIA))
    base, _, suffix = kind.partition("_")
    comp = component or {"": "radial", "x": "x", "y": "y", "xy": "xy"}[suffix]
    if comp not in ("radial", "x", "y", "xy"):
        raise ValueError("component must be 'radial', 'x', 'y' or 'xy'")
    if optimization not in OPTIMIZATION_TYPES:
        raise ValueError("optimization must be 'rms' or 'ptv'")
    if reference not in REFERENCES:
        raise ValueError("reference must be 'centroid', 'chief' or 'unreferenced'")
    if pupil not in PUPILS:
        raise ValueError("pupil must be 'gaussian' or 'rectangular'")
    if not 0.0 <= obscuration < 1.0:
        raise ValueError("obscuration must be in [0, 1)")
    if field_weighting not in ("system", "equal") or wavelength_weighting not in ("system", "equal"):
        raise ValueError("field_weighting and wavelength_weighting must be 'system' or 'equal'")
    if base == "mtf" and frequency is None:
        raise ValueError("kind='mtf' needs a frequency (cycles per lens unit)")
    block = {"kind": base, "frequency": frequency, "fields": fields, "field_weighting": field_weighting,
             "weight": float(weight), "params": {}}
    if base != "mtf":
        p = {"reference": reference, "wavelengths": None if wavelengths is None else list(wavelengths),
             "symmetric": symmetric}
        if pupil == "gaussian":
            p.update(rings=int(rings), arms=int(arms))
        else:
            p.update(pupil="rectangular", grid=int(grid))
        if obscuration:
            p["obscuration"] = float(obscuration)
        if base != "wavefront" and comp != "radial":
            p["component"] = comp
        if optimization != "rms":
            p["mode"] = optimization
        if not delete_vignetted:
            p["apertures"] = False
        if wavelength_weighting == "equal":
            p["equal_waves"] = True
        block["params"] = p
    mf = MeritFunction()
    sym = symmetric  # None: decided at each evaluation, so perturbed copies stay correct
    samp = f"{rings} rings x {arms} arms" if pupil == "gaussian" else f"{grid} x {grid} grid"
    if obscuration:
        samp += f", obscuration {obscuration:g}"
    label = CRITERIA[kind][1] if component is None else f"{CRITERIA[base][1].split()[0]} {comp}"
    head = (f"Default merit: {label}, {frequency:g} cycles" if base == "mtf" else
            f"Default merit: {optimization.upper()} {label}, {reference}, {samp}")
    mf.add("BLNK", weight=0, comment=head)
    rng = {}
    if boundary_surfaces is not None:
        a, b = boundary_surfaces
        rng = {"surf": int(a), "surf2": int(b)}
    for vals, ops in (((glass_min, glass_max, glass_edge, glass_max_edge), ("MNCG", "MXCG", "MNEG", "MXEG")),
                      ((air_min, air_max, air_edge, air_max_edge), ("MNCA", "MXCA", "MNEA", "MXEA"))):
        for v, op in zip(vals, ops):
            if v is not None:
                mf.add(op, float(v), boundary_weight, **rng)
    mc = getattr(system, "multiconfig", None)
    if configs is None:
        configs = list(mc.configs) if mc is not None and mc.n_configs > 1 else []
    configs = list(configs)
    if configs and mc is None:
        raise ValueError("configs given, but the lens has no multi-configuration table")
    cw = [1.0] * len(configs) if config_weights is None else [float(w) for w in config_weights]
    if len(cw) != len(configs):
        raise ValueError("give one config weight per configuration")
    for k, w in zip(configs, cw):
        mf.add("CONF", weight=0, cfg=int(k), comment=mc.name(int(k)))
        _image_quality_rows(mf, system.config_copy(int(k)), block, sym, w)
    if not configs:
        _image_quality_rows(mf, system, block, sym, 1.0)
    mf.wizard = opts
    return mf


def _image_quality_rows(mf, system, block, sym, scale):
    fields = block["fields"]
    idx = range(len(system.fields)) if fields is None else fields
    op = {"spot": "RAYS", "wavefront": "OPDS", "angular": "ANGS"}.get(block["kind"])
    for i in idx:
        fw = system.fields[i].weight
        if block["field_weighting"] == "system" and fw <= 0:
            continue
        w = (fw if block["field_weighting"] == "system" else 1.0) * scale * block["weight"]
        if w <= 0:
            continue
        if block["kind"] == "mtf":
            mf.add("MTFA", 1.0, w, freq=block["frequency"], field=i)
        else:
            p = dict(block["params"])
            p["symmetric"] = sym
            mf.add(op, 0.0, w, field=i, **p)


def apply_default_merit(system, start_at: Optional[int] = None, keep: bool = True, **options) -> MeritFunction:
    """Build :func:`default_merit` (``options``) and attach it to ``system``.

    ``start_at`` (row index from 0): keep the lens's rows above it and replace
    everything from that row on by the default rows.  Otherwise, with ``keep``
    the lens's own rows (those :func:`is_default_row` does not recognise) stay
    above the new default rows, and without it the merit function is replaced.
    Re-run with the same settings as ``apply_default_merit(lens, **lens.merit_function.wizard)``.
    """
    new = default_merit(system, **options)
    old = getattr(system, "merit_function", None)
    if old is not None:
        if start_at is not None:
            new.rows = old.rows[:max(0, int(start_at))] + new.rows
        elif keep:
            new.rows = [r for r in old.rows if not is_default_row(r)] + new.rows
    new.wizard = dict(new.wizard, start_at=None if start_at is None else int(start_at), keep=bool(keep))
    system.merit_function = new
    return new


def operand_help(name: Optional[str] = None) -> str:
    """Description of one operand, or a table of all of them."""
    if name:
        return f"{name.upper()}: {OPERAND_INFO[name.upper()]}"
    return "\n".join(f"{k:5} {v}" for k, v in sorted(OPERAND_INFO.items()))
