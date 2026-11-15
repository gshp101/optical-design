"""Non-Sequential Component Editor: the lens's non-sequential scene, as in Zemax's NSC Editor.

A separate window over ``doc.system.nonseq`` (see :mod:`lensforge_qt.ns_table`): an object
table and a source table (Type, Comment, Ref, position, tilts, material or ray settings, then
``Par 1..`` columns named after the selected row's type), the Ray Trace Control settings and a
Trace button.  Every edit is one undoable lens edit and the scene is saved in the lens file.
The traced rays are shown by the analysis windows of Analysis > Non-Sequential (NS Layout,
NS 3D Layout, Detector Viewer, Ray Path Analysis, NS Trace Report).  Everything it does is the
public ``lensforge.nonseq`` API.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QBrush, QColor, QKeySequence
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QGroupBox, QLabel, QMainWindow,
                               QMenu, QMessageBox, QPlainTextEdit, QPushButton, QSpinBox, QSplitter, QTableWidget,
                               QTableWidgetItem, QTabWidget, QToolBar, QToolButton, QVBoxLayout, QWidget)

from lensforge import nonseq as ns

from . import icons, workers
from . import ns_table as NT
from .flow_layout import FlowLayout, group
from .fonts import fixed_font
from .ns_table import BUTTONS, OBJ_COLS, OBJECT_LABELS, SOURCE_LABELS, SRC_COLS  # noqa: F401
from .ownership import qt_owns_children

HELP_ID = "Tools > Non-Sequential > Non-Sequential Component Editor"
BAD = QColor("#ffd6d6")
GREY = QColor("#eeeeee")


@qt_owns_children
class NonSequentialWindow(QMainWindow):
    def __init__(self, main):
        super().__init__(main)
        self.setWindowFlag(Qt.Window, True)
        self.main = main
        self.doc = main.doc
        self._filling = False
        self.setWindowTitle("Non-Sequential Component Editor")
        self.resize(1250, 640)

        self.actions_ = {}
        tb = QToolBar("Non-sequential")
        tb.setObjectName("ns_toolbar")
        self.addToolBar(tb)
        slots = {"new": self.new_scene, "open": self.open_scene, "save": self.save_scene,
                 "convert": self.from_current_lens, "add_object": None, "add_source": None,
                 "duplicate": self.duplicate_row, "move_up": lambda: self.move_row(-1),
                 "move_down": lambda: self.move_row(+1), "delete": self.delete_row, "trace": self.trace,
                 "layout": lambda: self.main.open_analysis("ns_layout"),
                 "detector": lambda: self.main.open_analysis("ns_detector"),
                 "paths": lambda: self.main.open_analysis("ns_paths"), "help": self.show_help}
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
                a.triggered.connect(lambda _=False, m=menu: m.exec(self.cursor().pos()))
                tb.addAction(a)
                btn = tb.widgetForAction(a)
                if isinstance(btn, QToolButton):
                    btn.setPopupMode(QToolButton.InstantPopup)
            else:
                tb.addAction(a)
            if key in ("convert", "delete", "trace"):
                tb.addSeparator()
        self.actions_["trace"].setShortcut(QKeySequence("F5"))
        self.actions_["help"].setShortcut(QKeySequence.HelpContents)
        self.actions_["move_up"].setShortcut(QKeySequence("Ctrl+Up"))
        self.actions_["move_down"].setShortcut(QKeySequence("Ctrl+Down"))

        self.tabs = QTabWidget()
        self.obj_table = QTableWidget(0, len(OBJ_COLS))
        self.src_table = QTableWidget(0, len(SRC_COLS))
        for t, cols in ((self.obj_table, OBJ_COLS), (self.src_table, SRC_COLS)):
            t.setHorizontalHeaderLabels(cols)
            for c, name in enumerate(cols):
                t.horizontalHeaderItem(c).setToolTip(NT.COLUMN_TIPS.get(name, ""))
            t.horizontalHeader().setStretchLastSection(True)
            t.setSelectionMode(QTableWidget.SingleSelection)
            t.itemChanged.connect(self._cell_changed)
            t.currentCellChanged.connect(lambda r, *_a, t=t: self._update_headers(t))
            t.setContextMenuPolicy(Qt.CustomContextMenu)
            t.customContextMenuRequested.connect(lambda pos, t=t: self._context_menu(t, pos))
        self.obj_table.setToolTip("One row per object. Edit any white cell; the Par columns are named after the "
                                  "selected row's type (hover a cell for its parameter). Right-click for more.")
        self.src_table.setToolTip("One row per source. Rays leave along the source's local +z axis.")
        self.tabs.addTab(self.obj_table, "Objects")
        self.tabs.addTab(self.src_table, "Sources")
        self.tabs.currentChanged.connect(lambda _: self._update_headers(self.current_table()))

        # Ray Trace Control (kept with the scene)
        box = QGroupBox("Ray Trace Control")
        box.setToolTip("Settings of the non-sequential ray trace; they are saved with the scene and used by the "
                       "analysis windows of Analysis > Non-Sequential.")
        flow = FlowLayout(box, margin=4, hspacing=10, vspacing=4)
        self.trace_widgets = {}
        for key, (label, kind, tip) in NT.TRACE_FIELDS.items():
            if kind == "bool":
                w = QCheckBox(label)
                w.toggled.connect(lambda v, k=key: self._set_trace(k, v))
                item = w
            elif kind == "int":
                w = QSpinBox()
                w.setRange(2 if key == "max_segments" else 0, 1_000_000)
                w.setKeyboardTracking(False)
                w.valueChanged.connect(lambda v, k=key: self._set_trace(k, v))
                item = group(QLabel(label), w)
            else:
                w = QDoubleSpinBox()
                w.setDecimals(10)
                w.setRange(0, 1)
                w.setSingleStep(1e-5)
                w.setKeyboardTracking(False)
                w.valueChanged.connect(lambda v, k=key: self._set_trace(k, v))
                item = group(QLabel(label), w)
            w.setToolTip(tip)
            self.trace_widgets[key] = w
            flow.addWidget(item)
        self.trace_btn = QPushButton(icons.ns_icon("trace"), "Trace")
        self.trace_btn.setToolTip(BUTTONS["trace"][1])
        self.trace_btn.clicked.connect(self.trace)
        flow.addWidget(self.trace_btn)
        for key in ("layout", "detector", "paths"):
            b = QPushButton(icons.ns_icon(key), BUTTONS[key][0])
            b.setToolTip(BUTTONS[key][1])
            b.clicked.connect(self.actions_[key].trigger)
            flow.addWidget(b)
        self.summary = QPlainTextEdit()
        self.summary.setReadOnly(True)
        self.summary.setFont(fixed_font())
        self.summary.setPlaceholderText("Press Trace (F5) to trace the scene; the summary appears here.")

        bottom = QWidget()
        bl = QVBoxLayout(bottom)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.addWidget(box)
        bl.addWidget(self.summary, 1)
        split = QSplitter(Qt.Vertical)
        split.addWidget(self.tabs)
        split.addWidget(bottom)
        split.setSizes([380, 220])
        self.setCentralWidget(split)
        self.doc.changed.connect(self.fill)
        self.doc.error.connect(self._error)
        self.fill()

    # ------------------------------------------------------------------ scene access
    @property
    def scene(self):
        """The lens's scene (an empty one if it has none yet; it is created by the first edit)."""
        return NT.scene_of(self.doc.system) or ns.NonSequentialSystem(self.doc.system.name or "Scene")

    def current_table(self):
        return self.obj_table if self.tabs.currentIndex() == 0 else self.src_table

    def current_name(self):
        return "objects" if self.tabs.currentIndex() == 0 else "sources"

    def _edit(self, text, fn):
        """One undoable lens edit of the scene: ``fn(scene)`` (the scene is created if needed)."""
        out = {}

        def apply(system):
            out["v"] = fn(NT.scene_of(system, create=True))
        ok = self.doc.modify(text, apply)
        return out.get("v") if ok else None

    def _error(self, msg):
        if self.isVisible():
            self.statusBar().showMessage(f"Not changed: {msg}", 8000)

    # ------------------------------------------------------------------ tables
    def fill(self):
        try:
            self._fill()
        except RuntimeError:  # window being deleted
            pass

    def _fill(self):
        sc = self.scene
        missing = NT.missing_rows(sc)
        self._filling = True
        try:
            for table, name, labels in ((self.obj_table, "objects", OBJECT_LABELS),
                                        (self.src_table, "sources", SOURCE_LABELS)):
                rows = NT.table_rows(sc, name, missing)
                cur = table.currentRow()
                table.setRowCount(len(rows))
                table.setVerticalHeaderLabels([str(r + 1) if name == "objects" else f"S{r + 1}"
                                               for r in range(len(rows))])
                for r, row in enumerate(rows):
                    for c, v in enumerate(row["cells"]):
                        it = QTableWidgetItem(v if c else "")
                        if not row["editable"][c] or c == 0:
                            it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                        if not row["editable"][c] and c:
                            it.setBackground(QBrush(GREY))
                        if c in row["bad"]:
                            it.setBackground(QBrush(BAD))
                        it.setToolTip(row["tips"][c])
                        table.setItem(r, c, it)
                    combo = QComboBox()
                    for kind, lab in labels.items():
                        combo.addItem(lab, kind)
                    combo.setCurrentIndex(max(0, combo.findData(row["kind"])))
                    combo.setToolTip(NT.COLUMN_TIPS["Type"])
                    combo.currentIndexChanged.connect(
                        lambda _i, cb=combo, r=r, n=name: self.change_type(n, r, cb.currentData()))
                    table.setCellWidget(r, 0, combo)
                if 0 <= cur < len(rows):
                    table.setCurrentCell(cur, max(0, table.currentColumn()))
                table.resizeColumnsToContents()
            for key, w in self.trace_widgets.items():
                v = sc.trace_settings.get(key)
                w.blockSignals(True)
                if isinstance(w, QCheckBox):
                    w.setChecked(bool(v))
                else:
                    w.setValue(v)
                w.blockSignals(False)
        finally:
            self._filling = False
        self._update_headers(self.current_table())
        n_obj, n_src = len(sc.objects), len(sc.sources)
        self.tabs.setTabText(0, f"Objects ({n_obj})")
        self.tabs.setTabText(1, f"Sources ({n_src})")
        self.setWindowTitle(f"Non-Sequential Component Editor - {sc.name or self.doc.display_name}")

    def _update_headers(self, table):
        """Name the Par columns after the selected row's parameters (as Zemax's editor does)."""
        is_obj = table is self.obj_table
        lst = self.scene.objects if is_obj else self.scene.sources
        par0, n = (NT.OBJ_PAR0, NT.N_OBJ_PAR) if is_obj else (NT.SRC_PAR0, NT.N_SRC_PAR)
        r = table.currentRow()
        labels = NT.par_labels(lst[r]) if 0 <= r < len(lst) else [""] * n
        for k in range(n):
            h = table.horizontalHeaderItem(par0 + k)
            if h is not None:
                h.setText(labels[k] or f"Par {k + 1}")
                if k < n - 1:
                    table.resizeColumnToContents(par0 + k)

    def _cell_changed(self, item):
        if self._filling:
            return
        table = item.tableWidget()
        r, c = item.row(), item.column()
        is_obj = table is self.obj_table
        cols = OBJ_COLS if is_obj else SRC_COLS
        name = "objects" if is_obj else "sources"
        text = item.text()
        self._edit(f"{'Object' if is_obj else 'Source'} {r + 1} {cols[c]}",
                   lambda sc: NT.apply_cell(NT.items(sc, name)[r], c, text, is_obj))

    # ------------------------------------------------------------------ commands
    def change_type(self, table, row, kind):
        if self._filling:
            return
        self._edit(f"{table[:-1].capitalize()} {row + 1} type", lambda sc: NT.change_type(sc, table, row, kind))

    def add_item(self, kind):
        is_obj = kind in ns.OBJECT_TYPES
        t = self.obj_table if is_obj else self.src_table
        res = self._edit(f"Add {(OBJECT_LABELS if is_obj else SOURCE_LABELS)[kind]}",
                         lambda sc: NT.insert(sc, kind, t.currentRow()))
        if res:
            self.tabs.setCurrentIndex(0 if is_obj else 1)
            t.setCurrentCell(res[1], 1)
        return res

    def _selected(self):
        return self.current_name(), self.current_table().currentRow()

    def delete_row(self):
        name, r = self._selected()
        if r < 0:
            self.statusBar().showMessage("Select a row to delete first", 5000)
            return
        self._edit(f"Delete {name[:-1]} {r + 1}", lambda sc: NT.delete(sc, name, r))

    def duplicate_row(self):
        name, r = self._selected()
        if r < 0:
            self.statusBar().showMessage("Select a row to duplicate first", 5000)
            return
        new = self._edit(f"Duplicate {name[:-1]} {r + 1}", lambda sc: NT.duplicate(sc, name, r))
        if new is not None:
            self.current_table().setCurrentCell(new, 1)

    def move_row(self, delta):
        name, r = self._selected()
        if r < 0:
            return
        new = self._edit(f"Move {name[:-1]} {r + 1}", lambda sc: NT.move(sc, name, r, delta))
        if new is not None:
            self.current_table().setCurrentCell(new, max(1, self.current_table().currentColumn()))

    def _set_trace(self, key, value):
        if not self._filling:
            self._edit(f"Ray trace: {NT.TRACE_FIELDS[key][0]}", lambda sc: NT.set_trace_setting(sc, key, value))

    def new_scene(self, ask=True):
        sc = NT.scene_of(self.doc.system)
        if ask and sc is not None and (sc.objects or sc.sources):
            if QMessageBox.question(self, "New scene", "Delete every object and source of the scene?") != \
                    QMessageBox.Yes:
                return
        self.doc.modify("New non-sequential scene", lambda s: setattr(
            s, "nonseq", ns.NonSequentialSystem(s.name or "Scene", s.units, library=s.library)))

    def set_scene(self, scene, text="Replace non-sequential scene"):
        def fn(s):
            scene.library = s.library
            s.nonseq = scene
        return self.doc.modify(text, fn)

    def from_current_lens(self):
        try:
            scene = NT.from_lens(self.doc.system)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Convert lens", f"This lens cannot be converted: {e}")
            return False
        return self.set_scene(scene, "Convert lens to non-sequential")

    def open_scene(self, path=None):
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, "Import non-sequential scene", "",
                                                  "Non-sequential scenes (*.ns.json *.json);;All files (*)")
        if not path:
            return False
        try:
            scene = ns.load(path)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Import scene", f"Could not open {path}: {e}")
            return False
        return self.set_scene(scene, "Import non-sequential scene")

    def save_scene(self, path=None):
        if not path:
            path, _ = QFileDialog.getSaveFileName(self, "Export non-sequential scene",
                                                  f"{self.scene.name or 'scene'}.ns.json",
                                                  "Non-sequential scenes (*.ns.json)")
        if not path:
            return
        ns.save(self.scene, path)
        self.statusBar().showMessage(f"Saved {path}", 5000)

    def choose_material(self, row):
        from .material_dialog import MaterialDialog
        o = self.scene.objects[row]
        dlg = MaterialDialog(self.doc.system, o.material, f"Material of object {row + 1}", self)
        if dlg.exec() and dlg.spec is not None:
            spec = dlg.spec
            self._edit(f"Object {row + 1} Material",
                       lambda sc: NT.apply_cell(sc.objects[row], NT.MATERIAL_COL, spec, True))

    def _context_menu(self, table, pos):
        is_obj = table is self.obj_table
        r = table.rowAt(pos.y())
        if r >= 0:
            table.setCurrentCell(r, max(1, table.columnAt(pos.x())))
        m = QMenu(self)
        if is_obj and 0 <= r < len(self.scene.objects) and not self.scene.objects[r].is_detector:
            m.addAction("Choose Material...").triggered.connect(lambda: self.choose_material(r))
            m.addSeparator()
        for key in (("add_object",) if is_obj else ("add_source",)):
            sub = m.addMenu(self.actions_[key].icon(), BUTTONS[key][0])
            for kind, lab in (OBJECT_LABELS if is_obj else SOURCE_LABELS).items():
                sub.addAction(lab).triggered.connect(lambda _=False, k=kind: self.add_item(k))
        for key in ("duplicate", "move_up", "move_down", "delete"):
            m.addAction(self.actions_[key])
        m.exec(table.viewport().mapToGlobal(pos))

    def show_help(self):
        self.main.help_contents(HELP_ID)

    # ------------------------------------------------------------------ tracing
    def trace(self):
        """Trace the scene (in a worker) and show the summary; the analysis windows trace it too."""
        sc = NT.scene_of(self.doc.system)
        if sc is None:
            self.summary.setPlainText("The scene is empty: add objects and a source, or press From Current Lens.")
            return
        scene, lib = sc.copy(), self.doc.system.library
        self.summary.setPlainText("Tracing...")
        self.trace_btn.setEnabled(False)
        workers.submit(lambda progress: NT.trace(scene, lib), self._traced, self._failed)

    def _traced(self, tag, result):
        try:
            self.trace_btn.setEnabled(True)
            self.result = result
            self.summary.setPlainText(NT.trace_report(result))
        except RuntimeError:
            pass

    def _failed(self, tag, msg):
        try:
            self.trace_btn.setEnabled(True)
            self.result = None
            self.summary.setPlainText(f"Trace failed: {msg}")
        except RuntimeError:
            pass
