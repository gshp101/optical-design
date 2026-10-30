"""Dockable analysis windows with embedded matplotlib and auto-update."""

from __future__ import annotations

import itertools

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDockWidget, QDoubleSpinBox, QFileDialog, QHBoxLayout, QLabel,
                               QPlainTextEdit, QPushButton, QSpinBox, QStackedWidget, QVBoxLayout, QWidget)

from . import workers
from .analyses import REGISTRY
from .fonts import fixed_font

_ids = itertools.count(1)

#: how to fix a lens whose glass is missing (shown in analysis windows and the open warning)
MISSING_HINT = ("Choose a replacement in the Material column of the Lens Data Editor (Ctrl+G), "
                "or load a catalog that has it with File > Load Glass Catalog (AGF).")


class SettingsBar(QWidget):
    """One widget per analysis setting; emits :attr:`changed`."""

    changed = Signal()

    def __init__(self, spec, doc, values=None, parent=None):
        super().__init__(parent)
        self.spec, self.doc = spec, doc
        self.widgets = {}
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 2, 4, 2)
        values = values or {}
        for st in spec.settings:
            w = self._make(st, values.get(st.name, st.default))
            self.widgets[st.name] = (st, w)
            if st.kind != "bool":
                lay.addWidget(QLabel(st.label))
            lay.addWidget(w)
        lay.addStretch(1)
        doc.changed.connect(self.sync_choices)

    def _make(self, st, value):
        if st.kind in ("field", "field_all", "wave", "wave_all", "config_all"):
            w = QComboBox()
            self._fill(st, w, value)
            w.currentIndexChanged.connect(lambda _: self.changed.emit())
        elif st.kind == "surface":
            w = QSpinBox()
            w.setRange(0, self.doc.system.image_index)
            w.setValue(int(value))
            w.valueChanged.connect(lambda _: self.changed.emit())
        elif st.kind == "int":
            w = QSpinBox()
            w.setRange(int(st.minimum), int(st.maximum))
            w.setValue(int(value))
            w.valueChanged.connect(lambda _: self.changed.emit())
        elif st.kind == "float":
            w = QDoubleSpinBox()
            w.setDecimals(4)
            w.setRange(st.minimum, st.maximum)
            w.setValue(float(value))
            w.setKeyboardTracking(False)
            w.valueChanged.connect(lambda _: self.changed.emit())
        elif st.kind == "choice":
            w = QComboBox()
            for lab, v in st.choices:
                w.addItem(lab, v)
            w.setCurrentIndex(max(0, [v for _, v in st.choices].index(value) if value in
                                  [v for _, v in st.choices] else 0))
            w.currentIndexChanged.connect(lambda _: self.changed.emit())
        elif st.kind == "bool":
            w = QCheckBox(st.label)
            w.setChecked(bool(value))
            w.toggled.connect(lambda _: self.changed.emit())
        else:  # pragma: no cover
            raise ValueError(st.kind)
        return w

    def _fill(self, st, w, value):
        s = self.doc.system
        w.blockSignals(True)
        w.clear()
        if st.kind in ("field_all", "wave_all", "wave", "config_all"):
            w.addItem("All" if st.kind != "wave" else "Primary", -1)
        if st.kind == "config_all":
            mc = getattr(s, "multiconfig", None)
            for k in (mc.configs if mc is not None else ()):
                w.addItem(mc.name(k), k)
        elif st.kind.startswith("field"):
            for k, f in enumerate(s.fields):
                w.addItem(f"{k + 1}: ({f.x:g}, {f.y:g})", k)
        else:
            for k, wl in enumerate(s.wavelengths):
                w.addItem(f"{k + 1}: {wl.value:.4f} um", k)
        i = w.findData(value)
        w.setCurrentIndex(i if i >= 0 else 0)
        w.blockSignals(False)

    def sync_choices(self):
        """Keep field / wavelength / surface choices in step with the lens."""
        for name, (st, w) in self.widgets.items():
            if isinstance(w, QComboBox) and st.kind in ("field", "field_all", "wave", "wave_all", "config_all"):
                self._fill(st, w, w.currentData())
            elif st.kind == "surface":
                w.blockSignals(True)
                w.setMaximum(self.doc.system.image_index)
                w.blockSignals(False)

    def values(self):
        out = {}
        for name, (st, w) in self.widgets.items():
            if isinstance(w, QComboBox):
                out[name] = w.currentData()
            elif isinstance(w, QCheckBox):
                out[name] = w.isChecked()
            else:
                out[name] = w.value()
        return out


