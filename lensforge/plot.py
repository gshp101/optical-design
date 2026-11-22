"""Matplotlib plotting helpers for analysis results.

Plotting is kept apart from computation: every analysis returns plain dicts
of NumPy arrays and these functions only draw them.  matplotlib is imported
lazily, so the core package needs only NumPy (a web front end can draw the
same dicts with its own charting library).

Each function takes a result dict, an optional ``ax`` and returns the axes.
"""

from __future__ import annotations

import math

import numpy as np


def _plt():
    import matplotlib.pyplot as plt
    return plt


def _ax(ax, **kw):
    if ax is None:
        _, ax = _plt().subplots(**kw)
    return ax


def _wl_label(w):
    return f"{w:.4f} um"


#: colours wavelengths are drawn in when they share a plot, from the longest (red) through green
#: to the shortest (blue); intermediate wavelengths are interpolated between these by rank
WAVELENGTH_SCALE = ("#d62728", "#e8820c", "#2ca02c", "#1a9fb4", "#1f4fd6")
#: the colour of a lens with one wavelength
SINGLE_WAVELENGTH_COLOR = "#1f4fd6"


def _scale_color(t):
    """Colour at ``t`` along :data:`WAVELENGTH_SCALE` (0 = red, 0.5 = green, 1 = blue)."""
    t = min(max(float(t), 0.0), 1.0) * (len(WAVELENGTH_SCALE) - 1)
    k = min(int(t), len(WAVELENGTH_SCALE) - 2)
    f = t - k
    a, b = (np.array([int(c[i:i + 2], 16) for i in (1, 3, 5)], float) for c in WAVELENGTH_SCALE[k:k + 2])
    r, g, bl = np.rint(a + (b - a) * f).astype(int)
    return f"#{r:02x}{g:02x}{bl:02x}"


def wavelength_colors(wavelengths, all_wavelengths=None):
    """Plot colours (hex strings, in the order given) of wavelengths that share a plot.

    The longest wavelength is red, the shortest blue and those in between run through green,
    by rank (not by value or by the order they were entered): three wavelengths are red, green
    and blue, five are red, orange, green, teal and blue.  ``all_wavelengths`` (usually every
    wavelength of the lens) sets the ranking, so a wavelength keeps its colour in a plot that
    shows only some of them; by default the wavelengths given are ranked among themselves.
    Values are in um (anything sortable works)."""
    wl = [float(w) for w in wavelengths]
    ref = sorted({float(w) for w in (all_wavelengths if all_wavelengths is not None else wl)} | set(wl),
                 reverse=True)
    if len(ref) <= 1:
        return [SINGLE_WAVELENGTH_COLOR for _ in wl]
    return [_scale_color(ref.index(w) / (len(ref) - 1)) for w in wl]


def wavelength_color(w, all_wavelengths):
    """Plot colour of one wavelength ranked among ``all_wavelengths`` (see :func:`wavelength_colors`)."""
    return wavelength_colors([w], all_wavelengths)[0]


def _wl_colors(result, waves=None):
    return wavelength_colors(result["wavelengths"], waves)


def ray_colors(rays, color_by="auto", waves=None):
    """Colour and legend label of each layout ray set (dicts with ``field`` and ``wavelength``).

    ``color_by`` "field" (matplotlib's colour cycle by field), "wavelength" (red longest through
    green to blue shortest, :func:`wavelength_colors`; ``waves`` ranks them) or "auto" (by
    wavelength when only one field is drawn, which shows the dispersion; by field otherwise).
    Returns (colours, labels) lists in the order of ``rays``."""
    fields = sorted({r["field"] for r in rays if isinstance(r["field"], (int, np.integer))})
    wls = sorted({float(r["wavelength"]) for r in rays})
    if color_by == "auto":
        color_by = "wavelength" if len(fields) <= 1 and len(wls) > 1 else "field"
    if color_by == "wavelength":
        cols = wavelength_colors([r["wavelength"] for r in rays], waves if waves is not None else wls)
        return cols, [_wl_label(r["wavelength"]) for r in rays]
    cycle = _cycle()
    cols, labels = [], []
    for r in rays:
        k = fields.index(r["field"]) if r["field"] in fields else 0
        cols.append(cycle[k % len(cycle)])
        labels.append(f"field {r['field'] + 1}" if r["field"] in fields else "rays")
    return cols, labels


def _cycle():
    return ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22",
            "#17becf"]


def layout(result, ax=None, plane="y", color_by="auto", waves=None):
    """2-D layout from :func:`lensforge.analysis.geometry.layout`; rays coloured as :func:`ray_colors`."""
    ax = _ax(ax, figsize=(9, 4))
    j = 1 if plane == "y" else 0
    for s in result["surfaces"]:
        P = s["points"]
        ax.plot(P[:, 2], P[:, j], color="k", lw=1.5 if s["mirror"] else 1)
    for r, c in zip(result["rays"], ray_colors(result["rays"], color_by, waves)[0]):
        p = r["path"]
        ax.plot(p[:, :, 2], p[:, :, j], color=c, lw=0.6)
    ax.set_aspect("equal", adjustable="datalim")
    ax.set_xlabel("z")
    ax.set_ylabel(plane)
    return ax


def _split_nan(P):
    """Pieces (each >= 2 points) of a polyline ``P`` (M, 3) between NaN points."""
    ok = np.all(np.isfinite(P), axis=1)
    out, start = [], None
    for k, good in enumerate(list(ok) + [False]):
        if good and start is None:
            start = k
        elif not good and start is not None:
            if k - start >= 2:
                out.append(P[start:k])
            start = None
    return out


