"""Optimisation and tolerancing runs with Stop and progress reports (pure Python, no Qt).

Shared by the Qt dialogs (opt_dialogs.py) and the web front end (lensforge_web): the merit function
(or tolerance criterion) given to the optimiser checks a stop flag at each evaluation, reports
progress, and the best design seen so far is kept.
"""

from __future__ import annotations

import math
import time

import numpy as np

from lensforge import optimize as opt
from lensforge.optimize.tolerance import Criterion, make_criterion


class StopRequested(Exception):
    """Raised inside a running optimisation when the user presses Stop."""


class WatchedMerit(opt.MeritFunction):
    """A merit function that checks a stop flag, reports progress and remembers
    the best feasible design it has evaluated."""

    def __init__(self, base, stop, report, interval: float = 0.25):
        """``stop`` is anything with ``is_set()`` (a threading.Event in the Qt app)."""
        super().__init__(base.rows)
        self.stop, self.report, self.interval = stop, report, interval
        self.best = math.inf
        self.best_system = None
        self.best_any = (math.inf, None)  # best design ignoring hard constraints
        self.evaluations = 0
        self._last = 0.0

    def residuals(self, system):
        if self.stop.is_set():
            raise StopRequested()
        r, c, ok = super().residuals(system)
        self.evaluations += 1
        if ok:
            v = float(np.sqrt(r @ r))
            feasible = c.size == 0 or float(np.max(np.abs(c))) < 1e-6
            if feasible and v < self.best:
                self.best = v
                self.best_system = system.copy()
            elif not feasible and self.best_system is None and v < self.best_any[0]:
                self.best_any = (v, system.copy())
        now = time.time()
        if now - self._last > self.interval:
            self._last = now
            self.report({"best": self.best, "evaluations": self.evaluations})
        return r, c, ok

    def value(self, system):
        r, _, ok = self.residuals(system)
        return float(np.sqrt(np.sum(r * r))) if ok else math.inf


ALGORITHMS = [("Local: damped least squares", "dls"),
              ("Local: orthogonal descent (no derivatives)", "od"), ("Hammer", "hammer"), ("Global search (multi-start)", "global"),
              ("Glass substitution", "glass")]


def run_optimization(system, merit, algorithm, stop, report, cycles=50, trials=50, time_limit=0.0, nearest=5,
                     starts=20, report_interval=0.25, catalogs=None):
    """Run one optimisation algorithm on ``system`` (a copy) and return
    (system, message, history).  Shared by the dialog and the tests."""
    wm = WatchedMerit(merit, stop, report, report_interval)
    t0 = time.time()
    tl = time_limit or None
    initial = wm.value(system)
    try:
        if algorithm == "dls":
            res = opt.optimize(system, wm, cycles=cycles)
            msg = f"DLS: {res.initial_merit:.8g} -> {res.merit:.8g} in {res.cycles} cycles ({res.message})"
            hist = res.history
        elif algorithm == "od":
            res = opt.orthogonal_descent(system, wm, cycles=cycles)
            msg = (f"Orthogonal descent: {res.initial_merit:.8g} -> {res.merit:.8g} in {res.cycles} cycles "
                   f"({res.message})")
            hist = res.history
        elif algorithm == "hammer":
            res = opt.hammer(system, wm, trials=trials, time_limit=tl, cycles=min(cycles, 20))
            msg = (f"Hammer: {res.initial_merit:.8g} -> {res.merit:.8g}, {res.trials} trials, "
                   f"{res.improvements} improvements")
            hist = res.history
        elif algorithm == "global":
            res = opt.global_search(system, wm, starts=starts, time_limit=tl, cycles=min(cycles, 30))
            msg = (f"Global search: {res.initial_merit:.8g} -> {res.merit:.8g}, {res.trials} starts, "
                   f"{len(res.designs)} designs kept")
            hist = res.history
        elif algorithm == "glass":
            res = opt.glass_substitution(system, wm, nearest=nearest, cycles=min(cycles, 10),
                                         catalogs=catalogs)
            ch = ", ".join(f"S{k}: {v}" for k, v in res.choices.items())
            msg = f"Glass substitution: {res.initial_merit:.8g} -> {res.merit:.8g}; {ch}"
            hist = [res.initial_merit, res.merit]
        else:
            raise ValueError(algorithm)
    except StopRequested:
        if wm.best_system is not None:
            best, value = wm.best_system, wm.best
        elif wm.best_any[1] is not None:
            value, best = wm.best_any
        else:
            return system, "Stopped by user before any design was evaluated", [initial]
        return best, f"Stopped by user: {initial:.8g} -> {value:.8g} (best design so far)", [initial, value]
    msg += f"   [{time.time() - t0:.1f} s, {wm.evaluations} merit evaluations]"
    return system, msg, hist


TOL_COLUMNS = ["Type", "Surf", "Surf2", "Param", "Min", "Max", "Comment"]
CRITERIA = [("RMS spot radius", "rms_spot"), ("RMS wavefront", "rms_wavefront"), ("MTF (average)", "mtf"),
            ("Merit function", "merit")]
COMPENSATORS = [("Back focus (optimised)", "focus"), ("Paraxial focus", "paraxial_focus"), ("None", None)]
DISTRIBUTIONS = ["normal", "uniform", "parabolic", "endpoint"]


def watched_criterion(system, kind, frequency, stop, report, total):
    """A tolerance criterion that honours the stop flag and reports progress."""
    if kind == "merit":
        crit = make_criterion(system, system.merit_function.copy())
    else:
        crit = make_criterion(system, kind, frequency)
    count = [0]

    def fn(s):
        if stop.is_set():
            raise StopRequested()
        count[0] += 1
        report({"done": count[0], "total": total})
        return crit.fn(s)
    return Criterion(crit.name, fn, crit.higher_is_better, crit.merit)
