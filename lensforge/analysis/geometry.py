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
    axis = np.array([0.0, 1.0, 0.0]) if plane == "y" else np.array([1.0, 0.0, 0.0])
    out = []
    for i, s in enumerate(system.surfaces):
        if i == 0 or s.is_coordinate_break or frames[i] is None:
            continue
        r = s.semi_diameter if s.semi_diameter is not None else (sd[i] if sd is not None else 0.0)
        t = np.linspace(-r, r, n)
        R, O = frames[i]
        # cut the surface along the local direction that lies in the global plot
        # plane, so a surface rotated about z (e.g. after a 90 deg tilt-z break)
        # is still drawn as its true cross-section rather than edge-on
        u = (R.T @ axis)[:2]
        if np.hypot(*u) < 1e-9:  # plot axis along the surface normal: use the local axis
            u = axis[:2]
        u = u / np.hypot(*u)
        x, y = t * u[0], t * u[1]
        z = s.sag(x, y)
        P = np.stack([x, y, z], axis=1) @ R.T + O
        out.append({"surface": i, "points": P, "semi_diameter": float(r),
                    "mirror": system.library.resolve(s.material).is_mirror if s.material else False})
    return out


def ray_paths(trace, start: int = 1):
    """Global (S', N, 3) ray paths of a :func:`trace_rays` result for layout plots.

    ``start`` is the first surface drawn (0 includes the object).  Points after
    the surface where a ray failed are NaN.  Coordinate breaks are left out:
    the intercept on a break's plane lies on the straight ray between the real
    surfaces either side of it, but can sit beyond the next surface (a break
    in front of a tilted element or fold mirror), which would draw a stray
    stub poking through the surface.  The break has no optical effect, so the
    straight line between the neighbouring real surfaces is the true path.
    """
    path = trace.global_positions()[start:]
    for k in range(path.shape[1]):
        if not trace.valid[k] and trace.error_surface[k] >= 0:
            path[trace.error_surface[k] - start + 1:, k] = np.nan
    keep = [k for k in range(path.shape[0])
            if k + start == 0 or not trace.system.surfaces[k + start].is_coordinate_break]
    return path[keep]


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
            path = ray_paths(r, 0 if (include_object or system.object_at_infinity) else 1)
            rays.append({"field": f, "wavelength": w, "path": path, "valid": r.valid})
    return {"rays": rays, "surfaces": surface_profiles(system, plane="y" if plane != "x" else "x")}


def _section(s, R, O, u, r, n):
    """Global points of surface ``s`` along the local direction ``u`` (unit 2-vector), from -r to r."""
    t = np.linspace(-r, r, n)
    x, y = t * u[0], t * u[1]
    return np.stack([x, y, s.sag(x, y)], axis=1) @ R.T + O


def surface_wireframes(system, n_rim: int = 64, n_section: int = 33):
    """3-D wireframe of every real surface (coordinate breaks left out) in global coordinates.

    Each entry has the ``rim`` (closed polyline at the semi-diameter, ``n_rim`` + 1 points), the
    two ``sections`` along the surface's local x and y axes, ``semi_diameter`` and ``mirror``.
    Semi-diameters come from the surfaces or, when unset, from a real ray trace of all fields
    (as :func:`surface_profiles`).  Surfaces are placed with :meth:`System.surface_frames`, so
    decentres and tilts of coordinate breaks are followed exactly."""
    sd = None
    if any(s.semi_diameter is None for s in system.surfaces[1:]):
        sd = system.copy().update_semi_diameters()
    frames = system.surface_frames()
    th = np.linspace(0, 2 * np.pi, n_rim + 1)
    out = []
    for i, s in enumerate(system.surfaces):
        if i == 0 or s.is_coordinate_break or frames[i] is None:
            continue
        r = s.semi_diameter if s.semi_diameter is not None else (sd[i] if sd is not None else 0.0)
        r = float(r or 0.0)
        R, O = frames[i]
        x, y = r * np.cos(th), r * np.sin(th)
        rim = np.stack([x, y, s.sag(x, y)], axis=1) @ R.T + O
        sections = [_section(s, R, O, (1.0, 0.0), r, n_section), _section(s, R, O, (0.0, 1.0), r, n_section)]
        out.append({"surface": i, "rim": rim, "sections": sections, "semi_diameter": r,
                    "mirror": system.library.resolve(s.material).is_mirror if s.material else False})
    return out


