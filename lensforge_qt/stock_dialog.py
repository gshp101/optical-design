"""File > Insert Stock Lens: search vendor stock lens catalogs by properties and insert a part."""

from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
                               QFormLayout, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QMessageBox,
                               QPlainTextEdit, QPushButton, QSpinBox, QSplitter, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

import lensforge as lf
from lensforge import stock as ST

from . import stock_table as T
from .fonts import fixed_font
from .ownership import qt_owns_children

CATALOG_FILTER = "Stock lens files (*.zmf *.ZMF *.zmx *.ZMX);;Zemax lens catalog (*.zmf *.ZMF);;" \
                 "Zemax lens file (*.zmx *.ZMX);;All files (*)"

_LIBRARY = None


def shared_stock_library() -> lf.StockLibrary:
    """The demo parts plus the catalogs imported before (lensforge.stock.user_library_path())."""
    global _LIBRARY
    if _LIBRARY is None:
        try:
            _LIBRARY = lf.StockLibrary.default()
        except Exception:  # unreadable saved file: start with the demo parts
            _LIBRARY = lf.StockLibrary(ST.demo_lenses(), path=ST.user_library_path())
    return _LIBRARY


@qt_owns_children
class StockLensDialog(QDialog):
    """Search form, result table and preview; Insert puts the part in front of a surface."""

    def __init__(self, doc, at: int = None, start_dir: str = "", library: lf.StockLibrary = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Insert Stock Lens")
        self.resize(1000, 700)
        self.doc = doc
        self.start_dir = start_dir
        self.library = library or shared_stock_library()
        self.found = []

        self.text = QLineEdit(placeholderText="part number or description")
        self.vendor = QComboBox()
        self.kind = QComboBox()
        self.kind.addItems(["All"] + list(ST.KINDS))
        self.glass = QLineEdit(placeholderText="e.g. N-BK7")
        self.efl_min, self.efl_max = QLineEdit(placeholderText="min"), QLineEdit(placeholderText="max")
        self.dia_min, self.dia_max = QLineEdit(placeholderText="min"), QLineEdit(placeholderText="max")
        self.elements = QComboBox()
        self.elements.addItems([label for label, _ in T.ELEMENT_CHOICES])
        for w in (self.text, self.glass, self.efl_min, self.efl_max, self.dia_min, self.dia_max):
            w.textChanged.connect(self.run_search)
        for w in (self.vendor, self.kind, self.elements):
            w.currentIndexChanged.connect(self.run_search)

        def pair(a, b, unit=""):
            h = QHBoxLayout()
            h.addWidget(a)
            h.addWidget(QLabel("to"))
            h.addWidget(b)
            if unit:
                h.addWidget(QLabel(unit))
            return h

        form = QFormLayout()
        form.addRow("Part / text:", self.text)
        form.addRow("Vendor:", self.vendor)
        form.addRow("Type:", self.kind)
        form2 = QFormLayout()
        form2.addRow("Focal length:", pair(self.efl_min, self.efl_max))
        form2.addRow("Diameter:", pair(self.dia_min, self.dia_max))
        form2.addRow("Glass:", self.glass)
        form2.addRow("Elements:", self.elements)
        top = QHBoxLayout()
        top.addLayout(form, 1)
        top.addLayout(form2, 1)

        self.table = QTableWidget(0, len(T.COLUMNS))
        self.table.setHorizontalHeaderLabels(T.COLUMNS)
        for i, c in enumerate(T.COLUMNS):
            if c in T.COLUMN_TIPS:
                self.table.horizontalHeaderItem(i).setToolTip(T.COLUMN_TIPS[c])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSortingEnabled(False)
        self.table.itemSelectionChanged.connect(self.update_preview)
        self.table.cellDoubleClicked.connect(lambda *_: self.accept())
        self.count = QLabel()

        ima = doc.system.image_index
        self.at = QSpinBox(minimum=1, maximum=ima)
        self.at.setValue(ima if at is None else max(1, min(at, ima)))
        self.at.setToolTip("The part's surfaces go in front of this surface of the current lens")
        self.at.setMaximumWidth(120)
        self.reverse = QCheckBox("Reverse (turn the part round: light meets its back surface first)")
        self.copy_sd = QCheckBox("Use the part's semi-diameters")
        self.copy_sd.setChecked(True)
        self.copy_sd.setToolTip("Checked: the inserted surfaces get the part's clear semi-diameters as fixed "
                                "values.\nUnchecked: automatic semi-diameters sized by the current lens's rays.")
        for w in (self.reverse, self.copy_sd):
            w.toggled.connect(self.update_preview)
        opts = QFormLayout()
        opts.addRow("Insert before surface:", self.at)
        opts.addRow("", self.reverse)
        opts.addRow("", self.copy_sd)

        self.preview = QPlainTextEdit(readOnly=True)
        self.preview.setFont(fixed_font())
        self.preview.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.info = QLabel()
        self.info.setWordWrap(True)
        self.info.setTextInteractionFlags(Qt.TextSelectableByMouse)

        lower = QWidget()
        ll = QVBoxLayout(lower)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addLayout(opts)
        ll.addWidget(QLabel("Surfaces to insert (in the order they will be inserted):"))
        ll.addWidget(self.preview, 1)
        ll.addWidget(self.info)
        upper = QWidget()
        ul = QVBoxLayout(upper)
        ul.setContentsMargins(0, 0, 0, 0)
        ul.addWidget(self.table, 1)
        ul.addWidget(self.count)
        split = QSplitter(Qt.Vertical)
        split.addWidget(upper)
        split.addWidget(lower)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)

        self.import_btn = QPushButton("Import Catalog...")
        self.import_btn.setToolTip("Add a Zemax lens catalog (.ZMF) or one part's .zmx file from a lens maker")
        self.import_btn.clicked.connect(self.import_dialog)
        self.remove_btn = QPushButton("Remove Catalog...")
        self.remove_btn.setToolTip("Forget a catalog you imported")
        self.remove_btn.clicked.connect(self.remove_dialog)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Close)
        self.buttons.button(QDialogButtonBox.Ok).setText("Insert")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.buttons.addButton(self.import_btn, QDialogButtonBox.ActionRole)
        self.buttons.addButton(self.remove_btn, QDialogButtonBox.ActionRole)

        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(split, 1)
        lay.addWidget(self.buttons)
        self.fill_vendors()
        self.run_search()

    # ------------------------------------------------------------------ search
    def fill_vendors(self):
        cur = self.vendor.currentText()
        self.vendor.blockSignals(True)
        self.vendor.clear()
        self.vendor.addItems(["All"] + self.library.vendors)
        i = self.vendor.findText(cur)
        self.vendor.setCurrentIndex(max(0, i))
        self.vendor.blockSignals(False)

    def form(self) -> dict:
        return dict(text=self.text.text(), vendor=self.vendor.currentText(), kind=self.kind.currentText(),
                    glass=self.glass.text(), efl_min=self.efl_min.text(), efl_max=self.efl_max.text(),
                    dia_min=self.dia_min.text(), dia_max=self.dia_max.text(), elements=self.elements.currentIndex())

    def run_search(self):
        try:
            self.found, rows, msg = T.search(self.library, self.form())
        except ValueError as e:
            self.count.setText(f"<span style='color:#b00020'>{e}</span>")
            return
        self.table.setRowCount(len(rows))
        for r, values in enumerate(rows):
            for c, v in enumerate(values):
                it = QTableWidgetItem(v)
                if T.COLUMNS[c] in ("EFL", "Diameter", "Thickness", "Elements"):
                    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(r, c, it)
        self.count.setText(msg + f" in {len(self.library.catalogs)} catalog(s)")
        if rows:
            self.table.selectRow(0)
        self.update_preview()

    def selected(self):
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not rows or rows[0].row() >= len(self.found):
            return None
        return self.found[rows[0].row()]

    def update_preview(self):
        part = self.selected()
        ok_btn = self.buttons.button(QDialogButtonBox.Ok)
        if part is None:
            self.preview.setPlainText("")
            self.info.setText("Choose a part in the list." if self.found else "No part matches the search.")
            ok_btn.setEnabled(False)
            return
        p = T.preview(self.doc.system, part, self.reverse.isChecked(), self.copy_sd.isChecked())
        self.preview.setPlainText(p["text"])
        self.info.setText(p["info"])
        ok_btn.setEnabled(p["ok"])

    # ------------------------------------------------------------------ catalogs
    def import_dialog(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Import Stock Lens Catalog", self.start_dir, CATALOG_FILTER)
        if paths:
            self.start_dir = os.path.dirname(paths[0])
            settings = getattr(self.parent(), "settings", None)
            if settings is not None:
                settings.setValue("stock_dir", self.start_dir)
            self.import_files(paths)

    def import_files(self, paths) -> int:
        n, errors = 0, []
        for p in paths:
            try:
                n += len(self.library.import_file(p))
            except Exception as e:  # noqa: BLE001
                errors.append(f"{os.path.basename(p)}: {e}")
        if n:
            try:
                self.library.save()
            except OSError as e:
                errors.append(f"Cannot save the catalog list: {e}")
        if errors:
            QMessageBox.warning(self, "Import Stock Lens Catalog", "\n".join(errors))
        self.fill_vendors()
        self.run_search()
        return n

    def remove_dialog(self):
        cats = [c for c in self.library.catalogs if c != ST.DEMO_CATALOG]
        if not cats:
            QMessageBox.information(self, "Remove Catalog", "No imported catalogs (the demo parts always stay).")
            return
        name, ok = QInputDialog.getItem(self, "Remove Catalog", "Catalog to forget:", cats, 0, False)
        if ok and name:
            self.remove_catalog(name)

    def remove_catalog(self, name: str) -> int:
        n = self.library.remove_catalog(name)
        try:
            self.library.save()
        except OSError:
            pass
        self.fill_vendors()
        self.run_search()
        return n

    # ------------------------------------------------------------------ insert
    def insert(self) -> bool:
        part = self.selected()
        if part is None:
            return False
        at, rev, sd = self.at.value(), self.reverse.isChecked(), self.copy_sd.isChecked()
        what = f"Insert stock lens {part.part}" + (" (reversed)" if rev else "")
        return self.doc.modify(what, lambda s: T.insert(s, part, at, rev, sd))

    def accept(self):
        if self.selected() is not None and self.insert():
            super().accept()
