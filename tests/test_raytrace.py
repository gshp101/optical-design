import math

import numpy as np
import pytest

import lensforge as lf
from lensforge import samples
from lensforge.raytrace import MISS, OK, TIR, VIGNETTED, trace


def test_single_surface_spherical_aberration_closed_form():
    """Parallel ray at height h refracted by one sphere crosses the axis at
    L' = R + R sin I' / sin(I - I')."""
    R, n, h = 50.0, 1.5, 12.0
    s = lf.OpticalSystem()
    s.set_aperture("EPD", 2 * h)
    s.add_surface(radius=R, thickness=200, material=n, stop=True)
    r = s.trace(0, 0, 0, 1)
    P, D = r.positions[1, 0], r.directions[1, 0]
    z_cross = P[2] - P[1] * D[2] / D[1]
    I = math.asin(h / R)
    Ip = math.asin(math.sin(I) / n)
    assert z_cross == pytest.approx(R + R * math.sin(Ip) / math.sin(I - Ip), rel=1e-12)


def test_snell_law_vector():
    s = samples.singlet()
    r = s.trace(0, 1, np.array([0.3, -0.7]), np.array([0.5, 0.6]))
    n = s.media(s.primary)[0]
    for k in (1, 2):
        N = r.normals[k]
        Din, Dout = r.directions[k - 1], r.directions[k]
        sin_in = np.linalg.norm(np.cross(Din, N), axis=1)
        sin_out = np.linalg.norm(np.cross(Dout, N), axis=1)
        np.testing.assert_allclose(n[k - 1] * sin_in, n[k] * sin_out, rtol=1e-12)
        # refracted ray stays in the plane of incidence
        np.testing.assert_allclose(np.einsum("ij,ij->i", np.cross(Din, N), Dout), 0, atol=1e-14)


def test_tilted_plate_lateral_shift():
    t, n, deg = 10.0, 1.5, 30.0
    s = lf.OpticalSystem()
    s.set_aperture("EPD", 1)
    s.set_fields([deg])
    s.add_surface(thickness=t, material=n, stop=True)
    s.add_surface(thickness=10)
    r = s.trace(0, 1, 0, 0)
    np.testing.assert_allclose(r.direction[0], r.directions[0, 0], atol=1e-15)
    th = math.radians(deg)
    shift = t * math.sin(th) * (1 - math.cos(th) / math.sqrt(n * n - math.sin(th) ** 2))
    # perpendicular displacement between incoming and outgoing rays
    P0, D = r.positions[0, 0], r.directions[0, 0]
    P2 = r.positions[2, 0] + np.array([0, 0, t])  # into surface-1 frame
    d = np.linalg.norm(np.cross(P2 - P0, D))
    assert d == pytest.approx(shift, rel=1e-12)


def test_parabola_is_perfect_on_axis():
    s = samples.parabolic_mirror()
    spot = lf.spot_diagram(s, 0)
    assert spot["rms_radius"] < 1e-12
    assert np.nanmax(np.abs(lf.opd_fan(s, 0)["wy"])) < 1e-6


def test_cassegrain_is_perfect_on_axis():
    s = samples.cassegrain()
    assert s.paraxial().efl == pytest.approx(2500)
    spot = lf.spot_diagram(s, 0)
    assert spot["n_rays"] == spot["n_launched"]
    assert spot["rms_radius"] < 1e-10
    assert np.nanmax(np.abs(lf.opd_fan(s, 0)["wy"])) < 1e-5


def test_ellipsoid_mirror_images_foci_perfectly():
    d1, d2 = 300.0, 900.0
    R = -2 * d1 * d2 / (d1 + d2)
    e = (d2 - d1) / (d1 + d2)
    s = lf.OpticalSystem()
    s.object.thickness = d1
    s.set_aperture("OBJECT_NA", 0.1)
    s.set_fields([0], "OBJECT_HEIGHT")
    s.add_surface(radius=R, conic=-e * e, thickness=-d2, material="MIRROR", stop=True)
    assert s.paraxial().image_distance == pytest.approx(-d2)
    spot = lf.spot_diagram(s, 0)
    assert spot["rms_radius"] < 1e-10
    assert np.nanmax(np.abs(lf.opd_fan(s, 0)["wy"])) < 1e-5


def test_ideal_lens_is_perfect_off_axis():
    s = lf.OpticalSystem()
    s.set_aperture("EPD", 20)
    s.set_fields([0, 10])
    s.add_surface(lf.Paraxial(focal_length=100, thickness=100, stop=True))
    spot = lf.spot_diagram(s, 1)
    assert spot["rms_radius"] < 1e-12
    assert np.nanmax(np.abs(lf.opd_fan(s, 1)["wy"])) < 1e-7
    assert spot["reference"][1] == pytest.approx(100 * math.tan(math.radians(10)))