def lens_edges(system, wireframes, n_edges: int = 8):
    """Edge lines of each element: straight lines joining the rims of consecutive surfaces that
    bound glass, at ``n_edges`` points around the rim.  Coordinate breaks in between (a wedge, a
    tilted back face) are skipped: the glass carries on through them to the next real surface."""
    by = {w["surface"]: w for w in wireframes}
    out = []
    for i, a in by.items():
        n = i + 1
        while n < len(system.surfaces) and system.surfaces[n].is_coordinate_break:
            n += 1
        b = by.get(n)
        if b is None or not system.surfaces[i].material:
            continue
        m = system.library.resolve(system.surfaces[i].material)
        if m.is_mirror or getattr(m, "nd", None) == 1.0 or a["semi_diameter"] <= 0 or b["semi_diameter"] <= 0:
            continue
        ra, rb = a["rim"][:-1], b["rim"][:-1]
        for k in np.linspace(0, len(ra), n_edges, endpoint=False).astype(int):
            out.append({"from": i, "to": n, "points": np.stack([ra[k], rb[k]])})
    return out


LAYOUT_3D_RAYS = ("y_fan", "x_fan", "fans", "ring", "grid")


def _pupil_3d(rays, n):
    p = np.linspace(-1, 1, n)
    z = np.zeros(n)
    if rays == "y_fan":
        return z, p
    if rays == "x_fan":
        return p, z
    if rays == "fans":
        m = p != 0  # the chief ray once
        return np.concatenate([z, p[m]]), np.concatenate([p, z[m]])
    if rays == "ring":
        th = np.linspace(0, 2 * np.pi, n, endpoint=False)
        return np.concatenate([[0.0], np.cos(th)]), np.concatenate([[0.0], np.sin(th)])
    if rays == "grid":
        X, Y = np.meshgrid(p, p)
        m = X**2 + Y**2 <= 1 + 1e-9
        return X[m], Y[m]
    raise ValueError(f"rays must be one of {', '.join(LAYOUT_3D_RAYS)}")


def layout_3d(system, fields=None, wavelengths=None, n_rays: int = 7, rays: str = "fans",
              include_object: bool = False, n_rim: int = 64, n_edges: int = 8):
    """Everything a 3-D layout draws, in global coordinates (surface 1's vertex at the origin).

    ``rays`` picks the pupil sampling: "y_fan", "x_fan", "fans" (both fans), "ring" (``n_rays``
    rays round the pupil edge plus the chief ray) or "grid" (an ``n_rays`` x ``n_rays`` square grid
    clipped to the pupil).  Returns ``surfaces`` (:func:`surface_wireframes`), ``edges``
    (:func:`lens_edges`), ``rays`` (field index, wavelength, ``path`` (S, N, 3) with NaN after a
    failed ray, ``valid``) and ``bounds`` (lo, hi corners of everything drawn).  Coordinate breaks
    are followed exactly (see :func:`ray_paths`), so folded and tilted systems come out in 3-D as
    they are.  Plot it with :func:`lensforge.plot.layout_3d`.
    """
    fields = range(len(system.fields)) if fields is None else fields
    wls = resolve_wavelengths(system, wavelengths if wavelengths is not None else [system.primary])
    px, py = _pupil_3d(rays, max(int(n_rays), 1))
    out_rays = []
    start = 0 if (include_object or system.object_at_infinity) else 1
    for f in fields:
        hx, hy = resolve_field(system, f)
        for w in wls:
            r = trace_rays(system, hx, hy, px, py, wavelength=w)
            out_rays.append({"field": f, "wavelength": w, "path": ray_paths(r, start), "valid": r.valid})
    surfaces = surface_wireframes(system, n_rim=n_rim)
    edges = lens_edges(system, surfaces, n_edges=n_edges)
    pts = [s["rim"] for s in surfaces] + [r["path"].reshape(-1, 3) for r in out_rays]
    P = np.concatenate(pts) if pts else np.zeros((1, 3))
    P = P[np.all(np.isfinite(P), axis=1)]
    if not len(P):
        P = np.zeros((1, 3))
    return {"surfaces": surfaces, "edges": edges, "rays": out_rays, "pattern": rays,
            "bounds": (P.min(axis=0), P.max(axis=0)), "units": system.units}


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
