"""Non-sequential objects, sources and the scene that holds them.

Every object and source has a pose: a position (x, y, z) and tilts about its
local X, then Y, then Z axes in degrees (local -> global: ``R @ p + position``
with ``R = Rx Ry Rz``, the same convention as coordinate breaks).  Geometry
is described in the object's local frame by a list of faces.

Object kinds
------------
Volumes (``material`` is the medium inside; faces refract and, with ray
splitting, also reflect by Fresnel's equations or a ``coating`` reflectance):

* :class:`StandardLens`  two faces (any sequential surface type) + cylindrical edge
* :class:`Sphere`        ball of radius R
* :class:`RectangularVolume`  box, z from 0 to ``length``
* :class:`CylinderVolume`     rod, z from 0 to ``length``

Surfaces (no volume; ``material`` "MIRROR" reflects, "ABSORB" absorbs):

* :class:`StandardSurface`  one sequential surface with an annular aperture
* :class:`Annulus`          flat ring (e.g. a stop or baffle)
* :class:`Rectangle`        flat rectangle (fold mirror, baffle)
* :class:`Detector`         flat rectangular pixel detector (absorbs unless ``transparent``)

Sources: :class:`SourcePoint`, :class:`SourceEllipse`, :class:`SourceRectangle`.
"""

from __future__ import annotations

import math
from typing import List, Optional

import numpy as np

from .. import surfaces as S
from ..surfaces import rotation_matrix

EPS = 1e-7  # minimum ray travel (lens units) so a ray never re-hits the face it starts on

# ---------------------------------------------------------------------------
# Faces (object-local geometry)
# ---------------------------------------------------------------------------


class Face:
    """One face of an object, in the object's local frame."""

    name = "face"

    def intersect(self, P, D):  # pragma: no cover - interface
        raise NotImplementedError

    def normal(self, P):  # pragma: no cover - interface
        raise NotImplementedError


class SurfaceFace(Face):
    """A sequential surface (any type) with its vertex at z = ``z0``, inside an annulus or rectangle.

    ``outward`` (+1 or -1) multiplies the surface normal (which points to +z) so that it
    points out of the volume.
    """

    def __init__(self, surface, z0=0.0, r_max=math.inf, r_min=0.0, outward=1.0, rect=None, name="face"):
        self.surface, self.z0, self.r_max, self.r_min = surface, float(z0), float(r_max), float(r_min)
        self.outward, self.rect, self.name = float(outward), rect, name

    def intersect(self, P, D):
        Q = P - np.array([0.0, 0.0, self.z0])
        with np.errstate(all="ignore"):
            t, ok = self.surface.intersect(Q, D)
        t = np.where(ok, t, np.nan)
        with np.errstate(invalid="ignore"):
            H = Q + t[:, None] * D
        x, y = H[:, 0], H[:, 1]
        if self.rect is not None:
            inside = (np.abs(x) <= self.rect[0]) & (np.abs(y) <= self.rect[1])
        else:
            r2 = x * x + y * y
            inside = (r2 <= self.r_max**2 * (1 + 1e-12)) & (r2 >= self.r_min**2)
        with np.errstate(invalid="ignore"):
            good = inside & (t > EPS)
        return np.where(good, t, np.nan)

    def normal(self, P):
        return self.outward * self.surface.normal(P[:, 0], P[:, 1])


class CylinderFace(Face):
    """Side wall x^2 + y^2 = R^2 between z_min and z_max; normal points away from the axis."""

    def __init__(self, radius, z_min, z_max, name="edge"):
        self.R, self.z_min, self.z_max, self.name = float(radius), min(z_min, z_max), max(z_min, z_max), name

    def intersect(self, P, D):
        a = D[:, 0] ** 2 + D[:, 1] ** 2
        b = 2 * (P[:, 0] * D[:, 0] + P[:, 1] * D[:, 1])
        c = P[:, 0] ** 2 + P[:, 1] ** 2 - self.R**2
        return _nearest_root(a, b, c, P, D, lambda H: (H[:, 2] >= self.z_min) & (H[:, 2] <= self.z_max))

    def normal(self, P):
        n = np.stack([P[:, 0], P[:, 1], np.zeros(len(P))], axis=1)
        return n / np.linalg.norm(n, axis=1, keepdims=True)