def layout_3d_lines(result, color_by="auto", waves=None, show_edges=True):
    """The polylines of a 3-D layout (:func:`lensforge.analysis.layout_3d`) as plain data.

    Returns a list of dicts ``points`` ((M, 3) global x, y, z), ``color``, ``width``, ``kind``
    ("surface", "edge" or "ray") and ``label`` (legend text of the first line of each ray colour,
    else None).  Rays are split where they fail (NaN).  :func:`layout_3d` draws these with
    matplotlib; the web app draws the same list on a canvas it can rotate."""
    lines = []
    for srf in result["surfaces"]:
        w = 1.5 if srf["mirror"] else 1.0
        if srf["semi_diameter"] > 0:
            lines.append({"points": srf["rim"], "color": "#000000", "width": w, "kind": "surface", "label": None,
                          "surface": srf["surface"]})
        for sec in srf["sections"]:
            lines.append({"points": sec, "color": "#000000", "width": w, "kind": "surface", "label": None,
                          "surface": srf["surface"]})
    if show_edges:
        for e in result.get("edges", []):
            lines.append({"points": e["points"], "color": "#000000", "width": 0.8, "kind": "edge", "label": None})
    cols, labels = ray_colors(result["rays"], color_by, waves)
    seen = set()
    for r, c, lab in zip(result["rays"], cols, labels):
        p = r["path"]
        for k in range(p.shape[1]):
            for piece in _split_nan(p[:, k]):
                first = lab not in seen
                seen.add(lab)
                lines.append({"points": piece, "color": c, "width": 0.6, "kind": "ray",
                              "label": lab if first else None})
    return lines


def layout_3d(result, ax=None, elevation=20.0, azimuth=-60.0, color_by="auto", waves=None, zoom=1.0,
              show_edges=True, title=None):
    """3-D layout (:func:`lensforge.analysis.layout_3d`): surfaces (rims and the local x and y
    sections), element edges and rays.  The optical axis z runs across the view (the plot's first
    axis), x and y are the other two, all to the same scale.  ``elevation`` / ``azimuth`` (degrees,
    matplotlib's convention: 0 / -90 is the YZ side view, 90 / -90 looks down on the XZ plane)
    turn the view; ``zoom`` > 1 magnifies about the centre.  Rays are coloured as
    :func:`ray_colors`.  ``ax`` must be a 3-D axes (``fig.add_subplot(projection="3d")``) or None.
    In an interactive matplotlib window, drag to rotate."""
    from mpl_toolkits.mplot3d.art3d import Line3DCollection
    if ax is None:
        ax = _plt().figure(figsize=(8, 6)).add_subplot(projection="3d")
    lines = layout_3d_lines(result, color_by, waves, show_edges)
    for kind in ("surface", "edge", "ray"):
        sel = [ln for ln in lines if ln["kind"] == kind]
        if not sel:
            continue
        segs = [ln["points"][:, [2, 0, 1]] for ln in sel]
        ax.add_collection3d(Line3DCollection(segs, colors=[ln["color"] for ln in sel],
                                             linewidths=[ln["width"] for ln in sel]))
    labelled = [ln for ln in lines if ln["label"]]
    for ln in labelled:
        ax.plot([], [], [], color=ln["color"], label=ln["label"])
    if labelled:
        ax.legend(fontsize=7, loc="upper left")
    lo, hi = (np.asarray(v, float) for v in result["bounds"])
    mid, half = (lo + hi) / 2, max(float((hi - lo).max()) / 2, 1e-6) / max(float(zoom), 1e-6)
    ax.set_xlim(mid[2] - half, mid[2] + half)
    ax.set_ylim(mid[0] - half, mid[0] + half)
    ax.set_zlim(mid[1] - half, mid[1] + half)
    try:
        ax.set_box_aspect((1, 1, 1))
    except Exception:  # noqa: BLE001 - old matplotlib
        pass
    ax.view_init(elev=float(elevation), azim=float(azimuth))
    ax.grid(False)
    for a in (ax.xaxis, ax.yaxis, ax.zaxis):
        a.set_pane_color((1, 1, 1, 0))
    u = result.get("units")
    u = f" ({u})" if u else ""
    ax.set_xlabel("z" + u)
    ax.set_ylabel("x" + u)
    ax.set_zlabel("y" + u)
    if title:
        ax.set_title(title, fontsize=9)
    return ax


#: marker of each field in a combined spot diagram (fields beyond these reuse them)
FIELD_MARKERS = ("o", "s", "^", "D", "v", "P", "X", "*", "<", ">", "h", "p")


def _field_magnification(spots):
    """Spot magnification of the "image" mode: the largest spot spans about a third of the
    smallest distance between two field points, rounded down to 1, 2 or 5 x a power of ten
    (1 when the fields share one image point)."""
    refs = np.array([sp["reference"] for sp in spots], float)
    geo = max((sp["geo_radius"] for sp in spots if np.isfinite(sp["geo_radius"])), default=0.0)
    d = [np.hypot(*(refs[i] - refs[k])) for i in range(len(refs)) for k in range(i)]
    d = [v for v in d if v > 1e-9 * max(1.0, float(np.abs(refs).max()))]
    if not d or geo <= 0:
        return 1.0
    m = 0.45 * min(d) / geo
    e = 10 ** math.floor(math.log10(m))  # a round number: 1, 2 or 5 x a power of ten
    return float(max(v * e for v in (1, 2, 5, 10) if v * e <= m * 1.0000001)) if m >= 1 else m


