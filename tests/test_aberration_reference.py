"""Aberration coefficients, ray fans, OPD fans, spot diagrams and Zernike terms checked against known truth.

Two kinds of reference:

* Closed form: Welford's thin-lens Seidel sums, the exact ray and OPD fans of a single refracting
  sphere (traced by hand with Snell's law), and the exact fans and spots of a defocused ideal lens.
* An independent code: Optiland 0.6.3 on the Cooke triplet of tests/test_mtf_reference.py (the Zemax
  "Cooke 40 degree field" sample).  The numbers below were computed with Optiland (Aberrations, RayFan,
  OPDFan, SpotDiagram, ZernikeOPD); ``test_live_optiland_comparison`` recomputes them where Optiland is
  installed (pip install optiland).  See docs/aberration-validation.md.

Conventions that differ from Optiland (checked here rather than hidden):

* Optiland's Seidel sums have the opposite sign (lensforge follows Zemax/Welford: S1 > 0 for an
  under-corrected positive lens).
* TAST: lensforge reported TTFC - TSFC = S3/(n'u') until November 2026; it now follows Optiland's TAC and
  Zemax's TAST, S3/(2n'u'), so the tangential and sagittal foci are 2 TAST apart.
* OPD fans of non-primary wavelengths: lensforge centres the reference sphere on the primary-wavelength
  chief ray, Optiland on each wavelength's own chief ray, so off axis they differ by a pure tilt.
* Spot diagrams: both use 6 hexapolar rings but start each ring at a different angle, so the RMS radius
  agrees and the largest-ray (GEO) radius can differ slightly off axis.
"""

import math

import numpy as np
import pytest

import lensforge as lf
from lensforge.analysis.common import defocused
from lensforge.pupil import pupil_grid

from test_mtf_reference import cooke

FIELDS = [(0, 0), (0, 0.7), (0, 1)]
WAVES = (0.48, 0.55, 0.65)

