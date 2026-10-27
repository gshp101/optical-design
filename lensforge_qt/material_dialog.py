"""Material picker: catalog glasses (table + clickable glass map), model glass, or other media."""

from __future__ import annotations

import math

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                               QFileDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QMessageBox, QPushButton, QRadioButton, QSplitter, QTableWidget, QTableWidgetItem,
                               QTabWidget, QVBoxLayout, QWidget)

from lensforge.materials import ConstantIndex, ModelGlass

from . import edits as E


def catalog_rows(library):
    """(spec, catalog, name, nd, vd) for every refracting catalog glass."""
    names = {}
    rows = []
    for cname, cat in library.catalogs.items():
        for g in cat:
            try:
                nd, vd = float(g.nd), float(g.vd)
            except Exception:  # noqa: BLE001 - glass outside its data range
                continue
            if nd <= 1.0 or not math.isfinite(vd):
                continue
            names[g.name.upper()] = names.get(g.name.upper(), 0) + 1
            rows.append([None, cname, g.name, nd, vd])
    for r in rows:  # plain name when unique, CATALOG:NAME otherwise
        r[0] = r[2] if names[r[2].upper()] == 1 else f"{r[1]}:{r[2]}"
    return [tuple(r) for r in rows]


class MaterialDialog(QDialog):
    """Choose the material after a surface.  :attr:`spec` holds the chosen spec
    ("" for air) after the dialog is accepted."""

    def __init__(self, system, current=None, title="Choose Material", parent=None):
        super().__init__(parent)
        self.system = system
        self.spec = None
        self.setWindowTitle(title)
        self.resize(860, 560)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._catalog_tab(), "Catalog Glass")
        self.tabs.addTab(self._model_tab(), "Model Glass")
        self.tabs.addTab(self._other_tab(), "Other")
        self.preview = QLabel()
        self.preview.setWordWrap(True)
        self.preview.setStyleSheet("padding: 4px;")
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(self.tabs, 1)
        lay.addWidget(self.preview)
        lay.addWidget(bb)
        self.tabs.currentChanged.connect(lambda _: self._update_preview())
        self._select_current(current)

    # -- catalog tab ------------------------------------------------------------------
    def _catalog_tab(self):
        w = QWidget()
        top = QHBoxLayout()
        self.catalog = QComboBox()
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter by name, e.g. SF or BK")
        load = QPushButton("Load AGF Catalog...")
        load.clicked.connect(self._load_agf)
        top.addWidget(QLabel("Catalog"))
        top.addWidget(self.catalog)
        top.addWidget(self.filter, 1)
        top.addWidget(load)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Glass", "Catalog", "nd", "Vd"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(20)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.itemSelectionChanged.connect(self._table_selected)
        self.table.itemDoubleClicked.connect(lambda _: self._accept())
        self.figure = Figure(figsize=(4, 3.5), dpi=80, layout="tight")
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.canvas.mpl_connect("button_press_event", self._map_clicked)
        split = QSplitter(Qt.Horizontal)
        split.addWidget(self.table)
        split.addWidget(self.canvas)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 1)
        lay = QVBoxLayout(w)
        lay.addLayout(top)
        lay.addWidget(split, 1)
        lay.addWidget(QLabel("Click a glass on the map (Abbe diagram) or in the table; double-click to choose."))
        self.catalog.currentIndexChanged.connect(lambda _: self._fill_table())
        self.filter.textChanged.connect(lambda _: self._fill_table())
        self._reload_catalogs()
        return w

    def _reload_catalogs(self):
        self.rows = catalog_rows(self.system.library)
        self.catalog.blockSignals(True)
        self.catalog.clear()
        self.catalog.addItem("All", None)
        for c in self.system.library.catalogs:
            self.catalog.addItem(c, c)
        self.catalog.blockSignals(False)
        self._fill_table()

    def _visible_rows(self):
        cat, t = self.catalog.currentData(), self.filter.text().strip().upper()
        return [r for r in self.rows if (cat is None or r[1] == cat) and (not t or t in r[2].upper())]

    def _fill_table(self):
        rows = self._visible_rows()
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))
        for k, (spec, cat, name, nd, vd) in enumerate(rows):
            it = QTableWidgetItem(name)
            it.setData(Qt.UserRole, spec)
            self.table.setItem(k, 0, it)
            self.table.setItem(k, 1, QTableWidgetItem(cat))
            for c, v in ((2, nd), (3, vd)):
                it = QTableWidgetItem()
                it.setData(Qt.DisplayRole, round(v, 5 if c == 2 else 2))
                self.table.setItem(k, c, it)
        self.table.setSortingEnabled(True)
        self._draw_map()

    def _draw_map(self, highlight=None):
        self.figure.clear()
        ax = self.figure.add_subplot(111)
        rows = self._visible_rows()
        if rows:
            vd = np.array([r[4] for r in rows])
            nd = np.array([r[3] for r in rows])
            ax.scatter(vd, nd, s=14, color="C0")
            for r in rows:
                ax.annotate(r[2], (r[4], r[3]), fontsize=6, color="0.35", xytext=(2, 2), textcoords="offset points")
        if highlight is not None:
            ax.scatter([highlight[1]], [highlight[0]], s=90, facecolors="none", edgecolors="crimson", lw=2)
        ax.set_xlabel("Abbe number Vd")
        ax.set_ylabel("index nd")
        ax.invert_xaxis()
        ax.grid(alpha=0.3)
        ax.set_title("Glass map", fontsize=9)
        self.canvas.draw_idle()

    def _map_clicked(self, ev):
        if ev.xdata is None or ev.ydata is None:
            return
        rows = self._visible_rows()
        if not rows:
            return
        ax = ev.inaxes
        xr = abs(np.diff(ax.get_xlim())[0]) or 1.0
        yr = abs(np.diff(ax.get_ylim())[0]) or 1.0
        d = [((r[4] - ev.xdata) / xr) ** 2 + ((r[3] - ev.ydata) / yr) ** 2 for r in rows]
        self.select_spec(rows[int(np.argmin(d))][0])

    def select_spec(self, spec):
        for k in range(self.table.rowCount()):
            if self.table.item(k, 0).data(Qt.UserRole) == spec:
                self.table.selectRow(k)
                self.table.scrollToItem(self.table.item(k, 0))
                return True
        return False

    def _table_selected(self):
        r = self._current_row()
        if r is not None:
            self._draw_map((r[3], r[4]))
        self._update_preview()

    def _current_row(self):
        items = self.table.selectedItems()
        if not items:
            return None
        spec = self.table.item(items[0].row(), 0).data(Qt.UserRole)
        return next((r for r in self.rows if r[0] == spec), None)

    def _load_agf(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load AGF glass catalog", "", "AGF catalogs (*.agf *.AGF)")
        if path:
            try:
                self.system.library.load_agf(path)
            except Exception as e:  # noqa: BLE001
                QMessageBox.critical(self, "Glass catalog", f"Could not load {path}:\n{e}")
                return
            main = self.parent().window() if self.parent() else None
            if hasattr(main, "remember_agf"):
                main.remember_agf(path)
            self._reload_catalogs()

    # -- model / other tabs ------------------------------------------------------------
    def _model_tab(self):
        w = QWidget()
        f = QFormLayout(w)
        self.m_nd = QDoubleSpinBox()
        self.m_nd.setDecimals(6)
        self.m_nd.setRange(1.0, 4.5)
        self.m_nd.setValue(1.5168)
        self.m_vd = QDoubleSpinBox()
        self.m_vd.setDecimals(3)
        self.m_vd.setRange(5, 120)
        self.m_vd.setValue(64.17)
        self.m_dp = QDoubleSpinBox()
        self.m_dp.setDecimals(5)
        self.m_dp.setRange(-0.1, 0.1)
        for sb in (self.m_nd, self.m_vd, self.m_dp):
            sb.valueChanged.connect(lambda _: self._update_preview())
        f.addRow("nd", self.m_nd)
        f.addRow("Vd", self.m_vd)
        f.addRow("dPgF", self.m_dp)
        f.addRow(QLabel("A model glass is defined by its index and Abbe number; it can be optimised "
                        "(Vary Glass) and later snapped to the nearest catalog glass."))
        return w

    def _other_tab(self):
        w = QWidget()
        f = QFormLayout(w)
        self.o_air = QRadioButton("Air (no material)")
        self.o_mirror = QRadioButton("Mirror (reflecting surface)")
        self.o_const = QRadioButton("Constant index")
        self.o_air.setChecked(True)
        self.o_n = QDoubleSpinBox()
        self.o_n.setDecimals(6)
        self.o_n.setRange(0.01, 10)
        self.o_n.setValue(1.333)
        for b in (self.o_air, self.o_mirror, self.o_const):
            b.toggled.connect(lambda _: self._update_preview())
        self.o_n.valueChanged.connect(lambda _: self._update_preview())
        f.addRow(self.o_air)
        f.addRow(self.o_mirror)
        f.addRow(self.o_const, self.o_n)
        return w

    # -- result ---------------------------------------------------------------------------
    def chosen_spec(self):
        tab = self.tabs.currentIndex()
        if tab == 0:
            r = self._current_row()
            return None if r is None else r[0]
        if tab == 1:
            dp = self.m_dp.value()
            return f"{self.m_nd.value():.6g},{self.m_vd.value():.6g}" + (f",{dp:.5g}" if dp else "")
        if self.o_mirror.isChecked():
            return "MIRROR"
        if self.o_const.isChecked():
            return f"{self.o_n.value():.6g}"
        return ""

    def _update_preview(self):
        spec = self.chosen_spec()
        if spec is None:
            self.preview.setText("Select a glass.")
            return
        if spec in ("", "MIRROR"):
            self.preview.setText("Air" if spec == "" else "Mirror")
            return
        try:
            m = self.system.library.resolve(spec)
            idx = ", ".join(f"n({w.value:.4f}) = {float(m.index(w.value)):.6f}" for w in self.system.wavelengths)
            self.preview.setText(f"<b>{spec}</b>: nd {m.nd:.6f}, Vd {m.vd:.3f}<br>{idx}")
        except Exception as e:  # noqa: BLE001
            self.preview.setText(f"{spec}: {e}")

    def _select_current(self, current):
        m = None
        try:
            m = self.system.library.resolve(current)
        except Exception:  # noqa: BLE001
            pass
        if current is None or current == "" or (m is not None and not m.is_mirror and m.nd == 1.0
                                                 and isinstance(m, ConstantIndex)):
            self.tabs.setCurrentIndex(2)
            self.o_air.setChecked(True)
        elif m is not None and m.is_mirror:
            self.tabs.setCurrentIndex(2)
            self.o_mirror.setChecked(True)
        elif isinstance(m, ModelGlass):
            self.tabs.setCurrentIndex(1)
            self.m_nd.setValue(m.nd_value)
            self.m_vd.setValue(m.vd_value)
            self.m_dp.setValue(m.dpgf)
        elif isinstance(m, ConstantIndex):
            self.tabs.setCurrentIndex(2)
            self.o_const.setChecked(True)
            self.o_n.setValue(m.n)
        elif m is not None:
            name = getattr(m, "name", "")
            cat = getattr(m, "catalog", None)
            spec = next((r[0] for r in self.rows if r[2] == name and (cat is None or r[1] == cat)), None)
            self.tabs.setCurrentIndex(0)
            if spec:
                self.select_spec(spec)
        self._update_preview()

    def _accept(self):
        spec = self.chosen_spec()
        if spec is None:
            QMessageBox.information(self, "Material", "Select a glass first.")
            return
        try:
            E.parse_material(self.system, spec)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Material", str(e))
            return
        self.spec = spec
        self.accept()
