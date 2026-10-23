"""Tests for lensforge.optimize: variables, solves, operands, merit functions,
damped least squares, global search, glass substitution and tolerancing."""

import math

import numpy as np
import pytest

import lensforge as lf
from lensforge import optimize as opt
from lensforge.optimize.tolerance import PerturbedMaterial, Tolerance, elements, perturbed_system
from lensforge.raytrace import trace_rays

D_LINE = 0.5875618


def mono_lens(R1=100.0, R2=-100.0, t=1.0, epd=10.0):
    s = lf.OpticalSystem("mono")
    s.set_aperture("EPD", epd)
    s.set_fields([0.0])
    s.set_wavelengths([D_LINE])
    s.add_surface(radius=R1, thickness=t, material="N-BK7", stop=True)
    s.add_surface(radius=R2, thickness=95.0)
    return s


def bk7_doublet():
    """Achromat geometry with crown glass in both elements (no colour correction)."""
    s = lf.samples.achromat()
    s.surfaces[2].material = "N-BK7"
    return s


# ---------------------------------------------------------------------------
# Variables
# ---------------------------------------------------------------------------

def test_variable_radius_is_varied_as_curvature():
    s = lf.samples.achromat()
    v = opt.set_variable(s, 1, "radius", min=50, max=100)
    assert v.param == "curvature"
    assert v.min == pytest.approx(0.01) and v.max == pytest.approx(0.02)
    v.set(s, 0.0125)
    assert s.surfaces[1].radius == pytest.approx(80.0)
    assert opt.get_param(s, 1, "radius") == pytest.approx(80.0)


def test_glass_variable_converts_to_equivalent_model_glass():
    s = lf.samples.achromat()
    n_before = s.material(2).index(D_LINE)
    v = opt.set_variable(s, 2, "glass.vd")
    assert isinstance(s.material(2), lf.ModelGlass)
    assert s.material(2).index(D_LINE) == pytest.approx(n_before, abs=1e-12)
    assert (v.min, v.max) == (20.0, 90.0)
    v.set(s, 30.0)
    assert s.material(2).vd == pytest.approx(30.0, rel=1e-9)
    assert s.material(2).nd == pytest.approx(n_before, abs=1e-12)


def test_coefficient_variable_extends_list():
    s = lf.OpticalSystem()
    s.add_surface(lf.EvenAsphere(radius=50, coefficients=[], thickness=5, material="N-BK7"))
    s.add_surface(radius=-50, thickness=40)
    opt.set_param(s, 1, "coefficients[1]", 1e-7)
    assert s.surfaces[1].coefficients == [0.0, 1e-7]
    assert opt.get_param(s, 1, "coefficients[3]") == 0.0


# ---------------------------------------------------------------------------
# Solves
# ---------------------------------------------------------------------------

def test_marginal_ray_height_solve_matches_paraxial_focus():
    s = lf.samples.achromat()
    s.surfaces[3].thickness = 10.0
    opt.set_solve(s, opt.MarginalRayHeight(3))
    assert s.surfaces[3].thickness == pytest.approx(s.paraxial().image_distance, rel=1e-12)
    ym, _ = s.paraxial().marginal_ray
    # height on an intermediate surface
    opt.set_solve(s, opt.MarginalRayHeight(1, height=9.0))
    assert s.paraxial().marginal_ray[0][1] == pytest.approx(9.0, abs=1e-10)


def test_real_marginal_ray_height_solve():
    s = lf.samples.singlet()
    opt.set_solve(s, opt.MarginalRayHeight(2, pupil_zone=0.7))
    r = trace_rays(s, 0, 0, 0, 0.7)
    assert abs(r.y[0]) < 1e-9
    assert s.surfaces[2].thickness < s.paraxial().image_distance  # undercorrected: zonal focus is closer


