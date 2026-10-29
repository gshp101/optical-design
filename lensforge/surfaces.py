"""Surface types for sequential ray tracing.

Every surface lives in its own local frame: the vertex is at the origin, the
local z axis is the optical axis, and incoming rays are expressed in this
frame.  A surface provides

* ``sag(x, y)`` and ``sag_gradient(x, y)``,
* ``intersect(P, D)`` -> (t, ok) for rays P + t*D,
* optionally ``phase(x, y, wavelength)`` -> (opl, dopl/dx, dopl/dy) for
  diffractive / ideal phase surfaces,
* ``paraxial_curvature`` for the paraxial trace,

plus bookkeeping fields shared by every row of a lens data editor: thickness to
the next surface, the material after the surface, semi-diameter, an optional
clear aperture, stop flag and comment.

All geometry is vectorised over rays (arrays of shape (N,) or (N, 3)).
"""

from __future__ import annotations

import copy
import math
from typing import Dict, Optional, Sequence, Type

import numpy as np

_REGISTRY: Dict[str, Type["Surface"]] = {}


def register(cls):
    _REGISTRY[cls.kind] = cls
    return cls


def surface_from_dict(d: dict) -> "Surface":
    d = dict(d)
    kind = d.pop("type", "STANDARD")
    cls = _REGISTRY[kind]
    ap = d.pop("aperture", None)
    s = cls(**d)
    if ap is not None:
        s.aperture = aperture_from_dict(ap)
    return s


# ---------------------------------------------------------------------------
# Apertures
# ---------------------------------------------------------------------------

class Aperture:
    kind = "NONE"

    def inside(self, x, y):
        return np.ones_like(x, dtype=bool)

    def to_dict(self):
        return {"type": self.kind}


class CircularAperture(Aperture):
    """Annular / circular clear aperture with optional central obscuration and decentre."""

    kind = "CIRCULAR"

    def __init__(self, r_max: float, r_min: float = 0.0, dx: float = 0.0, dy: float = 0.0):
        self.r_max, self.r_min, self.dx, self.dy = float(r_max), float(r_min), float(dx), float(dy)

    def inside(self, x, y):
        r2 = (x - self.dx) ** 2 + (y - self.dy) ** 2
        return (r2 <= self.r_max**2 * (1 + 1e-12)) & (r2 >= self.r_min**2)

    def to_dict(self):
        return {"type": self.kind, "r_max": self.r_max, "r_min": self.r_min, "dx": self.dx, "dy": self.dy}


class CircularObscuration(Aperture):
    kind = "OBSCURATION"

    def __init__(self, radius: float, dx: float = 0.0, dy: float = 0.0):
        self.radius, self.dx, self.dy = float(radius), float(dx), float(dy)

    def inside(self, x, y):
        return (x - self.dx) ** 2 + (y - self.dy) ** 2 > self.radius**2

    def to_dict(self):
        return {"type": self.kind, "radius": self.radius, "dx": self.dx, "dy": self.dy}


class RectangularAperture(Aperture):
    kind = "RECTANGULAR"

    def __init__(self, half_x: float, half_y: float, dx: float = 0.0, dy: float = 0.0):
        self.half_x, self.half_y, self.dx, self.dy = float(half_x), float(half_y), float(dx), float(dy)

    def inside(self, x, y):
        return (np.abs(x - self.dx) <= self.half_x) & (np.abs(y - self.dy) <= self.half_y)

    def to_dict(self):
        return {"type": self.kind, "half_x": self.half_x, "half_y": self.half_y, "dx": self.dx, "dy": self.dy}


class EllipticalAperture(RectangularAperture):
    kind = "ELLIPTICAL"

    def inside(self, x, y):
        return ((x - self.dx) / self.half_x) ** 2 + ((y - self.dy) / self.half_y) ** 2 <= 1 + 1e-12


_APERTURES = {c.kind: c for c in (CircularAperture, CircularObscuration, RectangularAperture, EllipticalAperture)}


def aperture_from_dict(d):
    d = dict(d)
    kind = d.pop("type")
    if kind == "NONE":
        return None
    return _APERTURES[kind](**d)


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------

