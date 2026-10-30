"""Multi-Configuration Editor: the table of :class:`lensforge.MultiConfig`.

Rows are operands (THIC 8, APER, YFIE 2 ...), columns after Type / Ref / Param
are the configurations.  The column of the current configuration (the one the
Lens Data Editor and the analyses show) is shaded and its header starred;
double-click a header to switch.  Every edit goes through
``LensDocument.modify``, so it is one undo step.  Cell text is parsed by
:func:`lensforge.multiconfig.parse_value`, which a web front end can share.
"""

from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal
from PySide6.QtGui import QAction, QColor, QFont, QKeySequence
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QCompleter, QHeaderView, QInputDialog, QLabel,
                               QLineEdit, QMenu, QStyledItemDelegate, QTableView, QToolBar, QVBoxLayout, QWidget)

import lensforge as lf
from lensforge import optimize as opt
from lensforge.compose import remove_mc_rows
from lensforge.multiconfig import MC_OPERANDS, format_value

FIXED = ["Type", "Ref", "Param"]
C_TYPE, C_REF, C_PARAM = range(3)
N_FIXED = len(FIXED)
CURRENT_BG = QColor(255, 248, 214)
VAR_BG = QColor(222, 235, 255)
ERROR_BG = QColor(255, 222, 222)
REF_HELP = {"surface": "surface number (0 = object)", "field": "field number, counting from 0",
            "wave": "wavelength number, counting from 0", None: "no reference"}


def multiconfig(system, create=False):
    """The lens's table; with ``create`` a one-configuration table is made if there is none."""
    mc = getattr(system, "multiconfig", None)
    if mc is None and create:
        mc = lf.MultiConfig.create(system, 1)
    return mc


