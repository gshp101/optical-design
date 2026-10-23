"""Field-dependent and chromatic analyses: field curvature and distortion,
grid distortion, lateral colour, longitudinal aberration, chromatic focal
shift and pupil aberration.

Field arguments ``h`` are normalised field coordinates (0 .. 1 along +y by
default).  All lengths in lens units.
"""

from __future__ import annotations

import math

import numpy as np

from ..paraxial import ParaxialAnalysis
from ..raytrace import trace_rays
from .common import resolve_wavelengths

_EPS_FIELD = 1e-4
_EPS_PUPIL = 1e-4


def _closest_point(P1, D1, P2, D2):
    """Midpoint of the shortest segment between two lines (vectorised, (N, 3))."""
    w = P1 - P2
    a = np.einsum("ij,ij->i", D1, D1)
    b = np.einsum("ij,ij->i", D1, D2)
    c = np.einsum("ij,ij->i", D2, D2)
    d = np.einsum("ij,ij->i", D1, w)
    e = np.einsum("ij,ij->i", D2, w)
    den = a * c - b * b
    with np.errstate(divide="ignore", invalid="ignore"):
        t = (b * e - c * d) / den
        s = (a * e - b * d) / den
    return 0.5 * ((P1 + t[:, None] * D1) + (P2 + s[:, None] * D2))


def _field_xy(h, axis):
    h = np.asarray(h, float)
    z = np.zeros_like(h)
    return (z, h) if axis == "y" else (h, z)


def _field_function(system, distortion: str = "ftan"):
    """Map normalised field -> the quantity image height is ideally proportional to."""
    if system.field_type == "ANGLE":
        tmax = math.radians(system.max_field)
        if distortion == "ftheta":
            return lambda h: np.asarray(h, float) * tmax
        return lambda h: np.tan(np.asarray(h, float) * tmax)
    return lambda h: np.asarray(h, float)


def field_curvature(system, wavelengths=None, n_fields: int = 21, axis: str = "y", distortion: str = "ftan"):
    """Tangential / sagittal focus position vs field and distortion vs field.

    Focus positions are the z distance from the image surface (at the chief
    ray) to the meeting point of two close rays straddling the chief ray in
    the tangential and sagittal planes.  Distortion is
    100 (y_real - y_ref) / y_ref, where the reference is the chief-ray height
    of a very small field scaled linearly in tan(angle) ("ftan", the usual
    definition) or angle ("ftheta"); height fields scale linearly.
    """
    wls = resolve_wavelengths(system, wavelengths)
    h = np.linspace(0, 1, n_fields)
    hx, hy = _field_xy(h, axis)
    g = _field_function(system, distortion)
    img = system.surfaces[system.image_index]
    e = _EPS_PUPIL
    T = np.full((len(wls), n_fields), np.nan)
    S = np.full_like(T, np.nan)
    D = np.full_like(T, np.nan)
    real = np.full_like(T, np.nan)
    ref = np.full_like(T, np.nan)
    tang = [(0, e), (0, -e)] if axis == "y" else [(e, 0), (-e, 0)]
    sag = [(e, 0), (-e, 0)] if axis == "y" else [(0, e), (0, -e)]
    for k, w in enumerate(wls):
        def tr(p):
            return trace_rays(system, hx, hy, p[0], p[1], wavelength=w, apertures=False)
        c = tr((0.0, 0.0))
        cx, cy = c.x, c.y
        zs = img.sag(cx, cy)
        for out, pair in ((T, tang), (S, sag)):
            r1, r2 = tr(pair[0]), tr(pair[1])
            Q = _closest_point(r1.image, r1.direction, r2.image, r2.direction)
            out[k] = Q[:, 2] - zs
        yr = (cy if axis == "y" else cx)
        small = trace_rays(system, *(_field_xy(_EPS_FIELD, axis)), 0.0, 0.0, wavelength=w, apertures=False)
        scale = (small.y[0] if axis == "y" else small.x[0]) / g(_EPS_FIELD)
        yref = scale * g(h)
        real[k], ref[k] = yr, yref
        with np.errstate(invalid="ignore", divide="ignore"):
            D[k] = np.where(h > 0, 100 * (yr - yref) / yref, 0.0)
    return {"field": h, "field_value": h * system.max_field, "wavelengths": wls, "tangential": T,
            "sagittal": S, "astigmatism": T - S, "distortion_percent": D, "real_height": real,
            "reference_height": ref, "axis": axis, "distortion_type": distortion}


def distortion(system, field=1.0, wavelength=None, distortion: str = "ftan", axis: str = "y") -> float:
    """Percent distortion at one normalised field (an optimisation operand)."""
    wl = system.primary if wavelength is None else wavelength
    g = _field_function(system, distortion)
    c = trace_rays(system, *(_field_xy(field, axis)), 0.0, 0.0, wavelength=wl, apertures=False)
    s = trace_rays(system, *(_field_xy(_EPS_FIELD, axis)), 0.0, 0.0, wavelength=wl, apertures=False)
    i = 1 if axis == "y" else 0
    ref = s.image[0, i] / g(_EPS_FIELD) * g(field)
    return float(100 * (c.image[0, i] - ref) / ref)


