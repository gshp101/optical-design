"""First-order (paraxial) optics using the y-nu trace.

Indices are signed (they change sign after each reflection) and thicknesses
after mirrors are negative, so all formulas hold for catadioptric systems.
Tilts and decentres from coordinate breaks are ignored here, as in other
codes; their thicknesses are still applied.
"""

from __future__ import annotations

import math
from functools import cached_property
from typing import Optional

import numpy as np


def surface_powers(system, wavelength):
    """Return (phi, n_signed) for each surface at ``wavelength`` (um)."""
    _, _, ns = system.media(wavelength)
    wl = wavelength * system.wavelength_scale
    phi = np.zeros(system.num_surfaces)
    for i in range(1, system.num_surfaces):
        s = system.surfaces[i]
        if s.is_coordinate_break:
            continue
        phi[i] = (ns[i] - ns[i - 1]) * s.paraxial_curvature + s.extra_power(wl)
    return phi, ns


def ynu_trace(system, y, nu, first, last, wavelength, phi=None, ns=None):
    """Trace paraxial rays from the vertex plane of ``first`` (before refraction there)
    through surface ``last``.

    ``y`` and ``nu`` may be arrays (several rays at once).  Returns arrays
    ``Y[k]`` (height at surface first+k) and ``NU[k]`` (n*u after refraction).
    """
    if phi is None:
        phi, ns = surface_powers(system, wavelength)
    y = np.asarray(y, float).copy()
    nu = np.asarray(nu, float).copy()
    Y, NU = [], []
    for i in range(first, last + 1):
        nu = nu - y * phi[i]
        Y.append(y.copy())
        NU.append(nu.copy())
        if i < last:
            y = y + system.surfaces[i].thickness * nu / ns[i]
    return np.array(Y), np.array(NU)


