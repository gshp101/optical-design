"""Scaling, reversing and inserting lens prescriptions (lensforge.compose)."""

import math

import numpy as np
import pytest

import lensforge as lf
from lensforge import surfaces as S
from lensforge.compose import lens_surfaces, reverse_surfaces, scale_surface


def _efl(system):
    return system.paraxial().efl


@pytest.mark.parametrize("surface", [
    S.Standard(radius=40, conic=-0.5, thickness=3),
    S.EvenAsphere(radius=30, conic=-1, coefficients=[1e-4, 2e-6, -3e-9]),
    S.OddAsphere(radius=-50, coefficients=[1e-3, 2e-4, 3e-6, -1e-7]),
    S.Toroidal(radius=25, radius_x=60, coefficients=[1e-4, 1e-6]),
    S.XYPolynomial(radius=80, terms=[[2, 0, 0.01], [1, 2, -0.002], [0, 3, 0.004]], norm_radius=10),
])
def test_scaled_sag_is_scaled_shape(surface):
    k = 2.5
    s2 = scale_surface(surface, k)
    x, y = np.meshgrid(np.linspace(-3, 3, 7), np.linspace(-2, 4, 7))
    assert np.allclose(s2.sag(k * x, k * y), k * surface.sag(x, y), rtol=1e-10, atol=1e-12)


def test_scale_lengths_apertures_and_phase():
    s = S.BinaryPhase(radius=100, coefficients=[-50, 3], norm_radius=5, thickness=4, semi_diameter=6,
                      aperture=S.CircularAperture(5, 1, dx=0.5))
    s2 = scale_surface(s, 3)
    assert (s2.thickness, s2.semi_diameter, s2.radius) == pytest.approx((12, 18, 300))
    assert (s2.aperture.r_max, s2.aperture.r_min, s2.aperture.dx) == pytest.approx((15, 3, 1.5))
    x, y = np.array([0.7, 1.9]), np.array([-0.4, 2.2])
    assert np.allclose(s2.phase(3 * x, 3 * y, 5e-4)[0], 3 * s.phase(x, y, 5e-4)[0])
    g = scale_surface(S.DiffractionGrating(lines_per_um=0.6), 2)
    assert g.lines_per_um == pytest.approx(0.3)
    cb = scale_surface(S.CoordinateBreak(decenter_x=1, decenter_y=2, tilt_x=5), 2)
    assert (cb.decenter_x, cb.decenter_y, cb.tilt_x) == (2, 4, 5)
    assert math.isinf(scale_surface(S.Standard(thickness=math.inf), 2).thickness)
    with pytest.raises(ValueError):
        scale_surface(s, 0)


def test_scaled_lens_scales_focal_length():
    a = lf.samples.achromat()
    b = lf.OpticalSystem("b")
    b.set_aperture("EPD", 2 * a.aperture_value)
    rng = lf.insert_lens(b, a, scale=2.0, keep_stop=True)
    assert list(rng) == [1, 2, 3]
    assert _efl(b) == pytest.approx(2 * _efl(a), rel=1e-12)
    assert b.surfaces[1].stop


def test_reverse_achromat():
    a = lf.samples.achromat()
    rev = lens_surfaces(a, reverse=True)
    assert [s.material for s in rev] == [a.surfaces[2].material, a.surfaces[1].material, None]
    assert [s.radius for s in rev] == pytest.approx([-a.surfaces[3].radius, -a.surfaces[2].radius,
                                                     -a.surfaces[1].radius])
    assert [s.thickness for s in rev] == pytest.approx([a.surfaces[2].thickness, a.surfaces[1].thickness,
                                                        a.surfaces[3].thickness])
    b = lf.OpticalSystem("b")
    b.set_aperture("EPD", a.aperture_value)
    lf.insert_lens(b, a, reverse=True)
    assert _efl(b) == pytest.approx(_efl(a), rel=1e-12)  # a thick lens has the same EFL both ways round
    assert b.paraxial().bfl != pytest.approx(a.paraxial().bfl)
    assert not any(s.stop for s in b.surfaces[1:-1]) and b.stop_index == 1


def _tilted_system():
    sys = lf.OpticalSystem("tilted")
    sys.add_surface(radius=40, thickness=5, material="N-BK7", stop=True)
    sys.add_surface(S.CoordinateBreak(decenter_x=1.2, decenter_y=-0.7, tilt_x=5, tilt_y=-3, tilt_z=10, thickness=2))
    sys.add_surface(S.EvenAsphere(radius=-60, coefficients=[1e-5], thickness=3, material="N-SF6",
                                  aperture=S.CircularAperture(8, dx=0.3)))
    sys.add_surface(S.CoordinateBreak(decenter_x=-0.4, decenter_y=0.9, tilt_x=-7, tilt_y=4, tilt_z=-20, order=1,
                                      thickness=4))
    sys.add_surface(S.XYPolynomial(radius=-100, terms=[[1, 2, 1e-3], [2, 1, -2e-3]], norm_radius=5, thickness=30))
    return sys


def test_reverse_places_every_surface_where_the_flipped_original_is():
    sys = _tilted_system()
    rev = lf.OpticalSystem("rev")
    for s in reverse_surfaces(sys, sys.surfaces[1:-1]):
        rev.add_surface(s)

    def placed(system):
        fr = system.surface_frames()
        return [(system.surfaces[i], fr[i]) for i in range(1, system.image_index)
                if not system.surfaces[i].is_coordinate_break]

    a, b = placed(sys), placed(rev)
    F = np.diag([-1.0, 1.0, -1.0])  # 180 degrees about y: the lens turned round
    RL, OL = a[-1][1]
    x, y = np.meshgrid(np.linspace(-2, 2, 5), np.linspace(-2, 2, 5))
    for (s, (R, O)), (s2, (R2, O2)) in zip(reversed(a), b):
        assert np.allclose(F @ RL.T @ (O - OL), O2, atol=1e-12)
        assert np.allclose(F @ RL.T @ R @ F, R2, atol=1e-12)
        # the same physical surface: the sag seen from the other side
        assert np.allclose(s2.sag(-x, y), -s.sag(x, y), atol=1e-12)
    assert b[1][0].aperture.dx == pytest.approx(-0.3)


def test_reverse_twice_is_identity():
    for sys in (_tilted_system(), lf.samples.cassegrain(), lf.samples.achromat()):
        grp = sys.surfaces[1:-1]
        once = reverse_surfaces(sys, grp)
        twice = reverse_surfaces(sys, once)
        assert [s.to_dict() for s in twice] == [s.to_dict() for s in grp]


def test_reverse_keeps_mirrors():
    c = lf.samples.cassegrain()
    rev = lens_surfaces(c, reverse=True)
    mirrors = [s for s in rev if str(s.material).upper() == "MIRROR"]
    assert len(mirrors) == sum(str(s.material).upper() == "MIRROR" for s in c.surfaces)


def test_insert_lens_from_file_into_middle(tmp_path):
    p = tmp_path / "achromat.lens.json"
    lf.save(lf.samples.achromat(), str(p))
    target = lf.samples.singlet()
    n0 = target.num_surfaces
    rng = lf.insert_lens(target, str(p), at=2, first=1, last=2)
    assert list(rng) == [2, 3]
    assert target.num_surfaces == n0 + 2
    assert target.surfaces[2].material == lf.samples.achromat().surfaces[1].material
    with pytest.raises(ValueError):
        lf.insert_lens(target, str(p), first=2, last=9)
    with pytest.raises(IndexError):
        lf.insert_lens(target, str(p), at=0)
