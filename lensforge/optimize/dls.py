"""Damped least squares (Levenberg-Marquardt) local optimisation.

Each cycle builds the Jacobian of the weighted residuals by finite
differences (one ray-trace pass per variable), then solves

    (J^T J + lambda D) dx = -J^T r          (D = diag(J^T J), Marquardt scaling)

subject to the linearised hard constraints ``C dx = -c`` (rows with negative
weight, solved with Lagrange multipliers).  Several damping values are tried
per cycle and the best is kept; variables at their bounds are frozen when the
gradient pushes them outward, and steps are clipped to the bounds.  Solves are
re-applied at every evaluation.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field as dc_field
from typing import Callable, List, Optional

import numpy as np

from .merit import MeritFunction
from .solves import apply_solves
from .variables import VariableSet, variables as _system_variables


@dataclass
class OptimizationResult:
    system: object
    merit: float
    initial_merit: float
    x: np.ndarray
    names: List[str]
    cycles: int
    evaluations: int
    constraint_error: float
    message: str
    history: List[float] = dc_field(default_factory=list)
    seconds: float = 0.0

    @property
    def improvement(self) -> float:
        return 1.0 - self.merit / self.initial_merit if self.initial_merit not in (0.0, math.inf) else 0.0

    def __repr__(self):
        return (f"OptimizationResult(merit {self.initial_merit:.6g} -> {self.merit:.6g}, {self.cycles} cycles, "
                f"{self.evaluations} evaluations, {self.seconds:.2f} s: {self.message})")


class _Problem:
    """Binds a system, variables and merit function into r(x), c(x)."""

    def __init__(self, system, merit: MeritFunction, variables: VariableSet):
        self.system, self.merit, self.vars = system, merit, variables
        self.lo, self.hi = variables.bounds()
        self.evaluations = 0

    def evaluate(self, x):
        self.vars.apply(self.system, x)
        self.evaluations += 1
        try:
            apply_solves(self.system)
        except (ValueError, ZeroDivisionError, FloatingPointError):
            return None, None
        with np.errstate(all="ignore"):
            r, c, ok = self.merit.residuals(self.system)
        if not ok or not np.all(np.isfinite(r)) or not np.all(np.isfinite(c)):
            return None, None
        return r, c

    def jacobian(self, x, r, c, steps):
        n = x.size
        J = np.zeros((r.size, n))
        C = np.zeros((c.size, n))
        for j in range(n):
            h = steps[j]
            for sgn in (1.0, -1.0):
                xp = x.copy()
                xp[j] += sgn * h
                if xp[j] > self.hi[j] or xp[j] < self.lo[j]:
                    continue
                rp, cp = self.evaluate(xp)
                if rp is not None:
                    J[:, j] = (rp - r) / (sgn * h)
                    C[:, j] = (cp - c) / (sgn * h)
                    break
        self.vars.apply(self.system, x)
        return J, C


def _step(J, r, C, c, lam, free):
    A = J[:, free].T @ J[:, free]
    g = J[:, free].T @ r
    d = np.diag(A).copy()
    dmax = d.max() if d.size and d.max() > 0 else 1.0
    d = np.maximum(d, 1e-9 * dmax)
    H = A + lam * np.diag(d)
    nf = int(free.sum())
    dx = np.zeros(free.size)
    Cf = C[:, free]
    active = np.any(Cf != 0, axis=1) | (c != 0)
    if active.any():
        Ca, ca = Cf[active], c[active]
        m = Ca.shape[0]
        K = np.zeros((nf + m, nf + m))
        K[:nf, :nf] = H
        K[:nf, nf:] = Ca.T
        K[nf:, :nf] = Ca
        sol, *_ = np.linalg.lstsq(K, np.concatenate([-g, -ca]), rcond=None)
        dx[free] = sol[:nf]
    else:
        try:
            dx[free] = np.linalg.solve(H, -g)
        except np.linalg.LinAlgError:
            dx[free], *_ = np.linalg.lstsq(H, -g, rcond=None)
    return dx


def optimize(system, merit: MeritFunction, variables: Optional[VariableSet] = None, cycles: int = 50,
             tol: float = 1e-7, damping: float = 1e-3, constraint_tol: float = 1e-9,
             callback: Optional[Callable] = None, verbose: bool = False) -> OptimizationResult:
    """Optimise ``system`` in place with damped least squares.

    ``variables`` defaults to ``system.variables``.  Stops after ``cycles``
    cycles, when the relative decrease of MF^2 stays below ``tol`` for three
    cycles (with hard constraints satisfied to ``constraint_tol``), or when no
    damping value improves the design.  ``callback(cycle, merit, x)`` is
    called after each cycle; returning True stops early.
    """
    t0 = time.time()
    vs = VariableSet(variables if variables is not None else _system_variables(system))
    if not vs:
        raise ValueError("No variables: use lensforge.optimize.set_variable(system, surface, param)")
    weightless = merit.problem() if isinstance(merit, MeritFunction) else None
    if weightless:
        raise ValueError(weightless)
    prob = _Problem(system, merit, vs)
    x = np.clip(vs.values(system), prob.lo, prob.hi)
    r, c = prob.evaluate(x)
    if r is None:
        raise RuntimeError("Merit function cannot be evaluated for the starting design "
                           f"({merit.evaluate(system).error})")
    steps = vs.steps(system)
    f = float(r @ r)
    cn = float(np.sqrt(c @ c)) if c.size else 0.0
    initial = math.sqrt(f)
    history = [initial]
    lam = damping
    stall = 0
    msg = "maximum cycles reached"
    cyc = 0
    for cyc in range(1, cycles + 1):
        J, C = prob.jacobian(x, r, c, steps)
        g = J.T @ r
        at_lo = (x <= prob.lo) & (g > 0)
        at_hi = (x >= prob.hi) & (g < 0)
        free = ~(at_lo | at_hi) & (np.any(J != 0, axis=0) | np.any(C != 0, axis=0))
        if not free.any():
            msg = "no free variables (all at bounds or without effect)"
            break
        Cpinv = None
        if C.size and np.any(C[:, free]):
            Cpinv = np.zeros((x.size, C.shape[0]))
            Cpinv[free] = np.linalg.pinv(C[:, free])
        def trial(xn, lt):
            rn, cv = prob.evaluate(np.clip(xn, prob.lo, prob.hi))
            if rn is None:
                return None
            xn = np.clip(xn, prob.lo, prob.hi)
            cnn = float(np.sqrt(cv @ cv)) if cv.size else 0.0
            # second-order correction: pull the trial point back onto the hard constraints
            for _ in range(3 if Cpinv is not None else 0):
                if cnn <= constraint_tol:
                    break
                xc = np.clip(xn - Cpinv @ cv, prob.lo, prob.hi)
                rc, cc = prob.evaluate(xc)
                if rc is None:
                    break
                ccn = float(np.sqrt(cc @ cc))
                if ccn >= cnn:
                    break
                xn, rn, cv, cnn = xc, rc, cc, ccn
            fn = float(rn @ rn)
            if not ((fn < f and cnn <= max(cn * (1 + 1e-6), constraint_tol)) or cnn < 0.9 * cn):
                return None
            return (xn, rn, cv, fn, cnn, lt, (0, fn) if cnn <= constraint_tol else (1, cnn))

        best = None
        for attempt in range(8):
            for lt in (lam * 0.1, lam, lam * 10):
                dx = _step(J, r, C, c, lt, free)
                # shorten the step when the (linearised) constraints are far from satisfied
                for alpha in ((1.0, 0.5, 0.25, 0.1) if cn > constraint_tol else (1.0,)):
                    t = trial(x + alpha * dx, lt)
                    if t is not None:
                        if best is None or t[6] < best[6]:
                            best = t
                        break
            if best is not None:
                break
            lam *= 100.0
        if best is None:
            msg = "converged (no improving step)"
            prob.evaluate(x)
            break
        xn, rn, cn_vec, fn, cnn, lam, _ = best
        lam = max(lam, 1e-12)
        rel = (f - fn) / f if f > 0 else 0.0
        x, r, c, f, cn = xn, rn, cn_vec, fn, cnn
        history.append(math.sqrt(f))
        if verbose:
            print(f"cycle {cyc:3d}: merit {math.sqrt(f):.8g}  constraints {cn:.3g}  damping {lam:.3g}")
        if callback is not None and callback(cyc, math.sqrt(f), x.copy()):
            msg = "stopped by callback"
            break
        stall = stall + 1 if (rel < tol and cn <= constraint_tol) else 0
        if stall >= 2:
            msg = "converged"
            break
        if f == 0.0 and cn <= constraint_tol:
            msg = "merit function is zero"
            break
    prob.evaluate(x)
    return OptimizationResult(system, math.sqrt(f), initial, x, vs.names(), cyc, prob.evaluations, cn, msg,
                              history, time.time() - t0)


def merit_value(system, merit: MeritFunction) -> float:
    """Merit value after applying the system's solves (like pressing "update")."""
    apply_solves(system)
    return merit.value(system)