def spot_combined(spots, ax=None, mode="overlay", scale=1.0, waves=None, labels=None, units=None,
                  magnification=None, ms=3.0, image_units=None):
    """Every field and wavelength of a set of spot diagrams in one plot.

    ``spots``: :func:`lensforge.analysis.spot_diagram` results (one per field) or (field, result)
    pairs.  Colour shows the wavelength (red longest, green, blue shortest: :func:`wavelength_colors`,
    ranked among ``waves``, every wavelength of the lens) and the marker shape the field.
    ``mode`` "overlay" draws every spot about its own reference point (chief ray or centroid), so
    the sizes and shapes compare directly; "image" draws each spot at its place on the image,
    magnified by ``magnification`` (default: chosen so the spots don't overlap) about its
    reference.  ``scale`` multiplies the spot coordinates (1000 shows mm lenses in um); ``labels``
    names the fields (default "Field 1", ...); ``units`` names the scaled unit (axes of "overlay",
    RMS radii in the legend) and ``image_units`` the lens unit (axes of "image")."""
    ax = _ax(ax, figsize=(5, 5))
    items = [sp if isinstance(sp, tuple) else (k, sp) for k, sp in enumerate(spots)]
    res = [sp for _, sp in items]
    if labels is None:
        labels = [f"Field {f + 1}" if isinstance(f, (int, np.integer)) else str(f) for f, _ in items]
    allw = waves if waves is not None else sorted({float(w) for sp in res for w in sp["wavelengths"]})
    image = mode == "image"
    mag = (magnification or _field_magnification(res)) if image else 1.0
    for k, sp in enumerate(res):
        mk = FIELD_MARKERS[k % len(FIELD_MARKERS)]
        cx, cy = sp["reference"] if image else (0.0, 0.0)
        for w, c, x, y in zip(sp["wavelengths"], wavelength_colors(sp["wavelengths"], allw), sp["x"], sp["y"]):
            x, y = np.asarray(x, float), np.asarray(y, float)
            if image:
                px, py = cx + mag * x, cy + mag * y
            else:
                px, py = x * scale, y * scale
            ax.plot(px, py, mk, ms=ms, color=c, mfc="none" if k % 2 else c, mew=0.7, alpha=0.8, ls="none")
    # legend: wavelengths by colour, fields by marker (with each field's RMS)
    hs = []
    shown = sorted({float(w) for sp in res for w in sp["wavelengths"]}, reverse=True)
    for w, c in zip(shown, wavelength_colors(shown, allw)):
        hs += ax.plot([], [], "s", color=c, ms=6, label=_wl_label(w))
    u = units or ""
    for k, (lab, sp) in enumerate(zip(labels, res)):
        mk = FIELD_MARKERS[k % len(FIELD_MARKERS)]
        rms = sp["rms_radius"] * scale
        hs += ax.plot([], [], mk, color="0.25", mfc="none" if k % 2 else "0.25", ms=5,
                      label=f"{lab}: RMS {rms:.4g} {u}".rstrip())
    ax.legend(handles=hs, fontsize=7, loc="upper left", bbox_to_anchor=(1.01, 1.0), borderaxespad=0,
              frameon=False)
    ax.set_aspect("equal", adjustable="datalim")
    ax.axhline(0, color="0.85", lw=0.5, zorder=0)
    ax.axvline(0, color="0.85", lw=0.5, zorder=0)
    if image:
        ax.set_title(f"All fields at their image positions, spots magnified x{mag:.3g}", fontsize=8)
    else:
        ax.set_title("All fields and wavelengths, each about its reference point", fontsize=8)
    au = image_units if image else units
    if au:
        ax.set_xlabel(f"x ({au})")
        ax.set_ylabel(f"y ({au})")
    ax.magnification = mag
    return ax


def spot(result, ax=None, scale=1.0, waves=None):
    """Spot diagram of one field (:func:`lensforge.analysis.spot_diagram`).  ``waves``: every
    wavelength of the lens, so each keeps its colour (:func:`wavelength_colors`)."""
    ax = _ax(ax, figsize=(4, 4))
    for w, c, x, y in zip(result["wavelengths"], _wl_colors(result, waves), result["x"], result["y"]):
        ax.plot(np.asarray(x) * scale, np.asarray(y) * scale, ".", ms=2, color=c, label=_wl_label(w))
    ax.set_aspect("equal")
    ax.set_title(f"RMS {result['rms_radius'] * scale:.4g}, GEO {result['geo_radius'] * scale:.4g}")
    ax.legend(fontsize=7)
    return ax


def point_source(result, ax=None, scale=1.0, relative=True):
    """Image-plane rays from :func:`lensforge.analysis.point_source_trace` (vignetted
    rays are dropped).  ``relative`` plots about the centroid."""
    ax = _ax(ax, figsize=(4, 4))
    v = result["valid"]
    cx, cy = result["centroid"] if (relative and result["centroid"]) else (0.0, 0.0)
    ax.plot((result["x"][v] - cx) * scale, (result["y"][v] - cy) * scale, ".", ms=2)
    ax.set_aspect("equal")
    x, y, z = result["point"]
    ax.set_title(f"({x:.4g}, {y:.4g}, {z:.4g}) {result['wavelength']:.4f} um\n"
                 f"RMS {result['rms_radius'] * scale:.4g}, {result['n_valid']}/{result['n_launched']} rays",
                 fontsize=8)
    return ax


def ray_fan(result, axes=None, units=None, waves=None):
    """Transverse ray fan.  ``units`` (lens unit name, e.g. "mm") labels the error axis; ``waves``
    (every wavelength of the lens) ranks the wavelength colours."""
    if axes is None:
        _, axes = _plt().subplots(1, 2, figsize=(8, 3.5), sharey=True)
    for w, c, ey, ex in zip(result["wavelengths"], _wl_colors(result, waves), result["ey"], result["ex"]):
        axes[0].plot(result["p"], ey, color=c, label=_wl_label(w))
        axes[1].plot(result["p"], ex, color=c)
    u = f" ({units})" if units else ""
    axes[0].set_title(f"Tangential ey{u} vs py")
    axes[1].set_title(f"Sagittal ex{u} vs px")
    axes[0].set_xlabel("py (normalised pupil)", fontsize=8)
    axes[1].set_xlabel("px (normalised pupil)", fontsize=8)
    axes[0].legend(fontsize=7)
    for a in axes:
        a.axhline(0, color="0.6", lw=0.5)
    return axes


