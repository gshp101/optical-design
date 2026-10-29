"""Input Rays dialog: ray sampling of the ray-based analyses and user-defined rays."""

from __future__ import annotations

from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox,
                               QHBoxLayout, QHeaderView, QListWidget, QListWidgetItem, QMessageBox,
                               QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)
from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPen

from lensforge import pupil_grid

from . import edits as E
from . import rays as R

USER_COLUMNS = ["Hx", "Hy", "Px", "Py", "Wavelength"]


class PupilPatternPreview(QWidget):
    """Small picture of the pupil sampling: the unit pupil and every ray the spot diagram traces."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(150, 168)
        self.px, self.py = pupil_grid("hexapolar", 6)
        self.setToolTip("Where the spot diagram's rays cross the entrance pupil (traced for every field and wavelength)")

    def sizeHint(self):
        return QSize(170, 190)

    def set_pattern(self, pattern: str, n: int):
        self.px, self.py = pupil_grid(pattern, n)
        self.update()

    @property
    def count(self) -> int:
        return len(self.px)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pal = self.palette()
        text_h = p.fontMetrics().height() + 4
        side = min(self.width(), self.height() - text_h) - 8
        r = side / 2
        c = QPointF(self.width() / 2, 4 + r)
        p.setPen(QPen(pal.mid().color(), 1))
        p.setBrush(pal.base())
        p.drawEllipse(c, r, r)
        p.setPen(QPen(pal.mid().color(), 1, Qt.DotLine))
        p.drawLine(QPointF(c.x() - r, c.y()), QPointF(c.x() + r, c.y()))
        p.drawLine(QPointF(c.x(), c.y() - r), QPointF(c.x(), c.y() + r))
        n = len(self.px)
        dot = max(0.8, min(3.0, 0.9 * r / max(n, 1) ** 0.5))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#1f5f99"))
        for x, y in zip(self.px, self.py):
            p.drawEllipse(QPointF(c.x() + x * r, c.y() - y * r), dot, dot)
        p.setPen(pal.text().color())
        p.drawText(QRectF(0, 4 + side + 2, self.width(), text_h), Qt.AlignHCenter | Qt.AlignTop,
                   f"{n} rays")
        p.end()


class InputRaysDialog(QDialog):
    def __init__(self, doc, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.setWindowTitle("Input Rays")
        self.resize(640, 640)
        s = doc.system
        ir = R.get(s)

        # layout rays
        lay_box = QGroupBox("Layout rays")
        f = QFormLayout(lay_box)
        self.layout_rays = QSpinBox()
        self.layout_rays.setRange(1, 101)
        self.layout_rays.setValue(ir["layout_rays"])
        self.layout_plane = QComboBox()
        self.layout_plane.addItem("Y-Z fan (meridional)", "y")
        self.layout_plane.addItem("X-Z fan (sagittal)", "x")
        self.layout_plane.setCurrentIndex(0 if ir["layout_plane"] == "y" else 1)
        self.layout_fields = self._check_list([f"Field {k + 1}: ({x.x:g}, {x.y:g})" for k, x in enumerate(s.fields)],
                                              R.fields(s, ir["layout_fields"]))
        self.layout_waves = self._check_list([f"{w.value:.4f} um" + (" (primary)" if k == s.primary_wavelength
                                                                      else "") for k, w in enumerate(s.wavelengths)],
                                             self._wave_indices(s, ir["layout_waves"]))
        f.addRow("Rays per fan", self.layout_rays)
        f.addRow("Fan plane", self.layout_plane)
        row = QHBoxLayout()
        row.addWidget(self.layout_fields)
        row.addWidget(self.layout_waves)
        f.addRow("Fields / wavelengths", row)

        # pupil sampling
        samp = QGroupBox("Pupil sampling (spot diagrams, fans, footprints)")
        g = QFormLayout()
        self.preview = PupilPatternPreview()
        sl = QHBoxLayout(samp)
        sl.addLayout(g, 1)
        sl.addWidget(self.preview, 0, Qt.AlignTop)
        self.pattern = QComboBox()
        for p in R.PATTERNS:
            self.pattern.addItem(p.title(), p)
        self.pattern.setCurrentIndex(max(0, R.PATTERNS.index(ir["spot_pattern"])))
        self.rings = QSpinBox()
        self.rings.setRange(1, 100)
        self.rings.setValue(ir["spot_rings"])
        self.reference = QComboBox()
        self.reference.addItem("Chief ray", "chief")
        self.reference.addItem("Centroid", "centroid")
        self.reference.setCurrentIndex(0 if ir["spot_reference"] == "chief" else 1)
        self.fan_points = QSpinBox()
        self.fan_points.setRange(3, 1001)
        self.fan_points.setValue(ir["fan_points"])
        self.footprint_rays = QSpinBox()
        self.footprint_rays.setRange(8, 2000)
        self.footprint_rays.setValue(ir["footprint_rays"])
        g.addRow("Spot pattern", self.pattern)
        g.addRow("Rings / grid size", self.rings)
        g.addRow("Spot reference", self.reference)
        g.addRow("Fan points", self.fan_points)
        g.addRow("Footprint rays per beam", self.footprint_rays)
        self.pattern.currentIndexChanged.connect(self._update_preview)
        self.rings.valueChanged.connect(self._update_preview)
        self._update_preview()

        # user rays
        ub = QGroupBox("User-defined rays (normalised field Hx, Hy and pupil Px, Py; drawn in red on the layout)")
        ul = QVBoxLayout(ub)
        self.table = QTableWidget(0, len(USER_COLUMNS))
        self.table.setHorizontalHeaderLabels(USER_COLUMNS)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setDefaultSectionSize(22)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        for ray in ir["user_rays"]:
            self.add_ray(ray)
        btns = QHBoxLayout()
        for text, slot in (("Add Ray", lambda: self.add_ray()), ("Add Marginal + Chief Rays", self.add_standard),
                           ("Remove Rays", self.remove_rays)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            btns.addWidget(b)
        btns.addStretch(1)
        ul.addWidget(self.table)
        ul.addLayout(btns)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Apply | QDialogButtonBox.Cancel
                              | QDialogButtonBox.RestoreDefaults)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        bb.button(QDialogButtonBox.Apply).clicked.connect(self.apply)
        bb.button(QDialogButtonBox.RestoreDefaults).clicked.connect(self.restore_defaults)
        lay = QVBoxLayout(self)
        lay.addWidget(lay_box)
        lay.addWidget(samp)
        lay.addWidget(ub, 1)
        lay.addWidget(bb)

    # -- helpers -----------------------------------------------------------------
    @staticmethod
    def _wave_indices(s, spec):
        if spec == "primary" or spec is None:
            return [s.primary_wavelength]
        if spec == "all":
            return list(range(len(s.wavelengths)))
        return [int(i) for i in spec]

    @staticmethod
    def _check_list(labels, checked):
        w = QListWidget()
        for k, lab in enumerate(labels):
            it = QListWidgetItem(lab)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if k in checked else Qt.Unchecked)
            w.addItem(it)
        w.setMaximumHeight(110)
        return w

    @staticmethod
    def _checked(w):
        return [k for k in range(w.count()) if w.item(k).checkState() == Qt.Checked]

    def _wave_combo(self, value=-1):
        cb = QComboBox()
        cb.addItem("Primary", -1)
        for k, w in enumerate(self.doc.system.wavelengths):
            cb.addItem(f"{k + 1}: {w.value:.4f} um", k)
        cb.setCurrentIndex(max(0, cb.findData(int(value))))
        return cb

    def add_ray(self, ray=None):
        ray = ray or {"hx": 0.0, "hy": 1.0, "px": 0.0, "py": 1.0, "wave": -1}
        r = self.table.rowCount()
        self.table.insertRow(r)
        for c, k in enumerate(("hx", "hy", "px", "py")):
            self.table.setItem(r, c, QTableWidgetItem(E.format_number(ray[k])))
        self.table.setCellWidget(r, 4, self._wave_combo(ray.get("wave", -1)))

    def add_standard(self):
        for hy, py in ((0.0, 1.0), (0.0, -1.0), (1.0, 0.0), (1.0, 1.0), (1.0, -1.0)):
            self.add_ray({"hx": 0.0, "hy": hy, "px": 0.0, "py": py, "wave": -1})

    def remove_rays(self):
        for r in sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True):
            self.table.removeRow(r)

    def _update_preview(self, *_):
        pattern = self.pattern.currentData()
        self.preview.set_pattern(pattern, self.rings.value())
        self.rings.setToolTip("Number of rings" if pattern == "hexapolar" else
                              "Grid size: n x n rays clipped to the pupil" if pattern != "random" else
                              "n x n random rays")

    def restore_defaults(self):
        d = R.DEFAULTS
        self.layout_rays.setValue(d["layout_rays"])
        self.layout_plane.setCurrentIndex(0)
        s = self.doc.system
        for w, on in ((self.layout_fields, range(len(s.fields))), (self.layout_waves, [s.primary_wavelength])):
            for k in range(w.count()):
                w.item(k).setCheckState(Qt.Checked if k in on else Qt.Unchecked)
        self.pattern.setCurrentIndex(0)
        self.rings.setValue(d["spot_rings"])
        self.reference.setCurrentIndex(0)
        self.fan_points.setValue(d["fan_points"])
        self.footprint_rays.setValue(d["footprint_rays"])
        self.table.setRowCount(0)

    # -- apply ---------------------------------------------------------------------
    def collect(self) -> dict:
        s = self.doc.system
        fields = self._checked(self.layout_fields)
        waves = self._checked(self.layout_waves)
        if not fields or not waves:
            raise ValueError("choose at least one field and one wavelength for the layout")
        users = []
        for r in range(self.table.rowCount()):
            vals = {}
            for c, k in enumerate(("hx", "hy", "px", "py")):
                it = self.table.item(r, c)
                vals[k] = E.parse_number(it.text() if it else "0", allow_inf=False)
            vals["wave"] = self.table.cellWidget(r, 4).currentData()
            users.append(vals)
        return {
            "layout_rays": self.layout_rays.value(), "layout_plane": self.layout_plane.currentData(),
            "layout_fields": "all" if len(fields) == len(s.fields) else fields,
            "layout_waves": ("primary" if waves == [s.primary_wavelength] else
                             "all" if len(waves) == len(s.wavelengths) else waves),
            "spot_pattern": self.pattern.currentData(), "spot_rings": self.rings.value(),
            "spot_reference": self.reference.currentData(), "fan_points": self.fan_points.value(),
            "footprint_rays": self.footprint_rays.value(), "user_rays": users}

    def apply(self) -> bool:
        try:
            vals = self.collect()
        except ValueError as e:
            QMessageBox.warning(self, "Input Rays", str(e))
            return False
        return self.doc.modify("Input rays", lambda s: R.set(s, vals))

    def _ok(self):
        if self.apply():
            self.accept()