def _conic_intersect(P, D, c, k):
    """Intersect rays with the conic z = c r^2 / (1 + sqrt(1 - (1+k) c^2 r^2)).

    Uses the numerically stable form that selects the branch through the vertex
    and reduces exactly to the plane case when c == 0.
    """
    px, py, pz = P[:, 0], P[:, 1], P[:, 2]
    dx, dy, dz = D[:, 0], D[:, 1], D[:, 2]
    kk = 1.0 + k
    A = c * (dx * dx + dy * dy + kk * dz * dz)
    B = c * (px * dx + py * dy + kk * pz * dz) - dz
    C = c * (px * px + py * py + kk * pz * pz) - 2.0 * pz
    disc = B * B - A * C
    ok = disc >= 0
    sq = np.sqrt(np.where(ok, disc, 0.0))
    sgn = np.where(dz >= 0, 1.0, -1.0)
    # root on the vertex branch: t = C / (-B + sgn*sq) = (-B - sgn*sq) / A.
    # Use whichever form avoids cancellation.
    denom = -B + sgn * sq
    num = -B - sgn * sq
    use_c = np.abs(denom) >= np.abs(num)
    with np.errstate(divide="ignore", invalid="ignore"):
        t = np.where(use_c, C / denom, num / A)
    ok &= np.isfinite(t)
    return np.where(ok, t, np.nan), ok


def _conic_sag(c, k, r2):
    arg = 1.0 - (1.0 + k) * c * c * r2
    with np.errstate(invalid="ignore"):
        return c * r2 / (1.0 + np.sqrt(arg))


def _conic_dsag_dr2(c, k, r2):
    """d(sag)/d(r^2) = c / (2 sqrt(1 - (1+k)c^2 r^2))."""
    arg = 1.0 - (1.0 + k) * c * c * r2
    with np.errstate(invalid="ignore", divide="ignore"):
        return 0.5 * c / np.sqrt(arg)


class Surface:
    kind = "BASE"
    #: parameter names that are scalar and may be used as optimisation variables
    scalar_params: Sequence[str] = ()
    #: parameter names that are coefficient lists
    list_params: Sequence[str] = ()

    def __init__(self, thickness: float = 0.0, material=None, semi_diameter: Optional[float] = None,
                 aperture: Optional[Aperture] = None, stop: bool = False, comment: str = ""):
        self.thickness = float(thickness)
        self.material = material
        self.semi_diameter = None if semi_diameter is None else float(semi_diameter)
        self.aperture = aperture
        self.stop = bool(stop)
        self.comment = comment

    # -- geometry ---------------------------------------------------------
    is_coordinate_break = False
    has_phase = False
    has_deflect = False  # surfaces that bend rays with their own rule (ideal lenses)

    @property
    def paraxial_curvature(self) -> float:
        return 0.0

    def extra_power(self, wavelength) -> float:
        """Paraxial optical power (1/f) not due to refraction (ideal lenses, diffractive phase).

        ``wavelength`` is in lens units.
        """
        return 0.0

    def sag(self, x, y):
        return np.zeros_like(np.asarray(x, float))

    def sag_gradient(self, x, y):
        z = np.zeros_like(np.asarray(x, float))
        return z, z

    def normal(self, x, y):
        """Unit surface normal pointing along +z (towards the image side)."""
        gx, gy = self.sag_gradient(x, y)
        n = np.stack([-gx, -gy, np.ones_like(gx)], axis=-1)
        return n / np.linalg.norm(n, axis=-1, keepdims=True)

    def intersect(self, P, D):
        """Return distance t (signed) along D to the surface and validity mask."""
        return _conic_intersect(P, D, 0.0, 0.0)

    def phase(self, x, y, wavelength, wavelength_um=None):
        """Optical path added by the surface and its x/y derivatives (lens units).

        ``wavelength`` is in lens units; ``wavelength_um`` is the same wavelength in
        micrometres (used by gratings, whose line density is per micrometre)."""
        return None

    # -- parameters / serialisation ----------------------------------------
    def get_param(self, name):
        return getattr(self, name)

    def set_param(self, name, value):
        if "[" in name:
            base, idx = name[:-1].split("[")
            arr = list(getattr(self, base))
            idx = int(idx)
            while len(arr) <= idx:
                arr.append(0.0)
            arr[idx] = float(value)
            setattr(self, base, arr)
        else:
            setattr(self, name, float(value))

    def to_dict(self) -> dict:
        d = {"type": self.kind}
        for p in self.scalar_params:
            d[p] = getattr(self, p)
        for p in self.list_params:
            d[p] = list(getattr(self, p))
        d["thickness"] = self.thickness
        mat = self.material
        if mat is not None and not isinstance(mat, (str, int, float, dict)):
            mat = mat.to_spec()
        d["material"] = mat
        if self.semi_diameter is not None:
            d["semi_diameter"] = self.semi_diameter
        if self.aperture is not None:
            d["aperture"] = self.aperture.to_dict()
        if self.stop:
            d["stop"] = True
        if self.comment:
            d["comment"] = self.comment
        return d

    def copy(self):
        return copy.deepcopy(self)

    def __repr__(self):
        return f"{type(self).__name__}(t={self.thickness:g}, material={self.material!r})"