def opd_fan(result, axes=None, waves=None):
    if axes is None:
        _, axes = _plt().subplots(1, 2, figsize=(8, 3.5), sharey=True)
    for w, c, wy, wx in zip(result["wavelengths"], _wl_colors(result, waves), result["wy"], result["wx"]):
        axes[0].plot(result["p"], wy, color=c, label=_wl_label(w))
        axes[1].plot(result["p"], wx, color=c)
    axes[0].set_title("Tangential OPD (waves) vs py")
    axes[1].set_title("Sagittal OPD (waves) vs px")
    axes[0].set_xlabel("py (normalised pupil)", fontsize=8)
    axes[1].set_xlabel("px (normalised pupil)", fontsize=8)
    axes[0].legend(fontsize=7)
    return axes


def map2d(Z, x, y, ax=None, title="", cmap="viridis", colorbar=True, **kw):
    ax = _ax(ax, figsize=(4.5, 4))
    im = ax.imshow(Z, origin="lower", extent=[x[0], x[-1], y[0], y[-1]], cmap=cmap, **kw)
    if colorbar:
        ax.figure.colorbar(im, ax=ax)
    ax.set_title(title)
    return ax


def wavefront(result, ax=None):
    return map2d(result["W"], result["px"], result["py"], ax,
                 f"Wavefront (waves) RMS {result['rms']:.4f} PV {result['pv']:.4f}", cmap="RdBu_r")


def psf_zoom_limits(result, zoom=1):
    """Plot limits ``(xlim, ylim)`` that zoom into the centre of a PSF result.

    ``zoom`` is a magnification (1 = the whole PSF window, 4 = the central quarter of its width,
    centred on the chief-ray reference) or ``"auto"``, which centres on the PSF centroid and spans
    the larger of 3 x the 50% and 1.5 x the 90% encircled-energy radius, so the core and the first
    rings fill the plot."""
    x, y = np.asarray(result["x"], float), np.asarray(result["y"], float)
    if zoom in (None, 0, 1, "full"):
        return (float(x[0]), float(x[-1])), (float(y[0]), float(y[-1]))
    if zoom == "auto":
        P = np.maximum(np.asarray(result["psf"], float), 0)
        if not P.sum() > 0:
            return psf_zoom_limits(result, 1)
        X, Y = np.meshgrid(x, y)
        w = P / P.sum()
        cx, cy = float((w * X).sum()), float((w * Y).sum())
        r = np.hypot(X - cx, Y - cy).ravel()
        order = np.argsort(r)
        ee = np.cumsum(w.ravel()[order])
        r50, r90 = (r[order][min(np.searchsorted(ee, q), len(r) - 1)] for q in (0.5, 0.9))
        dx, dy = abs(x[1] - x[0]), abs(y[1] - y[0])
        half = min(max(3 * r50, 1.5 * r90, 8 * max(dx, dy)), 0.5 * min(x[-1] - x[0], y[-1] - y[0]))
        cx = min(max(cx, x[0] + half), x[-1] - half)  # keep the frame inside the PSF window
        cy = min(max(cy, y[0] + half), y[-1] - half)
        return (cx - half, cx + half), (cy - half, cy + half)
    z = float(zoom)
    if z <= 0:
        raise ValueError("zoom must be positive or 'auto'")
    cx, cy = 0.5 * (x[0] + x[-1]), 0.5 * (y[0] + y[-1])
    hx, hy = 0.5 * (x[-1] - x[0]) / z, 0.5 * (y[-1] - y[0]) / z
    return (float(cx - hx), float(cx + hx)), (float(cy - hy), float(cy + hy))


def psf(result, ax=None, log=False, zoom=1):
    """PSF image (normalised to the aberration-free peak).  ``zoom`` magnifies the centre of the
    PSF window (2, 4, 8, ...) or frames the PSF itself with ``"auto"``; see :func:`psf_zoom_limits`."""
    Z = result["psf"] / result["perfect"].max()
    if log:
        Z = np.log10(np.maximum(Z, 1e-8))
    ax = map2d(Z, result["x"], result["y"], ax, f"{result['method'].upper()} PSF, Strehl {result['strehl']:.4f}",
               cmap="inferno")
    xl, yl = psf_zoom_limits(result, zoom)
    ax.set_xlim(*xl)
    ax.set_ylim(*yl)
    return ax


def mtf(result, ax=None, diffraction=True, units=None):
    """MTF curves; ``units`` (lens unit name) labels the frequency axis, e.g. cycles/mm."""
    ax = _ax(ax, figsize=(6, 4))
    l1, = ax.plot(result["freq"], result["tangential"], label="T")
    ax.plot(result["freq"], result["sagittal"], "--", color=l1.get_color(), label="S")
    if diffraction and "diffraction_limit_tangential" in result:
        ax.plot(result["freq"], result["diffraction_limit_tangential"], color="k", lw=0.8, label="diffraction limit")
    ax.set_xlabel(f"spatial frequency (cycles/{units or 'lens unit'})")
    ax.set_ylabel("modulus of the OTF")
    ax.set_ylim(0, 1.02)
    ax.legend(fontsize=8)
    return ax


def through_focus_mtf(result, ax=None):
    ax = _ax(ax, figsize=(6, 4))
    ax.plot(result["focus"], result["tangential"], label="T")
    ax.plot(result["focus"], result["sagittal"], "--", label="S")
    ax.set_xlabel("focus shift")
    ax.set_ylabel(f"MTF at {result['frequency']:g}")
    ax.legend()
    return ax


def mtf_vs_field(result, ax=None, units=None):
    ax = _ax(ax, figsize=(6, 4))
    for k, f in enumerate(result["frequencies"]):
        l, = ax.plot(result["field"], result["tangential"][:, k], label=f"T {f:g} cycles/{units or 'unit'}")
        ax.plot(result["field"], result["sagittal"][:, k], "--", color=l.get_color(), label=f"S {f:g}")
    ax.set_xlabel("normalised field")
    ax.set_ylabel("MTF")
    ax.set_ylim(0, 1.02)
    ax.legend(fontsize=7)
    return ax