def test_fnumber_and_angle_solves():
    s = lf.samples.achromat()
    opt.set_solve(s, opt.FNumber(3, 4.0))
    assert s.paraxial().working_fnum == pytest.approx(4.0, rel=1e-10)
    s2 = lf.samples.achromat()
    opt.set_solve(s2, opt.MarginalRayAngle(3, -0.1))
    _, nu = s2.paraxial().marginal_ray
    assert nu[-1] == pytest.approx(-0.1, rel=1e-10)
    s3 = lf.samples.achromat()
    s3.surfaces[1].stop = False
    s3.insert(1, lf.Standard(thickness=20.0, stop=True))
    opt.set_solve(s3, opt.ChiefRayAngle(4, 0.0))  # image-space telecentric
    _, nuc = s3.paraxial().chief_ray
    assert abs(nuc[-1]) < 1e-12


def test_pickup_position_edge_and_concentric_solves():
    s = lf.samples.achromat()
    opt.set_solve(s, opt.Pickup(3, "radius", 1, scale=-2.0))
    assert s.surfaces[3].radius == pytest.approx(-2 * 62.75)
    opt.set_solve(s, opt.Pickup(2, "material", 1))
    assert s.surfaces[2].material == "N-BAF10"
    opt.set_solve(s, opt.Position(3, from_surface=1, length=80.0))
    assert sum(x.thickness for x in s.surfaces[1:4]) == pytest.approx(80.0)
    s.surfaces[1].semi_diameter = s.surfaces[2].semi_diameter = 11.0
    opt.set_solve(s, opt.EdgeThickness(1, value=1.5))
    mf = opt.MeritFunction()
    mf.add("ETVA", surf=1)
    assert mf.evaluate(s).scalars[0] == pytest.approx(1.5, abs=1e-12)
    opt.set_solve(s, opt.Concentric(3, center_surface=1))
    assert s.surfaces[3].radius == pytest.approx(-(s.surfaces[1].thickness + s.surfaces[2].thickness))


# ---------------------------------------------------------------------------
# Operands and merit functions
# ---------------------------------------------------------------------------

def test_operands_agree_with_direct_calculations():
    s = lf.samples.achromat()
    mf = opt.MeritFunction()
    mf.add("EFFL")
    mf.add("REAY", surf=2, hy=1, py=1)
    mf.add("TRAY", hy=1, py=1, wave=0)
    mf.add("OPDC", py=1)
    mf.add("PARY", surf=2)
    mf.add("CONS", value=2.0)
    mf.add("PROD", a=0, b=5)
    mf.add("DIFF", a=6, b=0)
    mf.add("INDX", surf=1)
    ev = mf.evaluate(s)
    v = ev.scalars
    assert v[0] == pytest.approx(s.paraxial().efl, rel=1e-12)
    assert v[1] == pytest.approx(trace_rays(s, 0, 1, 0, 1).positions[2, 0, 1], rel=1e-12)
    fan = lf.ray_fan(s, 2, wavelengths=[0], n=3)
    assert v[2] == pytest.approx(fan["ey"][0][-1], rel=1e-9)
    assert v[3] == pytest.approx(lf.analysis.fans.opd(s, 0, 0, 0, 1)[0], rel=1e-9)
    assert v[4] == pytest.approx(s.paraxial().marginal_ray[0][1], rel=1e-12)
    assert v[6] == pytest.approx(2 * v[0]) and v[7] == pytest.approx(v[0])
    assert v[8] == pytest.approx(s.material(1).index(s.primary))
    assert "Merit function" in mf.table(s)
    assert len(opt.operand_help().splitlines()) == len(opt.OPERAND_INFO) > 70


def test_bounds_and_merit_definition():
    s = lf.samples.achromat()
    mf = opt.MeritFunction()
    mf.add("CTGT", 3.0, 1.0, surf=1)       # satisfied: 4 > 3
    mf.add("CTLT", 3.0, 1.0, surf=1)       # violated by 1
    mf.add("EFFL", 100.0, 3.0)
    mf.add("EFFL", 0.0, 0.0)               # display only
    efl = s.paraxial().efl
    expect = math.sqrt((1.0 * 1.0 + 3.0 * (efl - 100) ** 2) / (1 + 1 + 3))
    assert mf.value(s) == pytest.approx(expect, rel=1e-12)
    ev = mf.evaluate(s)
    assert ev.contributions[0] == 0 and ev.contributions.sum() == pytest.approx(1.0)


