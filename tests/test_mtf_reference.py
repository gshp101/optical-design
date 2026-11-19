"""MTF checked against an independent code on a published prescription.

The lens is the Cooke triplet of the Optiland gallery (the Zemax "Cooke 40 degree
field" sample: EFL 50 mm, F/5, EPD 10, 0/14/20 deg, SK16 (N-SK16) and F2).  The
Optiland page publishes an on-axis Strehl of 0.3082 at 0.55 um.  The reference
MTF values below were computed with Optiland 0.6.3 (FFTMTF, num_rays=128, 0.55 um,
and GeometricMTF, num_rays=200); see docs/mtf-validation.md.
"""

import numpy as np
import pytest

import lensforge as lf

FREQ = [25, 50, 75, 100, 150, 200]
FIELDS = [(0, 0), (0, 0.7), (0, 1)]
# Optiland FFTMTF at 0.55 um: (tangential, sagittal) per field
OPTILAND_FFT = {
    (0, 0): ([0.819, 0.525, 0.242, 0.063, 0.007, 0.039], [0.819, 0.525, 0.242, 0.063, 0.007, 0.039]),
    (0, 0.7): ([0.306, 0.062, 0.024, 0.010, 0.009, 0.006], [0.445, 0.135, 0.093, 0.063, 0.022, 0.013]),
    (0, 1): ([0.442, 0.139, 0.141, 0.010, 0.016, 0.074], [0.397, 0.112, 0.140, 0.094, 0.030, 0.013]),
}
GFREQ = [10, 25, 50, 75, 100]
OPTILAND_GEOMETRIC = {
    (0, 0): ([0.948, 0.818, 0.527, 0.257, 0.092], [0.948, 0.818, 0.527, 0.257, 0.092]),
    (0, 0.7): ([0.742, 0.265, 0.054, 0.009, 0.006], [0.832, 0.370, 0.150, 0.071, 0.048]),
    (0, 1): ([0.863, 0.423, 0.122, 0.027, 0.046], [0.836, 0.361, 0.125, 0.137, 0.039]),
}


def cooke():
    s = lf.OpticalSystem("Cooke triplet (Optiland gallery)")
    s.set_aperture("EPD", 10)
    s.set_fields([0, 14, 20])
    s.set_wavelengths([0.48, 0.55, 0.65], primary=1)
    rows = [(22.01359, 3.25896, "N-SK16"), (-435.76044, 6.00755, None), (-22.21328, 0.99997, "SCHOTT:F2"),
            (20.29192, 4.75041, None), (79.68360, 2.95208, "N-SK16"), (-18.39533, 42.20778, None)]
    for i, (r, t, m) in enumerate(rows):
        s.add_surface(lf.Standard(radius=r, thickness=t, material=m, stop=i == 3))
    return s


@pytest.fixture(scope="module")
def lens():
    return cooke()


def test_published_efl_and_strehl(lens):
    assert lf.ParaxialAnalysis(lens).efl == pytest.approx(49.99978, abs=1e-3)
    assert lf.strehl(lens, 0, [0.55], pupil_n=128) == pytest.approx(0.3082, abs=0.003)


@pytest.mark.parametrize("field", FIELDS)
def test_fft_mtf_matches_optiland(lens, field):
    m = lf.fft_mtf(lens, field, [0.55], pupil_n=128, frequencies=FREQ)
    t, s = OPTILAND_FFT[field]
    assert np.abs(m["tangential"] - t).max() < 0.01
    assert np.abs(m["sagittal"] - s).max() < 0.01


@pytest.mark.parametrize("field", FIELDS)
def test_geometric_mtf_matches_optiland(lens, field):
    m = lf.geometric_mtf(lens, field, [0.55], frequencies=GFREQ, grid=200)
    t, s = OPTILAND_GEOMETRIC[field]
    assert np.abs(m["tangential"] - t).max() < 0.005
    assert np.abs(m["sagittal"] - s).max() < 0.005


def test_live_optiland_comparison(lens):
    """Runs only where Optiland is installed (pip install optiland)."""
    pytest.importorskip("optiland")
    from optiland import mtf as omtf, optic
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
    o.add_wavelength(value=0.55, is_primary=True)
    ref = omtf.FFTMTF(o, fields=FIELDS, wavelength=0.55, num_rays=128)
    for k, f in enumerate(FIELDS):
        m = lf.fft_mtf(lens, f, [0.55], pupil_n=128, frequencies=FREQ)
        t = np.interp(FREQ, np.asarray(ref.freq_tang[k]), np.asarray(ref.mtf[k][0]))
        s = np.interp(FREQ, np.asarray(ref.freq_sag[k]), np.asarray(ref.mtf[k][1]))
        assert np.abs(m["tangential"] - t).max() < 0.01
        assert np.abs(m["sagittal"] - s).max() < 0.01


def test_plot_axes_carry_lens_units():
    from matplotlib.figure import Figure
    from lensforge_qt.analyses import REGISTRY
    s = cooke()
    s.units = "in"
    for key, want in (("mtf", "cycles/in"), ("ray_fan", "(in)"), ("opd_fan", "(waves)")):
        spec = REGISTRY[key]
        opts = {st.name: st.default for st in spec.settings if not st.plot_only}
        if key == "mtf":
            opts["pupil_n"] = 16
        fig = Figure()
        spec.plot(fig, spec.compute(s, **opts), opts, s)
        text = " ".join(a.get_xlabel() + " " + a.get_title() for a in fig.axes)
        assert want in text, (key, text)