def energy(result, ax=None):
    ax = _ax(ax, figsize=(6, 4))
    ax.plot(result["radius"], result["energy"], label=result.get("method", ""))
    if "diffraction_limit" in result:
        ax.plot(result["radius"], result["diffraction_limit"], color="k", lw=0.8, label="diffraction limit")
    ax.set_xlabel("radius" if result["kind"] == "encircled" else "half width")
    ax.set_ylabel(f"{result['kind']} energy fraction")
    ax.set_ylim(0, 1.02)
    ax.legend(fontsize=8)
    return ax


def field_curvature(result, axes=None, waves=None):
    if axes is None:
        _, axes = _plt().subplots(1, 2, figsize=(8, 4), sharey=True)
    for k, (w, c) in enumerate(zip(result["wavelengths"], _wl_colors(result, waves))):
        l, = axes[0].plot(result["tangential"][k], result["field_value"], color=c, label=f"T {_wl_label(w)}")
        axes[0].plot(result["sagittal"][k], result["field_value"], "--", color=l.get_color())
        axes[1].plot(result["distortion_percent"][k], result["field_value"], color=l.get_color())
    axes[0].set_title("Field curvature (T solid, S dashed)")
    axes[1].set_title("Distortion (%)")
    axes[0].legend(fontsize=7)
    for a in axes:
        a.axvline(0, color="0.6", lw=0.5)
    return axes


def grid_distortion(result, ax=None):
    ax = _ax(ax, figsize=(5, 5))
    for A, B, st in ((result["predicted_x"], result["predicted_y"], "0.7"), (result["real_x"], result["real_y"], "C0")):
        ax.plot(A, B, color=st, lw=0.8)
        ax.plot(A.T, B.T, color=st, lw=0.8)
    ax.set_aspect("equal")
    ax.set_title(f"Grid distortion, max {result['max_percent']:.3f}%")
    return ax


def lateral_color(result, ax=None, waves=None):
    ax = _ax(ax, figsize=(5, 4))
    for w, c, d in zip(result["wavelengths"], _wl_colors(result, waves), result["difference"]):
        ax.plot(d, result["field"], color=c, label=_wl_label(w))
    ax.set_xlabel("image height difference from primary")
    ax.set_ylabel("normalised field")
    ax.legend(fontsize=7)
    return ax


def longitudinal_aberration(result, ax=None, waves=None):
    ax = _ax(ax, figsize=(5, 4))
    for w, c, z in zip(result["wavelengths"], _wl_colors(result, waves), result["focus"]):
        ax.plot(z, result["pupil"], color=c, label=_wl_label(w))
    ax.set_xlabel("focus shift")
    ax.set_ylabel("pupil height")
    ax.legend(fontsize=7)
    return ax


def chromatic_focal_shift(result, ax=None):
    ax = _ax(ax, figsize=(5, 4))
    ax.plot(result["shift"], result["wavelength"])
    ax.set_xlabel("focal shift")
    ax.set_ylabel("wavelength (um)")
    ax.set_title(f"max shift {result['max_shift']:.4g} (DL range {result['diffraction_limited_range']:.4g})")
    return ax


def relative_illumination(result, ax=None):
    ax = _ax(ax, figsize=(5, 4))
    ax.plot(result["field"], result["relative_illumination"])
    ax.set_xlabel("normalised field")
    ax.set_ylabel("relative illumination")
    ax.set_ylim(0, 1.05)
    return ax


def vignetting(result, ax=None):
    ax = _ax(ax, figsize=(5, 4))
    ax.plot(result["field"], result["transmitted_fraction"])
    ax.set_xlabel("normalised field")
    ax.set_ylabel("unvignetted fraction")
    ax.set_ylim(0, 1.05)
    return ax


def footprint(result, ax=None):
    ax = _ax(ax, figsize=(5, 5))
    for b in result["beams"]:
        ax.plot(b["x"], b["y"], ".", ms=1.5)
    if result.get("semi_diameter"):
        t = np.linspace(0, 2 * math.pi, 200)
        r = result["semi_diameter"]
        ax.plot(r * np.cos(t), r * np.sin(t), "k", lw=0.8)
    ax.set_aspect("equal")
    ax.set_title(f"Footprint on surface {result['surface']}")
    return ax


def sag(result, ax=None, departure=False):
    Z = result["departure"] if departure else result["sag"]
    return map2d(Z, result["x"], result["y"], ax, "Departure from BFS" if departure else "Sag")


def bars(labels, values, ax=None, title=""):
    ax = _ax(ax, figsize=(7, 3.5))
    ax.bar(range(len(values)), values)
    ax.set_xticks(range(len(values)))
    ax.set_xticklabels(labels, rotation=90, fontsize=7)
    ax.set_title(title)
    ax.axhline(0, color="0.5", lw=0.5)
    return ax


def seidel(result, ax=None):
    """Seidel diagram: grouped bars per surface plus the sum."""
    ax = _ax(ax, figsize=(8, 4))
    keys = ("S1", "S2", "S3", "S4", "S5", "CL", "CT")
    surf = list(result["surface"][1:]) + ["SUM"]
    x = np.arange(len(surf))
    wdt = 0.8 / len(keys)
    for k, key in enumerate(keys):
        vals = list(result["per_surface"][key][1:]) + [result["totals"][key]]
        ax.bar(x + (k - len(keys) / 2) * wdt, vals, wdt, label=key)
    ax.set_xticks(x)
    ax.set_xticklabels([str(s) for s in surf])
    ax.legend(fontsize=7, ncol=7)
    ax.axhline(0, color="0.5", lw=0.5)
    return ax


