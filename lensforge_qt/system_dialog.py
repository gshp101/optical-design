"""System Explorer: aperture, fields, wavelengths, units and ray aiming.

The dialog edits a copy of the settings; OK / Apply write them to the lens as
one undoable change.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
                               QHeaderView, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QTableWidget,
                               QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget, QLabel)

from lensforge.system import APERTURE_TYPES, FIELD_TYPES, Field, Wavelength

from . import edits as E

APERTURE_LABELS = {"EPD": "Entrance Pupil Diameter", "IMAGE_FNUM": "Image Space F/#",
                   "OBJECT_NA": "Object Space NA", "STOP_SIZE": "Float By Stop Size",
                   "WORKING_FNUM": "Paraxial Working F/#"}
FIELD_LABELS = {"ANGLE": "Angle (degrees)", "OBJECT_HEIGHT": "Object Height",
                "PARAXIAL_IMAGE_HEIGHT": "Paraxial Image Height", "REAL_IMAGE_HEIGHT": "Real Image Height"}
WAVE_PRESETS = {
    "F, d, C (visible)": ([0.4861327, 0.5875618, 0.6562725], 1),
    "F', e, C' (visible)": ([0.4799914, 0.5460740, 0.6438470], 1),
    "d (0.5876)": ([0.5875618], 0),
    "e (0.5461)": ([0.5460740], 0),
    "HeNe (0.6328)": ([0.6328], 0),
    "Nd:YAG (1.064)": ([1.064], 0),
    "NIR 0.8 / 0.85 / 0.9": ([0.8, 0.85, 0.9], 1),
    "SWIR 1.0 / 1.3 / 1.55": ([1.0, 1.3, 1.55], 1),
    "LWIR 8 / 10 / 12": ([8.0, 10.0, 12.0], 1),
}
FIELD_COLUMNS = ["X", "Y", "Weight", "VDX", "VDY", "VCX", "VCY"]
FIELD_ATTRS = ["x", "y", "weight", "vdx", "vdy", "vcx", "vcy"]


def _table(headers):
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
    t.verticalHeader().setDefaultSectionSize(22)
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    return t


def _num(t, r, c, default=0.0):
    it = t.item(r, c)
    txt = it.text().strip() if it else ""
    return default if not txt else E.parse_number(txt, allow_inf=False)


class SystemExplorer(QDialog):
    def __init__(self, doc, parent=None, tab: int = 0):
        super().__init__(parent)
        self.doc = doc
        self.setWindowTitle("System Explorer")
        self.resize(620, 460)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._aperture_tab(), "Aperture")
        self.tabs.addTab(self._fields_tab(), "Fields")
        self.tabs.addTab(self._wave_tab(), "Wavelengths")
        self.tabs.addTab(self._general_tab(), "General")
        self.tabs.setCurrentIndex(tab)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Apply | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        bb.button(QDialogButtonBox.Apply).clicked.connect(self.apply)
        lay = QVBoxLayout(self)
        lay.addWidget(self.tabs)
        lay.addWidget(bb)
        self.load()

    # -- tabs ---------------------------------------------------------------------
    def _aperture_tab(self):
        w = QWidget()
        f = QFormLayout(w)
        self.ap_type = QComboBox()
        for k in APERTURE_TYPES:
            self.ap_type.addItem(APERTURE_LABELS[k], k)
        self.ap_value = QLineEdit()
        self.aiming = QComboBox()
        self.aiming.addItem("Paraxial", "paraxial")
        self.aiming.addItem("Real", "real")
        f.addRow("Aperture Type", self.ap_type)
        f.addRow("Aperture Value", self.ap_value)
        f.addRow("Ray Aiming", self.aiming)
        return w

    def _fields_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        top = QHBoxLayout()
        self.field_type = QComboBox()
        for k in FIELD_TYPES:
            self.field_type.addItem(FIELD_LABELS[k], k)
        top.addWidget(QLabel("Field Type"))
        top.addWidget(self.field_type, 1)
        lay.addLayout(top)
        self.field_table = _table(FIELD_COLUMNS)
        lay.addWidget(self.field_table)
        row = QHBoxLayout()
        add = QPushButton("Add Field")
        rem = QPushButton("Remove Field")
        eq = QPushButton("Equal-Area Fields...")
        add.clicked.connect(lambda: self._add_row(self.field_table, ["0", "0", "1", "0", "0", "0", "0"]))
        rem.clicked.connect(lambda: self._remove_rows(self.field_table))
        eq.clicked.connect(self._equal_area)
        for b in (add, rem, eq):
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        return w

    def _wave_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        self.wave_table = _table(["Wavelength (um)", "Weight", "Primary"])
        lay.addWidget(self.wave_table)
        row = QHBoxLayout()
        add = QPushButton("Add Wavelength")
        rem = QPushButton("Remove Wavelength")
        prim = QPushButton("Make Primary")
        self.preset = QComboBox()
        self.preset.addItem("Presets...")
        self.preset.addItems(list(WAVE_PRESETS))
        add.clicked.connect(lambda: self._add_row(self.wave_table, ["0.55", "1", ""]))
        rem.clicked.connect(lambda: self._remove_rows(self.wave_table))
        prim.clicked.connect(self._make_primary)
        self.preset.activated.connect(self._apply_preset)
        for b in (add, rem, prim, self.preset):
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        return w

    def _general_tab(self):
        w = QWidget()
        f = QFormLayout(w)
        self.name = QLineEdit()
        self.units = QComboBox()
        for u in ("mm", "cm", "m", "in"):
            self.units.addItem(u)
        self.notes = QPlainTextEdit()
        f.addRow("Lens Title", self.name)
        f.addRow("Lens Units", self.units)
        f.addRow("Notes", self.notes)
        return w

    # -- helpers ------------------------------------------------------------------
    def _add_row(self, t, values):
        r = t.rowCount()
        t.insertRow(r)
        for c, v in enumerate(values):
            it = QTableWidgetItem(v)
            if t is self.wave_table and c == 2:
                it.setFlags(it.flags() & ~Qt.ItemIsEditable)
            t.setItem(r, c, it)

    def _remove_rows(self, t):
        rows = sorted({i.row() for i in t.selectedIndexes()}, reverse=True) or [t.rowCount() - 1]
        for r in rows:
            if t.rowCount() > 1:
                t.removeRow(r)
        if t is self.wave_table and not any(self._is_primary(r) for r in range(t.rowCount())):
            self._set_primary(0)

    def _is_primary(self, r):
        it = self.wave_table.item(r, 2)
        return bool(it and it.text())

    def _set_primary(self, r):
        for k in range(self.wave_table.rowCount()):
            it = self.wave_table.item(k, 2)
            if it is None:
                it = QTableWidgetItem()
                self.wave_table.setItem(k, 2, it)
            it.setText("primary" if k == r else "")

    def _make_primary(self):
        r = self.wave_table.currentRow()
        if r >= 0:
            self._set_primary(r)

    def _apply_preset(self, i):
        if i <= 0:
            return
        waves, prim = WAVE_PRESETS[self.preset.itemText(i)]
        self.wave_table.setRowCount(0)
        for w in waves:
            self._add_row(self.wave_table, [f"{w:g}", "1", ""])
        self._set_primary(prim)
        self.preset.setCurrentIndex(0)

    def _equal_area(self):
        """Replace the fields by n equal-area fields up to the current maximum y field."""
        ys = [abs(_num(self.field_table, r, 1)) for r in range(self.field_table.rowCount())]
        ymax = max(ys) if ys and max(ys) > 0 else 1.0
        n = 5
        self.field_table.setRowCount(0)
        for k in range(n):
            y = ymax * (k / (n - 1)) ** 0.5
            self._add_row(self.field_table, ["0", f"{y:.6g}", "1", "0", "0", "0", "0"])

    # -- load / apply -------------------------------------------------------------
    def load(self):
        s = self.doc.system
        self.ap_type.setCurrentIndex(APERTURE_TYPES.index(s.aperture_type))
        self.ap_value.setText(repr(s.aperture_value))
        self.aiming.setCurrentIndex(0 if s.ray_aiming == "paraxial" else 1)
        self.field_type.setCurrentIndex(FIELD_TYPES.index(s.field_type))
        self.field_table.setRowCount(0)
        for f in s.fields:
            self._add_row(self.field_table, [E.format_number(getattr(f, a), 10) for a in FIELD_ATTRS])
        self.wave_table.setRowCount(0)
        for w in s.wavelengths:
            self._add_row(self.wave_table, [f"{w.value:.10g}", E.format_number(w.weight, 10), ""])
        self._set_primary(s.primary_wavelength)
        self.name.setText(s.name)
        self.units.setCurrentText(s.units)
        self.notes.setPlainText(s.notes)

    def collect(self):
        fields = [Field(**{a: _num(self.field_table, r, c, 1.0 if a == "weight" else 0.0)
                           for c, a in enumerate(FIELD_ATTRS)}) for r in range(self.field_table.rowCount())]
        waves = [Wavelength(_num(self.wave_table, r, 0), _num(self.wave_table, r, 1, 1.0))
                 for r in range(self.wave_table.rowCount())]
        if not fields or not waves:
            raise ValueError("at least one field and one wavelength are needed")
        if any(w.value <= 0 for w in waves):
            raise ValueError("wavelengths must be positive")
        prim = next((r for r in range(self.wave_table.rowCount()) if self._is_primary(r)), 0)
        value = E.parse_number(self.ap_value.text(), allow_inf=False)
        if value <= 0:
            raise ValueError("the aperture value must be positive")
        return dict(aperture_type=self.ap_type.currentData(), aperture_value=value,
                    ray_aiming=self.aiming.currentData(), field_type=self.field_type.currentData(),
                    fields=fields, wavelengths=waves, primary_wavelength=prim, name=self.name.text(),
                    units=self.units.currentText(), notes=self.notes.toPlainText())

    def apply(self) -> bool:
        try:
            vals = self.collect()
        except ValueError as e:
            QMessageBox.warning(self, "System Explorer", str(e))
            return False

        def fn(s):
            for k, v in vals.items():
                setattr(s, k, v)
        return self.doc.modify("System settings", fn)

    def _ok(self):
        if self.apply():
            self.accept()