class SphereFace(Face):
    def __init__(self, radius, name="sphere"):
        self.R, self.name = float(radius), name

    def intersect(self, P, D):
        a = np.einsum("ij,ij->i", D, D)
        b = 2 * np.einsum("ij,ij->i", P, D)
        c = np.einsum("ij,ij->i", P, P) - self.R**2
        return _nearest_root(a, b, c, P, D, None)

    def normal(self, P):
        return P / np.linalg.norm(P, axis=1, keepdims=True)


class PlaneFace(Face):
    """Flat face through ``center`` with unit ``normal``; ``u`` is its first in-plane axis.

    ``shape`` is ("rect", half_u, half_v) or ("disk", r_max, r_min).
    """

    def __init__(self, center, normal, u, shape, name="plane"):
        self.c = np.asarray(center, float)
        self.n = np.asarray(normal, float) / np.linalg.norm(normal)
        self.u = np.asarray(u, float) / np.linalg.norm(u)
        self.v = np.cross(self.n, self.u)
        self.shape, self.name = shape, name

    def local_uv(self, H):
        d = H - self.c
        return d @ self.u, d @ self.v

    def intersect(self, P, D):
        dn = D @ self.n
        with np.errstate(divide="ignore", invalid="ignore"):
            t = ((self.c - P) @ self.n) / dn
            H = P + t[:, None] * D
            u, v = self.local_uv(H)
        if self.shape[0] == "rect":
            inside = (np.abs(u) <= self.shape[1]) & (np.abs(v) <= self.shape[2])
        else:
            r2 = u * u + v * v
            inside = (r2 <= self.shape[1] ** 2 * (1 + 1e-12)) & (r2 > self.shape[2] ** 2 * (1 + 1e-9))
        with np.errstate(invalid="ignore"):
            good = inside & (t > EPS) & np.isfinite(t)
        return np.where(good, t, np.nan)

    def normal(self, P):
        return np.broadcast_to(self.n, P.shape).copy()


def _nearest_root(a, b, c, P, D, accept):
    """Smallest root t > EPS of a t^2 + b t + c = 0 whose point passes ``accept``."""
    disc = b * b - 4 * a * c
    ok = (disc >= 0) & (a > 1e-300)
    sq = np.sqrt(np.where(ok, disc, 0.0))
    with np.errstate(divide="ignore", invalid="ignore"):
        q = -0.5 * (b + np.where(b >= 0, sq, -sq))
        t1, t2 = q / a, c / q
    best = np.full(len(a), np.nan)
    for t in (np.minimum(t1, t2), np.maximum(t1, t2)):
        t = np.where(ok & np.isfinite(t), t, np.nan)
        with np.errstate(invalid="ignore"):
            cand = t > EPS
        if accept is not None:
            H = P + np.nan_to_num(t)[:, None] * D
            cand &= accept(H)
        best = np.where(np.isnan(best) & cand, t, best)
    return best


# ---------------------------------------------------------------------------
# Poses
# ---------------------------------------------------------------------------

class Posed:
    """Position and X-Y-Z tilts (degrees)."""

    def __init__(self, x=0.0, y=0.0, z=0.0, tilt_x=0.0, tilt_y=0.0, tilt_z=0.0, comment=""):
        self.x, self.y, self.z = float(x), float(y), float(z)
        self.tilt_x, self.tilt_y, self.tilt_z = float(tilt_x), float(tilt_y), float(tilt_z)
        self.comment = comment

    @property
    def R(self):
        return rotation_matrix(self.tilt_x, self.tilt_y, self.tilt_z)

    @property
    def origin(self):
        return np.array([self.x, self.y, self.z])

    def to_local(self, P, D):
        R = self.R
        return (P - self.origin) @ R, D @ R

    def to_global_dir(self, V):
        return V @ self.R.T

    def to_global(self, P):
        return P @ self.R.T + self.origin

    def set_pose(self, R, origin):
        """Set position and tilts from a rotation matrix (columns = local axes) and an origin."""
        self.x, self.y, self.z = (float(v) for v in origin)
        self.tilt_x, self.tilt_y, self.tilt_z = angles_from_matrix(R)

    _pose_keys = ("x", "y", "z", "tilt_x", "tilt_y", "tilt_z")

    def _pose_dict(self):
        return {k: getattr(self, k) for k in self._pose_keys}