# ---------------------------------------------------------------------------
# Standard (sphere / conic) surface
# ---------------------------------------------------------------------------

@register
class Standard(Surface):
    """Sphere or conic of revolution.  ``radius`` = inf (or curvature 0) is a plane."""

    kind = "STANDARD"
    scalar_params = ("curvature", "conic")

    def __init__(self, radius: float = math.inf, conic: float = 0.0, curvature: Optional[float] = None, **kw):
        super().__init__(**kw)
        if curvature is None:
            curvature = 0.0 if (radius is None or math.isinf(radius) or radius == 0) else 1.0 / radius
        self.curvature = float(curvature)
        self.conic = float(conic)

    @property
    def radius(self):
        return math.inf if self.curvature == 0 else 1.0 / self.curvature

    @radius.setter
    def radius(self, r):
        self.curvature = 0.0 if (math.isinf(r) or r == 0) else 1.0 / r

    @property
    def paraxial_curvature(self):
        return self.curvature

    def sag(self, x, y):
        return _conic_sag(self.curvature, self.conic, x * x + y * y)

    def sag_gradient(self, x, y):
        g = 2.0 * _conic_dsag_dr2(self.curvature, self.conic, x * x + y * y)
        return g * x, g * y

    def intersect(self, P, D):
        t, ok = _conic_intersect(P, D, self.curvature, self.conic)
        if self.conic < -1 or self.curvature == 0:
            return t, ok
        # reject points beyond the conic's maximum aperture (sqrt argument < 0)
        x = P[:, 0] + t * D[:, 0]
        y = P[:, 1] + t * D[:, 1]
        arg = 1.0 - (1.0 + self.conic) * self.curvature**2 * (x * x + y * y)
        return t, ok & (arg >= -1e-12)


class _NewtonSurface(Standard):
    """Surface defined by base conic + extra sag; intersection refined by Newton iteration."""

    max_iterations = 50
    tolerance = 1e-12

    def _extra_sag(self, x, y):
        raise NotImplementedError

    def _extra_gradient(self, x, y):
        raise NotImplementedError

    def sag(self, x, y):
        return Standard.sag(self, x, y) + self._extra_sag(x, y)

    def sag_gradient(self, x, y):
        gx, gy = Standard.sag_gradient(self, x, y)
        ex, ey = self._extra_gradient(x, y)
        return gx + ex, gy + ey

    def intersect(self, P, D):
        t, ok = _conic_intersect(P, D, self.curvature, self.conic)
        t = np.where(ok, t, _conic_intersect(P, D, 0.0, 0.0)[0])
        ok = np.isfinite(t)
        t = np.where(ok, t, 0.0)
        # rays already lost upstream carry NaN positions; keep them out of the tolerance scale
        scale = 1.0 + np.abs(P[np.isfinite(P)]).max(initial=1.0)
        with np.errstate(invalid="ignore", divide="ignore", over="ignore"):
            for _ in range(self.max_iterations):
                x = P[:, 0] + t * D[:, 0]
                y = P[:, 1] + t * D[:, 1]
                z = P[:, 2] + t * D[:, 2]
                f = self.sag(x, y) - z
                gx, gy = self.sag_gradient(x, y)
                fp = gx * D[:, 0] + gy * D[:, 1] - D[:, 2]
                dt = f / fp
                dt = np.where(ok, dt, 0.0)
                t = t - dt
                bad = ~np.isfinite(t)
                if bad.any():
                    ok &= ~bad
                    t = np.where(bad, 0.0, t)
                if np.all(np.abs(dt) < self.tolerance * scale):
                    break
            else:
                ok &= np.abs(dt) < 1e-9 * scale
        return np.where(ok, t, np.nan), ok