# --- Optiland 0.6.3 reference values (Cooke triplet) -------------------------------------------------
# Seidel sums in Optiland's sign (opposite to lensforge's), per surface 1..6 and in total
OPTILAND_SEIDEL_PER_SURFACE = {'S1': [-0.0138546263, -0.0112561392, 0.0521152847, 0.0241349819, -0.00407998871, -0.0540195539], 'S2': [-0.0105910574, 0.0350108275, -0.0813889854, 0.0438738213, -0.0161319355, 0.030462216], 'S3': [-0.00809624849, -0.108896845, 0.12710603, 0.0797561067, -0.063784329, -0.0171779761], 'S4': [-0.0577273766, -0.00291625096, 0.0572677026, 0.0626901502, -0.015947909, -0.0690820333], 'S5': [-0.0503183396, 0.347780792, -0.287938388, 0.25894619, -0.315254627, 0.0486429608]}
OPTILAND_SEIDEL_TOTALS = [-0.00696004149, 0.00123488647, 0.00890673846, -0.0257157169, 0.0018585891]
OPTILAND_TRANSVERSE = {'TSC': -0.0348001949, 'CC': 0.00617443012, 'TAC': 0.0445336763, 'TPC': -0.128578538, 'DC': 0.00929294216, 'TAchC': -0.00763929615, 'TchC': -0.000944597914}
OPTILAND_RAY_FAN = {
    (0, 0): { 0.48: ([0.00208979082, -0.00611445501, 0.0, 0.00611445501, -0.00208979082], [0.00208979082, -0.00611445501, 0.0, 0.00611445501, -0.00208979082]), 0.55: ([0.00417383737, -0.00629685586, 0.0, 0.00629685586, -0.00417383737], [0.00417383737, -0.00629685586, 0.0, 0.00629685586, -0.00417383737]), 0.65: ([-8.58059598e-05, -0.00935603225, 0.0, 0.00935603225, 8.58059598e-05], [-8.58059598e-05, -0.00935603225, 0.0, 0.00935603225, 8.58059598e-05]) },
    (0, 0.7): { 0.48: ([-0.0235333183, -0.00691937749, -0.000148741038, 0.00776584639, 0.0395861713], [0.0194254079, 0.00740066599, 0.0, -0.00740066599, -0.0194254079]), 0.55: ([-0.0248360697, -0.00847466439, 0.0, 0.00947476083, 0.0407752171], [0.0213977881, 0.00717888298, 0.0, -0.00717888298, -0.0213977881]), 0.65: ([-0.0323814352, -0.0128945161, 7.68567171e-05, 0.0138484424, 0.0478003093], [0.0169459615, 0.00403652939, 0.0, -0.00403652939, -0.0169459615]) },
    (0, 1): { 0.48: ([-0.00483785701, 0.0186039176, -0.000165159792, -0.0188338938, 0.0133248347], [0.0153255049, 0.011365724, 0.0, -0.011365724, -0.0153255049]), 0.55: ([-0.0170766185, 0.0128335045, 0.0, -0.0135554907, 0.0225252014], [0.0169134963, 0.0110079417, 0.0, -0.0110079417, -0.0169134963]), 0.65: ([-0.034046206, 0.00483744818, 0.000234739069, -0.00590469688, 0.0366292919], [0.0120639103, 0.00771146275, 0.0, -0.00771146275, -0.0120639103]) },
}
OPTILAND_OPD_FAN = {
    (0.0, 0.0): { 0.48: ([-0.722314278, -0.53841029, -0.0796812696, -0.0796812696, -0.53841029, -0.722314278], [-0.722314278, -0.53841029, -0.0796812696, -0.0796812696, -0.53841029, -0.722314278]), 0.55: ([-0.59158881, -0.488165021, -0.0731719933, -0.0731719933, -0.488165021, -0.59158881], [-0.59158881, -0.488165021, -0.0731719933, -0.0731719933, -0.488165021, -0.59158881]), 0.65: ([-0.926550461, -0.587150745, -0.0822802856, -0.0822802856, -0.587150745, -0.926550461], [-0.926550461, -0.587150745, -0.0822802856, -0.0822802856, -0.587150745, -0.926550461]) },
    (0.0, 0.7): { 0.48: ([-1.56950293, -0.451560257, -0.0467924794, -0.0477232108, -0.509537269, -2.19255889], [1.72165532, 0.493495357, 0.0428478152, 0.0428478152, 0.493495357, 1.72165532]), 0.55: ([-1.60261767, -0.50029301, -0.0535724974, -0.054114879, -0.543795918, -2.116337], [1.53228001, 0.410497637, 0.0336170809, 0.0336170809, 0.410497637, 1.53228001]), 0.65: ([-1.96132616, -0.653669399, -0.0713588899, -0.0715134365, -0.682225691, -2.35802187], [0.870055929, 0.174006144, 0.00820899233, 0.00820899233, 0.174006144, 0.870055929]) },
    (0.0, 1.0): { 0.48: ([2.05707454, 1.26130077, 0.1666062, 0.168284437, 1.28101445, 1.86224772], [2.06177402, 0.792947588, 0.0853088814, 0.0853088814, 0.792947588, 2.06177402]), 0.55: ([0.895875141, 0.785116816, 0.111239706, 0.113742233, 0.831363266, 0.871031449], [1.80178238, 0.664341504, 0.0699555374, 0.0699555374, 0.664341504, 1.80178238]), 0.65: ([-0.301735728, 0.291962691, 0.0536233009, 0.0565914676, 0.354992722, -0.202372099], [1.08704541, 0.386430048, 0.03877215, 0.03877215, 0.386430048, 1.08704541]) },
}
OPTILAND_SPOT_RMS = {(0, 0): [0.0038566975, 0.00429454108, 0.00623197922], (0, 0.7): [0.0158647023, 0.0169215438, 0.0192461044], (0, 1): [0.0130800789, 0.0121101127, 0.0136648243]}
OPTILAND_SPOT_GEO = {(0, 0): [0.00611445501, 0.00629685586, 0.00935603225], (0, 0.7): [0.0395861713, 0.0407752171, 0.0478003093], (0, 1): [0.0187487643, 0.0225252014, 0.0366292919]}
OPTILAND_ZERNIKE_FRINGE = {
    (0, 0): [-0.486981, -1.89015e-13, 3.38165e-13, -0.279475, 1.37813e-15, 2.67974e-13, 8.0865e-14, -5.19475e-13, 0.191838, 1.7985e-13, -7.50986e-14, 1.50285e-13, -6.93673e-13, 3.11317e-14, 2.80885e-14, -0.0164953],
    (0, 0.7): [-0.0742349, -3.62444e-13, -0.125154, -0.0687498, 1.53995, -1.67518e-13, -1.58177e-13, -0.10303, -0.0119071, 5.66167e-13, 0.00346432, 0.156507, -3.909e-13, 8.22105e-14, -0.0286378, -0.0181614],
    (0, 1): [0.84216, -1.02958e-12, 0.145002, 0.658562, 0.202743, 9.36489e-13, 1.15185e-12, 0.0392503, -0.203454, -2.96514e-13, 0.174566, 0.257526, -4.5332e-13, 3.8039e-13, -0.0238312, -0.0206389],
}