def grid_distortion(system, n: int = 11, wavelength=None, distortion: str = "ftan"):
    """Chief-ray grid distortion over the full rectangular field.

    The grid is uniform in the ideal-image space (tan(angle) for angle fields)
    and predicted positions scale each axis from very small fields.  Returns
    real and predicted (x, y) grids, per-point percent distortion and its
    maximum (``max_percent``) and location.
    """
    wl = system.primary if wavelength is None else wavelength
    g = _field_function(system, distortion)
    u = np.linspace(-1, 1, n)
    gmax = float(g(1.0))
    if system.field_type == "ANGLE":
        tmax = math.radians(system.max_field)
        inv = (lambda v: np.arctan(v * gmax) / tmax) if distortion == "ftan" else (lambda v: v)
    else:
        inv = lambda v: v  # noqa: E731
    U, V = np.meshgrid(u, u)
    HX, HY = inv(U), inv(V)
    r = trace_rays(system, HX.ravel(), HY.ravel(), 0.0, 0.0, wavelength=wl, apertures=False)
    sx = trace_rays(system, _EPS_FIELD, 0.0, 0.0, 0.0, wavelength=wl, apertures=False).x[0] / g(_EPS_FIELD)
    sy = trace_rays(system, 0.0, _EPS_FIELD, 0.0, 0.0, wavelength=wl, apertures=False).y[0] / g(_EPS_FIELD)
    PX, PY = sx * g(HX), sy * g(HY)
    RX, RY = r.x.reshape(U.shape), r.y.reshape(U.shape)
    rp = np.hypot(PX, PY)
    with np.errstate(invalid="ignore", divide="ignore"):
        pct = np.where(rp > 0, 100 * np.hypot(RX - PX, RY - PY) / rp, 0.0)
        radial = np.where(rp > 0, 100 * ((RX - PX) * PX + (RY - PY) * PY) / rp**2, 0.0)
    i = np.unravel_index(np.nanargmax(pct), pct.shape)
    return {"hx": HX, "hy": HY, "real_x": RX, "real_y": RY, "predicted_x": PX, "predicted_y": PY,
            "percent": pct, "radial_percent": radial, "max_percent": float(pct[i]),
            "max_at": (float(HX[i]), float(HY[i])), "wavelength": wl}


def lateral_color(system, wavelengths=None, n_fields: int = 21, axis: str = "y", reference: str = "primary"):
    """Chief-ray image height of each wavelength minus that of the primary
    (``reference="primary"``) vs field; ``extreme`` is shortest minus longest."""
    wls = resolve_wavelengths(system, wavelengths)
    h = np.linspace(0, 1, n_fields)
    hx, hy = _field_xy(h, axis)
    i = 1 if axis == "y" else 0
    y = np.array([trace_rays(system, hx, hy, 0.0, 0.0, wavelength=w, apertures=False).image[:, i] for w in wls])
    y0 = trace_rays(system, hx, hy, 0.0, 0.0, wavelength=system.primary, apertures=False).image[:, i]
    order = np.argsort(wls)
    return {"field": h, "wavelengths": wls, "difference": y - y0[None, :],
            "extreme": y[order[0]] - y[order[-1]], "axis": axis}


def longitudinal_aberration(system, wavelengths=None, n_pupil: int = 21):
    """On-axis focus position (z where a meridional ray crosses the axis,
    relative to the image surface) vs normalised pupil height, per wavelength."""
    wls = resolve_wavelengths(system, wavelengths)
    p = np.linspace(0, 1, n_pupil)
    pp = np.where(p == 0, _EPS_PUPIL, p)
    out = np.full((len(wls), n_pupil), np.nan)
    for k, w in enumerate(wls):
        r = trace_rays(system, 0.0, 0.0, 0.0, pp, wavelength=w)
        with np.errstate(invalid="ignore", divide="ignore"):
            out[k] = np.where(r.valid, r.z - r.y * r.direction[:, 2] / r.direction[:, 1], np.nan)
    return {"pupil": p, "wavelengths": wls, "focus": out}


def chromatic_focal_shift(system, n: int = 31, wl_min=None, wl_max=None):
    """Paraxial focus shift vs wavelength relative to the primary wavelength,
    plus the maximum shift and the diffraction-limited depth of focus
    (4 lambda F#^2, primary)."""
    wls = [w.value for w in system.wavelengths]
    lo = min(wls) if wl_min is None else wl_min
    hi = max(wls) if wl_max is None else wl_max
    lam = np.linspace(lo, hi, n)
    z0 = ParaxialAnalysis(system).image_distance
    dz = np.array([ParaxialAnalysis(system, l).image_distance - z0 for l in lam])
    par = ParaxialAnalysis(system)
    F = par.working_fnum
    return {"wavelength": lam, "shift": dz, "max_shift": float(dz.max() - dz.min()),
            "diffraction_limited_range": float(4 * system.primary * system.wavelength_scale * F * F)}


def pupil_aberration(system, field=1.0, wavelength=None, n: int = 21, axis: str = "y"):
    """Pupil aberration: percent difference between where paraxially aimed real
    rays cross the stop and where they were aimed (``p * stop radius``)."""
    wl = system.primary if wavelength is None else wavelength
    par = ParaxialAnalysis(system)
    p = np.linspace(-1, 1, n)
    hx, hy = _field_xy(field, axis)
    st = system.stop_index
    rs = par.stop_radius
    ty = trace_rays(system, hx, hy, 0.0, p, wavelength=wl, aiming="paraxial", apertures=False, last=st)
    tx = trace_rays(system, hx, hy, p, 0.0, wavelength=wl, aiming="paraxial", apertures=False, last=st)
    cy = trace_rays(system, hx, hy, 0.0, 0.0, wavelength=wl, aiming="paraxial", apertures=False, last=st)
    return {"pupil": p, "tangential_percent": 100 * (ty.y - cy.y[0] - p * rs) / rs,
            "sagittal_percent": 100 * (tx.x - cy.x[0] - p * rs) / rs, "chief_offset": (float(cy.x[0]), float(cy.y[0]))}