def test_real_converges_to_paraxial():
    s = samples.singlet()
    for py in (1e-3, 1e-4):
        r = s.trace(0, 0, 0, py)
        # small aperture ray lands at the paraxial focus
        assert abs(r.y[0]) < 1e-3 * py
    r = s.trace(0, 1e-4, 0, 0)
    par_h = s.paraxial().image_height_per_unit_field() * math.tan(math.radians(10 * 1e-4))
    assert r.y[0] == pytest.approx(par_h, rel=1e-6)


def test_paraxial_vs_real_marginal_ray_heights():
    s = samples.achromat()
    p = s.paraxial()
    ym, _ = p.marginal_ray
    r = s.trace(0, 0, 0, 1e-5)
    np.testing.assert_allclose(r.positions[1:-1, 0, 1] / 1e-5, ym, rtol=1e-6)


def test_total_internal_reflection_flagged():
    s = lf.OpticalSystem()
    s.set_aperture("EPD", 2)
    s.set_fields([0, 30])
    s.add_surface(thickness=5, material=1.5, stop=True)
    s.add_surface(lf.CoordinateBreak(tilt_x=45))  # 45 deg > critical angle 41.8 deg
    s.add_surface(thickness=5)
    r = s.trace(0, 0, 0, 0)
    assert r.status[0] == TIR and r.error_surface[0] == 3


def test_miss_flagged():
    s = lf.OpticalSystem()
    s.set_aperture("EPD", 30)
    s.add_surface(radius=10, thickness=5, material=1.5, stop=True)
    s.add_surface(thickness=10)
    r = s.trace(0, 0, 0, np.array([0.0, 1.0]))
    assert r.status[0] == OK and r.status[1] == MISS


def test_vignetting_by_aperture():
    s = samples.singlet()
    s.surfaces[2].aperture = lf.CircularAperture(5.0)
    r = s.trace(0, 0, 0, np.array([0.1, 0.9]))
    assert list(r.status) == [OK, VIGNETTED]
    s.surfaces[2].aperture = lf.CircularObscuration(2.0)
    r = s.trace(0, 0, 0, np.array([0.1, 0.9]))
    assert list(r.status) == [VIGNETTED, OK]


def test_even_asphere_zero_terms_equals_standard():
    a = samples.singlet()
    b = a.copy()
    s = b.surfaces[1]
    b.surfaces[1] = lf.EvenAsphere(radius=s.radius, thickness=s.thickness, material=s.material, stop=True,
                                   coefficients=[0.0, 0.0])
    px, py = lf.pupil_grid("hexapolar", 4)
    ra, rb = a.trace(0, 1, px, py), b.trace(0, 1, px, py)
    np.testing.assert_allclose(ra.image, rb.image, atol=1e-11)


@pytest.mark.parametrize("surf", [
    lf.EvenAsphere(radius=40, conic=-0.5, coefficients=[0, 1e-5, -2e-8]),
    lf.OddAsphere(radius=40, coefficients=[0, 0, 1e-4, 1e-6]),
    lf.Toroidal(radius=40, radius_x=-60),
    lf.XYPolynomial(radius=40, terms=[[2, 0, 0.01], [0, 3, 0.002], [1, 2, -0.003]], norm_radius=10),
])
def test_newton_intersection_lies_on_surface(surf):
    rng = np.random.default_rng(1)
    P = np.column_stack([rng.uniform(-8, 8, 50), rng.uniform(-8, 8, 50), np.full(50, -20.0)])
    D = np.column_stack([rng.uniform(-0.2, 0.2, 50), rng.uniform(-0.2, 0.2, 50), np.ones(50)])
    D /= np.linalg.norm(D, axis=1, keepdims=True)
    t, ok = surf.intersect(P, D)
    assert ok.all()
    X = P + t[:, None] * D
    np.testing.assert_allclose(surf.sag(X[:, 0], X[:, 1]), X[:, 2], atol=1e-11)
    # analytic gradient agrees with finite differences
    h = 1e-6
    gx, gy = surf.sag_gradient(X[:, 0], X[:, 1])
    fx = (surf.sag(X[:, 0] + h, X[:, 1]) - surf.sag(X[:, 0] - h, X[:, 1])) / (2 * h)
    fy = (surf.sag(X[:, 0], X[:, 1] + h) - surf.sag(X[:, 0], X[:, 1] - h)) / (2 * h)
    np.testing.assert_allclose(gx, fx, atol=1e-7)
    np.testing.assert_allclose(gy, fy, atol=1e-7)


def test_cylinder_lens_focuses_one_axis():
    s = lf.OpticalSystem()
    s.set_aperture("EPD", 10)
    s.add_surface(lf.Toroidal(radius=51.68, thickness=3, material="N-BK7", stop=True))
    s.add_surface(thickness=100)
    f = s.paraxial().efl
    s.surfaces[2].thickness = s.paraxial().bfl
    ry = s.trace(0, 0, 0, 0.01)
    rx = s.trace(0, 0, 0.5, 0)
    assert abs(ry.y[0]) < 1e-6
    assert rx.x[0] == pytest.approx(2.5, rel=1e-12)  # no power in x