@pytest.fixture(scope="module")
def lens():
    return cooke()


def _seidel_per_surface(r, key):
    return np.asarray(r["per_surface"][key])[1:7]


def test_seidel_sums_match_optiland(lens):
    r = lf.seidel(lens)
    tot = r["totals"]
    for k, ref in zip(("S1", "S2", "S3", "S4", "S5"), OPTILAND_SEIDEL_TOTALS):
        assert tot[k] == pytest.approx(-ref, rel=1e-7), k
        np.testing.assert_allclose(_seidel_per_surface(r, k), -np.asarray(OPTILAND_SEIDEL_PER_SURFACE[k]),
                                   rtol=1e-7, atol=1e-12, err_msg=k)
    t, o = r["transverse"], OPTILAND_TRANSVERSE
    for mine, theirs in (("TSPH", "TSC"), ("TSCO", "CC"), ("TAST", "TAC"), ("TPFC", "TPC"), ("TDIS", "DC"),
                         ("TAXC", "TAchC"), ("TLAC", "TchC")):
        assert t[mine] == pytest.approx(o[theirs], rel=1e-7), mine
    # Zemax's relations: the tangential and sagittal foci are 2 TAST apart
    assert t["TTFC"] - t["TSFC"] == pytest.approx(2 * t["TAST"], rel=1e-9)
    u = lf.ParaxialAnalysis(lens).marginal_ray[1][-1]
    assert r["longitudinal"]["LAST"] == pytest.approx(-t["TAST"] / u, rel=1e-9)
    assert t["TSFC"] == pytest.approx(o["TAC"] + o["TPC"], rel=1e-7)
    assert t["TTFC"] == pytest.approx(3 * o["TAC"] + o["TPC"], rel=1e-7)


@pytest.mark.parametrize("field", FIELDS)
def test_ray_fans_match_optiland(lens, field):
    f = lf.ray_fan(lens, field, list(WAVES), n=5)
    for i, w in enumerate(WAVES):
        ey, ex = OPTILAND_RAY_FAN[field][w]
        np.testing.assert_allclose(f["ey"][i], ey, atol=1e-9, err_msg=f"ey {w}")
        np.testing.assert_allclose(f["ex"][i], ex, atol=1e-9, err_msg=f"ex {w}")


