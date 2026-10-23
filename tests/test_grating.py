"""Linear diffraction grating surface (DGRATING)."""

import math

import numpy as np
import pytest

import lensforge as lf


def grating_system(T=0.6, m=1, material=None, units="mm", wave=0.55):
    s = lf.OpticalSystem("grating", units=units)
    s.set_aperture("EPD", 2.0)
    s.set_wavelengths([wave])
    s.add_surface(lf.DiffractionGrating(lines_per_um=T, diffraction_order=m, thickness=10, material=material,
                                        stop=True))
    return s


@pytest.mark.parametrize("m", [-2, -1, 0, 1, 2])
def test_grating_equation_normal_incidence(m):
    s = grating_system(T=0.6, m=m)
    r = s.trace(0, 0, [0, 0.5, -1], [0, 0.3, 1])
    M = r.directions[-1][:, 1]
    assert np.allclose(M, m * 0.55 * 0.6, atol=1e-12)
    assert np.allclose(r.directions[-1][:, 0], 0, atol=1e-12)


def test_grating_equation_oblique_and_units():
    # 10 degree field, collimated: sin(theta_out) = sin(theta_in) + m lambda T, independent of lens units
    for units in ("mm", "m", "in"):
        s = grating_system(T=0.3, m=1, units=units)
        s.set_fields([0, 10])
        r = s.trace(0, 1, 0, 0)
        sin_out = r.directions[-1][0, 1]
        assert sin_out == pytest.approx(math.sin(math.radians(10)) + 0.55 * 0.3, abs=1e-12)


def test_grating_into_glass_and_dispersion():
    s = grating_system(T=0.5, m=1, material="N-BK7")
    for w in (0.48, 0.55, 0.65):
        r = s.trace(0, 0, 0, 0, wavelength=w)
        n = s.library.resolve("N-BK7").index(w)
        assert n * r.directions[-1][0, 1] == pytest.approx(w * 0.5, abs=1e-12)


def test_reflective_grating_littrow():
    # Littrow: the diffracted ray returns along the incident direction when 2 sin(theta) = m lambda T
    lam, T = 0.6, 1.2
    theta = math.degrees(math.asin(lam * T / 2))
    s = lf.OpticalSystem("littrow")
    s.set_aperture("EPD", 2.0)
    s.set_wavelengths([lam])
    s.set_fields([0, theta])
    s.add_surface(lf.DiffractionGrating(lines_per_um=T, diffraction_order=-1, thickness=-10, material="MIRROR",
                                        stop=True))
    r = s.trace(0, 1, 0, 0)
    d_in, d_out = r.directions[0][0], r.directions[-1][0]
    assert np.allclose(d_out, -d_in, atol=1e-12)


def test_evanescent_order_fails():
    s = grating_system(T=2.0, m=1, wave=0.6)  # m lambda T = 1.2 > 1
    r = s.trace(0, 0, 0, 0)
    assert not r.valid[0]


def test_grating_serialisation_and_zmx():
    s = grating_system(T=0.75, m=-1)
    s2 = lf.io.loads(lf.io.dumps(s))
    g = s2.surfaces[1]
    assert g.kind == "DGRATING" and g.lines_per_um == 0.75 and g.diffraction_order == -1
    zmx = ("UNIT MM\nENPD 2\nWAVM 1 0.55 1\nSURF 0\n  DISZ INFINITY\nSURF 1\n  TYPE DGRATING\n  STOP\n"
           "  PARM 1 0.6\n  PARM 2 1\n  DISZ 10\nSURF 2\n")
    z = lf.load_zmx(zmx)
    assert z.surfaces[1].kind == "DGRATING" and z.surfaces[1].lines_per_um == 0.6
    r = z.trace(0, 0, 0, 0)
    assert r.directions[-1][0, 1] == pytest.approx(0.55 * 0.6)
