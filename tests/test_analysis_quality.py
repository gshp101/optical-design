"""Image-quality and field analyses checked against closed-form results."""

import math

import numpy as np
import pytest

import lensforge as lf
from lensforge import samples
from lensforge.analysis.common import bessel_j1, defocused

LAM = 0.5875618


def ideal(epd=10.0, f=100.0, fields=(0, 5)):
    s = lf.OpticalSystem("ideal")
    s.set_aperture("EPD", epd)
    s.set_fields(list(fields))
    s.add_surface(lf.Paraxial(focal_length=f, thickness=f, stop=True))
    return s


def small_singlet():
    s = samples.singlet()
    s.set_aperture("EPD", 4)
    s.set_fields([0, 1])
    samples.focus_paraxial(s)
    return s


# --- diffraction ------------------------------------------------------------------

def test_bessel_j1():
    x = np.array([0.0, 0.5, 1.0, 3.8317059702, 7.0, 8.0, 10.0, 25.0, -2.0])
    ref = [0.0, 0.2422684577, 0.4400505857, 0.0, -0.0046828235, 0.2346363469, 0.0434727462,
           -0.1253502496, -0.5767248078]
    np.testing.assert_allclose(bessel_j1(x), ref, atol=2e-8)


def test_perfect_psf_peak_and_strehl():
    s = ideal()
    for method in ("fft", "huygens"):
        p = (lf.fft_psf if method == "fft" else lf.huygens_psf)(s, 0)
        na = p["na"][1]
        airy_peak = math.pi * na**2 / (LAM * 1e-3) ** 2 * p["dx"] ** 2
        assert p["strehl"] == pytest.approx(1.0, abs=1e-9)
        assert p["peak"] == pytest.approx(airy_peak, rel=0.01)
    assert lf.fft_psf(s, 0)["psf"].sum() == pytest.approx(1.0, abs=1e-3)


def test_perfect_mtf_matches_analytic():
    s = ideal()
    for f in (0, 1):
        m = lf.fft_mtf(s, f)
        na = abs(lf.pupil_function(s, f, n=16).na_y)
        dl = lf.diffraction_limited_mtf(m["freq"], na, [LAM])
        assert np.abs(m["tangential"] - dl).max() < 3e-3
        assert np.abs(m["sagittal"] - lf.diffraction_limited_mtf(m["freq"], abs(lf.pupil_function(s, f, n=16).na_x),
                                                                [LAM])).max() < 3e-3
    na0 = 0.05 / math.sqrt(1 + 0.05**2)
    assert lf.fft_mtf(s, 0)["cutoff"] == pytest.approx(2 * na0 / (LAM * 1e-3), rel=2e-3)
    h = lf.huygens_mtf(s, 0, frequencies=[50, 100])
    np.testing.assert_allclose(h["tangential"], lf.diffraction_limited_mtf([50, 100], 0.0499583, [LAM]), atol=0.01)


def test_airy_encircled_energy():
    s = ideal()
    p = lf.fft_psf(s, 0, image_n=128)
    na = p["na"][1]
    lam = LAM * 1e-3
    ee = lf.energy_from_psf(p, [0.61 * lam / na, 1.117 * lam / na], "encircled", "chief")
    np.testing.assert_allclose(ee, [0.8378, 0.9099], atol=2e-3)  # first and second dark rings
    half = 0.5 * p["x"].size * p["dx"]
    assert lf.energy_from_psf(p, [half], "ensquared")[0] == pytest.approx(p["psf"].sum(), rel=1e-9)
    d = lf.diffraction_energy(s, 0)
    np.testing.assert_allclose(d["energy"], d["diffraction_limit"], atol=1e-6)


