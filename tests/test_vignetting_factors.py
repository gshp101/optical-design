"""Vignetting factors (VDX/VDY/VCX/VCY/VAN): ray mapping, Set / Clear Vignetting, file formats, UIs."""

import json
import math
import os

import numpy as np
import pytest

import lensforge as lf
from lensforge.system import Field
from lensforge.vignetting_factors import _Passes

HERE = os.path.dirname(__file__)
ARDUCAM = os.path.join(HERE, "..", "examples", "arducam-lk004", "CS1806ZM06_6mm.lens.json")


def clipped_lens():
    """A wide-angle lens whose front element and a rear surface are too small for the outer fields."""
    s = lf.load(ARDUCAM)
    s.surfaces[1].semi_diameter = 8.0
    s.surfaces[13].semi_diameter = 4.6
    return s


def rim(n=64, r=0.999):
    th = np.linspace(0, 2 * np.pi, n, endpoint=False)
    return r * np.cos(th), r * np.sin(th)


# ---------------------------------------------------------------------- the pupil mapping
def test_vignette_pupil_formula_and_angle():
    f = Field(0, 1, vdx=0.1, vdy=-0.2, vcx=0.25, vcy=0.5, van=90.0)
    u, v = f.vignette_pupil(np.array([1.0, 0.0]), np.array([0.0, 1.0]))
    # compress (0.75, 0) / (0, 0.5), rotate +90 deg -> (0, 0.75) / (-0.5, 0), then decentre
    assert np.allclose(u, [0.1, -0.4]) and np.allclose(v, [0.55, -0.2])
    assert not Field().vignetted and Field(van=10).vignetted
    px, py = Field().vignette_pupil(0.3, 0.4)
    assert (px, py) == (0.3, 0.4)


def test_factors_change_traced_rays_only_at_defined_fields():
    s = lf.load(ARDUCAM)
    hx, hy = s.normalized_field(4)
    before = lf.trace_rays(s, hx, hy, 0.0, 1.0).image.copy()
    s.fields[4].vcy = 0.5
    s.fields[4].vdy = 0.2
    after = lf.trace_rays(s, hx, hy, 0.0, 1.0).image
    same_as = lf.trace_rays(s, hx, hy, 0.0, 0.7, vignetting=False).image  # 0.2 + 1 * (1 - 0.5)
    assert not np.allclose(before, after) and np.allclose(after, same_as)
    # the chief ray stays the ray through the stop centre; other field points are not vignetted
    assert np.allclose(lf.chief_ray(s, hx, hy).image, lf.trace_rays(s, hx, hy, 0, 0, vignetting=False).image)
    a = lf.trace_rays(s, 0, 0.5 * hy, 0.0, 1.0).image
    b = lf.trace_rays(s, 0, 0.5 * hy, 0.0, 1.0, vignetting=False).image
    assert np.allclose(a, b)


def test_distortion_ignores_factors():
    s = lf.load(ARDUCAM)
    d0 = lf.distortion(s, 1.0)
    s.fields[-1].vdy = 0.3
    assert lf.distortion(s, 1.0) == pytest.approx(d0)


# ---------------------------------------------------------------------- Set / Clear Vignetting
@pytest.mark.parametrize("aiming", ["paraxial", "real"])
def test_set_vignetting_makes_every_rim_ray_pass(aiming):
    s = clipped_lens()
    s.ray_aiming = aiming
    res = s.set_vignetting()
    assert set(res) == set(range(len(s.fields)))
    assert res[0] == {"vdx": 0.0, "vdy": 0.0, "vcx": 0.0, "vcy": 0.0, "van": 0.0}  # on axis: not clipped
    assert s.fields[4].vcy > 0.3 and s.fields[4].vdy > 0.1  # the edge field loses its lower rim
    px, py = rim()
    for i in range(len(s.fields)):
        passes = _Passes(s, i, None, True)
        hx, hy = s.normalized_field(i)
        assert passes(*s.fields[i].vignette_pupil(px, py)).all(), i
        # and it is no smaller than needed: a slightly larger rim loses rays
        if s.fields[i].vcy:
            assert not passes(*s.fields[i].vignette_pupil(1.03 * px, 1.03 * py)).all(), i


def test_set_vignetting_classic_four_ray_mode_and_unclipped_lens():
    s = lf.load(ARDUCAM)
    assert all(v["vcy"] == 0 and v["vdy"] == 0 for v in s.set_vignetting().values())
    s = clipped_lens()
    loose = s.copy()
    loose.set_vignetting(strict=False)
    s.set_vignetting()
    assert loose.fields[4].vcy < s.fields[4].vcy  # the strict fit shrinks the ellipse to fit inside
    assert loose.fields[4].vdy == pytest.approx(s.fields[4].vdy)