def test_gaussian_quadrature_is_exact_for_polynomials():
    px, py, w = opt.gaussian_quadrature(3, 6)
    assert w.sum() == pytest.approx(1.0)
    r2 = px**2 + py**2
    # pupil averages of r^2, r^4, r^8 and y^2 over the unit disk
    assert np.sum(w * r2) == pytest.approx(1 / 2)
    assert np.sum(w * r2**2) == pytest.approx(1 / 3)
    assert np.sum(w * r2**4) == pytest.approx(1 / 5)
    assert np.sum(w * py**2) == pytest.approx(1 / 4)
    hx, hy, hw = opt.gaussian_quadrature(3, 6, symmetric=True)
    assert np.all(hx >= 0) and np.sum(hw * hy**2) == pytest.approx(1 / 4)


def test_default_spot_merit_equals_rms_spot():
    """Default RMS-spot merit = sqrt(field-weighted mean of squared RMS spot radii),
    checked against a fine equal-area pupil sampling."""
    s = lf.samples.achromat()
    mf = opt.default_merit(s, "spot", rings=4, arms=8)
    n = 60
    r = np.sqrt((np.arange(n) + 0.5) / n)
    th = (np.arange(4 * n) + 0.5) * 2 * np.pi / (4 * n)
    R, T = np.meshgrid(r, th)
    px, py = (R * np.cos(T)).ravel(), (R * np.sin(T)).ravel()
    ms = []
    for k in range(3):
        hx, hy = s.normalized_field(k)
        xs, ys = [], []
        for w in s.wavelengths:
            t = trace_rays(s, hx, hy, px, py, wavelength=w.value)
            xs.append(t.x)
            ys.append(t.y)
        X, Y = np.concatenate(xs), np.concatenate(ys)
        ms.append(np.mean((X - X.mean()) ** 2 + (Y - Y.mean()) ** 2))
    assert mf.value(s) == pytest.approx(math.sqrt(np.mean(ms)), rel=2e-3)
    # symmetric half-pupil sampling gives the same answer as the full pupil
    full = opt.default_merit(s, "spot", rings=4, arms=8, symmetric=False)
    assert full.value(s) == pytest.approx(mf.value(s), rel=1e-6)


def test_default_wavefront_merit_matches_rms_wavefront():
    s = lf.samples.singlet()
    for k in range(3):
        mf = opt.default_merit(s, "wavefront", rings=6, arms=12, fields=[k], wavelengths=[1])
        assert mf.value(s) == pytest.approx(lf.metrics.rms_wavefront(s, k, sampling=128), rel=1e-2)


def test_boundary_rows_and_thickness_limits():
    s = lf.samples.achromat()
    mf = opt.default_merit(s, "spot", glass_min=3.0, glass_edge=1.0, air_min=0.5)
    types = [r.type for r in mf]
    assert {"MNCG", "MNEG", "MNCA"} <= set(types)
    ev = mf.evaluate(s)
    mncg = types.index("MNCG")
    assert ev.scalars[mncg] == pytest.approx(2.5)        # thinnest glass (N-SF6 element)
    assert ev.contributions[mncg] > 0                    # 2.5 < 3 is penalised


# ---------------------------------------------------------------------------
# Damped least squares
# ---------------------------------------------------------------------------

def test_dls_finds_minimum_spherical_bending():
    """Thin-lens theory: minimum spherical aberration for an object at infinity
    has shape factor q = 2 (n^2 - 1) / (n + 2)."""
    s = mono_lens()
    opt.set_variable(s, 1, "curvature")
    opt.set_solve(s, opt.FNumber(2, 10.0))          # keeps f = 100 mm
    opt.set_solve(s, opt.MarginalRayHeight(2))
    mf = opt.default_merit(s, "wavefront", rings=4)
    res = opt.optimize(s, mf)
    assert res.merit < 0.7 * res.initial_merit
    R1, R2 = s.surfaces[1].radius, s.surfaces[2].radius
    n = s.material(1).index(D_LINE)
    q = (R2 + R1) / (R2 - R1)
    assert q == pytest.approx(2 * (n * n - 1) / (n + 2), rel=0.02)
    assert s.paraxial().efl == pytest.approx(100.0, rel=1e-9)


