"""Geometric/visual analyses: layout ray paths, surface profiles and sag,
footprint diagrams, through-focus and full-field spot diagrams, interferograms."""

from __future__ import annotations

import math

import numpy as np

from ..pupil import pupil_grid
from ..raytrace import trace_rays
from .common import defocused, resolve_field, resolve_wavelengths
from .spot import spot_diagram


def _surface_extent(system, i, default=None):
    s = system.surfaces[i]
    if s.semi_diameter is not None:
        return s.semi_diameter
    return default


def surface_profiles(system, n: int = 41, plane: str = "y"):
    """Global (y or x, z) polylines of every non-dummy surface for layout plots.

    Semi-diameters come from the surfaces or, when unset, from a real ray
    trace of all fields (``update_semi_diameters`` without modifying the system).
    """
    sd = None
    if any(s.semi_diameter is None for s in system.surfaces[1:]):
        sd = system.copy().update_semi_diameters()
    frames = system.surface_frames()
    out = []
    for i, s in enumerate(system.surfaces):
        if i == 0 or s.is_coordinate_break or frames[i] is None:
            continue
        r = s.semi_diameter if s.semi_diameter is not None else (sd[i] if sd is not None else 0.0)
        t = np.linspace(-r, r, n)
        x, y = (np.zeros(n), t) if plane == "y" else (t, np.zeros(n))
        z = s.sag(x, y)
        R, O = frames[i]
        P = np.stack([x, y, z], axis=1) @ R.T + O
        out.append({"surface": i, "points": P, "semi_diameter": float(r),
                    "mirror": system.library.resolve(s.material).is_mirror if s.material else False})
    return out


def layout(system, fields=None, wavelengths=None, n_rays: int = 7, plane: str = "y", include_object: bool = False):
    """Ray paths in global coordinates for 2-D/3-D layout plots.

    Returns ``rays``: list of dicts (field index, wavelength, ``path`` array
    (S, N, 3)), and ``surfaces`` from :func:`surface_profiles`.  Fans lie in the
    ``plane`` ("y" meridional, "x" sagittal, "3d" for a ring + cross).
    """
    fields = range(len(system.fields)) if fields is None else fields
    wls = resolve_wavelengths(system, wavelengths if wavelengths is not None else [system.primary])
    p = np.linspace(-1, 1, n_rays)
    if plane == "y":
        px, py = np.zeros(n_rays), p
    elif plane == "x":
        px, py = p, np.zeros(n_rays)
    else:
        th = np.linspace(0, 2 * np.pi, n_rays, endpoint=False)
        px, py = np.concatenate([[0.0], np.cos(th)]), np.concatenate([[0.0], np.sin(th)])
    rays = []
    for f in fields:
        hx, hy = resolve_field(system, f)
        for w in wls:
            r = trace_rays(system, hx, hy, px, py, wavelength=w)
            G = r.global_positions()
            start = 0 if (include_object or system.object_at_infinity) else 1
            path = G[start:]
            # keep rays only up to the surface where they failed
            for k in range(path.shape[1]):
                if not r.valid[k] and r.error_surface[k] >= 0:
                    path[r.error_surface[k] - start + 1:, k] = np.nan
            rays.append({"field": f, "wavelength": w, "path": path, "valid": r.valid})
    return {"rays": rays, "surfaces": surface_profiles(system, plane="y" if plane != "x" else "x")}


def surface_sag(surface, semi_diameter=None, n: int = 101, best_fit: str = "vertex-edge"):
    """Sag of one surface: 2-D map, y cross-section and departure from a best-fit sphere.

    ``best_fit``: "vertex-edge" (sphere through vertex and edge at the
    semi-diameter, Zemax's default) or "lsq" (least-squares curvature through
    the vertex).  Returns ``x``, ``y``, ``sag`` (n x n, NaN outside),
    ``profile``, ``bfs_radius``, ``departure`` (map) and its ``max_departure``.
    """
    r = semi_diameter if semi_diameter is not None else (surface.semi_diameter or 1.0)
    v = np.linspace(-r, r, n)
    X, Y = np.meshgrid(v, v)
    m = X**2 + Y**2 <= r * r
    Z = np.full(X.shape, np.nan)
    Z[m] = surface.sag(X[m], Y[m])
    prof = surface.sag(np.zeros(n), v)

    def sphere(c, r2):
        return c * r2 / (1 + np.sqrt(np.maximum(1 - c * c * r2, 0)))

    r2 = X[m] ** 2 + Y[m] ** 2
    if best_fit == "lsq":
        c = surface.paraxial_curvature
        for _ in range(30):  # Gauss-Newton on curvature
            f = sphere(c, r2)
            h = 1e-9 * max(1.0, abs(c))
            J = (sphere(c + h, r2) - f) / h
            dc = np.sum(J * (Z[m] - f)) / max(np.sum(J * J), 1e-300)
            c += dc
            if abs(dc) < 1e-15:
                break
    else:
        ze = float(surface.sag(np.array([0.0]), np.array([r]))[0])
        c = 0.0 if ze == 0 else 2 * ze / (r * r + ze * ze)
    dep = np.full(X.shape, np.nan)
    dep[m] = Z[m] - sphere(c, r2)
    return {"x": v, "y": v, "sag": Z, "profile": prof, "bfs_radius": math.inf if c == 0 else 1 / c,
            "departure": dep, "max_departure": float(np.nanmax(dep) - np.nanmin(dep))}


