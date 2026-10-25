"""Optimisation and tolerancing dialogs.

Both run lensforge.optimize on a copy of the lens in a worker thread.  The
optimised lens replaces the open one as a single undoable step.  "Stop" works
for every algorithm: the merit function (or tolerance criterion) given to the
optimiser checks a stop flag at each evaluation and the best design seen so
far is kept.
"""

from __future__ import annotations

import math
import threading
import time

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFormLayout,
                               QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QMessageBox,
                               QPlainTextEdit, QPushButton, QSpinBox, QSplitter, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from lensforge import optimize as opt
from lensforge.optimize.tolerance import (TOLERANCE_TYPES, Criterion, make_criterion, sensitivity_table)

from . import workers
from .fonts import fixed_font


class StopRequested(Exception):
    """Raised inside a running optimisation when the user presses Stop."""


class WatchedMerit(opt.MeritFunction):
    """A merit function that checks a stop flag, reports progress and remembers
    the best feasible design it has evaluated."""

    def __init__(self, base, stop: threading.Event, report, interval: float = 0.25):
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


ALGORITHMS = [("Local: damped least squares", "dls"), ("Hammer", "hammer"), ("Global search (multi-start)", "global"),
              ("Glass substitution", "glass")]


def run_optimization(system, merit, algorithm, stop, report, cycles=50, trials=50, time_limit=0.0, nearest=5,
                     starts=20, report_interval=0.25):
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
            res = opt.glass_substitution(system, wm, nearest=nearest, cycles=min(cycles, 10))
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


