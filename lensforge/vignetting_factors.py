"""Vignetting factors: compute them from the surface apertures, or clear them.

Each :class:`~lensforge.system.Field` carries five vignetting factors, as in
common lens design codes:

``vdx``, ``vdy``
    decentre of the vignetted pupil (fractions of the pupil radius);
``vcx``, ``vcy``
    compression of the pupil in x and y (0 = none, 0.3 = 30 % narrower);
``van``
    vignetting angle in degrees: rotates the compressed pupil
    counter-clockwise about its centre, so a field off the y axis can be
    compressed along its own meridional direction.

A ray at normalised pupil coordinates (px, py) of a defined field is traced at
``R(van) . (px (1 - vcx), py (1 - vcy)) + (vdx, vdy)``.  The factors make the
ray grid of spot diagrams, fans and other geometric analyses fill exactly the
part of the pupil that gets through the lens instead of losing the clipped
rays.  Diffraction analyses (pupil function, PSF, FFT MTF), the chief-ray
field analyses (field curvature, distortion, lateral colour) and the
relative-illumination / vignetting plots trace the full pupil and let the
apertures clip it, so they stay physical.

:func:`set_vignetting` finds the factors for each field: it traces fans across
the pupil (with the factors off) along the two axes of the field's vignetting
angle, finds where rays start to fail on a surface aperture or fall outside a
fixed semi-diameter, and centres and compresses the pupil onto that range.
"""

from __future__ import annotations

import math
from typing import Iterable, List, Optional

import numpy as np

from .raytrace import OK, RayGenerator, trace

__all__ = ["set_vignetting", "clear_vignetting", "vignetting_limits"]

_FACTORS = ("vdx", "vdy", "vcx", "vcy")


def _field_list(system, fields) -> List[int]:
    if fields is None:
        return list(range(len(system.fields)))
    if isinstance(fields, int):
        return [fields]
    return [int(i) for i in fields]


def clear_vignetting(system, fields: Optional[Iterable[int]] = None, keep_angle: bool = False):
    """Set the vignetting factors of ``fields`` (default: all) to zero.

    ``keep_angle=True`` leaves the vignetting angle (``van``) as it is."""
    for i in _field_list(system, fields):
        f = system.fields[i]
        for a in _FACTORS:
            setattr(f, a, 0.0)
        if not keep_angle:
            f.van = 0.0
    return system


class _Passes:
    """Which raw pupil points of one field reach the image."""

    def __init__(self, system, index, wavelength, use_semi_diameters):
        self.system = system
        self.hx, self.hy = system.normalized_field(index)
        self.wavelength = system.primary if wavelength is None else float(wavelength)
        self.gen = RayGenerator(system, self.wavelength, vignetting=False)
        last = system.image_index
        self.limits = []
        if use_semi_diameters:
            for i in range(1, last):
                s = system.surfaces[i]
                if s.semi_diameter is not None and not s.is_coordinate_break and s.semi_diameter > 0:
                    self.limits.append((i, s.semi_diameter))

    def __call__(self, px, py):
        px, py = np.broadcast_arrays(np.atleast_1d(np.asarray(px, float)), np.atleast_1d(np.asarray(py, float)))
        n = px.size
        with np.errstate(all="ignore"):
            P, D, o = self.gen.rays(np.full(n, self.hx), np.full(n, self.hy), px.ravel(), py.ravel())
            r = trace(self.system, P, D, self.wavelength, o)
            ok = (r.status == OK) & np.all(np.isfinite(r.positions[-1]), axis=1)
            for i, sd in self.limits:
                rr = np.hypot(r.positions[i, :, 0], r.positions[i, :, 1])
                ok &= rr <= sd * (1 + 1e-9)
        return ok.reshape(px.shape)


def _bisect(passes, point, good, bad, iters=22):
    """Refine pass/fail boundaries along t (arrays of good / bad t values, all at once)."""
    good, bad = np.array(good, float), np.array(bad, float)
    for _ in range(iters):
        m = 0.5 * (good + bad)
        ok = passes(*point(m))
        good = np.where(ok, m, good)
        bad = np.where(ok, bad, m)
    return good


def _runs(ok):
    """Index ranges (first, last) of the runs of True in ``ok``."""
    runs, start = [], None
    for k, v in enumerate(ok):
        if v and start is None:
            start = k
        if not v and start is not None:
            runs.append((start, k - 1))
            start = None
    if start is not None:
        runs.append((start, len(ok) - 1))
    return runs