@register
class EvenAsphere(_NewtonSurface):
    """Conic + even polynomial: z = conic(r) + a1 r^2 + a2 r^4 + a3 r^6 + ..."""

    kind = "EVENASPH"
    list_params = ("coefficients",)

    def __init__(self, radius=math.inf, conic=0.0, coefficients: Sequence[float] = (), **kw):
        super().__init__(radius=radius, conic=conic, **kw)
        self.coefficients = [float(c) for c in coefficients]

    @property
    def paraxial_curvature(self):
        a1 = self.coefficients[0] if self.coefficients else 0.0
        return self.curvature + 2.0 * a1

    def _extra_sag(self, x, y):
        r2 = x * x + y * y
        z = np.zeros_like(r2)
        p = r2.copy()
        for a in self.coefficients:
            z = z + a * p
            p = p * r2
        return z

    def _extra_gradient(self, x, y):
        r2 = x * x + y * y
        dz = np.zeros_like(r2)  # d z / d(r^2)
        p = np.ones_like(r2)
        for i, a in enumerate(self.coefficients, start=1):
            dz = dz + i * a * p
            p = p * r2
        return 2 * dz * x, 2 * dz * y


@register
class OddAsphere(_NewtonSurface):
    """Conic + polynomial in r: z = conic(r) + b1 r + b2 r^2 + b3 r^3 + ..."""

    kind = "ODDASPH"
    list_params = ("coefficients",)

    def __init__(self, radius=math.inf, conic=0.0, coefficients: Sequence[float] = (), **kw):
        super().__init__(radius=radius, conic=conic, **kw)
        self.coefficients = [float(c) for c in coefficients]

    @property
    def paraxial_curvature(self):
        b2 = self.coefficients[1] if len(self.coefficients) > 1 else 0.0
        return self.curvature + 2.0 * b2

    def _extra_sag(self, x, y):
        r = np.sqrt(x * x + y * y)
        return sum(b * r ** (i + 1) for i, b in enumerate(self.coefficients)) + np.zeros_like(r)

    def _extra_gradient(self, x, y):
        r = np.sqrt(x * x + y * y)
        dzdr = sum((i + 1) * b * r**i for i, b in enumerate(self.coefficients)) + np.zeros_like(r)
        with np.errstate(invalid="ignore", divide="ignore"):
            f = np.where(r > 0, dzdr / np.where(r > 0, r, 1.0), 0.0)
        return f * x, f * y


