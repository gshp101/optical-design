"""Ready-made example systems for scripting, tests and demos."""

from __future__ import annotations

from .system import OpticalSystem

VISIBLE = ([0.4861327, 0.5875618, 0.6562725], 1)  # F, d, C


def singlet(efl_hint: float = 100.0) -> OpticalSystem:
    """Equi-convex N-BK7 singlet, F/5, 0/5/10 degree fields, image at paraxial focus."""
    s = OpticalSystem("Equi-convex singlet")
    s.set_aperture("EPD", 20.0)
    s.set_fields([0.0, 5.0, 10.0])
    s.set_wavelengths(*VISIBLE)
    R = 2 * 0.5168 * efl_hint
    s.add_surface(radius=R, thickness=5.0, material="N-BK7", stop=True)
    s.add_surface(radius=-R, thickness=efl_hint)
    focus_paraxial(s)
    return s


def achromat() -> OpticalSystem:
    """Cemented N-BAF10 / N-SF6 achromat, EPD 20, image at paraxial focus."""
    s = OpticalSystem("Cemented achromat")
    s.set_aperture("EPD", 20.0)
    s.set_fields([0.0, 1.0, 2.0])
    s.set_wavelengths(*VISIBLE)
    s.add_surface(radius=62.75, thickness=4.0, material="N-BAF10", stop=True)
    s.add_surface(radius=-45.71, thickness=2.5, material="N-SF6")
    s.add_surface(radius=-128.23, thickness=70.0)
    focus_paraxial(s)
    return s


def parabolic_mirror(focal_length: float = 500.0, diameter: float = 100.0) -> OpticalSystem:
    s = OpticalSystem("Parabolic mirror")
    s.set_aperture("EPD", diameter)
    s.set_fields([0.0, 0.25, 0.5])
    s.add_surface(radius=-2 * focal_length, conic=-1.0, thickness=-focal_length, material="MIRROR", stop=True)
    return s


def cassegrain(f1: float = 500.0, separation: float = 400.0, back_focus: float = 100.0,
               diameter: float = 100.0) -> OpticalSystem:
    """Classical Cassegrain (parabolic primary, hyperbolic secondary): stigmatic on axis."""
    p = f1 - separation  # secondary to primary focus
    q = separation + back_focus  # secondary to final image
    m = q / p
    f2 = p * q / (q - p)
    s = OpticalSystem("Classical Cassegrain")
    s.set_aperture("EPD", diameter)
    s.set_fields([0.0, 0.1, 0.2])
    s.add_surface(radius=-2 * f1, conic=-1.0, thickness=-separation, material="MIRROR", stop=True)
    s.add_surface(radius=-2 * f2, conic=-((m + 1) / (m - 1)) ** 2, thickness=q, material="MIRROR")
    return s


def focus_paraxial(system: OpticalSystem) -> float:
    """Set the last thickness so the image surface sits at the paraxial focus
    (marginal-ray height solve).  Returns the new thickness."""
    last = system.surfaces[system.image_index - 1]
    last.thickness = system.paraxial().image_distance
    return last.thickness