def _chord(c, e):
    """Range of t for which c + t e lies in the unit pupil (c inside it, e a unit vector)."""
    ce = c[0] * e[0] + c[1] * e[1]
    root = math.sqrt(max(ce * ce - (c[0] ** 2 + c[1] ** 2) + 1.0, 0.0))
    return -ce - root, -ce + root


def _interval(passes, c, e, n=101):
    """Passing interval [lo, hi] of t along the pupil chord c + t e, or None.

    Takes the passing run that contains t = 0 (the starting point c), else
    the run nearest to it, and refines both ends by bisection."""
    t0, t1 = _chord(c, e)
    t = np.linspace(t0, t1, n)

    def point(tt):
        return c[0] + tt * e[0], c[1] + tt * e[1]

    ok = passes(*point(t))
    if not ok.any():
        return None
    runs = _runs(ok)
    k0 = int(np.argmin(np.abs(t)))
    run = next((r for r in runs if r[0] <= k0 <= r[1]), None) or \
        min(runs, key=lambda r: min(abs(t[r[0]]), abs(t[r[1]])))
    good = [t[run[0]], t[run[1]]]
    bad = [t[run[0] - 1] if run[0] > 0 else t[0], t[run[1] + 1] if run[1] < n - 1 else t[-1]]
    lo, hi = _bisect(passes, point, good, bad)
    return float(lo), float(hi)


def _axes(angle):
    c, s = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    return (c, s), (-s, c)  # the compressed x and y axes in the pupil


def _start_point(passes, field, n=41):
    """A pupil point whose ray gets through, as close as possible to the centre of
    the field's current vignetted pupil, or None when no ray of the field passes.

    Tries that centre, then points of the current vignetted pupil, then the
    whole unit pupil, so factors that already let rays through are never lost."""
    cx, cy = field.vignette_pupil(0.0, 0.0)
    cx, cy = float(cx), float(cy)
    r = math.hypot(cx, cy)
    if r > 1.0:
        cx, cy = cx / r, cy / r
    if passes(cx, cy)[0]:
        return cx, cy
    v = np.linspace(-1.0, 1.0, n)
    X, Y = np.meshgrid(v, v)
    disk = X**2 + Y**2 <= 1.0
    X, Y = X[disk], Y[disk]
    for px, py in (field.vignette_pupil(X, Y), (X, Y)):
        px, py = np.asarray(px, float), np.asarray(py, float)
        inside = px**2 + py**2 <= 1.0 + 1e-12
        px, py = px[inside], py[inside]
        ok = passes(px, py)
        if ok.any():
            k = np.argmin(np.where(ok, (px - cx) ** 2 + (py - cy) ** 2, np.inf))
            return float(px[k]), float(py[k])
    return None


def vignetting_limits(system, field: int, wavelength=None, angle: float = 0.0,
                      use_semi_diameters: bool = True, samples: int = 101, passes=None):
    """Unvignetted pupil range of one field along the axes of ``angle`` (degrees).

    The search starts from the field's current vignetted pupil (its centre, or
    the passing point of it nearest the centre) and follows the pupil chords
    through it, so a field whose present factors let rays through always
    gives a result.  Returns ``(x_lo, x_hi, y_lo, y_hi)`` in the rotated pupil
    frame (fractions of the pupil radius), or None when no ray of the field
    gets through."""
    passes = passes or _Passes(system, field, wavelength, use_semi_diameters)
    start = _start_point(passes, system.fields[field])
    if start is None:
        return None
    ex, ey = _axes(angle)
    c = start
    for _ in range(12):
        yr = _interval(passes, c, ey, samples)
        if yr is None:
            return None
        m = 0.5 * (yr[0] + yr[1])
        c = (c[0] + m * ey[0], c[1] + m * ey[1])
        xr = _interval(passes, c, ex, samples)
        if xr is None:
            return None
        m = 0.5 * (xr[0] + xr[1])
        c = (c[0] + m * ex[0], c[1] + m * ex[1])
        if abs(m) < 1e-7:
            break  # the y range found through c is final
    cu, cv = c[0] * ex[0] + c[1] * ex[1], c[0] * ey[0] + c[1] * ey[1]
    a, b = 0.5 * (xr[1] - xr[0]), 0.5 * (yr[1] - yr[0])
    return cu - a, cu + a, cv - b, cv + b


def _rot(angle):
    c, s = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    return lambda u, v: (c * u - s * v, s * u + c * v)