@register
class Toroidal(_NewtonSurface):
    """Toroid: a conic + even polynomial curve in the YZ plane rotated about an
    axis parallel to Y at distance ``radius_x`` from the vertex.

    ``radius``/``curvature`` and ``conic`` describe the Y profile; ``radius_x`` = inf
    gives a cylinder with power in Y only.
    """

    kind = "TOROIDAL"
    scalar_params = ("curvature", "conic", "curvature_x")
    list_params = ("coefficients",)

    def __init__(self, radius=math.inf, conic=0.0, radius_x=math.inf, coefficients=(), curvature_x=None, **kw):
        super().__init__(radius=radius, conic=conic, **kw)
        if curvature_x is None:
            curvature_x = 0.0 if (math.isinf(radius_x) or radius_x == 0) else 1.0 / radius_x
        self.curvature_x = float(curvature_x)
        self.coefficients = [float(c) for c in coefficients]

    @property
    def paraxial_curvature(self):  # Y section
        a1 = self.coefficients[0] if self.coefficients else 0.0
        return self.curvature + 2 * a1

    def _zy(self, y):
        y2 = y * y
        z = _conic_sag(self.curvature, self.conic, y2)
        dz = 2 * _conic_dsag_dr2(self.curvature, self.conic, y2) * y
        p = y2.copy()
        dp = np.ones_like(y2)
        for i, a in enumerate(self.coefficients, start=1):
            z = z + a * p
            dz = dz + 2 * i * a * dp * y
            p = p * y2
            dp = dp * y2
        return z, dz

    def sag(self, x, y):
        zy, _ = self._zy(y)
        if self.curvature_x == 0:
            return zy + 0 * x
        R = 1.0 / self.curvature_x
        u = R - zy
        with np.errstate(invalid="ignore"):
            return R - np.sign(R) * np.sqrt(u * u - x * x)

    def sag_gradient(self, x, y):
        zy, dzy = self._zy(y)
        if self.curvature_x == 0:
            return np.zeros_like(x), dzy
        R = 1.0 / self.curvature_x
        u = R - zy
        with np.errstate(invalid="ignore", divide="ignore"):
            s = np.sqrt(u * u - x * x)
            sg = np.sign(R)
            return sg * x / s, sg * u * dzy / s

    # base intersection for Newton start: use plane
    def intersect(self, P, D):
        return _NewtonSurface.intersect(self, P, D)

    def _extra_sag(self, x, y):  # not used (sag overridden)
        return 0 * x

    def _extra_gradient(self, x, y):
        return 0 * x, 0 * x


@register
class XYPolynomial(_NewtonSurface):
    """Conic base + sum_{i,j} C_ij (x/R0)^i (y/R0)^j  (freeform).

    ``terms`` is a list of [i, j, coefficient]; ``norm_radius`` normalises x, y.
    """

    kind = "XYPOLY"
    scalar_params = ("curvature", "conic", "norm_radius")

    def __init__(self, radius=math.inf, conic=0.0, terms=(), norm_radius=1.0, **kw):
        super().__init__(radius=radius, conic=conic, **kw)
        self.terms = [[int(i), int(j), float(c)] for i, j, c in terms]
        self.norm_radius = float(norm_radius)

    @property
    def paraxial_curvature(self):
        # rotationally averaged quadratic terms
        r0 = self.norm_radius
        cx = sum(c for i, j, c in self.terms if (i, j) == (2, 0)) / r0**2
        cy = sum(c for i, j, c in self.terms if (i, j) == (0, 2)) / r0**2
        return self.curvature + (cx + cy)

    def _extra_sag(self, x, y):
        u, v = x / self.norm_radius, y / self.norm_radius
        z = np.zeros_like(u)
        for i, j, c in self.terms:
            z = z + c * u**i * v**j
        return z

    def _extra_gradient(self, x, y):
        r0 = self.norm_radius
        u, v = x / r0, y / r0
        gx = np.zeros_like(u)
        gy = np.zeros_like(u)
        for i, j, c in self.terms:
            if i:
                gx = gx + c * i * u ** (i - 1) * v**j / r0
            if j:
                gy = gy + c * j * u**i * v ** (j - 1) / r0
        return gx, gy

    def to_dict(self):
        d = super().to_dict()
        d["terms"] = [list(t) for t in self.terms]
        return d


# ---------------------------------------------------------------------------
# Phase surfaces
# ---------------------------------------------------------------------------

