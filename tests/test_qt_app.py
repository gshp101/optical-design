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
