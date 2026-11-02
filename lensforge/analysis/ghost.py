"""Ghost analysis for sequential systems (two-bounce ghost reflections).

A ghost is light that is reflected at one surface ``i``, travels backwards,
is reflected again at an earlier surface ``j`` (j < i) and then goes forward
to the image.  Every pair of refracting surfaces, optionally including the
image surface (a reflective detector), makes one ghost.

The analysis builds an ordinary sequential "ghost system" for each pair by
unfolding the path: surfaces 1..i-1, a mirror copy of i, the surfaces i-1..j+1
traversed backwards, a mirror copy of j, then surfaces j+1..image again (the
same method as commercial ghost focus generators).  Each ghost system can be
traced and analysed like any other lens with the rest of lensforge.

Functions
---------
``ghost_system(system, i, j)``    the unfolded sequential system of one ghost
``ghost_pairs(system)``           all (i, j) pairs that make a ghost
``ghost_trace(system, i, j, ...)`` real rays (from the original pupil) along a ghost path
``ghost_focus(system, ...)``      paraxial + real-ray table of every ghost (Ghost Focus Generator)
``ghost_image(system, ...)``      detector irradiance of all ghosts with angle-dependent Fresnel weights
``ghost_layout(system, i, j)``    ghost ray paths in global coordinates for layout plots
``format_ghost_table(result)``    text report of :func:`ghost_focus`

Reflectances are uncoated Fresnel values (unpolarised) from the media on both
sides of the surface, unless ``coating`` gives a reflectance: one number for
every surface or ``{surface: R}`` for some of them.  The image surface has no
index step, so it only makes ghosts when ``image_reflectance`` > 0.
"""

from __future__ import annotations

import math
from typing import Dict, Optional, Union

import numpy as np

from ..paraxial import ParaxialAnalysis, ynu_trace
from ..raytrace import RayGenerator, trace
from ..pupil import pupil_grid
from .common import resolve_field

Coating = Union[None, float, Dict[int, float]]


# ---------------------------------------------------------------------------
# Building the unfolded ghost system
# ---------------------------------------------------------------------------

def _medium_names(system):
    """Material name of the medium after every surface (mirrors and coordinate breaks keep the medium)."""
    out = []
    cur = "AIR"
    for k, s in enumerate(system.surfaces):
        m = s.material
        if s.is_coordinate_break:
            pass
        elif m is not None and str(m).upper() == "MIRROR":
            pass
        elif m in (None, ""):
            cur = "AIR"
        else:
            cur = m
        out.append(cur)
    return out


def _check_pair(system, i, j, allow_image=True):
    last = system.image_index if allow_image else system.image_index - 1
    if not (1 <= j < i <= last):
        raise ValueError(f"ghost pair needs 1 <= j < i <= {last}, got i={i}, j={j}")
    _, mirror, _ = system.media(system.primary)
    for k in range(j, i + 1):
        s = system.surfaces[k]
        if s.is_coordinate_break:
            raise NotImplementedError(f"surface {k} is a coordinate break; ghosts through tilted or decentred "
                                      "groups are not supported (use the non-sequential tracer)")
        if mirror[k]:
            raise ValueError(f"surface {k} is a mirror; ghost pairs must lie between refracting surfaces")
        if s.has_deflect or s.has_phase:
            raise NotImplementedError(f"surface {k} ({s.kind}) is a phase or ideal surface; ghosts through it "
                                      "are not supported")


