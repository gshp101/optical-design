"""File > Insert Lens: put surfaces from a lens file into the current design (scaled, optionally reversed,
optionally with the lens's semi-diameters)."""

from __future__ import annotations

import math
import os

from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QSpinBox, QVBoxLayout)

import lensforge as lf
from lensforge.compose import lens_surfaces

from . import edits as E
from .fonts import fixed_font

FILE_FILTER = "Lens files (*.json *.zmx);;lensforge JSON (*.json);;Zemax ZMX (*.zmx);;All files (*)"


class InsertLensDialog(QDialog):
    """Pick a lens file, a surface range, where to insert, a scale factor and the order."""

    def __init__(self, doc, at: int = None, start_dir: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Insert Lens")
        self.resize(720, 560)
        self.doc = doc
        self.start_dir = start_dir
        self.source = None

        self.path = QLineEdit(placeholderText="Lens file (.json or .zmx) to insert")
        self.path.editingFinished.connect(lambda: self.load(self.path.text()))
        browse = QPushButton("Browse...")
        browse.clicked.connect(self.browse)
        row = QHBoxLayout()
        row.addWidget(self.path, 1)
        row.addWidget(browse)

        self.first = QSpinBox(minimum=1, maximum=1)
        self.last = QSpinBox(minimum=1, maximum=1)
        self.at = QSpinBox(minimum=1, maximum=doc.system.image_index)
        self.at.setValue(doc.system.image_index if at is None else max(1, min(at, doc.system.image_index)))
        self.at.setToolTip("The inserted surfaces go in front of this surface of the current lens")
        self.scale = QDoubleSpinBox(decimals=6, minimum=1e-6, maximum=1e6, value=1.0, singleStep=0.1)
        self.scale.setToolTip("Every length (radii, thicknesses, semi-diameters, aspheric terms) is multiplied")
        self.reverse = QCheckBox("Reverse the surface order (turn the lens round)")
        self.keep_stop = QCheckBox("Use the inserted lens's stop surface as the system stop")
        self.units = QCheckBox("Convert units to the current lens's units")
        self.units.setChecked(True)
        self.copy_sd = QCheckBox("Copy semi-diameters from the inserted lens")
        self.copy_sd.setToolTip("Checked: each surface keeps the semi-diameter it has in the lens file (automatic "
                                "ones are computed there), as a fixed value, scaled.\n"
                                "Unchecked: the inserted surfaces get automatic semi-diameters.")
        for w in (self.first, self.last, self.at):
            w.valueChanged.connect(self.update_preview)
        self.scale.valueChanged.connect(self.update_preview)
        for w in (self.reverse, self.keep_stop, self.units, self.copy_sd):
            w.toggled.connect(self.update_preview)

        rng = QHBoxLayout()
        rng.addWidget(self.first)
        rng.addWidget(QLabel("to"))
        rng.addWidget(self.last)
        rng.addStretch(1)
        form = QFormLayout()
        form.addRow("File:", row)
        form.addRow("Surfaces:", rng)
        form.addRow("Insert before surface:", self.at)
        form.addRow("Scale factor:", self.scale)
        form.addRow("", self.reverse)
        form.addRow("", self.keep_stop)
        form.addRow("", self.units)
        form.addRow("", self.copy_sd)

        mono = fixed_font()
        self.preview = QPlainTextEdit(readOnly=True)
        self.preview.setFont(mono)
        self.preview.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.info = QLabel()
        self.info.setWordWrap(True)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Ok).setText("Insert")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(QLabel("Surfaces to insert (scaled and in the order they will be inserted):"))
        lay.addWidget(self.preview, 1)
        lay.addWidget(self.info)
        lay.addWidget(self.buttons)
        self.update_preview()

    # ------------------------------------------------------------------
    def browse(self):
        path, _ = QFileDialog.getOpenFileName(self, "Insert Lens", self.start_dir, FILE_FILTER)
        if path:
            self.load(path)

    def load(self, path: str):
        if not path or (self.source is not None and path == getattr(self, "_loaded", None)):
            return
        try:
            src = lf.load(path)
        except Exception as e:  # unreadable file: say so in the dialog
            self.source = None
            self.info.setText(f"<span style='color:#b00020'>Cannot read {os.path.basename(path)}: {e}</span>")
            self.update_preview()
            return
        self.source, self._loaded = src, path
        self.path.setText(path)
        n = src.image_index - 1
        for w in (self.first, self.last):
            w.blockSignals(True)
            w.setMaximum(max(1, n))
        self.first.setValue(1)
        self.last.setValue(max(1, n))
        for w in (self.first, self.last):
            w.blockSignals(False)
        self.update_preview()

    def options(self) -> dict:
        return dict(first=self.first.value(), last=max(self.first.value(), self.last.value()),
                    scale=self.scale.value(), reverse=self.reverse.isChecked(),
                    keep_stop=self.keep_stop.isChecked(), convert_units=self.units.isChecked(),
                    copy_semi_diameters=self.copy_sd.isChecked())

    def update_preview(self):
        ok = self.source is not None and self.source.image_index > 1
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(ok)
        if not ok:
            self.preview.setPlainText("" if self.source is None else "This file has no surfaces between object and image.")
            return
        o = self.options()
        try:
            trial = lf.OpticalSystem("preview", self.doc.system.units, self.doc.system.library)
            E.insert_lens(trial, self.source, 1, **o)
            group = lens_surfaces(self.source, o["first"], o["last"], 1.0, o["reverse"], o["keep_stop"])
        except Exception as e:
            self.preview.setPlainText(f"Cannot insert: {e}")
            self.buttons.button(QDialogButtonBox.Ok).setEnabled(False)
            return
        lines = trial.prescription().splitlines()
        self.preview.setPlainText("\n".join(lines[:1] + lines[2:-1]))
        src = self.source
        text = (f"{src.name or 'Lens'}: {len(group)} surface(s), {src.units}. ")
        try:
            trial.set_aperture("EPD", 1.0)
            f = trial.paraxial().efl
            if math.isfinite(f) and abs(f) < 1e12:
                text += f"Focal length of the inserted group: {f:.6g} {self.doc.system.units}."
        except Exception:
            pass
        self.info.setText(text)

    def insert(self) -> bool:
        """Insert into the document as one undoable edit."""
        o = self.options()
        at = self.at.value()
        name = os.path.basename(getattr(self, "_loaded", "") or "lens")
        return self.doc.modify(f"Insert lens {name}", lambda s: E.insert_lens(s, self.source, at, **o))

    def accept(self):
        if self.source is not None and self.insert():
            super().accept()
