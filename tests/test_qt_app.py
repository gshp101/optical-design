"""Tests of the Qt front end (offscreen; needs PySide6, pytest-qt and matplotlib)."""

import math
import os
import threading

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")
pytest.importorskip("matplotlib")

import matplotlib  # noqa: E402

matplotlib.use("QtAgg")

from PySide6.QtCore import QSettings, Qt  # noqa: E402
from PySide6.QtWidgets import QDialogButtonBox  # noqa: E402

import lensforge as lf  # noqa: E402
from lensforge import optimize as opt  # noqa: E402
from lensforge_qt import edits as E  # noqa: E402
from lensforge_qt import workers  # noqa: E402
from lensforge_qt.analyses import REGISTRY  # noqa: E402
from lensforge_qt.document import LensDocument  # noqa: E402

HERE = os.path.dirname(__file__)
TRIPLET = os.path.join(HERE, "..", "examples", "output", "cooke_triplet.lens.json")


@pytest.fixture(autouse=True)
def sync_workers(monkeypatch):
    monkeypatch.setattr(workers, "SYNC", True)


@pytest.fixture
def win(qtbot, tmp_path):
    from lensforge_qt.main_window import MainWindow
    w = MainWindow(settings=QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat))
    w.doc.reset(lf.samples.achromat())
    yield w
    w.doc.undo_stack.setClean()  # no "save changes?" prompt on close
    w.close()
    w.deleteLater()


def lde_index(w, row, key):
    m = w.lde.model
    for c in range(m.columnCount()):
        if m.key(row, c) == key:
            return m.index(row, c)
    raise KeyError(key)


# ---------------------------------------------------------------------------
# Lens Data Editor
# ---------------------------------------------------------------------------

def test_edit_radius_undo_redo(win):
    m = win.lde.model
    idx = lde_index(win, 1, "radius")
    assert m.setData(idx, "70", Qt.EditRole)
    assert win.doc.system.surfaces[1].radius == pytest.approx(70)
    assert win.doc.modified
    assert m.data(idx) == "70"
    win.doc.undo_stack.undo()
    assert win.doc.system.surfaces[1].radius == pytest.approx(62.75)
    win.doc.undo_stack.redo()
    assert win.doc.system.surfaces[1].radius == pytest.approx(70)
    # infinity and thickness
    assert m.setData(idx, "inf", Qt.EditRole)
    assert math.isinf(win.doc.system.surfaces[1].radius)
    assert m.data(idx) == "Infinity"
    assert m.setData(lde_index(win, 2, "thickness"), "3.5", Qt.EditRole)
    assert win.doc.system.surfaces[2].thickness == 3.5


def test_invalid_material_is_rejected(win, qtbot):
    m = win.lde.model
    before = win.doc.system.surfaces[1].material
    with qtbot.waitSignal(win.doc.error):
        assert not m.setData(lde_index(win, 1, "material"), "NOT-A-GLASS", Qt.EditRole)
    assert win.doc.system.surfaces[1].material == before
    assert m.setData(lde_index(win, 1, "material"), "n-bk7", Qt.EditRole)
    assert win.doc.system.material(1).name.upper() == "N-BK7"
    assert m.setData(lde_index(win, 1, "material"), "1.6,40", Qt.EditRole)
    assert win.doc.system.material(1).nd == pytest.approx(1.6, abs=1e-6)


def test_surface_type_and_parameter_columns(win):
    m = win.lde.model
    assert m.setData(m.index(1, 1), "EVENASPH", Qt.EditRole)
    assert win.doc.system.surfaces[1].kind == "EVENASPH"
    win.lde.view.setCurrentIndex(m.index(1, 3))
    assert m.headerData(9, Qt.Horizontal) == "4th Order Term"
    assert m.setData(lde_index(win, 1, "coefficients[1]"), "1e-6", Qt.EditRole)
    assert win.doc.system.surfaces[1].coefficients == [0.0, 1e-6]
    assert m.data(lde_index(win, 1, "coefficients[1]")) == "1e-06"
    # coordinate break: no radius / material cells
    assert m.setData(m.index(1, 1), "Coordinate Break", Qt.EditRole)
    assert not (m.flags(lde_index(win, 1, "radius")) & Qt.ItemIsEditable)
    assert m.setData(lde_index(win, 1, "tilt_x"), "2.5", Qt.EditRole)
    assert win.doc.system.surfaces[1].tilt_x == 2.5


def test_insert_delete_renumbers_variables_and_solves(win):
    doc = win.doc
    doc.modify("setup", lambda s: (opt.set_variable(s, 3, "curvature"),
                                   opt.set_solve(s, opt.MarginalRayHeight(3)),
                                   setattr(s, "merit_function", opt.MeritFunction())))
    doc.modify("op", lambda s: s.merit_function.add("REAY", 0.0, 1.0, surf=4, hy=1, py=1))
    win.lde.select(2, 3)
    win.lde.insert_before()
    s = doc.system
    assert s.num_surfaces == 6
    assert (s.variables[0].surface, s.solves[0].surface) == (4, 4)
    assert s.merit_function.rows[0].params["surf"] == 5
    win.lde.select(2, 3)
    win.lde.delete_surface()
    s = doc.system
    assert (s.variables[0].surface, s.solves[0].surface) == (3, 3)
    assert s.merit_function.rows[0].params["surf"] == 4
    # deleting a surface drops its variable and solve
    win.lde.select(3, 3)
    win.lde.delete_surface()
    assert not doc.system.variables and not doc.system.solves


def _select_rows(w, first, last, col=3):
    from PySide6.QtCore import QItemSelection, QItemSelectionModel
    m = w.lde.model
    w.lde.select(first, col)
    w.lde.view.selectionModel().select(QItemSelection(m.index(first, col), m.index(last, col)),
                                       QItemSelectionModel.ClearAndSelect)