def test_small_defocus_strehl_marechal():
    s = ideal()
    na = 0.05 / math.sqrt(1 + 0.05**2)
    w020 = 0.08  # waves
    dz = 2 * w020 * LAM * 1e-3 / na**2
    t = defocused(s, dz)
    zc = lf.zernike_coefficients(t, 0, n_terms=9)
    assert zc["coefficients"][3] == pytest.approx(w020 / 2, rel=0.02)  # fringe Z4 = 2 rho^2 - 1
    rms = w020 / math.sqrt(12)
    marechal = math.exp(-(2 * math.pi * rms) ** 2)
    assert lf.strehl(t, 0) == pytest.approx(marechal, abs=0.01)
    assert lf.strehl(t, 0, method="marechal") == pytest.approx(marechal, abs=0.002)
    assert lf.strehl(t, 0, method="huygens") == pytest.approx(lf.strehl(t, 0), abs=0.01)


def test_through_focus_mtf_peaks_at_focus():
    tf = lf.through_focus_mtf(ideal(), 50, 0, steps=9)
    assert np.argmax(tf["tangential"]) == 4
    np.testing.assert_allclose(tf["tangential"], tf["tangential"][::-1], atol=5e-3)


def test_geometric_mtf_and_energy_of_uniform_blur():
    s = ideal(epd=10)
    dz = 2.0
    t = defocused(s, dz)
    b = dz * 0.05  # blur radius: tan(marginal angle) = 5/100
    g = lf.geometric_mtf(t, 0, frequencies=[1, 3, 5], scale_by_diffraction=False, grid=96)
    x = 2 * math.pi * np.array([1, 3, 5]) * b
    np.testing.assert_allclose(g["tangential"], np.abs(2 * bessel_j1(x) / x), atol=0.01)
    e = lf.geometric_energy(t, 0, radii=[0.5 * b, 0.8 * b], grid=96)
    np.testing.assert_allclose(e["energy"], [0.25, 0.64], atol=0.01)
    assert lf.radius_for_energy(lf.geometric_energy(t, 0, grid=96, n_radii=400), 0.25) == pytest.approx(0.5 * b, rel=0.02)


def test_mtf_vs_field_and_metrics_operands():
    s = samples.achromat()
    r = lf.mtf_vs_field(s, [20, 40], n_fields=3)
    assert r["tangential"].shape == (3, 2)
    t, sg = lf.mtf_at(s, 20, 0)
    assert t == pytest.approx(r["tangential"][0, 0], rel=1e-9) and t == pytest.approx(sg, rel=1e-6)
    from lensforge.analysis import metrics
    assert metrics.evaluate(s, "EFFL") == pytest.approx(s.paraxial().efl)
    assert metrics.evaluate(s, "RSCE", field=2) > 0
    assert 0 < metrics.evaluate(s, "STRH", field=0) <= 1


# --- Seidel -------------------------------------------------------------------------

def test_seidel_matches_real_rays_at_small_aperture():
    s = small_singlet()
    r = lf.seidel(s)
    T, L = r["transverse"], r["longitudinal"]
    assert s.trace(0, 0, 0, 1.0).y[0] == pytest.approx(T["TSPH"], rel=2e-3)
    assert s.trace(0, 1, 0, 0).y[0] - s.paraxial().paraxial_image_height == pytest.approx(T["TDIS"], rel=1e-3)
    yF = s.trace(0, 1, 0, 0, wavelength=0.4861327).y[0]
    yC = s.trace(0, 1, 0, 0, wavelength=0.6562725).y[0]
    assert yF - yC == pytest.approx(T["TLAC"], rel=5e-3)
    fc = lf.field_curvature(s, wavelengths=[s.primary], n_fields=2)
    assert fc["tangential"][0, -1] == pytest.approx(L["LTFC"], rel=5e-3)
    assert fc["sagittal"][0, -1] == pytest.approx(L["LSFC"], rel=5e-3)
    # wavefront coefficients in lensforge's OPD sign convention
    assert lf.opd(s, 0, 0, 0, 1.0)[0] == pytest.approx(r["wavefront"]["W040"], rel=2e-3)
    o = lf.opd(s, 0, 1, 0, np.array([1.0, -1.0]))
    assert (o[0] - o[1]) / 2 == pytest.approx(r["wavefront"]["W131"], rel=5e-3)
    assert lf.opd(s, 0, 1, 1.0, 0.0)[0] == pytest.approx(r["wavefront"]["W040"] + r["wavefront"]["W220"], rel=2e-3)
    cf = lf.chromatic_focal_shift(s, 3)
    assert cf["shift"][0] - cf["shift"][-1] == pytest.approx(L["LAXC"], rel=0.01)