def test_set_vignetting_uses_surface_apertures_and_semi_diameter_switch():
    s = lf.load(ARDUCAM)
    s.surfaces[1].aperture = lf.CircularAperture(8.0)
    assert s.set_vignetting(use_semi_diameters=False)[4]["vcy"] > 0.3
    s = clipped_lens()
    assert all(v["vcy"] == 0 for v in s.set_vignetting(use_semi_diameters=False).values())


def test_auto_angle_follows_the_field_direction():
    s = clipped_lens()
    y = s.fields[4].y
    # angle fields: the same off-axis angle along the diagonal has tan components tan(y) / sqrt(2)
    d = math.degrees(math.atan(math.tan(math.radians(y)) / math.sqrt(2)))
    s.fields = [Field(0, 0), Field(0, y), Field(d, d)]
    res = s.set_vignetting(angle="auto")
    assert res[1]["van"] == 0.0 and res[2]["van"] == pytest.approx(-45.0)
    # the lens is rotationally symmetric: the diagonal field gets the y field's factors, rotated
    assert res[2]["vcy"] == pytest.approx(res[1]["vcy"], abs=2e-3)
    assert res[2]["vcx"] == pytest.approx(res[1]["vcx"], abs=2e-3)
    r = math.hypot(res[2]["vdx"], res[2]["vdy"])
    assert r == pytest.approx(res[1]["vdy"], abs=2e-3)
    assert res[2]["vdx"] == pytest.approx(res[2]["vdy"], abs=2e-3)


def test_set_vignetting_keeps_a_users_angle_and_clear_resets():
    s = clipped_lens()
    s.fields[4].van = 30.0
    s.set_vignetting(fields=[4])
    assert s.fields[4].van == 30.0 and s.fields[4].vcy > 0
    px, py = rim()
    assert _Passes(s, 4, None, True)(*s.fields[4].vignette_pupil(px, py)).all()
    s.clear_vignetting(keep_angle=True)
    assert not any((s.fields[4].vdx, s.fields[4].vdy, s.fields[4].vcx, s.fields[4].vcy))
    assert s.fields[4].van == 30.0
    lf.clear_vignetting(s)
    assert not any(f.vignetted for f in s.fields)


def test_field_with_no_passing_ray():
    s = lf.load(ARDUCAM)
    s.surfaces[5].aperture = lf.CircularAperture(1e-4, dx=4.0)
    s.fields[2].vcy = 0.4
    res = s.set_vignetting(fields=[2])
    assert res == {2: None} and s.fields[2].vcy == 0.4  # left as it was, not cleared


# ---------------------------------------------------------------------- files and multi-config
def test_json_round_trip_and_old_files(tmp_path):
    s = clipped_lens()
    s.set_vignetting(angle=10.0)
    p = tmp_path / "v.lens.json"
    lf.save(s, str(p))
    t = lf.load(str(p))
    assert [vars(f) for f in t.fields] == [vars(f) for f in s.fields]
    d = json.loads(p.read_text())
    for f in d["fields"]["values"]:
        f.pop("van")
    p.write_text(json.dumps(d))
    assert lf.load(str(p)).fields[0].van == 0.0


def test_zmx_import_reads_vignetting_factors():
    text = """VERS 140000
UNIT MM X W X CM MR CPMM
ENPD 10
FTYP 0 0 3 1 0 0 0
XFLN 0 0 0
YFLN 0 10 20
FWGN 1 1 1
VDXN 0 0 0.05
VDYN 0 0.1 0.2
VCXN 0 0 0.1
VCYN 0 0.2 0.3
VANN 0 0 15
WAVM 1 0.55 1
PWAV 1
SURF 0
  TYPE STANDARD
  DISZ INFINITY
SURF 1
  STOP
  TYPE STANDARD
  CURV 0.01
  DISZ 5
  GLAS N-BK7 0 0 1.5 40
SURF 2
  TYPE STANDARD
  DISZ 95
SURF 3
  TYPE STANDARD
"""
    s = lf.load_zmx(text)
    f = s.fields[2]
    assert (f.vdx, f.vdy, f.vcx, f.vcy, f.van) == (0.05, 0.2, 0.1, 0.3, 15.0)
    assert s.fields[1].vdy == 0.1 and "VANN" not in s.notes


def test_multiconfig_fvan_operand():
    s = clipped_lens()
    mc = lf.MultiConfig(2)
    s.multiconfig = mc
    mc.add_row(s, "FVAN", 4, values=[0.0, 25.0])
    mc.set_config(s, 2)
    assert s.fields[4].van == 25.0
    assert "FVAN" in lf.MC_OPERANDS


