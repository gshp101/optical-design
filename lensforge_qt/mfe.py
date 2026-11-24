"""Merit Function Editor: the operand spreadsheet.

Rows are :class:`lensforge.optimize.Operand`; parameters are typed as
``name=value`` pairs (e.g. ``surf=4, hy=1, py=1``).  Values and % contribution
are recomputed in the background after every change of the lens.  The help pages
(columns, weights, operands, an example) are in mfe_help.py.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QBrush, QColor, QKeySequence, QPainter, QPen
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QCompleter, QDialog, QDialogButtonBox,
                               QDoubleSpinBox, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QSpinBox, QStyledItemDelegate, QTableView,
                               QTextBrowser, QToolBar, QVBoxLayout, QWidget)

from lensforge import optimize as opt

from . import edits as E
from . import keys
from . import mfe_help
from . import workers
from .fonts import fixed_font
from .ownership import qt_owns_children

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


@qt_owns_children
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
        self._act(tb, "Wizard...", self.wizard, tip="Write a default merit function: RMS or PTV spot, wavefront, "
                  "angular or MTF, with pupil sampling, weighting and thickness boundary options.")
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
        label = QKeySequence(keys.primary(shortcut)).toString(QKeySequence.NativeText) if shortcut else ""
        if tip:
            a.setToolTip(f"{text} ({label})\n{tip}" if shortcut else f"{text}\n{tip}")
            a.setStatusTip(tip)
        if shortcut:
            a.setShortcuts([QKeySequence(s) for s in keys.shortcuts(shortcut)])  # Mac: Option+Up for Insert
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

            self.doc.modify("Default merit function", lambda s: opt.apply_default_merit(s, keep=keep, **kw))

    def operand_list(self):
        dlg = OperandList(self)
        if dlg.exec() == QDialog.Accepted and dlg.chosen:
            t = dlg.chosen
            r = self.current_row()
            self.doc.modify(f"Insert {t}", lambda s: merit_function(s).insert(r, t, weight=1.0))
            self.view.setCurrentIndex(self.model.index(r, C_PARAMS))


class MeritPupilPreview(QWidget):
    """Picture of the wizard's pupil sampling: the unit pupil, the obscuration, and each ray of one field and
    wavelength drawn with an area proportional to its weight (hollow: the mirrored half that a symmetric lens
    does not trace)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(170, 190)
        self.set_sampling("gaussian", 3, 6, 6, 0.0, False)

    def sizeHint(self):
        return QSize(190, 212)

    def set_sampling(self, pupil, rings, arms, grid, obscuration, symmetric):
        self.pupil, self.rings, self.obscuration, self.symmetric = pupil, int(rings), float(obscuration), symmetric
        try:
            self.px, self.py, self.w = opt.pupil_samples(pupil, rings, arms, grid, symmetric, obscuration)
            self.error = None
        except ValueError as e:
            self.px = self.py = self.w = ()
            self.error = str(e)
        n = len(self.px)
        self.caption = (self.error or f"{n} rays per field and wavelength" + (" (half pupil)" if symmetric else ""))
        self.setToolTip("Where the merit function's rays cross the entrance pupil, for each field and wavelength.\n"
                        "Dot area is proportional to the ray's weight." + ("\nHollow dots: the mirrored half, not "
                                                                           "traced for a symmetric lens."
                                                                           if symmetric else ""))
        self.update()

    @property
    def count(self) -> int:
        return len(self.px)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pal = self.palette()
        fm = p.fontMetrics()
        text_h = 2 * fm.height() + 4
        side = min(self.width(), self.height() - text_h) - 8
        r = side / 2
        c = QPointF(self.width() / 2, 4 + r)
        p.setPen(QPen(pal.mid().color(), 1))
        p.setBrush(pal.base())
        p.drawEllipse(c, r, r)
        if self.obscuration > 0:
            p.setBrush(QBrush(pal.mid().color(), Qt.BDiagPattern))
            p.drawEllipse(c, r * self.obscuration, r * self.obscuration)
        p.setPen(QPen(pal.mid().color(), 1, Qt.DotLine))
        p.setBrush(Qt.NoBrush)
        p.drawLine(QPointF(c.x() - r, c.y()), QPointF(c.x() + r, c.y()))
        p.drawLine(QPointF(c.x(), c.y() - r), QPointF(c.x(), c.y() + r))
        n = len(self.px)
        if n:
            if self.pupil == "gaussian":  # the quadrature rings
                for rr in sorted({round(float(math.hypot(x, y)), 9) for x, y in zip(self.px, self.py)}):
                    p.drawEllipse(c, rr * r, rr * r)
            base = max(1.6, min(5.0, 0.9 * r / n ** 0.5))
            wmax = max(self.w)
            colour = QColor("#1f5f99")
            for x, y, w in zip(self.px, self.py, self.w):
                d = base * (w / wmax) ** 0.5
                p.setPen(Qt.NoPen)
                p.setBrush(colour)
                p.drawEllipse(QPointF(c.x() + x * r, c.y() - y * r), d, d)
                if self.symmetric and abs(x) > 1e-9:  # the mirrored half
                    p.setPen(QPen(colour, 1))
                    p.setBrush(Qt.NoBrush)
                    p.drawEllipse(QPointF(c.x() - x * r, c.y() - y * r), d, d)
        p.setPen(pal.text().color())
        p.drawText(QRectF(0, 4 + side + 2, self.width(), text_h), Qt.AlignHCenter | Qt.AlignTop | Qt.TextWordWrap,
                   self.caption)
        p.end()