def angles_from_matrix(R):
    """Tilts (deg) about X, Y, Z with ``rotation_matrix(tx, ty, tz) == R``."""
    sy = max(-1.0, min(1.0, R[0, 2]))
    ty = math.asin(sy)
    if abs(math.cos(ty)) > 1e-12:
        tx = math.atan2(-R[1, 2], R[2, 2])
        tz = math.atan2(-R[0, 1], R[0, 0])
    else:  # gimbal lock: put everything in tx
        tx = math.atan2(R[2, 1], R[1, 1])
        tz = 0.0
    return math.degrees(tx), math.degrees(ty), math.degrees(tz)


def direction_angles(d):
    """Tilts (tx, ty) that turn local +z into the unit vector ``d``."""
    d = np.asarray(d, float) / np.linalg.norm(d)
    ty = math.asin(max(-1.0, min(1.0, d[0])))
    tx = math.atan2(-d[1], d[2])
    return math.degrees(tx), math.degrees(ty)


# ---------------------------------------------------------------------------
# Objects
# ---------------------------------------------------------------------------

_OBJECTS = {}


def _register(cls):
    _OBJECTS[cls.kind] = cls
    return cls


class NSObject(Posed):
    kind = "OBJECT"
    is_volume = False
    is_detector = False
    #: editable parameters (name, label) shown by front ends after the pose and material
    params: tuple = ()

    def __init__(self, material=None, coating: Optional[float] = None, **pose):
        super().__init__(**pose)
        self.material = material
        self.coating = None if coating in (None, "") else float(coating)

    def faces(self) -> List[Face]:  # pragma: no cover - interface
        raise NotImplementedError

    @property
    def action(self) -> str:
        """What a hit does: "refract" (volumes), "mirror", "absorb", "detect" or "pass"."""
        if self.is_volume:
            return "refract"
        m = str(self.material or "").upper()
        if m == "MIRROR":
            return "mirror"
        if m == "ABSORB":
            return "absorb"
        return "pass"

    def to_dict(self):
        d = {"type": self.kind, **self._pose_dict(), "material": self.material, "comment": self.comment}
        if self.coating is not None:
            d["coating"] = self.coating
        for name, _ in self.params:
            d[name] = getattr(self, name)
        return d

    def copy(self):
        return object_from_dict(self.to_dict())

    def outline(self, n=41):
        """Polylines (lists of (k, 3) global points) for layout drawings."""
        return []

    def __repr__(self):
        return f"{type(self).__name__}({self.comment or self.material!r} at {self.x:g}, {self.y:g}, {self.z:g})"


def object_from_dict(d):
    d = dict(d)
    cls = _OBJECTS[d.pop("type")]
    return cls.from_dict(d)


def _surf_dict(s):
    return None if s is None else s.to_dict()


def _profile(surface, z0, r, n):
    y = np.linspace(-r, r, n)
    z = z0 + surface.sag(np.zeros(n), y)
    return np.stack([np.zeros(n), y, z], axis=1)


