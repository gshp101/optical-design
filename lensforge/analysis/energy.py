"""Encircled, ensquared and enslitted (line) energy, diffraction and geometric.

Diffraction energies integrate the band-limited PSF exactly through its OTF:

    E(r)  = sum_nu OTF(nu) e^{2 pi i nu.c} r J1(2 pi r |nu|) / |nu|  dnu^2      (circle)
    E(a)  = sum_nu OTF(nu) e^{2 pi i nu.c} (2a)^2 sinc(2a nu_x) sinc(2a nu_y) dnu^2   (square, half width a)

so the result is free of pixelation error.  ``center`` "centroid" (default),
"chief" (primary chief ray) or an (x, y) point on the image surface.
Results are fractions of the total energy reaching the image.
"""

from __future__ import annotations

import math

import numpy as np

from ..pupil import pupil_grid
from ..raytrace import trace_rays
from .common import bessel_j1, resolve_field, resolve_wavelengths, resolve_weights
from .psf import fft_psf, huygens_psf

KINDS = ("encircled", "ensquared", "x", "y")


def _psf_centroid(psf):
    P = psf["psf"]
    X, Y = np.meshgrid(psf["x"], psf["y"])
    t = P.sum()
    return float((P * X).sum() / t), float((P * Y).sum() / t)


def energy_from_psf(psf: dict, radii, kind: str = "encircled", center="centroid", perfect: bool = False):
    """Energy fractions for a PSF result.  ``radii`` are radius / half-widths in lens units."""
    P = psf["perfect"] if perfect else psf["psf"]
    n = P.shape[0]
    dx = psf["dx"]
    O = np.fft.fft2(np.fft.ifftshift(P))  # O[0,0] = energy on grid (fraction of total)
    f = np.fft.fftfreq(n, dx)
    FX, FY = np.meshgrid(f, f)
    if center == "centroid":
        c = _psf_centroid({"psf": P, "x": psf["x"], "y": psf["y"]})
    elif center == "chief":
        c = (0.0, 0.0)
    else:
        c = (center[0] - psf["center"][0], center[1] - psf["center"][1])
    # O (transform of the per-pixel energies) equals the continuous OTF of the
    # band-limited PSF sampled at the DFT frequencies
    O = O * np.exp(2j * math.pi * (FX * c[0] + FY * c[1]))
    df = 1.0 / (n * dx)
    radii = np.atleast_1d(np.asarray(radii, float))
    out = np.empty(radii.size)
    rho = np.hypot(FX, FY)
    half = 0.5 * n * dx  # beyond this the periodic PSF would be counted twice
    for i, r in enumerate(radii):
        r = min(r, half)
        if kind == "encircled":
            with np.errstate(invalid="ignore", divide="ignore"):
                K = np.where(rho > 0, r * bessel_j1(2 * math.pi * r * rho) / np.where(rho > 0, rho, 1), math.pi * r * r)
        elif kind == "ensquared":
            K = (2 * r) ** 2 * np.sinc(2 * r * FX) * np.sinc(2 * r * FY)
        elif kind == "x":
            K = np.where(FY == 0, 2 * r * np.sinc(2 * r * FX) / df, 0.0)
        elif kind == "y":
            K = np.where(FX == 0, 2 * r * np.sinc(2 * r * FY) / df, 0.0)
        else:
            raise ValueError(f"kind must be one of {KINDS}")
        out[i] = float(np.real(np.sum(O * K)) * df * df)
    return out


def diffraction_energy(system, field=0, wavelengths=None, radii=None, kind: str = "encircled",
                       center="centroid", method: str = "fft", n_radii: int = 50, **kw):
    """Diffraction encircled/ensquared/line energy vs radius, plus the
    aberration-free curve.  Default radii span 0 .. 5 lambda F#."""
    psf = (fft_psf if method == "fft" else huygens_psf)(system, field, wavelengths, **kw)
    if radii is None:
        from .spot import spot_diagram
        lam = min(psf["wavelengths"]) * system.wavelength_scale
        na = max(abs(psf["na"][0]), abs(psf["na"][1]))
        geo = spot_diagram(system, field, wavelengths, rings=8)["rms_radius"]
        rmax = min(max(5 * lam / (2 * na), 3 * geo), 0.5 * psf["x"].size * psf["dx"])
        radii = np.linspace(0, rmax, n_radii)
    radii = np.asarray(radii, float)
    return {"radius": radii, "energy": energy_from_psf(psf, radii, kind, center),
            "diffraction_limit": energy_from_psf(psf, radii, kind, "chief", perfect=True),
            "kind": kind, "field": psf["field"], "method": method}


def geometric_energy(system, field=0, wavelengths=None, radii=None, kind: str = "encircled",
                     center="centroid", grid: int = 64, n_radii: int = 50):
    """Geometric (ray-count) encircled/ensquared/line energy (fraction of
    rays launched into the unit pupil, so vignetting lowers the curve)."""
    hx, hy = resolve_field(system, field)
    wls = resolve_wavelengths(system, wavelengths)
    wts = resolve_weights(system, wls)
    px, py = pupil_grid("square", grid)
    xs, ys, ws, total = [], [], [], 0.0
    for w, wt in zip(wls, wts):
        r = trace_rays(system, hx, hy, px, py, wavelength=w)
        xs.append(r.x[r.valid])
        ys.append(r.y[r.valid])
        ws.append(np.full(r.valid.sum(), wt))
        total += wt * px.size
    X, Y, Wt = np.concatenate(xs), np.concatenate(ys), np.concatenate(ws)
    if center == "centroid":
        c = (np.average(X, weights=Wt), np.average(Y, weights=Wt))
    elif center == "chief":
        cr = trace_rays(system, hx, hy, 0, 0, apertures=False)
        c = (cr.x[0], cr.y[0])
    else:
        c = center
    dx, dy = X - c[0], Y - c[1]
    d = {"encircled": np.hypot(dx, dy), "ensquared": np.maximum(abs(dx), abs(dy)),
         "x": abs(dx), "y": abs(dy)}[kind]
    if radii is None:
        radii = np.linspace(0, d.max() * 1.05 if d.size else 1.0, n_radii)
    radii = np.asarray(radii, float)
    order = np.argsort(d)
    cum = np.concatenate([[0.0], np.cumsum(Wt[order])]) / total
    idx = np.searchsorted(d[order], radii, side="right")
    return {"radius": radii, "energy": cum[idx], "kind": kind, "field": (hx, hy), "method": "geometric"}


def radius_for_energy(curve: dict, fraction: float = 0.8):
    """Radius at which an energy curve reaches ``fraction`` (linear interpolation)."""
    e, r = curve["energy"], curve["radius"]
    if e.max() < fraction:
        return math.nan
    i = int(np.argmax(e >= fraction))
    if i == 0:
        return float(r[0])
    return float(r[i - 1] + (fraction - e[i - 1]) * (r[i] - r[i - 1]) / (e[i] - e[i - 1]))
