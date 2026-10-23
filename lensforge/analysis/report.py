"""Text/dict reports: cardinal points, single-ray trace table, glass dispersion,
and a full system report combining the main analyses."""

from __future__ import annotations

import math

import numpy as np

from ..paraxial import ParaxialAnalysis
from ..raytrace import ERROR_NAMES, trace_rays


def cardinal_points(system, wavelength=None):
    """Focal, principal and nodal points and focal lengths.

    Object-side positions are measured from surface 1, image-side ones from
    the last surface before the image (lens units, + to the right).
    """
    p = ParaxialAnalysis(system, wavelength)
    n, n2 = p.n_object, p.n_image
    f = p.efl
    zF, zF2 = p.ffl, p.bfl
    out = {"efl": f, "front_focal_length": -n * f, "rear_focal_length": n2 * f,
            "front_focal_point": zF, "rear_focal_point": zF2,
            "front_principal_plane": zF + n * f, "rear_principal_plane": zF2 - n2 * f,
            "front_nodal_point": zF + n2 * f, "rear_nodal_point": zF2 - n * f,
            "front_antiprincipal_plane": zF - n * f, "rear_antiprincipal_plane": zF2 + n2 * f}
    return {k: float(v) for k, v in out.items()}


def ray_trace_table(system, hx=0.0, hy=0.0, px=0.0, py=0.0, wavelength=None):
    """Per-surface data of one real ray (Zemax "Single Ray Trace").

    Rows: surface, local x/y/z, direction cosines L/M/N after the surface,
    angle of incidence (deg), cumulative optical path, plus ray status.
    """
    r = trace_rays(system, hx, hy, px, py, wavelength=wavelength)
    rows = []
    for k in range(1, r.positions.shape[0]):
        P, D, Nv = r.positions[k, 0], r.directions[k, 0], r.normals[k, 0]
        Din = r.directions[k - 1, 0]
        with np.errstate(invalid="ignore"):
            aoi = math.degrees(math.acos(min(1.0, abs(float(np.dot(Din, Nv)))))) if np.all(np.isfinite(Din)) else math.nan
        rows.append({"surface": k, "x": P[0], "y": P[1], "z": P[2], "L": D[0], "M": D[1], "N": D[2],
                     "aoi_deg": aoi, "opl": r.opl[k, 0]})
    return {"rows": rows, "status": ERROR_NAMES[int(r.status[0])], "error_surface": int(r.error_surface[0])}


def format_ray_table(table) -> str:
    lines = [f"{'Surf':>4} {'X':>12} {'Y':>12} {'Z':>12} {'L':>10} {'M':>10} {'N':>10} {'AOI':>8} {'OPL':>12}"]
    for r in table["rows"]:
        lines.append(f"{r['surface']:>4} {r['x']:12.6g} {r['y']:12.6g} {r['z']:12.6g} {r['L']:10.6f} {r['M']:10.6f}"
                     f" {r['N']:10.6f} {r['aoi_deg']:8.3f} {r['opl']:12.6g}")
    lines.append(f"status: {table['status']}")
    return "\n".join(lines)


def dispersion(system, material, wl_min=0.4, wl_max=0.8, n: int = 41):
    """Index vs wavelength of a material (name or Material)."""
    m = system.library.resolve(material) if not hasattr(material, "index") else material
    lam = np.linspace(wl_min, wl_max, n)
    return {"wavelength": lam, "index": np.array([float(m.index(l)) for l in lam])}


def system_report(system, mtf_frequency=None, diffraction: bool = True) -> str:
    """Multi-section text report: prescription, first-order data, cardinal
    points, Seidel sums and per-field image quality."""
    from .field import distortion
    from .fans import wavefront
    from .mtf import mtf_at
    from .psf import strehl
    from .seidel import seidel_table
    from .spot import spot_diagram

    par = system.paraxial()
    out = [f"SYSTEM REPORT: {system.name}", "", system.prescription(), "", "First-order data:", repr(par), "",
           "Cardinal points:"]
    out += [f"{k:>26}: {v:.6g}" for k, v in cardinal_points(system).items()]
    out += ["", "Seidel coefficients:", seidel_table(system), "", "Image quality per field:"]
    if mtf_frequency is None:
        mtf_frequency = round(0.25 / (system.primary * system.wavelength_scale * par.working_fnum), -1) or 10
    hdr = f"{'field':>6} {'value':>9} {'RMS spot':>12} {'RMS WFE':>9} {'dist %':>9}"
    if diffraction:
        hdr += f" {'Strehl':>8} {'MTF T':>7} {'MTF S':>7}  @ {mtf_frequency:g} cyc/unit"
    out.append(hdr)
    for i, f in enumerate(system.fields):
        sp = spot_diagram(system, i)["rms_radius"]
        w = wavefront(system, i, n=32, remove_tilt=True)["rms"]
        h = system.normalized_field(i)
        d = distortion(system, h[1]) if h[1] else 0.0
        line = f"{i:>6} {math.hypot(f.x, f.y):9.4g} {sp:12.6g} {w:9.4f} {d:9.4f}"
        if diffraction:
            st = strehl(system, i)
            t, s = mtf_at(system, mtf_frequency, i)
            line += f" {st:8.4f} {t:7.4f} {s:7.4f}"
        out.append(line)
    return "\n".join(out)
