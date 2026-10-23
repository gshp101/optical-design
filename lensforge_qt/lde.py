"""Lens Data Editor: the surface spreadsheet.

One row per surface, Zemax-style columns (type, comment, radius, thickness,
material, semi-diameter, conic, Par 1..8 whose meaning depends on the surface
type).  Cells carry markers: ``V`` variable, a letter for a solve (``M``
marginal ray, ``C`` chief ray, ``F`` F-number, ``P`` pickup, ...), ``U`` a
fixed (user) semi-diameter.  Right-click a cell for variables, solves,
surface type, stop and surface properties.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QRect, Qt, Signal
from PySide6.QtGui import QAction, QColor, QFont, QKeySequence
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QCompleter, QDialog, QDialogButtonBox,
                               QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMenu, QMessageBox,
                               QPlainTextEdit, QStyledItemDelegate, QTableView, QToolButton, QVBoxLayout, QWidget)

from lensforge import optimize as opt
from lensforge import surfaces as S

from . import edits as E

FIXED_COLUMNS = [("surf", "Surf"), ("type", "Surf:Type"), ("comment", "Comment"), ("radius", "Radius"),
                 ("thickness", "Thickness"), ("material", "Material"), ("semi_diameter", "Semi-Diameter"),
                 ("conic", "Conic")]
PAR0 = len(FIXED_COLUMNS)
N_COLUMNS = PAR0 + E.N_PAR

MarkerRole = Qt.UserRole + 1
KeyRole = Qt.UserRole + 2

SOLVE_BG = QColor(225, 238, 255)
VAR_BG = QColor(255, 246, 214)


class LensDataModel(QAbstractTableModel):
    def __init__(self, doc, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.current_row = 1
        self._rows = doc.system.num_surfaces
        self._auto_sd = {}
        self._refresh_auto_sd()
        doc.changed.connect(self.refresh)

    # -- helpers -----------------------------------------------------------------
    @property
    def system(self):
        return self.doc.system

    def key(self, row: int, col: int):
        """Column key (parameter name) of a cell, or None when the cell does not apply."""
        if col < PAR0:
            return FIXED_COLUMNS[col][0]
        s = self.system.surfaces[row]
        cols = E.parameter_columns(s)
        k = col - PAR0
        return cols[k][1] if k < len(cols) else None

    def applies(self, row, key) -> bool:
        if key is None:
            return False
        s = self.system.surfaces[row]
        if key in ("radius", "conic"):
            return E.has_radius(s)
        if key == "material":
            return not s.is_coordinate_break and row != self.system.image_index
        if key == "thickness":
            return row != self.system.image_index
        if key == "semi_diameter":
            return not s.is_coordinate_break
        return True

    def _refresh_auto_sd(self):
        _, self._auto_sd = E.fill_auto_semi_diameters(self.system)

    def refresh(self):
        self._refresh_auto_sd()
        n = self.system.num_surfaces
        if n != self._rows:
            self.beginResetModel()
            self._rows = n
            self.endResetModel()
        else:
            self.dataChanged.emit(self.index(0, 0), self.index(n - 1, N_COLUMNS - 1))
        self.headerDataChanged.emit(Qt.Horizontal, 0, N_COLUMNS - 1)

    def set_current_row(self, row):
        if row != self.current_row and 0 <= row < self.rowCount():
            self.current_row = row
            self.headerDataChanged.emit(Qt.Horizontal, PAR0, N_COLUMNS - 1)

    # -- Qt model API ----------------------------------------------------------------
    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else self.system.num_surfaces

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else N_COLUMNS

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Vertical:
            return None
        if section < PAR0:
            return FIXED_COLUMNS[section][1]
        row = min(self.current_row, self.system.num_surfaces - 1)
        cols = E.parameter_columns(self.system.surfaces[row])
        k = section - PAR0
        return cols[k][0] if k < len(cols) else f"Par {k + 1}"

    def row_label(self, row):
        s = self.system.surfaces[row]
        if row == 0:
            return "OBJ"
        if row == self.system.image_index:
            return "IMA"
        return "STO" if s.stop else str(row)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row, col = index.row(), index.column()
        s = self.system.surfaces[row]
        key = self.key(row, col)
        if role == KeyRole:
            return key
        if col == 0:
            if role == Qt.DisplayRole:
                return self.row_label(row)
            if role == Qt.FontRole and s.stop:
                f = QFont()
                f.setBold(True)
                return f
            if role == Qt.TextAlignmentRole:
                return int(Qt.AlignCenter)
            return None
        if col == 1:
            if role in (Qt.DisplayRole, Qt.EditRole):
                return E.SURFACE_TYPES.get(s.kind, (s.kind,))[0]
            return None
        applies = self.applies(row, key)
        if role in (Qt.DisplayRole, Qt.EditRole):
            if not applies:
                return ""
            if key == "comment":
                return s.comment
            if key == "material":
                return E.material_text(self.system, s.material)
            if key == "semi_diameter":
                if s.semi_diameter is None:
                    v = self._auto_sd.get(row)
                    return "" if v is None else E.format_number(v)
                return E.format_number(s.semi_diameter) if role == Qt.DisplayRole else repr(s.semi_diameter)
            v = E.get_value(s, key)
            if role == Qt.EditRole:
                return "Infinity" if isinstance(v, float) and math.isinf(v) else repr(v)
            return E.format_number(v)
        if role == Qt.TextAlignmentRole:
            if key in ("comment", "material"):
                return int(Qt.AlignLeft | Qt.AlignVCenter)
            return int(Qt.AlignRight | Qt.AlignVCenter)
        if not applies:
            if role == Qt.BackgroundRole:
                return QColor(242, 242, 242)
            return None
        if role == MarkerRole:
            return self.marker(row, key)
        if role == Qt.BackgroundRole:
            if E.solve_on(self.system, row, key) is not None:
                return SOLVE_BG
            if E.variable_on(self.system, row, key) is not None:
                return VAR_BG
            return None
        if role == Qt.ForegroundRole and key == "semi_diameter" and s.semi_diameter is None:
            return QColor(110, 110, 110)
        if role == Qt.ToolTipRole:
            return self.tooltip(row, key)
        return None

    def marker(self, row, key):
        x = E.solve_on(self.system, row, key)
        if x is not None:
            return E.SOLVE_CODES.get(type(x).__name__, "S")
        if E.variable_on(self.system, row, key) is not None:
            return "V"
        if key == "semi_diameter" and self.system.surfaces[row].semi_diameter is not None:
            return "U"
        return ""

    def tooltip(self, row, key):
        parts = [f"Surface {row}: {key}"]
        x = E.solve_on(self.system, row, key)
        if x is not None:
            parts.append(E.describe_solve(x))
        v = E.variable_on(self.system, row, key)
        if v is not None:
            b = "" if v.min is None and v.max is None else f" in [{v.min}, {v.max}]"
            parts.append(f"Variable {v.param}{b}")
        if key == "semi_diameter":
            parts.append("fixed (type a value; clear the cell for automatic)"
                         if self.system.surfaces[row].semi_diameter is not None else "automatic")
        if key == "material":
            parts.append("catalog glass (e.g. N-BK7, SCHOTT:N-SF6), model glass 'nd,vd', index, or MIRROR")
        return "\n".join(parts)

    def flags(self, index):
        if not index.isValid():
            return Qt.NoItemFlags
        f = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        row, col = index.row(), index.column()
        if col == 0:
            return f
        if col == 1:
            return f | Qt.ItemIsEditable
        key = self.key(row, col)
        if self.applies(row, key) and E.solve_on(self.system, row, key) is None:
            f |= Qt.ItemIsEditable
        return f

    def setData(self, index, value, role=Qt.EditRole):
        if role != Qt.EditRole or not index.isValid():
            return False
        row, col = index.row(), index.column()
        if col == 1:
            kind = value if value in E.SURFACE_TYPES else next(
                (k for k, (lab, _) in E.SURFACE_TYPES.items() if lab == value), None)
            if kind is None:
                return False
            return self.doc.modify(f"Surface {row} type {kind}", lambda s: E.change_type(s, row, kind))
        key = self.key(row, col)
        text = str(value)
        if text == self.data(index, Qt.EditRole):
            return False
        label = self.headerData(col, Qt.Horizontal) if col < PAR0 else key
        return self.doc.modify(f"Surface {row} {label} = {text}", lambda s: E.set_cell(s, row, key, text))


class MarkerDelegate(QStyledItemDelegate):
    """Draws the V / solve / U marker at the right edge of a cell and supplies editors."""

    def __init__(self, model: LensDataModel, parent=None):
        super().__init__(parent)
        self.model = model

    def paint(self, painter, option, index):
        m = index.data(MarkerRole)
        if m:
            option.rect = option.rect.adjusted(0, 0, -14, 0)
            super().paint(painter, option, index)
            option.rect = option.rect.adjusted(0, 0, 14, 0)
            r = QRect(option.rect.right() - 13, option.rect.top() + 2, 12, option.rect.height() - 4)
            painter.save()
            painter.setPen(QColor(30, 80, 170) if m != "U" else QColor(120, 120, 120))
            f = painter.font()
            f.setBold(True)
            f.setPointSizeF(max(6.0, f.pointSizeF() - 1))
            painter.setFont(f)
            painter.drawText(r, Qt.AlignCenter, m)
            painter.restore()
        else:
            super().paint(painter, option, index)

    def createEditor(self, parent, option, index):
        if index.column() == 1:
            cb = QComboBox(parent)
            for k, (lab, _) in E.SURFACE_TYPES.items():
                cb.addItem(lab, k)
            return cb
        if index.data(KeyRole) == "material":
            return MaterialEditor(self, index, parent)
        return QLineEdit(parent)

    def setEditorData(self, editor, index):
        if isinstance(editor, QComboBox):
            editor.setCurrentIndex(max(0, editor.findText(index.data(Qt.EditRole))))
            editor.showPopup()
        else:
            editor.setText(index.data(Qt.EditRole) or "")
            editor.selectAll()

    def setModelData(self, editor, model, index):
        if isinstance(editor, QComboBox):
            model.setData(index, editor.currentData(), Qt.EditRole)
        else:
            model.setData(index, editor.text(), Qt.EditRole)


class MaterialEditor(QWidget):
    """Material cell editor: text with glass-name completion plus a "..." button
    that opens the material picker dialog."""

    def __init__(self, delegate, index, parent=None):
        super().__init__(parent)
        self.delegate, self.row = delegate, index.row()
        self.edit = QLineEdit(self)
        names = sorted({g.name for g in delegate.model.system.library.all_glasses()}) + ["MIRROR"]
        c = QCompleter(names, self.edit)
        c.setCaseSensitivity(Qt.CaseInsensitive)
        self.edit.setCompleter(c)
        self.button = QToolButton(self)
        self.button.setText("...")
        self.button.setToolTip("Choose a material from the catalog")
        self.button.clicked.connect(self.pick)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.edit, 1)
        lay.addWidget(self.button)
        self.setFocusProxy(self.edit)
        self.setAutoFillBackground(True)

    def setText(self, t):
        self.edit.setText(t)

    def text(self):
        return self.edit.text()

    def selectAll(self):
        self.edit.selectAll()

    def pick(self):
        from .material_dialog import MaterialDialog
        system = self.delegate.model.system
        dlg = MaterialDialog(system, system.surfaces[self.row].material, f"Material after surface {self.row}",
                             self.window())
        if dlg.exec() == QDialog.Accepted:
            self.edit.setText(dlg.spec)
            self.delegate.commitData.emit(self)
            self.delegate.closeEditor.emit(self)


class LensDataEditor(QWidget):
    """The Lens Data Editor widget (table plus context menu and key bindings)."""

    statusMessage = Signal(str)

    def __init__(self, doc, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.model = LensDataModel(doc, self)
        self.view = QTableView(self)
        self.view.setModel(self.model)
        self.view.setItemDelegate(MarkerDelegate(self.model, self.view))
        self.view.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.view.setSelectionMode(QAbstractItemView.SingleSelection)
        self.view.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed
                                  | QAbstractItemView.AnyKeyPressed)
        self.view.verticalHeader().setVisible(False)
        self.view.verticalHeader().setDefaultSectionSize(22)
        hh = self.view.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.Interactive)
        hh.setDefaultSectionSize(92)
        self.view.setColumnWidth(0, 44)
        self.view.setColumnWidth(1, 110)
        self.view.setColumnWidth(2, 90)
        for c in (3, 4):
            self.view.setColumnWidth(c, 100)
        self.view.setColumnWidth(5, 120)
        self.view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self._context_menu)
        self.view.selectionModel().currentChanged.connect(lambda cur, _: self.model.set_current_row(cur.row()))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.view)
        self._make_actions()
        self.view.setCurrentIndex(self.model.index(1, 3))

    # -- actions --------------------------------------------------------------------
    def _make_actions(self):
        def act(text, slot, shortcut=None):
            a = QAction(text, self)
            if shortcut:
                a.setShortcut(QKeySequence(shortcut))
                a.setShortcutContext(Qt.WidgetWithChildrenShortcut)
            a.triggered.connect(slot)
            self.view.addAction(a)
            return a

        self.act_insert = act("Insert Surface", self.insert_before, "Insert")
        self.act_insert_after = act("Insert Surface After", self.insert_after, "Ctrl+Insert")
        self.act_delete = act("Delete Surface", self.delete_surface, "Shift+Delete")
        self.act_variable = act("Toggle Variable", self.toggle_variable, "Ctrl+Shift+V")
        self.act_props = act("Surface Properties...", self.surface_properties, "Ctrl+Shift+P")
        self.act_material = act("Choose Material...", self.choose_material, "Ctrl+G")

    def current(self):
        idx = self.view.currentIndex()
        row = idx.row() if idx.isValid() else 1
        key = self.model.key(row, idx.column()) if idx.isValid() else None
        return row, key

    def select(self, row, col=None):
        col = self.view.currentIndex().column() if col is None else col
        self.view.setCurrentIndex(self.model.index(max(0, min(row, self.model.rowCount() - 1)), max(col, 0)))

    def insert_before(self):
        row, _ = self.current()
        row = max(1, row)
        if self.doc.modify(f"Insert surface {row}", lambda s: E.insert_surface(s, row)):
            self.select(row)

    def insert_after(self):
        row, _ = self.current()
        row = min(row + 1, self.doc.system.image_index)
        if self.doc.modify(f"Insert surface {row}", lambda s: E.insert_surface(s, row)):
            self.select(row)

    def delete_surface(self):
        row, _ = self.current()
        if self.doc.modify(f"Delete surface {row}", lambda s: E.delete_surface(s, row)):
            self.select(row)

    def make_stop(self, row):
        self.doc.modify(f"Stop on surface {row}", lambda s: E.set_stop(s, row))

    def can_vary(self, row, key):
        if key is None or not self.model.applies(row, key):
            return False
        if key in ("comment", "semi_diameter", "order"):
            return False
        if key == "thickness" and math.isinf(self.doc.system.surfaces[row].thickness):
            return False
        if key == "material":
            m = self.doc.system.material(row)
            return not m.is_mirror and m.nd != 1.0
        return True

    def toggle_variable(self, row=None, key=None):
        if row is None or key is None:
            row, key = self.current()
        if not self.can_vary(row, key):
            self.statusMessage.emit("This cell cannot be a variable")
            return
        if E.variable_on(self.doc.system, row, key) is not None:
            v = E.variable_on(self.doc.system, row, key)
            self.doc.modify(f"Remove variable S{row} {v.param}", lambda s: opt.remove_variable(s, row, v.param))
        elif key == "material":
            self.vary_glass(row)
        else:
            def fn(s):
                opt.remove_solve(s, row, E.cell_param(key))
                opt.set_variable(s, row, E.cell_param(key))
            self.doc.modify(f"Variable S{row} {key}", fn)

    def vary_glass(self, row):
        def fn(s):
            opt.remove_solve(s, row, "material")
            opt.set_variable(s, row, "glass.nd")
            opt.set_variable(s, row, "glass.vd")
        self.doc.modify(f"Vary glass on S{row} (model nd, Vd)", fn)

    def remove_solve(self, row, key):
        self.doc.modify(f"Remove solve S{row} {key}", lambda s: opt.remove_solve(s, row, E.cell_param(key)))

    def set_solve_dialog(self, row, key, name):
        current = E.solve_on(self.doc.system, row, key)
        dlg = SolveDialog(name, row, key, current if type(current).__name__ == name else None, self)
        if dlg.exec() == QDialog.Accepted:
            values = dlg.values()

            def fn(s):
                opt.remove_variable(s, row, E.cell_param(key))
                opt.set_solve(s, E.make_solve(name, row, key, values))
            self.doc.modify(f"{E.SOLVE_TITLES[name]} solve on S{row} {key}", fn)

    def choose_material(self, row=None):
        """Open the material picker for the material after surface ``row`` (default: current row)."""
        if row is None or row is False:
            row, _ = self.current()
        if not self.model.applies(row, "material"):
            self.statusMessage.emit("This surface has no material")
            return
        from .material_dialog import MaterialDialog
        s = self.doc.system
        dlg = MaterialDialog(s, s.surfaces[row].material, f"Material after surface {row}", self)
        if dlg.exec() == QDialog.Accepted:
            spec = dlg.spec
            self.doc.modify(f"Surface {row} material = {spec or 'air'}",
                            lambda x: E.set_cell(x, row, "material", spec))

    def surface_properties(self, row=None):
        if row is None or row is False:
            row, _ = self.current()
        dlg = SurfacePropertiesDialog(self.doc.system, row, self)
        if dlg.exec() == QDialog.Accepted:
            self.doc.modify(f"Surface {row} properties", lambda s: dlg.apply(s))

    def _context_menu(self, pos):
        idx = self.view.indexAt(pos)
        if not idx.isValid():
            return
        self.view.setCurrentIndex(idx)
        row, col = idx.row(), idx.column()
        key = self.model.key(row, col)
        sys_ = self.doc.system
        m = QMenu(self)
        if col >= 3 and self.model.applies(row, key):
            if self.can_vary(row, key):
                is_var = E.variable_on(sys_, row, key) is not None
                a = m.addAction("Remove Variable" if is_var else
                                ("Vary Glass (model nd, Vd)" if key == "material" else "Make Variable"))
                a.triggered.connect(lambda: self.toggle_variable(row, key))
            names = E.SOLVES_FOR.get(key, ["Pickup"] if key not in ("comment", "semi_diameter") else [])
            if names and row not in (0,) and not (key == "thickness" and row == sys_.image_index):
                sm = m.addMenu("Solve")
                for n in names:
                    sm.addAction(E.SOLVE_TITLES[n] + "...").triggered.connect(
                        lambda _=False, n=n: self.set_solve_dialog(row, key, n))
                if E.solve_on(sys_, row, key) is not None:
                    sm.addSeparator()
                    sm.addAction("Remove Solve (fixed)").triggered.connect(lambda: self.remove_solve(row, key))
            if key == "semi_diameter" and sys_.surfaces[row].semi_diameter is not None:
                m.addAction("Automatic Semi-Diameter").triggered.connect(
                    lambda: self.doc.modify(f"Automatic semi-diameter S{row}",
                                            lambda s: E.set_cell(s, row, "semi_diameter", "")))
            m.addSeparator()
        if self.model.applies(row, "material"):
            m.addAction("Choose Material...").triggered.connect(lambda: self.choose_material(row))
        tm = m.addMenu("Surface Type")
        for k, (lab, _) in E.SURFACE_TYPES.items():
            a = tm.addAction(lab)
            a.setCheckable(True)
            a.setChecked(sys_.surfaces[row].kind == k)
            a.triggered.connect(lambda _=False, k=k: self.doc.modify(
                f"Surface {row} type {k}", lambda s: E.change_type(s, row, k)))
        if 0 < row < sys_.image_index:
            m.addAction("Make Stop").triggered.connect(lambda: self.make_stop(row))
        m.addAction(self.act_props)
        m.addSeparator()
        m.addAction(self.act_insert)
        m.addAction(self.act_insert_after)
        m.addAction(self.act_delete)
        m.exec(self.view.viewport().mapToGlobal(pos))


class SolveDialog(QDialog):
    """Parameters of one solve (fields taken from the solve class)."""

    INT_FIELDS = ("from_surface", "center_surface")

    def __init__(self, name, row, key, current=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{E.SOLVE_TITLES[name]} solve on surface {row} ({key})")
        self.name, self.key = name, key
        form = QFormLayout()
        doc = (E.solve_class(name).__doc__ or "").strip()
        lab = QLabel(" ".join(doc.split()))
        lab.setWordWrap(True)
        self.edits = {}
        for f, default in E.solve_fields(name):
            if name == "Pickup" and key == "material" and f in ("scale", "offset", "from_param"):
                continue
            v = getattr(current, f) if current is not None else default
            if name == "Pickup" and f == "from_surface" and v is None:
                v = max(1, row - 1)
            ed = QLineEdit("" if v is None else str(v))
            if f == "from_param":
                ed.setPlaceholderText(f"same as this cell ({key})")
            if f == "height" and name == "EdgeThickness":
                ed.setPlaceholderText("larger semi-diameter")
            form.addRow(f.replace("_", " ").capitalize(), ed)
            self.edits[f] = ed
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(lab)
        lay.addLayout(form)
        lay.addWidget(bb)
        self.setMinimumWidth(380)

    def values(self):
        out = {}
        for f, ed in self.edits.items():
            t = ed.text().strip()
            if not t:
                if f == "from_surface":
                    raise ValueError("from surface is required")
                continue
            if f in self.INT_FIELDS:
                out[f] = int(t)
            elif f == "from_param":
                out[f] = E.cell_param(t)
            else:
                out[f] = E.parse_number(t)
        return out

    def _accept(self):
        try:
            self.values()
        except ValueError as e:
            QMessageBox.warning(self, "Solve", str(e))
            return
        self.accept()


APERTURE_KINDS = [("None", None, ()), ("Circular aperture", "CIRCULAR", ("r_max", "r_min", "dx", "dy")),
                  ("Circular obscuration", "OBSCURATION", ("radius", "dx", "dy")),
                  ("Rectangular aperture", "RECTANGULAR", ("half_x", "half_y", "dx", "dy")),
                  ("Elliptical aperture", "ELLIPTICAL", ("half_x", "half_y", "dx", "dy"))]


class SurfacePropertiesDialog(QDialog):
    """Aperture, stop, comment and (XY polynomial) terms of one surface."""

    def __init__(self, system, row, parent=None):
        super().__init__(parent)
        self.row = row
        s = system.surfaces[row]
        self.setWindowTitle(f"Surface {row} properties ({E.SURFACE_TYPES.get(s.kind, (s.kind,))[0]})")
        form = QFormLayout()
        self.comment = QLineEdit(s.comment)
        form.addRow("Comment", self.comment)
        self.stop = QCheckBox("This surface is the aperture stop")
        self.stop.setChecked(s.stop)
        self.stop.setEnabled(0 < row < system.image_index)
        form.addRow("", self.stop)
        self.ap_kind = QComboBox()
        for lab, k, _ in APERTURE_KINDS:
            self.ap_kind.addItem(lab, k)
        cur = s.aperture.kind if s.aperture is not None else None
        self.ap_kind.setCurrentIndex(next(i for i, a in enumerate(APERTURE_KINDS) if a[1] == cur))
        form.addRow("Aperture", self.ap_kind)
        self.ap_edits = {}
        for name in ("r_max", "r_min", "radius", "half_x", "half_y", "dx", "dy"):
            ed = QLineEdit()
            if s.aperture is not None and hasattr(s.aperture, name):
                ed.setText(E.format_number(getattr(s.aperture, name), 10))
            form.addRow(f"  {name}", ed)
            self.ap_edits[name] = ed
        self.terms = None
        if s.kind == "XYPOLY":
            self.terms = QPlainTextEdit("\n".join(f"{i} {j} {c!r}" for i, j, c in s.terms))
            self.terms.setPlaceholderText("one term per line: i j coefficient   (x^i y^j / R0^(i+j))")
            form.addRow("XY terms", self.terms)
        self.ap_kind.currentIndexChanged.connect(self._update_enabled)
        self._update_enabled()
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(bb)

    def _update_enabled(self):
        names = APERTURE_KINDS[self.ap_kind.currentIndex()][2]
        for n, ed in self.ap_edits.items():
            ed.setEnabled(n in names)

    def _aperture(self):
        lab, kind, names = APERTURE_KINDS[self.ap_kind.currentIndex()]
        if kind is None:
            return None
        vals = {n: E.parse_number(self.ap_edits[n].text() or "0", allow_inf=False) for n in names}
        return S.aperture_from_dict({"type": kind, **vals})

    def _terms(self):
        out = []
        for line in self.terms.toPlainText().splitlines():
            if line.strip():
                i, j, c = line.replace(",", " ").split()
                out.append([int(i), int(j), float(c)])
        return out

    def _accept(self):
        try:
            self._aperture()
            if self.terms is not None:
                self._terms()
        except Exception as e:  # noqa: BLE001 - shown to the user
            QMessageBox.warning(self, "Surface properties", f"Invalid value: {e}")
            return
        self.accept()

    def apply(self, system):
        s = system.surfaces[self.row]
        s.comment = self.comment.text()
        s.aperture = self._aperture()
        if self.stop.isEnabled() and self.stop.isChecked():
            system.stop_index = self.row
        if self.terms is not None:
            s.terms = self._terms()
