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


def layout(result, ax=None, plane="y"):
    """2-D layout from :func:`lensforge.analysis.geometry.layout`."""
    ax = _ax(ax, figsize=(9, 4))
    j = 1 if plane == "y" else 0
    colors = _plt().rcParams["axes.prop_cycle"].by_key()["color"]
    for s in result["surfaces"]:
        P = s["points"]
        ax.plot(P[:, 2], P[:, j], color="k", lw=1.5 if s["mirror"] else 1)
    for r in result["rays"]:
        c = colors[r["field"] % len(colors)] if isinstance(r["field"], int) else colors[0]
        p = r["path"]
        ax.plot(p[:, :, 2], p[:, :, j], color=c, lw=0.6)
    ax.set_aspect("equal", adjustable="datalim")
    ax.set_xlabel("z")
    ax.set_ylabel(plane)
    return ax


def spot(result, ax=None, scale=1.0):
    ax = _ax(ax, figsize=(4, 4))
    for w, x, y in zip(result["wavelengths"], result["x"], result["y"]):
        ax.plot(np.asarray(x) * scale, np.asarray(y) * scale, ".", ms=2, label=_wl_label(w))
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


def ray_fan(result, axes=None):
    if axes is None:
        _, axes = _plt().subplots(1, 2, figsize=(8, 3.5), sharey=True)
    for w, ey, ex in zip(result["wavelengths"], result["ey"], result["ex"]):
        axes[0].plot(result["p"], ey, label=_wl_label(w))
        axes[1].plot(result["p"], ex)
    axes[0].set_title("Tangential ey vs py")
    axes[1].set_title("Sagittal ex vs px")
    axes[0].legend(fontsize=7)
    for a in axes:
        a.axhline(0, color="0.6", lw=0.5)
    return axes


def opd_fan(result, axes=None):
    if axes is None:
        _, axes = _plt().subplots(1, 2, figsize=(8, 3.5), sharey=True)
    for w, wy, wx in zip(result["wavelengths"], result["wy"], result["wx"]):
        axes[0].plot(result["p"], wy, label=_wl_label(w))
        axes[1].plot(result["p"], wx)
    axes[0].set_title("Tangential OPD (waves)")
    axes[1].set_title("Sagittal OPD (waves)")
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


def psf(result, ax=None, log=False):
    Z = result["psf"] / result["perfect"].max()
    if log:
        Z = np.log10(np.maximum(Z, 1e-8))
    return map2d(Z, result["x"], result["y"], ax, f"{result['method'].upper()} PSF, Strehl {result['strehl']:.4f}",
                 cmap="inferno")


def mtf(result, ax=None, diffraction=True):
    ax = _ax(ax, figsize=(6, 4))
    l1, = ax.plot(result["freq"], result["tangential"], label="T")
    ax.plot(result["freq"], result["sagittal"], "--", color=l1.get_color(), label="S")
    if diffraction and "diffraction_limit_tangential" in result:
        ax.plot(result["freq"], result["diffraction_limit_tangential"], color="k", lw=0.8, label="diffraction limit")
    ax.set_xlabel("spatial frequency (cycles per lens unit)")
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


def mtf_vs_field(result, ax=None):
    ax = _ax(ax, figsize=(6, 4))
    for k, f in enumerate(result["frequencies"]):
        l, = ax.plot(result["field"], result["tangential"][:, k], label=f"T {f:g}")
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


def field_curvature(result, axes=None):
    if axes is None:
        _, axes = _plt().subplots(1, 2, figsize=(8, 4), sharey=True)
    for k, w in enumerate(result["wavelengths"]):
        l, = axes[0].plot(result["tangential"][k], result["field_value"], label=f"T {_wl_label(w)}")
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


def lateral_color(result, ax=None):
    ax = _ax(ax, figsize=(5, 4))
    for w, d in zip(result["wavelengths"], result["difference"]):
        ax.plot(d, result["field"], label=_wl_label(w))
    ax.set_xlabel("image height difference from primary")
    ax.set_ylabel("normalised field")
    ax.legend(fontsize=7)
    return ax


def longitudinal_aberration(result, ax=None):
    ax = _ax(ax, figsize=(5, 4))
    for w, z in zip(result["wavelengths"], result["focus"]):
        ax.plot(z, result["pupil"], label=_wl_label(w))
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