def test_delete_range_from_selection_confirms(win, monkeypatch):
    from lensforge_qt.lde import LensDataEditor
    win.doc.reset(lf.load(TRIPLET))
    win.doc.modify("setup", lambda s: (opt.variables(s).clear(), opt.solves(s).clear(),
                                       opt.set_variable(s, 3, "curvature"), opt.set_variable(s, 5, "curvature")))
    radii = [x.radius for x in win.doc.system.surfaces]
    asked = []

    def refuse(self, first, last, lines):
        asked.append((first, last, lines))
        return False
    monkeypatch.setattr(LensDataEditor, "confirm_delete", refuse)
    _select_rows(win, 2, 4)
    assert win.lde.selected_rows() == (2, 4)
    assert win.lde.delete_surface() is False      # cancelled: nothing deleted
    assert win.doc.system.num_surfaces == 8
    first, last, lines = asked[0]
    assert (first, last) == (2, 4)
    assert lines[0].startswith("Surface 2:") and lines[2].startswith("Surface 4:")
    assert any("1 variable" in t for t in lines) and any("stop" in t for t in lines)

    monkeypatch.setattr(LensDataEditor, "confirm_delete", lambda *a: True)
    _select_rows(win, 2, 4)
    assert win.lde.delete_surface()
    s = win.doc.system
    assert [x.radius for x in s.surfaces] == radii[:2] + radii[5:]
    assert [v.surface for v in s.variables] == [2]
    assert win.doc.undo_stack.undoText() == "Delete surfaces 2-4"
    win.doc.undo_stack.undo()                     # one undo step restores everything
    assert [x.radius for x in win.doc.system.surfaces] == radii
    assert sorted(v.surface for v in win.doc.system.variables) == [3, 5]


def test_delete_range_selection_clamped_to_object_and_image(win, monkeypatch):
    from lensforge_qt.lde import LensDataEditor
    monkeypatch.setattr(LensDataEditor, "confirm_delete", lambda *a: True)
    win.doc.reset(lf.load(TRIPLET))
    _select_rows(win, 0, 4)                       # from the object row: only 1..4 go
    assert win.lde.delete_surface()
    assert win.doc.system.num_surfaces == 4
    _select_rows(win, 2, 3)                       # onto the image row: only surface 2 goes
    assert win.lde.delete_surface()
    assert win.doc.system.num_surfaces == 3


def test_delete_surfaces_dialog(win, qtbot, monkeypatch):
    from lensforge_qt import lde
    win.doc.reset(lf.load(TRIPLET))
    seen = {}

    def fake_exec(self):
        seen["range"] = self.surface_range()
        ok = self.bb.button(QDialogButtonBox.Ok)
        self.last.setValue(1)                     # reversed range: preview says so, Delete disabled
        seen["reversed_ok"] = ok.isEnabled()
        self.first.setValue(4)
        self.last.setValue(6)
        seen["preview"] = self.preview.toPlainText()
        seen["ok"] = ok.isEnabled()
        return lde.QDialog.Accepted
    monkeypatch.setattr(lde.DeleteSurfacesDialog, "exec", fake_exec)
    confirmed = []
    monkeypatch.setattr(lde.LensDataEditor, "confirm_delete", lambda self, f, l, lines: confirmed.append((f, l)) or True)
    _select_rows(win, 2, 3)
    assert win.lde.delete_surfaces_dialog()
    assert seen["range"] == (2, 3)
    assert not seen["reversed_ok"] and seen["ok"]
    assert "Surface 4:" in seen["preview"] and "Surface 6:" in seen["preview"]
    assert confirmed == [(4, 6)]
    assert win.doc.system.num_surfaces == 5
    # the spin boxes never offer the object or image surface
    d = lde.DeleteSurfacesDialog(win.doc.system, 0, 99)
    assert (d.first.minimum(), d.last.maximum()) == (1, win.doc.system.image_index - 1)
    assert d.surface_range() == (1, win.doc.system.image_index - 1)
    d.deleteLater()


def test_confirm_delete_prompt_defaults_to_cancel(win, monkeypatch):
    from lensforge_qt import lde
    shown = {}

    def fake_exec(box):
        shown["text"], shown["info"] = box.text(), box.informativeText()
        shown["default"] = box.defaultButton() is box.button(lde.QMessageBox.Cancel)
        return lde.QMessageBox.Cancel
    monkeypatch.setattr(lde.QMessageBox, "exec", fake_exec)
    win.doc.reset(lf.load(TRIPLET))
    assert win.lde.delete_range(2, 4) is False
    assert shown["text"] == "Delete surfaces 2 to 4 (3 surfaces)?"
    assert "Surface 3:" in shown["info"] and "Undo" in shown["info"]
    assert shown["default"]
    assert win.doc.system.num_surfaces == 8


def test_variable_and_solve_markers(win):
    m = win.lde.model
    win.lde.toggle_variable(1, "radius")
    assert E.variable_on(win.doc.system, 1, "radius") is not None
    assert m.data(lde_index(win, 1, "radius"), Qt.UserRole + 1) == "V"
    win.lde.toggle_variable(1, "radius")
    assert not win.doc.system.variables
    # solve marker; solved cells are read-only
    win.doc.modify("solve", lambda s: opt.set_solve(s, opt.FNumber(3, 5.0)))
    idx = lde_index(win, 3, "radius")
    assert m.data(idx, Qt.UserRole + 1) == "F"
    assert not (m.flags(idx) & Qt.ItemIsEditable)
    assert win.doc.system.paraxial().working_fnum == pytest.approx(5.0, rel=1e-6)
    # glass variable
    win.lde.toggle_variable(1, "material")
    assert {v.param for v in win.doc.system.variables} == {"glass.nd", "glass.vd"}
    assert m.data(lde_index(win, 1, "material"), Qt.UserRole + 1) == "V"