def test_dls_hard_constraint_and_bounds():
    s = lf.samples.achromat()
    for i in (1, 2, 3):
        opt.set_variable(s, i, "curvature")
    opt.set_variable(s, 1, "curvature", max=0.0175)          # R1 >= 57.1
    opt.set_solve(s, opt.MarginalRayHeight(3))
    mf = opt.default_merit(s, "spot")
    mf.add("EFFL", 90.0, -1)                                  # Lagrange constraint
    start = opt.merit_value(s, mf)
    res = opt.optimize(s, mf)
    assert s.paraxial().efl == pytest.approx(90.0, abs=1e-7)
    assert s.surfaces[1].curvature <= 0.0175 + 1e-15
    assert res.merit <= start
    assert res.constraint_error < 1e-8
    assert res.history == sorted(res.history, reverse=True)


def test_dls_soft_target():
    s = lf.samples.singlet()
    opt.set_variable(s, 2, "curvature")
    mf = opt.MeritFunction()
    mf.add("EFFL", 80.0, 1.0)
    opt.optimize(s, mf)
    assert s.paraxial().efl == pytest.approx(80.0, rel=1e-6)


def test_model_glass_variable_reduces_axial_colour():
    s = lf.samples.achromat()
    s.surfaces[2].material = "1.80518,45"        # flint index, crown-like dispersion
    for i in (1, 2, 3):
        opt.set_variable(s, i, "curvature")
    opt.set_variable(s, 2, "glass.vd")
    opt.set_solve(s, opt.MarginalRayHeight(3))
    mf = opt.default_merit(s, "spot")
    mf.add("EFFL", 100.0, -1)
    before = abs(lf.metrics.axial_color(s))
    opt.optimize(s, mf)
    assert abs(lf.metrics.axial_color(s)) < 0.5 * before
    assert 20.0 <= s.material(2).vd < 45.0


def test_ray_failure_is_rejected_not_crashing():
    s = lf.samples.singlet()
    opt.set_variable(s, 1, "curvature", max=0.2)
    mf = opt.default_merit(s, "spot")
    res = opt.optimize(s, mf, cycles=5)
    assert math.isfinite(res.merit)


# ---------------------------------------------------------------------------
# Global optimisation and glass substitution
# ---------------------------------------------------------------------------

def _doublet_problem(bounds=False):
    s = bk7_doublet()
    kw = dict(min=-0.05, max=0.05) if bounds else {}
    for i in (1, 2, 3):
        opt.set_variable(s, i, "curvature", **kw)
    opt.set_solve(s, opt.MarginalRayHeight(3))
    mf = opt.default_merit(s, "spot")
    mf.add("EFFL", 100.0, -1)
    return s, mf


def test_glass_substitution_picks_a_flint():
    s, mf = _doublet_problem()
    local = opt.optimize(s, mf).merit
    axcl = abs(lf.metrics.axial_color(s))
    res = opt.glass_substitution(s, mf, surfaces=[2], candidates=["N-BK7", "N-K5", "F2", "N-SF6"], cycles=10)
    assert res.choices[2] in ("F2", "N-SF6")
    assert res.merit < 0.35 * local
    assert abs(lf.metrics.axial_color(s)) < 0.2 * axcl
    assert opt.merit_value(s, mf) == pytest.approx(res.merit, rel=1e-9)