@_register
class StandardLens(NSObject):
    """Lens of ``material``: front face at z = 0, back face at z = ``thickness``, cylindrical edge.

    Faces are Standard surfaces (radius, conic) unless ``surface1`` / ``surface2``
    give any sequential surface (even/odd aspheres, toroids, XY polynomials ...).
    """

    kind = "STANDARD_LENS"
    is_volume = True
    params = (("radius1", "Radius 1"), ("conic1", "Conic 1"), ("thickness", "Thickness"),
              ("radius2", "Radius 2"), ("conic2", "Conic 2"), ("semi_diameter", "Semi-diameter"))

    def __init__(self, radius1=math.inf, conic1=0.0, thickness=5.0, radius2=math.inf, conic2=0.0,
                 semi_diameter=10.0, material="N-BK7", surface1=None, surface2=None, **kw):
        super().__init__(material=material, **kw)
        self.radius1, self.conic1, self.radius2, self.conic2 = (float(v) for v in (radius1, conic1, radius2, conic2))
        self.thickness, self.semi_diameter = float(thickness), float(semi_diameter)
        self.surface1 = S.surface_from_dict(surface1) if isinstance(surface1, dict) else surface1
        self.surface2 = S.surface_from_dict(surface2) if isinstance(surface2, dict) else surface2

    def _surfaces(self):
        s1 = self.surface1 or S.Standard(radius=self.radius1, conic=self.conic1)
        s2 = self.surface2 or S.Standard(radius=self.radius2, conic=self.conic2)
        return s1, s2

    def faces(self):
        s1, s2 = self._surfaces()
        sd, t = self.semi_diameter, self.thickness
        sgn = 1.0 if t >= 0 else -1.0
        z1 = float(s1.sag(np.array([0.0]), np.array([sd]))[0])
        z2 = t + float(s2.sag(np.array([0.0]), np.array([sd]))[0])
        faces = [SurfaceFace(s1, 0.0, sd, outward=-sgn, name="front"),
                 SurfaceFace(s2, t, sd, outward=sgn, name="back")]
        if abs(z2 - z1) > 1e-12:
            faces.append(CylinderFace(sd, z1, z2))
        return faces

    def to_dict(self):
        d = super().to_dict()
        if self.surface1 is not None:
            d["surface1"] = _surf_dict(self.surface1)
        if self.surface2 is not None:
            d["surface2"] = _surf_dict(self.surface2)
        return d

    @classmethod
    def from_dict(cls, d):
        return cls(**d)

    def outline(self, n=41):
        s1, s2 = self._surfaces()
        a = _profile(s1, 0.0, self.semi_diameter, n)
        b = _profile(s2, self.thickness, self.semi_diameter, n)
        loop = np.concatenate([a, b[::-1], a[:1]])
        return [self.to_global(loop)]


@_register
class Sphere(NSObject):
    kind = "SPHERE"
    is_volume = True
    params = (("radius", "Radius"),)

    def __init__(self, radius=5.0, material="N-BK7", **kw):
        super().__init__(material=material, **kw)
        self.radius = float(radius)

    def faces(self):
        return [SphereFace(self.radius)]

    @classmethod
    def from_dict(cls, d):
        return cls(**d)

    def outline(self, n=41):
        th = np.linspace(0, 2 * np.pi, 2 * n)
        p = np.stack([np.zeros_like(th), self.radius * np.sin(th), self.radius * np.cos(th)], axis=1)
        return [self.to_global(p)]


@_register
class RectangularVolume(NSObject):
    """Box with x in [-half_x, half_x], y in [-half_y, half_y], z in [0, length]."""

    kind = "RECT_VOLUME"
    is_volume = True
    params = (("half_x", "X half width"), ("half_y", "Y half width"), ("length", "Length"))

    def __init__(self, half_x=5.0, half_y=5.0, length=10.0, material="N-BK7", **kw):
        super().__init__(material=material, **kw)
        self.half_x, self.half_y, self.length = float(half_x), float(half_y), float(length)

    def faces(self):
        hx, hy, L = self.half_x, self.half_y, self.length
        ex, ey, ez = np.eye(3)
        return [PlaneFace([0, 0, 0], -ez, ex, ("rect", hx, hy), "front"),
                PlaneFace([0, 0, L], ez, ex, ("rect", hx, hy), "back"),
                PlaneFace([hx, 0, L / 2], ex, ey, ("rect", hy, L / 2), "+x"),
                PlaneFace([-hx, 0, L / 2], -ex, ey, ("rect", hy, L / 2), "-x"),
                PlaneFace([0, hy, L / 2], ey, ez, ("rect", L / 2, hx), "+y"),
                PlaneFace([0, -hy, L / 2], -ey, ez, ("rect", L / 2, hx), "-y")]

    @classmethod
    def from_dict(cls, d):
        return cls(**d)

    def outline(self, n=41):
        hy, L = self.half_y, self.length
        p = np.array([[0, -hy, 0], [0, hy, 0], [0, hy, L], [0, -hy, L], [0, -hy, 0]], float)
        return [self.to_global(p)]