def test_semi_diameter_auto_and_fixed(win):
    m = win.lde.model
    idx = lde_index(win, 1, "semi_diameter")
    assert win.doc.system.surfaces[1].semi_diameter is None
    assert float(m.data(idx)) == pytest.approx(10.0, rel=0.05)  # automatic value displayed
    assert m.setData(idx, "12.5", Qt.EditRole)
    assert win.doc.system.surfaces[1].semi_diameter == 12.5
    assert m.data(idx, Qt.UserRole + 1) == "U"
    assert m.setData(idx, "", Qt.EditRole)
    assert win.doc.system.surfaces[1].semi_diameter is None


def test_surface_properties_dialog(win):
    from lensforge_qt.lde import SurfacePropertiesDialog
    d = SurfacePropertiesDialog(win.doc.system, 2)
    d.ap_kind.setCurrentIndex(1)
    d.ap_edits["r_max"].setText("8")
    d.stop.setChecked(True)
    assert win.doc.modify("props", d.apply)
    s = win.doc.system
    assert s.stop_index == 2 and s.surfaces[2].aperture.r_max == 8


# ---------------------------------------------------------------------------
# System Explorer
# ---------------------------------------------------------------------------

def test_system_explorer(win):
    from lensforge_qt.system_dialog import SystemExplorer
    d = SystemExplorer(win.doc, win)
    d.ap_type.setCurrentIndex(d.ap_type.findData("IMAGE_FNUM"))
    d.ap_value.setText("8")
    d._add_row(d.field_table, ["0", "3", "1", "0", "0", "0", "0"])
    d._apply_preset(d.preset.findText("d (0.5876)"))
    assert d.apply()
    s = win.doc.system
    assert s.aperture_type == "IMAGE_FNUM" and s.aperture_value == 8
    assert len(s.fields) == 4 and s.fields[-1].y == 3
    assert len(s.wavelengths) == 1 and s.primary_wavelength == 0
    win.doc.undo_stack.undo()
    assert win.doc.system.aperture_type == "EPD" and len(win.doc.system.wavelengths) == 3


# ---------------------------------------------------------------------------
# Merit Function Editor
# ---------------------------------------------------------------------------

def test_merit_function_editor(win):
    mfe = win.mfe
    win.doc.modify("wizard", lambda s: setattr(s, "merit_function", opt.default_merit(s, "spot")))
    mfe.add_row()
    m = mfe.model
    r = m.n_rows() - 1
    assert m.setData(m.index(r, 0), "efFL", Qt.EditRole)
    assert m.setData(m.index(r, 3), "100", Qt.EditRole)
    assert m.setData(m.index(r, 4), "1", Qt.EditRole)
    row = win.doc.system.merit_function.rows[r]
    assert (row.type, row.target, row.weight) == ("EFFL", 100.0, 1.0)
    ev = m.evaluation
    assert ev is not None
    assert ev.value == pytest.approx(win.doc.system.merit_function.value(win.doc.system))
    assert float(m.data(m.index(r, 5))) == pytest.approx(win.doc.system.paraxial().efl, rel=1e-6)
    # parameters
    assert m.setData(m.index(r, 0), "REAY", Qt.EditRole)
    assert m.setData(m.index(r, 1), "surf=4, hy=1, py=1", Qt.EditRole)
    assert win.doc.system.merit_function.rows[r].params == {"surf": 4, "hy": 1, "py": 1}
    assert not m.setData(m.index(r, 0), "XXXX", Qt.EditRole)  # unknown operand rejected
    mfe.view.selectRow(r)
    mfe.delete_rows()
    assert m.n_rows() == r


def test_parse_params():
    assert E.parse_params("surf=3, hy=1.0, reference=centroid, wavelengths=[0, 1]") == {
        "surf": 3, "hy": 1.0, "reference": "centroid", "wavelengths": [0, 1]}
    with pytest.raises(ValueError):
        E.parse_params("surf 3")


# ---------------------------------------------------------------------------
# Analyses
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("key", sorted(REGISTRY))
def test_every_analysis_window(win, key):
    win.doc.reset(lf.load(TRIPLET))
    w = win.open_analysis(key)
    assert w.updates == 1, w.error
    assert w.error is None, w.error
    if w.text is None:
        assert w.figure.axes
    else:
        assert w.text.toPlainText().strip()
    w.close()


def test_analysis_auto_update_and_settings(win):
    w = win.open_analysis("spot")
    n = w.updates
    rms0 = w.result[0][1]["rms_radius"]
    win.lde.model.setData(lde_index(win, 3, "thickness"), "60", Qt.EditRole)
    assert w.updates == n + 1
    assert w.result[0][1]["rms_radius"] != rms0
    w.auto.setChecked(False)
    win.doc.undo_stack.undo()
    assert w.updates == n + 1
    # field selector follows the lens fields
    combo = w.settings.widgets["field"][1]
    assert combo.count() == 1 + len(win.doc.system.fields)
    win.doc.modify("fields", lambda s: s.set_fields([0, 1, 2, 3]))
    assert combo.count() == 5
    combo.setCurrentIndex(4)
    assert len(w.result) == 1 and w.result[0][0] == 3


# ---------------------------------------------------------------------------
# Optimisation and tolerancing
# ---------------------------------------------------------------------------

def _singlet_problem(doc):
    def fn(s):
        opt.set_variable(s, 1, "curvature")
        opt.set_variable(s, 2, "curvature")
        opt.set_solve(s, opt.MarginalRayHeight(2))
        s.merit_function = opt.default_merit(s, "spot")
        s.merit_function.add("EFFL", 100.0, -1)
    doc.reset(lf.samples.singlet())
    doc.modify("problem", fn)


def test_optimization_dialog(win):
    _singlet_problem(win.doc)
    s0 = win.doc.system
    m0 = s0.merit_function.value(s0)
    d = win.optimization()
    d.cycles.setValue(10)
    d.start()
    s = win.doc.system
    m1 = s.merit_function.value(s)
    assert m1 < 0.95 * m0  # best-form bending of the singlet
    assert s.paraxial().efl == pytest.approx(100.0, rel=1e-4)
    win.doc.undo_stack.undo()
    assert win.doc.system.merit_function.value(win.doc.system) == pytest.approx(m0)
    d.close()