def ghost_system(system, i: int, j: int):
    """The unfolded sequential system of the ghost reflected at surface ``i`` and then at ``j`` (j < i).

    Surface ``k`` of the result traces back to surface ``ghost.ghost_map[k]`` of
    the original.  The entrance pupil (aperture, fields, wavelengths, stop) is
    copied from the original, so its rays can be launched with the original
    lens's :class:`RayGenerator` (see :func:`ghost_trace`).
    """
    _check_pair(system, i, j)
    g = system.copy()
    g.multiconfig = None
    for attr in ("variables", "solves", "merit_function"):
        if hasattr(g, attr):
            setattr(g, attr, [] if attr != "merit_function" else None)
    src = system.surfaces
    med = _medium_names(system)
    new, gmap = [], []

    def add(k, **changes):
        s = src[k].copy()
        s.stop = False
        for key, v in changes.items():
            setattr(s, key, v)
        new.append(s)
        gmap.append(k)
        return s

    for k in range(0, i):  # forward pass up to surface i
        add(k)
    t_back = -src[i - 1].thickness
    m = add(i, material="MIRROR", thickness=t_back)
    m.comment = f"ghost reflection {i}"
    for k in range(i - 1, j, -1):  # backwards through i-1 .. j+1
        add(k, material=med[k - 1], thickness=-src[k - 1].thickness)
    m = add(j, material="MIRROR", thickness=src[j].thickness)
    m.comment = f"ghost reflection {j}"
    for k in range(j + 1, len(src)):  # forward again to the image
        add(k)
    g.surfaces = new
    g.ghost_map = gmap
    g.ghost_pair = (i, j)
    st = system.stop_index
    # stop on its first appearance along the path (same entrance pupil when the stop is before i)
    first = gmap.index(st) if st in gmap else 1
    g.surfaces[first].stop = True
    if system.aperture_type in ("IMAGE_FNUM", "WORKING_FNUM"):
        g.set_aperture("EPD", system.paraxial().epd)
    g.name = f"{system.name or 'Lens'}: ghost {i}-{j}"
    return g


def ghost_pairs(system, include_image: bool = False):
    """All (i, j) surface pairs (i > j) that can make a ghost."""
    _, mirror, _ = system.media(system.primary)
    last = system.image_index if include_image else system.image_index - 1
    ok = [k for k in range(1, last + 1)
          if not system.surfaces[k].is_coordinate_break and not mirror[k]
          and not system.surfaces[k].has_deflect and not system.surfaces[k].has_phase]
    pairs = []
    for i in ok:
        for j in ok:
            if j < i:
                try:
                    _check_pair(system, i, j)
                except (ValueError, NotImplementedError):
                    continue
                pairs.append((i, j))
    return pairs


# ---------------------------------------------------------------------------
# Reflectances
# ---------------------------------------------------------------------------

def _fresnel_R(n1, n2, cos_i):
    """Unpolarised power reflectance (TIR gives 1)."""
    n1 = np.asarray(n1, float)
    n2 = np.asarray(n2, float)
    ci = np.clip(np.abs(np.asarray(cos_i, float)), 0.0, 1.0)
    st2 = (n1 / n2) ** 2 * (1 - ci * ci)
    tir = st2 >= 1
    ct = np.sqrt(np.clip(1 - st2, 0.0, 1.0))
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = (n1 * ci - n2 * ct) / (n1 * ci + n2 * ct)
        rp = (n2 * ci - n1 * ct) / (n2 * ci + n1 * ct)
    R = 0.5 * (rs * rs + rp * rp)
    return np.where(tir, 1.0, np.nan_to_num(R, nan=1.0))


def surface_reflectance(system, k: int, wavelength=None, coating: Coating = None, image_reflectance: float = 0.0,
                        cos_i=1.0):
    """Reflectance of surface ``k`` (normal incidence unless ``cos_i`` given)."""
    if isinstance(coating, dict) and k in coating:
        return np.broadcast_to(float(coating[k]), np.shape(cos_i)) * 1.0
    if coating is not None and not isinstance(coating, dict):
        return np.broadcast_to(float(coating), np.shape(cos_i)) * 1.0
    if k == system.image_index:
        return np.broadcast_to(float(image_reflectance), np.shape(cos_i)) * 1.0
    wl = system.primary if wavelength is None else wavelength
    n, _, _ = system.media(wl)
    return _fresnel_R(n[k - 1], n[k], cos_i)


# ---------------------------------------------------------------------------
# Tracing
# ---------------------------------------------------------------------------

def ghost_trace(system, i: int, j: int, hx=0.0, hy=0.0, px=0.0, py=0.0, wavelength=None, apertures=True,
                ghost=None):
    """Trace rays defined on the *original* system's pupil along the ghost path i -> j.

    Returns the :class:`TraceResult` of the ghost system (``result.system``).
    """
    g = ghost if ghost is not None else ghost_system(system, i, j)
    gen = RayGenerator(system, wavelength)
    P, D, opl0 = gen.rays(hx, hy, px, py)
    return trace(g, P, D, gen.wavelength, opl0, apertures=apertures)


def _reflectance_j(system, j, wavelength, coating, cos_i):
    """Reflectance at j for light travelling backwards (from the medium after j onto the one before)."""
    if coating is not None and (not isinstance(coating, dict) or j in coating):
        return surface_reflectance(system, j, wavelength, coating, 0.0, cos_i)
    n, _, _ = system.media(wavelength)
    return _fresnel_R(n[j], n[j - 1], cos_i)


