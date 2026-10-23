"""Point-source trace: rays from an arbitrary 3-D object point to the image plane."""

from __future__ import annotations

import math

import numpy as np

from ..pupil import pupil_grid
from ..raytrace import ERROR_NAMES, OK, RayGenerator, trace


def _resolve_system(system):
    if isinstance(system, str) or hasattr(system, "__fspath__"):
        from ..io import load
        return load(str(system))
    return system


def _resolve_wavelength(system, wavelength):
    if wavelength is None:
        return system.primary
    if isinstance(wavelength, (int, np.integer)) and not isinstance(wavelength, bool):
        return system.wavelengths[int(wavelength)].value
    return float(wavelength)


def point_source_trace(system, point, wavelength=None, pattern: str = "hexapolar", n: int = 6,
                       size: float = 1.0, px=None, py=None, aiming=None, frame: str = "lens",
                       apertures: bool = True, seed: int = 0):
    """Trace rays from one object point (x, y, z) to the image plane.

    ``system`` is an :class:`OpticalSystem` or a lens file path (``.lens.json``
    or ``.zmx``).  ``point`` is the source position in lens units: (x, y, z)
    or (x, y), which puts it on the object surface.  With ``frame="lens"``
    (default) coordinates are global, surface 1's vertex at the origin, so a
    point 100 mm in front of the lens has z = -100.  With ``frame="object"``
    z is measured from the object surface (z = 0 on it; needs a finite
    object distance).  The point does not have to lie on the object surface,
    and it can be used with lenses whose object is at infinity.

    ``wavelength`` is in micrometres (an int selects a system wavelength,
    None the primary).  Rays are aimed through the entrance pupil with
    ``pupil_grid(pattern, n)``: "hexapolar" (n rings), "square"/"grid" (n x n),
    "random" and "dithered" (n**2 points), "ring" (n points on the rim),
    "cross", "xfan", "yfan" (n points per fan).  ``size`` scales the pattern
    (0.5 fills the inner half of the pupil radius; "ring" with size 0.7 is a
    zone).  Explicit normalised ``px``, ``py`` arrays override the pattern.
    ``aiming`` is "paraxial" or "real" (default: the system's setting); with
    real aiming pupil coordinates map onto the stop exactly.

    Returns a dict: ``x``, ``y``, ``z`` and ``positions`` (N, 3) on the image
    surface (its local frame; NaN where a ray failed), ``directions`` (N, 3),
    ``px``, ``py`` (normalised pupil coordinates launched), ``valid`` (reached
    the image unvignetted), ``vignetted`` (= ~valid), ``status`` (0 ok, 1 missed
    a surface, 2 TIR, 3 clipped by an aperture), ``error_surface`` (-1 if
    none), ``reasons`` (text per ray), ``chief`` (image (x, y) of the px = py = 0
    ray, traced without apertures), ``centroid``, ``rms_radius`` and
    ``geo_radius`` (about the centroid, valid rays only), counts and the
    full :class:`TraceResult` as ``trace``.
    """
    sysm = _resolve_system(system)
    wl = _resolve_wavelength(sysm, wavelength)
    pt = [float(v) for v in point]
    if len(pt) not in (2, 3):
        raise ValueError("point must be (x, y) or (x, y, z)")
    if frame not in ("lens", "object"):
        raise ValueError('frame must be "lens" or "object"')
    t0 = sysm.object.thickness
    if len(pt) == 2 or frame == "object":
        if not math.isfinite(t0):
            raise ValueError("object is at infinity: give (x, y, z) with frame='lens'")
        z = -t0 + (pt[2] if len(pt) == 3 else 0.0)
    else:
        z = pt[2]
    if not math.isfinite(z):
        raise ValueError("point z must be finite (use trace_rays with field angles for infinite objects)")
    x, y = pt[0], pt[1]

    gen = RayGenerator(sysm, wl, aiming)
    if abs(z - gen.z_ep) < 1e-9 * max(1.0, abs(gen.z_ep)):
        raise ValueError("the point lies on the entrance pupil plane; rays cannot be aimed from there")
    if px is None or py is None:
        px, py = pupil_grid(pattern, n, seed=seed)
    px, py = np.broadcast_arrays(np.atleast_1d(np.asarray(px, float)), np.atleast_1d(np.asarray(py, float)))
    px, py = px.ravel() * size, py.ravel() * size

    spec = ("point", x, y, z)
    ax, ay = gen.aim(spec, np.concatenate([[0.0], px]), np.concatenate([[0.0], py]))
    P, D, opl0 = gen._rays_from_aim(spec, ax, ay)
    # bring rays from very distant points up to the lens through the homogeneous
    # object space before intersecting, so surface 1 is not solved at 1e10 mm
    z_start = min(gen.z_ep, 0.0) - 10.0 * max(gen.r_ep, 1.0)
    if z < z_start:
        t = (z_start - z) / D[:, 2]
        P = P + t[:, None] * D
        opl0 = opl0 + gen.n0 * t
    chief = trace(sysm, P[:1], D[:1], wl, opl0[:1], apertures=False)
    r = trace(sysm, P[1:], D[1:], wl, opl0[1:], apertures=apertures)

    valid = r.valid
    X, Y = r.x[valid], r.y[valid]
    if X.size:
        cx, cy = float(X.mean()), float(Y.mean())
        r2 = (X - cx) ** 2 + (Y - cy) ** 2
        rms, geo, centroid = float(np.sqrt(r2.mean())), float(np.sqrt(r2.max())), (cx, cy)
    else:
        rms = geo = float("nan")
        centroid = None
    return {
        "point": (x, y, z),
        "wavelength": wl,
        "pattern": pattern,
        "size": size,
        "px": px,
        "py": py,
        "x": r.x.copy(),
        "y": r.y.copy(),
        "z": r.z.copy(),
        "positions": r.image.copy(),
        "directions": r.direction.copy(),
        "valid": valid,
        "vignetted": ~valid,
        "status": r.status.copy(),
        "error_surface": r.error_surface.copy(),
        "reasons": [ERROR_NAMES[int(s)] for s in r.status],
        "chief": (float(chief.x[0]), float(chief.y[0])) if chief.status[0] == OK else None,
        "centroid": centroid,
        "rms_radius": rms,
        "geo_radius": geo,
        "n_launched": int(px.size),
        "n_valid": int(valid.sum()),
        "trace": r,
    }