def test_lone_merit_row_type_change_sets_weight_one(win):
    from lensforge_qt.mfe import MeritModel
    win.doc.reset(lf.samples.singlet())
    m = MeritModel(win.doc)
    win.doc.modify("mf", lambda s: setattr(s, "merit_function", opt.MeritFunction()))
    win.doc.modify("row", lambda s: s.merit_function.add("BLNK", weight=0))
    m.setData(m.index(0, 0), "EFFL")
    assert win.doc.system.merit_function.rows[0].weight == 1.0


def test_stop_keeps_best_design():
    from lensforge_qt.opt_dialogs import run_optimization
    doc = LensDocument()
    _singlet_problem(doc)
    s = doc.system.copy()
    m0 = s.merit_function.value(s)
    stop = threading.Event()
    calls = []

    def report(p):
        calls.append(p)
        if len(calls) >= 2:
            stop.set()
    best, msg, hist = run_optimization(s, s.merit_function.copy(), "hammer", stop, report, trials=1000,
                                       report_interval=0.0)
    assert msg.startswith("Stopped")
    assert best.merit_function.value(best) <= m0


def test_tolerance_dialog(win):
    from lensforge_qt.opt_dialogs import ToleranceDialog
    win.doc.reset(lf.samples.singlet())
    d = ToleranceDialog(win.doc, win)
    while d.table.rowCount() > 3:
        d.table.removeRow(d.table.rowCount() - 1)
    d.comp.setCurrentIndex(1)  # paraxial focus (fast)
    d.run("sensitivity")
    out = d.output.toPlainText()
    assert "Estimated performance" in out
    d.mc_trials.setValue(5)
    d.run("monte_carlo")
    assert d.mc is not None and d.mc.values.size == 5
    assert "Monte Carlo" in d.output.toPlainText()


# ---------------------------------------------------------------------------
# Files and scripting
# ---------------------------------------------------------------------------

ZMX = """VERS 140000
UNIT MM X W X CM MR CPMM
NAME ZMX test
ENPD 20
FTYP 0 0 2 1 0 0 0
YFLN 0 5
WAVM 1 0.5876 1
PWAV 1
SURF 0
  DISZ INFINITY
SURF 1
  STOP
  CURV 0.02
  DISZ 5
  GLAS N-BK7 0 0 1.5168 64.17
SURF 2
  CURV -0.005
  DISZ 90
SURF 3
"""


def test_open_save_roundtrip(win, tmp_path):
    p = tmp_path / "a.zmx"
    p.write_text(ZMX)
    assert win.open_file(str(p))
    s = win.doc.system
    assert s.num_surfaces == 4 and s.surfaces[1].radius == pytest.approx(50)
    assert win.doc.path is None and win.doc.display_name == "a"
    out = tmp_path / "b.lens.json"
    win.doc.modify("v", lambda s: opt.set_variable(s, 1, "curvature"))
    win.doc.save(str(out))
    assert not win.doc.modified
    win.doc.reset(lf.samples.singlet())
    assert win.open_file(str(out))
    assert win.doc.system.surfaces[1].radius == pytest.approx(50)
    assert win.doc.system.variables[0].param == "curvature"


def test_script_console(win):
    c = win.console
    c.run("print(round(lens.paraxial().efl, 3))\nlens.surfaces[1].radius = 70")
    assert win.doc.system.surfaces[1].radius == pytest.approx(70)
    assert win.doc.undo_stack.undoText() == "Script"
    out = c.run("lens.surfaces[1].radius = 80\nraise ValueError('boom')")
    assert "boom" in out and win.doc.system.surfaces[1].radius == pytest.approx(70)
    n = win.doc.undo_stack.count()
    c.run("x = 1")  # no change: no undo step
    assert win.doc.undo_stack.count() == n


def test_samples_menu_and_title(win):
    from lensforge_qt.main_window import _sample_list
    for name, fn in _sample_list():
        win.load_sample(name, fn)
        assert win.doc.system.num_surfaces >= 3
    assert "lensforge" in win.windowTitle()


# ---------------------------------------------------------------------------
# Menus, input rays, material picker, gratings
# ---------------------------------------------------------------------------

def _plain(text):
    return text.replace("&&", "\0").replace("&", "").replace("\0", "&")


def _menu(win, title):
    for a in win.menuBar().actions():
        if _plain(a.text()) == title:
            return [_plain(x.text()) for x in a.menu().actions() if not x.isSeparator()]
    raise KeyError(title)


def test_menu_layout(win):
    titles = [_plain(a.text()) for a in win.menuBar().actions()]
    assert titles[:4] == ["File", "Edit", "Analysis", "Tools"]
    f = _menu(win, "File")
    for item in ("New", "Open...", "Open Recent", "Save", "Save As...", "System Explorer...", "Input Rays..."):
        assert item in f, item
    assert f.index("Open Recent") < f.index("Save")
    e = _menu(win, "Edit")
    assert e[:2] == ["Undo", "Redo"] or (e[0].startswith("Undo") and e[1].startswith("Redo"))
    t = _menu(win, "Tools")
    assert t[:3] == ["Optimization...", "Tolerancing...", "Python Shell"]
    assert set(_menu(win, "Analysis")) >= {"Layout", "Rays & Spots", "PSF & MTF"}
    assert not win.menuBar().isNativeMenuBar()


