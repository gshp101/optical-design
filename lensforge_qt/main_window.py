"""The main window: Lens Data Editor in the centre, everything else in docks."""

from __future__ import annotations

import os

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (QDockWidget, QFileDialog, QLabel, QMainWindow, QMessageBox, QUndoView)

import lensforge as lf
from lensforge import optimize as opt

from . import edits as E
from .analyses import GROUPS, REGISTRY
from .analysis_window import AnalysisWindow
from .document import LensDocument, new_system
from .lde import LensDataEditor
from .mfe import MeritFunctionEditor
from .opt_dialogs import OptimizationDialog, ToleranceDialog
from .script_console import ScriptConsole
from .system_dialog import SystemExplorer

HERE = os.path.dirname(os.path.abspath(__file__))
EXAMPLES = os.path.join(os.path.dirname(HERE), "examples")
FILE_FILTER = "Lens files (*.json *.zmx);;lensforge JSON (*.json);;Zemax ZMX (*.zmx);;All files (*)"


def _sample_list():
    out = [("Singlet", lf.samples.singlet), ("Cemented Achromat", lf.samples.achromat),
           ("Parabolic Mirror", lf.samples.parabolic_mirror), ("Classical Cassegrain", lf.samples.cassegrain)]
    for name, rel in (("Cooke Triplet (optimised)", "output/cooke_triplet.lens.json"),
                      ("Scripted Singlet", "best_singlet.lens.json"),
                      ("Diffraction Grating Demo", "grating_demo.lens.json")):
        p = os.path.join(EXAMPLES, rel)
        if os.path.exists(p):
            out.append((name, lambda p=p: lf.load(p)))
    return out