class OptimizationDialog(QDialog):
    def __init__(self, doc, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.setWindowTitle("Optimization")
        self.resize(640, 560)
        self.stop = threading.Event()
        self.running = False
        self.result = None

        form = QFormLayout()
        self.algorithm = QComboBox()
        for lab, k in ALGORITHMS:
            self.algorithm.addItem(lab, k)
        self.cycles = QSpinBox()
        self.cycles.setRange(1, 10000)
        self.cycles.setValue(50)
        self.trials = QSpinBox()
        self.trials.setRange(1, 100000)
        self.trials.setValue(50)
        self.time_limit = QDoubleSpinBox()
        self.time_limit.setRange(0, 1e6)
        self.time_limit.setSuffix(" s")
        self.time_limit.setSpecialValueText("none")
        self.nearest = QSpinBox()
        self.nearest.setRange(1, 200)
        self.nearest.setValue(5)
        self.auto_apply = QCheckBox("Load the result into the lens when finished")
        self.auto_apply.setChecked(True)
        form.addRow("Algorithm", self.algorithm)
        form.addRow("DLS cycles", self.cycles)
        form.addRow("Trials / starts", self.trials)
        form.addRow("Time limit", self.time_limit)
        form.addRow("Glass candidates (nearest)", self.nearest)
        form.addRow("", self.auto_apply)
        self.algorithm.currentIndexChanged.connect(self._enable)

        self.info = QLabel()
        self.info.setWordWrap(True)
        self.merit_label = QLabel()
        f = self.merit_label.font()
        f.setPointSizeF(f.pointSizeF() * 1.25)
        f.setBold(True)
        self.merit_label.setFont(f)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(2000)
        self.figure = Figure(figsize=(4, 2), dpi=80, layout="tight")
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.canvas.setMinimumHeight(140)
        self.history = []

        btns = QHBoxLayout()
        self.start_btn = QPushButton("Start")
        self.stop_btn = QPushButton("Stop")
        self.apply_btn = QPushButton("Load Result")
        close = QPushButton("Close")
        self.start_btn.clicked.connect(self.start)
        self.stop_btn.clicked.connect(self.request_stop)
        self.apply_btn.clicked.connect(self.apply_result)
        close.clicked.connect(self.close)
        self.stop_btn.setEnabled(False)
        self.apply_btn.setEnabled(False)
        for b in (self.start_btn, self.stop_btn, self.apply_btn):
            btns.addWidget(b)
        btns.addStretch(1)
        btns.addWidget(close)

        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(self.info)
        lay.addWidget(self.merit_label)
        lay.addWidget(self.canvas)
        lay.addWidget(self.log, 1)
        lay.addLayout(btns)
        self._enable()
        self.refresh_info()
        doc.changed.connect(self.refresh_info)

    def _enable(self):
        a = self.algorithm.currentData()
        self.trials.setEnabled(a in ("hammer", "global"))
        self.time_limit.setEnabled(a in ("hammer", "global"))
        self.nearest.setEnabled(a == "glass")

    def refresh_info(self):
        if self.running:
            return
        s = self.doc.system
        vs = getattr(s, "variables", None) or []
        mf = getattr(s, "merit_function", None)
        names = ", ".join(v.name for v in vs[:12]) + (" ..." if len(vs) > 12 else "")
        self.info.setText(f"{len(vs)} variable(s): {names or 'none (right-click a cell in the Lens Data Editor)'}"
                          f"\n{len(mf.rows) if mf else 0} merit function row(s)")
        if mf is not None and mf.rows:
            try:
                v = mf.value(s)
            except Exception:  # noqa: BLE001
                v = math.inf
            self.merit_label.setText(f"Current merit function: {v:.10g}")
        else:
            self.merit_label.setText("No merit function (Tools > Merit Function Editor)")

    def start(self):
        s = self.doc.system
        if not getattr(s, "variables", None) and self.algorithm.currentData() != "glass":
            QMessageBox.information(self, "Optimization", "There are no variables. Right-click a radius, "
                                    "thickness, conic or material cell in the Lens Data Editor and choose "
                                    "Make Variable.")
            return
        mf = getattr(s, "merit_function", None)
        if mf is None or not mf.rows:
            QMessageBox.information(self, "Optimization", "The merit function is empty. Use the Merit Function "
                                    "Editor (its Wizard builds a default merit function).")
            return
        self.stop.clear()
        self.running = True
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.apply_btn.setEnabled(False)
        self.history = []
        alg = self.algorithm.currentData()
        self.log.appendPlainText(f"--- {self.algorithm.currentText()} started")
        system, merit = s.copy(), mf.copy()
        kw = dict(cycles=self.cycles.value(), trials=self.trials.value(), starts=self.trials.value(),
                  time_limit=self.time_limit.value(), nearest=self.nearest.value())
        self._t0 = time.time()
        workers.submit(lambda report: run_optimization(system, merit, alg, self.stop, report, **kw),
                       self._done, self._failed, self._progress)

    def request_stop(self):
        self.stop.set()
        self.log.appendPlainText("Stopping...")

    def _progress(self, _tag, p):
        try:
            self.history.append(p["best"])
            self.merit_label.setText(f"Best merit: {p['best']:.10g}   ({p['evaluations']} evaluations, "
                                     f"{time.time() - self._t0:.1f} s)")
            self._plot()
        except RuntimeError:
            pass

    def _plot(self):
        h = [v for v in self.history if math.isfinite(v)]
        self.figure.clear()
        ax = self.figure.add_subplot(111)
        if h:
            ax.semilogy(h, ".-", ms=3)
        ax.set_xlabel("progress updates", fontsize=8)
        ax.set_ylabel("merit", fontsize=8)
        ax.tick_params(labelsize=7)
        self.canvas.draw_idle()

    def _done(self, _tag, res):
        system, msg, hist = res
        self.running = False
        self.result = system
        self.log.appendPlainText(msg)
        self.history = list(hist)
        self._plot()
        try:
            mv = system.merit_function.value(system) if getattr(system, "merit_function", None) else math.nan
        except Exception:  # noqa: BLE001
            mv = math.nan
        self.merit_label.setText(f"Result merit function: {mv:.10g}")
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.apply_btn.setEnabled(not self.auto_apply.isChecked())
        if self.auto_apply.isChecked():
            self.apply_result()

    def _failed(self, _tag, msg):
        self.running = False
        self.log.appendPlainText(f"Failed: {msg}")
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.refresh_info()

    def apply_result(self):
        if self.result is None:
            return
        alg = self.algorithm.currentText()
        self.doc.replace(f"Optimization ({alg})", self.result)
        self.result = None
        self.apply_btn.setEnabled(False)
        self.refresh_info()

    def closeEvent(self, ev):
        if self.running:
            self.stop.set()
        super().closeEvent(ev)


# ---------------------------------------------------------------------------
# Tolerancing
# ---------------------------------------------------------------------------

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


class ToleranceDialog(QDialog):
    def __init__(self, doc, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.setWindowTitle("Tolerancing")
        self.resize(900, 680)
        self.stop = threading.Event()
        self.running = False
        self.mc = None

        # wizard
        wiz = QGroupBox("Tolerance wizard")
        g = QGridLayout(wiz)
        self.wiz = {}
        for k, (name, label, val, dec) in enumerate((
                ("fringes", "Power (fringes)", 2.0, 2), ("thickness", "Thickness", 0.05, 4),
                ("surface_decenter", "Surface decenter", 0.01, 4), ("surface_tilt", "Surface tilt (deg)", 0.01, 4),
                ("element_decenter", "Element decenter", 0.02, 4), ("element_tilt", "Element tilt (deg)", 0.02, 4),
                ("index", "Index", 0.0005, 5), ("abbe_percent", "Abbe (%)", 0.5, 2))):
            sb = QDoubleSpinBox()
            sb.setDecimals(dec)
            sb.setRange(0, 1e4)
            sb.setSingleStep(10 ** -dec * 10)
            sb.setValue(val)
            g.addWidget(QLabel(label), k // 4, 2 * (k % 4))
            g.addWidget(sb, k // 4, 2 * (k % 4) + 1)
            self.wiz[name] = sb
        gen = QPushButton("Generate Default Tolerances")
        gen.clicked.connect(self.generate)
        g.addWidget(gen, 2, 0, 1, 2)
        addb = QPushButton("Add Row")
        addb.clicked.connect(lambda: self._add_row(["TTHI", "1", "", "", "-0.05", "0.05", ""]))
        remb = QPushButton("Remove Rows")
        remb.clicked.connect(self._remove_rows)
        g.addWidget(addb, 2, 2)
        g.addWidget(remb, 2, 3)

        self.table = QTableWidget(0, len(TOL_COLUMNS))
        self.table.setHorizontalHeaderLabels(TOL_COLUMNS)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setDefaultSectionSize(20)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setToolTip("Types: " + ", ".join(TOLERANCE_TYPES))

        # run options
        run = QGroupBox("Analysis")
        f = QFormLayout(run)
        self.criterion = QComboBox()
        for lab, k in CRITERIA:
            self.criterion.addItem(lab, k)
        self.freq = QDoubleSpinBox()
        self.freq.setRange(0.1, 1e5)
        self.freq.setValue(30)
        self.freq.setSuffix(" cycles/mm")
        self.comp = QComboBox()
        for lab, k in COMPENSATORS:
            self.comp.addItem(lab, k)
        self.mc_trials = QSpinBox()
        self.mc_trials.setRange(1, 100000)
        self.mc_trials.setValue(100)
        self.dist = QComboBox()
        self.dist.addItems(DISTRIBUTIONS)
        self.seed = QSpinBox()
        self.seed.setRange(0, 2**31 - 1)
        f.addRow("Criterion", self.criterion)
        f.addRow("MTF frequency", self.freq)
        f.addRow("Compensator", self.comp)
        f.addRow("Monte Carlo trials", self.mc_trials)
        f.addRow("Distribution", self.dist)
        f.addRow("Seed", self.seed)
        b = QHBoxLayout()
        self.sens_btn = QPushButton("Run Sensitivity")
        self.mc_btn = QPushButton("Run Monte Carlo")
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setEnabled(False)
        self.sens_btn.clicked.connect(lambda: self.run("sensitivity"))
        self.mc_btn.clicked.connect(lambda: self.run("monte_carlo"))
        self.stop_btn.clicked.connect(self.stop.set)
        for w in (self.sens_btn, self.mc_btn, self.stop_btn):
            b.addWidget(w)
        f.addRow(b)
        self.progress = QLabel("")
        f.addRow(self.progress)

        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setLineWrapMode(QPlainTextEdit.NoWrap)
        mono = fixed_font()
        self.output.setFont(mono)
        self.figure = Figure(figsize=(4, 3), dpi=80, layout="tight")
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.load_worst = QPushButton("Load Worst Monte Carlo Lens")
        self.load_worst.setEnabled(False)
        self.load_worst.clicked.connect(lambda: self._load_mc("worst"))

        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(wiz)
        ll.addWidget(self.table, 1)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(run)
        rl.addWidget(self.canvas, 1)
        rl.addWidget(self.load_worst)
        top = QSplitter(Qt.Horizontal)
        top.addWidget(left)
        top.addWidget(right)
        top.setStretchFactor(0, 3)
        top.setStretchFactor(1, 2)
        split = QSplitter(Qt.Vertical)
        split.addWidget(top)
        split.addWidget(self.output)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        lay = QVBoxLayout(self)
        lay.addWidget(split)
        self.generate()

    # -- tolerance table ------------------------------------------------------------
    def _add_row(self, vals):
        r = self.table.rowCount()
        self.table.insertRow(r)
        for c, v in enumerate(vals):
            self.table.setItem(r, c, QTableWidgetItem(v))

    def _remove_rows(self):
        for r in sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True):
            self.table.removeRow(r)

    def generate(self):
        try:
            tols = opt.default_tolerances(self.doc.system, **{k: sb.value() for k, sb in self.wiz.items()})
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Tolerancing", f"Could not build default tolerances: {e}")
            return
        self.table.setRowCount(0)
        for t in tols:
            self._add_row([t.type, str(t.surface), "" if t.surface2 is None else str(t.surface2), t.param or "",
                           f"{t.min:.6g}", f"{t.max:.6g}", t.comment])

    def tolerances(self):
        out = []
        for r in range(self.table.rowCount()):
            v = [(self.table.item(r, c).text().strip() if self.table.item(r, c) else "") for c in range(7)]
            if not v[0]:
                continue
            out.append(opt.Tolerance(v[0].upper(), int(v[1]), float(v[4]), float(v[5]),
                                     int(v[2]) if v[2] else None, v[3] or None, None, v[6]))
        if not out:
            raise ValueError("the tolerance list is empty")
        return out

    # -- running --------------------------------------------------------------------
    def run(self, what):
        try:
            tols = self.tolerances()
        except (ValueError, KeyError) as e:
            QMessageBox.warning(self, "Tolerancing", f"Invalid tolerance row: {e}")
            return
        kind = self.criterion.currentData()
        system = self.doc.system.copy()
        if kind == "merit" and not (getattr(system, "merit_function", None) and system.merit_function.rows):
            QMessageBox.warning(self, "Tolerancing", "The lens has no merit function.")
            return
        freq = self.freq.value()
        comp = self.comp.currentData()
        trials, dist, seed = self.mc_trials.value(), self.dist.currentText(), self.seed.value()
        total = 1 + (2 * len(tols) if what == "sensitivity" else trials)
        self.stop.clear()
        self._busy(True)
        self.output.appendPlainText(f"=== {what.replace('_', ' ').title()}: {len(tols)} tolerances, "
                                    f"criterion {self.criterion.currentText()}, compensator {self.comp.currentText()}")
        stop = self.stop

        def job(report):
            crit = watched_criterion(system, kind, freq, stop, report, total)
            if what == "sensitivity":
                return what, opt.sensitivity_analysis(system, tols, crit, compensators=comp, frequency=freq)
            return what, opt.monte_carlo(system, tols, trials, crit, compensators=comp, frequency=freq,
                                         distribution=dist, seed=seed)
        workers.submit(job, self._done, self._failed, self._progress)

    def _busy(self, on):
        self.running = on
        self.sens_btn.setEnabled(not on)
        self.mc_btn.setEnabled(not on)
        self.stop_btn.setEnabled(on)

    def _progress(self, _tag, p):
        try:
            self.progress.setText(f"{p['done']} / {p['total']} evaluations")
        except RuntimeError:
            pass

    def _failed(self, _tag, msg):
        self._busy(False)
        self.output.appendPlainText("Stopped." if "StopRequested" in msg else f"Failed: {msg}")

    def _done(self, _tag, res):
        self._busy(False)
        what, r = res
        self.figure.clear()
        ax = self.figure.add_subplot(111)
        if what == "sensitivity":
            self.output.appendPlainText(sensitivity_table(r))
            self.output.appendPlainText("\nWorst offenders:\n" + sensitivity_table(r, 10).split("\n", 2)[2])
            worst = r["worst"][:12]
            labels = [w["label"] for w in worst][::-1]
            vals = [max(abs(w["change_min"]), abs(w["change_max"])) for w in worst][::-1]
            ax.barh(range(len(vals)), vals)
            ax.set_yticks(range(len(vals)))
            ax.set_yticklabels(labels, fontsize=7)
            ax.set_xlabel(f"change in {r['criterion']}", fontsize=8)
            ax.set_title("Worst offenders", fontsize=9)
        else:
            self.mc = r
            self.output.appendPlainText(r.summary() + f"\n  ({r.seconds:.1f} s)")
            v = r.values[np.isfinite(r.values)]
            if v.size:
                ax.hist(v, bins=min(40, max(5, v.size // 4)), color="C0", alpha=0.8)
                ax.axvline(r.nominal, color="k", lw=1, label="nominal")
                ax.legend(fontsize=7)
            ax.set_xlabel(r.criterion, fontsize=8)
            ax.set_ylabel("trials", fontsize=8)
            ax.set_title("Monte Carlo", fontsize=9)
            self.load_worst.setEnabled(r.worst is not None)
        ax.tick_params(labelsize=7)
        self.canvas.draw_idle()
        self.progress.setText("")

    def _load_mc(self, which):
        s = getattr(self.mc, which, None)
        if s is not None:
            self.doc.replace(f"Load {which} Monte Carlo lens", s.copy())

    def closeEvent(self, ev):
        if self.running:
            self.stop.set()
        super().closeEvent(ev)
