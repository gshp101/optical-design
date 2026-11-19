"""Formula solves: a cell computed from other cells (a general pickup), in the core, the shared editing
helpers (Qt and web), the web session, and the Qt Solve dialog."""

import json
import math

import pytest

import lensforge as lf
from lensforge import optimize as opt
from lensforge.optimize import formula as F
from lensforge.samples import achromat
from lensforge_qt import edits as E


def lens():
    return achromat()


# ---------------------------------------------------------------------- core
def test_formula_of_several_cells():
    s = lens()
    opt.set_solve(s, opt.Formula(3, "radius", "-(R1 + R2) / 2"))
    assert s.surfaces[3].radius == pytest.approx(-(s.surfaces[1].radius + s.surfaces[2].radius) / 2)
    opt.set_solve(s, opt.Formula(2, "thickness", "T(s-1) * 0.5 + N1"))
    n1 = float(s.media(s.primary)[0][1])
    assert s.surfaces[2].thickness == pytest.approx(s.surfaces[1].thickness * 0.5 + n1)
    # follows the cells it reads
    s.surfaces[1].thickness = 6.0
    opt.apply_solves(s)
    assert s.surfaces[2].thickness == pytest.approx(3.0 + n1)


def test_names_functions_and_conditions():
    s = lens()
    assert F.evaluate(s, "sqrt(16) + pi - pi + abs(-1) + max(1, 2)", 1) == pytest.approx(7)
    assert F.evaluate(s, "1 if T1 > 3 else 2", 1) == 1
    assert F.evaluate(s, "C1", 1) == pytest.approx(1 / s.surfaces[1].radius)
    assert F.evaluate(s, "K1 + PARAM(1, \"conic\")", 1) == 0
    assert F.evaluate(s, "SD1", 1) > 0  # automatic semi-diameter is computed


def test_par_columns():
    s = lens()
    lf_s = s.surfaces[2]
    E.change_type(s, 2, "EVENASPH")
    s.surfaces[2].coefficients = [0.0, 1e-5]
    assert F.evaluate(s, "PAR2_2 * 2", 1) == pytest.approx(2e-5)
    assert F.evaluate(s, "PAR(s+1, 2)", 1) == pytest.approx(1e-5)
    with pytest.raises(F.FormulaError):
        F.evaluate(s, "PAR1_1", 1)  # a standard surface has no Par columns
    del lf_s


@pytest.mark.parametrize("bad", ["__import__('os')", "open('x')", "T(R1)", "foo", "R1.real", "PAR(1, 9)",
                                 "[1]", "'a'", "lambda: 1", "R1_2", "", "1 +", "x.y", "().__class__"])
def test_unsafe_or_invalid_formulas_are_refused(bad):
    with pytest.raises(F.FormulaError):
        F.parse(bad)


def test_circular_references_are_refused():
    s = lens()
    opt.set_solve(s, opt.Formula(2, "thickness", "T1 + 1"))
    with pytest.raises(ValueError, match="circular"):
        opt.set_solve(s, opt.Formula(1, "thickness", "T2"))
    with pytest.raises(ValueError, match="circular"):
        opt.set_solve(s, opt.Formula(3, "conic", "K3 + 1"))
    assert len(s.solves) == 1


def test_order_follows_dependencies():
    s = lens()
    # surface 1 reads surface 3's formula, which reads surface 2: applied in that order
    opt.set_solve(s, opt.Formula(3, "conic", "T2 * 2"))
    opt.set_solve(s, opt.Formula(1, "conic", "K3 + 1"))
    s.surfaces[2].thickness = 1.25
    opt.apply_solves(s)
    assert s.surfaces[3].conic == pytest.approx(2.5)
    assert s.surfaces[1].conic == pytest.approx(3.5)


def test_saved_in_the_lens_file():
    s = lens()
    opt.set_solve(s, opt.Formula(3, "radius", "-(R1 + R2)/2"))
    s2 = lf.OpticalSystem.from_dict(json.loads(json.dumps(s.to_dict())))
    assert s2.solves == s.solves