def zernike(result, ax=None):
    c = result["coefficients"]
    return bars([f"Z{j}" for j in range(1, c.size + 1)], c, ax, f"{result['kind'].title()} Zernike (waves)")


def interferogram(result, ax=None):
    return map2d(result["intensity"], result["px"], result["py"], ax, "Interferogram", cmap="gray", colorbar=False)


def polarization_pupil(result, ax=None, scale=0.08):
    """Polarisation ellipses (major axis lines) across the pupil."""
    ax = _ax(ax, figsize=(5, 5))
    ang = np.radians(result["orientation_deg"])
    ok = result["valid"]
    ax.quiver(result["px"][ok], result["py"][ok], np.cos(ang[ok]), np.sin(ang[ok]), headlength=0, headaxislength=0,
              pivot="middle", scale=1 / scale)
    ax.set_aspect("equal")
    ax.set_title(f"Polarisation pupil map, T = {result['total_transmission']:.4f}")
    return ax


def ghost_layout(result, ax=None):
    """Lens cross-section with the rays of one ghost (:func:`lensforge.analysis.ghost.ghost_layout`)."""
    ax = _ax(ax, figsize=(9, 4))
    j = 0 if result.get("plane") == "x" else 1
    for s in result["surfaces"]:
        P = s["points"]
        ax.plot(P[:, 2], P[:, j], color="k", lw=1.5 if s["mirror"] else 1)
    p = result["path"]
    ax.plot(p[:, :, 2], p[:, :, j], color="C3", lw=0.7)
    i, k = result["pair"]
    ax.set_title(f"Ghost {i}-{k}: reflected at surface {i}, then at surface {k}")
    ax.set_aspect("equal", adjustable="datalim")
    ax.set_xlabel("z")
    ax.set_ylabel("x" if j == 0 else "y")
    return ax


def ghost_image(result, ax=None, log=True, show="ghost"):
    """Image-plane irradiance of ghosts (:func:`lensforge.analysis.ghost.ghost_image`).

    ``show``: "ghost", "nominal" or "both" (sum).  ``log`` uses a log10 colour scale.
    """
    ax = _ax(ax, figsize=(6, 5))
    Z = {"ghost": result["ghost"], "nominal": result["nominal"],
         "both": result["ghost"] + result["nominal"]}[show]
    if log:
        pos = Z[Z > 0]
        floor = pos.min() if pos.size else 1e-12
        Z = np.log10(np.maximum(Z, floor))
    im = ax.imshow(Z, origin="lower", extent=result["extent"], cmap="inferno")
    ax.figure.colorbar(im, ax=ax, label=("log10 " if log else "") + f"irradiance (fraction / {result['units']}²)")
    ax.set_xlabel(f"x ({result['units']})")
    ax.set_ylabel(f"y ({result['units']})")
    ax.set_title(f"Ghost irradiance: {result['ghost_power']:.3g} of the beam in {len(result['pairs'])} ghosts")
    return ax


def _ns_keep(result, rays="all", path=None, min_power=0.0):
    """Indices of the segments to draw: by reflection count of the light (``rays`` as
    :meth:`DetectorData.select`), or the segments of one ray ``path`` (a dict from
    :meth:`NSTraceResult.paths`, or an array of segment indices)."""
    seg = result.segments
    if path is not None:
        idx = path["segments"] if isinstance(path, dict) else np.asarray(path, dtype=int)
        return idx[seg["power"][idx] >= min_power]
    m = seg["power"] >= min_power
    nr = seg["n_reflections"]
    if rays == "direct":
        m &= nr == 0
    elif rays == "ghost":
        m &= nr >= 2
    elif isinstance(rays, (int, np.integer)):
        m &= nr == rays
    return np.flatnonzero(m)


def _ns_thin(result, keep, max_segments):
    """At most ``max_segments`` of ``keep``: whole ray paths picked at random within each
    reflection order, so faint ghost paths stay visible."""
    seg = result.segments
    if len(keep) <= max_segments:
        return keep
    rng = np.random.default_rng(0)
    order = np.minimum(seg["n_reflections"][keep], 2)
    share = {0: 2.0, 1: 1.0, 2: 1.0}  # direct light gets half the budget when there are reflections
    present = [k for k in range(3) if np.any(order == k)]
    total = sum(share[k] for k in present)
    parts = []
    for k in present:
        g = keep[order == k]
        ids = np.unique(seg["ray"][g])
        rng.shuffle(ids)
        per_ray = max(len(g) / max(len(ids), 1), 1.0)
        take = ids[: max(1, int(max_segments * share[k] / total / per_ray))]
        parts.append(g[np.isin(seg["ray"][g], take)])
    return np.concatenate(parts)


def wavelength_rgb(wl_um):
    """Approximate display colour (r, g, b in 0..1) of a wavelength in um (grey outside 380-780 nm)."""
    w = float(wl_um) * 1000
    if w < 380 or w > 780:
        return (0.5, 0.5, 0.5)
    if w < 440:
        r, g, b = (440 - w) / 60, 0.0, 1.0
    elif w < 490:
        r, g, b = 0.0, (w - 440) / 50, 1.0
    elif w < 510:
        r, g, b = 0.0, 1.0, (510 - w) / 20
    elif w < 580:
        r, g, b = (w - 510) / 70, 1.0, 0.0
    elif w < 645:
        r, g, b = 1.0, (645 - w) / 65, 0.0
    else:
        r, g, b = 1.0, 0.0, 0.0
    f = 0.3 + 0.7 * (w - 380) / 40 if w < 420 else 0.3 + 0.7 * (780 - w) / 80 if w > 700 else 1.0
    return (r * f, g * f, b * f)