class AnalysisWindow(QDockWidget):
    """A dock holding one analysis (plot or text), recomputed when the lens changes."""

    closed = Signal(object)

    def __init__(self, key, doc, values=None, parent=None, on_rays=None):
        self.spec = REGISTRY[key]
        super().__init__(self.spec.title, parent)
        self.doc = doc
        self.setObjectName(f"analysis_{key}_{next(_ids)}")
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setAllowedAreas(Qt.AllDockWidgetAreas)
        self.result = None
        self.error = None
        self._request = 0
        self._busy = False
        self._pending = False
        self.updates = 0  # completed computations (tests use it)

        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        top = QHBoxLayout()
        top.setContentsMargins(2, 2, 2, 2)
        # which configuration of a multi-configuration lens to show ("Current" follows the editor)
        self.config_label = QLabel("Config")
        self.config = QComboBox()
        self.config.setToolTip("Configuration to analyse: Current follows the configuration shown in the Lens Data "
                               "Editor; a number keeps this window on that configuration")
        self._fill_configs((values or {}).get("config", 0))
        self.config.currentIndexChanged.connect(lambda _: self.request_update())
        top.addWidget(self.config_label)
        top.addWidget(self.config)
        self.settings = SettingsBar(self.spec, doc, values)
        self.settings.changed.connect(self.request_update)
        top.addWidget(self.settings, 1)
        self.auto = QCheckBox("Auto")
        self.auto.setChecked(True)
        self.auto.setToolTip("Recompute whenever the lens changes")
        upd = QPushButton("Update")
        upd.clicked.connect(self.request_update)
        if self.spec.uses_rays and on_rays is not None:
            rb = QPushButton("Input Rays...")
            rb.setToolTip("Ray sampling and user rays (File > Input Rays)")
            rb.clicked.connect(on_rays)
            top.addWidget(rb)
        top.addWidget(self.auto)
        top.addWidget(upd)
        lay.addLayout(top)

        self.stack = QStackedWidget()
        if self.spec.plot is not None:
            self.figure = Figure(figsize=(6, 4), dpi=90, layout="tight")
            self.canvas = FigureCanvasQTAgg(self.figure)
            pw = QWidget()
            pl = QVBoxLayout(pw)
            pl.setContentsMargins(0, 0, 0, 0)
            pl.addWidget(self.canvas, 1)
            self.toolbar = NavigationToolbar2QT(self.canvas, pw)
            self.toolbar.setIconSize(self.toolbar.iconSize() * 0.75)
            pl.addWidget(self.toolbar)
            self.stack.addWidget(pw)
            self.text = None
        else:
            self.figure = self.canvas = None
            self.text = QPlainTextEdit()
            self.text.setReadOnly(True)
            self.text.setLineWrapMode(QPlainTextEdit.NoWrap)
            f = fixed_font()
            self.text.setFont(f)
            tw = QWidget()
            tl = QVBoxLayout(tw)
            tl.setContentsMargins(0, 0, 0, 0)
            tl.addWidget(self.text)
            row = QHBoxLayout()
            cp = QPushButton("Copy")
            cp.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.text.toPlainText()))
            sv = QPushButton("Save...")
            sv.clicked.connect(self.save_text)
            row.addStretch(1)
            row.addWidget(cp)
            row.addWidget(sv)
            tl.addLayout(row)
            self.stack.addWidget(tw)
        lay.addWidget(self.stack, 1)
        self.status = QLabel("")
        self.status.setStyleSheet("color: #a00; padding: 2px 4px;")
        self.status.setWordWrap(True)
        self.status.hide()
        lay.addWidget(self.status)
        self.setWidget(body)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(150)
        self._timer.timeout.connect(self.compute)
        doc.changed.connect(self._lens_changed)
        doc.opened.connect(self.request_update)
        self.request_update()

    # -- configurations -------------------------------------------------------------
    def _fill_configs(self, value=None):
        mc = getattr(self.doc.system, "multiconfig", None)
        value = self.config.currentData() if value is None else value
        self.config.blockSignals(True)
        self.config.clear()
        self.config.addItem("Current", 0)
        if mc is not None:
            for k in mc.configs:
                self.config.addItem(mc.name(k), k)
        i = self.config.findData(value)
        self.config.setCurrentIndex(i if i >= 0 else 0)
        self.config.blockSignals(False)
        # (the multi-configuration layout chooses its configurations in its own settings)
        many = mc is not None and mc.n_configs > 1 and self.spec.key != "mc_layout"
        self.config.setVisible(many)
        self.config_label.setVisible(many)

    def config_number(self):
        """The configuration this window shows (0: the current one)."""
        return self.config.currentData() or 0

    def set_config(self, k):
        i = self.config.findData(int(k))
        if i >= 0:
            self.config.setCurrentIndex(i)

    def _system_to_analyse(self):
        k = self.config_number()
        s = self.doc.system
        mc = getattr(s, "multiconfig", None)
        if k and mc is not None and k <= mc.n_configs and k != mc.current:
            return s.config_copy(k)
        return s.copy()

    def _title(self):
        mc = getattr(self.doc.system, "multiconfig", None)
        if mc is None or mc.n_configs < 2 or not self.config_label.isVisibleTo(self):
            return self.spec.title
        k = self.config_number() or mc.current
        return f"{self.spec.title} [{mc.name(k)}]" if k <= mc.n_configs else self.spec.title

    # -- scheduling ---------------------------------------------------------------
    def _lens_changed(self):
        self._fill_configs()
        if self.auto.isChecked():
            self.request_update()

    def request_update(self):
        if workers.SYNC:
            self.compute()
        else:
            self._timer.start()

    def compute(self):
        if self._busy:
            self._pending = True
            return
        missing = self.doc.system.missing_materials_message()
        if missing:  # cannot trace: say why instead of computing (and failing) or showing old results
            self._request += 1
            self.error = f"Cannot trace this lens. {missing} {MISSING_HINT}"
            self._show_error(self.error)
            self.updates += 1
            return
        self._busy = True
        self._request += 1
        self.setWindowTitle(f"{self._title()}  (computing...)")
        opts = self.settings.values()
        system = self._system_to_analyse()
        spec = self.spec
        workers.submit(lambda _p: spec.compute(system, **opts), self._done, self._failed,
                       tag=(self._request, opts, system))

    def _finish(self):
        self._busy = False
        if self._pending:
            self._pending = False
            self.request_update()

    def _done(self, tag, result):
        try:
            if not self._pending:
                _, opts, system = tag
                self.result, self.error = result, None
                self.status.hide()
                self._show(result, opts, system)
                self.setWindowTitle(self._title())
                self.updates += 1
        except RuntimeError:  # window already deleted
            return
        except Exception as e:  # noqa: BLE001 - plotting problem, shown in the window
            self._show_error(f"Plot failed: {type(e).__name__}: {e}")
        self._finish()

    def _failed(self, tag, msg):
        try:
            self.error = msg
            self._show_error(msg)
            self.updates += 1
        except RuntimeError:
            return
        self._finish()

    def _show_error(self, msg):
        # never leave the previous lens's plot or report on screen under an error
        self.result = None
        if self.text is not None:
            self.text.setPlainText("")
        else:
            self.figure.clear()
            self.canvas.draw_idle()
        self.status.setText(msg)
        self.status.show()
        self.setWindowTitle(f"{self._title()}  (error)")

    def _show(self, result, opts, system):
        if self.text is not None:
            self.text.setPlainText(result if isinstance(result, str) else str(result))
            return
        self.figure.clear()
        self.spec.plot(self.figure, result, opts, system)
        self.canvas.draw_idle()

    # -- misc -------------------------------------------------------------------
    def save_text(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save text", f"{self.spec.key}.txt", "Text (*.txt)")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.text.toPlainText())

    def state(self):
        return {"key": self.spec.key, "settings": {**self.settings.values(), "config": self.config_number()}}

    def closeEvent(self, ev):
        try:
            self.doc.changed.disconnect(self._lens_changed)
            self.doc.opened.disconnect(self.request_update)
            self.doc.changed.disconnect(self.settings.sync_choices)
        except (RuntimeError, TypeError):
            pass
        self.closed.emit(self)
        super().closeEvent(ev)