def test_coordinate_break_round_trip():
    s = samples.singlet()
    base = s.trace(0, 1, 0.3, 0.4).image
    cb1 = lf.CoordinateBreak(decenter_x=1.2, decenter_y=-0.7, tilt_x=5, tilt_y=-3, tilt_z=20)
    cb2 = lf.CoordinateBreak(decenter_x=-1.2, decenter_y=0.7, tilt_x=-5, tilt_y=3, tilt_z=-20, order=1)
    s.insert(2, cb1)
    s.insert(3, cb2)
    np.testing.assert_allclose(s.trace(0, 1, 0.3, 0.4).image, base, atol=1e-12)


def test_fold_mirror():
    """45 degree fold: the image plane after the fold receives a perfect focus."""
    s = lf.OpticalSystem()
    s.set_aperture("EPD", 10)
    s.add_surface(lf.Paraxial(focal_length=100, thickness=50, stop=True))
    s.add_surface(lf.CoordinateBreak(tilt_x=45))
    s.add_surface(material="MIRROR")
    s.add_surface(lf.CoordinateBreak(tilt_x=45, thickness=-50))
    r = s.trace(0, 0, *lf.pupil_grid("hexapolar", 3))
    assert r.valid.all()
    np.testing.assert_allclose(r.image[:, :2], 0, atol=1e-12)
    # global geometry: image lies 50 below the mirror (rotated into -y or +y)
    g = r.global_positions()
    assert abs(abs(g[-1, 0, 1]) - 50) < 1e-9 and abs(g[-1, 0, 2] - 50) < 1e-9


def test_real_ray_aiming_hits_stop_centre():
    # Wide-angle meniscus with stop behind: paraxial aiming misses the stop centre
    s = lf.OpticalSystem()
    s.set_aperture("EPD", 4)
    s.set_fields([0, 30])
    s.add_surface(radius=20, thickness=3, material="N-SF11")
    s.add_surface(radius=12, thickness=8)
    s.add_surface(thickness=30, stop=True)
    st = s.stop_index
    rp = s.trace(0, 1, 0, 0, last=None)
    s.ray_aiming = "real"
    rr = s.trace(0, 1, np.array([0.0, 0.0, 1.0]), np.array([0.0, 1.0, 0.0]))
    stop_r = s.paraxial().stop_radius
    assert abs(rp.positions[st, 0, 1]) > 1e-3
    np.testing.assert_allclose(rr.positions[st, :, :2], [[0, 0], [0, stop_r], [stop_r, 0]], atol=1e-8)


def test_real_ray_aiming_fisheye_full_field():
    # Fig. 9.16 (180 deg fisheye): a chief ray aimed at the paraxial pupil misses the front
    # meniscus at 87.5 deg, so real aiming has to walk the field out from the axis
    import os
    from lensforge.raytrace import RayGenerator
    path = os.path.join(os.path.dirname(__file__), "..", "examples", "ModernLensDesignSmith",
                        "Chapter 9 - Reverse Telephoto Lenses", "Figure 9.16.lens.json")
    s = lf.load(path)
    g = RayGenerator(s, aiming="real")
    spec = g.object_spec(0, 1)
    zero = np.zeros(1)
    sx, sy = g._stop_coords(spec, *g._solve_aim(spec, zero, zero, zero, zero))
    assert not np.isfinite(sy).all()
    r = s.trace(0, 1, zero, zero)
    assert r.valid.all()
    np.testing.assert_allclose(r.positions[s.stop_index, 0, :2], [0, 0], atol=1e-8)


def test_real_image_height_field():
    s = samples.singlet()
    s.set_fields([0, 5, 10], "REAL_IMAGE_HEIGHT")
    r = s.trace(0, 1, 0, 0)
    assert r.y[0] == pytest.approx(10, abs=1e-9)
    r = s.trace(0, 0.5, 0, 0)
    assert r.y[0] == pytest.approx(5, abs=1e-9)


def test_binary_phase_lens_power():
    f, M, R0, wl = 200.0, 1, 10.0, 0.55
    a1 = -math.pi * R0**2 / (M * wl * 1e-3 * f)
    s = lf.OpticalSystem()
    s.set_wavelengths([wl])
    s.set_aperture("EPD", 2)
    s.add_surface(lf.BinaryPhase(coefficients=[a1], norm_radius=R0, thickness=f, stop=True))
    assert s.paraxial().efl == pytest.approx(f)
    r = s.trace(0, 0, 0, 0.01)
    assert abs(r.y[0]) < 1e-6
    # diffractive dispersion: focal length scales as 1/wavelength
    assert s.paraxial(wavelength=wl * 2).efl == pytest.approx(f / 2)


