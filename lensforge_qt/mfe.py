"""Merit Function Editor: the operand spreadsheet.

Rows are :class:`lensforge.optimize.Operand`; parameters are typed as
``name=value`` pairs (e.g. ``surf=4, hy=1, py=1``).  Values and % contribution
are recomputed in the background after every change of the lens.  The help pages
(columns, weights, operands, an example) are in mfe_help.py.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QKeySequence
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QCompleter, QDialog, QDialogButtonBox,
                               QDoubleSpinBox, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QSpinBox, QStyledItemDelegate, QTableView,
                               QToolBar, QVBoxLayout, QWidget)

from lensforge import optimize as opt

from . import edits as E
from . import mfe_help
from . import workers
from .fonts import fixed_font

COLUMNS = ["Type", "Parameters", "Bound", "Target", "Weight", "Value", "% Contrib", "Comment"]
C_TYPE, C_PARAMS, C_BOUND, C_TARGET, C_WEIGHT, C_VALUE, C_CONTRIB, C_COMMENT = range(len(COLUMNS))


def merit_function(system):
    mf = getattr(system, "merit_function", None)
    if mf is None:
        mf = opt.MeritFunction()
        system.merit_function = mf
    return mf


class MeritModel(QAbstractTableModel):
    evaluated = Signal(object)  # MeritEvaluation or None

    def __init__(self, doc, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.evaluation = None
        self._rows = self.n_rows()
        self._pending = False
        self._busy = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(120)
        self._timer.timeout.connect(self.evaluate)
        doc.changed.connect(self.refresh)
        self.refresh()

    def n_rows(self):
        mf = getattr(self.doc.system, "merit_function", None)
        return len(mf.rows) if mf is not None else 0

    @property
    def mf(self):
        return getattr(self.doc.system, "merit_function", None)

    def refresh(self):
        n = self.n_rows()
        if n != self._rows:
            self.beginResetModel()
            self._rows = n
            self.endResetModel()
        elif n:
            self.dataChanged.emit(self.index(0, 0), self.index(n - 1, len(COLUMNS) - 1))
        if workers.SYNC:
            self.evaluate()
        else:
            self._timer.start()

    def evaluate(self):
        mf = self.mf
        if mf is None or not mf.rows:
            self.evaluation = None
            self.evaluated.emit(None)
            return
        if self._busy:
            self._pending = True
            return
        self._busy = True
        system, mfc, rev = self.doc.system.copy(), mf.copy(), self.doc.revision
        workers.submit(lambda _p: mfc.evaluate(system), self._done, self._failed, tag=rev)

    def _finish(self):
        self._busy = False
        if self._pending:
            self._pending = False
            self.evaluate()

    def _done(self, rev, ev):
        if rev == self.doc.revision and len(ev.scalars) == self.n_rows():
            self.evaluation = ev
            if self._rows:
                self.dataChanged.emit(self.index(0, C_VALUE), self.index(self._rows - 1, C_CONTRIB))
            self.evaluated.emit(ev)
        self._finish()

    def _failed(self, rev, msg):
        self.evaluation = None
        self.evaluated.emit(None)
        self._finish()

    # -- model API -------------------------------------------------------------
    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else self.n_rows()

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.ToolTipRole and orientation == Qt.Horizontal:
            return mfe_help.COLUMN_TIPS[COLUMNS[section]]
        if role != Qt.DisplayRole:
            return None
        return COLUMNS[section] if orientation == Qt.Horizontal else str(section + 1)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = self.mf.rows[index.row()]
        c = index.column()
        if role in (Qt.DisplayRole, Qt.EditRole):
            if c == C_TYPE:
                return row.type
            if c == C_PARAMS:
                return E.format_params(row.params)
            if c == C_BOUND:
                return row.bound
            if c == C_TARGET:
                return E.format_number(row.target, 8) if role == Qt.DisplayRole else repr(row.target)
            if c == C_WEIGHT:
                return E.format_number(row.weight, 8) if role == Qt.DisplayRole else repr(row.weight)
            if c == C_COMMENT:
                return row.comment
            ev = self.evaluation
            if ev is None or index.row() >= len(ev.scalars):
                return ""
            if c == C_VALUE:
                v = ev.scalars[index.row()]
                return "" if v is None or (isinstance(v, float) and math.isnan(v)) else E.format_number(v, 8)
            if c == C_CONTRIB:
                if row.weight <= 0:
                    return ""
                return f"{100 * ev.contributions[index.row()]:.3f}"
        if role == Qt.TextAlignmentRole and c in (C_TARGET, C_WEIGHT, C_VALUE, C_CONTRIB):
            return int(Qt.AlignRight | Qt.AlignVCenter)
        if role == Qt.TextAlignmentRole and c == C_BOUND:
            return int(Qt.AlignCenter)
        if role == Qt.ToolTipRole:
            return mfe_help.operand_tooltip(row.type)
        if role == Qt.BackgroundRole:
            if row.type == "BLNK":
                return QColor(245, 245, 245)
            if row.weight < 0:
                return QColor(255, 236, 236)
            if c in (C_VALUE, C_CONTRIB):
                return QColor(248, 248, 252)
        if role == Qt.ForegroundRole and row.weight == 0 and c != C_COMMENT:
            return QColor(120, 120, 120)
        return None

    def flags(self, index):
        f = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        if index.column() not in (C_VALUE, C_CONTRIB):
            f |= Qt.ItemIsEditable
        return f

    def setData(self, index, value, role=Qt.EditRole):
        if role != Qt.EditRole or not index.isValid():
            return False
        r, c = index.row(), index.column()
        text = str(value)
        if text == self.data(index, Qt.EditRole):
            return False

        def fn(s):
            row = merit_function(s).rows[r]
            if c == C_TYPE:
                t = text.strip().upper()
                opt.Operand(t, params={})  # validates the name
                row.type = t
                from lensforge.optimize.operands import DEFAULT_BOUND
                row.bound = DEFAULT_BOUND[t]
                merit_function(s).auto_weight()
            elif c == C_PARAMS:
                row.params = E.parse_params(text)
            elif c == C_BOUND:
                if text.strip() not in ("=", ">", "<"):
                    raise ValueError("bound must be =, > or <")
                row.bound = text.strip()
            elif c == C_TARGET:
                row.target = E.parse_number(text, allow_inf=False)
            elif c == C_WEIGHT:
                row.weight = E.parse_number(text, allow_inf=False)
            elif c == C_COMMENT:
                row.comment = text
        return self.doc.modify(f"Merit row {r + 1} {COLUMNS[c]}", fn)


class MeritDelegate(QStyledItemDelegate):
    def createEditor(self, parent, option, index):
        if index.column() == C_TYPE:
            cb = QComboBox(parent)
            cb.setEditable(True)
            cb.addItems(sorted(opt.OPERANDS))
            cb.completer().setCaseSensitivity(Qt.CaseInsensitive)
            cb.completer().setCompletionMode(QCompleter.PopupCompletion)
            return cb
        if index.column() == C_BOUND:
            cb = QComboBox(parent)
            cb.addItems(["=", ">", "<"])
            return cb
        return QLineEdit(parent)

    def setEditorData(self, editor, index):
        if isinstance(editor, QComboBox):
            editor.setCurrentText(index.data(Qt.EditRole))
        else:
            editor.setText(index.data(Qt.EditRole) or "")

    def setModelData(self, editor, model, index):
        model.setData(index, editor.currentText() if isinstance(editor, QComboBox) else editor.text(), Qt.EditRole)


class MeritFunctionEditor(QWidget):
    statusMessage = Signal(str)
    helpRequested = Signal(str)  # a help page key (mfe_help.ROOT)

    def __init__(self, doc, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.model = MeritModel(doc, self)
        self.view = QTableView()
        self.view.setModel(self.model)
        self.view.setItemDelegate(MeritDelegate(self.view))
        self.view.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.view.verticalHeader().setDefaultSectionSize(22)
        self.view.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed
                                  | QAbstractItemView.AnyKeyPressed)
        hh = self.view.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.Interactive)
        hh.setStretchLastSection(True)
        for c, w in ((C_TYPE, 70), (C_PARAMS, 260), (C_BOUND, 46), (C_TARGET, 90), (C_WEIGHT, 70),
                     (C_VALUE, 110), (C_CONTRIB, 80)):
            self.view.setColumnWidth(c, w)
        tb = QToolBar()
        self.act_add = self._act(tb, "Add Row", self.add_row, "Ctrl+Shift+A", "Add a blank row at the end.")
        self.act_insert = self._act(tb, "Insert Row", self.insert_row, "Insert",
                                    "Insert a blank row above the selected row.")
        self.act_delete = self._act(tb, "Delete Rows", self.delete_rows, "Shift+Delete", "Delete the selected rows.")
        tb.addSeparator()
        self._act(tb, "Wizard...", self.wizard, tip="Write a default RMS spot, wavefront or MTF merit function, "
                  "with optional thickness limits.")
        self._act(tb, "Operands...", self.operand_list, tip="List every operand with its description and insert "
                  "one.")
        self._act(tb, "Clear", self.clear, tip="Remove every row (undoable).")
        tb.addSeparator()
        self.act_help = self._act(tb, "Help", lambda: self.helpRequested.emit(mfe_help.ROOT),
                                  tip="Merit Function Editor help: columns, weights, ray coordinates, every "
                                  "operand and a worked example (F1).")
        self.label = QLabel("Merit function: -")
        self.label.setStyleSheet("font-weight: bold; padding: 2px 6px;")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(tb)
        lay.addWidget(self.view)
        lay.addWidget(self.label)
        self.model.evaluated.connect(self._show_value)

    def _act(self, tb, text, slot, shortcut=None, tip=""):
        a = QAction(text, self)
        a.triggered.connect(slot)
        if tip:
            a.setToolTip(f"{text} ({shortcut})\n{tip}" if shortcut else f"{text}\n{tip}")
            a.setStatusTip(tip)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
            a.setShortcutContext(Qt.WidgetWithChildrenShortcut)
            self.view.addAction(a)
        tb.addAction(a)
        return a

    def _show_value(self, ev):
        if ev is None:
            self.label.setText("Merit function: -" if not self.model.n_rows() else "Merit function: (error)")
            return
        txt = f"Merit function: {ev.value:.10g}"
        if ev.error:
            txt += f"    ({ev.error})"
        self.label.setText(txt)

    def current_row(self):
        idx = self.view.currentIndex()
        return idx.row() if idx.isValid() else self.model.n_rows()

    def add_row(self):
        self.doc.modify("Add merit row", lambda s: merit_function(s).add("BLNK", weight=0))
        self.view.setCurrentIndex(self.model.index(self.model.n_rows() - 1, C_TYPE))

    def insert_row(self):
        r = self.current_row()
        self.doc.modify("Insert merit row", lambda s: merit_function(s).insert(r, "BLNK", weight=0))
        self.view.setCurrentIndex(self.model.index(r, C_TYPE))

    def delete_rows(self):
        rows = sorted({i.row() for i in self.view.selectionModel().selectedIndexes()}, reverse=True)
        if not rows:
            return

        def fn(s):
            for r in rows:
                merit_function(s).remove(r)
        self.doc.modify(f"Delete {len(rows)} merit row(s)", fn)

    def clear(self):
        self.doc.modify("Clear merit function", lambda s: merit_function(s).clear())

    def wizard(self):
        dlg = MeritWizard(self.doc.system, self)
        if dlg.exec() == QDialog.Accepted:
            kw, keep = dlg.options()

            def fn(s):
                new = opt.default_merit(s, **kw)
                old = merit_function(s)
                if keep:  # keep the user's rows that are not part of a default merit function
                    user = [r for r in old.rows if r.type not in ("RAYS", "OPDS", "MTFA", "CONF") and
                            not (r.type == "BLNK" and r.comment.startswith("Default merit"))
                            and r.type not in ("MNCG", "MXCG", "MNEG", "MNCA", "MXCA", "MNEA")]
                    new.rows = user + new.rows
                s.merit_function = new
            self.doc.modify("Default merit function", fn)

    def operand_list(self):
        dlg = OperandList(self)
        if dlg.exec() == QDialog.Accepted and dlg.chosen:
            t = dlg.chosen
            r = self.current_row()
            self.doc.modify(f"Insert {t}", lambda s: merit_function(s).insert(r, t, weight=1.0))
            self.view.setCurrentIndex(self.model.index(r, C_PARAMS))


class MeritWizard(QDialog):
    """Options of :func:`lensforge.optimize.default_merit` (the optimisation wizard)."""

    def __init__(self, system, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Merit Function Wizard")
        f = QFormLayout()
        self.kind = QComboBox()
        self.kind.addItem("RMS spot radius", "spot")
        self.kind.addItem("RMS wavefront", "wavefront")
        self.kind.addItem("MTF (1 - average MTF)", "mtf")
        self.reference = QComboBox()
        self.reference.addItem("Centroid", "centroid")
        self.reference.addItem("Chief ray", "chief")
        self.rings = QSpinBox()
        self.rings.setRange(1, 20)
        self.rings.setValue(3)
        self.arms = QSpinBox()
        self.arms.setRange(4, 36)
        self.arms.setValue(6)
        self.freq = QDoubleSpinBox()
        self.freq.setRange(0.1, 10000)
        self.freq.setValue(30)
        self.bounds = {}
        f.addRow("Optimise for", self.kind)
        f.addRow("Reference", self.reference)
        f.addRow("Rings", self.rings)
        f.addRow("Arms", self.arms)
        f.addRow("MTF frequency (cycles/mm)", self.freq)
        for name, label in (("glass_min", "Glass min centre"), ("glass_max", "Glass max centre"),
                            ("glass_edge", "Glass min edge"), ("air_min", "Air min centre"),
                            ("air_max", "Air max centre"), ("air_edge", "Air min edge")):
            row = QHBoxLayout()
            cb = QCheckBox()
            sb = QDoubleSpinBox()
            sb.setRange(0, 1e5)
            sb.setDecimals(4)
            sb.setValue({"glass_min": 2, "glass_max": 20, "glass_edge": 1, "air_min": 0.5, "air_max": 1000,
                         "air_edge": 0.5}[name])
            sb.setEnabled(False)
            cb.toggled.connect(sb.setEnabled)
            row.addWidget(cb)
            row.addWidget(sb, 1)
            f.addRow(label, row)
            self.bounds[name] = (cb, sb)
        mc = getattr(system, "multiconfig", None)
        self.all_configs = QCheckBox(f"All {mc.n_configs} configurations (a CONF row heads each group)"
                                     if mc is not None and mc.n_configs > 1 else "All configurations")
        self.all_configs.setChecked(True)
        self.all_configs.setEnabled(mc is not None and mc.n_configs > 1)
        f.addRow("Configurations", self.all_configs)
        self.keep = QCheckBox("Keep my other operands (above the default rows)")
        self.keep.setChecked(True)
        f.addRow("", self.keep)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(f)
        lay.addWidget(bb)

    def options(self):
        kw = dict(kind=self.kind.currentData(), reference=self.reference.currentData(), rings=self.rings.value(),
                  arms=self.arms.value())
        if kw["kind"] == "mtf":
            kw["frequency"] = self.freq.value()
        for name, (cb, sb) in self.bounds.items():
            if cb.isChecked():
                kw[name] = sb.value()
        if self.all_configs.isEnabled() and not self.all_configs.isChecked():
            kw["configs"] = []  # the current configuration only
        return kw, self.keep.isChecked()


class OperandList(QDialog):
    """Searchable list of all operands with their descriptions."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Optimisation Operands")
        self.resize(640, 520)
        self.chosen = None
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter (name or description)")
        self.list = QListWidget()
        for k in sorted(opt.OPERAND_INFO):
            it = QListWidgetItem(f"{k:6} {opt.OPERAND_INFO[k]}")
            it.setData(Qt.UserRole, k)
            self.list.addItem(it)
        self.list.setFont(fixed_font(self.list.font()))
        self.filter.textChanged.connect(self._filter)
        self.list.itemDoubleClicked.connect(self._choose)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Insert")
        bb.accepted.connect(lambda: self._choose(self.list.currentItem()))
        bb.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(self.filter)
        lay.addWidget(self.list)
        lay.addWidget(bb)

    def _filter(self, text):
        t = text.lower()
        for i in range(self.list.count()):
            it = self.list.item(i)
            it.setHidden(t not in it.text().lower())

    def _choose(self, item):
        if item is None:
            return
        self.chosen = item.data(Qt.UserRole)
        self.accept()