@_register
class CylinderVolume(NSObject):
    """Rod of radius ``radius`` from z = 0 to z = ``length`` (a light pipe)."""

    kind = "CYLINDER_VOLUME"
    is_volume = True
    params = (("radius", "Radius"), ("length", "Length"))

    def __init__(self, radius=2.0, length=20.0, material="N-BK7", **kw):
        super().__init__(material=material, **kw)
        self.radius, self.length = float(radius), float(length)

    def faces(self):
        ex, _, ez = np.eye(3)
        R, L = self.radius, self.length
        return [PlaneFace([0, 0, 0], -ez, ex, ("disk", R, 0.0), "front"),
                PlaneFace([0, 0, L], ez, ex, ("disk", R, 0.0), "back"),
                CylinderFace(R, 0.0, L)]

    @classmethod
    def from_dict(cls, d):
        return cls(**d)

    def outline(self, n=41):
        R, L = self.radius, self.length
        p = np.array([[0, -R, 0], [0, R, 0], [0, R, L], [0, -R, L], [0, -R, 0]], float)
        return [self.to_global(p)]


@_register
class StandardSurface(NSObject):
    """One surface (no volume): a mirror ("MIRROR") or absorber ("ABSORB") with an annular aperture."""

    kind = "STANDARD_SURFACE"
    params = (("radius", "Radius"), ("conic", "Conic"), ("semi_diameter", "Semi-diameter"),
              ("inner_radius", "Inner radius"))

    def __init__(self, radius=math.inf, conic=0.0, semi_diameter=10.0, inner_radius=0.0, material="MIRROR",
                 surface=None, reflectance=1.0, **kw):
        super().__init__(material=material, **kw)
        self.radius, self.conic = float(radius), float(conic)
        self.semi_diameter, self.inner_radius = float(semi_diameter), float(inner_radius)
        self.surface = S.surface_from_dict(surface) if isinstance(surface, dict) else surface
        self.reflectance = float(reflectance)

    def _surface(self):
        return self.surface or S.Standard(radius=self.radius, conic=self.conic)

    def faces(self):
        return [SurfaceFace(self._surface(), 0.0, self.semi_diameter, self.inner_radius, outward=-1.0, name="surface")]

    def to_dict(self):
        d = super().to_dict()
        d["reflectance"] = self.reflectance
        if self.surface is not None:
            d["surface"] = _surf_dict(self.surface)
        return d

    @classmethod
    def from_dict(cls, d):
        return cls(**d)

    def outline(self, n=41):
        return [self.to_global(_profile(self._surface(), 0.0, self.semi_diameter, n))]


@_register
class Annulus(NSObject):
    """Flat ring in the local z = 0 plane (absorbing by default): stops and baffles."""

    kind = "ANNULUS"
    params = (("inner_radius", "Inner radius"), ("outer_radius", "Outer radius"))

    def __init__(self, inner_radius=5.0, outer_radius=10.0, material="ABSORB", reflectance=1.0, **kw):
        super().__init__(material=material, **kw)
        self.inner_radius, self.outer_radius = float(inner_radius), float(outer_radius)
        self.reflectance = float(reflectance)

    def faces(self):
        ex, _, ez = np.eye(3)
        return [PlaneFace([0, 0, 0], -ez, ex, ("disk", self.outer_radius, self.inner_radius), "ring")]

    def to_dict(self):
        return {**super().to_dict(), "reflectance": self.reflectance}

    @classmethod
    def from_dict(cls, d):
        return cls(**d)

    def outline(self, n=41):
        a, b = self.inner_radius, self.outer_radius
        return [self.to_global(np.array([[0, a, 0], [0, b, 0]], float)),
                self.to_global(np.array([[0, -a, 0], [0, -b, 0]], float))]


