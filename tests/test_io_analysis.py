import math

import numpy as np
import pytest

import lensforge as lf
from lensforge import samples
from lensforge.io import dumps, loads


def test_json_round_trip(tmp_path):
    s = samples.achromat()
    s.insert(2, lf.EvenAsphere(radius=-200, coefficients=[0, 1e-6], thickness=0.0))
    s.surfaces[3].aperture = lf.CircularAperture(12)
    p = tmp_path / "a.lens.json"
    lf.save(s, str(p))
    t = lf.load(str(p))
    assert dumps(t) == dumps(s)
    px, py = lf.pupil_grid("hexapolar", 3)
    np.testing.assert_allclose(s.trace(0, 1, px, py).image, t.trace(0, 1, px, py).image)


ZMX = """VERS 140101
MODE SEQ
NAME Test doublet
UNIT MM X W X CM MR CPMM
ENPD 2.0E+1
FTYP 0 0 3 3 0 0 0
XFLN 0 0 0 0 0 0 0 0 0 0 0 0
YFLN 0 1 2 0 0 0 0 0 0 0 0 0
FWGN 1 1 1 1 1 1 1 1 1 1 1 1
WAVM 1 0.4861 1
WAVM 2 0.5876 1
WAVM 3 0.6563 1
PWAV 2
SURF 0
  TYPE STANDARD
  CURV 0.0
  DISZ INFINITY
SURF 1
  STOP
  TYPE STANDARD
  CURV 1.593625498E-2
  DISZ 4
  GLAS N-BAF10 0 0 1.67 47.1
  DIAM 10
SURF 2
  TYPE STANDARD
  CURV -2.187705097E-2
  DISZ 2.5
  GLAS N-SF6 0 0 1.8 25
SURF 3
  TYPE EVENASPH
  CURV -7.798487093E-3
  PARM 1 0
  PARM 2 1E-7
  DISZ 70
SURF 4
  TYPE STANDARD
  CURV 0
  DISZ 0
"""


def test_zmx_import():
    s = lf.load_zmx(ZMX)
    assert s.name == "Test doublet"
    assert s.num_surfaces == 5 and s.stop_index == 1
    assert [f.y for f in s.fields] == [0, 1, 2]
    assert s.primary == pytest.approx(0.5876)
    assert isinstance(s.surfaces[3], lf.EvenAsphere) and s.surfaces[3].coefficients == [0, 1e-7]
    assert s.surfaces[1].radius == pytest.approx(62.75, rel=1e-8)
    assert s.paraxial().epd == 20


def test_spot_and_fans_shapes():
    s = samples.singlet()
    sp = lf.spot_diagram(s, 2)
    assert len(sp["x"]) == 3 and sp["rms_radius"] > 0 and sp["geo_radius"] >= sp["rms_radius"]
    f = lf.ray_fan(s, 2, n=11)
    assert f["ey"].shape == (3, 11)
    # chief ray of primary wavelength has zero aberration
    assert f["ey"][1, 5] == pytest.approx(0, abs=1e-12)
    o = lf.opd_fan(s, 1, n=11)
    assert o["wy"][1, 5] == pytest.approx(0, abs=1e-9)
    wf = lf.wavefront(s, 0, n=32)
    assert wf["W"].shape == (32, 32) and wf["rms"] > 0


def test_singlet_spherical_aberration_sign():
    """An under-corrected positive singlet has marginal rays focusing short:
    at the paraxial focus the upper marginal ray lands below the axis."""
    s = samples.singlet()
    f = lf.ray_fan(s, 0, [s.primary], n=5)
    assert f["ey"][0, -1] < 0 and f["ey"][0, 0] > 0


def test_update_semi_diameters():
    s = samples.singlet()
    s.update_semi_diameters()
    assert s.surfaces[1].semi_diameter >= 10
    assert s.surfaces[2].semi_diameter > 9


def test_copy_is_independent():
    s = samples.singlet()
    c = s.copy()
    c.surfaces[1].radius = 1000
    assert s.surfaces[1].radius != 1000
    assert c.library is s.library


def test_set_param_for_optimisation():
    s = lf.EvenAsphere(radius=50, coefficients=[0])
    s.set_param("coefficients[2]", 1e-6)
    s.set_param("curvature", 0.01)
    assert s.coefficients == [0, 0, 1e-6] and s.radius == pytest.approx(100)


def test_cli_runs(capsys, tmp_path):
    from lensforge.__main__ import main
    p = tmp_path / "s.lens.json"
    lf.save(samples.singlet(), str(p))
    assert main([str(p)]) == 0
    out = capsys.readouterr().out
    assert "efl" in out and "rms" in out
