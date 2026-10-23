"""Ray fans, optical path difference and wavefront maps."""

from __future__ import annotations

import math
from typing import Optional

import numpy as np

from ..paraxial import ParaxialAnalysis
from ..raytrace import RayGenerator, trace, trace_rays
from .common import resolve_field, resolve_wavelengths


def ray_fan(system, field=0, wavelengths=None, n: int = 41):
    """Transverse ray aberration fans.

    Returns a dict with ``p`` (pupil coordinate samples) and, per wavelength,
    ``ey`` (tangential fan: y error vs py) and ``ex`` (sagittal fan: x error vs
    px), measured on the image surface relative to the primary-wavelength chief
    ray.  Rays that fail are NaN.
    """
    hx, hy = resolve_field(system, field)
    p = np.linspace(-1, 1, n)
    chief = trace_rays(system, hx, hy, 0.0, 0.0, wavelength=system.primary, apertures=False)
    cx, cy = chief.x[0], chief.y[0]
    out = {"p": p, "field": (hx, hy), "wavelengths": [], "ey": [], "ex": []}
    for w in resolve_wavelengths(system, wavelengths):
        t = trace_rays(system, hx, hy, 0.0, p, wavelength=w)
        s = trace_rays(system, hx, hy, p, 0.0, wavelength=w)
        out["wavelengths"].append(w)
        out["ey"].append(np.where(t.valid, t.y - cy, np.nan))
        out["ex"].append(np.where(s.valid, s.x - cx, np.nan))
    out["ey"] = np.array(out["ey"])
    out["ex"] = np.array(out["ex"])
    return out


class _Reference:
    """Exit-pupil reference sphere for one field point."""

    def __init__(self, system, hx, hy):
        self.system = system
        par = ParaxialAnalysis(system)
        last = system.image_index - 1
        z_xp = par.exit_pupil_position - system.surfaces[last].thickness  # image-surface frame
        chief = trace_rays(system, hx, hy, 0.0, 0.0, wavelength=system.primary, apertures=False)
        if not chief.valid[0]:
            raise RuntimeError("Chief ray failed; cannot build reference sphere")
        self.center = chief.image[0]
        D = chief.direction[0]
        if math.isfinite(z_xp) and abs(z_xp) < 1e12:
            s_c = (self.center[2] - z_xp) / D[2]
            E = self.center - s_c * D
            self.radius = float(np.linalg.norm(self.center - E))
            self.sign = 1.0 if s_c >= 0 else -1.0
        else:
            self.radius = math.inf
            self.sign = 1.0
            self.plane_normal = D

    def opl_to_sphere(self, result):
        """OPL of each ray from its start to the reference sphere."""
        n_img = self.system.media(result.wavelength)[0][self.system.image_index - 1]
        Q = result.image
        D = result.direction
        if math.isinf(self.radius):
            s = np.einsum("ij,j->i", Q - self.center, self.plane_normal)
            s = s / np.einsum("ij,j->i", D, self.plane_normal)
        else:
            W = Q - self.center
            b = np.einsum("ij,ij->i", W, D)
            disc = b * b - np.einsum("ij,ij->i", W, W) + self.radius**2
            s = b + self.sign * np.sqrt(np.maximum(disc, 0.0))
        return result.opl[-1] - n_img * s


def opd(system, hx, hy, px, py, wavelength=None, reference=None):
    """Optical path difference in waves at normalised pupil points.

    The reference sphere is centred on the primary-wavelength chief ray's image
    point and passes through the paraxial exit pupil; OPD is zero for the chief
    ray at each wavelength.  Sign convention: W = OPL(chief) - OPL(ray), so the
    transverse aberration is  ey = -(R / n') dW/dy  (W in lens units).
    """
    wavelength = system.primary if wavelength is None else wavelength
    ref = reference or _Reference(system, hx, hy)
    px, py = np.broadcast_arrays(np.atleast_1d(px).astype(float), np.atleast_1d(py).astype(float))
    gen = RayGenerator(system, wavelength)
    P, D, o = gen.rays(np.append(np.full(px.shape, hx), hx), np.append(np.full(px.shape, hy), hy),
                       np.append(px, 0.0), np.append(py, 0.0))
    res = trace(system, P, D, wavelength, o)
    L = ref.opl_to_sphere(res)
    w = (L[-1] - L[:-1]) / (wavelength * system.wavelength_scale)
    return np.where(res.valid[:-1], w, np.nan)


def opd_fan(system, field=0, wavelengths=None, n: int = 41):
    """OPD fans (waves): ``wy`` vs py (tangential) and ``wx`` vs px (sagittal)."""
    hx, hy = resolve_field(system, field)
    ref = _Reference(system, hx, hy)
    p = np.linspace(-1, 1, n)
    out = {"p": p, "field": (hx, hy), "wavelengths": [], "wy": [], "wx": []}
    for w in resolve_wavelengths(system, wavelengths):
        out["wavelengths"].append(w)
        out["wy"].append(opd(system, hx, hy, 0.0, p, w, ref))
        out["wx"].append(opd(system, hx, hy, p, 0.0, w, ref))
    out["wy"], out["wx"] = np.array(out["wy"]), np.array(out["wx"])
    return out


def wavefront(system, field=0, wavelength=None, n: int = 64, remove_tilt: bool = False):
    """Wavefront (OPD) map in waves on an n x n pupil grid (NaN outside the pupil).

    Returns dict with ``px``, ``py`` (1-D axes), ``W`` (n x n), ``rms`` and ``pv``
    (piston removed; tilt removed too if ``remove_tilt``).
    """
    hx, hy = resolve_field(system, field)
    v = np.linspace(-1, 1, n)
    X, Y = np.meshgrid(v, v)
    m = X**2 + Y**2 <= 1.0
    W = np.full(X.shape, np.nan)
    W[m] = opd(system, hx, hy, X[m], Y[m], wavelength)
    ok = np.isfinite(W)
    if remove_tilt:
        A = np.column_stack([np.ones(ok.sum()), X[ok], Y[ok]])
        c, *_ = np.linalg.lstsq(A, W[ok], rcond=None)
        W[ok] -= A @ c
    else:
        W[ok] -= W[ok].mean()
    return {"px": v, "py": v, "W": W, "rms": float(np.sqrt(np.mean(W[ok] ** 2))) if ok.any() else math.nan,
            "pv": float(W[ok].max() - W[ok].min()) if ok.any() else math.nan}
