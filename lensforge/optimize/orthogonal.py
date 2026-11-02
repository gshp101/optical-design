"""Orthogonal descent: a derivative-free local optimiser.

Damped least squares needs the derivative of every merit row with respect to
every variable, which it takes by finite differences with tiny steps.  When
the merit function is noisy or jumpy (rays that hit or miss an aperture,
Monte Carlo or grid-sampled non-sequential traces, detector pixels), those
derivatives are garbage and DLS stalls.  Orthogonal descent never takes a
derivative.  It works in scaled variable space with a set of orthonormal
search directions (at first one per variable) and, each cycle:

1. searches along each direction in turn: a trial step either way, expanded
   while it keeps improving, then a parabola through the three best points
   bracketing the minimum (steps are clipped to the variable bounds);
2. rotates the directions (Rosenbrock's method, with Palmer's
   orthonormalisation): the first new direction is the net move of the
   cycle and the others are orthonormalised from what is left of it (QR), so
   the directions turn to follow long, curved valleys;
3. adapts each direction's trial step: a successful search keeps the step it
   found, a failed one shrinks it by 4x.

The steps it compares are many times larger than DLS's finite-difference
steps, so ray-count noise and small discontinuities do not mislead it.  It
stops after ``cycles`` cycles, when the relative decrease of the merit stays
below ``tol`` for two cycles, or when every trial step has shrunk below
``min_step`` (in units of the variable scales).

Hard constraints (rows with negative weight) are handled with a quadratic
penalty that is stiffened until they are met to ``constraint_tol``; DLS meets
them exactly with Lagrange multipliers, so use a solve or DLS for constraints
that must hold to many digits.

Two entry points:

* :func:`orthogonal_descent` optimises a lens in place against a
  :class:`~lensforge.optimize.merit.MeritFunction` (including the
  non-sequential operands NSDP / NSRR) or any function ``f(system) -> float``,
  and returns the same :class:`~lensforge.optimize.dls.OptimizationResult` as
  :func:`~lensforge.optimize.dls.optimize`.
* :func:`minimize_od` minimises any ``f(x) -> float`` of a plain vector, e.g.
  the positions of objects in a :class:`~lensforge.nonseq.NonSequentialSystem`.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field as dc_field
from typing import Callable, List, Optional, Sequence

import numpy as np

from .dls import OptimizationResult, _Problem, check_mc_conflicts
from .merit import MeritFunction
from .solves import apply_solves
from .variables import VariableSet, variables as _system_variables

_GROW = 2.0
_SHRINK = 0.25


@dataclass
class ODResult:
    """Result of :func:`minimize_od`."""

    x: np.ndarray
    fun: float
    initial_fun: float
    cycles: int
    evaluations: int
    message: str
    history: List[float] = dc_field(default_factory=list)
    seconds: float = 0.0
    directions: Optional[np.ndarray] = None
    steps: Optional[np.ndarray] = None

    def __repr__(self):
        return (f"ODResult(f {self.initial_fun:.6g} -> {self.fun:.6g}, {self.cycles} cycles, "
                f"{self.evaluations} evaluations, {self.seconds:.2f} s: {self.message})")


def _parabola_min(t, f):
    """Vertex of the parabola through three (t, f) points, or None if it opens downwards."""
    (a, b, c), (fa, fb, fc) = t, f
    den = (b - a) * (fb - fc) - (b - c) * (fb - fa)
    if den == 0 or not all(map(math.isfinite, (fa, fb, fc))):
        return None
    num = (b - a) ** 2 * (fb - fc) - (b - c) ** 2 * (fb - fa)
    curv = (fa - fb) / (a - b) - (fb - fc) / (b - c) if a != b and b != c else 0.0
    if curv / (a - c) <= 0:
        return None
    return b - 0.5 * num / den


class _Search:
    def __init__(self, fun, x0, lo, hi, scale):
        self.fun, self.x0, self.lo, self.hi, self.scale = fun, x0, lo, hi, scale
        self.evaluations = 0

    def x(self, u):
        return np.clip(self.x0 + self.scale * u, self.lo, self.hi)

    def f(self, u):
        self.evaluations += 1
        with np.errstate(all="ignore"):
            try:
                v = float(self.fun(self.x(u)))
            except (ValueError, ZeroDivisionError, FloatingPointError, ArithmeticError):
                return math.inf
        return v if math.isfinite(v) else math.inf

    def t_range(self, u, d):
        """Interval of t for which u + t d stays inside the bounds."""
        x = self.x0 + self.scale * u
        p = self.scale * d
        tmin, tmax = -math.inf, math.inf
        for xi, pi, l, h in zip(x, p, self.lo, self.hi):
            if abs(pi) < 1e-300:
                continue
            a, b = (l - xi) / pi, (h - xi) / pi
            if a > b:
                a, b = b, a
            tmin, tmax = max(tmin, a), min(tmax, b)
        return min(tmin, 0.0), max(tmax, 0.0)

    def line(self, u, f0, d, delta):
        """Minimise along direction d from u (value f0).  Returns (t, f)."""
        tmin, tmax = self.t_range(u, d)
        clamp = lambda t: min(max(t, tmin), tmax)  # noqa: E731
        side = {}
        for sgn in (1.0, -1.0):
            t1 = clamp(sgn * delta)
            if t1 == 0.0:
                continue
            f1 = self.f(u + t1 * d)
            side[sgn] = (t1, f1)
            if f1 < f0:
                ts, fs = [0.0, t1], [f0, f1]
                while True:
                    t2 = clamp(ts[-1] + _GROW * (ts[-1] - ts[-2]))
                    if t2 == ts[-1]:
                        return ts[-1], fs[-1]          # at a bound and still improving
                    f2 = self.f(u + t2 * d)
                    ts.append(t2)
                    fs.append(f2)
                    if f2 >= fs[-2]:
                        break
                tv = _parabola_min(ts[-3:], fs[-3:])
                tb, fb = ts[-2], fs[-2]
                if tv is not None and min(ts[-3], ts[-1]) < tv < max(ts[-3], ts[-1]) and tv != tb:
                    fv = self.f(u + tv * d)
                    if fv < fb:
                        return tv, fv
                return tb, fb
        # neither trial step improved: the minimum lies between them (or the step is too large)
        if 1.0 in side and -1.0 in side:
            (tp, fp), (tm, fm) = side[1.0], side[-1.0]
            tv = _parabola_min((tm, 0.0, tp), (fm, f0, fp))
            if tv is not None and tm < tv < tp and tv != 0.0:
                fv = self.f(u + tv * d)
                if fv < f0:
                    return tv, fv
        return 0.0, f0


def minimize_od(fun: Callable[[np.ndarray], float], x0: Sequence[float], lo=None, hi=None, scale=None,
                cycles: int = 50, tol: float = 1e-7, min_step: float = 1e-6, step: float = 1.0,
                directions: Optional[np.ndarray] = None, steps: Optional[np.ndarray] = None,
                callback: Optional[Callable] = None, verbose: bool = False) -> ODResult:
    """Minimise ``fun(x)`` by orthogonal descent, without derivatives.

    ``lo`` / ``hi`` are optional bounds (arrays, ``-inf`` / ``inf`` for none)
    and ``scale`` the typical size of a useful change of each variable (the
    first trial step is ``step * scale``; default 10% of each value or of its
    bounded range).  ``fun`` may return ``inf`` (or raise ValueError) where it
    cannot be evaluated.  ``callback(cycle, f, x)`` is called after each
    cycle; returning True stops.  ``directions`` / ``steps`` from a previous
    result continue a run where it left off.
    """
    t0 = time.time()
    x0 = np.asarray(x0, float).copy()
    n = x0.size
    if n == 0:
        raise ValueError("No variables")
    lo = np.full(n, -np.inf) if lo is None else np.asarray(lo, float)
    hi = np.full(n, np.inf) if hi is None else np.asarray(hi, float)
    x0 = np.clip(x0, lo, hi)
    if scale is None:
        finite = np.isfinite(lo) & np.isfinite(hi)
        scale = np.where(finite, 0.1 * (hi - lo), np.maximum(0.1 * np.abs(x0), 1e-3))
    scale = np.where(np.asarray(scale, float) > 0, np.asarray(scale, float), 1.0)
    S = _Search(fun, x0, lo, hi, scale)
    u = np.zeros(n)
    f = S.f(u)
    if not math.isfinite(f):
        raise RuntimeError("The function cannot be evaluated at the starting point")
    initial = f
    D = np.eye(n) if directions is None else np.array(directions, float)
    delta = np.full(n, float(step)) if steps is None else np.array(steps, float)
    history = [f]
    msg = "maximum cycles reached"
    stall = 0
    cyc = 0
    for cyc in range(1, cycles + 1):
        u_start, f_start = u.copy(), f
        lam = np.zeros(n)
        for k in range(n):
            t, fn = S.line(u, f, D[:, k], delta[k])
            if fn < f and t != 0.0:
                lam[k] = t
                u = u + t * D[:, k]
                f = fn
                delta[k] = max(abs(t), _SHRINK * delta[k])
            else:
                delta[k] *= _SHRINK
        move = u - u_start
        norm = float(np.linalg.norm(move))
        if n > 1 and norm > 0 and np.count_nonzero(lam) > 1:
            # rotate the directions (Rosenbrock, with Palmer's orthonormalisation): the partial sums
            # A_k = sum_{j >= k} lam_j d_j are orthonormalised in order, so the first new direction is
            # the net move of the cycle and the others span what is left
            Ds, ls, dl = D, lam, delta.copy()
            A = np.cumsum((Ds * ls)[:, ::-1], axis=1)[:, ::-1]
            moved = ls != 0
            A[:, ~moved] = Ds[:, ~moved]
            Q, R = np.linalg.qr(A)
            Q = Q * np.where(np.diag(R) < 0, -1.0, 1.0)
            D = Q
            dl[moved] = np.maximum(np.abs(ls[moved]), dl[moved])
            delta = dl
        history.append(f)
        if verbose:
            print(f"OD cycle {cyc:3d}: f {f:.8g}  largest step {delta.max():.3g}")
        if callback is not None and callback(cyc, f, S.x(u)):
            msg = "stopped by callback"
            break
        if f == 0.0:
            msg = "function is zero"
            break
        if delta.max() < min_step:
            msg = "converged (steps below min_step)"
            break
        rel = (f_start - f) / abs(f_start) if f_start != 0 else 0.0
        stall = stall + 1 if rel < tol else 0
        if stall >= 2:
            msg = "converged"
            break
    return ODResult(S.x(u), f, initial, cyc, S.evaluations, msg, history, time.time() - t0, D, delta)


def _scales(system, vs: VariableSet, x):
    lo, hi = vs.bounds()
    st = vs.steps(system)
    s = np.maximum(0.05 * np.abs(x), 1e3 * st)
    finite = np.isfinite(lo) & np.isfinite(hi)
    return np.where(finite, np.minimum(s, 0.1 * (hi - lo)), s)


def orthogonal_descent(system, merit, variables: Optional[VariableSet] = None, cycles: int = 50,
                       tol: float = 1e-7, min_step: float = 1e-5, step: float = 1.0,
                       constraint_tol: float = 1e-6, callback: Optional[Callable] = None,
                       verbose: bool = False) -> OptimizationResult:
    """Optimise ``system`` in place with orthogonal descent (no derivatives).

    ``merit`` is a :class:`MeritFunction` or any function ``f(system) ->
    float`` to minimise as returned (it may be negative, e.g. minus the
    detected power; it is called after the solves are applied and may return
    ``inf`` where it cannot be evaluated).  ``variables`` defaults to
    ``system.variables``.  The first trial step of each variable is ``step``
    times its scale (5% of its value or 1000 finite-difference steps, at most
    10% of a bounded range).  ``callback(cycle, merit, x)`` is called after
    each cycle; returning True stops.  Returns an :class:`OptimizationResult`
    like :func:`~lensforge.optimize.optimize`.
    """
    t0 = time.time()
    vs = VariableSet(variables if variables is not None else _system_variables(system))
    if not vs:
        raise ValueError("No variables: use lensforge.optimize.set_variable(system, surface, param)")
    check_mc_conflicts(system, vs)
    lo, hi = vs.bounds()
    x0 = np.clip(vs.values(system), lo, hi)
    scale = _scales(system, vs, x0)
    is_mf = isinstance(merit, MeritFunction)
    counter = [0]

    if is_mf:
        merit.auto_weight()
        prob = _Problem(system, merit, vs)

        def parts(x):
            """(sum of squared soft residuals, sum of squared hard-constraint errors)"""
            r, c = prob.evaluate(x)
            if r is None:
                return math.inf, math.inf
            return float(r @ r), float(c @ c)

        def reported(x):
            return math.sqrt(parts(x)[0])
    else:
        def value(x):
            vs.apply(system, x)
            counter[0] += 1
            try:
                apply_solves(system)
                with np.errstate(all="ignore"):
                    v = float(merit(system))
            except (ValueError, ZeroDivisionError, FloatingPointError, ArithmeticError):
                return math.inf
            return v if math.isfinite(v) else math.inf

        def parts(x):
            return value(x), 0.0

        reported = value

    f0, c0 = parts(x0)
    if not math.isfinite(f0):
        err = merit.evaluate(system).error if is_mf else "the function returned inf or raised"
        raise RuntimeError(f"Merit function cannot be evaluated for the starting design ({err})")
    hard = is_mf and any(r.hard for r in merit)
    # quadratic penalty on the hard constraints, stiffened 100x per round until they are met: it
    # starts soft (the starting constraint error, or 0.1% of the targets, costs as much as the
    # merit) so that the optimiser can still move along the constraints
    if hard:
        tscale = max([abs(r.target) for r in merit if r.hard] + [1.0])
        mu = max(f0, 1e-12) / max(c0, (1e-3 * tscale) ** 2)
    else:
        mu = 0.0
    initial = reported(x0)
    history = [initial]
    done = [0, False]  # cycles finished in earlier rounds, stopped by the callback

    def cb(k, _f, xc):
        m = reported(xc)
        history.append(m)
        if verbose:
            print(f"OD cycle {done[0] + k:3d}: merit {m:.8g}")
        if callback is not None and callback(done[0] + k, m, xc.copy()):
            done[1] = True
            return True
        return False

    x, D, steps = x0, None, None
    evaluations = 0
    msg = "maximum cycles reached"
    while done[0] < cycles:
        fun = (lambda xx, mu=mu: (lambda a, b: a + mu * b)(*parts(xx))) if hard else (lambda xx: parts(xx)[0])
        res = minimize_od(fun, x, lo, hi, scale, cycles=cycles - done[0], tol=tol, min_step=min_step,
                          step=step, directions=D, steps=steps, callback=cb)
        x, D = res.x, res.directions
        steps = np.maximum(res.steps, 16 * min_step)
        done[0] += res.cycles
        evaluations += res.evaluations
        msg = res.message
        if done[1] or not hard or math.sqrt(parts(x)[1]) <= constraint_tol:
            break
        mu *= 100.0
        if mu > 1e40:
            msg = "hard constraints could not be met"
            break
    _, cc = parts(x)
    final = reported(x)
    if is_mf:
        prob.evaluate(x)
    if hard and math.sqrt(cc) > constraint_tol and msg != "stopped by callback":
        msg += f"; hard constraints not met (error {math.sqrt(cc):.3g})"
    return OptimizationResult(system, final, initial, x, vs.names(), done[0], evaluations,
                              math.sqrt(cc) if math.isfinite(cc) else math.inf, msg, history, time.time() - t0)