@pytest.mark.parametrize("field", FIELDS)
def test_opd_fans_match_optiland(lens, field):
    f = lf.opd_fan(lens, field, list(WAVES), n=6)
    p = f["p"]
    for i, w in enumerate(WAVES):
        wy, wx = (np.asarray(v) for v in OPTILAND_OPD_FAN[field][w])
        np.testing.assert_allclose(f["wx"][i], wx, atol=1e-4, err_msg=f"wx {w}")
        if w == 0.55 or field == (0, 0):
            np.testing.assert_allclose(f["wy"][i], wy, atol=1e-4, err_msg=f"wy {w}")
        else:
            # reference sphere on the primary chief ray (lensforge) vs this wavelength's chief ray (Optiland):
            # the tangential fans differ by a tilt (plus a trace of focus from the shifted sphere centre)
            d = f["wy"][i] - wy
            res = d - np.polyval(np.polyfit(p, d, 1), p)
            assert np.abs(res).max() < 1e-3, (w, res)


@pytest.mark.parametrize("field", FIELDS)
def test_spot_radii_match_optiland(lens, field):
    for i, w in enumerate(WAVES):
        s = lf.spot_diagram(lens, field, [w], rings=6)
        assert s["n_rays"] == 127
        assert s["rms_radius"] == pytest.approx(OPTILAND_SPOT_RMS[field][i], rel=1e-6), w
        # GEO is the largest of the sampled rays: the rings start at another angle in Optiland
        tol = 1e-6 if field != (0, 1) else 0.01
        assert s["geo_radius"] == pytest.approx(OPTILAND_SPOT_GEO[field][i], rel=tol), w


@pytest.mark.parametrize("field", FIELDS)
def test_zernike_fringe_matches_optiland(lens, field):
    z = lf.zernike_coefficients(lens, field, 0.55, n_terms=16, kind="fringe", sampling=128)
    np.testing.assert_allclose(z["coefficients"], OPTILAND_ZERNIKE_FRINGE[field], atol=2e-3)


def test_live_optiland_comparison(lens):
    """Recompute the Optiland reference values (runs only where Optiland is installed)."""
    pytest.importorskip("optiland")
    from optiland import optic
    from optiland.aberrations import Aberrations
    from optiland.analysis import RayFan, SpotDiagram
    from optiland.wavefront import ZernikeOPD
    o = optic.Optic()
    o.add_surface(index=0, radius=np.inf, thickness=np.inf)
    for i, s in enumerate(lens.surfaces[1:-1], 1):
        mat = {"N-SK16": "N-SK16", "SCHOTT:F2": ("F2", "schott")}.get(s.material)
        kw = {"material": mat} if mat else {}
        o.add_surface(index=i, radius=1 / s.curvature, thickness=s.thickness, is_stop=i == 4, **kw)
    o.add_surface(index=len(lens.surfaces) - 1)
    o.set_aperture(aperture_type="EPD", value=10)
    o.set_field_type(field_type="angle")
    for y in (0, 14, 20):
        o.add_field(y=y)
    for w in WAVES:
        o.add_wavelength(value=w, is_primary=w == 0.55)
    S = np.asarray(Aberrations(o).seidels(), float).ravel()
    tot = lf.seidel(lens)["totals"]
    np.testing.assert_allclose([tot[k] for k in ("S1", "S2", "S3", "S4", "S5")], -S, rtol=1e-6)
    rf = RayFan(o, num_points=5)
    sd = SpotDiagram(o, num_rings=6)
    rms = sd.rms_spot_radius()
    for k, f in enumerate(FIELDS):
        mine = lf.ray_fan(lens, f, list(WAVES), n=5)
        for i, w in enumerate(WAVES):
            d = rf.data[str((float(f[0]), float(f[1])))][str(w)]
            np.testing.assert_allclose(mine["ey"][i], np.asarray(d["y"]), atol=1e-9)
            np.testing.assert_allclose(mine["ex"][i], np.asarray(d["x"]), atol=1e-9)
            assert lf.spot_diagram(lens, f, [w], rings=6)["rms_radius"] == pytest.approx(float(rms[k][i]), rel=1e-6)
        z = ZernikeOPD(o, f, 0.55, num_rings=32, zernike_type="fringe", num_terms=16)
        np.testing.assert_allclose(lf.zernike_coefficients(lens, f, 0.55, n_terms=16, sampling=128)["coefficients"],
                                   np.asarray(z.coeffs), atol=2e-3)