def footprint(system, surface: int, fields=None, wavelengths=None, n_ring: int = 64, grid: int = 0):
    """Beam footprint on a surface (local x, y) for each field and wavelength.

    Pupil-edge rays are traced (plus a square grid of ``grid`` x ``grid`` if
    >0).  Returns per-beam point sets, the overall extent and the surface's
    clear semi-diameter for comparison.
    """
    fields = range(len(system.fields)) if fields is None else fields
    wls = resolve_wavelengths(system, wavelengths)
    th = np.linspace(0, 2 * np.pi, n_ring, endpoint=False)
    px, py = np.cos(th), np.sin(th)
    if grid:
        gx, gy = pupil_grid("square", grid)
        px, py = np.concatenate([px, gx]), np.concatenate([py, gy])
    beams = []
    allx, ally = [], []
    for f in fields:
        hx, hy = resolve_field(system, f)
        for w in wls:
            r = trace_rays(system, hx, hy, px, py, wavelength=w, last=surface)
            ok = r.valid
            x, y = r.positions[-1, ok, 0], r.positions[-1, ok, 1]
            beams.append({"field": f, "wavelength": w, "x": x, "y": y, "vignetted": int((~ok).sum())})
            allx.append(x)
            ally.append(y)
    X, Y = np.concatenate(allx), np.concatenate(ally)
    s = system.surfaces[surface]
    return {"surface": surface, "beams": beams, "x_range": (float(X.min()), float(X.max())),
            "y_range": (float(Y.min()), float(Y.max())), "max_radius": float(np.hypot(X, Y).max()),
            "semi_diameter": s.semi_diameter}


def through_focus_spot(system, field=0, wavelengths=None, focus_range=None, steps: int = 7, **kw):
    """Spot diagrams at image-plane shifts ``focus`` (lens units)."""
    if focus_range is None:
        focus_range = 4 * max(spot_diagram(system, field, wavelengths)["rms_radius"], 1e-6) * \
            2 * system.paraxial().working_fnum
    dz = np.linspace(-focus_range / 2, focus_range / 2, steps)
    spots = [spot_diagram(defocused(system, d), field, wavelengths, **kw) for d in dz]
    return {"focus": dz, "spots": spots, "rms_radius": np.array([s["rms_radius"] for s in spots])}


def full_field_spot(system, wavelengths=None, n_fields: int = 5, axis: str = "y", **kw):
    """Spot diagrams at evenly spaced field points along one axis."""
    h = np.linspace(0, 1, n_fields)
    pts = [(0.0, v) if axis == "y" else (v, 0.0) for v in h]
    spots = [spot_diagram(system, p, wavelengths, **kw) for p in pts]
    return {"field": h, "spots": spots, "rms_radius": np.array([s["rms_radius"] for s in spots])}


def interferogram(system, field=0, wavelength=None, n: int = 128, tilt_x: float = 0.0, tilt_y: float = 0.0,
                  scale: float = 1.0, double_pass: bool = False):
    """Simulated interferogram (fringe intensity map) of the wavefront.

    ``tilt_x/y`` add reference tilt in waves across the pupil radius,
    ``scale`` multiplies the OPD (2 for a double-pass test).
    """
    from .fans import wavefront
    w = wavefront(system, field, wavelength, n)
    X, Y = np.meshgrid(w["px"], w["py"])
    k = (2.0 if double_pass else 1.0) * scale
    phase = 2 * np.pi * (k * w["W"] + tilt_x * X + tilt_y * Y)
    I = 0.5 * (1 + np.cos(phase))
    return {"px": w["px"], "py": w["py"], "intensity": I, "wavefront": w["W"]}
