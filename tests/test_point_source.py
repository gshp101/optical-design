import numpy as np
import pytest

import lensforge as lf
from lensforge import samples
from lensforge.raytrace import OK, VIGNETTED, RayGenerator, trace_rays


def _ideal_lens(f=100.0, image_distance=200.0, epd=20.0):
    s = lf.OpticalSystem("ideal")
    s.set_aperture("EPD", epd)
    s.set_wavelengths([0.55])
    s.add_surface(lf.Paraxial(focal_length=f, thickness=image_distance, stop=True))
    return s


def _finite_singlet():
    s = lf.OpticalSystem("finite singlet")
    s.object.thickness = 300.0
    s.set_aperture("EPD", 20)
    s.set_fields([0, 10], kind="OBJECT_HEIGHT")
    s.set_wavelengths([0.5876])
    s.add_surface(radius=60, thickness=5, material="N-BK7", stop=True)
    s.add_surface(radius=-200, thickness=150)
    return s


def test_point_anywhere_in_object_space_images_through_ideal_lens():
    """The lens object is at infinity, but a point 200 mm in front of an f=100 ideal
    lens must image perfectly at 200 mm behind it with magnification -1."""
    s = _ideal_lens()
    r = lf.point_source_trace(s, (2.0, 5.0, -200.0), pattern="hexapolar", n=5)
    assert r["n_valid"] == r["n_launched"] == 91
    np.testing.assert_allclose(r["x"], -2.0, atol=1e-10)
    np.testing.assert_allclose(r["y"], -5.0, atol=1e-10)
    assert r["rms_radius"] < 1e-10
    assert r["chief"] == pytest.approx((-2.0, -5.0), abs=1e-10)


def test_point_on_object_surface_matches_field_trace():
    s = _finite_singlet()
    gen = RayGenerator(s)
    kind, ox, oy = gen.object_spec(0.0, 1.0)
    assert kind == "point"
    px, py = lf.pupil_grid("square", 7)
    ref = trace_rays(s, 0.0, 1.0, px, py)
    for point, frame in (((ox, oy), "lens"), ((ox, oy, 0.0), "object"), ((ox, oy, -300.0), "lens")):
        r = lf.point_source_trace(s, point, px=px, py=py, frame=frame)
        np.testing.assert_allclose(r["x"], ref.x, atol=1e-12)
        np.testing.assert_allclose(r["y"], ref.y, atol=1e-12)
        np.testing.assert_array_equal(r["valid"], ref.valid)


def test_distant_axial_point_approaches_collimated_spot():
    s = samples.singlet()
    sp = lf.spot_diagram(s, 0, wavelengths=[s.primary], reference="centroid")
    r = lf.point_source_trace(s, (0, 0, -1e10))
    assert r["rms_radius"] == pytest.approx(sp["rms_radius"], rel=1e-5)
    assert r["centroid"] == pytest.approx((0.0, 0.0), abs=1e-12)


def test_real_aiming_and_size_put_rays_on_stop_zone():
    s = _finite_singlet()
    s.ray_aiming = "real"
    r_stop = s.paraxial().stop_radius
    r = lf.point_source_trace(s, (0.0, -30.0, -250.0), pattern="ring", n=12, size=0.5, aiming="real")
    stop = r["trace"].positions[s.stop_index]
    np.testing.assert_allclose(np.hypot(stop[:, 0], stop[:, 1]), 0.5 * r_stop, rtol=1e-8)
    np.testing.assert_allclose(np.hypot(r["px"], r["py"]), 0.5)


def test_vignetting_flags():
    s = _finite_singlet()
    s.surfaces[2].aperture = lf.CircularAperture(8.0)
    r = lf.point_source_trace(s, (0.0, 0.0), pattern="yfan", n=21, size=1.2)
    assert r["n_launched"] == 21
    assert r["vignetted"].any() and r["valid"].any()
    assert set(r["status"][r["vignetted"]]) == {VIGNETTED}
    assert set(r["error_surface"][r["vignetted"]]) == {2}
    assert r["reasons"][0] == "vignetted"
    assert np.all(r["status"][r["valid"]] == OK)
    # edge rays are the ones clipped
    assert r["vignetted"][0] and r["vignetted"][-1] and r["valid"][10]
    free = lf.point_source_trace(s, (0.0, 0.0), pattern="yfan", n=21, size=1.2, apertures=False)
    assert free["valid"].all()


def test_lens_file_path_and_wavelength_index(tmp_path):
    s = samples.achromat()
    path = tmp_path / "a.lens.json"
    lf.save(s, str(path))
    a = lf.point_source_trace(str(path), (0, 1.0, -1e4), wavelength=0, pattern="xfan", n=9)
    b = lf.point_source_trace(s, (0, 1.0, -1e4), wavelength=s.wavelengths[0].value, pattern="xfan", n=9)
    np.testing.assert_allclose(a["y"], b["y"])
    assert a["wavelength"] == s.wavelengths[0].value
    np.testing.assert_allclose(a["py"], 0.0)


@pytest.mark.parametrize("pattern", ["hexapolar", "square", "grid", "random", "dithered", "ring", "cross",
                                     "xfan", "yfan"])
def test_all_patterns_trace(pattern):
    r = lf.point_source_trace(samples.singlet(), (0, 3.0, -500.0), pattern=pattern, n=5)
    assert r["n_valid"] == r["n_launched"] > 0
    assert np.isfinite(r["x"]).all()


def test_errors():
    s = samples.singlet()
    with pytest.raises(ValueError):
        lf.point_source_trace(s, (0, 1))  # object at infinity, no z
    with pytest.raises(ValueError):
        lf.point_source_trace(s, (0, 1, 2, 3))
    with pytest.raises(ValueError):
        lf.point_source_trace(s, (0, 0, -100), pattern="nope")