def test_seidel_parabola_and_distortion_form():
    p = samples.parabolic_mirror()
    assert abs(lf.seidel(p)["totals"]["S1"]) < 1e-15
    # conic term: a sphere has spherical aberration
    sph = samples.parabolic_mirror()
    sph.surfaces[1].conic = 0.0
    assert lf.seidel(sph)["totals"]["S1"] != 0
    # S5 equals (Abar/A)(S3+S4) surface by surface for a stop-shifted singlet
    s = small_singlet()
    s.insert(1, lf.Standard(thickness=10.0, stop=True))
    s.surfaces[2].stop = False
    r = lf.seidel(s)
    par = s.paraxial()
    ym, num = par.marginal_ray
    yc, nuc = par.chief_ray
    for i in (2, 3):
        c = s.surfaces[i].curvature
        n0 = s.media(s.primary)[2][i - 1]
        A = num[i - 2] + n0 * ym[i - 1] * c
        Ab = nuc[i - 2] + n0 * yc[i - 1] * c
        ps = r["per_surface"]
        assert ps["S5"][i] == pytest.approx(Ab / A * (ps["S3"][i] + ps["S4"][i]), rel=1e-9)
    # an even asphere's r^4 term adds 8 a4 y^4 (n'-n) to S1
    a = small_singlet()
    b = small_singlet()
    s1 = b.surfaces[1]
    b.surfaces[1] = lf.EvenAsphere(radius=s1.radius, thickness=s1.thickness, material=s1.material, stop=True,
                                   coefficients=[0.0, 1e-6])
    y = a.paraxial().marginal_ray[0][0]
    n = a.media(a.primary)[0][1]
    assert lf.seidel(b)["totals"]["S1"] - lf.seidel(a)["totals"]["S1"] == pytest.approx(8e-6 * y**4 * (n - 1), rel=1e-9)


# --- Zernike --------------------------------------------------------------------------

def test_zernike_orderings_and_fit():
    from lensforge.analysis.zernike import fringe_to_nm, noll_to_nm
    assert [fringe_to_nm(j) for j in (1, 4, 9, 16, 25, 36, 37)] == \
        [(0, 0), (2, 0), (4, 0), (6, 0), (8, 0), (10, 0), (12, 0)]
    assert [noll_to_nm(j) for j in (1, 2, 3, 4, 5, 6, 11, 22)] == \
        [(0, 0), (1, 1), (1, -1), (2, 0), (2, -2), (2, 2), (4, 0), (6, 0)]
    n = 200
    v = (np.arange(n) + 0.5) / n * 2 - 1
    X, Y = np.meshgrid(v, v)
    m = X**2 + Y**2 <= 1
    x, y = X[m], Y[m]
    Z = np.array([lf.zernike_xy(j, x, y, "standard") for j in range(1, 16)])
    np.testing.assert_allclose(Z @ Z.T / x.size, np.eye(15), atol=0.01)
    c = np.zeros(20)
    c[[3, 6, 8, 11]] = [0.3, -0.2, 0.1, 0.05]
    w = lf.evaluate_zernike(c, x, y, "fringe")
    f = lf.fit_zernike(x, y, w, 20, "fringe")
    np.testing.assert_allclose(f["coefficients"], c, atol=1e-10)


# --- field analyses --------------------------------------------------------------------

def test_ideal_lens_distortion_definitions():
    s = ideal(epd=2, fields=(0, 20))
    fc = lf.field_curvature(s, n_fields=3)
    assert np.abs(fc["distortion_percent"]).max() < 1e-8
    assert np.abs(fc["tangential"]).max() < 1e-6 and np.abs(fc["sagittal"]).max() < 1e-6
    th = math.radians(20)
    ft = lf.field_curvature(s, n_fields=2, distortion="ftheta")["distortion_percent"][0, -1]
    assert ft == pytest.approx(100 * (math.tan(th) / th - 1), rel=1e-6)
    assert lf.grid_distortion(s, 5)["max_percent"] < 1e-8
    assert lf.distortion(s, 1.0) == pytest.approx(0, abs=1e-8)