def test_input_rays_dialog(win, tmp_path):
    from lensforge_qt import rays as R
    from lensforge_qt.rays_dialog import InputRaysDialog
    lay = win.open_analysis("layout")
    spot = win.open_analysis("spot")
    n_paths = len(lay.result["rays"][0]["path"][0])
    d = InputRaysDialog(win.doc, win)
    d.layout_rays.setValue(11)
    d.rings.setValue(3)
    d.pattern.setCurrentIndex(d.pattern.findData("square"))
    d.add_ray({"hx": 0.0, "hy": 1.0, "px": 0.0, "py": 0.5, "wave": 0})
    assert d.apply()
    ir = R.get(win.doc.system)
    assert ir["layout_rays"] == 11 and ir["spot_pattern"] == "square" and len(ir["user_rays"]) == 1
    assert len(lay.result["rays"][0]["path"][0]) == 11 != n_paths
    assert len(lay.result["user_rays"]) == 1
    assert "square 3" in "".join(t.get_text() for t in spot.figure.texts)
    # saved with the lens, ignored by the core loader, undoable
    p = tmp_path / "r.lens.json"
    win.doc.save(str(p))
    assert lf.load(str(p)).num_surfaces == win.doc.system.num_surfaces
    win.doc.undo_stack.undo()
    assert R.get(win.doc.system)["layout_rays"] == 7
    win.open_file(str(p))
    assert R.get(win.doc.system)["layout_rays"] == 11
    rep = win.open_analysis("user_rays")
    assert "User ray 1" in rep.text.toPlainText()


def test_material_dialog(win):
    from lensforge_qt.material_dialog import MaterialDialog
    s = win.doc.system
    d = MaterialDialog(s, s.surfaces[1].material)
    assert d.tabs.currentIndex() == 0 and d.chosen_spec() == "N-BAF10"
    assert d.select_spec("N-SF6")
    d._accept()
    assert d.spec == "N-SF6"
    d = MaterialDialog(s, "1.6,40")
    assert d.tabs.currentIndex() == 1 and d.m_nd.value() == pytest.approx(1.6)
    d = MaterialDialog(s, None)
    assert d.chosen_spec() == ""
    d.o_mirror.setChecked(True)
    assert d.chosen_spec() == "MIRROR"
    # the LDE action applies the choice as one undo step
    from unittest import mock
    def fake_exec(dlg):
        dlg.spec = "N-BK7"
        return 1
    with mock.patch("lensforge_qt.material_dialog.MaterialDialog.exec", fake_exec):
        win.lde.choose_material(1)
    assert win.doc.system.material(1).name == "N-BK7"
    assert win.doc.undo_stack.undoText().startswith("Surface 1 material")


def test_grating_surface_in_editor(win):
    m = win.lde.model
    win.doc.reset(lf.samples.singlet())
    assert m.setData(m.index(2, 1), "DGRATING", Qt.EditRole)
    win.lde.view.setCurrentIndex(m.index(2, 3))
    assert m.headerData(8, Qt.Horizontal) == "Lines/um"
    assert m.setData(lde_index(win, 2, "lines_per_um"), "0.3", Qt.EditRole)
    g = win.doc.system.surfaces[2]
    assert g.kind == "DGRATING" and g.lines_per_um == 0.3 and g.diffraction_order == 1
    r = win.doc.system.trace(0, 0, 0, 0)
    assert r.directions[-1][0, 1] == pytest.approx(0.3 * win.doc.system.primary, abs=1e-9)
    win.lde.toggle_variable(2, "lines_per_um")
    assert win.doc.system.variables[0].param == "lines_per_um"
    w = win.open_analysis("layout")
    assert w.error is None


# ---------------------------------------------------------------------- customize toolbar
def _toolbar_ids(w):
    """Toolbar contents as menu paths ("|" for separators)."""
    back = {id(a): iid for iid, _, a in w.toolbar_items}
    return [back.get(id(a), "|") if not a.isSeparator() else "|" for a in w.toolbar.actions()]


def test_toolbar_defaults_and_every_menu_command_listed(win):
    from lensforge_qt.main_window import DEFAULT_TOOLBAR
    ids = [i for i, _, _ in win.toolbar_items]
    assert "File > Open" in ids and "Tools > Optimization" in ids and "Analysis > PSF & MTF > MTF" in ids
    assert "View > Customize Toolbar" in ids
    assert not any(i.startswith("File > Open Recent") for i in ids)  # dynamic entries are not offered
    assert _toolbar_ids(win) == DEFAULT_TOOLBAR
    assert not win.a_toolbar.isChecked()
    assert win.toolbar_lookup["Tools > Optimization"].iconText() == "Opt"


def test_toolbar_dialog_add_remove_reorder(win, qtbot):
    from lensforge_qt.toolbar_dialog import SEPARATOR, ToolbarDialog
    dlg = ToolbarDialog(win.toolbar_items, ["File > New", "File > Open"], ["File > Save"], win)
    qtbot.addWidget(dlg)
    assert dlg.ids() == ["File > New", "File > Open"]

    # add a command picked in the menu tree (after the current row), and a separator
    dlg.filter.setText("tolerancing")
    leaf = [it for it in _tree_leaves(dlg.tree) if not it.isHidden()]
    assert [it.data(0, Qt.UserRole) for it in leaf] == ["Tools > Tolerancing"]
    leaf[0].setSelected(True)
    dlg.add_selected()
    dlg.add_selected()  # already there: not added twice
    assert dlg.ids() == ["File > New", "File > Open", "Tools > Tolerancing"]
    dlg.list.setCurrentRow(0)
    dlg.insert_ids([SEPARATOR])
    assert dlg.ids() == ["File > New", SEPARATOR, "File > Open", "Tools > Tolerancing"]

    # move and remove
    dlg.list.clearSelection()
    dlg.list.item(3).setSelected(True)
    dlg.move(-1)
    assert dlg.ids() == ["File > New", SEPARATOR, "Tools > Tolerancing", "File > Open"]
    dlg.list.clearSelection()
    dlg.list.item(0).setSelected(True)
    dlg.list.item(1).setSelected(True)
    dlg.remove_selected()
    assert dlg.ids() == ["Tools > Tolerancing", "File > Open"]
    dlg.b_reset.click()
    assert dlg.ids() == ["File > Save"]
    dlg.set_ids(["No > Such > Command", "File > New"])  # stale entries are dropped
    assert dlg.ids() == ["File > New"]