# --- closed form: thin lens (Welford, "Aberrations of Optical Systems", section 7.5) -----------------

def _thin_lens(B, object_distance, n=1.5168, vd=64.17, f=100.0, y=5.0):
    """Thin lens of shape factor B = (c1 + c2)/(c1 - c2), stop at the lens, EPD 2y."""
    s = lf.OpticalSystem()
    s.set_wavelengths([0.4861327, 0.5875618, 0.6562725], primary=1)
    glass = f"{n},{vd}"
    if object_distance is None:
        s.set_aperture("EPD", 2 * y)
        s.set_fields([0, 5])
    else:
        s.object.thickness = object_distance
        s.set_aperture("OBJECT_NA", math.sin(math.atan(y / object_distance)))
        s.set_fields([0, 5.0], "OBJECT_HEIGHT")
    d = 1 / (f * (n - 1))
    c1, c2 = (B + 1) * d / 2, (B - 1) * d / 2
    s.add_surface(radius=1 / c1 if c1 else 1e18, thickness=0.0, material=glass, stop=True)
    s.add_surface(radius=1 / c2 if c2 else 1e18, thickness=50)
    return s


@pytest.mark.parametrize("object_distance", [None, 300.0])
@pytest.mark.parametrize("B", [-1.0, 0.0, 0.714, 1.0, 2.0])
def test_thin_lens_seidel_matches_welford(B, object_distance):
    n, f, y = 1.5168, 100.0, 5.0
    K = 1 / f
    s = _thin_lens(B, object_distance)
    # paraxial marginal ray (u before, u' after the lens) and Lagrange invariant H = n (u ybar - ubar y),
    # with ybar = 0 at the stop
    if object_distance is None:
        u, ubar = 0.0, math.tan(math.radians(5))
    else:
        u, ubar = y / object_distance, -5.0 / object_distance
    up = u - y * K
    C = (u + up) / (u - up)
    H = -ubar * y
    S1 = y**4 * K**3 / 4 * ((n / (n - 1)) ** 2 + (n + 2) / (n * (n - 1) ** 2) * B**2
                            + 4 * (n + 1) / (n * (n - 1)) * B * C + (3 * n + 2) / n * C**2)
    S2 = -y**2 * K**2 * H / 2 * ((n + 1) / (n * (n - 1)) * B + (2 * n + 1) / n * C)
    t = lf.seidel(s)["totals"]
    assert t["S1"] == pytest.approx(S1, rel=1e-9)
    assert t["S2"] == pytest.approx(S2, rel=1e-9)
    assert t["S3"] == pytest.approx(H * H * K, rel=1e-9)
    assert t["S4"] == pytest.approx(H * H * K / n, rel=1e-9)
    assert t["S5"] == pytest.approx(0, abs=1e-15)
    assert t["CL"] == pytest.approx(y * y * K / 64.17, rel=1e-9)
    assert t["CT"] == pytest.approx(0, abs=1e-15)


def test_thin_lens_minimum_spherical_bending():
    """S1 is smallest at B = -2 (n^2 - 1) C / (n + 2) (= 0.740 for n = 1.5168 from infinity)."""
    n = 1.5168
    best = 2 * (n * n - 1) / (n + 2)
    bs = np.linspace(best - 0.3, best + 0.3, 61)
    s1 = [lf.seidel(_thin_lens(b, None))["totals"]["S1"] for b in bs]
    assert bs[int(np.argmin(s1))] == pytest.approx(best, abs=0.006)


# --- closed form: one refracting sphere, object at infinity, image plane at the paraxial focus -------

R1, N1, LAM = 50.0, 1.5, 0.5875618
LP = N1 * R1 / (N1 - 1)