@qt_owns_children
class MeritWizard(QDialog):
    """Options of :func:`lensforge.optimize.default_merit` (the optimisation wizard).

    Opens with the settings that built the lens's current default rows (saved with the lens), or the
    defaults; Reset puts the defaults back."""

    BOUNDS = (("glass_min", "Min centre", 2.0), ("glass_max", "Max centre", 20.0), ("glass_edge", "Min edge", 1.0),
              ("glass_max_edge", "Max edge", 30.0), ("air_min", "Min centre", 0.5), ("air_max", "Max centre", 1000.0),
              ("air_edge", "Min edge", 0.5), ("air_max_edge", "Max edge", 1000.0))

    def __init__(self, system, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Merit Function Wizard")
        self.system = system
        self._help = None
        n_surf = system.num_surfaces
        # -- image quality
        self.optimization = QComboBox()
        self.optimization.addItem("RMS", "rms")
        self.optimization.addItem("PTV (peak to valley)", "ptv")
        self.optimization.setToolTip("RMS: root-mean-square error over the pupil (the usual choice).\n"
                                     "PTV: the largest error (spot) or max - min (wavefront).")
        self.kind = QComboBox()
        for key, (op, label) in opt.CRITERIA.items():
            self.kind.addItem({"mtf": "MTF (1 - average MTF)"}.get(key, label), key)
        self.kind.setToolTip("What is minimised: transverse ray error (spot), OPD (wavefront), image-space ray "
                             "angle (angular, for afocal systems) or 1 - MTF.\nX / Y use only that component; "
                             "X + Y uses both separately.")
        self.reference = QComboBox()
        self.reference.addItem("Centroid", "centroid")
        self.reference.addItem("Chief ray", "chief")
        self.reference.addItem("Unreferenced", "unreferenced")
        self.reference.setToolTip("What the errors are measured from: the centroid of the rays (tilt removed for "
                                  "wavefront), the chief ray, or nothing (spot: the image-surface origin; "
                                  "wavefront: OPD as traced).")
        self.freq = QDoubleSpinBox()
        self.freq.setRange(0.1, 10000)
        self.freq.setValue(30)
        # -- pupil integration
        self.pupil = QComboBox()
        self.pupil.addItem("Gaussian quadrature", "gaussian")
        self.pupil.addItem("Rectangular array", "rectangular")
        self.pupil.setToolTip("Gaussian quadrature: few rays on rings and arms, very accurate for smooth "
                              "aberrations.\nRectangular array: a grid x grid array of rays, better for vignetted "
                              "or odd-shaped pupils.")
        self.rings = QSpinBox()
        self.rings.setRange(1, 20)
        self.rings.setValue(3)
        self.arms = QSpinBox()
        self.arms.setRange(4, 36)
        self.arms.setValue(6)
        self.grid = QSpinBox()
        self.grid.setRange(2, 40)
        self.grid.setValue(6)
        self.obscuration = QDoubleSpinBox()
        self.obscuration.setRange(0.0, 0.99)
        self.obscuration.setDecimals(3)
        self.obscuration.setSingleStep(0.05)
        self.obscuration.setToolTip("Leave out rays inside this fraction of the pupil radius (central obscuration).")
        # -- weighting and rays
        self.field_weighting = QComboBox()
        self.field_weighting.addItem("Field weights (Fields dialog)", "system")
        self.field_weighting.addItem("Equal", "equal")
        self.wave_weighting = QComboBox()
        self.wave_weighting.addItem("Wavelength weights (Wavelengths dialog)", "system")
        self.wave_weighting.addItem("Equal", "equal")
        self.weight = QDoubleSpinBox()
        self.weight.setRange(0.0001, 1e6)
        self.weight.setDecimals(4)
        self.weight.setValue(1.0)
        self.weight.setToolTip("Scales the weight of every image-quality row.")
        self.symmetric = QComboBox()
        self.symmetric.addItem("Automatic (from the lens)", None)
        self.symmetric.addItem("Yes: trace half the pupil", True)
        self.symmetric.addItem("No: trace the whole pupil", False)
        self.symmetric.setToolTip("Assume the lens is symmetric about the y-z plane, so only half the pupil is "
                                  "traced. Automatic checks the lens at every evaluation.")
        self.delete_vignetted = QCheckBox("Delete vignetted rays")
        self.delete_vignetted.setChecked(True)
        self.delete_vignetted.setToolTip("Ticked: rays stopped by surface apertures are left out.\nCleared: every "
                                         "ray is traced ignoring apertures.")
        # -- boundaries
        self.bounds = {}
        bgrid = QGridLayout()
        bgrid.addWidget(QLabel("<b>Glass</b>"), 0, 0, 1, 2)
        bgrid.addWidget(QLabel("<b>Air</b>"), 0, 2, 1, 2)
        for k, (name, label, val) in enumerate(self.BOUNDS):
            cb = QCheckBox(label)
            sb = QDoubleSpinBox()
            sb.setRange(0, 1e5)
            sb.setDecimals(4)
            sb.setValue(val)
            sb.setEnabled(False)
            cb.toggled.connect(sb.setEnabled)
            col = 0 if name.startswith("glass") else 2
            bgrid.addWidget(cb, 1 + k % 4, col)
            bgrid.addWidget(sb, 1 + k % 4, col + 1)
            self.bounds[name] = (cb, sb)
        self.bsurf = QCheckBox("Only surfaces")
        self.bfirst = QSpinBox()
        self.blast = QSpinBox()
        for sb, v in ((self.bfirst, 1), (self.blast, max(1, n_surf - 3))):
            sb.setRange(1, max(1, n_surf - 3))
            sb.setValue(v)
            sb.setEnabled(False)
            self.bsurf.toggled.connect(sb.setEnabled)
        srow = QHBoxLayout()
        srow.addWidget(self.bsurf)
        srow.addWidget(self.bfirst)
        srow.addWidget(QLabel("to"))
        srow.addWidget(self.blast)
        srow.addStretch(1)
        self.bweight = QDoubleSpinBox()
        self.bweight.setRange(0.0001, 1e6)
        self.bweight.setDecimals(4)
        self.bweight.setValue(1.0)
        # -- rows and configurations
        mc = getattr(system, "multiconfig", None)
        self.all_configs = QCheckBox(f"All {mc.n_configs} configurations (a CONF row heads each group)"
                                     if mc is not None and mc.n_configs > 1 else "All configurations")
        self.all_configs.setChecked(True)
        self.all_configs.setEnabled(mc is not None and mc.n_configs > 1)
        n_rows = len(getattr(getattr(system, "merit_function", None), "rows", []) or [])
        self.start = QCheckBox("Start at row")
        self.start.setToolTip("Keep the rows above this one as they are and replace this row and everything "
                              "below it by the default rows.")
        self.start_row = QSpinBox()
        self.start_row.setRange(1, n_rows + 1)
        self.start_row.setValue(n_rows + 1)
        self.start_row.setEnabled(False)
        self.keep = QCheckBox("Keep my other operands (above the default rows)")
        self.keep.setChecked(True)
        self.start.toggled.connect(self.start_row.setEnabled)
        self.start.toggled.connect(lambda on: self.keep.setEnabled(not on))
        strow = QHBoxLayout()
        strow.addWidget(self.start)
        strow.addWidget(self.start_row)
        strow.addStretch(1)

        def group(title, rows):
            g = QGroupBox(title)
            f = QFormLayout(g)
            for label, w in rows:
                f.addRow(label, w)
            return g
        self.freq_label = QLabel(f"MTF frequency (cycles/{system.units})")
        g1 = group("Image quality", [("Optimisation type", self.optimization), ("Criterion", self.kind),
                                     ("Reference", self.reference), (self.freq_label, self.freq)])
        self.rings_label, self.arms_label, self.grid_label = QLabel("Rings"), QLabel("Arms"), QLabel("Grid")
        g2 = QGroupBox("Pupil integration")
        f2 = QFormLayout()
        for label, w in (("Method", self.pupil), (self.rings_label, self.rings), (self.arms_label, self.arms),
                         (self.grid_label, self.grid), ("Obscuration", self.obscuration)):
            f2.addRow(label, w)
        self.preview = MeritPupilPreview()
        h2 = QHBoxLayout(g2)
        h2.addLayout(f2, 1)
        h2.addWidget(self.preview)
        g3 = group("Weighting and rays", [("Fields", self.field_weighting), ("Wavelengths", self.wave_weighting),
                                          ("Overall weight", self.weight), ("Assume axial symmetry", self.symmetric),
                                          ("", self.delete_vignetted)])
        g4 = QGroupBox("Thickness boundaries")
        v4 = QVBoxLayout(g4)
        v4.addLayout(bgrid)
        v4.addLayout(srow)
        f4 = QFormLayout()
        f4.addRow("Boundary weight", self.bweight)
        v4.addLayout(f4)
        g5 = group("Rows", [("Configurations", self.all_configs), ("", strow), ("", self.keep)])
        cols = QHBoxLayout()
        left, right = QVBoxLayout(), QVBoxLayout()
        for w in (g1, g2, g3):
            left.addWidget(w)
        for w in (g4, g5):
            right.addWidget(w)
        left.addStretch(1)
        right.addStretch(1)
        cols.addLayout(left)
        cols.addLayout(right)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel | QDialogButtonBox.Help
                              | QDialogButtonBox.Reset)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        bb.button(QDialogButtonBox.Reset).setToolTip("Put every option back to its default.")
        bb.button(QDialogButtonBox.Reset).clicked.connect(self.reset)
        bb.button(QDialogButtonBox.Help).setToolTip("Help on every wizard option (F1).")
        bb.helpRequested.connect(self.show_help)
        lay = QVBoxLayout(self)
        lay.addLayout(cols)
        lay.addWidget(bb)
        for w in (self.kind, self.pupil, self.symmetric):
            w.currentIndexChanged.connect(self._update)
        for w in (self.rings, self.arms, self.grid, self.obscuration):
            w.valueChanged.connect(self._update_preview)
        self._defaults = self.options()[0]
        wiz = getattr(getattr(system, "merit_function", None), "wizard", None)
        if wiz:
            self.set_options(wiz)
        self._update()

    def show_help(self):
        """The wizard's help page in a window of its own (the main help browser is blocked while this
        modal dialog is open); also in Help > Help Contents > Merit Function Editor."""
        if self._help is None:
            self._help = QDialog(self)
            self._help.setWindowTitle("Merit Function Wizard Help")
            self._help.resize(720, 640)
            tb = QTextBrowser(self._help)
            tb.setHtml(mfe_help.topic_html(mfe_help.WIZARD))
            QVBoxLayout(self._help).addWidget(tb)
        self._help.show()
        self._help.raise_()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_F1:
            self.show_help()
            return
        super().keyPressEvent(e)

    def _update(self):
        mtf = self.kind.currentData() == "mtf"
        for w in (self.optimization, self.reference, self.pupil, self.rings, self.arms, self.grid, self.obscuration,
                  self.wave_weighting, self.symmetric, self.delete_vignetted):
            w.setEnabled(not mtf)
        self.freq.setEnabled(mtf)
        self.freq_label.setEnabled(mtf)
        gq = self.pupil.currentData() == "gaussian"
        for w in (self.rings, self.arms, self.rings_label, self.arms_label):
            w.setEnabled(gq and not mtf)
        self.grid.setEnabled(not gq and not mtf)
        self.grid_label.setEnabled(not gq and not mtf)
        self.preview.setEnabled(not mtf)
        self._update_preview()

    def _update_preview(self):
        sym = self.symmetric.currentData()
        if sym is None:
            sym = opt.is_symmetric(self.system)
        self.preview.set_sampling(self.pupil.currentData(), self.rings.value(), self.arms.value(), self.grid.value(),
                                  self.obscuration.value(), sym)

    def reset(self):
        self.set_options(self._defaults)

    def set_options(self, o):
        """Show the options of a :func:`lensforge.optimize.apply_default_merit` call (``mf.wizard``)."""
        def pick(combo, value):
            i = combo.findData(value)
            if i >= 0:
                combo.setCurrentIndex(i)
        pick(self.kind, o.get("kind", "spot"))
        pick(self.optimization, o.get("optimization", "rms"))
        pick(self.reference, o.get("reference", "centroid"))
        pick(self.pupil, o.get("pupil", "gaussian"))
        pick(self.field_weighting, o.get("field_weighting", "system"))
        pick(self.wave_weighting, o.get("wavelength_weighting", "system"))
        pick(self.symmetric, o.get("symmetric"))
        self.rings.setValue(int(o.get("rings", 3)))
        self.arms.setValue(int(o.get("arms", 6)))
        self.grid.setValue(int(o.get("grid", 6)))
        self.obscuration.setValue(float(o.get("obscuration", 0.0)))
        self.freq.setValue(float(o.get("frequency") or 30))
        self.weight.setValue(float(o.get("weight", 1.0)))
        self.delete_vignetted.setChecked(bool(o.get("delete_vignetted", True)))
        for name, label, val in self.BOUNDS:
            cb, sb = self.bounds[name]
            v = o.get(name)
            cb.setChecked(v is not None)
            if v is not None:
                sb.setValue(float(v))
        bs = o.get("boundary_surfaces")
        self.bsurf.setChecked(bs is not None)
        if bs is not None:
            self.bfirst.setValue(int(bs[0]))
            self.blast.setValue(int(bs[1]))
        self.bweight.setValue(float(o.get("boundary_weight", 1.0)))
        if self.all_configs.isEnabled():
            self.all_configs.setChecked(o.get("configs", None) != [])
        st = o.get("start_at")
        self.start.setChecked(st is not None)
        if st is not None:
            self.start_row.setValue(int(st) + 1)
        self.keep.setChecked(bool(o.get("keep", True)))
        self._update()

    def options(self):
        """(default_merit keyword arguments, keep) -- start_at is in the keywords when set."""
        kw = dict(kind=self.kind.currentData())
        if kw["kind"] == "mtf":
            kw["frequency"] = self.freq.value()
        else:
            kw.update(optimization=self.optimization.currentData(), reference=self.reference.currentData(),
                      pupil=self.pupil.currentData(), obscuration=self.obscuration.value(),
                      wavelength_weighting=self.wave_weighting.currentData(),
                      symmetric=self.symmetric.currentData(), delete_vignetted=self.delete_vignetted.isChecked())
            if kw["pupil"] == "gaussian":
                kw.update(rings=self.rings.value(), arms=self.arms.value())
            else:
                kw["grid"] = self.grid.value()
        kw.update(field_weighting=self.field_weighting.currentData(), weight=self.weight.value())
        for name, (cb, sb) in self.bounds.items():
            if cb.isChecked():
                kw[name] = sb.value()
        if self.bsurf.isChecked():
            kw["boundary_surfaces"] = [self.bfirst.value(), self.blast.value()]
        kw["boundary_weight"] = self.bweight.value()
        if self.all_configs.isEnabled() and not self.all_configs.isChecked():
            kw["configs"] = []  # the current configuration only
        if self.start.isChecked():
            kw["start_at"] = self.start_row.value() - 1
        return kw, self.keep.isChecked()


@qt_owns_children
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