def _tree_leaves(tree):
    out, stack = [], [tree.invisibleRootItem()]
    while stack:
        n = stack.pop()
        for i in range(n.childCount()):
            c = n.child(i)
            (out.append(c) if c.data(0, Qt.UserRole) else stack.append(c))
    return out


def test_customize_toolbar_applies_and_persists(win, qtbot, tmp_path, monkeypatch):
    from lensforge_qt import toolbar_dialog
    from lensforge_qt.main_window import MainWindow
    chosen = ["Analysis > Layout > 2D Layout", "|", "Tools > Python Shell", "File > Save As"]

    def fake_exec(dlg):
        dlg.set_ids(chosen)
        return 1
    monkeypatch.setattr(toolbar_dialog.ToolbarDialog, "exec", fake_exec)
    win.a_customize_tb.trigger()
    assert _toolbar_ids(win) == chosen
    assert win.a_toolbar.isChecked()

    # the toolbar button runs the same command as the menu item
    btn = win.toolbar.widgetForAction(win.toolbar_lookup["Analysis > Layout > 2D Layout"])
    n = len(win.analysis_windows)
    btn.click()
    assert len(win.analysis_windows) == n + 1

    # a new session (same settings file) gets the same toolbar, shown
    w2 = MainWindow(settings=QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat))
    try:
        assert _toolbar_ids(w2) == chosen
        assert w2.a_toolbar.isChecked()
        w2.show_toolbar(False)
        w2.set_toolbar([])
        assert w2.toolbar.actions() == []
    finally:
        w2.doc.undo_stack.setClean()
        w2.close()
        w2.deleteLater()
    w3 = MainWindow(settings=QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat))
    try:
        assert w3.toolbar.actions() == [] and not w3.a_toolbar.isChecked()
    finally:
        w3.doc.undo_stack.setClean()
        w3.close()
        w3.deleteLater()


def test_customize_toolbar_cancel_keeps_toolbar(win, monkeypatch):
    from lensforge_qt import toolbar_dialog
    from lensforge_qt.main_window import DEFAULT_TOOLBAR

    def fake_exec(dlg):
        dlg.set_ids([])
        return 0
    monkeypatch.setattr(toolbar_dialog.ToolbarDialog, "exec", fake_exec)
    win.customize_toolbar()
    assert _toolbar_ids(win) == DEFAULT_TOOLBAR


# ---------------------------------------------------------------------- help, icons, tooltips
# These keep the help complete: a new menu command fails here until it has help text in
# lensforge_qt/help_text.py and an icon in lensforge_qt/icons.py.
def test_every_menu_command_has_help(win):
    from lensforge_qt.help_text import lookup
    missing = [iid for iid, _, _ in win.toolbar_items if not (lookup(iid) and all(lookup(iid)))]
    assert missing == [], f"add help for these menu commands to lensforge_qt/help_text.py: {missing}"
    for iid, _, a in win.toolbar_items:
        summary = lookup(iid)[0]
        assert a.statusTip() == summary
        assert summary in a.toolTip() and a.whatsThis()


def test_no_help_or_icon_for_commands_that_no_longer_exist(win):
    from lensforge_qt import help_text as H, icons as I
    from lensforge_qt.analyses import REGISTRY
    ids = {iid for iid, _, _ in win.toolbar_items}
    assert set(H.HELP) - ids == set()
    assert set(I.ICONS) - ids == set()
    assert set(H.ANALYSIS_HELP) == set(REGISTRY) == set(I.ANALYSIS_ICONS)
    samples = {i[len(H.SAMPLE_PREFIX):] for i in ids if i.startswith(H.SAMPLE_PREFIX)}
    assert set(H.SAMPLE_HELP) >= samples and set(I.SAMPLE_ICONS) >= samples


def test_every_command_has_its_own_icon(win):
    from lensforge_qt import icons
    seen = {}
    for iid, _, a in win.toolbar_items:
        assert not a.icon().isNull(), f"add an icon for {iid} to lensforge_qt/icons.py"
        seen.setdefault(icons.svg(iid), set()).add(id(a))
    shared = [ids for ids in seen.values() if len(ids) > 1]
    assert shared == [], "two different commands share an icon"
    img = icons.render(icons.svg("Tools > Optimization"), 32)
    assert sum(img.pixelColor(x, y).alpha() > 0 for x in range(32) for y in range(32)) > 50  # it draws


def test_toolbar_buttons_show_icons_and_tooltips(win):
    win.show_toolbar(True)
    assert win.toolbar.toolButtonStyle() == Qt.ToolButtonIconOnly
    for a in win.toolbar.actions():
        if a.isSeparator():
            continue
        btn = win.toolbar.widgetForAction(a)
        assert not btn.icon().isNull()
        assert a.statusTip() and a.statusTip() in btn.toolTip()
    opt_tip = win.toolbar_lookup["Tools > Optimization"].toolTip()
    assert "Optimization" in opt_tip and "Ctrl+U" in opt_tip


def test_no_two_commands_share_a_shortcut(win):
    from PySide6.QtGui import QAction
    keys = {}
    for a in win.findChildren(QAction):
        if a.shortcutContext() in (Qt.WidgetShortcut, Qt.WidgetWithChildrenShortcut):
            continue  # editor-local keys (LDE and MFE both use Insert / Shift+Delete)
        for sc in a.shortcuts():
            keys.setdefault(sc.toString(), set()).add(id(a))
    clashes = {k: v for k, v in keys.items() if k and len(v) > 1}
    assert clashes == {}
    rows = win.shortcut_rows()
    assert ("Analysis", "Rays & Spots > Standard Spot Diagram", "Ctrl+D") in rows
    assert any(r[1] == "Insert Lens" for r in rows)