class ParaxialAnalysis:
    """First-order properties of a system at one wavelength (default: primary).

    All distances are in lens units.  Pupil positions are relative to the
    vertex of surface 1 (entrance) and of the last surface before the image
    (exit), positive to the right.
    """

    def __init__(self, system, wavelength: Optional[float] = None):
        self.system = system
        self.wavelength = system.primary if wavelength is None else wavelength
        self.phi, self.n = surface_powers(system, self.wavelength)
        self.n_object = self.n[0]
        self.last = system.image_index - 1  # last optical surface
        self.n_image = self.n[self.last]

    def _trace(self, y, nu, first=1, last=None):
        return ynu_trace(self.system, y, nu, first, self.last if last is None else last,
                         self.wavelength, self.phi, self.n)

    # -- cardinal quantities -----------------------------------------------
    @cached_property
    def _unit_parallel(self):
        return self._trace(1.0, 0.0)

    @property
    def power(self) -> float:
        Y, NU = self._unit_parallel
        return -NU[-1]

    @property
    def efl(self) -> float:
        p = self.power
        return math.inf if p == 0 else 1.0 / p

    @property
    def bfl(self) -> float:
        """Distance from the last surface to the paraxial focus for an object at infinity."""
        Y, NU = self._unit_parallel
        u = NU[-1] / self.n_image
        return math.inf if u == 0 else -Y[-1] / u

    @property
    def ffl(self) -> float:
        """Front focal distance: from surface 1 to the front focal point (negative if to the left)."""
        # trace a ray that exits parallel: solve with two rays
        Y, NU = self._trace([1.0, 0.0], [0.0, 1.0])
        # want NU_last = 0: a*NU1 + b*NU2 = 0 with ray at front focus crossing axis
        a, b = NU[-1, 1], -NU[-1, 0]
        y1, nu1 = a * 1.0, b * 1.0
        u = nu1 / self.n_object
        return math.inf if u == 0 else -y1 / u

    # -- pupils ---------------------------------------------------------------
    @cached_property
    def _to_stop(self):
        st = self.system.stop_index
        Y, NU = self._trace([1.0, 0.0], [0.0, 1.0], 1, st)
        return Y[-1, 0], Y[-1, 1]  # A, B : y_stop = A y1 + B nu1

    @cached_property
    def _from_stop(self):
        st = self.system.stop_index
        if st > self.last:
            return 1.0, 0.0, 0.0, 1.0
        # rays leaving the stop: (y=0, nu=1) and (y=1, nu=0) after refraction at stop
        Y, NU = self._trace([0.0, 1.0], [1.0, self.phi[st]], st, self.last)
        return Y[-1, 1], Y[-1, 0], NU[-1, 1], NU[-1, 0]  # A', B', C', D'

    @property
    def entrance_pupil_position(self) -> float:
        A, B = self._to_stop
        return math.inf if A == 0 else B * self.n_object / A

    @property
    def stop_radius(self) -> float:
        """Paraxial semi-diameter of the stop implied by the aperture setting."""
        sysm = self.system
        A, _ = self._to_stop
        if sysm.aperture_type == "STOP_SIZE":
            return sysm.aperture_value
        return abs(A) * self.entrance_pupil_radius

    @property
    def entrance_pupil_radius(self) -> float:
        sysm = self.system
        kind, v = sysm.aperture_type, sysm.aperture_value
        A, _ = self._to_stop
        if kind == "EPD":
            return v / 2.0
        if kind == "STOP_SIZE":
            return v / abs(A)
        if kind == "IMAGE_FNUM":
            return abs(self.efl) / (2.0 * v)
        if kind == "OBJECT_NA":
            if sysm.object_at_infinity:
                raise ValueError("Object NA requires a finite object distance")
            u = math.tan(math.asin(v / self.n_object))
            return u * (sysm.object.thickness + self.entrance_pupil_position)
        if kind == "WORKING_FNUM":
            # marginal ray is linear in pupil radius: scale a unit ray
            _, nu = self._marginal_unit()
            return 1.0 / (2.0 * v * abs(nu[-1]))
        raise ValueError(kind)

    @property
    def epd(self) -> float:
        return 2.0 * self.entrance_pupil_radius

    @property
    def exit_pupil_position(self) -> float:
        _, B, _, D = self._from_stop
        return math.inf if D == 0 else -B * self.n_image / D

    @property
    def exit_pupil_radius(self) -> float:
        _, _, _, D = self._from_stop
        return math.inf if D == 0 else self.stop_radius / abs(D)

    # -- marginal and chief rays -----------------------------------------------
    def _marginal_unit(self):
        """Marginal ray for unit entrance pupil radius: (Y, NU) at surfaces 1..last."""
        sysm = self.system
        if sysm.object_at_infinity:
            return self._trace(1.0, 0.0)
        t0 = sysm.object.thickness
        u = 1.0 / (t0 + self.entrance_pupil_position)
        return self._trace(u * t0, self.n_object * u)

    @cached_property
    def marginal_ray(self):
        """(y, nu) of the paraxial marginal ray at surfaces 1..last (arrays)."""
        Y, NU = self._marginal_unit()
        r = self.entrance_pupil_radius
        return Y * r, NU * r

    def object_slope_for_field(self, hx: float = 0.0, hy: float = 1.0):
        """Paraxial chief-ray description of a field point.

        Returns ("angle", tan_x, tan_y) for objects at infinity or
        ("point", x, y) object coordinates for finite objects, ignoring
        real-image-height fields (handled by the real ray tracer).
        """
        sysm = self.system
        kind = sysm.field_type
        fx, fy = hx * sysm.max_field, hy * sysm.max_field
        inf = sysm.object_at_infinity
        if kind == "ANGLE":
            tx, ty = math.tan(math.radians(fx)), math.tan(math.radians(fy))
            if inf:
                return ("angle", tx, ty)
            L = sysm.object.thickness + self.entrance_pupil_position
            return ("point", -tx * L, -ty * L)
        if kind == "OBJECT_HEIGHT":
            if inf:
                raise ValueError("Object height fields require a finite object distance")
            return ("point", fx, fy)
        if kind in ("PARAXIAL_IMAGE_HEIGHT", "REAL_IMAGE_HEIGHT"):
            k = self.image_height_per_unit_field()
            return ("angle" if inf else "point", fx / k, fy / k)
        raise ValueError(kind)

    def _chief_unit(self):
        """Chief ray for unit tan(angle) (infinite object) or unit object height."""
        sysm = self.system
        ze = self.entrance_pupil_position
        if sysm.object_at_infinity:
            return self._trace(-ze, self.n_object)
        t0 = sysm.object.thickness
        u = -1.0 / (t0 + ze)
        return self._trace(1.0 + u * t0, self.n_object * u)

    def image_height_per_unit_field(self) -> float:
        """Paraxial image height (at the paraxial image plane) per unit tan(angle)
        or unit object height."""
        Y, NU = self._chief_unit()
        return Y[-1] + self.image_distance * NU[-1] / self.n_image

    @cached_property
    def chief_ray(self):
        """(y, nu) of the paraxial chief ray (max +y field) at surfaces 1..last."""
        kind, a, b = self.object_slope_for_field(0.0, 1.0)
        Y, NU = self._chief_unit()
        return Y * b, NU * b

    # -- image -------------------------------------------------------------------
    @property
    def image_distance(self) -> float:
        """Distance from the last surface to the paraxial image of the actual object."""
        Y, NU = self._marginal_unit()
        u = NU[-1] / self.n_image
        return math.inf if u == 0 else -Y[-1] / u

    @property
    def magnification(self) -> float:
        if self.system.object_at_infinity:
            return 0.0
        # Lagrange: m = (n u)_object / (n' u')_image for the marginal ray
        _, NU = self._marginal_unit()
        nu_object = self.n_object / (self.system.object.thickness + self.entrance_pupil_position)
        return nu_object / NU[-1]

    @property
    def paraxial_image_height(self) -> float:
        _, a, b = self.object_slope_for_field(0.0, 1.0)
        return b * self.image_height_per_unit_field()

    @property
    def working_fnum(self) -> float:
        _, NU = self.marginal_ray
        return math.inf if NU[-1] == 0 else 1.0 / (2.0 * abs(NU[-1]))

    @property
    def image_space_fnum(self) -> float:
        return abs(self.efl) / self.epd

    @property
    def image_space_na(self) -> float:
        _, NU = self.marginal_ray
        u = NU[-1] / self.n_image
        return abs(self.n_image) * math.sin(math.atan(abs(u)))

    @property
    def lagrange_invariant(self) -> float:
        ym, num = self.marginal_ray
        yc, nuc = self.chief_ray
        return float(nuc[0] * ym[0] - num[0] * yc[0])

    @property
    def total_track(self) -> float:
        return float(sum(s.thickness for s in self.system.surfaces[1:-1]))

    def summary(self) -> dict:
        def f(x):
            return float(x)

        return {
            "wavelength_um": self.wavelength,
            "efl": f(self.efl),
            "bfl": f(self.bfl),
            "ffl": f(self.ffl),
            "image_distance": f(self.image_distance),
            "epd": f(self.epd),
            "entrance_pupil_position": f(self.entrance_pupil_position),
            "exit_pupil_position": f(self.exit_pupil_position),
            "exit_pupil_diameter": f(2 * self.exit_pupil_radius),
            "stop_radius": f(self.stop_radius),
            "image_space_fnum": f(self.image_space_fnum),
            "working_fnum": f(self.working_fnum),
            "image_space_na": f(self.image_space_na),
            "magnification": f(self.magnification),
            "paraxial_image_height": f(self.paraxial_image_height),
            "lagrange_invariant": f(self.lagrange_invariant),
            "total_track": f(self.total_track),
        }

    def __repr__(self):
        return "\n".join(f"{k:>26}: {v:.6g}" for k, v in self.summary().items())
