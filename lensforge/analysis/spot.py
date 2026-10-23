"""Spot diagrams."""

from __future__ import annotations

import numpy as np

from ..pupil import pupil_grid
from ..raytrace import trace_rays
from .common import resolve_field, resolve_wavelengths


def spot_diagram(system, field=0, wavelengths=None, pattern: str = "hexapolar", rings: int = 6,
                 reference: str = "chief"):
    """Spot diagram for one field point.

    Returns a dict with per-wavelength ``x``, ``y`` arrays (relative to the
    reference point), and ``rms_radius`` / ``geo_radius`` / ``centroid`` over
    all wavelengths (weighted by wavelength weights).  ``reference`` is
    "chief" (primary chief ray) or "centroid".
    """
    hx, hy = resolve_field(system, field)
    px, py = pupil_grid(pattern, rings)
    wls = resolve_wavelengths(system, wavelengths)
    weights = {w.value: w.weight for w in system.wavelengths}
    xs, ys, ws = [], [], []
    per = []
    for w in wls:
        r = trace_rays(system, hx, hy, px, py, wavelength=w)
        x, y = r.x[r.valid], r.y[r.valid]
        per.append((w, x, y))
        xs.append(x)
        ys.append(y)
        ws.append(np.full(x.size, weights.get(w, 1.0)))
    X, Y, Wt = np.concatenate(xs), np.concatenate(ys), np.concatenate(ws)
    if reference == "centroid":
        cx, cy = np.average(X, weights=Wt), np.average(Y, weights=Wt)
    else:
        c = trace_rays(system, hx, hy, 0.0, 0.0, wavelength=system.primary, apertures=False)
        cx, cy = c.x[0], c.y[0]
    dx, dy = X - cx, Y - cy
    r2 = dx * dx + dy * dy
    return {
        "field": (hx, hy),
        "reference": (float(cx), float(cy)),
        "wavelengths": [p[0] for p in per],
        "x": [p[1] - cx for p in per],
        "y": [p[2] - cy for p in per],
        "rms_radius": float(np.sqrt(np.average(r2, weights=Wt))) if r2.size else float("nan"),
        "geo_radius": float(np.sqrt(r2.max())) if r2.size else float("nan"),
        "centroid": (float(np.average(X, weights=Wt)), float(np.average(Y, weights=Wt))) if r2.size else None,
        "n_rays": int(X.size),
        "n_launched": int(px.size * len(wls)),
    }