def test_toolbar_button_style_persists(win, tmp_path, monkeypatch):
    from lensforge_qt import toolbar_dialog
    from lensforge_qt.main_window import MainWindow

    def fake_exec(dlg):
        dlg.style.setCurrentIndex(dlg.style.findData("icons+text"))
        return 1
    monkeypatch.setattr(toolbar_dialog.ToolbarDialog, "exec", fake_exec)
    win.customize_toolbar()
    assert win.toolbar.toolButtonStyle() == Qt.ToolButtonTextUnderIcon
    w2 = MainWindow(settings=QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat))
    try:
        assert w2.toolbar.toolButtonStyle() == Qt.ToolButtonTextUnderIcon
    finally:
        w2.doc.undo_stack.setClean()
        w2.close()
        w2.deleteLater()


def test_help_browser(win):
    dlg = win.help_contents("File > Insert Lens")
    try:
        text = dlg.page.toPlainText()
        assert "Insert Lens" in text and "Scale factor" in text and "Ctrl+I" in text
        dlg.filter.setText("zernike")
        cur = dlg.tree.currentItem().data(0, Qt.UserRole)
        assert "Zernike" in cur
        dlg.filter.setText("")
        assert dlg.show_command("Tools > Python Shell")
        assert "Python" in dlg.page.toPlainText()
        menu = dlg._find(dlg.tree.invisibleRootItem(), ":menu:Tools")
        dlg.tree.setCurrentItem(menu)
        assert "Optimization" in dlg.page.toPlainText() and "Tolerancing" in dlg.page.toPlainText()
        assert win.help_contents() is dlg  # one help window
    finally:
        dlg.close()



# ---------------------------------------------------------------------- merit function editor help
def test_every_operand_is_in_the_merit_function_help():
    from lensforge_qt import mfe_help
    filed = [n for names in mfe_help.OPERAND_GROUPS.values() for n in names]
    assert len(filed) == len(set(filed)), "an operand is filed in two groups"
    missing = sorted(set(opt.OPERANDS) - set(filed))
    assert missing == [], f"add these operands to OPERAND_GROUPS in lensforge_qt/mfe_help.py: {missing}"
    assert set(filed) <= set(opt.OPERANDS)
    page = mfe_help.topic_text(mfe_help.ROOT + "/operands")
    assert all(n in page for n in opt.OPERANDS)
    assert mfe_help.operand_signature("REAY") == "surf=None, hx=0.0, hy=0.0, px=0.0, py=0.0, wave=None"
    assert mfe_help.operand_signature("SUMM") == "a, b"


def test_merit_function_help_pages(win):
    from lensforge_qt import mfe_help
    from PySide6.QtCore import QUrl
    win.show_mfe()
    win.mfe.act_help.trigger()  # the editor's Help button
    dlg = win.dialogs["help"]
    try:
        assert dlg.tree.currentItem().data(0, Qt.UserRole) == mfe_help.ROOT
        assert "Merit Function Editor" in dlg.page.toPlainText()
        dlg.page.anchorClicked.emit(QUrl("help:mfe/weights"))  # links between pages
        assert dlg.tree.currentItem().data(0, Qt.UserRole) == mfe_help.ROOT + "/weights"
        text = dlg.page.toPlainText()
        assert "Hard constraint" in text and "Only ratios matter" in text
        for key, title in mfe_help.TOPICS:
            assert dlg.show_command(key) and title.split(" (")[0] in dlg.page.toPlainText()
        dlg.filter.setText("lagrange")  # search finds text inside topic pages
        assert dlg.tree.currentItem().data(0, Qt.UserRole).startswith(mfe_help.TOPIC_PREFIX)
        dlg.filter.setText("")
        win.mfe.view.setFocus()
        assert win.help_contents(False) is dlg  # F1 / Help Contents from the editor
    finally:
        dlg.close()
    m = win.mfe.model
    from lensforge_qt.mfe import C_WEIGHT
    assert "hard constraint" in m.headerData(C_WEIGHT, Qt.Horizontal, Qt.ToolTipRole)


def test_spot_size_merit_example():
    """The help's worked example: the shipped file holds the merit function the help describes."""
    s = lf.load(os.path.join(os.path.dirname(__file__), "..", "examples", "spot_size_merit.lens.json"))
    mf = s.merit_function
    types = [r.type for r in mf.rows]
    assert types.count("RAYS") == len(s.fields) == 3
    effl = mf.rows[types.index("EFFL")]
    assert effl.target == 100 and effl.weight < 0
    assert {"MNCG", "MNEG", "MNCA"} <= set(types)
    assert len(opt.variables(s)) == 9
    ev = mf.evaluate(s)
    assert ev.error is None and 0.5 < ev.value < 1.5  # the unoptimised start
    from lensforge_qt.main_window import _sample_list
    assert "Spot Size Merit Example" in dict(_sample_list())


def test_misspelt_operand_parameter_is_reported():
    s = lf.samples.singlet()
    mf = opt.MeritFunction()
    mf.add("EFFL", 100, 1, focal=3)
    ev = mf.evaluate(s)
    assert ev.value == float("inf") and "focal" in ev.error


# ---------------------------------------------------------------------- insert lens
def test_insert_lens_dialog_scaled_and_reversed(win, tmp_path):
    from lensforge_qt.insert_lens_dialog import InsertLensDialog
    src = lf.samples.achromat()
    p = tmp_path / "doublet.lens.json"
    lf.save(src, str(p))
    win.doc.reset(lf.samples.singlet())
    s0 = win.doc.system
    opt.vary_curvatures(s0)  # references after the insertion point must move
    win.doc.reset(s0)
    n0, img_curv_vars = win.doc.system.num_surfaces, sorted(v.surface for v in opt.variables(win.doc.system))
    dlg = InsertLensDialog(win.doc, at=2, start_dir=str(tmp_path), parent=win)
    try:
        dlg.load(str(p))
        assert dlg.last.value() == 3 and dlg.buttons.button(QDialogButtonBox.Ok).isEnabled()
        dlg.scale.setValue(0.5)
        dlg.reverse.setChecked(True)
        assert "Focal length of the inserted group" in dlg.info.text()
        assert "N-SF" in dlg.preview.toPlainText() or "SF" in dlg.preview.toPlainText()
        dlg.accept()
    finally:
        dlg.close()
    s = win.doc.system
    assert s.num_surfaces == n0 + 3
    assert s.surfaces[2].radius == pytest.approx(-0.5 * src.surfaces[3].radius)
    assert s.surfaces[4].thickness == pytest.approx(0.5 * src.surfaces[3].thickness)
    assert sorted(v.surface for v in opt.variables(s)) == [i if i < 2 else i + 3 for i in img_curv_vars]
    win.doc.undo_stack.undo()  # one undo step removes the whole insertion
    assert win.doc.system.num_surfaces == n0