def test_insert_and_delete_renumber_the_formula():
    s = lens()
    opt.set_solve(s, opt.Formula(3, "radius", "-(R1 + R2)/2"))
    opt.set_solve(s, opt.Formula(2, "thickness", "T(s-1) * 0.5"))
    E.insert_surface(s, 1)
    got = {x.surface: x.expression for x in s.solves}
    assert got == {4: "-(R2 + R3)/2", 3: "T(s-1) * 0.5"}
    E.insert_surface(s, 3)  # between T(s-1) on 3 and the T2 it reads: written as a number from now on
    got = {x.surface: x.expression for x in s.solves}
    assert got == {5: "-(R2 + R4)/2", 4: "T(2) * 0.5"}
    E.delete_surface(s, 3)
    got = {x.surface: x.expression for x in s.solves}
    assert got == {4: "-(R2 + R3)/2", 3: "T(2) * 0.5"}
    E.delete_surface(s, 2)  # both refer to surface 2: removed
    assert s.solves == []


def test_renumber_keeps_formatting():
    assert F.renumber("2*T3  +   R( 3 )", lambda i: i + 1 if i >= 2 else i, 5, 6) == "2*T4  +   R( 4 )"
    assert F.renumber("T(s-1)", lambda i: i + 1 if i >= 2 else i, 3, 4) == "T(s-1)"
    assert F.renumber("T1", lambda i: None if i == 1 else i, 3, 2) is None


def test_pickup_of_radius_x_and_par():
    s = lens()
    E.change_type(s, 2, "TOROIDAL")
    s.surfaces[2].curvature_x = 0.02
    opt.set_solve(s, opt.Formula(3, "radius", "PAR2_1 * 2"))
    assert s.surfaces[3].radius == pytest.approx(100.0)
    E.change_type(s, 1, "TOROIDAL")
    opt.set_solve(s, opt.Pickup(1, "radius_x", 2))
    assert s.surfaces[1].curvature_x == pytest.approx(0.02)


# ---------------------------------------------------------------------- editing (shared by Qt and web)
def test_typing_an_equals_formula_in_a_cell():
    s = lens()
    E.set_cell(s, 3, "thickness", "=T1 * 10")
    x = E.solve_on(s, 3, "thickness")
    assert type(x).__name__ == "Formula" and x.expression == "T1 * 10"
    assert s.surfaces[3].thickness == pytest.approx(40.0)
    assert E.formula_text(s, 3, "thickness") == "=T1 * 10" and E.typeable(s, 3, "thickness")
    assert E.SOLVE_CODES["Formula"] == "="
    E.set_cell(s, 3, "thickness", "50")          # a plain number: fixed again
    assert E.solve_on(s, 3, "thickness") is None and s.surfaces[3].thickness == 50
    with pytest.raises(ValueError):
        E.set_cell(s, 3, "thickness", "=nonsense(")
    with pytest.raises(ValueError):
        E.set_cell(s, 0, "thickness", "=T1")    # the object cannot have a solve
    # a variable on the cell gives way to the formula
    opt.set_variable(s, 3, "conic")
    E.set_cell(s, 3, "conic", "=K1 - 1")
    assert not any(v.surface == 3 and v.param == "conic" for v in s.variables)


def test_solves_offered_per_cell():
    s = lens()
    assert "Formula" in E.solves_for(s, 2, "radius") and "FNumber" in E.solves_for(s, 2, "radius")
    assert E.solves_for(s, 2, "conic") == ["Pickup", "Formula"]
    assert E.solves_for(s, 2, "material") == ["Pickup"]
    assert E.solves_for(s, 0, "radius") == [] and E.solves_for(s, s.image_index, "thickness") == []
    assert E.solves_for(s, 2, "comment") == [] and E.solves_for(s, 2, "semi_diameter") == []


def test_preview():
    s = lens()
    assert E.formula_preview(s, 3, "thickness", "T1 * 2") == "= 8"
    assert E.formula_preview(s, 3, "thickness", "T9").startswith("Error")
    assert "circular" in E.formula_preview(s, 3, "thickness", "T3 + 1")
    assert not getattr(s, "solves", None)  # the preview does not change the lens