def test_distortion_sign_and_grid():
    s = small_singlet()
    s.set_fields([0, 15])
    fc = lf.field_curvature(s, n_fields=3, wavelengths=[s.primary])
    d = lf.distortion(s, 1.0)
    assert fc["distortion_percent"][0, -1] == pytest.approx(d, rel=1e-9)
    g = lf.grid_distortion(s, 5)
    assert g["max_percent"] >= abs(d) * 0.99


def test_relative_illumination_cos4():
    s = ideal(epd=2, fields=(0, 30))
    ri = lf.relative_illumination(s, n_fields=4)
    np.testing.assert_allclose(ri["relative_illumination"], np.cos(np.radians(ri["field"] * 30)) ** 4, rtol=2e-4)
    assert ri["effective_fnum"][0] == pytest.approx(50, rel=3e-3)


def test_vignetting_fraction():
    s = samples.singlet()
    s.surfaces[1].aperture = lf.CircularAperture(5.0)  # EPD 20 at the stop: keeps 1/4 of the area
    v = lf.vignetting(s, n_fields=2, sampling=96)
    assert v["transmitted_fraction"][0] == pytest.approx(0.25, abs=0.01)
    assert v["vignetting_surfaces"][0] == [1]


def test_lateral_color_and_longitudinal():
    s = small_singlet()
    lc = lf.lateral_color(s, n_fields=3)
    assert lc["extreme"][0] == 0
    assert lc["extreme"][-1] == pytest.approx(lf.seidel(s)["transverse"]["TLAC"], rel=5e-3)
    la = lf.longitudinal_aberration(s, wavelengths=[s.primary], n_pupil=3)
    assert la["focus"][0, 0] == pytest.approx(0, abs=1e-6)
    assert la["focus"][0, -1] == pytest.approx(lf.seidel(s)["longitudinal"]["LSPH"], rel=5e-3)


def test_pupil_aberration():
    pa = lf.pupil_aberration(ideal(), n=5)  # plane stop surface: rays land where aimed
    assert np.abs(pa["tangential_percent"]).max() < 1e-9
    s = samples.singlet()
    s.surfaces[1].stop = False
    back = s.surfaces[2].thickness
    s.surfaces[2].thickness = 10.0
    s.insert(3, lf.Standard(thickness=back - 10.0, stop=True))  # stop 10 mm behind the lens
    pa = lf.pupil_aberration(s, n=5)
    assert np.abs(pa["tangential_percent"]).max() > 0.01


# --- geometry, polarisation, reports -------------------------------------------------------

def test_footprint_sag_layout():
    s = samples.achromat()
    fp = lf.footprint(s, 1, fields=[0])
    assert fp["max_radius"] == pytest.approx(10.0, rel=1e-9)
    sg = lf.surface_sag(lf.Standard(radius=50), 10)
    assert sg["max_departure"] < 1e-12 and sg["bfs_radius"] == pytest.approx(50)
    asp = lf.surface_sag(lf.EvenAsphere(radius=50, coefficients=[0, 1e-6]), 10, best_fit="lsq")
    assert asp["max_departure"] > 0
    lay = lf.layout(s)
    assert len(lay["rays"]) == 3 and len(lay["surfaces"]) == 4


def test_fresnel_transmission():
    s = lf.OpticalSystem()
    s.set_aperture("EPD", 1)
    s.add_surface(thickness=5, material=1.5, stop=True)
    s.add_surface(thickness=10)
    assert lf.polarization_pupil_map(s, 0, n=5)["total_transmission"] == pytest.approx(0.96**2, rel=1e-9)
    b = lf.OpticalSystem()
    b.set_aperture("EPD", 0.01)
    b.add_surface(lf.CoordinateBreak(tilt_x=math.degrees(math.atan(1.5)), stop=True))
    b.add_surface(thickness=5, material=1.5)
    b.add_surface(thickness=10)
    # tilt about x puts the plane of incidence in y-z: y is p-polarised (Brewster angle)
    assert lf.polarization_pupil_map(b, 0, polarization="y", n=3)["total_transmission"] == pytest.approx(1, abs=1e-6)
    ts, tp, rs, rp, ct = lf.fresnel(1.0, 1.5, math.cos(math.atan(1.5)))
    Ts = 1 - abs(rs) ** 2
    assert lf.polarization_pupil_map(b, 0, polarization="x", n=3)["total_transmission"] == pytest.approx(Ts**2, rel=1e-4)
    m = samples.parabolic_mirror()
    assert lf.transmission(m, n_fields=2)["transmission"][0] == pytest.approx(1.0)