def test_insert_lens_dialog_copies_semi_diameters(win, tmp_path):
    from lensforge_qt.insert_lens_dialog import InsertLensDialog
    src = lf.samples.achromat()
    src.surfaces[1].semi_diameter = 9.0
    p = tmp_path / "doublet.lens.json"
    lf.save(src, str(p))
    win.doc.reset(lf.samples.singlet())
    dlg = InsertLensDialog(win.doc, at=1, parent=win)
    try:
        dlg.load(str(p))
        assert not dlg.copy_sd.isChecked() and not dlg.options()["copy_semi_diameters"]
        dlg.copy_sd.setChecked(True)
        dlg.scale.setValue(2.0)
        assert "18" in dlg.preview.toPlainText()  # preview shows the copied, scaled value
        dlg.accept()
    finally:
        dlg.close()
    s = win.doc.system
    assert s.surfaces[1].semi_diameter == pytest.approx(18.0)
    assert all(s.surfaces[i].semi_diameter is not None for i in (1, 2, 3))  # automatic ones copied as fixed


def test_insert_lens_menu_and_bad_file(win, tmp_path, monkeypatch):
    from lensforge_qt import insert_lens_dialog as M
    bad = tmp_path / "bad.json"
    bad.write_text("not a lens")
    monkeypatch.setattr(M.InsertLensDialog, "exec", lambda self: 0)
    dlg = win.insert_lens()
    assert dlg.at.value() >= 1
    dlg.load(str(bad))
    assert "Cannot read" in dlg.info.text()
    assert not dlg.buttons.button(QDialogButtonBox.Ok).isEnabled()
    assert "File > Insert Lens" in [i for i, _, _ in win.toolbar_items]


def test_app_icon(win):
    from lensforge_qt import icons
    assert not win.windowIcon().isNull()
    img = icons.render(icons.APP_ICON, 32)
    assert img.pixelColor(16, 12).alpha() == 255      # the glowing lens is drawn, not transparent


def test_inspect_lens_file_window(win, tmp_path, monkeypatch):
    from lensforge_qt import main_window as M
    src = lf.samples.achromat()
    src.name = "Inspected doublet"
    p = tmp_path / "doublet.lens.json"
    lf.save(src, str(p))
    win.doc.reset(lf.samples.singlet())
    before = win.doc.system.to_dict()
    assert "Inspect Lens File..." in _menu(win, "File")
    monkeypatch.setattr(M.QFileDialog, "getOpenFileName", lambda *a, **k: (str(p), ""))
    w = win.inspect_lens_dialog()
    try:
        assert w.isVisible() and not w.isModal() and w.windowModality() == Qt.NonModal
        assert w in win.inspect_windows
        report = w.text.toPlainText()
        assert report.startswith("SYSTEM REPORT: Inspected doublet") and "Seidel coefficients" in report
        assert w.save_btn.isEnabled() and "doublet.lens.json" in w.windowTitle()
        after = win.doc.system.to_dict()
        assert after == before and win.doc.undo_stack.count() == 0  # current lens untouched
        out = tmp_path / "report.txt"
        monkeypatch.setattr("lensforge_qt.inspect_window.QFileDialog.getSaveFileName",
                            lambda *a, **k: (str(out), ""))
        w.save_text()
        assert out.read_text(encoding="utf-8") == report
        w.open_btn.click()  # Open in Editor loads the file as the current lens
        assert win.doc.system.name == "Inspected doublet"
    finally:
        w.close()


def test_inspect_lens_file_bad_file_and_cancel(win, tmp_path, monkeypatch):
    from lensforge_qt import main_window as M
    bad = tmp_path / "bad.json"
    bad.write_text("not a lens")
    w = win.inspect_lens(str(bad))
    try:
        assert "Could not read" in w.text.toPlainText()
        assert not w.open_btn.isEnabled() and not w.save_btn.isEnabled()
    finally:
        w.close()
    monkeypatch.setattr(M.QFileDialog, "getOpenFileName", lambda *a, **k: ("", ""))
    assert win.inspect_lens_dialog() is None


def test_fixed_font_is_a_real_family(qtbot):
    # Requesting a missing family ("Monospace" on macOS/Windows) makes Qt rebuild its alias table and warn.
    from PySide6.QtGui import QFont, QFontDatabase, QFontInfo
    from lensforge_qt.fonts import fixed_font
    info = QFontInfo(fixed_font())
    assert info.family() in QFontDatabase.families()
    assert info.fixedPitch()
    base = QFont()
    base.setPointSizeF(13.0)
    assert fixed_font(base).pointSizeF() == 13.0


def test_no_hard_coded_font_families():
    import re
    pkg = os.path.join(HERE, "..", "lensforge_qt")
    bad = re.compile(r'QFont\(\s*["\']|setFamily\(|setFamilies\(|font-family\s*:', re.I)
    hits = [f"{name}:{i}" for name in sorted(os.listdir(pkg)) if name.endswith(".py")
            for i, line in enumerate(open(os.path.join(pkg, name), encoding="utf-8"), 1) if bad.search(line)]
    assert not hits, f"use lensforge_qt.fonts.fixed_font() instead of a named family: {hits}"