def test_opd_consistent_with_ray_fan():
    """ey = -(R/n') dW/dy  (the documented OPD sign convention)."""
    s = samples.singlet()
    from lensforge.analysis.fans import _Reference
    hx, hy = s.normalized_field(1)
    ref = _Reference(s, hx, hy)
    py = np.linspace(-0.6, 0.6, 7)
    h = 1e-5
    w_plus = lf.opd(s, hx, hy, 0, py + h)
    w_minus = lf.opd(s, hx, hy, 0, py - h)
    r_xp = s.paraxial().exit_pupil_radius
    dWdy = (w_plus - w_minus) / (2 * h * r_xp) * s.primary * 1e-3
    ey = s.trace(hx, hy, 0, py).y - s.trace(hx, hy, 0, 0).y
    np.testing.assert_allclose(ey, -ref.radius * dWdy, rtol=0.06, atol=2e-3)


def test_opl_through_plate_equals_n_t():
    s = lf.OpticalSystem()
    s.set_aperture("EPD", 10)
    s.add_surface(thickness=10, material=1.5, stop=True)
    s.add_surface(thickness=5)
    r = s.trace(0, 0, 0, 0)
    assert r.opl[-1, 0] - r.opl[1, 0] == pytest.approx(15 + 5)


def test_many_rays_vectorised_speed():
    s = samples.achromat()
    px, py = lf.pupil_grid("square", 300)
    r = s.trace(0, 1, px, py)
    assert r.n_rays > 60000 and r.valid.mean() > 0.99


@pytest.mark.parametrize("t0,f,field", [(300.0, 100.0, 10.0), (200.0, 100.0, 5.0), (150.0, 60.0, 3.0)])
def test_ideal_lens_perfect_at_finite_conjugates(t0, f, field):
    """Ideal lens imaging a finite object: zero OPD at every field (was ~3 waves)."""
    s = lf.OpticalSystem()
    s.object.thickness = t0
    s.set_aperture("OBJECT_NA", 0.05)
    s.set_fields([0, field], "OBJECT_HEIGHT")
    s.add_surface(lf.Paraxial(focal_length=f, thickness=1 / (1 / f - 1 / t0), stop=True))
    for k in (0, 1):
        assert lf.spot_diagram(s, k)["rms_radius"] < 1e-10
        o = lf.opd_fan(s, k)
        assert np.nanmax(np.abs(o["wy"])) < 1e-6 and np.nanmax(np.abs(o["wx"])) < 1e-6
    assert lf.wavefront(s, 1, n=16)["rms"] < 1e-6


def test_second_ideal_lens_uses_its_conjugate():
    """The second of two ideal lenses sees a converging beam (finite, negative
    conjugate); the pair must still be aberration-free."""
    s = lf.OpticalSystem()
    s.set_aperture("EPD", 10)
    s.set_fields([0, 2])
    s.add_surface(lf.Paraxial(focal_length=200, thickness=20, stop=True))
    s.add_surface(lf.Paraxial(focal_length=150, thickness=10))
    samples.focus_paraxial(s)
    for k in (0, 1):
        assert np.nanmax(np.abs(lf.opd_fan(s, k)["wy"])) < 1e-6


def test_coordinate_break_z_tilt_inverse_pair_is_identity():
    """+90 then -90 deg about z, immediately after each other, changes nothing."""
    s = samples.achromat()
    base_rays = lf.layout(s)
    base_surfs = lf.surface_profiles(s)
    s.insert(2, lf.CoordinateBreak(tilt_z=90))
    s.insert(3, lf.CoordinateBreak(tilt_z=-90))
    for a, b in zip(lf.surface_profiles(s), base_surfs):
        np.testing.assert_allclose(a["points"], b["points"], atol=1e-12)
    for a, b in zip(lf.layout(s)["rays"], base_rays["rays"]):
        np.testing.assert_allclose(np.delete(a["path"], [2, 3], axis=0), b["path"], atol=1e-12)


@pytest.mark.parametrize("tilt_z", [90, -90, 37, 180])
def test_layout_profile_unchanged_by_z_rotation(tilt_z):
    """A rotationally symmetric lens rotated about z looks the same in the 2-D layout."""
    s = samples.achromat()
    base = lf.surface_profiles(s)
    s.insert(1, lf.CoordinateBreak(tilt_z=tilt_z))
    prof = lf.surface_profiles(s)
    for a, b in zip(prof, base):
        # same cross-section, possibly traversed in the opposite direction
        pa = a["points"] if np.allclose(a["points"][0], b["points"][0], atol=1e-9) else a["points"][::-1]
        np.testing.assert_allclose(pa, b["points"], atol=1e-9)