class MainWindow(QMainWindow):
    def __init__(self, path=None, settings: QSettings = None):
        super().__init__()
        self.settings = settings or QSettings("lensforge", "lensforge-qt")
        self.doc = LensDocument()
        self.analysis_windows = []
        self.dialogs = {}
        self.setDockNestingEnabled(True)
        self.setDockOptions(QMainWindow.AnimatedDocks | QMainWindow.AllowTabbedDocks | QMainWindow.AllowNestedDocks)
        self.resize(1400, 880)

        self.lde = LensDataEditor(self.doc)
        self.setCentralWidget(self.lde)
        self.mfe = MeritFunctionEditor(self.doc)
        self.mfe_dock = self._dock("Merit Function Editor", self.mfe, Qt.BottomDockWidgetArea, "mfe")
        self.console = ScriptConsole(self.doc)
        self.console_dock = self._dock("Python Shell", self.console, Qt.BottomDockWidgetArea, "script")
        self.tabifyDockWidget(self.mfe_dock, self.console_dock)
        self.undo_view = QUndoView(self.doc.undo_stack)
        self.undo_view.setEmptyLabel("<original lens>")
        self.undo_dock = self._dock("Undo History", self.undo_view, Qt.LeftDockWidgetArea, "undo")
        self.mfe_dock.hide()
        self.console_dock.hide()
        self.undo_dock.hide()

        self._make_actions()
        self._make_menus()
        self._make_toolbar()
        self._make_status()

        self.doc.changed.connect(self._update_status)
        self.doc.titleChanged.connect(self._update_title)
        self.doc.error.connect(lambda m: self.statusBar().showMessage(m, 8000))
        self.lde.statusMessage.connect(lambda m: self.statusBar().showMessage(m, 5000))
        self.mfe.model.evaluated.connect(self._show_merit)

        if path:
            self.open_file(path)
        self._update_title()
        self._update_status()

    # ------------------------------------------------------------------ helpers
    def _dock(self, title, widget, area, name):
        d = QDockWidget(title, self)
        d.setObjectName(f"dock_{name}")
        d.setWidget(widget)
        self.addDockWidget(area, d)
        return d

    def _action(self, text, slot, shortcut=None, tip=None, checkable=False):
        a = QAction(text, self)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
        if tip:
            a.setStatusTip(tip)
        a.setCheckable(checkable)
        a.triggered.connect(slot)
        return a

    # ------------------------------------------------------------------ actions / menus
    def _make_actions(self):
        A = self._action
        self.a_new = A("&New", self.new_file, QKeySequence.New)
        self.a_open = A("&Open...", self.open_dialog, QKeySequence.Open, "Open a lensforge JSON or Zemax .zmx file")
        self.a_save = A("&Save", self.save, QKeySequence.Save)
        self.a_save_as = A("Save &As...", self.save_as, QKeySequence.SaveAs)
        self.a_agf = A("Load Glass Catalog (AGF)...", self.load_agf)
        self.a_export = A("Export Prescription...", self.export_prescription)
        self.a_quit = A("E&xit", self.close, QKeySequence.Quit)
        self.a_undo = self.doc.undo_stack.createUndoAction(self, "&Undo")
        self.a_undo.setShortcut(QKeySequence.Undo)
        self.a_redo = self.doc.undo_stack.createRedoAction(self, "&Redo")
        self.a_redo.setShortcut(QKeySequence.Redo)
        self.a_sys = A("System &Explorer...", lambda: self.system_explorer(0), "F2")
        self.a_fields = A("&Fields...", lambda: self.system_explorer(1), "F3")
        self.a_waves = A("&Wavelengths...", lambda: self.system_explorer(2), "F4")
        self.a_fix_sd = A("Fix Semi-Diameters at Current Values", self.fix_semi_diameters)
        self.a_auto_sd = A("Make All Semi-Diameters Automatic", self.auto_semi_diameters)
        self.a_focus = A("&Quick Focus (paraxial)", self.quick_focus, "Ctrl+Shift+F")
        self.a_mfe = A("&Merit Function Editor", self.show_mfe, "F6")
        self.a_opt = A("&Optimization...", self.optimization, "Ctrl+U")
        self.a_tol = A("&Tolerancing...", self.tolerancing, "Ctrl+Shift+T")
        self.a_vary_curv = A("Make All Curvatures Variable", lambda: self.doc.modify(
            "Vary all curvatures", lambda s: opt.vary_curvatures(s)))
        self.a_vary_thick = A("Make All Air Spaces Variable", lambda: self.doc.modify(
            "Vary air spaces", lambda s: opt.vary_thicknesses(s, air_only=True)))
        self.a_clear_vars = A("Remove All Variables", lambda: self.doc.modify(
            "Remove all variables", lambda s: opt.clear_variables(s)))
        self.a_clear_solves = A("Remove All Solves", lambda: self.doc.modify(
            "Remove all solves", lambda s: setattr(s, "solves", [])))
        self.a_console = A("&Python Shell", self.show_console, "F8")
        self.a_rays = A("&Input Rays...", self.input_rays, "F5")
        self.a_toolbar = A("Toolbar", lambda on: self.toolbar.setVisible(on), checkable=True)
        self.a_undo_view = A("Undo History", lambda: (self.undo_dock.show(), self.undo_dock.raise_()))
        self.a_close_analyses = A("Close All Analysis Windows", self.close_analyses)
        self.a_tab_analyses = A("Tab All Analysis Windows", self.tab_analyses)
        self.a_about = A("&About", self.about)
        self.a_keys = A("Keyboard Shortcuts", self.shortcuts_help)

    def _make_menus(self):
        mb = self.menuBar()
        mb.setNativeMenuBar(False)  # menus inside the window on every platform (also macOS)

        m = mb.addMenu("&File")
        for a in (self.a_new, self.a_open):
            m.addAction(a)
        self.recent_menu = m.addMenu("Open &Recent")
        self.recent_menu.aboutToShow.connect(self._fill_recent)
        self._fill_recent()
        for a in (self.a_save, self.a_save_as):
            m.addAction(a)
        m.addSeparator()
        for a in (self.a_sys, self.a_fields, self.a_waves, self.a_rays):
            m.addAction(a)
        m.addSeparator()
        sm = m.addMenu("Sample Lenses")
        for name, fn in _sample_list():
            sm.addAction(name).triggered.connect(lambda _=False, n=name, f=fn: self.load_sample(n, f))
        m.addAction(self.a_agf)
        m.addAction(self.a_export)
        m.addSeparator()
        m.addAction(self.a_quit)

        m = mb.addMenu("&Edit")
        m.addAction(self.a_undo)
        m.addAction(self.a_redo)
        m.addAction(self.a_undo_view)
        m.addSeparator()
        for a in (self.lde.act_insert, self.lde.act_insert_after, self.lde.act_delete, self.lde.act_variable,
                  self.lde.act_material, self.lde.act_props):
            m.addAction(a)
        m.addSeparator()
        for a in (self.a_focus, self.a_fix_sd, self.a_auto_sd):
            m.addAction(a)

        m = mb.addMenu("&Analysis")
        for g in GROUPS:
            gm = m.addMenu(g.replace("&", "&&"))
            for spec in REGISTRY.values():
                if spec.group == g:
                    a = gm.addAction(spec.title.replace("&", "&&"))
                    if spec.shortcut:
                        a.setShortcut(QKeySequence(spec.shortcut))
                        self.addAction(a)
                    a.triggered.connect(lambda _=False, k=spec.key: self.open_analysis(k))
        m.addSeparator()
        m.addAction(self.a_tab_analyses)
        m.addAction(self.a_close_analyses)

        m = mb.addMenu("&Tools")
        for a in (self.a_opt, self.a_tol, self.a_console):
            m.addAction(a)
        m.addSeparator()
        m.addAction(self.a_mfe)
        vm = m.addMenu("Variables and Solves")
        for a in (self.a_vary_curv, self.a_vary_thick, self.a_clear_vars, self.a_clear_solves):
            vm.addAction(a)

        m = mb.addMenu("&View")
        m.addAction(self.a_toolbar)
        m.addAction(self.a_undo_view)

        m = mb.addMenu("&Help")
        m.addAction(self.a_keys)
        m.addAction(self.a_about)

    def _make_toolbar(self):
        tb = self.toolbar = self.addToolBar("Main")
        tb.setObjectName("toolbar_main")
        tb.setVisible(False)  # everything is in the menus; View > Toolbar shows quick buttons
        tb.visibilityChanged.connect(self.a_toolbar.setChecked)
        tb.setToolButtonStyle(Qt.ToolButtonTextOnly)
        for a in (self.a_new, self.a_open, self.a_save):
            tb.addAction(a)
        tb.addSeparator()
        tb.addAction(self.a_undo)
        tb.addAction(self.a_redo)
        tb.addSeparator()
        tb.addAction(self._action("Sys", lambda: self.system_explorer(0), tip="System Explorer"))
        for key, label in (("layout", "Lay"), ("spot", "Spt"), ("ray_fan", "Ray"), ("opd_fan", "Opd"),
                           ("mtf", "Mtf"), ("psf", "Psf"), ("field_curvature", "Fcd"), ("seidel", "Sei"),
                           ("prescription", "Pre")):
            tb.addAction(self._action(label, lambda _=False, k=key: self.open_analysis(k),
                                      tip=REGISTRY[key].title))
        tb.addSeparator()
        tb.addAction(self._action("Mfe", self.show_mfe, tip="Merit Function Editor"))
        tb.addAction(self._action("Opt", self.optimization, tip="Optimization"))
        tb.addAction(self._action("Tol", self.tolerancing, tip="Tolerancing"))
        tb.addAction(self._action("Py", self.show_console, tip="Python script console"))

    def _make_status(self):
        self.status_lens = QLabel()
        self.status_merit = QLabel()
        self.statusBar().addPermanentWidget(self.status_lens)
        self.statusBar().addPermanentWidget(self.status_merit)

    # ------------------------------------------------------------------ status / title
    def _update_title(self):
        self.setWindowTitle(f"{self.doc.display_name}[*] - lensforge")
        self.setWindowModified(self.doc.modified)

    def _update_status(self):
        s = self.doc.system
        try:
            p = s.paraxial()
            txt = (f"EFL {p.efl:.6g}   WFNO {p.working_fnum:.4g}   ENPD {p.epd:.5g}   "
                   f"TOTR {sum(x.thickness for x in s.surfaces[1:-1]):.6g}   {s.units}")
        except Exception:  # noqa: BLE001 - incomplete lens
            txt = "first-order data unavailable"
        self.status_lens.setText(txt)
        self._update_title()

    def _show_merit(self, ev):
        self.status_merit.setText("" if ev is None else f"   MF {ev.value:.6g}")

    # ------------------------------------------------------------------ files
    def maybe_save(self) -> bool:
        if not self.doc.modified:
            return True
        r = QMessageBox.question(self, "lensforge", f"Save changes to {self.doc.display_name}?",
                                 QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        if r == QMessageBox.Save:
            return self.save()
        return r == QMessageBox.Discard

    def new_file(self):
        if self.maybe_save():
            self.doc.reset(new_system())

    def load_sample(self, name, fn):
        if self.maybe_save():
            s = fn()
            if not s.name:
                s.name = name
            self.doc.reset(s)
            if not self.analysis_windows:
                self.open_analysis("layout")

    def open_dialog(self):
        if not self.maybe_save():
            return
        start = os.path.dirname(self.doc.path) if self.doc.path else self.settings.value("last_dir", EXAMPLES)
        path, _ = QFileDialog.getOpenFileName(self, "Open lens", start, FILE_FILTER)
        if path:
            self.open_file(path)

    def open_file(self, path) -> bool:
        try:
            self.doc.open(path)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Open", f"Could not open {path}:\n{type(e).__name__}: {e}")
            return False
        self._add_recent(path)
        if self.doc.system.notes.startswith("ZMX import ignored"):
            self.statusBar().showMessage(self.doc.system.notes, 10000)
        return True

    def save(self) -> bool:
        if not self.doc.path:
            return self.save_as()
        try:
            self.doc.save()
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Save", f"Could not save:\n{e}")
            return False
        self.statusBar().showMessage(f"Saved {self.doc.path}", 4000)
        return True

    def save_as(self) -> bool:
        start = self.doc.path or os.path.join(self.settings.value("last_dir", EXAMPLES),
                                              f"{self.doc.display_name}.lens.json")
        path, _ = QFileDialog.getSaveFileName(self, "Save lens", start, "lensforge JSON (*.json)")
        if not path:
            return False
        if not path.lower().endswith(".json"):
            path += ".lens.json"
        self.doc.path = path
        ok = self.save()
        if ok:
            self._add_recent(path)
        return ok

    def _add_recent(self, path):
        path = os.path.abspath(path)
        self.settings.setValue("last_dir", os.path.dirname(path))
        rec = [p for p in self._recent() if p != path]
        self.settings.setValue("recent", [path] + rec[:9])

    def _recent(self):
        v = self.settings.value("recent", []) or []
        return [v] if isinstance(v, str) else list(v)

    def _fill_recent(self):
        self.recent_menu.clear()
        for p in self._recent():
            self.recent_menu.addAction(p).triggered.connect(
                lambda _=False, p=p: self.maybe_save() and self.open_file(p))
        if self.recent_menu.isEmpty():
            self.recent_menu.addAction("(none)").setEnabled(False)

    def load_agf(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load AGF glass catalog", "", "AGF catalogs (*.agf *.AGF)")
        if path:
            try:
                lf.shared_library().load_agf(path)
            except Exception as e:  # noqa: BLE001
                QMessageBox.critical(self, "Glass catalog", f"Could not load {path}:\n{e}")
                return
            self.statusBar().showMessage(f"Loaded glass catalog {os.path.basename(path)}", 5000)

    def export_prescription(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export prescription", f"{self.doc.display_name}.txt",
                                              "Text (*.txt)")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(REGISTRY["prescription"].compute(self.doc.system))

    # ------------------------------------------------------------------ system
    def system_explorer(self, tab=0):
        SystemExplorer(self.doc, self, tab).exec()

    def input_rays(self):
        from .rays_dialog import InputRaysDialog
        InputRaysDialog(self.doc, self).exec()

    def quick_focus(self):
        self.doc.modify("Quick focus", lambda s: lf.samples.focus_paraxial(s))

    def fix_semi_diameters(self):
        def fn(s):
            _, vals = E.fill_auto_semi_diameters(s)
            for i, v in vals.items():
                s.surfaces[i].semi_diameter = v
        self.doc.modify("Fix semi-diameters", fn)

    def auto_semi_diameters(self):
        def fn(s):
            for x in s.surfaces:
                x.semi_diameter = None
        self.doc.modify("Automatic semi-diameters", fn)

    # ------------------------------------------------------------------ analyses
    def open_analysis(self, key, settings=None) -> AnalysisWindow:
        w = AnalysisWindow(key, self.doc, settings, self, on_rays=self.input_rays)
        w.closed.connect(self._analysis_closed)
        others = [x for x in self.analysis_windows if not x.isFloating()]
        self.addDockWidget(Qt.RightDockWidgetArea, w)
        if others:
            self.tabifyDockWidget(others[-1], w)
        else:
            self.resizeDocks([w], [int(self.width() * 0.48)], Qt.Horizontal)
        w.show()
        w.raise_()
        self.analysis_windows.append(w)
        return w

    def _analysis_closed(self, w):
        if w in self.analysis_windows:
            self.analysis_windows.remove(w)

    def close_analyses(self):
        for w in list(self.analysis_windows):
            w.close()

    def tab_analyses(self):
        ws = self.analysis_windows
        for w in ws:
            w.setFloating(False)
        for a, b in zip(ws, ws[1:]):
            self.tabifyDockWidget(a, b)

    # ------------------------------------------------------------------ optimisation
    def show_mfe(self):
        self.mfe_dock.show()
        self.mfe_dock.raise_()

    def show_console(self):
        self.console_dock.show()
        self.console_dock.raise_()

    def _dialog(self, name, cls):
        d = self.dialogs.get(name)
        if d is None:
            d = cls(self.doc, self)
            self.dialogs[name] = d
        d.show()
        d.raise_()
        d.activateWindow()
        return d

    def optimization(self):
        return self._dialog("opt", OptimizationDialog)

    def tolerancing(self):
        return self._dialog("tol", ToleranceDialog)

    # ------------------------------------------------------------------ help
    def about(self):
        QMessageBox.about(self, "About lensforge", f"<b>lensforge {lf.__version__}</b><br>Sequential optical "
                          "design: lens data editor, analyses, optimisation and tolerancing.<br><br>Qt front end "
                          "over the lensforge Python API (PySide6, matplotlib).")

    def shortcuts_help(self):
        text = "\n".join([
            "Lens Data Editor",
            "  Insert            insert surface before the current row",
            "  Ctrl+Insert       insert surface after",
            "  Shift+Delete      delete surface",
            "  Ctrl+Shift+V      toggle variable on the current cell",
            "  Ctrl+Shift+P      surface properties (aperture, stop, XY terms)",
            "  right-click       variables, solves, surface type, stop",
            "",
            "  Ctrl+G            choose material (also the ... button in a Material cell)",
            "",
            "File:     F2 System Explorer, F3 fields, F4 wavelengths, F5 input rays",
            "Edit:     Ctrl+Shift+F quick focus",
            "Analyses: Ctrl+L layout, Ctrl+S spot, Ctrl+R ray fan, Ctrl+M MTF, Ctrl+P PSF, Ctrl+W wavefront,",
            "          Ctrl+F field curvature / distortion",
            "Tools:    Ctrl+U optimization, Ctrl+Shift+T tolerancing, F8 Python shell (Ctrl+Enter runs),",
            "          F6 merit function editor",
            "Edit:     Ctrl+Z undo, Ctrl+Y / Ctrl+Shift+Z redo"])
        d = QMessageBox(self)
        d.setWindowTitle("Keyboard shortcuts")
        d.setText("<pre>" + text + "</pre>")
        d.exec()

    # ------------------------------------------------------------------ session
    def closeEvent(self, ev):
        if not self.maybe_save():
            ev.ignore()
            return
        for d in self.dialogs.values():
            d.close()
        ev.accept()