def _ns_colors(result, keep, color_by):
    """(colours, legend {colour: label}) of the segments ``keep``."""
    seg = result.segments
    if color_by == "power":
        lp = np.log10(np.maximum(seg["power"][keep], 1e-300))
        lo, hi = (lp.min(), lp.max()) if len(lp) else (0, 1)
        g = (lp - lo) / max(hi - lo, 1e-12)
        return [(0.85 * (1 - v), 0.85 * (1 - v), 0.85 * (1 - v) + 0.15 * v) for v in g], {}
    if color_by == "source":
        src = seg["source"][keep]
        return [f"C{int(v) % 10}" for v in src], {f"C{int(v) % 10}": f"source {int(v) + 1}"
                                                  for v in np.unique(src)[:10] if v >= 0}
    if color_by == "wavelength":
        wl = seg["wavelength"][keep]
        allw = np.unique(seg["wavelength"])
        cmap = {float(w): wavelength_color(w, allw) for w in np.unique(wl)}
        return [cmap[float(w)] for w in wl], {c: f"{w:.4f} um" for w, c in list(cmap.items())[:10]}
    nr = np.minimum(seg["n_reflections"][keep], 2)
    cmap = {0: "C0", 1: "C2", 2: "C3"}
    labels = {"C0": "direct", "C2": "1 reflection", "C3": "2+ reflections (ghosts)"}
    present = {cmap[int(v)] for v in np.unique(nr)}
    return [cmap[int(v)] for v in nr], {c: lab for c, lab in labels.items() if c in present}


def _ns_object_color(o):
    if o.is_detector:
        return "C1"
    if o.is_volume:
        return "k"
    return "0.3"


def ns_layout(result, ax=None, plane="y", max_segments=4000, color_by="reflections", min_power=0.0, rays="all",
              path=None, numbers=True):
    """2-D projection of a non-sequential trace (:class:`lensforge.nonseq.NSTraceResult`) with its objects.

    ``plane`` "y" draws z across and y up with each object's YZ section, "x" the XZ plane.
    ``color_by``: "reflections" (direct / one / two+ Fresnel reflections), "source", "wavelength"
    or "power" (grey level by log power).  ``rays`` keeps only light with that reflection history
    ("all", "direct", "ghost" or a count); ``path`` draws only one ray path (from
    :meth:`NSTraceResult.paths`).  At most ``max_segments`` segments are drawn: whole ray paths
    picked at random within each reflection order.  ``numbers`` labels each object with its number.
    """
    from matplotlib.collections import LineCollection
    ax = _ax(ax, figsize=(9, 4))
    j = 0 if plane == "x" else 1
    for k, o in enumerate(result.system.objects):
        lines = o.outline(plane=plane)
        for line in lines:
            ax.plot(line[:, 2], line[:, j], color=_ns_object_color(o),
                    lw=1.4 if o.action == "mirror" or o.is_detector else 1)
        if numbers and lines:
            pts = np.concatenate(lines)
            top = pts[np.argmax(pts[:, j])]
            ax.annotate(str(k + 1), (top[2], top[j]), textcoords="offset points", xytext=(0, 3), ha="center",
                        fontsize=7, color="0.35")
    seg = result.segments
    keep = _ns_thin(result, _ns_keep(result, rays, path, min_power), max_segments)
    keep = keep[np.argsort(-seg["n_reflections"][keep], kind="stable")]  # direct light drawn on top
    a, b = seg["start"][keep], seg["end"][keep]
    lines = np.stack([np.stack([a[:, 2], a[:, j]], 1), np.stack([b[:, 2], b[:, j]], 1)], axis=1)
    colors, labels = _ns_colors(result, keep, color_by)
    if len(keep):
        ax.add_collection(LineCollection(lines, colors=colors, linewidths=0.5))
    for c, lab in labels.items():
        ax.plot([], [], color=c, label=lab)
    if labels:
        ax.legend(fontsize=7, loc="upper right")
    ax.autoscale()
    ax.set_aspect("equal", adjustable="datalim")
    ax.set_xlabel("z")
    ax.set_ylabel("x" if j == 0 else "y")
    if path is not None and isinstance(path, dict):
        ax.set_title(path.get("label", ""), fontsize=7)
    return ax


def ns_layout_3d(result, ax=None, elevation=20.0, azimuth=-60.0, max_segments=3000, color_by="reflections",
                 rays="all", path=None, min_power=0.0):
    """3-D wireframe view of a non-sequential trace: objects (sections, rims and edges) and rays.

    The optical axis z runs across the view (drawn as the first plot axis), x and y are the
    other two.  ``ax`` must be a 3-D axes (``fig.add_subplot(projection="3d")``) or None.
    """
    from mpl_toolkits.mplot3d.art3d import Line3DCollection
    if ax is None:
        ax = _plt().figure(figsize=(8, 6)).add_subplot(projection="3d")
    pts = []
    for o in result.system.objects:
        c = _ns_object_color(o)
        for line in o.wireframe(25):
            ax.plot(line[:, 2], line[:, 0], line[:, 1], color=c, lw=0.8)
            pts.append(line)
    seg = result.segments
    keep = _ns_thin(result, _ns_keep(result, rays, path, min_power), max_segments)
    a, b = seg["start"][keep], seg["end"][keep]
    if len(keep):
        colors, labels = _ns_colors(result, keep, color_by)
        lines = np.stack([a[:, [2, 0, 1]], b[:, [2, 0, 1]]], axis=1)
        ax.add_collection3d(Line3DCollection(lines, colors=colors, linewidths=0.4))
        for c, lab in labels.items():
            ax.plot([], [], [], color=c, label=lab)
        if labels:
            ax.legend(fontsize=7, loc="upper right")
        pts += [a, b]
    if pts:
        P = np.concatenate(pts)
        P = P[np.all(np.isfinite(P), axis=1)]
        lo, hi = P.min(axis=0), P.max(axis=0)
        mid, half = (lo + hi) / 2, max(float((hi - lo).max()) / 2, 1e-6)
        ax.set_xlim(mid[2] - half, mid[2] + half)
        ax.set_ylim(mid[0] - half, mid[0] + half)
        ax.set_zlim(mid[1] - half, mid[1] + half)
    try:
        ax.set_box_aspect((1, 1, 1))
    except Exception:  # noqa: BLE001 - old matplotlib
        pass
    ax.view_init(elev=float(elevation), azim=float(azimuth))
    ax.set_xlabel("z")
    ax.set_ylabel("x")
    ax.set_zlabel("y")
    return ax