# ---------------------------------------------------------------------- web session
def test_web_session_compute_vignetting_leaves_the_lens_alone():
    from lensforge_web.session import Session, dispatch
    s = Session()
    s.doc.replace("load", clipped_lens())
    d = json.loads(dispatch("system_settings", "{}", s))["result"]
    assert len(d["fields"][0]) == 8 and "VAN" in d["field_tips"] and d["set_vignetting_tip"]
    rev = s.doc.revision
    out = json.loads(dispatch("compute_vignetting", json.dumps({"d": d}), s))
    assert "error" not in out and s.doc.revision == rev and "state" not in out
    rows = out["result"]["fields"]
    assert float(rows[4][6]) > 0.3 and out["result"]["lost"] == []
    d["fields"] = rows
    json.loads(dispatch("apply_system_settings", json.dumps({"d": d}), s))
    assert s.doc.system.fields[4].vcy == pytest.approx(float(rows[4][6]))


# ---------------------------------------------------------------------- Qt dialog
def test_qt_fields_tab_set_and_clear(qtbot, tmp_path):
    pytest.importorskip("PySide6")
    from PySide6.QtCore import QSettings
    from lensforge_qt.main_window import MainWindow
    from lensforge_qt.system_dialog import FIELD_COLUMNS, SystemExplorer
    w = MainWindow(settings=QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat))
    try:
        w.doc.reset(clipped_lens())
        d = SystemExplorer(w.doc, w, tab=1)
        assert FIELD_COLUMNS[-1] == "VAN" and d.field_table.columnCount() == 8
        assert d.set_vig.toolTip() and d.clear_vig.toolTip()
        assert d.field_table.horizontalHeaderItem(7).toolTip()
        res = d.set_vignetting()
        assert res[4]["vcy"] > 0.3
        assert not w.doc.system.fields[4].vignetted  # only the table changed
        assert float(d.field_table.item(4, 6).text()) == pytest.approx(res[4]["vcy"])
        assert d.apply() and w.doc.system.fields[4].vcy == pytest.approx(res[4]["vcy"])
        d.field_table.item(4, 7).setText("12")
        d.clear_vignetting()
        assert all(d.field_table.item(r, c).text() == "0" for r in range(5) for c in range(3, 8))
        assert d.apply() and not any(f.vignetted for f in w.doc.system.fields)
        w.doc.undo_stack.undo()
        assert w.doc.system.fields[4].vcy > 0.3
        d.close()
    finally:
        w.doc.undo_stack.setClean()
        w.close()
        w.deleteLater()


# ---------------------------------------------------------------------- iterative Set Vignetting
def off_centre_lens():
    """Only an off-axis patch of the pupil (around px = -0.6) gets through: no ray on the line px = 0 passes."""
    s = lf.load(ARDUCAM)
    stop = s.stop_index
    r_stop = lf.ParaxialAnalysis(s).stop_radius
    s.surfaces[stop].aperture = lf.CircularAperture(0.3 * r_stop, dx=-0.6 * r_stop)
    return s


def test_set_vignetting_finds_an_off_centre_pupil_from_scratch():
    s = off_centre_lens()
    res = s.set_vignetting()
    px, py = rim()
    for i in range(len(s.fields)):
        assert res[i] is not None, i
        assert res[i]["vdx"] == pytest.approx(-0.6, abs=0.06) and res[i]["vcx"] > 0.6
        assert _Passes(s, i, None, True)(*s.fields[i].vignette_pupil(px, py)).all(), i


def test_set_vignetting_starts_from_the_current_factors():
    s = off_centre_lens()
    s.set_vignetting()
    before = [dict(vars(f)) for f in s.fields]
    # pressing it again on its own result changes nothing
    s.set_vignetting()
    for b, f in zip(before, s.fields):
        for k in ("vdx", "vdy", "vcx", "vcy"):
            assert getattr(f, k) == pytest.approx(b[k], abs=1e-5), k
    # factors that let rays through always give new factors, even from a rough guess
    for f in s.fields:
        f.vdx, f.vdy, f.vcx, f.vcy = -0.5, 0.05, 0.9, 0.9
    res = s.set_vignetting()
    assert all(v is not None for v in res.values())
    assert s.fields[0].vdx == pytest.approx(before[0]["vdx"], abs=2e-3)


def test_hyperspectral_example_keeps_working_vignetting():
    s = lf.load(os.path.join(HERE, "..", "examples", "output", "hyperspectral.lens.json"))
    px, py = rim()
    res = s.set_vignetting()
    for i in range(len(s.fields)):
        assert res[i] is not None, i
        assert _Passes(s, i, None, True)(*s.fields[i].vignette_pupil(px, py)).all(), i