class MultiConfigModel(QAbstractTableModel):
    def __init__(self, doc, parent=None):
        super().__init__(parent)
        self.doc = doc
        self._shape = self.shape()
        doc.changed.connect(self.refresh)

    @property
    def mc(self):
        return multiconfig(self.doc.system)

    def shape(self):
        mc = self.mc
        return (0, 0) if mc is None else (len(mc.rows), mc.n_configs)

    def refresh(self):
        s = self.shape()
        if s != self._shape:
            self.beginResetModel()
            self._shape = s
            self.endResetModel()
        else:
            if s[0]:
                self.dataChanged.emit(self.index(0, 0), self.index(s[0] - 1, self.columnCount() - 1))
            self.headerDataChanged.emit(Qt.Horizontal, 0, max(0, self.columnCount() - 1))

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else self.shape()[0]

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else N_FIXED + self.shape()[1]

    def config_of(self, column):
        return column - N_FIXED + 1 if column >= N_FIXED else None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        mc = self.mc
        if orientation == Qt.Vertical:
            return str(section + 1) if role == Qt.DisplayRole else None
        if section < N_FIXED:
            if role == Qt.DisplayRole:
                return FIXED[section]
            if role == Qt.ToolTipRole:
                return ["Operand: what the row sets (see Help)", "Surface, field or wavelength the operand refers "
                        "to", "Parameter name, for PARM rows only"][section]
            return None
        k = self.config_of(section)
        if mc is None or k > mc.n_configs:
            return None
        if role == Qt.DisplayRole:
            name = mc.names[k - 1]
            return f"{'* ' if k == mc.current else ''}Config {k}" + (f"\n{name}" if name else "")
        if role == Qt.FontRole and k == mc.current:
            f = QFont()
            f.setBold(True)
            return f
        if role == Qt.ToolTipRole:
            return (f"{mc.name(k)}{' (current)' if k == mc.current else ''}. Double-click to make it current; "
                    "right-click to rename, insert or delete configurations.")
        return None

    def data(self, index, role=Qt.DisplayRole):
        mc = self.mc
        if mc is None or not index.isValid():
            return None
        r = mc.rows[index.row()]
        c = index.column()
        k = self.config_of(c)
        if role in (Qt.DisplayRole, Qt.EditRole):
            if c == C_TYPE:
                return r.type
            if c == C_REF:
                return "" if r.ref is None else str(r.ref)
            if c == C_PARAM:
                return r.param or ""
            text = format_value(r, r.values[k - 1])
            if role == Qt.DisplayRole and opt.is_mc_variable(self.doc.system, index.row(), k):
                text += "  V"
            return text
        if role == Qt.TextAlignmentRole and k is not None:
            return int((Qt.AlignLeft if r.type == "GLSS" else Qt.AlignRight) | Qt.AlignVCenter)
        if role == Qt.BackgroundRole:
            if c == C_TYPE and self.error(index.row()):
                return ERROR_BG
            if k is not None and opt.is_mc_variable(self.doc.system, index.row(), k):
                return VAR_BG
            if k == mc.current:
                return CURRENT_BG
            if c == C_PARAM and r.type != "PARM" or c == C_REF and r.ref is None:
                return QColor(242, 242, 242)
        if role == Qt.ToolTipRole:
            err = self.error(index.row())
            tip = f"{r.label}: {MC_OPERANDS[r.type][1]}"
            if c == C_REF:
                tip = f"Ref: {REF_HELP[r.ref_kind]}"
            if k is not None:
                tip += f"\n{mc.name(k)}" + (" (current)" if k == mc.current else "")
                if opt.is_mc_variable(self.doc.system, index.row(), k):
                    tip += "\nVariable (Ctrl+Shift+V toggles)"
            return tip + (f"\n⚠ {err}" if err else "")
        return None

    def error(self, row):
        mc = self.mc
        try:
            return mc.errors(self.doc.system)[row]
        except IndexError:
            return None

    def flags(self, index):
        f = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        mc = self.mc
        if mc is None or not index.isValid():
            return f
        r = mc.rows[index.row()]
        c = index.column()
        if (c == C_REF and r.ref is None) or (c == C_PARAM and r.type != "PARM") or \
                (c >= N_FIXED and r.type == "MOFF"):
            return f
        return f | Qt.ItemIsEditable

    def setData(self, index, value, role=Qt.EditRole):
        if role != Qt.EditRole or not index.isValid():
            return False
        text = str(value).strip()
        if text == (self.data(index, Qt.EditRole) or ""):
            return False
        i, c = index.row(), index.column()
        k = self.config_of(c)

        def fn(s):
            mc = multiconfig(s)
            r = mc.rows[i]
            if c == C_TYPE:
                t = text.upper()
                if t not in MC_OPERANDS:
                    raise ValueError(f"unknown operand {text!r}")
                param = r.param if t == "PARM" else None
                if t == "PARM" and not param:
                    param = "conic"
                mc.set_row_operand(s, i, t, r.ref, param)
                _drop_row_variables(s, i)  # its cell variables meant the old parameter
            elif c == C_REF:
                mc.set_row_operand(s, i, r.type, int(text), r.param)
                _drop_row_variables(s, i)
            elif c == C_PARAM:
                mc.set_row_operand(s, i, r.type, r.ref, text)
                _drop_row_variables(s, i)
            else:
                mc.set_value(s, i, k, text)
        what = FIXED[c] if c < N_FIXED else f"config {k}"
        return self.doc.modify(f"Multi-config row {i + 1} {what}", fn)


class MultiConfigDelegate(QStyledItemDelegate):
    def createEditor(self, parent, option, index):
        if index.column() == C_TYPE:
            cb = QComboBox(parent)
            cb.setEditable(True)
            cb.addItems(list(MC_OPERANDS))
            cb.completer().setCaseSensitivity(Qt.CaseInsensitive)
            cb.completer().setCompletionMode(QCompleter.PopupCompletion)
            return cb
        return QLineEdit(parent)

    def setEditorData(self, editor, index):
        if isinstance(editor, QComboBox):
            editor.setCurrentText(index.data(Qt.EditRole))
        else:
            editor.setText(index.data(Qt.EditRole) or "")

    def setModelData(self, editor, model, index):
        model.setData(index, editor.currentText() if isinstance(editor, QComboBox) else editor.text(), Qt.EditRole)