def _fit_inside(passes, angle, cu, cv, a, b, n_rim=72, iters=14):
    """Shrink the semi-axes (a, b) of the pupil ellipse centred on (cu, cv) until
    its whole rim passes, keeping it as large as possible."""
    rot = _rot(angle)
    th = np.linspace(0.0, 2 * np.pi, n_rim, endpoint=False)
    cth, sth = np.cos(th), np.sin(th)

    def rim_ok(ka, kb):
        return bool(passes(*rot(cu + ka * a * cth, cv + kb * b * sth)).all())

    if rim_ok(1.0, 1.0):
        return a, b
    # largest uniform scale whose rim passes, then grow each axis on its own
    lo, hi = 0.0, 1.0
    for _ in range(iters):
        m = 0.5 * (lo + hi)
        lo, hi = (m, hi) if rim_ok(m, m) else (lo, m)
    ka = kb = lo
    for axis in (0, 1):
        g, bd = (ka, 1.0) if axis == 0 else (kb, 1.0)
        for _ in range(iters):
            m = 0.5 * (g + bd)
            ok = rim_ok(m, kb) if axis == 0 else rim_ok(ka, m)
            g, bd = (m, bd) if ok else (g, m)
        if axis == 0:
            ka = g
        else:
            kb = g
    return ka * a, kb * b


def set_vignetting(system, fields: Optional[Iterable[int]] = None, wavelength=None, angle=None,
                   use_semi_diameters: bool = True, strict: bool = True, samples: int = 101,
                   tol: float = 1e-6):
    """Compute vignetting factors so every ray of each field passes the lens.

    For each field (default: all) the pupil is decentred (VDX, VDY) and
    compressed (VCX, VCY) onto the range of pupil coordinates whose rays get
    through every surface aperture and, with ``use_semi_diameters``, inside
    every fixed (non-automatic) semi-diameter, at the primary wavelength unless
    ``wavelength`` (um) is given.  Automatic semi-diameters never clip.

    The decentre comes from the four extreme rays (top, bottom, left and right
    of the unclipped part of the pupil, along the axes of the vignetting
    angle).  The clipped pupil is rarely an exact ellipse, so with ``strict``
    (the default) the compression is then increased until rays all round the
    rim of the vignetted pupil pass too; ``strict=False`` keeps the classic
    four-ray factors, whose ellipse can still lose rays near the diagonals.

    ``angle`` sets the vignetting angle VAN (degrees) used for the compression
    axes: None keeps each field's own VAN, a number uses it for every field,
    and ``"auto"`` lines the compressed y axis up with each field's direction
    (VAN = -atan2(x, y), so fields on the y axis keep VAN = 0).

    The search is iterative: it starts from each field's current factors
    (the centre of its present vignetted pupil, or the nearest point of that
    pupil whose ray gets through) and walks out to the clip boundary from
    there, so a field whose current factors let rays through always gets new
    factors, and pressing Set Vignetting again on a result changes nothing.

    Fields that are already unvignetted get zero factors.  Returns one entry
    per field index processed: a dict of the new factors, or None when no ray
    of that field gets through (its factors are then left as they were).
    """
    out = {}
    for i in _field_list(system, fields):
        f = system.fields[i]
        if angle is None:
            van = f.van
        elif isinstance(angle, str) and angle.lower() == "auto":
            van = 0.0 if f.x == 0 else -math.degrees(math.atan2(f.x, f.y))
        else:
            van = float(angle)
        passes = _Passes(system, i, wavelength, use_semi_diameters)
        lim = vignetting_limits(system, i, wavelength, van, use_semi_diameters, samples, passes)
        if lim is None:
            out[i] = None  # keep the field's factors: nothing better was found
            continue
        x0, x1, y0, y1 = lim
        cu, cv = 0.5 * (x0 + x1), 0.5 * (y0 + y1)
        a, b = 0.5 * (x1 - x0), 0.5 * (y1 - y0)
        if strict:
            a, b = _fit_inside(passes, van, cu, cv, a, b)
        vdx, vdy = _rot(van)(cu, cv)
        vals = {"vdx": vdx, "vdy": vdy, "vcx": 1.0 - a, "vcy": 1.0 - b, "van": van}
        for k in _FACTORS:
            v = vals[k]
            if abs(v) < tol:
                vals[k] = 0.0
            elif k in ("vcx", "vcy"):
                vals[k] = math.ceil(v * 1e6) / 1e6  # round the compression up: the pupil never grows
            else:
                vals[k] = round(v, 6)
        for k, v in vals.items():
            setattr(f, k, v)
        out[i] = vals
    return out