def test_cardinal_points_thick_lens():
    n, R1, R2, t = 1.5168, 50.0, -50.0, 6.0
    s = lf.OpticalSystem()
    s.add_surface(radius=R1, thickness=t, material=n, stop=True)
    s.add_surface(radius=R2, thickness=50)
    f = s.paraxial().efl
    cp = lf.cardinal_points(s)
    assert cp["rear_principal_plane"] == pytest.approx(-f * (n - 1) * t / (n * R1), rel=1e-9)
    assert cp["front_principal_plane"] == pytest.approx(-f * (n - 1) * t / (n * R2), rel=1e-9)
    assert cp["front_nodal_point"] == pytest.approx(cp["front_principal_plane"])


def test_ray_table_and_report_and_sensitivity():
    s = samples.achromat()
    tab = lf.ray_trace_table(s, 0, 1, 0, 1)
    assert tab["status"] == "ok" and len(tab["rows"]) == 4
    txt = lf.system_report(s)
    assert "Seidel" in txt and "Strehl" in txt
    from lensforge.analysis import metrics
    sens = metrics.sensitivity(s, [(1, "curvature"), (2, "thickness")], metrics.efl)
    # dEFL/dc1 = -EFL^2 dphi/dc1 with dphi/dc1 = (n1 - 1) for a thin-ish lens front surface (approx)
    assert sens["derivatives"][0] < 0
    sw = metrics.sweep(s, (3, "thickness"), [69, 70], metrics.rms_spot)
    assert np.all(np.isfinite(sw["metric"]))


def test_plot_helpers_smoke():
    mpl = pytest.importorskip("matplotlib")
    mpl.use("Agg")
    mpl.rcParams["figure.max_open_warning"] = 0
    import lensforge.plot as P
    s = samples.achromat()
    P.layout(lf.layout(s))
    P.spot(lf.spot_diagram(s, 1))
    P.ray_fan(lf.ray_fan(s, 1))
    P.opd_fan(lf.opd_fan(s, 1))
    P.wavefront(lf.wavefront(s, 1))
    P.psf(lf.fft_psf(s, 0), log=True)
    P.mtf(lf.fft_mtf(s, 0))
    P.through_focus_mtf(lf.through_focus_mtf(s, 20, steps=3))
    P.mtf_vs_field(lf.mtf_vs_field(s, [20], n_fields=2))
    P.energy(lf.diffraction_energy(s, 0))
    P.field_curvature(lf.field_curvature(s, n_fields=3))
    P.grid_distortion(lf.grid_distortion(s, 5))
    P.lateral_color(lf.lateral_color(s, n_fields=3))
    P.longitudinal_aberration(lf.longitudinal_aberration(s, n_pupil=3))
    P.chromatic_focal_shift(lf.chromatic_focal_shift(s, 5))
    P.relative_illumination(lf.relative_illumination(s, n_fields=3, sampling=16))
    P.vignetting(lf.vignetting(s, n_fields=3, sampling=16))
    P.footprint(lf.footprint(s, 1))
    P.sag(lf.surface_sag(s.surfaces[1], 10), departure=True)
    P.seidel(lf.seidel(s))
    P.zernike(lf.zernike_coefficients(s, 1))
    P.interferogram(lf.interferogram(s, 0, n=32))
    P.polarization_pupil(lf.polarization_pupil_map(s, 1, n=7))
    import matplotlib.pyplot as plt
    plt.close("all")