@_register
class Rectangle(NSObject):
    """Flat rectangle in the local z = 0 plane: fold mirror ("MIRROR") or baffle ("ABSORB")."""

    kind = "RECTANGLE"
    params = (("half_x", "X half width"), ("half_y", "Y half width"))

    def __init__(self, half_x=5.0, half_y=5.0, material="MIRROR", reflectance=1.0, **kw):
        super().__init__(material=material, **kw)
        self.half_x, self.half_y, self.reflectance = float(half_x), float(half_y), float(reflectance)

    def faces(self):
        ex, _, ez = np.eye(3)
        return [PlaneFace([0, 0, 0], -ez, ex, ("rect", self.half_x, self.half_y), "rect")]

    def to_dict(self):
        return {**super().to_dict(), "reflectance": self.reflectance}

    @classmethod
    def from_dict(cls, d):
        return cls(**d)

    def outline(self, n=41):
        return [self.to_global(np.array([[0, -self.half_y, 0], [0, self.half_y, 0]], float))]


@_register
class Detector(NSObject):
    """Rectangular pixel detector in the local z = 0 plane; records every ray that hits it.

    It absorbs the light unless ``transparent``.  Hits are recorded from both sides.
    """

    kind = "DETECTOR"
    is_detector = True
    params = (("half_x", "X half width"), ("half_y", "Y half width"), ("nx", "X pixels"), ("ny", "Y pixels"),
              ("transparent", "Transparent (1/0)"))

    def __init__(self, half_x=5.0, half_y=5.0, nx=101, ny=101, transparent=False, material=None, **kw):
        super().__init__(material=material, **kw)
        self.half_x, self.half_y = float(half_x), float(half_y)
        self.nx, self.ny, self.transparent = int(nx), int(ny), bool(transparent)

    @property
    def action(self):
        return "detect"

    def faces(self):
        ex, _, ez = np.eye(3)
        return [PlaneFace([0, 0, 0], -ez, ex, ("rect", self.half_x, self.half_y), "detector")]

    @classmethod
    def from_dict(cls, d):
        return cls(**d)

    def outline(self, n=41):
        return [self.to_global(np.array([[0, -self.half_y, 0], [0, self.half_y, 0]], float))]


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------

_SOURCES = {}


def _register_source(cls):
    _SOURCES[cls.kind] = cls
    return cls


class Source(Posed):
    """Base class: ``n_rays`` rays carrying ``power`` (watts, or any unit) in total,
    spread evenly over ``wavelengths`` (um).  Rays leave along local +z.

    ``sampling`` is "random" (seeded; Monte Carlo) or "grid" (regular, repeatable).
    """

    kind = "SOURCE"
    params: tuple = ()

    def __init__(self, n_rays=1000, power=1.0, wavelengths=(0.5875618,), sampling="random", **pose):
        super().__init__(**pose)
        self.n_rays, self.power = int(n_rays), float(power)
        self.wavelengths = [float(w) for w in np.atleast_1d(wavelengths)]
        self.sampling = sampling

    def local_rays(self, n, rng):  # pragma: no cover - interface
        raise NotImplementedError

    def rays(self, rng):
        """Global (P, D, power per ray, wavelength index per ray)."""
        n = max(int(self.n_rays), 1)
        P, D = self.local_rays(n, rng)
        m = len(P)
        wl = np.arange(m) % len(self.wavelengths)
        return self.to_global(P), self.to_global_dir(D), np.full(m, self.power / m), wl

    def to_dict(self):
        d = {"type": self.kind, **self._pose_dict(), "comment": self.comment, "n_rays": self.n_rays,
             "power": self.power, "wavelengths": list(self.wavelengths), "sampling": self.sampling}
        for name, _ in self.params:
            d[name] = getattr(self, name)
        return d

    @classmethod
    def from_dict(cls, d):
        return cls(**d)

    def copy(self):
        return source_from_dict(self.to_dict())


