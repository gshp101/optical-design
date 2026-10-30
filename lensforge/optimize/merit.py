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

    def __init__(self, rows: Sequence[Operand] = ()):
        self.rows: List[Operand] = list(rows)

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
                              for r in self.rows])

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
        return {"rows": [r.to_dict() for r in self.rows]}

    @classmethod
    def from_dict(cls, d):
        mf = cls([Operand(r["type"], r.get("target", 0.0), r.get("weight", 1.0), r.get("bound"),
                          dict(r.get("params", {})), r.get("comment", "")) for r in d["rows"]])
        mf.auto_weight()
        return mf

    def __repr__(self):
        return f"MeritFunction({len(self.rows)} rows)"


def default_merit(system, kind: str = "spot", reference: str = "centroid", rings: int = 3, arms: int = 6,
                  frequency: Optional[float] = None, fields: Optional[Sequence[int]] = None,
                  wavelengths: Optional[Sequence[int]] = None, symmetric: Optional[bool] = None,
                  glass_min: Optional[float] = None, glass_max: Optional[float] = None,
                  glass_edge: Optional[float] = None, air_min: Optional[float] = None,
                  air_max: Optional[float] = None, air_edge: Optional[float] = None,
                  boundary_weight: float = 1.0, configs: Optional[Sequence[int]] = None,
                  config_weights: Optional[Sequence[float]] = None) -> MeritFunction:
    """Default merit function (the "optimisation wizard").

    ``kind``: "spot" (RMS transverse ray error), "wavefront" (RMS OPD, waves)
    or "mtf" (1 - average MTF at ``frequency`` cycles/mm for each field).
    ``reference``: "centroid" or "chief".  Pupil sampling is Gaussian
    quadrature with ``rings`` x ``arms`` rays per field and wavelength (half
    pupil if the system is symmetric).  Rows are weighted by the field
    weights; wavelength weights are applied inside each block.

    Optional thickness boundaries add MNCG / MXCG / MNEG / MNCA / MXCA / MNEA rows.

    For a multi-configuration lens the image-quality rows are repeated for
    every configuration (or those listed in ``configs``), each group headed by
    a ``CONF`` row and scaled by its ``config_weights`` entry; pass
    ``configs=[]`` for the current configuration only.  Boundary rows apply
    to the configuration the lens shows.
    """
    mf = MeritFunction()
    sym = symmetric  # None: decided at each evaluation, so perturbed copies stay correct
    mf.add("BLNK", weight=0, comment=f"Default merit: {kind}, {reference}, {rings} rings x {arms} arms")
    for k, (lo, hi_t, edge, op_min, op_max, op_edge) in enumerate((
            (glass_min, glass_max, glass_edge, "MNCG", "MXCG", "MNEG"),
            (air_min, air_max, air_edge, "MNCA", "MXCA", "MNEA"))):
        if lo is not None:
            mf.add(op_min, lo, boundary_weight)
        if hi_t is not None:
            mf.add(op_max, hi_t, boundary_weight)
        if edge is not None:
            mf.add(op_edge, edge, boundary_weight)
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
        _image_quality_rows(mf, system.config_copy(int(k)), kind, reference, rings, arms, frequency, fields,
                            wavelengths, sym, w)
    if not configs:
        _image_quality_rows(mf, system, kind, reference, rings, arms, frequency, fields, wavelengths, sym, 1.0)
    return mf


def _image_quality_rows(mf, system, kind, reference, rings, arms, frequency, fields, wavelengths, sym, scale):
    idx = range(len(system.fields)) if fields is None else fields
    for i in idx:
        w = system.fields[i].weight * scale
        if w <= 0:
            continue
        if kind == "spot":
            mf.add("RAYS", 0.0, w, field=i, reference=reference, rings=rings, arms=arms,
                   wavelengths=None if wavelengths is None else list(wavelengths), symmetric=sym)
        elif kind == "wavefront":
            mf.add("OPDS", 0.0, w, field=i, reference=reference, rings=rings, arms=arms,
                   wavelengths=None if wavelengths is None else list(wavelengths), symmetric=sym)
        elif kind == "mtf":
            if frequency is None:
                raise ValueError("kind='mtf' needs a frequency (cycles per mm)")
            mf.add("MTFA", 1.0, w, freq=frequency, field=i)
        else:
            raise ValueError("kind must be 'spot', 'wavefront' or 'mtf'")


def operand_help(name: Optional[str] = None) -> str:
    """Description of one operand, or a table of all of them."""
    if name:
        return f"{name.upper()}: {OPERAND_INFO[name.upper()]}"
    return "\n".join(f"{k:5} {v}" for k, v in sorted(OPERAND_INFO.items()))
