"""Catalogue of analysis windows.

Each :class:`AnalysisSpec` names a lensforge analysis, the settings shown in
its window, a ``compute(system, **opts)`` function (runs in a worker thread on
a copy of the lens, returns the analysis dict or text) and a
``plot(fig, result, opts, system)`` function (GUI thread, matplotlib).  The
computations are the public lensforge API; plotting reuses
:mod:`lensforge.plot` wherever it fits.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field as dc_field
from typing import Any, Callable, List, Optional

import numpy as np

import lensforge as lf
import lensforge.plot as P

from . import rays as R


@dataclass
class Setting:
    name: str
    label: str
    kind: str  # field, field_all, wave, wave_all, surface, int, float, choice, bool
    default: Any = None
    choices: Optional[list] = None  # (label, value) pairs for "choice"
    minimum: float = 0
    maximum: float = 1e6


@dataclass
class AnalysisSpec:
    key: str
    title: str
    group: str
    compute: Callable
    plot: Optional[Callable] = None  # None: text result
    settings: List[Setting] = dc_field(default_factory=list)
    shortcut: Optional[str] = None
    uses_rays: bool = False  # sampling comes from the Input Rays dialog


REGISTRY: dict = {}
GROUPS: list = []


def register(spec: AnalysisSpec):
    REGISTRY[spec.key] = spec
    if spec.group not in GROUPS:
        GROUPS.append(spec.group)
    return spec


def _waves(system, w):
    """Setting value -> ``wavelengths`` argument (None = all)."""
    return None if w is None or w < 0 else [int(w)]


def _wave(system, w):
    """Setting value -> one wavelength in um (primary if "all"/None)."""
    return system.primary if w is None or w < 0 else system.wavelengths[int(w)].value


def _fields(system, f):
    return list(range(len(system.fields))) if f is None or f < 0 else [int(f)]


def _field_title(system, f):
    fl = system.fields[f]
    unit = "deg" if system.field_type == "ANGLE" else system.units
    return f"Field {f + 1}: ({fl.x:g}, {fl.y:g}) {unit}"


FIELD = Setting("field", "Field", "field", 0)
FIELD_ALL = Setting("field", "Field", "field_all", -1)
WAVE_ALL = Setting("wave", "Wavelength", "wave_all", -1)
WAVE = Setting("wave", "Wavelength", "wave", -1)


def _grid(fig, n):
    cols = min(n, 3)
    rows = int(math.ceil(n / cols))
    return [fig.add_subplot(rows, cols, k + 1) for k in range(n)]


def _legend_note(fig, text):
    fig.text(0.01, 0.005, text, fontsize=7, color="0.35", ha="left", va="bottom")


# ---------------------------------------------------------------------------
# Layout and geometry
# ---------------------------------------------------------------------------

def _layout_compute(system):
    ir = R.get(system)
    r = lf.layout(system, fields=R.fields(system, ir["layout_fields"]), wavelengths=R.waves(system, ir["layout_waves"]),
                  n_rays=ir["layout_rays"], plane=ir["layout_plane"])
    r["plane"] = ir["layout_plane"]
    r["user_rays"] = []
    for ray in ir["user_rays"]:
        t = lf.trace_rays(system, ray["hx"], ray["hy"], ray["px"], ray["py"],
                          wavelength=R.user_ray_wavelength(system, ray))
        G = t.global_positions()[:, 0]
        start = 0 if system.object_at_infinity else 1
        path = G[start:]
        if not t.valid[0] and t.error_surface[0] >= 0:
            path[t.error_surface[0] - start + 1:] = np.nan
        r["user_rays"].append(path)
    return r


def _layout_plot(fig, r, opts, system):
    ax = fig.add_subplot(111)
    plane = r.get("plane", "y")
    j = 0 if plane == "x" else 1
    # colour by field, or by wavelength when only one field is drawn (shows dispersion)
    fields = sorted({ray["field"] for ray in r["rays"] if isinstance(ray["field"], int)})
    waves = sorted({ray["wavelength"] for ray in r["rays"]})
    by_wave = len(fields) <= 1 and len(waves) > 1
    for srf in r["surfaces"]:
        p = srf["points"]
        ax.plot(p[:, 2], p[:, j], color="k", lw=1.5 if srf["mirror"] else 1)
    labelled = set()
    for ray in r["rays"]:
        key = ray["wavelength"] if by_wave else ray["field"]
        k = waves.index(key) if by_wave else (fields.index(key) if key in fields else 0)
        lab = None
        if key not in labelled:
            labelled.add(key)
            lab = f"{key:.4f} um" if by_wave else f"field {key + 1}"
        p = ray["path"]
        lines = ax.plot(p[:, :, 2], p[:, :, j], color=f"C{k % 10}", lw=0.6)
        if lab and lines:
            lines[0].set_label(lab)
    ax.set_aspect("equal", adjustable="datalim")
    for s in r["surfaces"]:
        p = s["points"]
        ax.annotate(str(s["surface"]), (p[-1, 2], p[-1, j]), fontsize=7, color="0.4",
                    xytext=(0, 3), textcoords="offset points", ha="center")
    _connect_lens_edges(ax, r, system, j)
    for k, path in enumerate(r.get("user_rays", [])):
        ax.plot(path[:, 2], path[:, j], color="crimson", lw=1.1, ls="--", label="user rays" if k == 0 else None)
    ax.legend(fontsize=7, loc="upper left")
    ax.set_title(f"{system.name or 'Lens'}: layout")
    ax.set_xlabel(f"z ({system.units})")
    ax.set_ylabel(f"{'x' if plane == 'x' else 'y'} ({system.units})")


def _connect_lens_edges(ax, r, system, j):
    """Draw element edges between consecutive surfaces bounding glass."""
    surfs = {s["surface"]: s for s in r["surfaces"]}
    for i in surfs:
        if i + 1 not in surfs:
            continue
        m = system.library.resolve(system.surfaces[i].material)
        if m.is_mirror or m.nd == 1.0:
            continue
        a, b = surfs[i]["points"], surfs[i + 1]["points"]
        for k in (0, -1):
            ax.plot([a[k, 2], b[k, 2]], [a[k, j], b[k, j]], color="k", lw=1)


register(AnalysisSpec("layout", "2D Layout", "Layout", _layout_compute, _layout_plot, [], shortcut="Ctrl+L",
                      uses_rays=True))


def _footprint_compute(system, surface=1, wave=-1, field=-1):
    return lf.footprint(system, surface, fields=_fields(system, field), wavelengths=_waves(system, wave),
                        n_ring=R.get(system)["footprint_rays"])


register(AnalysisSpec("footprint", "Footprint Diagram", "Layout", _footprint_compute,
                      lambda fig, r, o, s: P.footprint(r, fig.add_subplot(111)),
                      [Setting("surface", "Surface", "surface", 1), FIELD_ALL, WAVE_ALL], uses_rays=True))


def _sag_compute(system, surface=1, departure=False):
    s = system.surfaces[surface]
    sd = s.semi_diameter
    if sd is None:
        from .edits import fill_auto_semi_diameters
        sd = fill_auto_semi_diameters(system)[1].get(surface, 10.0)
    return lf.surface_sag(s, sd)


register(AnalysisSpec("sag", "Surface Sag", "Layout", _sag_compute,
                      lambda fig, r, o, s: P.sag(r, fig.add_subplot(111), departure=bool(o.get("departure"))),
                      [Setting("surface", "Surface", "surface", 1),
                       Setting("departure", "Departure from BFS", "bool", False)]))

# ---------------------------------------------------------------------------
# Rays and spots
# ---------------------------------------------------------------------------


def _fan_compute(system, field=-1, wave=-1, kind="ray"):
    fn = lf.ray_fan if kind == "ray" else lf.opd_fan
    n = R.get(system)["fan_points"]
    return [(f, fn(system, f, _waves(system, wave), n=n)) for f in _fields(system, field)]


def _fan_plot(fig, res, opts, system, kind="ray"):
    n = len(res)
    for k, (f, r) in enumerate(res):
        a1 = fig.add_subplot(n, 2, 2 * k + 1)
        a2 = fig.add_subplot(n, 2, 2 * k + 2, sharey=a1)
        (P.ray_fan if kind == "ray" else P.opd_fan)(r, [a1, a2])
        a1.set_ylabel(_field_title(system, f), fontsize=8)
        if k:
            a1.set_title("")
            a2.set_title("")
            if a1.get_legend():
                a1.get_legend().remove()
        for a in (a1, a2):
            a.axhline(0, color="0.6", lw=0.5)
            a.axvline(0, color="0.6", lw=0.5)
            a.tick_params(labelsize=7)


register(AnalysisSpec("ray_fan", "Ray Aberration (Ray Fan)", "Rays & Spots",
                      lambda s, **o: _fan_compute(s, kind="ray", **o), lambda *a: _fan_plot(*a, kind="ray"),
                      [FIELD_ALL, WAVE_ALL], shortcut="Ctrl+R", uses_rays=True))
register(AnalysisSpec("opd_fan", "Optical Path (OPD Fan)", "Rays & Spots",
                      lambda s, **o: _fan_compute(s, kind="opd", **o), lambda *a: _fan_plot(*a, kind="opd"),
                      [FIELD_ALL, WAVE_ALL], uses_rays=True))


def _spot_compute(system, field=-1, wave=-1):
    ir = R.get(system)
    pattern, rings, reference = ir["spot_pattern"], ir["spot_rings"], ir["spot_reference"]
    return [(f, lf.spot_diagram(system, f, _waves(system, wave), pattern=pattern, rings=rings,
                                reference=reference)) for f in _fields(system, field)]


def _spot_plot(fig, res, opts, system):
    axes = _grid(fig, len(res))
    lim = max((np.nanmax(np.abs(np.concatenate([np.concatenate([np.ravel(x) for x in r["x"]] or [[0]]),
                                                 np.concatenate([np.ravel(y) for y in r["y"]] or [[0]])])))
               for _, r in res if r["x"]), default=1.0)
    lim = lim * 1.1 if lim > 0 else 1.0
    scale = 1000.0 if system.units == "mm" else 1.0
    unit = "um" if system.units == "mm" else system.units
    for ax, (f, r) in zip(axes, res):
        P.spot(r, ax, scale=scale)
        ax.set_xlim(-lim * scale, lim * scale)
        ax.set_ylim(-lim * scale, lim * scale)
        ax.set_title(f"{_field_title(system, f)}\nRMS {r['rms_radius'] * scale:.4g} {unit}, "
                     f"GEO {r['geo_radius'] * scale:.4g} {unit}", fontsize=8)
        ax.tick_params(labelsize=7)
        if ax is not axes[0] and ax.get_legend():
            ax.get_legend().remove()
    ir = R.get(system)
    _legend_note(fig, f"Spot diagram, units {unit}, reference: {ir['spot_reference']}, "
                      f"{ir['spot_pattern']} {ir['spot_rings']}")


register(AnalysisSpec("spot", "Standard Spot Diagram", "Rays & Spots", _spot_compute, _spot_plot,
                      [FIELD_ALL, WAVE_ALL], shortcut="Ctrl+S", uses_rays=True))


def _tfs_compute(system, field=0, wave=-1, steps=7, focus_range=0.0):
    ir = R.get(system)
    return lf.through_focus_spot(system, field, _waves(system, wave), focus_range=focus_range or None, steps=steps,
                                 pattern=ir["spot_pattern"], rings=ir["spot_rings"])


def _tfs_plot(fig, r, opts, system):
    n = len(r["spots"])
    axes = [fig.add_subplot(1, n, k + 1) for k in range(n)]
    lim = max(max((np.nanmax(np.abs(np.concatenate([np.ravel(x) for x in s["x"]]))) for s in r["spots"]
                   if s["x"]), default=1.0), 1e-12) * 1.1
    for ax, dz, s in zip(axes, r["focus"], r["spots"]):
        for w, x, y in zip(s["wavelengths"], s["x"], s["y"]):
            ax.plot(x, y, ".", ms=1.5)
        ax.set_xlim(-lim, lim)
        ax.set_ylim(-lim, lim)
        ax.set_aspect("equal")
        ax.set_title(f"{dz:+.4g}\nRMS {s['rms_radius']:.3g}", fontsize=7)
        ax.set_xticks([])
        ax.set_yticks([])
    _legend_note(fig, f"Through-focus spot, {_field_title(system, opts.get('field', 0))}")


register(AnalysisSpec("through_focus_spot", "Through Focus Spot Diagram", "Rays & Spots", _tfs_compute, _tfs_plot,
                      [FIELD, WAVE_ALL, Setting("steps", "Steps", "int", 7, minimum=3, maximum=15),
                       Setting("focus_range", "Range (0 = auto)", "float", 0.0, minimum=0, maximum=1e4)]))


def _ffs_plot(fig, r, opts, system):
    ax = fig.add_subplot(111)
    ax.plot(r["field"], r["rms_radius"], "o-")
    ax.set_xlabel("normalised field")
    ax.set_ylabel(f"RMS spot radius ({system.units})")
    ax.set_title("RMS spot radius vs field")
    ax.grid(alpha=0.3)


register(AnalysisSpec("rms_vs_field", "RMS Spot vs Field", "Rays & Spots",
                      lambda s, wave=-1, n_fields=11: lf.full_field_spot(s, _waves(s, wave), n_fields=n_fields),
                      _ffs_plot, [WAVE_ALL, Setting("n_fields", "Field points", "int", 11, minimum=2, maximum=51)]))

# ---------------------------------------------------------------------------
# Wavefront
# ---------------------------------------------------------------------------

register(AnalysisSpec("wavefront", "Wavefront Map", "Wavefront",
                      lambda s, field=0, wave=-1, n=64, remove_tilt=False: lf.wavefront(
                          s, field, _wave(s, wave), n=n, remove_tilt=remove_tilt),
                      lambda fig, r, o, s: P.wavefront(r, fig.add_subplot(111)),
                      [FIELD, WAVE, Setting("n", "Sampling", "choice", 64, [("32", 32), ("64", 64), ("128", 128)]),
                       Setting("remove_tilt", "Remove tilt", "bool", False)], shortcut="Ctrl+W"))
register(AnalysisSpec("interferogram", "Interferogram", "Wavefront",
                      lambda s, field=0, wave=-1, tilt_x=0.0, tilt_y=0.0: lf.interferogram(
                          s, field, _wave(s, wave), tilt_x=tilt_x, tilt_y=tilt_y),
                      lambda fig, r, o, s: P.interferogram(r, fig.add_subplot(111)),
                      [FIELD, WAVE, Setting("tilt_x", "Fringes X tilt", "float", 0.0, minimum=-100, maximum=100),
                       Setting("tilt_y", "Fringes Y tilt", "float", 0.0, minimum=-100, maximum=100)]))


def _zernike_compute(system, field=0, wave=-1, kind="fringe", n_terms=37):
    return lf.zernike_coefficients(system, field, _wave(system, wave), n_terms=n_terms, kind=kind)


def _zernike_text(r):
    lines = [f"Zernike {r['kind'].title()} coefficients (waves)"]
    for k in ("pv", "rms"):
        if k in r:
            v = r[k]
            lines.append(f"  {k.upper()}: {v}" if not isinstance(v, float) else f"  {k.upper()}: {v:.6f}")
    names = r.get("names") or [""] * len(r["coefficients"])
    for j, (c, n) in enumerate(zip(r["coefficients"], names), start=1):
        lines.append(f"  Z{j:<3d} {c:+12.6f}   {n}")
    return "\n".join(lines)


register(AnalysisSpec("zernike", "Zernike Coefficients", "Wavefront", _zernike_compute,
                      lambda fig, r, o, s: P.zernike(r, fig.add_subplot(111)),
                      [FIELD, WAVE, Setting("kind", "Kind", "choice", "fringe",
                                            [("Fringe", "fringe"), ("Standard", "standard")]),
                       Setting("n_terms", "Terms", "int", 37, minimum=4, maximum=231)]))
register(AnalysisSpec("zernike_text", "Zernike Coefficients (text)", "Wavefront",
                      lambda s, **o: _zernike_text(_zernike_compute(s, **o)), None,
                      [FIELD, WAVE, Setting("kind", "Kind", "choice", "fringe",
                                            [("Fringe", "fringe"), ("Standard", "standard")]),
                       Setting("n_terms", "Terms", "int", 37, minimum=4, maximum=231)]))

# ---------------------------------------------------------------------------
# PSF / MTF / energy
# ---------------------------------------------------------------------------


def _psf_compute(system, field=0, wave=-1, method="fft", pupil_n=64, log=False):
    fn = lf.fft_psf if method == "fft" else lf.huygens_psf
    return fn(system, field, _waves(system, wave), pupil_n=pupil_n)


def _psf_plot(fig, r, opts, system):
    ax = fig.add_subplot(111)
    P.psf(r, ax, log=bool(opts.get("log")))
    ax.set_xlabel(system.units)
    for w in r.get("warnings", []):
        _legend_note(fig, w)


register(AnalysisSpec("psf", "PSF", "PSF & MTF", _psf_compute, _psf_plot,
                      [FIELD, WAVE_ALL, Setting("method", "Method", "choice", "fft",
                                                [("FFT", "fft"), ("Huygens", "huygens")]),
                       Setting("pupil_n", "Pupil sampling", "choice", 64, [("32", 32), ("64", 64), ("128", 128)]),
                       Setting("log", "Log scale", "bool", False)], shortcut="Ctrl+P"))


def _psf_x_plot(fig, r, opts, system):
    ax = fig.add_subplot(111)
    for k, axis in enumerate(("x", "y")):
        res = lf.psf_cross_section(r, axis)
        x, v = res[0], res[1]
        ax.plot(x, v / np.max(r["perfect"]), label=f"{axis} section")
    ax.set_xlabel(system.units)
    ax.set_ylabel("relative irradiance (perfect peak = 1)")
    ax.set_title(f"PSF cross section, Strehl {r['strehl']:.4f}")
    ax.legend(fontsize=8)


register(AnalysisSpec("psf_cross", "PSF Cross Section", "PSF & MTF", _psf_compute, _psf_x_plot,
                      [FIELD, WAVE_ALL, Setting("method", "Method", "choice", "fft",
                                                [("FFT", "fft"), ("Huygens", "huygens")])]))


def _mtf_compute(system, field=-1, wave=-1, method="fft", max_freq=0.0):
    out = []
    for f in _fields(system, field):
        kw = {"max_freq": max_freq} if max_freq else {}
        out.append((f, lf.mtf(system, f, _waves(system, wave), method=method, **kw)))
    return out


def _mtf_plot(fig, res, opts, system):
    ax = fig.add_subplot(111)
    for k, (f, r) in enumerate(res):
        c = f"C{k % 10}"
        ax.plot(r["freq"], r["tangential"], color=c, label=f"F{f + 1} T")
        ax.plot(r["freq"], r["sagittal"], "--", color=c, label=f"F{f + 1} S")
    r0 = res[0][1]
    if "diffraction_limit_tangential" in r0:
        ax.plot(r0["freq"], r0["diffraction_limit_tangential"], color="k", lw=0.8, label="Diff. limit")
    ax.set_xlabel("spatial frequency (cycles/mm)")
    ax.set_ylabel("modulus of the OTF")
    ax.set_ylim(0, 1.02)
    ax.set_xlim(left=0)
    ax.grid(alpha=0.3)
    ax.legend(fontsize=7, ncol=2)
    ax.set_title(f"{opts.get('method', 'fft').upper()} MTF")


register(AnalysisSpec("mtf", "MTF", "PSF & MTF", _mtf_compute, _mtf_plot,
                      [FIELD_ALL, WAVE_ALL, Setting("method", "Method", "choice", "fft",
                                                    [("FFT", "fft"), ("Huygens", "huygens"),
                                                     ("Geometric", "geometric")]),
                       Setting("max_freq", "Max frequency (0 = auto)", "float", 0.0, minimum=0, maximum=1e5)],
                      shortcut="Ctrl+M"))


def _tfm_compute(system, frequency=50.0, field=-1, wave=-1, steps=21, method="fft"):
    return [(f, lf.through_focus_mtf(system, frequency, f, _waves(system, wave), steps=steps, method=method))
            for f in _fields(system, field)]


def _tfm_plot(fig, res, opts, system):
    ax = fig.add_subplot(111)
    for k, (f, r) in enumerate(res):
        c = f"C{k % 10}"
        ax.plot(r["focus"], r["tangential"], color=c, label=f"F{f + 1} T")
        ax.plot(r["focus"], r["sagittal"], "--", color=c, label=f"F{f + 1} S")
    ax.set_xlabel(f"focus shift ({system.units})")
    ax.set_ylabel(f"MTF at {opts.get('frequency', 50):g} cycles/mm")
    ax.set_ylim(0, 1.02)
    ax.grid(alpha=0.3)
    ax.legend(fontsize=7, ncol=2)


register(AnalysisSpec("through_focus_mtf", "Through Focus MTF", "PSF & MTF", _tfm_compute, _tfm_plot,
                      [Setting("frequency", "Frequency (cycles/mm)", "float", 50.0, minimum=0.01, maximum=1e5),
                       FIELD_ALL, WAVE_ALL, Setting("steps", "Steps", "int", 21, minimum=3, maximum=101),
                       Setting("method", "Method", "choice", "fft", [("FFT", "fft"), ("Geometric", "geometric")])]))


def _mvf_compute(system, f1=10.0, f2=30.0, f3=50.0, wave=-1, method="fft"):
    freqs = [f for f in (f1, f2, f3) if f > 0]
    return lf.mtf_vs_field(system, freqs, _waves(system, wave), method=method)


register(AnalysisSpec("mtf_vs_field", "MTF vs Field", "PSF & MTF", _mvf_compute,
                      lambda fig, r, o, s: P.mtf_vs_field(r, fig.add_subplot(111)),
                      [Setting("f1", "Frequency 1", "float", 10.0, minimum=0, maximum=1e5),
                       Setting("f2", "Frequency 2", "float", 30.0, minimum=0, maximum=1e5),
                       Setting("f3", "Frequency 3", "float", 50.0, minimum=0, maximum=1e5), WAVE_ALL,
                       Setting("method", "Method", "choice", "fft", [("FFT", "fft"), ("Geometric", "geometric")])]))


def _ee_compute(system, field=-1, wave=-1, method="diffraction", kind="encircled"):
    out = []
    for f in _fields(system, field):
        if method == "diffraction":
            out.append((f, lf.diffraction_energy(system, f, _waves(system, wave), kind=kind)))
        else:
            out.append((f, lf.geometric_energy(system, f, _waves(system, wave), kind=kind)))
    return out


def _ee_plot(fig, res, opts, system):
    ax = fig.add_subplot(111)
    for k, (f, r) in enumerate(res):
        ax.plot(r["radius"], r["energy"], color=f"C{k % 10}", label=f"Field {f + 1}")
    r0 = res[0][1]
    if "diffraction_limit" in r0:
        ax.plot(r0["radius"], r0["diffraction_limit"], color="k", lw=0.8, label="Diff. limit")
    ax.set_xlabel(f"{'radius' if r0['kind'] == 'encircled' else 'half width'} ({system.units})")
    ax.set_ylabel(f"fraction of {r0['kind']} energy")
    ax.set_ylim(0, 1.02)
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8)


register(AnalysisSpec("encircled_energy", "Encircled Energy", "PSF & MTF", _ee_compute, _ee_plot,
                      [FIELD_ALL, WAVE_ALL, Setting("method", "Method", "choice", "diffraction",
                                                    [("Diffraction", "diffraction"), ("Geometric", "geometric")]),
                       Setting("kind", "Type", "choice", "encircled",
                               [("Encircled", "encircled"), ("Ensquared", "ensquared"), ("X line", "x"),
                                ("Y line", "y")])]))

# ---------------------------------------------------------------------------
# Aberrations
# ---------------------------------------------------------------------------

register(AnalysisSpec("field_curvature", "Field Curvature / Distortion", "Aberrations",
                      lambda s, wave=-1, distortion="ftan": lf.field_curvature(s, _waves(s, wave),
                                                                                distortion=distortion),
                      lambda fig, r, o, s: P.field_curvature(r, [fig.add_subplot(121), fig.add_subplot(122)]),
                      [WAVE_ALL, Setting("distortion", "Distortion", "choice", "ftan",
                                         [("F-Tan(theta)", "ftan"), ("F-Theta", "ftheta")])], shortcut="Ctrl+F"))
register(AnalysisSpec("grid_distortion", "Grid Distortion", "Aberrations",
                      lambda s, n=11, wave=-1: lf.grid_distortion(s, n, _wave(s, wave)),
                      lambda fig, r, o, s: P.grid_distortion(r, fig.add_subplot(111)),
                      [Setting("n", "Grid size", "int", 11, minimum=3, maximum=41), WAVE]))
register(AnalysisSpec("lateral_color", "Lateral Color", "Aberrations",
                      lambda s, wave=-1: lf.lateral_color(s, _waves(s, wave)),
                      lambda fig, r, o, s: P.lateral_color(r, fig.add_subplot(111)), [WAVE_ALL]))
register(AnalysisSpec("longitudinal", "Longitudinal Aberration", "Aberrations",
                      lambda s, wave=-1: lf.longitudinal_aberration(s, _waves(s, wave)),
                      lambda fig, r, o, s: P.longitudinal_aberration(r, fig.add_subplot(111)), [WAVE_ALL]))
register(AnalysisSpec("focal_shift", "Chromatic Focal Shift", "Aberrations",
                      lambda s: lf.chromatic_focal_shift(s),
                      lambda fig, r, o, s: P.chromatic_focal_shift(r, fig.add_subplot(111)), []))


def _seidel_plot(fig, r, opts, system):
    P.seidel(r, fig.add_subplot(111))


register(AnalysisSpec("seidel", "Seidel Diagram", "Aberrations", lambda s, wave=-1: lf.seidel(s, _wave(s, wave)),
                      _seidel_plot, [WAVE]))
register(AnalysisSpec("seidel_text", "Seidel Coefficients", "Aberrations",
                      lambda s, wave=-1: lf.seidel_table(s, _wave(s, wave)), None, [WAVE]))


def _pupil_ab_plot(fig, r, opts, system):
    ax = fig.add_subplot(111)
    ax.plot(r["pupil"], r["tangential_percent"], label="tangential")
    ax.plot(r["pupil"], r["sagittal_percent"], "--", label="sagittal")
    ax.set_xlabel("pupil coordinate")
    ax.set_ylabel("pupil aberration (%)")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)


register(AnalysisSpec("pupil_aberration", "Pupil Aberration", "Aberrations",
                      lambda s, wave=-1: lf.pupil_aberration(s, 1.0, _wave(s, wave)), _pupil_ab_plot, [WAVE]))

# ---------------------------------------------------------------------------
# Illumination and polarisation
# ---------------------------------------------------------------------------

register(AnalysisSpec("relative_illumination", "Relative Illumination", "Illumination",
                      lambda s, wave=-1: lf.relative_illumination(s, _wave(s, wave)),
                      lambda fig, r, o, s: P.relative_illumination(r, fig.add_subplot(111)), [WAVE]))
register(AnalysisSpec("vignetting", "Vignetting Plot", "Illumination",
                      lambda s, wave=-1: lf.vignetting(s, _wave(s, wave)),
                      lambda fig, r, o, s: P.vignetting(r, fig.add_subplot(111)), [WAVE]))
register(AnalysisSpec("polarization_pupil", "Polarization Pupil Map", "Illumination",
                      lambda s, field=0, wave=-1, polarization="y": lf.polarization_pupil_map(
                          s, field, _wave(s, wave), polarization=polarization),
                      lambda fig, r, o, s: P.polarization_pupil(r, fig.add_subplot(111)),
                      [FIELD, WAVE, Setting("polarization", "Input", "choice", "y",
                                            [("Linear Y", "y"), ("Linear X", "x"), ("Left circular", "lcp"),
                                             ("Right circular", "rcp")])]))


def _transmission_plot(fig, r, opts, system):
    ax = fig.add_subplot(111)
    ax.plot(r["field"], r["transmission"], "o-")
    ax.set_xlabel("normalised field")
    ax.set_ylabel("transmission (Fresnel, uncoated)")
    ax.grid(alpha=0.3)


register(AnalysisSpec("transmission", "Transmission", "Illumination",
                      lambda s, wave=-1: lf.transmission(s, _wave(s, wave)), _transmission_plot, [WAVE]))

# ---------------------------------------------------------------------------
# Reports (text)
# ---------------------------------------------------------------------------


def _prescription(system):
    lines = [system.name or "Lens", "", system.prescription(), "", "First-order properties (primary wavelength):",
             str(system.paraxial())]
    if getattr(system, "variables", None):
        lines += ["", "Variables:"] + [f"  {v.name}  = {v.get(system):.10g}" for v in system.variables]
    if getattr(system, "solves", None):
        from .edits import describe_solve
        lines += ["", "Solves:"] + [f"  S{x.surface} {x.cell[1]}: {describe_solve(x)}" for x in system.solves]
    return "\n".join(lines)


def _ray_trace_text(system, hx=0.0, hy=1.0, px=0.0, py=1.0, wave=-1):
    t = lf.ray_trace_table(system, hx, hy, px, py, _wave(system, wave))
    return (f"Real ray trace: Hx={hx:g} Hy={hy:g} Px={px:g} Py={py:g}, wavelength {_wave(system, wave):.6g} um\n\n"
            + lf.format_ray_table(t))


def _cardinal_text(system, wave=-1):
    c = lf.cardinal_points(system, _wave(system, wave))
    return "Cardinal points (positions relative to the first/last surface vertex)\n\n" + "\n".join(
        f"  {k.replace('_', ' '):28s} {v:16.8g}" for k, v in c.items())


register(AnalysisSpec("prescription", "Prescription Data", "Reports", lambda s: _prescription(s), None, []))
register(AnalysisSpec("system_report", "System Report", "Reports",
                      lambda s, mtf_frequency=0.0: lf.system_report(s, mtf_frequency or None), None,
                      [Setting("mtf_frequency", "MTF frequency (0 = none)", "float", 0.0, minimum=0, maximum=1e5)]))
register(AnalysisSpec("ray_trace", "Single Ray Trace", "Reports", _ray_trace_text, None,
                      [Setting("hx", "Hx", "float", 0.0, minimum=-1, maximum=1),
                       Setting("hy", "Hy", "float", 1.0, minimum=-1, maximum=1),
                       Setting("px", "Px", "float", 0.0, minimum=-1, maximum=1),
                       Setting("py", "Py", "float", 1.0, minimum=-1, maximum=1), WAVE]))
def _user_rays_text(system):
    ir = R.get(system)
    if not ir["user_rays"]:
        return "No user rays. Add them in File > Input Rays."
    out = []
    for k, ray in enumerate(ir["user_rays"], start=1):
        w = R.user_ray_wavelength(system, ray)
        t = lf.ray_trace_table(system, ray["hx"], ray["hy"], ray["px"], ray["py"], w)
        out.append(f"User ray {k}: Hx={ray['hx']:g} Hy={ray['hy']:g} Px={ray['px']:g} Py={ray['py']:g}, "
                   f"wavelength {w:.6g} um\n" + lf.format_ray_table(t))
    return "\n\n".join(out)


register(AnalysisSpec("user_rays", "User Ray Trace", "Reports", _user_rays_text, None, [], uses_rays=True))
register(AnalysisSpec("cardinal_points", "Cardinal Points", "Reports", _cardinal_text, None, [WAVE]))


def _dispersion_compute(system, surface=1):
    m = system.material(surface)
    lo = min(w.value for w in system.wavelengths)
    hi = max(w.value for w in system.wavelengths)
    if hi - lo < 0.2:
        lo, hi = max(0.3, lo - 0.15), hi + 0.15
    r = lf.dispersion(system, m, lo, hi)
    r["name"] = getattr(m, "name", str(system.surfaces[surface].material))
    return r


def _dispersion_plot(fig, r, opts, system):
    ax = fig.add_subplot(111)
    ax.plot(r["wavelength"], r["index"])
    ax.set_xlabel("wavelength (um)")
    ax.set_ylabel("refractive index")
    ax.set_title(f"Dispersion of {r['name']}")
    ax.grid(alpha=0.3)


register(AnalysisSpec("dispersion", "Glass Dispersion", "Reports", _dispersion_compute, _dispersion_plot,
                      [Setting("surface", "Surface (material after)", "surface", 1)]))