@register
class Paraxial(Surface):
    """Ideal thin lens of focal length ``focal_length`` on a plane.

    Ray directions obey  tan' = tan - h/f  exactly, so the lens images
    perfectly at every field angle and conjugate.  The added optical path turns
    the incoming wave from each object point into a perfect spherical wave
    converging on its ideal image, so OPD is zero at any conjugate.  The object
    distance seen by the lens (``conjugate``) comes from the paraxial trace.
    """

    kind = "PARAXIAL"
    scalar_params = ("focal_length",)
    has_deflect = True

    def __init__(self, focal_length: float = 100.0, **kw):
        super().__init__(**kw)
        self.focal_length = float(focal_length)

    def extra_power(self, wavelength):
        return 0.0 if self.focal_length == 0 or math.isinf(self.focal_length) else 1.0 / self.focal_length

    def deflect(self, P, D, n1, n2, conjugate=math.inf):
        """Bend rays and return (new directions, added OPL).

        ``conjugate`` is the signed distance a from the lens to the incoming
        paraxial object point (object at z = -a; inf for collimated input,
        negative for a converging beam).
        """
        f = self.focal_length
        x, y = P[:, 0], P[:, 1]
        dz = D[:, 2]
        tx, ty = D[:, 0] / dz, D[:, 1] / dz
        tx2, ty2 = tx - x / f, ty - y / f
        D2 = np.stack([tx2, ty2, np.ones_like(tx2)], axis=1) * np.sign(dz)[:, None]
        D2 /= np.linalg.norm(D2, axis=1, keepdims=True)
        a = conjugate
        inv_b = 1.0 / f - (0.0 if math.isinf(a) else 1.0 / a)

        # optical path from the incoming wavefront through the vertex to X
        if math.isinf(a):
            in_path = n1 * (x * D[:, 0] + y * D[:, 1])
            Ox, Oy = None, None
        else:
            Ox, Oy = x - a * tx, y - a * ty  # object point of each ray, at z = -a
            sa = math.copysign(1.0, a)
            in_path = n1 * sa * (np.sqrt((x - Ox) ** 2 + (y - Oy) ** 2 + a * a) - np.sqrt(Ox**2 + Oy**2 + a * a))

        # optical path from X to the outgoing wavefront through the vertex
        if abs(inv_b) < 1e-300:
            out_path = -n2 * np.einsum("ij,ij->i", P[:, :2], D2[:, :2])  # collimated output
        else:
            b = 1.0 / inv_b
            if Ox is None:  # ideal image in the focal plane
                Ix, Iy = f * tx, f * ty
            else:
                Ix, Iy = -b / a * Ox, -b / a * Oy
            sb = math.copysign(1.0, b)
            out_path = n2 * sb * (np.sqrt((Ix - x) ** 2 + (Iy - y) ** 2 + b * b) - np.sqrt(Ix**2 + Iy**2 + b * b))
        return D2, -in_path - out_path


@register
class BinaryPhase(Standard):
    """Diffractive surface (Zemax "Binary 2" style) on a conic base.

    phase [rad] = M * sum_i A_i * (r / R0)^(2 i),  i = 1..N
    The added optical path is phase * wavelength / (2 pi).
    """

    kind = "BINARY2"
    scalar_params = ("curvature", "conic", "diffraction_order", "norm_radius")
    list_params = ("coefficients",)
    has_phase = True

    def __init__(self, radius=math.inf, conic=0.0, coefficients=(), diffraction_order=1.0, norm_radius=1.0,
                 design_wavelength: Optional[float] = None, **kw):
        super().__init__(radius=radius, conic=conic, **kw)
        self.coefficients = [float(c) for c in coefficients]
        self.diffraction_order = float(diffraction_order)
        self.norm_radius = float(norm_radius)

    def phase(self, x, y, wavelength, wavelength_um=None):
        r2 = (x * x + y * y) / self.norm_radius**2
        ph = np.zeros_like(r2)
        dph = np.zeros_like(r2)  # d phase / d(r2)
        p = np.ones_like(r2)
        for i, a in enumerate(self.coefficients, start=1):
            dph = dph + i * a * p
            p = p * r2
            ph = ph + a * p
        k = self.diffraction_order * wavelength / (2 * math.pi)
        g = k * dph * 2 / self.norm_radius**2
        return k * ph, g * x, g * y

    def extra_power(self, wavelength):
        a1 = self.coefficients[0] if self.coefficients else 0.0
        return -2.0 * self.diffraction_order * a1 * wavelength / (2 * math.pi) / self.norm_radius**2