def test_nearest_glasses_and_snap():
    lib = lf.shared_library()
    near = opt.nearest_glasses((1.5168, 64.17), lib, n=3)
    assert near[0][0].endswith("N-BK7") and near[0][1] < 0.01  # catalog nd/vd vs computed
    s = lf.samples.achromat()
    opt.set_variable(s, 2, "glass.nd")
    s.surfaces[2].material = lf.ModelGlass(1.7283, 28.5)
    out = opt.snap_to_catalog(s)
    assert out[2].endswith("N-SF10")
    assert not any(v.param.startswith("glass") for v in s.variables)


def test_hammer_never_worse_and_reproducible():
    s, mf = _doublet_problem()
    s.surfaces[2].material = "F2"
    s2 = s.copy()
    r1 = opt.hammer(s, mf, trials=4, cycles=6, seed=3, glasses={2: ["F2", "N-SF6"]})
    r2 = opt.hammer(s2, mf, trials=4, cycles=6, seed=3, glasses={2: ["F2", "N-SF6"]})
    assert r1.merit == pytest.approx(r2.merit, rel=1e-12)
    assert r1.history == sorted(r1.history, reverse=True)
    assert opt.merit_value(s, mf) == pytest.approx(r1.merit, rel=1e-9)


def test_global_search_returns_sorted_designs_within_bounds():
    s, mf = _doublet_problem(bounds=True)
    s.surfaces[2].material = "N-SF6"
    res = opt.global_search(s, mf, starts=4, keep=3, cycles=10, seed=1)
    ms = [m for m, _ in res.designs]
    assert ms == sorted(ms) and res.merit == ms[0]
    for _, d in res.designs:
        for i in (1, 2, 3):
            assert -0.05 - 1e-12 <= d.surfaces[i].curvature <= 0.05 + 1e-12
    assert opt.merit_value(s, mf) == pytest.approx(res.merit, rel=1e-9)


# ---------------------------------------------------------------------------
# Tolerancing
# ---------------------------------------------------------------------------

def test_coordinate_return_is_exact():
    s = lf.samples.achromat()
    p = perturbed_system(s, [(Tolerance("TETX", 1, -1, 1, surface2=3), 0.5),
                             (Tolerance("TEDY", 1, -1, 1, surface2=3), 0.1),
                             (Tolerance("TSTY", 2, -1, 1), 0.3), (Tolerance("TSDX", 2, -1, 1), 0.05)])
    assert p.num_surfaces == s.num_surfaces + 4
    R, O = p.surface_frames()[-1]
    R0, O0 = s.surface_frames()[-1]
    assert np.allclose(R, R0, atol=1e-14) and np.allclose(O, O0, atol=1e-12)
    z = perturbed_system(s, [(Tolerance("TETX", 1, -1, 1, surface2=3), 0.0)])
    assert lf.metrics.rms_spot(z, 2) == lf.metrics.rms_spot(s, 2)


def test_element_decenter_moves_the_image():
    s = lf.samples.singlet()
    s.set_fields([0.0])
    p = perturbed_system(s, [(Tolerance("TEDY", 1, -1, 1, surface2=2), 0.1)])
    c = lf.spot_diagram(p, 0)["centroid"]
    assert c[1] == pytest.approx(0.1, rel=0.03)
    q = perturbed_system(s, [(Tolerance("TSDY", 1, -1, 1), 0.1)])   # one surface: a wedge
    assert abs(lf.spot_diagram(q, 0)["centroid"][1]) > 1e-3


def test_material_and_radius_perturbations():
    base = lf.shared_library().resolve("N-BK7")
    m = PerturbedMaterial(base, 0.001, -0.5)
    assert m.nd == pytest.approx(base.nd + 0.001, abs=1e-12)
    assert m.vd == pytest.approx(base.vd - 0.5, rel=1e-9)
    s = lf.samples.achromat()
    p = perturbed_system(s, [(Tolerance("TRAD", 1, -1, 1), 0.5), (Tolerance("TIND", 2, -1, 1), 0.002),
                             (Tolerance("TTHI", 1, -1, 1, adjust=2), 0.1)])
    assert p.surfaces[1].radius == pytest.approx(63.25)
    assert p.material(2).nd == pytest.approx(s.material(2).nd + 0.002, abs=1e-12)
    assert p.surfaces[1].thickness == pytest.approx(4.1) and p.surfaces[2].thickness == pytest.approx(2.4)
    f = perturbed_system(s, [(Tolerance("TFRN", 1, -1, 1), 2.0)])
    r = lf.optimize.operands.EvalContext(s).semi_diameters()[1]
    dsag = (f.surfaces[1].sag(np.array([r]), np.array([0.0])) - s.surfaces[1].sag(np.array([r]), np.array([0.0])))[0]
    assert dsag == pytest.approx(2.0 * 0.6328e-3 / 2, rel=0.02)    # 2 fringes = 2 half-waves of sag