def _single_surface(a):
    s = lf.OpticalSystem()
    s.set_wavelengths([LAM])
    s.set_aperture("EPD", 2 * a)
    s.set_fields([0])
    s.add_surface(radius=R1, thickness=LP, material=N1, stop=True)
    return s


def _single_surface_truth(h):
    """Exact transverse error at the paraxial focus and OPD (waves) of a ray at height h >= 0.

    Snell's law at the sphere; the ray crosses the axis at L' = R + R sin I' / sin(I - I').  The OPD is the
    optical path from the vertex plane to the reference sphere (centre at the paraxial focus, through the
    vertex = exit pupil), relative to the chief ray, in lensforge's sign: W = OPL(chief) - OPL(ray)."""
    h = np.asarray(h, float)
    I = np.arcsin(h / R1)
    Ip = np.arcsin(np.sin(I) / N1)
    U = I - Ip
    zs = R1 - np.sqrt(R1 * R1 - h * h)
    with np.errstate(invalid="ignore", divide="ignore"):
        L = np.where(h == 0, LP, R1 + R1 * np.sin(Ip) / np.sin(U))
    ey = -(LP - L) * np.tan(U)
    q = np.stack([h, zs - LP], -1)
    d = np.stack([-np.sin(U), np.cos(U)], -1)
    b = (q * d).sum(-1)
    c = (q * q).sum(-1) - LP * LP
    t = -b - np.sqrt(b * b - c)  # the root next to the surface
    opl = zs + N1 * t
    return ey, -opl / (LAM * 1e-3)


@pytest.mark.parametrize("a", [5.0, 10.0, 15.0])
def test_single_surface_exact_ray_and_opd_fans(a):
    s = _single_surface(a)
    p = np.linspace(-1, 1, 21)
    ey, w = _single_surface_truth(np.abs(p) * a)
    ey = np.sign(p) * ey
    f = lf.ray_fan(s, 0, n=21)
    np.testing.assert_allclose(f["ey"][0], ey, atol=1e-12)
    np.testing.assert_allclose(f["ex"][0], ey, atol=1e-12)
    o = lf.opd_fan(s, 0, n=21)
    np.testing.assert_allclose(o["wy"][0], w, atol=1e-7 * max(1.0, np.abs(w).max()))
    np.testing.assert_allclose(o["wx"][0], w, atol=1e-7 * max(1.0, np.abs(w).max()))


@pytest.mark.parametrize("a", [5.0, 15.0])
def test_single_surface_exact_spot(a):
    s = _single_surface(a)
    px, py = pupil_grid("hexapolar", 6)
    e, _ = _single_surface_truth(np.hypot(px, py) * a)
    sp = lf.spot_diagram(s, 0, rings=6)
    assert sp["rms_radius"] == pytest.approx(np.sqrt(np.mean(e * e)), rel=1e-10)
    assert sp["geo_radius"] == pytest.approx(np.abs(e).max(), rel=1e-10)
    # a dense uniform grid tends to the continuous RMS, sqrt(int_0^1 e(rho)^2 2 rho d rho)
    x, wt = np.polynomial.legendre.leggauss(80)
    rho = 0.5 * (x + 1)
    e2, _ = _single_surface_truth(rho * a)
    rms = math.sqrt(float(np.sum(0.5 * wt * e2 * e2 * 2 * rho)))
    assert lf.spot_diagram(s, 0, pattern="square", rings=300)["rms_radius"] == pytest.approx(rms, rel=3e-3)


def _fringe_radial(rho):
    r2 = rho * rho
    return np.stack([np.ones_like(rho), 2 * r2 - 1, 6 * r2**2 - 6 * r2 + 1, 20 * r2**3 - 30 * r2**2 + 12 * r2 - 1,
                     70 * r2**4 - 140 * r2**3 + 90 * r2**2 - 20 * r2 + 1], -1)