class MultiConfigEditor(QWidget):
    statusMessage = Signal(str)
    helpRequested = Signal(str)  # a help id (menu path)

    def __init__(self, doc, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.model = MultiConfigModel(doc, self)
        self.view = QTableView()
        self.view.setModel(self.model)
        self.view.setItemDelegate(MultiConfigDelegate(self.view))
        self.view.verticalHeader().setDefaultSectionSize(22)
        self.view.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed
                                  | QAbstractItemView.AnyKeyPressed)
        hh = self.view.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.Interactive)
        hh.setDefaultSectionSize(100)
        hh.sectionDoubleClicked.connect(self._header_double_clicked)
        hh.setContextMenuPolicy(Qt.CustomContextMenu)
        hh.customContextMenuRequested.connect(self._header_menu)
        self.view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self._cell_menu)
        tb = QToolBar()
        self.act_insert = self._act(tb, "Insert Operand", self.insert_row, "Insert",
                                    "Insert a THIC row above the selected row (all configurations take the lens's "
                                    "current value; change the type, Ref and values afterwards).")
        self.act_delete = self._act(tb, "Delete Operands", self.delete_rows, "Shift+Delete",
                                    "Delete the selected rows; the lens keeps its current values.")
        tb.addSeparator()
        self.act_add_config = self._act(tb, "Add Config", self.add_config, tip="Add a configuration after the "
                                        "selected one, copying its values.")
        self.act_del_config = self._act(tb, "Delete Config", self.delete_config,
                                        tip="Delete the selected configuration.")
        self.act_rename = self._act(tb, "Rename Config...", self.rename_config,
                                    tip="Name the selected configuration (e.g. short, mid, long).")
        tb.addSeparator()
        self.act_make_current = self._act(tb, "Make Current", self.make_current,
                                          tip="Show the selected configuration in the Lens Data Editor and the "
                                          "analyses (or double-click its header).")
        self.act_variable = self._act(tb, "Toggle Variable", self.toggle_variable, "Ctrl+Shift+V",
                                      "Make the selected cells optimisation variables, or fixed again.")
        tb.addSeparator()
        self._act(tb, "Help", lambda: self.helpRequested.emit("Tools > Multi-Configuration Editor"),
                  tip="How multi-configuration works: operands, switching, analyses and optimisation.")
        self.label = QLabel()
        self.label.setStyleSheet("padding: 2px 6px;")
        self.label.setWordWrap(True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(tb)
        lay.addWidget(self.view)
        lay.addWidget(self.label)
        doc.changed.connect(self._update_label)
        self._update_label()

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

    def _update_label(self):
        mc = self.model.mc
        if mc is None:
            self.label.setText("Single configuration. Insert an operand or add a configuration to start a "
                               "multi-configuration lens.")
            return
        bad = sum(1 for e in mc.errors(self.doc.system) if e)
        nv = sum(1 for v in opt.variables(self.doc.system) if isinstance(v, opt.MCVariable))
        txt = f"{mc.n_configs} configurations, {len(mc.rows)} operands. Current: {mc.name(mc.current)}."
        if nv:
            txt += f" {nv} variable cell{'s' if nv > 1 else ''}."
        if bad:
            txt += f" <span style='color:#a00'>{bad} row{'s' if bad > 1 else ''} cannot be applied (red).</span>"
        self.label.setText(txt)

    # -- selection ------------------------------------------------------------------
    def current_row(self):
        idx = self.view.currentIndex()
        return idx.row() if idx.isValid() else self.model.rowCount()

    def current_config(self):
        mc = self.model.mc
        idx = self.view.currentIndex()
        k = self.model.config_of(idx.column()) if idx.isValid() else None
        return k if k is not None else (mc.current if mc is not None else 1)

    # -- rows -------------------------------------------------------------------------
    def insert_row(self):
        r = self.current_row()

        def fn(s):
            multiconfig(s, create=True).add_row(s, "THIC", 1, index=r)
            _shift_mc_variables(s, r, +1)
        self.doc.modify("Insert multi-config operand", fn)
        self.view.setCurrentIndex(self.model.index(r, C_TYPE))

    def delete_rows(self):
        rows = sorted({i.row() for i in self.view.selectionModel().selectedIndexes()})
        if not rows or self.model.mc is None:
            return
        self.doc.modify(f"Delete {len(rows)} multi-config operand(s)", lambda s: remove_mc_rows(s, rows))

    # -- configurations -----------------------------------------------------------------
    def add_config(self):
        k = self.current_config()

        def fn(s):
            mc = multiconfig(s, create=True)
            new = mc.insert_config(s, at=k + 1, copy_from=k)
            _shift_mc_configs(s, new, +1)
        self.doc.modify("Add configuration", fn)

    def delete_config(self, k=None):
        k = k or self.current_config()
        mc = self.model.mc
        if mc is None or mc.n_configs < 2:
            self.statusMessage.emit("The last configuration cannot be deleted")
            return

        def fn(s):
            _shift_mc_configs(s, k, -1)
            multiconfig(s).remove_config(s, k)
        self.doc.modify(f"Delete configuration {k}", fn)

    def rename_config(self, k=None):
        k = k or self.current_config()
        mc = self.model.mc
        if mc is None:
            return
        name, ok = QInputDialog.getText(self, "Rename configuration", f"Name of configuration {k}:",
                                        text=mc.names[k - 1])
        if ok:
            self.set_config_name(k, name)

    def set_config_name(self, k, name):
        def fn(s):
            multiconfig(s).names[k - 1] = name.strip()
        self.doc.modify(f"Rename configuration {k}", fn)

    def make_current(self, k=None):
        k = k or self.current_config()
        switch_config(self.doc, k)

    def _header_double_clicked(self, section):
        k = self.model.config_of(section)
        if k is not None:
            self.make_current(k)

    def _header_menu(self, pos):
        k = self.model.config_of(self.view.horizontalHeader().logicalIndexAt(pos))
        if k is None:
            return
        m = QMenu(self)
        m.addAction(f"Make Config {k} Current", lambda: self.make_current(k))
        m.addAction("Rename...", lambda: self.rename_config(k))
        m.addAction("Insert Config After", lambda: (self.view.setCurrentIndex(self.model.index(0, k + N_FIXED - 1)),
                                                     self.add_config()))
        m.addAction("Delete Config", lambda: self.delete_config(k))
        m.exec(self.view.horizontalHeader().mapToGlobal(pos))

    def _cell_menu(self, pos):
        m = QMenu(self)
        for a in (self.act_insert, self.act_delete, self.act_variable, self.act_make_current):
            m.addAction(a)
        m.exec(self.view.viewport().mapToGlobal(pos))

    # -- variables ------------------------------------------------------------------------
    def toggle_variable(self):
        cells = [(i.row(), self.model.config_of(i.column())) for i in self.view.selectionModel().selectedIndexes()
                 if self.model.config_of(i.column()) is not None]
        if not cells:
            self.statusMessage.emit("Select value cells (configuration columns) to make them variable")
            return

        def fn(s):
            for row, k in cells:
                if opt.is_mc_variable(s, row, k):
                    opt.remove_mc_variable(s, row, k)
                else:
                    opt.set_mc_variable(s, row, k)
        self.doc.modify("Toggle multi-config variable", fn)


def switch_config(doc, k) -> bool:
    """Make configuration ``k`` current (one undo step)."""
    mc = multiconfig(doc.system)
    if mc is None or not 1 <= k <= mc.n_configs or k == mc.current:
        return False
    return doc.modify(f"Switch to {mc.name(k)}", lambda s: s.set_config(k))


def _drop_row_variables(system, row):
    vs = opt.variables(system)
    vs[:] = [v for v in vs if not (isinstance(v, opt.MCVariable) and v.row == row)]


def _shift_mc_variables(system, row, delta):
    """Cell variables of rows at or after ``row`` move down (a row was inserted there)."""
    for v in opt.variables(system):
        if isinstance(v, opt.MCVariable) and v.row >= row:
            v.row += delta


def _shift_mc_configs(system, k, delta):
    """Keep cell variables on their configuration when configuration ``k`` is inserted (+1) or deleted (-1)."""
    vs = opt.variables(system)
    keep = []
    for v in vs:
        if isinstance(v, opt.MCVariable):
            if delta < 0 and v.config == k:
                continue
            if v.config >= k + (1 if delta < 0 else 0):
                v.config += delta
        keep.append(v)
    vs[:] = keep
