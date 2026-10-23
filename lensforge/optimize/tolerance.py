"""Tolerancing: sensitivity, inverse sensitivity and Monte Carlo analysis.

Tolerance operands (Zemax names; ``surface`` / ``surface2`` are nominal indices):

==========  =====================================================================
TRAD        radius change (lens units)
TCUR        curvature change
TFRN        power change in fringes at 0.6328 um over the surface semi-diameter
TCON        conic change
TTHI        thickness change (``adjust``: surface whose thickness absorbs it)
TPAR        change of any parameter ``param`` (e.g. "coefficients[0]")
TIND, TABB  refractive index (nd) and Abbe number changes of the glass after the surface
TSDX, TSDY  surface decentre;  TSTX, TSTY surface tilt (degrees, about the vertex)
TEDX, TEDY  element decentre;  TETX, TETY element tilt (surfaces ``surface``..``surface2``)
==========  =====================================================================

Decentres and tilts are modelled the way commercial codes do it: coordinate
breaks are inserted around the surface or element, and a return break after
it restores the nominal coordinate system exactly, so the rest of the lens is
unaffected.  Perturbed systems are copies; their solves are frozen.

The criterion is "rms_spot" (field-weighted RMS spot radius, centroid),
"rms_wavefront" (waves), "mtf" (field-averaged MTF at ``frequency``), a
:class:`~lensforge.optimize.merit.MeritFunction`, or any callable(system).
Compensators (default: back focus) are re-optimised for each perturbed lens.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field as dc_field
from typing import Callable, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np

from .. import surfaces as S
from ..materials import Material
from .dls import optimize
from .merit import MeritFunction, default_merit
from .solves import MarginalRayHeight
from .variables import Variable, VariableSet, get_param, set_param

STRUCTURAL = {"TSDX": "dx", "TSDY": "dy", "TSTX": "tx", "TSTY": "ty",
              "TEDX": "dx", "TEDY": "dy", "TETX": "tx", "TETY": "ty"}
TOLERANCE_TYPES = ("TRAD", "TCUR", "TFRN", "TCON", "TTHI", "TPAR", "TIND", "TABB") + tuple(STRUCTURAL)
TEST_WAVELENGTH = 0.6328  # um, for fringes


class PerturbedMaterial(Material):
    """A material with its d-line index shifted by ``dn`` and Abbe number changed by ``dv``
    (dispersion scaled about the d line)."""

    def __init__(self, base: Material, dn: float = 0.0, dv: float = 0.0):
        self.base, self.dn, self.dv = base, float(dn), float(dv)
        self.name = f"{base.name}{dn:+.2g}n{dv:+.2g}v"
        nd = base.nd
        nf, nc = base.index(0.4861327), base.index(0.6562725)
        vd = (nd - 1) / (nf - nc)
        self._nd = nd
        self._k = ((nd + dn - 1) / (vd + dv)) / (nf - nc)

    def index(self, wavelength_um):
        n = self.base.index(wavelength_um)
        return self._nd + self.dn + (n - self._nd) * self._k

    def to_spec(self):
        return {"model": [self.nd, self.vd, 0.0]}


@dataclass
class Tolerance:
    type: str
    surface: int
    min: float
    max: float
    surface2: Optional[int] = None
    param: Optional[str] = None
    adjust: Optional[int] = None
    comment: str = ""

    def __post_init__(self):
        self.type = self.type.upper()
        if self.type not in TOLERANCE_TYPES:
            raise KeyError(f"Unknown tolerance {self.type!r}; one of {TOLERANCE_TYPES}")
        if self.type.startswith("TE") and self.surface2 is None:
            raise ValueError(f"{self.type} needs surface2 (last surface of the element)")
        if self.type == "TPAR" and not self.param:
            raise ValueError("TPAR needs param")

    def label(self) -> str:
        s = f"{self.type} S{self.surface}" + (f"-{self.surface2}" if self.surface2 is not None else "")
        return s + (f" {self.param}" if self.param else "")

    def __repr__(self):
        return f"Tolerance({self.label()}, {self.min:+g} / {self.max:+g})"


# ---------------------------------------------------------------------------
# Building perturbed systems
# ---------------------------------------------------------------------------

def _semi_diameter(system, i):
    sd = system.surfaces[i].semi_diameter
    if sd:
        return sd
    from .operands import EvalContext
    return float(EvalContext(system).semi_diameters()[i])


def _insert(system, spans, pos, surf):
    system.surfaces.insert(pos, surf)
    for sp in spans.values():
        for k in (0, 1):
            if sp[k] >= pos:
                sp[k] += 1


def _wrap(system, spans, thick, i, j, dx, dy, tx, ty):
    """Decentre / tilt nominal surfaces i..j with an exact coordinate return."""
    L = sum(thick[k] for k in range(i, j))
    T = thick[j]
    start = spans[i][0]
    _insert(system, spans, start, S.CoordinateBreak(decenter_x=dx, decenter_y=dy, tilt_x=tx, tilt_y=ty,
                                                    thickness=0.0, comment=f"tol {i}-{j}"))
    spans[i][0] = start
    end = spans[j][1]
    system.surfaces[end].thickness -= T
    R = S.rotation_matrix(tx, ty, 0.0)
    O = np.array([dx, dy, 0.0]) + R @ np.array([0.0, 0.0, L])
    w = np.array([0.0, 0.0, L]) - O
    _insert(system, spans, end + 1, S.CoordinateBreak(decenter_x=w[0], decenter_y=w[1], tilt_x=-tx, tilt_y=-ty,
                                                      order=1, thickness=T + w[2], comment=f"tol return {i}-{j}"))
    spans[j][1] = end + 1


def perturbed_system(system, perturbations: Sequence[Tuple[Tolerance, float]]):
    """Copy of ``system`` with each (tolerance, value) applied.  Solves are removed
    (frozen).  The copy has ``tolerance_map``: nominal surface -> (surface
    position, position of the surface carrying its thickness)."""
    p = system.copy()
    p.solves = []
    nominal_n = system.num_surfaces
    mats: Dict[int, List[float]] = {}
    struct: Dict[Tuple[int, int], Dict[str, float]] = {}
    for tol, v in perturbations:
        t, i = tol.type, tol.surface
        s = p.surfaces[i]
        if t == "TRAD":
            r = s.radius
            if math.isfinite(r):
                s.curvature = 1.0 / (r + v)
        elif t == "TCUR":
            s.curvature += v
        elif t == "TFRN":
            r = _semi_diameter(system, i)
            s.curvature += v * TEST_WAVELENGTH * system.wavelength_scale / (r * r)
        elif t == "TCON":
            s.conic += v
        elif t == "TTHI":
            s.thickness += v
            if tol.adjust is not None:
                p.surfaces[tol.adjust].thickness -= v
        elif t == "TPAR":
            set_param(p, i, tol.param, get_param(p, i, tol.param) + v)
        elif t in ("TIND", "TABB"):
            m = mats.setdefault(i, [0.0, 0.0])
            m[0 if t == "TIND" else 1] += v
        else:
            j = i if t.startswith("TS") else tol.surface2
            d = struct.setdefault((i, j), {"dx": 0.0, "dy": 0.0, "tx": 0.0, "ty": 0.0})
            d[STRUCTURAL[t]] += v
    for i, (dn, dv) in mats.items():
        base = p.library.resolve(p.surfaces[i].material)
        p.surfaces[i].material = PerturbedMaterial(base, dn, dv)
    thick = [s.thickness for s in p.surfaces]
    spans = {k: [k, k] for k in range(nominal_n)}
    pos = {k: p.surfaces[k] for k in range(nominal_n)}
    for (i, j), d in sorted(struct.items(), key=lambda kv: (kv[0][1] - kv[0][0], -kv[0][0])):
        if any(d.values()):
            _wrap(p, spans, thick, i, j, d["dx"], d["dy"], d["tx"], d["ty"])
    index = {id(s): k for k, s in enumerate(p.surfaces)}
    p.tolerance_map = {k: (index[id(pos[k])], spans[k][1]) for k in range(nominal_n)}
    return p


# ---------------------------------------------------------------------------
# Criteria and compensation
# ---------------------------------------------------------------------------

class Criterion:
    def __init__(self, name: str, fn: Callable, higher_is_better: bool = False,
                 merit: Optional[MeritFunction] = None):
        self.name, self.fn, self.higher_is_better, self.merit = name, fn, higher_is_better, merit

    def __call__(self, system) -> float:
        with np.errstate(all="ignore"):
            try:
                return float(self.fn(system))
            except (RuntimeError, ValueError, ZeroDivisionError):
                return math.nan


def make_criterion(system, criterion: Union[str, MeritFunction, Callable] = "rms_spot",
                   frequency: Optional[float] = None, rings: int = 4, arms: int = 8) -> Criterion:
    if isinstance(criterion, Criterion):
        return criterion
    if isinstance(criterion, MeritFunction):
        return Criterion("merit", criterion.value, False, criterion)
    if callable(criterion):
        return Criterion(getattr(criterion, "__name__", "user"), criterion)
    c = criterion.lower()
    if c == "rms_spot":
        mf = default_merit(system, "spot", rings=rings, arms=arms)
        return Criterion("RMS spot radius", mf.value, False, mf)
    if c == "rms_wavefront":
        mf = default_merit(system, "wavefront", rings=rings, arms=arms)
        return Criterion("RMS wavefront (waves)", mf.value, False, mf)
    if c == "mtf":
        if frequency is None:
            raise ValueError("criterion 'mtf' needs frequency")
        from ..analysis.metrics import mtf_average
        w = np.array([f.weight for f in system.fields], float)

        def avg(s):
            v = [mtf_average(s, frequency, field=k) for k in range(len(s.fields))]
            return float(np.sum(w * v) / w.sum())
        return Criterion(f"MTF at {frequency:g}/mm", avg, True, default_merit(system, "spot", rings=3, arms=6))
    raise ValueError("criterion must be 'rms_spot', 'rms_wavefront', 'mtf', a MeritFunction or a callable")


def _resolve_compensators(system, compensators):
    if compensators is None:
        return []
    if isinstance(compensators, str):
        if compensators not in ("focus", "paraxial_focus"):
            raise ValueError("compensators: 'focus', 'paraxial_focus', None or a list of (surface, param)")
        return compensators
    return [c if isinstance(c, tuple) else (c.surface, c.param) for c in compensators]


def _compensate(p, comps, comp_merit, cycles):
    if not comps:
        return
    last = p.image_index - 1
    if comps == "paraxial_focus":
        MarginalRayHeight(last).apply(p)
        return
    if comps == "focus":
        vs = VariableSet([Variable(last, "thickness")])
    else:
        mp = p.tolerance_map
        vs = VariableSet(Variable(mp[k][1] if param == "thickness" else mp[k][0], param) for k, param in comps)
    try:
        optimize(p, comp_merit, vs, cycles=cycles)
    except RuntimeError:
        pass


class _Runner:
    def __init__(self, system, criterion, compensators, comp_cycles, frequency, comp_merit=None):
        self.system = system
        self.crit = make_criterion(system, criterion, frequency)
        self.comps = _resolve_compensators(system, compensators)
        self.comp_merit = comp_merit or self.crit.merit or default_merit(system, "spot")
        self.cycles = comp_cycles

    def __call__(self, perturbations):
        p = perturbed_system(self.system, perturbations)
        _compensate(p, self.comps, self.comp_merit, self.cycles)
        return self.crit(p), p


# ---------------------------------------------------------------------------
# Default tolerance set
# ---------------------------------------------------------------------------

def elements(system) -> List[Tuple[int, int]]:
    """(first, last) surface of each lens element / cemented group."""
    out, i = [], 1
    lib = system.library

    def glass(k):
        m = lib.resolve(system.surfaces[k].material)
        return not m.is_mirror and m.nd != 1.0 and not system.surfaces[k].is_coordinate_break

    while i < system.image_index:
        if glass(i):
            j = i
            while j + 1 < system.image_index and glass(j + 1):
                j += 1
            out.append((i, j + 1))
            i = j + 2
        else:
            i += 1
    return out


def default_tolerances(system, fringes: float = 2.0, thickness: float = 0.05, surface_decenter: float = 0.01,
                       surface_tilt: float = 0.01, element_decenter: float = 0.02, element_tilt: float = 0.02,
                       index: float = 0.0005, abbe_percent: float = 0.5) -> List[Tolerance]:
    """A tolerance set like a code's default tolerance wizard (values in lens units / degrees):
    power (fringes) on every curved surface, every thickness except the image distance,
    surface and element decentres and tilts, and glass index / Abbe number."""
    tols: List[Tolerance] = []
    lib = system.library
    last = system.image_index - 1
    for i in range(1, system.image_index):
        s = system.surfaces[i]
        if s.is_coordinate_break:
            continue
        if fringes and getattr(s, "curvature", 0.0):
            tols.append(Tolerance("TFRN", i, -fringes, fringes))
        if thickness and i < last:
            tols.append(Tolerance("TTHI", i, -thickness, thickness))
    for i, j in elements(system):
        for k in (i, j):
            if surface_decenter:
                tols += [Tolerance("TSDX", k, -surface_decenter, surface_decenter),
                         Tolerance("TSDY", k, -surface_decenter, surface_decenter)]
            if surface_tilt:
                tols += [Tolerance("TSTX", k, -surface_tilt, surface_tilt),
                         Tolerance("TSTY", k, -surface_tilt, surface_tilt)]
        if element_decenter:
            tols += [Tolerance("TEDX", i, -element_decenter, element_decenter, surface2=j),
                     Tolerance("TEDY", i, -element_decenter, element_decenter, surface2=j)]
        if element_tilt:
            tols += [Tolerance("TETX", i, -element_tilt, element_tilt, surface2=j),
                     Tolerance("TETY", i, -element_tilt, element_tilt, surface2=j)]
        for k in range(i, j):
            if index:
                tols.append(Tolerance("TIND", k, -index, index))
            if abbe_percent:
                vd = lib.resolve(system.surfaces[k].material).vd
                tols.append(Tolerance("TABB", k, -abbe_percent * vd / 100, abbe_percent * vd / 100))
    return tols


# ---------------------------------------------------------------------------
# Analyses
# ---------------------------------------------------------------------------

def _rss(changes, higher):
    return float(math.sqrt(sum(c * c for c in changes)))


def sensitivity_analysis(system, tolerances: Sequence[Tolerance], criterion="rms_spot",
                         compensators="focus", comp_cycles: int = 10, frequency: Optional[float] = None,
                         comp_merit: Optional[MeritFunction] = None) -> dict:
    """Criterion at each tolerance's min and max (others nominal), with compensation.

    Returns a dict with ``nominal``, ``rows`` (per tolerance: min/max values,
    criterion and change at each), ``worst`` (rows sorted by the larger
    degradation) and ``estimated`` (nominal +/- the RSS of the larger change
    of each tolerance, as in the usual sensitivity report).
    """
    t0 = time.time()
    run = _Runner(system, criterion, compensators, comp_cycles, frequency, comp_merit)
    nominal, _ = run([])
    sign = -1.0 if run.crit.higher_is_better else 1.0
    rows = []
    for tol in tolerances:
        cmin, _ = run([(tol, tol.min)])
        cmax, _ = run([(tol, tol.max)])
        rows.append({"tolerance": tol, "label": tol.label(), "min": tol.min, "max": tol.max,
                     "criterion_min": cmin, "criterion_max": cmax,
                     "change_min": cmin - nominal, "change_max": cmax - nominal})
    worst_change = [max(sign * r["change_min"], sign * r["change_max"]) for r in rows]
    order = np.argsort(worst_change)[::-1]
    rss = _rss([max(abs(r["change_min"]), abs(r["change_max"])) for r in rows], run.crit.higher_is_better)
    return {"criterion": run.crit.name, "nominal": nominal, "rows": rows,
            "worst": [rows[k] for k in order], "rss_change": rss,
            "estimated": nominal - rss if run.crit.higher_is_better else nominal + rss,
            "seconds": time.time() - t0}


def sensitivity_table(result: dict, n: Optional[int] = None) -> str:
    rows = result["worst"] if n else result["rows"]
    rows = rows[:n] if n else rows
    out = [f"Criterion: {result['criterion']}   nominal {result['nominal']:.6g}",
           f"{'Tolerance':22} {'Min':>10} {'Crit(min)':>12} {'Max':>10} {'Crit(max)':>12}"]
    for r in rows:
        out.append(f"{r['label']:22} {r['min']:>10.4g} {r['criterion_min']:>12.6g} {r['max']:>10.4g} "
                   f"{r['criterion_max']:>12.6g}")
    out.append(f"Estimated performance (RSS): {result['estimated']:.6g}  (change {result['rss_change']:.4g})")
    return "\n".join(out)


def inverse_sensitivity(system, tolerances: Sequence[Tolerance], max_change: float, criterion="rms_spot",
                        compensators="focus", comp_cycles: int = 10, frequency: Optional[float] = None,
                        max_scale: float = 10.0, iterations: int = 12) -> List[Tolerance]:
    """New tolerance limits for which each tolerance alone degrades the criterion by
    ``max_change`` (bisection on each side, between 0 and ``max_scale`` times the
    current limit).  Returns new :class:`Tolerance` objects."""
    run = _Runner(system, criterion, compensators, comp_cycles, frequency)
    nominal, _ = run([])
    sign = -1.0 if run.crit.higher_is_better else 1.0
    out = []
    for tol in tolerances:
        lims = []
        for lim in (tol.min, tol.max):
            if lim == 0:
                lims.append(0.0)
                continue

            def bad(s):
                v, _ = run([(tol, s * lim)])
                return not (sign * (v - nominal) <= max_change)
            lo, hi = 0.0, max_scale
            if not bad(hi):
                lims.append(hi * lim)
                continue
            for _ in range(iterations):
                mid = 0.5 * (lo + hi)
                if bad(mid):
                    hi = mid
                else:
                    lo = mid
            lims.append(lo * lim)
        out.append(Tolerance(tol.type, tol.surface, lims[0], lims[1], tol.surface2, tol.param, tol.adjust,
                             tol.comment))
    return out


def _sample(rng, lo, hi, distribution):
    if distribution == "uniform":
        return rng.uniform(lo, hi)
    if distribution == "endpoint":
        return lo if rng.random() < 0.5 else hi
    mid, half = 0.5 * (lo + hi), 0.5 * (hi - lo)
    if distribution == "parabolic":
        u = rng.uniform(-1, 1)
        return mid + half * math.copysign(abs(u) ** (1 / 3), u)
    if distribution == "normal":
        for _ in range(100):
            z = rng.normal()
            if abs(z) <= 2:
                return mid + half * z / 2
        return mid
    raise ValueError("distribution must be 'normal', 'uniform', 'parabolic' or 'endpoint'")


@dataclass
class MonteCarloResult:
    criterion: str
    nominal: float
    values: np.ndarray
    samples: np.ndarray            # (trials, n_tolerances) perturbation values
    tolerances: List[Tolerance]
    higher_is_better: bool = False
    best: Optional[object] = None
    worst: Optional[object] = None
    seconds: float = 0.0

    @property
    def mean(self):
        return float(np.nanmean(self.values))

    @property
    def std(self):
        return float(np.nanstd(self.values))

    def percentile(self, q):
        return float(np.nanpercentile(self.values, q))

    def yield_fraction(self, limit: float) -> float:
        """Fraction of trials meeting ``limit`` (<= limit, or >= for higher-is-better criteria)."""
        v = self.values[np.isfinite(self.values)]
        return float(np.mean(v >= limit) if self.higher_is_better else np.mean(v <= limit)) if v.size else 0.0

    def summary(self) -> str:
        qs = (98, 90, 80, 50, 20, 10) if not self.higher_is_better else (2, 10, 20, 50, 80, 90)
        word = "<=" if not self.higher_is_better else ">="
        lines = [f"Monte Carlo: {self.values.size} trials, criterion {self.criterion}",
                 f"  nominal {self.nominal:.6g}   mean {self.mean:.6g}   std {self.std:.4g}   "
                 f"best {np.nanmin(self.values) if not self.higher_is_better else np.nanmax(self.values):.6g}   "
                 f"worst {np.nanmax(self.values) if not self.higher_is_better else np.nanmin(self.values):.6g}"]
        for q in qs:
            frac = q if not self.higher_is_better else 100 - q
            lines.append(f"  {frac:3d}% of lenses {word} {self.percentile(q):.6g}")
        return "\n".join(lines)

    def __repr__(self):
        return (f"MonteCarloResult({self.values.size} trials, nominal {self.nominal:.4g}, mean {self.mean:.4g}, "
                f"std {self.std:.3g})")


def monte_carlo(system, tolerances: Sequence[Tolerance], trials: int = 100, criterion="rms_spot",
                compensators="focus", comp_cycles: int = 10, frequency: Optional[float] = None,
                distribution: str = "normal", seed: int = 0, keep_systems: bool = True,
                comp_merit: Optional[MeritFunction] = None) -> MonteCarloResult:
    """Monte Carlo tolerance analysis: every trial perturbs all tolerances at once,
    drawn from ``distribution`` ("normal": +-2 sigma truncated at the limits,
    "uniform", "parabolic" (weighted to the limits) or "endpoint"), compensates
    and evaluates the criterion.  Seeded for reproducibility."""
    t0 = time.time()
    rng = np.random.default_rng(seed)
    run = _Runner(system, criterion, compensators, comp_cycles, frequency, comp_merit)
    nominal, _ = run([])
    tolerances = list(tolerances)
    samples = np.zeros((trials, len(tolerances)))
    values = np.full(trials, np.nan)
    best = worst = None
    sign = -1.0 if run.crit.higher_is_better else 1.0
    for k in range(trials):
        pert = []
        for j, tol in enumerate(tolerances):
            v = _sample(rng, tol.min, tol.max, distribution)
            samples[k, j] = v
            pert.append((tol, v))
        val, p = run(pert)
        values[k] = val
        if keep_systems and math.isfinite(val):
            if best is None or sign * val < sign * best[0]:
                best = (val, p)
            if worst is None or sign * val > sign * worst[0]:
                worst = (val, p)
    return MonteCarloResult(run.crit.name, nominal, values, samples, tolerances, run.crit.higher_is_better,
                            best[1] if best else None, worst[1] if worst else None, time.time() - t0)