def test_single_surface_zernike_terms():
    """Fringe Z1, Z4, Z9, Z16, Z25 of the exact single-surface wavefront, fitted here on a fine grid."""
    a = 15.0
    s = _single_surface(a)
    v = (np.arange(400) + 0.5) / 200 - 1
    X, Y = np.meshgrid(v, v)
    rho = np.hypot(X, Y)[np.hypot(X, Y) <= 1]
    _, w = _single_surface_truth(rho * a)
    ref = np.linalg.lstsq(_fringe_radial(rho), w, rcond=None)[0]
    z = lf.zernike_coefficients(s, 0, LAM, n_terms=37, kind="fringe", sampling=128)["coefficients"]
    np.testing.assert_allclose(z[[0, 3, 8, 15, 24]], ref, atol=2e-3 * np.abs(ref).max())
    assert np.abs(np.delete(z, [0, 3, 8, 15, 24, 35, 36])).max() < 1e-6  # rotationally symmetric


# --- closed form: defocused ideal lens --------------------------------------------------------------

F0, D0, DZ = 100.0, 10.0, 1.0


def _defocused_ideal():
    s = lf.OpticalSystem()
    s.set_wavelengths([LAM])
    s.set_aperture("EPD", D0)
    s.set_fields([0, 10])
    s.add_surface(lf.Paraxial(focal_length=F0, thickness=F0, stop=True))
    return defocused(s, DZ)


@pytest.mark.parametrize("field", [0, 1])
def test_defocused_ideal_lens_ray_fans(field):
    """Every ray heads for the focus, so DZ behind it the error is -h DZ / f at any field."""
    f = lf.ray_fan(_defocused_ideal(), field, n=11)
    exact = -f["p"] * (D0 / 2) * DZ / F0
    np.testing.assert_allclose(f["ey"][0], exact, atol=1e-12)
    np.testing.assert_allclose(f["ex"][0], exact, atol=1e-12)


def test_defocused_ideal_lens_opd_fan():
    """On axis: W = |Q - F| - f, Q where the ray to the focus F meets the reference sphere centred DZ beyond F
    (through the exit pupil at the lens).  To first order this is DZ (1 - cos theta)."""
    o = lf.opd_fan(_defocused_ideal(), 0, n=11)
    h = o["p"] * D0 / 2
    P = np.stack([h, 0 * h], -1)
    Fp, Cp, Rr = np.array([0, F0]), np.array([0, F0 + DZ]), F0 + DZ
    d = (Fp - P) / np.linalg.norm(Fp - P, axis=-1)[:, None]
    q = P - Cp
    b = (q * d).sum(-1)
    t = -b - np.sqrt(b * b - ((q * q).sum(-1) - Rr * Rr))
    W = (np.linalg.norm(P + t[:, None] * d - Fp, axis=-1) - F0) / (LAM * 1e-3)
    np.testing.assert_allclose(o["wy"][0], W, atol=1e-8)
    np.testing.assert_allclose(o["wx"][0], W, atol=1e-8)
    th = np.arctan(h / F0)
    assert o["wy"][0][-1] == pytest.approx(DZ * (1 - math.cos(th[-1])) / (LAM * 1e-3), rel=0.02)


@pytest.mark.parametrize("field", [0, 1])
def test_defocused_ideal_lens_spot(field):
    """A uniform blur disc of radius b = (D/2) DZ / f: GEO = b; RMS = b / sqrt(2) for a uniform pupil, and on
    six hexapolar rings (6k rays at radius k/6, plus the centre) RMS = b sqrt(sum 6k (k/6)^2 / 127)."""
    t = _defocused_ideal()
    b = D0 / 2 * DZ / F0
    sp = lf.spot_diagram(t, field, rings=6)
    assert sp["geo_radius"] == pytest.approx(b, rel=1e-10)
    assert sp["rms_radius"] == pytest.approx(b * math.sqrt(sum(6 * k * (k / 6) ** 2 for k in range(1, 7)) / 127),
                                             rel=1e-10)
    assert lf.spot_diagram(t, field, pattern="square", rings=300)["rms_radius"] == pytest.approx(b / math.sqrt(2),
                                                                                                rel=1e-3)