def _transmittance(n1, n2, k, coating, cos_i):
    if coating is not None and not isinstance(coating, dict):
        return 1.0 - float(coating)
    if isinstance(coating, dict) and k in coating:
        return 1.0 - float(coating[k])
    return 1.0 - _fresnel_R(n1, n2, cos_i)


def _path_weights(system, g, r, wavelength, coating, image_reflectance, fresnel_losses=True):
    """Per-ray power weight along a ghost path: R_i * R_j * product of transmittances."""
    i, j = g.ghost_pair
    mi, mj = i, 2 * i - j  # indices of the two ghost reflections in the unfolded system
    n_g, mirror_g, _ = g.media(wavelength)
    w = np.ones(r.n_rays)
    for k in range(1, g.image_index):
        s = g.surfaces[k]
        if s.is_coordinate_break:
            continue
        cos_i = np.nan_to_num(np.abs(np.einsum("ij,ij->i", r.directions[k - 1], r.normals[k])), nan=1.0)
        if k == mi:
            w = w * surface_reflectance(system, i, wavelength, coating, image_reflectance, cos_i)
        elif k == mj:
            w = w * _reflectance_j(system, j, wavelength, coating, cos_i)
        elif fresnel_losses and not mirror_g[k]:
            w = w * _transmittance(n_g[k - 1], n_g[k], g.ghost_map[k], coating, cos_i)
    return w


def _airy_radius(system, wavelength):
    par = ParaxialAnalysis(system, wavelength)
    try:
        fn = par.working_fnum
    except Exception:  # pragma: no cover - defensive
        fn = math.nan
    if not math.isfinite(fn) or fn <= 0:
        fn = 1.0
    return 1.22 * wavelength * system.wavelength_scale * abs(fn)


def _paraxial_ghost(system, g, wavelength):
    """Paraxial marginal ray of the original pupil traced through the ghost system."""
    par = ParaxialAnalysis(system, wavelength)
    r_ep = par.entrance_pupil_radius
    if system.object_at_infinity:
        y0, nu0 = r_ep, 0.0
    else:
        t0 = system.object.thickness
        u = 1.0 / (t0 + par.entrance_pupil_position)
        y0, nu0 = u * t0 * r_ep, par.n_object * u * r_ep
    last = g.image_index - 1
    Y, NU = ynu_trace(g, y0, nu0, 1, last, wavelength)
    _, _, ns = g.media(wavelength)
    n_img = ns[last]
    y, nu = float(Y[-1]), float(NU[-1])
    t = g.surfaces[last].thickness
    y_img = y + t * nu / n_img
    u = nu / n_img
    focus = math.inf if abs(u) < 1e-300 else -y / u  # from the last surface
    return {"marginal_height": abs(y_img), "focus_distance": focus - t,
            "fnum": math.inf if abs(u) < 1e-300 else 1.0 / (2 * abs(u))}