def ns_detector(result, det=0, ax=None, rays="all", log=False, show="irradiance", **select):
    """A detector of a non-sequential trace.  ``rays``: "all", "direct", "ghost" or a count.

    ``show``: "irradiance" (power per area map), "color" (true-colour image of the wavelengths),
    "cross_x" / "cross_y" (irradiance along x through y = 0 / along y through x = 0) or
    "angle" (radiant intensity against the direction cosines of the arriving rays).
    """
    ax = _ax(ax, figsize=(6, 5))
    d = result.detector(det)
    name = d.detector.comment or f"object {d.object_index + 1}"
    total = d.total_power(rays, **select)
    title = f"Detector {name} ({rays}): total {total:.4g}"
    if show == "color":
        m = d.select(rays, **select)
        o = d.detector
        ex = np.linspace(-o.half_x, o.half_x, o.nx + 1)
        ey = np.linspace(-o.half_y, o.half_y, o.ny + 1)
        img = np.zeros((o.ny, o.nx, 3))
        for w in np.unique(d.wavelength[m]):
            mw = m & np.isclose(d.wavelength, w)
            H, _, _ = np.histogram2d(d.y[mw], d.x[mw], bins=[ey, ex], weights=d.power[mw])
            img += H[:, :, None] * np.array(wavelength_rgb(w))[None, None, :]
        if log and img.max() > 0:
            lo = img[img > 0].min()
            img = np.log10(np.maximum(img, lo) / lo) + np.where(img > 0, 1.0, 0.0)
        img = img / img.max() if img.max() > 0 else img
        ax.imshow(img, origin="lower", extent=d.extent)
        ax.set_xlabel("x")
        ax.set_ylabel("y")
    elif show in ("cross_x", "cross_y"):
        Z = d.image(rays, **select)
        o = d.detector
        if show == "cross_x":
            row = Z[Z.shape[0] // 2, :] if o.ny % 2 else Z[Z.shape[0] // 2 - 1: Z.shape[0] // 2 + 1, :].mean(axis=0)
            u = np.linspace(-o.half_x, o.half_x, o.nx + 1)
            lab = "x"
        else:
            row = Z[:, Z.shape[1] // 2] if o.nx % 2 else Z[:, Z.shape[1] // 2 - 1: Z.shape[1] // 2 + 1].mean(axis=1)
            u = np.linspace(-o.half_y, o.half_y, o.ny + 1)
            lab = "y"
        c = 0.5 * (u[1:] + u[:-1])
        ax.plot(c, row, color="C0", lw=1.2, drawstyle="steps-mid")
        if log and np.any(row > 0):
            ax.set_yscale("log")
        ax.set_xlabel(lab)
        ax.set_ylabel("irradiance (power / area)")
        ax.grid(True, alpha=0.3)
        title += f"; {'row y = 0' if show == 'cross_x' else 'column x = 0'}"
    elif show == "angle":
        m = d.select(rays, **select)
        D = d.direction[m]
        D = D * np.where(D[:, 2:3] < 0, -1.0, 1.0)  # light arriving from either side
        n = 61
        e = np.linspace(-1, 1, n + 1)
        H, _, _ = np.histogram2d(D[:, 1], D[:, 0], bins=[e, e], weights=d.power[m]) if len(D) else (
            np.zeros((n, n)), None, None)
        if log:
            pos = H[H > 0]
            H = np.log10(np.maximum(H, pos.min() if pos.size else 1e-300))
        im = ax.imshow(H, origin="lower", extent=(-1, 1, -1, 1), cmap="viridis")
        ax.figure.colorbar(im, ax=ax, label=("log10 " if log else "") + "power per direction-cosine bin")
        ax.set_xlabel("direction cosine l (x)")
        ax.set_ylabel("direction cosine m (y)")
    else:
        Z = d.image(rays, **select)
        if log:
            pos = Z[Z > 0]
            Z = np.log10(np.maximum(Z, pos.min() if pos.size else 1e-300))
        im = ax.imshow(Z, origin="lower", extent=d.extent, cmap="inferno")
        ax.figure.colorbar(im, ax=ax, label=("log10 " if log else "") + "irradiance (power / area)")
        ax.set_xlabel("x")
        ax.set_ylabel("y")
    ax.set_title(title, fontsize=9)
    return ax


def ns_paths(paths, ax=None, n=15):
    """Bar chart of the power of the brightest ray paths (from :meth:`NSTraceResult.paths`)."""
    ax = _ax(ax, figsize=(8, 5))
    top = paths[:n]
    if not top:
        ax.text(0.5, 0.5, "No ray reached the detector", ha="center", va="center", transform=ax.transAxes)
        return ax
    y = np.arange(len(top))[::-1]
    cols = ["C0" if p["n_reflections"] == 0 else "C2" if p["n_reflections"] == 1 else "C3" for p in top]
    ax.barh(y, [max(p["power"], 1e-300) for p in top], color=cols)
    ax.set_xscale("log")
    ax.set_yticks(y)
    ax.set_yticklabels([f"{k + 1}: {p['n_reflections']} refl., {p['rays']} rays" for k, p in enumerate(top)],
                       fontsize=7)
    ax.set_xlabel("power on the detector")
    ax.grid(True, axis="x", alpha=0.3)
    return ax