@register
class DiffractionGrating(Standard):
    """Linear diffraction grating ruled on a conic surface (Zemax "Diffraction Grating" style).

    The lines are parallel to the local x axis, so light is diffracted in the
    local y-z plane.  ``lines_per_um`` is the line density T (lines per
    micrometre, measured along y in the surface's projected plane) and
    ``diffraction_order`` the order m.  The grating adds the optical path
    ``m * lambda * T * y``, so the tangential direction cosines obey the
    grating equation

        n' M' = n M + m * lambda[um] * T[lines/um]

    (M = y direction cosine), for transmission and for reflection (on a
    MIRROR).  The grating has no paraxial power; its deviation is not part of
    the paraxial trace, so follow it with a coordinate break that tilts the
    axis onto the diffracted beam when the order is not zero.
    """

    kind = "DGRATING"
    scalar_params = ("curvature", "conic", "lines_per_um", "diffraction_order")
    has_phase = True

    def __init__(self, radius=math.inf, conic=0.0, lines_per_um: float = 0.6, diffraction_order: float = 1.0, **kw):
        super().__init__(radius=radius, conic=conic, **kw)
        self.lines_per_um = float(lines_per_um)
        self.diffraction_order = float(diffraction_order)

    def phase(self, x, y, wavelength, wavelength_um=None):
        lam_um = wavelength_um if wavelength_um is not None else wavelength * 1e3  # default: mm lens units
        g = self.diffraction_order * lam_um * self.lines_per_um  # d(OPL)/dy, dimensionless
        y = np.asarray(y, float)
        return g * y, np.zeros_like(y), np.full_like(y, g)


# ---------------------------------------------------------------------------
# Coordinate break
# ---------------------------------------------------------------------------

def rotation_matrix(tilt_x_deg, tilt_y_deg, tilt_z_deg):
    a, b, g = (math.radians(v) for v in (tilt_x_deg, tilt_y_deg, tilt_z_deg))
    rx = np.array([[1, 0, 0], [0, math.cos(a), -math.sin(a)], [0, math.sin(a), math.cos(a)]])
    ry = np.array([[math.cos(b), 0, math.sin(b)], [0, 1, 0], [-math.sin(b), 0, math.cos(b)]])
    rz = np.array([[math.cos(g), -math.sin(g), 0], [math.sin(g), math.cos(g), 0], [0, 0, 1]])
    return rx @ ry @ rz


@register
class CoordinateBreak(Surface):
    """Decentre and tilt the coordinate system (no optical effect).

    order 0: decentre, then tilt about X, then Y, then Z.
    order 1: tilt about Z, Y, X, then decentre (the exact inverse of order 0).
    The thickness is applied after the break, along the new z axis.
    """

    kind = "COORDBRK"
    scalar_params = ("decenter_x", "decenter_y", "tilt_x", "tilt_y", "tilt_z", "order")
    is_coordinate_break = True

    def __init__(self, decenter_x=0.0, decenter_y=0.0, tilt_x=0.0, tilt_y=0.0, tilt_z=0.0, order=0, **kw):
        super().__init__(**kw)
        self.decenter_x, self.decenter_y = float(decenter_x), float(decenter_y)
        self.tilt_x, self.tilt_y, self.tilt_z = float(tilt_x), float(tilt_y), float(tilt_z)
        self.order = int(order)

    def frame(self):
        """Return (R, d): new axes as columns of R and new origin d, in the old frame."""
        d = np.array([self.decenter_x, self.decenter_y, 0.0])
        if self.order == 0:
            return rotation_matrix(self.tilt_x, self.tilt_y, self.tilt_z), d
        R = rotation_matrix(0, 0, self.tilt_z) @ rotation_matrix(0, self.tilt_y, 0) @ rotation_matrix(self.tilt_x, 0, 0)
        return R, R @ d

    def transform(self, P, D):
        R, d = self.frame()
        return (P - d) @ R, D @ R
