"""Solves: parameters computed from the rest of the lens instead of being free.

A solve is attached to one cell of the lens (surface, parameter) and is
re-applied whenever the lens changes during optimisation, exactly like the
solves of a lens data editor.  Solves are stored on ``system.solves`` and
applied in surface order by :func:`apply_solves`.

Thickness solves
    :class:`MarginalRayHeight` (paraxial, or real at a pupil zone),
    :class:`ChiefRayHeight`, :class:`EdgeThickness`, :class:`Position`.
Curvature solves
    :class:`MarginalRayAngle`, :class:`ChiefRayAngle`, :class:`FNumber`,
    :class:`Concentric`.
Any parameter
    :class:`Pickup` (value = scale * other cell + offset; also materials).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional

import numpy as np

from ..paraxial import ParaxialAnalysis
from .variables import get_param, set_param


class Solve:
    """Base class; subclasses define ``surface`` and the solved ``param``."""

    #: True if the solve changes a curvature (and so possibly the aperture / pupils)
    changes_power = False

    def apply(self, system):  # pragma: no cover - interface
        raise NotImplementedError

    def to_dict(self):
        d = {"type": type(self).__name__}
        d.update(vars(self))
        return d

    @property
    def cell(self):
        return (self.surface, "curvature" if self.param == "radius" else self.param)


def _marginal(system, wavelength=None):
    par = ParaxialAnalysis(system, wavelength)
    Y, NU = par.marginal_ray
    return par, Y, NU


def _chief(system, wavelength=None):
    par = ParaxialAnalysis(system, wavelength)
    Y, NU = par.chief_ray
    return par, Y, NU


def _thickness_for_height(par, Y, NU, i, h):
    nu, y = NU[i - 1], Y[i - 1]
    if nu == 0:
        raise ValueError(f"height solve on surface {i}: ray is parallel to the axis")
    return (h - y) * par.n[i] / nu


def _curvature_for_angle(system, par, Y, NU, i, u):
    s = system.surfaces[i]
    y = Y[i - 1]
    if y == 0:
        raise ValueError(f"angle solve on surface {i}: ray height is zero")
    n0, n1 = par.n[i - 1], par.n[i]
    nu_before = NU[i - 1] + y * par.phi[i]
    phi = (nu_before - u * n1) / y
    extra = s.extra_power(par.wavelength * system.wavelength_scale)
    if n1 == n0:
        raise ValueError(f"angle solve on surface {i}: no index change")
    return (phi - extra) / (n1 - n0)


@dataclass
class MarginalRayHeight(Solve):
    """Thickness of ``surface`` so the marginal ray has height ``height`` on the next surface.

    ``height = 0`` on the last surface puts the image at the paraxial focus.
    With ``pupil_zone > 0`` the real marginal ray at that pupil zone (primary
    wavelength) is used instead, e.g. 0.7 for a "best" focus.
    """

    surface: int
    height: float = 0.0
    pupil_zone: float = 0.0
    param = "thickness"

    def apply(self, system):
        s = system.surfaces[self.surface]
        if self.pupil_zone == 0:
            par, Y, NU = _marginal(system)
            s.thickness = _thickness_for_height(par, Y, NU, self.surface, self.height)
            return
        from ..raytrace import trace_rays
        par, Y, NU = _marginal(system)
        s.thickness = _thickness_for_height(par, Y, NU, self.surface, self.height)
        for _ in range(20):
            r = trace_rays(system, 0.0, 0.0, 0.0, self.pupil_zone, apertures=False, last=self.surface + 1)
            if not r.valid[0]:
                break
            d = r.directions[self.surface][0]
            err = r.positions[-1, 0, 1] - self.height
            if d[1] == 0:
                break
            dt = -err / (d[1] / d[2])
            s.thickness += dt
            if abs(dt) < 1e-12 * max(1.0, abs(s.thickness)):
                break


@dataclass
class ChiefRayHeight(Solve):
    """Thickness of ``surface`` so the paraxial chief ray has height ``height`` on the next surface
    (``height = 0`` places the next surface at a pupil image)."""

    surface: int
    height: float = 0.0
    param = "thickness"

    def apply(self, system):
        par, Y, NU = _chief(system)
        system.surfaces[self.surface].thickness = _thickness_for_height(par, Y, NU, self.surface, self.height)


@dataclass
class MarginalRayAngle(Solve):
    """Curvature of ``surface`` so the paraxial marginal ray slope after it is ``angle`` (tan u')."""

    surface: int
    angle: float = 0.0
    param = "curvature"
    changes_power = True

    def apply(self, system):
        par, Y, NU = _marginal(system)
        system.surfaces[self.surface].curvature = _curvature_for_angle(system, par, Y, NU, self.surface, self.angle)


@dataclass
class ChiefRayAngle(Solve):
    """Curvature of ``surface`` so the paraxial chief ray slope after it is ``angle``
    (0 on the last surface makes image space telecentric)."""

    surface: int
    angle: float = 0.0
    param = "curvature"
    changes_power = True

    def apply(self, system):
        par, Y, NU = _chief(system)
        system.surfaces[self.surface].curvature = _curvature_for_angle(system, par, Y, NU, self.surface, self.angle)


@dataclass
class FNumber(Solve):
    """Curvature of ``surface`` (usually the last) giving marginal slope u' = -1/(2 F#),
    i.e. a paraxial working F-number ``fnum`` (this fixes the focal length for a
    given entrance pupil)."""

    surface: int
    fnum: float = 5.0
    param = "curvature"
    changes_power = True

    def apply(self, system):
        par, Y, NU = _marginal(system)
        u = -1.0 / (2.0 * self.fnum)
        system.surfaces[self.surface].curvature = _curvature_for_angle(system, par, Y, NU, self.surface, u)


@dataclass
class Concentric(Solve):
    """Curvature of ``surface`` so its centre of curvature is at the vertex of ``center_surface``."""

    surface: int
    center_surface: int
    param = "curvature"
    changes_power = True

    def apply(self, system):
        i, j = self.surface, self.center_surface
        if j > i:
            R = sum(system.surfaces[k].thickness for k in range(i, j))
        else:
            R = -sum(system.surfaces[k].thickness for k in range(j, i))
        system.surfaces[i].curvature = 0.0 if R == 0 else 1.0 / R


@dataclass
class EdgeThickness(Solve):
    """Thickness of ``surface`` giving edge thickness ``value`` to the next surface at
    radial ``height`` (default: the larger semi-diameter of the two surfaces)."""

    surface: int
    value: float = 1.0
    height: Optional[float] = None
    param = "thickness"

    def apply(self, system):
        i = self.surface
        s1, s2 = system.surfaces[i], system.surfaces[i + 1]
        h = self.height
        if h is None:
            h = max(s1.semi_diameter or 0.0, s2.semi_diameter or 0.0)
            if h == 0.0:
                par = ParaxialAnalysis(system)
                ym, _ = par.marginal_ray
                yc, _ = par.chief_ray
                h = abs(ym[i - 1]) + abs(yc[i - 1])
        z1 = float(np.nan_to_num(s1.sag(np.array([h]), np.array([0.0]))[0]))
        z2 = float(np.nan_to_num(s2.sag(np.array([h]), np.array([0.0]))[0]))
        s1.thickness = self.value + z1 - z2


@dataclass
class Position(Solve):
    """Thickness of ``surface`` so the next surface lies ``length`` from ``from_surface``
    (e.g. a fixed total track)."""

    surface: int
    from_surface: int = 1
    length: float = 100.0
    param = "thickness"

    def apply(self, system):
        i, j = self.surface, self.from_surface
        if j > i:
            raise ValueError("Position solve: from_surface must precede the solved surface")
        system.surfaces[i].thickness = self.length - sum(system.surfaces[k].thickness for k in range(j, i))


@dataclass
class Pickup(Solve):
    """``param`` of ``surface`` = scale * (``from_param`` of ``from_surface``) + offset.

    ``param="material"`` copies the material (scale/offset ignored).  Use
    ``param="radius"`` to pick up radii (scale applies to the radius).
    """

    surface: int
    param: str
    from_surface: int
    scale: float = 1.0
    offset: float = 0.0
    from_param: Optional[str] = None

    def apply(self, system):
        if self.param == "material":
            system.surfaces[self.surface].material = system.surfaces[self.from_surface].material
            return
        src = self.from_param or self.param
        v = get_param(system, self.from_surface, src)
        set_param(system, self.surface, self.param, self.scale * v + self.offset)


SOLVE_TYPES = {c.__name__: c for c in (MarginalRayHeight, ChiefRayHeight, MarginalRayAngle, ChiefRayAngle,
                                        FNumber, Concentric, EdgeThickness, Position, Pickup)}


def solve_from_dict(d: dict) -> Solve:
    d = dict(d)
    cls = SOLVE_TYPES[d.pop("type")]
    if cls is not Pickup:
        d.pop("param", None)
    return cls(**d)


def solves(system) -> List[Solve]:
    if getattr(system, "solves", None) is None:
        system.solves = []
    return system.solves


def set_solve(system, solve: Solve) -> Solve:
    """Attach a solve (replacing any other solve on the same cell) and apply it."""
    lst = solves(system)
    lst[:] = [s for s in lst if s.cell != solve.cell]
    lst.append(solve)
    apply_solves(system)
    return solve


def remove_solve(system, surface: int, param: str):
    lst = solves(system)
    p = "curvature" if param == "radius" else param
    lst[:] = [s for s in lst if s.cell != (surface, p)]


def apply_solves(system):
    """Apply all solves in surface order.  If a curvature solve may change the
    aperture definition (F/# or NA apertures) the pass is repeated."""
    lst = getattr(system, "solves", None)
    if not lst:
        return
    order = sorted(lst, key=lambda s: (s.surface, 0 if s.changes_power else 1))
    passes = 2 if any(s.changes_power for s in order) and system.aperture_type in (
        "IMAGE_FNUM", "WORKING_FNUM") else 1
    for _ in range(passes):
        for s in order:
            s.apply(system)
