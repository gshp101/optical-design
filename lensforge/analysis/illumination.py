"""Relative illumination and vignetting vs field."""

from __future__ import annotations

import math

import numpy as np

from ..raytrace import trace_rays
from .field import _field_xy


def _projected_solid_angle(system, hx, hy, wavelength, n):
    v = -1.0 + (np.arange(n) + 0.5) * 2.0 / n
    X, Y = np.meshgrid(v, v)
    r = trace_rays(system, hx, hy, X.ravel(), Y.ravel(), wavelength=wavelength, apertures=False)
    ra = trace_rays(system, hx, hy, X.ravel(), Y.ravel(), wavelength=wavelength)
    L = r.direction[:, 0].reshape(X.shape)
    M = r.direction[:, 1].reshape(X.shape)
    dp = 2.0 / n
    Lx, Ly = np.gradient(L, dp, axis=1), np.gradient(L, dp, axis=0)
    Mx, My = np.gradient(M, dp, axis=1), np.gradient(M, dp, axis=0)
    J = np.abs(Lx * My - Ly * Mx)
    ok = (ra.valid.reshape(X.shape)) & (X**2 + Y**2 <= 1) & np.isfinite(J)
    return float(np.sum(J[ok]) * dp * dp)


def relative_illumination(system, wavelength=None, n_fields: int = 21, axis: str = "y", sampling: int = 48):
    """Relative illumination vs field.

    Image irradiance from a Lambertian object is proportional to the
    projected solid angle of the exit pupil seen from the image point (by
    conservation of radiance), which is computed from the area the real
    rays cover in image-space direction-cosine space.  This includes cos^4
    fall-off, pupil distortion and vignetting.  Also returns the effective
    working F/# from the same solid angle.
    """
    wl = system.primary if wavelength is None else wavelength
    h = np.linspace(0, 1, n_fields)
    hx, hy = _field_xy(h, axis)
    om = np.array([_projected_solid_angle(system, a, b, wl, sampling) for a, b in zip(hx, hy)])
    n_img = system.media(wl)[0][system.image_index - 1]
    with np.errstate(divide="ignore", invalid="ignore"):
        fno = 1.0 / (2 * n_img * np.sqrt(om / math.pi))
    return {"field": h, "relative_illumination": om / om[0], "solid_angle": om,
            "effective_fnum": fno, "wavelength": wl}


def vignetting(system, wavelength=None, n_fields: int = 21, axis: str = "y", sampling: int = 48):
    """Fraction of a uniformly filled entrance pupil that reaches the image, vs field."""
    wl = system.primary if wavelength is None else wavelength
    h = np.linspace(0, 1, n_fields)
    v = -1.0 + (np.arange(sampling) + 0.5) * 2.0 / sampling
    X, Y = np.meshgrid(v, v)
    m = X**2 + Y**2 <= 1
    px, py = X[m], Y[m]
    frac = np.empty(n_fields)
    first_surface = []
    for i, f in enumerate(h):
        a, b = _field_xy(f, axis)
        r = trace_rays(system, a, b, px, py, wavelength=wl)
        frac[i] = r.valid.mean()
        bad = r.error_surface[~r.valid]
        first_surface.append(np.unique(bad).tolist())
    return {"field": h, "transmitted_fraction": frac, "vignetted_fraction": 1 - frac,
            "vignetting_surfaces": first_surface, "wavelength": wl}