def test_default_tolerances_and_elements():
    s = lf.samples.achromat()
    assert elements(s) == [(1, 3)]
    tols = opt.default_tolerances(s)
    kinds = {t.type for t in tols}
    assert {"TFRN", "TTHI", "TSDX", "TSTY", "TEDX", "TETY", "TIND", "TABB"} <= kinds
    assert not any(t.type == "TTHI" and t.surface == 3 for t in tols)   # image distance is the compensator


def test_focus_compensation_absorbs_thickness_error():
    s = lf.samples.achromat()
    tol = Tolerance("TTHI", 1, -0.5, 0.5)
    comp = opt.sensitivity_analysis(s, [tol], compensators="focus")
    none = opt.sensitivity_analysis(s, [tol], compensators=None)
    assert comp["rows"][0]["change_max"] < 0.3 * none["rows"][0]["change_max"]
    assert none["estimated"] > none["nominal"]


def test_inverse_sensitivity_hits_allowed_change():
    s = lf.samples.achromat()
    tol = Tolerance("TSDY", 1, -0.05, 0.05)
    new = opt.inverse_sensitivity(s, [tol], max_change=2e-4, compensators=None, iterations=14)[0]
    assert 0.05 < new.max < 0.5   # (a -y decentre partly cancels the off-axis coma, so new.min is open)
    base = opt.sensitivity_analysis(s, [Tolerance("TSDY", 1, new.min, new.max)], compensators=None)
    assert base["rows"][0]["change_max"] == pytest.approx(2e-4, rel=0.02)


def test_monte_carlo_statistics():
    s = lf.samples.achromat()
    tols = opt.default_tolerances(s)
    a = opt.monte_carlo(s, tols, trials=8, compensators="paraxial_focus", seed=7)
    b = opt.monte_carlo(s, tols, trials=8, compensators="paraxial_focus", seed=7)
    assert np.array_equal(a.values, b.values)
    lo = np.array([t.min for t in tols])
    hi = np.array([t.max for t in tols])
    assert np.all(a.samples >= lo - 1e-15) and np.all(a.samples <= hi + 1e-15)
    assert np.all(np.isfinite(a.values))
    assert a.percentile(10) <= a.percentile(50) <= a.percentile(90)
    assert 0.0 <= a.yield_fraction(a.percentile(50)) <= 1.0
    assert a.worst is not None and "Monte Carlo" in a.summary()


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def test_variables_solves_and_merit_round_trip_json():
    s = lf.samples.achromat()
    opt.set_variable(s, 1, "curvature", min=0.0)
    opt.set_variable(s, 2, "glass.vd")
    opt.set_solve(s, opt.MarginalRayHeight(3))
    opt.set_solve(s, opt.Pickup(2, "thickness", 1, 0.5))
    s.merit_function = opt.default_merit(s, "spot")
    s.merit_function.add("EFFL", 100.0, -1)
    r = lf.io.jsonio.loads(lf.io.jsonio.dumps(s))
    assert [(v.surface, v.param, v.min) for v in r.variables] == [(1, "curvature", 0.0), (2, "glass.vd", 20.0)]
    assert [type(x).__name__ for x in r.solves] == ["MarginalRayHeight", "Pickup"]
    assert r.merit_function.value(r) == pytest.approx(s.merit_function.value(s), rel=1e-12)