def ghost_focus(system, wavelength=None, coating: Coating = None, include_image: bool = False,
                image_reflectance: float = 0.04, real_rays: bool = True, n_rings: int = 6, sort: str = "irradiance"):
    """Ghost Focus Generator: one row per two-bounce ghost.

    For each pair (i, j) the paraxial marginal ray of the original entrance
    pupil is traced through the ghost path, giving the ghost focus position
    relative to the image surface (``focus_distance``, positive behind it),
    the ghost beam radius on the image surface (``marginal_height``) and its
    F-number.  ``R`` = R_i * R_j is the fraction of the beam power in the ghost
    (normal-incidence reflectances, ignoring other losses).

    ``irradiance_ratio`` estimates the ghost's peak irradiance relative to the
    peak of the diffraction-limited image: R spread over a disc of the ghost
    beam radius versus the Airy disc (1 for a ghost focused on the image, much
    less for out-of-focus ghosts).  It is an estimate for ranking ghosts.

    With ``real_rays`` an on-axis polar grid of real rays is traced along each
    path: ``rms_radius`` and ``max_radius`` of the ghost footprint on the image
    and ``throughput`` (fraction of rays that get through; ghost light leaving
    clear apertures or totally reflected is lost).

    ``sort``: "irradiance" (brightest first), "R", "focus" or "pairs".
    """
    wl = system.primary if wavelength is None else wavelength
    pairs = ghost_pairs(system, include_image=include_image and image_reflectance > 0)
    rows = []
    airy = _airy_radius(system, wl)
    if real_rays:
        px, py = pupil_grid("hexapolar", n_rings)
    for (i, j) in pairs:
        g = ghost_system(system, i, j)
        Ri = float(surface_reflectance(system, i, wl, coating, image_reflectance))
        Rj = float(_reflectance_j(system, j, wl, coating, 1.0))
        par = _paraxial_ghost(system, g, wl)
        R = Ri * Rj
        rad = max(par["marginal_height"], airy)
        row = {"i": i, "j": j, "R_i": Ri, "R_j": Rj, "R": R, **par,
               "irradiance_ratio": R * (airy / rad) ** 2}
        if real_rays:
            t = ghost_trace(system, i, j, 0.0, 0.0, px, py, wl, ghost=g)
            v = t.valid
            row["throughput"] = float(v.mean()) if v.size else 0.0
            if v.any():
                x, y = t.x[v], t.y[v]
                cx, cy = x.mean(), y.mean()
                rr = np.hypot(x - cx, y - cy)
                row["rms_radius"] = float(np.sqrt(np.mean(rr * rr)))
                row["max_radius"] = float(np.hypot(x, y).max())
            else:
                row["rms_radius"] = row["max_radius"] = math.nan
        rows.append(row)
    key = {"irradiance": lambda r: -r["irradiance_ratio"], "R": lambda r: -r["R"],
           "focus": lambda r: abs(r["focus_distance"]), "pairs": lambda r: (r["i"], r["j"])}[sort]
    rows.sort(key=key)
    out = {"rows": rows, "wavelength": wl, "airy_radius": airy, "units": system.units,
           "pairs": np.array([(r["i"], r["j"]) for r in rows], dtype=int).reshape(-1, 2)}
    for name in ("R", "focus_distance", "marginal_height", "irradiance_ratio"):
        out[name] = np.array([r[name] for r in rows])
    return out


def format_ghost_table(result) -> str:
    """Text table of :func:`ghost_focus`."""
    u = result["units"]
    real = bool(result["rows"]) and "rms_radius" in result["rows"][0]
    head = (f"{'Pair':>9} {'R_i':>8} {'R_j':>8} {'R':>10} {'Focus from image':>17} {'Beam radius':>12} "
            f"{'F/#':>8} {'Irr. ratio':>11}")
    if real:
        head += f" {'RMS (real)':>11} {'Through':>8}"
    lines = [f"Ghost focus analysis, wavelength {result['wavelength']:.6g} um "
             f"(lengths in {u}; Airy radius {result['airy_radius']:.4g})",
             "Pair i-j: light reflects at surface i, then at surface j, then goes on to the image.",
             "Irr. ratio: ghost peak irradiance / diffraction-limited image peak (estimate).", "", head]
    for r in result["rows"]:
        fd = "inf" if not math.isfinite(r["focus_distance"]) else f"{r['focus_distance']:.6g}"
        fn = "inf" if not math.isfinite(r["fnum"]) else f"{r['fnum']:.3g}"
        s = (f"{r['i']:>4}-{r['j']:<4} {r['R_i']:8.4f} {r['R_j']:8.4f} {r['R']:10.3e} {fd:>17} "
             f"{r['marginal_height']:12.5g} {fn:>8} {r['irradiance_ratio']:11.3e}")
        if real:
            s += f" {r['rms_radius']:11.4g} {r['throughput']:8.2%}"
        lines.append(s)
    if not result["rows"]:
        lines.append("  (no surface pairs: the lens needs at least two refracting surfaces)")
    return "\n".join(lines)


