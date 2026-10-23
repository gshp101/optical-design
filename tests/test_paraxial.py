import math

import numpy as np
import pytest

import lensforge as lf
from lensforge import samples


def thick_lens(R1, R2, t, n):
    phi1 = (n - 1) / R1
    phi2 = (1 - n) / R2
    phi = phi1 + phi2 - t / n * phi1 * phi2
    efl = 1 / phi
    bfl = efl * (1 - t / n * phi1)
    return efl, bfl


def make_lens(R1, R2, t, n, **kw):
    s = lf.OpticalSystem()
    s.set_aperture("EPD", 10)
    s.add_surface(radius=R1, thickness=t, material=n, stop=True)
    s.add_surface(radius=R2, thickness=50)
    return s


@pytest.mark.parametrize("R1,R2,t,n", [(50, -50, 5, 1.5), (30, 200, 8, 1.8), (-40, -20, 3, 1.6), (100, 1e18, 4, 1.5)])
def test_thick_lens_formulas(R1, R2, t, n):
    s = make_lens(R1, R2, t, n)
    p = s.paraxial()
    efl, bfl = thick_lens(R1, R2, t, n)
    assert p.efl == pytest.approx(efl, rel=1e-12)
    assert p.bfl == pytest.approx(bfl, rel=1e-12)


def test_concave_mirror():
    s = samples.parabolic_mirror(focal_length=250)
    p = s.paraxial()
    assert p.efl == pytest.approx(250)
    assert p.bfl == pytest.approx(-250)


def test_pupils_stop_behind_lens():
    # thin lens f=100, stop 50 behind -> entrance pupil is virtual image of stop
    s = lf.OpticalSystem()
    s.set_aperture("STOP_SIZE", 5)
    s.add_surface(lf.Paraxial(focal_length=100, thickness=50))
    s.add_surface(thickness=50, stop=True)
    p = s.paraxial()
    # stop at +50 seen through lens f=100: image at z=100 (virtual), magnification 2
    assert p.entrance_pupil_position == pytest.approx(100)
    assert p.entrance_pupil_radius == pytest.approx(10)
    assert p.exit_pupil_position == pytest.approx(0)  # stop is last surface
    assert p.efl == pytest.approx(100)


def test_finite_conjugate_magnification():
    s = lf.OpticalSystem()
    s.object.thickness = 200
    s.set_aperture("OBJECT_NA", 0.05)
    s.set_fields([0, 5], "OBJECT_HEIGHT")
    s.add_surface(lf.Paraxial(focal_length=100, thickness=200, stop=True))
    p = s.paraxial()
    assert p.image_distance == pytest.approx(200)
    assert p.magnification == pytest.approx(-1)
    assert p.paraxial_image_height == pytest.approx(-5)
    assert p.entrance_pupil_radius == pytest.approx(200 * math.tan(math.asin(0.05)))


def test_fnum_aperture_types():
    s = make_lens(50, -50, 5, 1.5)
    efl = s.paraxial().efl
    s.set_aperture("IMAGE_FNUM", 4)
    assert s.paraxial().epd == pytest.approx(efl / 4)
    s.set_aperture("WORKING_FNUM", 4)
    assert s.paraxial().working_fnum == pytest.approx(4)


def test_paraxial_image_height_angle_field():
    s = lf.OpticalSystem()
    s.set_aperture("EPD", 10)
    s.set_fields([0, 10])
    s.add_surface(lf.Paraxial(focal_length=100, thickness=100, stop=True))
    assert s.paraxial().paraxial_image_height == pytest.approx(100 * math.tan(math.radians(10)))