def source_from_dict(d):
    d = dict(d)
    return _SOURCES[d.pop("type")].from_dict(d)


def _cone_dirs(n, half_angle_deg, rng, sampling):
    """Unit directions uniform in solid angle within a cone about +z."""
    ca = math.cos(math.radians(half_angle_deg))
    if sampling == "grid":
        k = max(int(round(math.sqrt(n))), 1)
        g = (np.arange(k) + 0.5) / k
        u, v = np.meshgrid(g, g)
        u, v = u.ravel(), v.ravel()
    else:
        u, v = rng.random(n), rng.random(n)
    cz = 1 - u * (1 - ca)
    s = np.sqrt(np.maximum(1 - cz * cz, 0))
    ph = 2 * np.pi * v
    return np.stack([s * np.cos(ph), s * np.sin(ph), cz], axis=1)


@_register_source
class SourcePoint(Source):
    """Point source radiating uniformly into a cone of half-angle ``cone_angle`` (deg) about local +z."""

    kind = "SOURCE_POINT"
    params = (("cone_angle", "Cone half-angle (deg)"),)

    def __init__(self, cone_angle=10.0, **kw):
        super().__init__(**kw)
        self.cone_angle = float(cone_angle)

    def local_rays(self, n, rng):
        D = _cone_dirs(n, self.cone_angle, rng, self.sampling)
        return np.zeros_like(D), D


def _area_points(n, rng, sampling, ellipse):
    if sampling == "grid":
        k = max(int(round(math.sqrt(n * (4 / math.pi if ellipse else 1)))), 1)
        g = (np.arange(k) + 0.5) / k * 2 - 1
        u, v = np.meshgrid(g, g)
        u, v = u.ravel(), v.ravel()
        if ellipse:
            keep = u * u + v * v <= 1
            u, v = u[keep], v[keep]
        return u, v
    if ellipse:
        r, th = np.sqrt(rng.random(n)), 2 * np.pi * rng.random(n)
        return r * np.cos(th), r * np.sin(th)
    return rng.random(n) * 2 - 1, rng.random(n) * 2 - 1


class _AreaSource(Source):
    params = (("half_x", "X half width"), ("half_y", "Y half width"), ("cone_angle", "Divergence half-angle (deg)"))
    ellipse = True

    def __init__(self, half_x=5.0, half_y=5.0, cone_angle=0.0, **kw):
        super().__init__(**kw)
        self.half_x, self.half_y, self.cone_angle = float(half_x), float(half_y), float(cone_angle)

    def local_rays(self, n, rng):
        u, v = _area_points(n, rng, self.sampling, self.ellipse)
        P = np.stack([u * self.half_x, v * self.half_y, np.zeros_like(u)], axis=1)
        if self.cone_angle > 0:
            D = _cone_dirs(len(P), self.cone_angle, rng, "random")
        else:
            D = np.tile([0.0, 0.0, 1.0], (len(P), 1))
        return P, D


@_register_source
class SourceEllipse(_AreaSource):
    """Elliptical emitting area (collimated along local +z when ``cone_angle`` = 0)."""

    kind = "SOURCE_ELLIPSE"
    ellipse = True


@_register_source
class SourceRectangle(_AreaSource):
    """Rectangular emitting area (collimated along local +z when ``cone_angle`` = 0)."""

    kind = "SOURCE_RECTANGLE"
    ellipse = False


OBJECT_TYPES = dict(_OBJECTS)
SOURCE_TYPES = dict(_SOURCES)
