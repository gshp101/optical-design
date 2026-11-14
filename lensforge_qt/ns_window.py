"""Non-sequential editor and ray-trace viewer.

A separate window holding one :class:`lensforge.nonseq.NonSequentialSystem`:
an object table and a source table (one row each, pose columns plus a
``name=value`` parameter column), trace settings, and a plot of the traced
rays with the irradiance on a chosen detector.  Everything it does is the
public ``lensforge.nonseq`` API.
"""

from __future__ import annotations


from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QHBoxLayout, QLabel, QMainWindow,
                               QMenu, QMessageBox, QPlainTextEdit, QPushButton, QSpinBox, QSplitter, QTableWidget,
                               QTableWidgetItem, QTabWidget, QToolBar, QToolButton, QVBoxLayout, QWidget)

from lensforge import nonseq as ns

from . import icons, workers
from .ns_table import (BUTTONS, OBJ_COLS, OBJECT_LABELS, POSE, SOURCE_LABELS, SRC_COLS,  # noqa: F401
                       _fmt, _num, apply_cell)
from .ownership import qt_owns_children

@qt_owns_children
class NonSequentialWindow(QMainWindow):
    def __init__(self, main=None, scene=None):
        super().__init__(main)
        self.setWindowFlag(Qt.Window, True)
        self.main = main
        self.scene = scene or ns.NonSequentialSystem("Scene")
        self.result = None
        self.path = None
        self._filling = False
        self.setWindowTitle("Non-Sequential Editor")
        self.resize(1200, 820)

        self.actions_ = {}
        tb = QToolBar("Non-sequential")
        tb.setObjectName("ns_toolbar")
        self.addToolBar(tb)
        slots = {"new": self.new_scene, "open": self.open_scene, "save": self.save_scene,
                 "convert": self.from_current_lens, "add_object": None, "add_source": None,
                 "delete": self.delete_row, "trace": self.trace, "help": self.show_help}
        for key, (text, tip) in BUTTONS.items():
            a = QAction(icons.ns_icon(key), text, self)
            a.setToolTip(f"<b>{text}</b><br>{tip}")
            a.setStatusTip(tip)
            if slots[key] is not None:
                a.triggered.connect(slots[key])
            self.actions_[key] = a
            if key in ("add_object", "add_source"):
                menu = QMenu(self)
                labels = OBJECT_LABELS if key == "add_object" else SOURCE_LABELS
                for kind, lab in labels.items():
                    menu.addAction(lab).triggered.connect(lambda _=False, k=kind: self.add_item(k))
                a.setMenu(menu)
                a.triggered.connect(lambda _=False, m=menu, k=key: m.exec(self.cursor().pos()))
                tb.addAction(a)
                btn = tb.widgetForAction(a)
                if isinstance(btn, QToolButton):
                    btn.setPopupMode(QToolButton.InstantPopup)
            else:
                tb.addAction(a)
        self.actions_["trace"].setShortcut(QKeySequence("F5"))
        self.actions_["help"].setShortcut(QKeySequence.HelpContents)

        self.tabs = QTabWidget()
        self.obj_table = QTableWidget(0, len(OBJ_COLS))
        self.obj_table.setHorizontalHeaderLabels(OBJ_COLS)
        self.src_table = QTableWidget(0, len(SRC_COLS))
        self.src_table.setHorizontalHeaderLabels(SRC_COLS)
        for t in (self.obj_table, self.src_table):
            t.horizontalHeader().setStretchLastSection(True)
            t.itemChanged.connect(self._cell_changed)
        self.obj_table.setToolTip("One row per object. Edit any cell; Parameters are name=value pairs "
                                  "(hover a row's Parameters cell for the names).")
        self.src_table.setToolTip("One row per source. Rays leave along the source's local +z axis.")
        self.tabs.addTab(self.obj_table, "Objects")
        self.tabs.addTab(self.src_table, "Sources")

        # trace settings
        self.split = QCheckBox("Split rays")
        self.split.setChecked(True)
        self.split.setToolTip("Follow both the reflected and transmitted part at every refracting face "
                              "(shows ghosts and stray light).")
        self.fresnel = QCheckBox("Fresnel losses")
        self.fresnel.setChecked(True)
        self.min_int = QDoubleSpinBox()
        self.min_int.setDecimals(10)
        self.min_int.setRange(0, 1)
        self.min_int.setValue(1e-5)
        self.min_int.setSingleStep(1e-5)
        self.min_int.setToolTip("Minimum relative ray intensity: split rays weaker than this fraction of their "
                                "source ray are dropped.")
        self.max_seg = QSpinBox()
        self.max_seg.setRange(2, 10000)
        self.max_seg.setValue(100)
        self.max_seg.setToolTip("Maximum segments per ray.")
        self.det_box = QComboBox()
        self.det_box.setToolTip("Detector shown on the right.")
        self.filter_box = QComboBox()
        for lab, v in (("All rays", "all"), ("Direct (no reflection)", "direct"), ("Ghosts (2+ reflections)", "ghost"),
                       ("1 reflection", 1), ("2 reflections", 2), ("3 reflections", 3), ("4 reflections", 4)):
            self.filter_box.addItem(lab, v)
        self.filter_box.setToolTip("Which rays the detector image and the layout count, by the number of Fresnel "
                                   "(partial) reflections they took.")
        self.log_box = QCheckBox("Log scale")
        self.log_box.setChecked(True)
        self.plane_box = QComboBox()
        self.plane_box.addItem("YZ layout", "y")
        self.plane_box.addItem("XZ layout", "x")
        for w in (self.det_box, self.filter_box, self.log_box, self.plane_box):
            (w.currentIndexChanged if hasattr(w, "currentIndexChanged") else w.toggled).connect(self.redraw)
        row = QHBoxLayout()
        for lab, w in (("", self.split), ("", self.fresnel), ("Min. intensity", self.min_int),
                       ("Max. segments", self.max_seg), ("Detector", self.det_box), ("Show", self.filter_box),
                       ("", self.log_box), ("", self.plane_box)):
            if lab:
                row.addWidget(QLabel(lab))
            row.addWidget(w)
        self.trace_btn = QPushButton("Trace")
        self.trace_btn.setToolTip(BUTTONS["trace"][1])
        self.trace_btn.clicked.connect(self.trace)
        row.addWidget(self.trace_btn)
        row.addStretch(1)

        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
        from matplotlib.figure import Figure
        self.figure = Figure(figsize=(10, 4))
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.summary = QPlainTextEdit()
        self.summary.setReadOnly(True)
        self.summary.setMaximumHeight(110)

        bottom = QWidget()
        bl = QVBoxLayout(bottom)
        bl.addLayout(row)
        bl.addWidget(self.canvas, 1)
        bl.addWidget(self.summary)
        split = QSplitter(Qt.Vertical)
        split.addWidget(self.tabs)
        split.addWidget(bottom)
        split.setSizes([280, 540])
        self.setCentralWidget(split)
        self.fill()

    # ------------------------------------------------------------------ tables
    def fill(self):
        self._filling = True
        try:
            self.obj_table.setRowCount(len(self.scene.objects))
            for r, o in enumerate(self.scene.objects):
                vals = [OBJECT_LABELS.get(o.kind, o.kind), o.comment] + [_fmt(getattr(o, k)) for k in POSE] + [
                    _fmt(o.material or "") if not o.is_detector else "", "" if o.coating is None else _fmt(o.coating),
                    ", ".join(f"{n}={_fmt(getattr(o, n))}" for n, _ in o.params)]
                for c, v in enumerate(vals):
                    it = QTableWidgetItem(v)
                    if c == 0:
                        it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                    if c == len(OBJ_COLS) - 1:
                        it.setToolTip("; ".join(f"{n}: {lab}" for n, lab in o.params))
                    self.obj_table.setItem(r, c, it)
            self.src_table.setRowCount(len(self.scene.sources))
            for r, s in enumerate(self.scene.sources):
                vals = [SOURCE_LABELS.get(s.kind, s.kind), s.comment] + [_fmt(getattr(s, k)) for k in POSE] + [
                    str(s.n_rays), _fmt(s.power), ", ".join(_fmt(w) for w in s.wavelengths), s.sampling,
                    ", ".join(f"{n}={_fmt(getattr(s, n))}" for n, _ in s.params)]
                for c, v in enumerate(vals):
                    it = QTableWidgetItem(v)
                    if c == 0:
                        it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                    if c == len(SRC_COLS) - 1:
                        it.setToolTip("; ".join(f"{n}: {lab}" for n, lab in s.params))
                    self.src_table.setItem(r, c, it)
            self.obj_table.resizeColumnsToContents()
            self.src_table.resizeColumnsToContents()
            cur = self.det_box.currentIndex()
            self.det_box.blockSignals(True)
            self.det_box.clear()
            for k, o in enumerate(self.scene.objects):
                if o.is_detector:
                    self.det_box.addItem(f"{k + 1}: {o.comment or 'detector'}", k)
            self.det_box.setCurrentIndex(max(0, min(cur, self.det_box.count() - 1)))
            self.det_box.blockSignals(False)
        finally:
            self._filling = False
        title = self.scene.name or "Scene"
        self.setWindowTitle(f"Non-Sequential Editor - {title}")

    def _cell_changed(self, item):
        if self._filling:
            return
        table = item.tableWidget()
        r, c = item.row(), item.column()
        is_obj = table is self.obj_table
        target = (self.scene.objects if is_obj else self.scene.sources)[r]
        try:
            self._apply(target, c, item.text(), is_obj)
            self.statusBar().clearMessage()
        except Exception as e:  # noqa: BLE001 - shown to the user
            self.statusBar().showMessage(f"Not changed: {e}", 8000)
        self.fill()

    _apply = staticmethod(apply_cell)

    # ------------------------------------------------------------------ commands
    def add_item(self, kind):
        if kind in ns.OBJECT_TYPES:
            obj = ns.OBJECT_TYPES[kind]()
            r = self.obj_table.currentRow()
            at = len(self.scene.objects) if r < 0 else r + 1
            self.scene.objects.insert(at, obj)
            self.tabs.setCurrentIndex(0)
        else:
            self.scene.sources.append(ns.SOURCE_TYPES[kind](z=-10.0))
            self.tabs.setCurrentIndex(1)
        self.fill()

    def delete_row(self):
        table, items = ((self.obj_table, self.scene.objects) if self.tabs.currentIndex() == 0
                        else (self.src_table, self.scene.sources))
        r = table.currentRow()
        if 0 <= r < len(items):
            del items[r]
            self.fill()

    def new_scene(self, ask=True):
        if ask and (self.scene.objects or self.scene.sources):
            if QMessageBox.question(self, "New scene", "Discard the current scene?") != QMessageBox.Yes:
                return
        self.set_scene(ns.NonSequentialSystem("Scene"))

    def set_scene(self, scene, path=None):
        self.scene, self.path, self.result = scene, path, None
        self.figure.clear()
        self.canvas.draw_idle()
        self.summary.setPlainText("")
        self.fill()

    def from_current_lens(self):
        if self.main is None:
            return
        try:
            scene = ns.from_sequential(self.main.doc.system, n_rays=1000, sampling="random")
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Convert lens", f"This lens cannot be converted: {e}")
            return
        self.set_scene(scene)

    def open_scene(self, path=None):
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, "Open non-sequential scene", "",
                                                  "Non-sequential scenes (*.ns.json *.json);;All files (*)")
        if not path:
            return
        try:
            self.set_scene(ns.load(path), path)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Open scene", f"Could not open {path}: {e}")

    def save_scene(self, path=None):
        if not path:
            path, _ = QFileDialog.getSaveFileName(self, "Save non-sequential scene", self.path or "scene.ns.json",
                                                  "Non-sequential scenes (*.ns.json)")
        if not path:
            return
        ns.save(self.scene, path)
        self.path = path
        self.statusBar().showMessage(f"Saved {path}", 5000)

    def show_help(self):
        if self.main is not None:
            self.main.help_contents("Tools > Non-Sequential > Non-Sequential Editor")

    # ------------------------------------------------------------------ tracing
    def trace(self):
        scene = self.scene.copy()
        miss = scene.missing_materials()
        if miss:
            self.summary.setPlainText("Cannot trace: " + "; ".join(
                f"{m} (objects {', '.join(str(k + 1) for k in rows)})" for m, rows in miss.items())
                + " not in any loaded glass catalog.")
            return
        if not scene.sources:
            self.summary.setPlainText("Add a source first (Add Source on the toolbar).")
            return
        opts = dict(split=self.split.isChecked(), fresnel=self.fresnel.isChecked(),
                    min_relative_intensity=self.min_int.value(), max_segments=self.max_seg.value())
        self.summary.setPlainText("Tracing...")
        self.trace_btn.setEnabled(False)
        workers.submit(lambda progress: ns.trace(scene, **opts), self._traced, self._failed)

    def _traced(self, tag, result):
        self.trace_btn.setEnabled(True)
        self.result = result
        self.summary.setPlainText(result.summary())
        self.redraw()

    def _failed(self, tag, msg):
        self.trace_btn.setEnabled(True)
        self.summary.setPlainText(f"Trace failed: {msg}")

    def redraw(self, *_):
        import lensforge.plot as P
        r = self.result
        self.figure.clear()
        if r is None:
            self.canvas.draw_idle()
            return
        rays = self.filter_box.currentData()
        ax1 = self.figure.add_subplot(1, 2, 1)
        P.ns_layout(r, ax1, plane=self.plane_box.currentData())
        if r.detectors and self.det_box.count():
            k = self.det_box.currentData()
            ax2 = self.figure.add_subplot(1, 2, 2)
            try:
                P.ns_detector(r, k, ax2, rays=rays, log=self.log_box.isChecked())
            except KeyError:  # detector added after the trace
                ax2.set_title("Trace again to see this detector")
        self.figure.tight_layout()
        self.canvas.draw_idle()