# ---------------------------------------------------------------------- web session
def call(sess, method, **args):
    from lensforge_web.session import dispatch
    out = json.loads(dispatch(method, json.dumps(args), sess))
    assert "error" not in out, out.get("error")
    return out


def test_web_solve_dialog_and_formula():
    pytest.importorskip("matplotlib")
    from lensforge_web.session import Session
    sess = Session()
    call(sess, "load_sample", name="Cemented Achromat")
    form = call(sess, "solve_form", row=3, key="thickness", name=None)["result"]
    assert form["name"] == "" and ["Formula", "Formula"] in form["types"] and form["types"][0][0] == ""
    form = call(sess, "solve_form", row=3, key="thickness", name="Formula")["result"]
    assert form["fields"][0]["name"] == "expression" and form["fields"][0]["value"] == "T(s-1)"
    assert "PAR3_2" in form["help"]
    assert call(sess, "solve_preview", row=3, key="thickness", text="T1*2")["result"] == "= 8"
    out = call(sess, "set_solve", row=3, key="thickness", name="Formula", values={"expression": "=2*T1"})
    cell = out["state"]["lde"]["rows"][3]["cells"][2]
    assert cell["k"] == "thickness" and cell["m"] == "=" and cell["e"] == "=2*T1" and not cell["ro"]
    assert call(sess, "solve_form", row=3, key="thickness", name=None)["result"]["name"] == "Formula"
    # Fixed (no solve) removes it
    out = call(sess, "set_solve", row=3, key="thickness", name="", values={})
    assert "m" not in out["state"]["lde"]["rows"][3]["cells"][2]
    # typing =... in the cell
    out = call(sess, "set_cell", row=3, key="thickness", text="=T1 + T2")
    assert out["state"]["lde"]["rows"][3]["cells"][2]["m"] == "="
    # the context menu offers Formula
    items = call(sess, "context_menu", row=2, col=7)["result"]
    solve = next(i for i in items if i and i.get("label") == "Solve")
    assert any(i and i["label"] == "Formula..." for i in solve["items"])


def test_web_menu_has_solve_command():
    pytest.importorskip("matplotlib")
    from lensforge_web import menus
    c = menus.menu_data()["commands"]["Edit > Solve"]
    assert c["summary"] and "formula" in c["details"].lower() and c["icon"] and c["shortcut"]


# ---------------------------------------------------------------------- Qt
def test_qt_solve_dialog(qtbot):
    pytest.importorskip("PySide6")
    pytest.importorskip("pytestqt")
    from lensforge_qt.lde import SolveDialog
    s = lens()
    dlg = SolveDialog("", 3, "thickness", None, system=s)
    qtbot.addWidget(dlg)
    assert dlg.name == "" and not dlg.edits
    dlg.type_box.setCurrentIndex(dlg.type_box.findData("Formula"))
    assert set(dlg.edits) == {"expression"} and dlg.edits["expression"].text() == "T(s-1)"
    dlg.edits["expression"].setText("=T1*2")
    assert dlg.preview.text() == "= 8"
    assert dlg.values() == {"expression": "T1*2"}
    dlg.type_box.setCurrentIndex(dlg.type_box.findData("Pickup"))
    assert "from_surface" in dlg.edits


def test_qt_solve_dialog_grows_with_its_fields(qtbot):
    pytest.importorskip("PySide6")
    pytest.importorskip("pytestqt")
    from PySide6.QtWidgets import QApplication
    from lensforge_qt.lde import SolveDialog
    dlg = SolveDialog("", 3, "thickness", None, system=lens())
    qtbot.addWidget(dlg)
    dlg.show()
    QApplication.processEvents()
    fixed = dlg.height()
    for name in ("Pickup", "Formula"):
        dlg.type_box.setCurrentIndex(dlg.type_box.findData(name))
        qtbot.wait(20)
        lay = dlg.layout()
        # every row fits: the dialog is at least as tall as its layout needs at this width
        assert dlg.height() >= lay.totalHeightForWidth(dlg.width()) - 1, name
        assert dlg.height() > fixed
        assert "``" not in dlg.doc_label.text()
