"""Global optimisation: multi-start global search and the "hammer".

Both drive the damped-least-squares optimiser from many starting points:

* :func:`global_search` samples starting designs across the variable ranges
  (Latin hypercube), optimises each locally and keeps the best distinct
  designs, which is useful for finding different solution families.
* :func:`hammer` repeatedly perturbs the current best design (and optionally
  swaps glasses), re-optimises, and keeps any improvement: a tool for
  escaping a local minimum near a good design.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field as dc_field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from .dls import optimize
from .merit import MeritFunction
from .solves import apply_solves
from .variables import VariableSet, variables as _system_variables


def snapshot(system):
    """Copy of the lens data (surfaces and solves), restorable with :func:`restore`."""
    return [s.copy() for s in system.surfaces]


def restore(system, snap):
    system.surfaces = [s.copy() for s in snap]


@dataclass
class GlobalResult:
    system: object
    merit: float
    initial_merit: float
    designs: List[Tuple[float, object]] = dc_field(default_factory=list)
    trials: int = 0
    improvements: int = 0
    history: List[float] = dc_field(default_factory=list)
    seconds: float = 0.0

    def __repr__(self):
        return (f"GlobalResult(merit {self.initial_merit:.6g} -> {self.merit:.6g}, {self.trials} trials, "
                f"{self.improvements} improvements, {len(self.designs)} designs kept, {self.seconds:.1f} s)")


def _spreads(system, vs: VariableSet, scale: float):
    lo, hi = vs.bounds()
    x = vs.values(system)
    st = vs.steps(system)
    s = np.maximum(0.2 * np.abs(x), 1e5 * st)
    finite = np.isfinite(lo) & np.isfinite(hi)
    s = np.where(finite, 0.1 * (hi - lo), s)
    return s * scale


def _merit_or_inf(system, merit):
    try:
        apply_solves(system)
    except (ValueError, ZeroDivisionError):
        return math.inf
    with np.errstate(all="ignore"):
        return merit.value(system)


def _local(system, merit, vs, cycles):
    try:
        return optimize(system, merit, vs, cycles=cycles).merit
    except RuntimeError:
        return math.inf


def _glass_specs(glasses):
    return {int(k): list(v) for k, v in (glasses or {}).items()}


def hammer(system, merit: MeritFunction, variables: Optional[VariableSet] = None, trials: int = 50,
           time_limit: Optional[float] = None, cycles: int = 20, scale: float = 1.0, seed: int = 0,
           glasses: Optional[Dict[int, Sequence[str]]] = None, glass_probability: float = 0.3,
           verbose: bool = False) -> GlobalResult:
    """Hammer optimisation of ``system`` in place.

    Each trial perturbs a random subset of the variables (Gaussian, about 20%
    of each value or 10% of its bounded range, times ``scale``), optionally
    replaces the glass of one surface in ``glasses`` (mapping surface ->
    candidate glass names) and re-optimises with ``cycles`` DLS cycles.
    Improvements are kept.  Runs ``trials`` trials or until ``time_limit``
    seconds.
    """
    t0 = time.time()
    rng = np.random.default_rng(seed)
    vs = VariableSet(variables if variables is not None else _system_variables(system))
    gl = _glass_specs(glasses)
    lo, hi = vs.bounds()
    initial = _merit_or_inf(system, merit)
    best = _local(system, merit, vs, cycles)
    if not math.isfinite(best):
        raise RuntimeError("Merit function cannot be evaluated for the starting design")
    best_snap = snapshot(system)
    history = [best]
    improvements = 0
    k = 0
    for k in range(1, trials + 1):
        if time_limit is not None and time.time() - t0 > time_limit:
            k -= 1
            break
        restore(system, best_snap)
        x = vs.values(system)
        sp = _spreads(system, vs, scale * rng.choice([0.25, 0.5, 1.0]))
        mask = rng.random(x.size) < max(1.0 / x.size, rng.random())
        xt = np.clip(x + mask * rng.normal(size=x.size) * sp, lo, hi)
        vs.apply(system, xt)
        if gl and rng.random() < glass_probability:
            surf = int(rng.choice(list(gl)))
            system.surfaces[surf].material = str(rng.choice(gl[surf]))
        if not math.isfinite(_merit_or_inf(system, merit)):
            continue
        m = _local(system, merit, vs, cycles)
        if m < best * (1 - 1e-9):
            best, best_snap = m, snapshot(system)
            improvements += 1
            if verbose:
                print(f"hammer trial {k}: merit {m:.8g}")
        history.append(best)
    restore(system, best_snap)
    apply_solves(system)
    return GlobalResult(system, best, initial, [(best, system.copy())], k, improvements, history, time.time() - t0)


def _latin_hypercube(rng, n, d):
    u = (rng.permuted(np.tile(np.arange(n), (d, 1)), axis=1).T + rng.random((n, d))) / n
    return u


def global_search(system, merit: MeritFunction, variables: Optional[VariableSet] = None, starts: int = 20,
                  keep: int = 5, cycles: int = 30, spread: float = 1.0, seed: int = 0,
                  glasses: Optional[Dict[int, Sequence[str]]] = None, time_limit: Optional[float] = None,
                  verbose: bool = False) -> GlobalResult:
    """Multi-start global search.  Starting points fill the variable bounds (or,
    for unbounded variables, +-``spread`` x max(|value|, a typical scale)
    around the current value) on a Latin hypercube; glasses in ``glasses`` are
    drawn at random per start.  Each start is optimised with ``cycles`` DLS
    cycles.  The ``keep`` best distinct designs are returned in
    ``result.designs`` (merit, system copy) and the best is loaded into
    ``system``.
    """
    t0 = time.time()
    rng = np.random.default_rng(seed)
    vs = VariableSet(variables if variables is not None else _system_variables(system))
    gl = _glass_specs(glasses)
    lo, hi = vs.bounds()
    x0 = vs.values(system)
    initial = _merit_or_inf(system, merit)
    st = vs.steps(system)
    half = spread * np.maximum(np.abs(x0), 1e5 * st)
    a = np.where(np.isfinite(lo), lo, x0 - half)
    b = np.where(np.isfinite(hi), hi, x0 + half)
    base = snapshot(system)
    designs: List[Tuple[float, object]] = []

    def record(m):
        if not math.isfinite(m):
            return
        for dm, _ in designs:
            if abs(dm - m) <= 1e-6 * max(abs(m), 1e-30):
                return
        designs.append((m, system.copy()))
        designs.sort(key=lambda t: t[0])
        del designs[keep:]

    record(_local(system, merit, vs, cycles))
    history = [designs[0][0] if designs else math.inf]
    U = _latin_hypercube(rng, starts, x0.size)
    n = 0
    for n in range(1, starts + 1):
        if time_limit is not None and time.time() - t0 > time_limit:
            n -= 1
            break
        restore(system, base)
        vs.apply(system, a + U[n - 1] * (b - a))
        for surf, cands in gl.items():
            system.surfaces[surf].material = str(rng.choice(cands))
        if not math.isfinite(_merit_or_inf(system, merit)):
            continue
        m = _local(system, merit, vs, cycles)
        record(m)
        history.append(designs[0][0] if designs else math.inf)
        if verbose:
            print(f"global start {n}: merit {m:.8g}  (best {history[-1]:.8g})")
    if not designs:
        restore(system, base)
        raise RuntimeError("No starting point could be optimised")
    best_m, best_sys = designs[0]
    system.surfaces = [s.copy() for s in best_sys.surfaces]
    apply_solves(system)
    return GlobalResult(system, best_m, initial, designs, n, 0, history, time.time() - t0)