def ghost_image(system, field=0, wavelength=None, coating: Coating = None, include_image: bool = False,
                image_reflectance: float = 0.04, n_rays: int = 64, pixels: int = 101,
                half_width: Optional[float] = None, include_nominal: bool = True, fresnel_losses: bool = True,
                pairs=None):
    """Irradiance on the image surface from all two-bounce ghosts of one field point.

    A square grid of ``n_rays`` x ``n_rays`` rays across the entrance pupil
    (total power 1) is traced along every ghost path; each ray carries the
    angle-dependent unpolarised Fresnel reflectances at its two reflections
    (or the ``coating`` reflectance) and, with ``fresnel_losses``, the
    transmittances of the other surfaces.  Ray powers are binned on a
    ``pixels`` x ``pixels`` grid of half-width ``half_width`` (default: the
    image semi-diameter or the paraxial image height, +10 %).

    Returns ``ghost`` and ``nominal`` irradiance maps (power fraction per unit
    area, lens units), ``extent``, per-pair ``pair_power`` (power reaching the
    image) and the ``pairs`` traced.
    """
    wl = system.primary if wavelength is None else wavelength
    hx, hy = resolve_field(system, field)
    v = (np.arange(n_rays) + 0.5) / n_rays * 2 - 1
    PX, PY = np.meshgrid(v, v)
    inside = PX**2 + PY**2 <= 1.0
    px, py = PX[inside], PY[inside]
    w0 = 1.0 / px.size
    if half_width is None:
        par = ParaxialAnalysis(system, wl)
        hw = abs(system.image.semi_diameter or 0.0)
        if hw <= 0:
            try:
                hw = abs(par.paraxial_image_height)
            except Exception:  # pragma: no cover
                hw = 0.0
        if not (hw > 0 and math.isfinite(hw)):
            hw = par.entrance_pupil_radius
        half_width = 1.1 * hw
    edges = np.linspace(-half_width, half_width, pixels + 1)
    area = (edges[1] - edges[0]) ** 2

    def bin_(x, y, w):
        H, _, _ = np.histogram2d(y, x, bins=[edges, edges], weights=w)
        return H / area

    if pairs is None:
        pairs = ghost_pairs(system, include_image=include_image and image_reflectance > 0)
    ghost = np.zeros((pixels, pixels))
    pair_power = []
    for (i, j) in pairs:
        g = ghost_system(system, i, j)
        t = ghost_trace(system, i, j, hx, hy, px, py, wl, ghost=g)
        wt = _path_weights(system, g, t, wl, coating, image_reflectance, fresnel_losses) * w0
        ok = t.valid & np.isfinite(wt)
        pair_power.append(float(wt[ok].sum()))
        if ok.any():
            ghost += bin_(t.x[ok], t.y[ok], wt[ok])
    nominal = np.zeros((pixels, pixels))
    nominal_power = 0.0
    if include_nominal:
        from ..raytrace import trace_rays
        t = trace_rays(system, hx, hy, px, py, wavelength=wl)
        wt = np.full(t.n_rays, w0)
        if fresnel_losses:
            n, mirror, _ = system.media(wl)
            for k in range(1, system.image_index):
                s = system.surfaces[k]
                if s.is_coordinate_break or mirror[k]:
                    continue
                cos_i = np.nan_to_num(np.abs(np.einsum("ij,ij->i", t.directions[k - 1], t.normals[k])), nan=1.0)
                wt = wt * _transmittance(n[k - 1], n[k], k, coating, cos_i)
        ok = t.valid
        nominal_power = float(wt[ok].sum())
        if ok.any():
            nominal = bin_(t.x[ok], t.y[ok], wt[ok])
    c = 0.5 * (edges[1:] + edges[:-1])
    return {"ghost": ghost, "nominal": nominal, "x": c, "y": c,
            "extent": (-half_width, half_width, -half_width, half_width),
            "pairs": np.array(pairs, dtype=int).reshape(-1, 2), "pair_power": np.array(pair_power),
            "ghost_power": float(np.sum(pair_power)), "nominal_power": nominal_power,
            "field": (hx, hy), "wavelength": wl, "units": system.units}


def ghost_layout(system, i: int, j: int, field=0, wavelength=None, n_rays: int = 7, plane: str = "y"):
    """Ray paths (global coordinates) of the ghost i -> j for layout plots.

    Returns ``path`` (S, N, 3) along the unfolded ghost system, ``valid`` and
    the original lens ``surfaces`` profiles (from :func:`surface_profiles`).
    """
    from .geometry import surface_profiles
    wl = system.primary if wavelength is None else wavelength
    hx, hy = resolve_field(system, field)
    p = np.linspace(-1, 1, n_rays)
    px, py = (p, np.zeros(n_rays)) if plane == "x" else (np.zeros(n_rays), p)
    g = ghost_system(system, i, j)
    t = ghost_trace(system, i, j, hx, hy, px, py, wl, ghost=g)
    G = t.global_positions()
    start = 0 if system.object_at_infinity else 1
    path = G[start:]
    for k in range(path.shape[1]):
        if not t.valid[k] and t.error_surface[k] >= 0:
            path[t.error_surface[k] - start + 1:, k] = np.nan
    return {"path": path, "valid": t.valid, "pair": (i, j), "field": field, "wavelength": wl,
            "surfaces": surface_profiles(system, plane=plane), "plane": plane}
