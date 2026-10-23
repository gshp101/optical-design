"""Modulation transfer function: FFT, Huygens and geometric MTF, through-focus
MTF and MTF vs field.

Frequencies are in cycles per lens unit (cycles/mm for mm lenses).  For a
field point on the y axis the *tangential* MTF is the response to
frequencies along y and the *sagittal* MTF along x, as in Zemax.  Every
result also carries the aberration-free (diffraction-limited) curve for the
same pupil, wavelengths and weights.
"""

from __future__ import annotations

import math

import numpy as np

from ..pupil import pupil_grid
from ..raytrace import trace_rays
from .common import defocused, resolve_field, resolve_wavelengths, resolve_weights
from .pupilfn import pupil_function
from .psf import fft_psf, huygens_psf


def diffraction_limited_mtf(freq, na, wavelengths, weights=None, units_scale: float = 1e-3):
    """Analytic MTF of an aberration-free circular pupil.

    ``na`` is the image-space NA, ``wavelengths`` in um and ``units_scale``
    converts um to lens units (1e-3 for mm).  Polychromatic curves are the
    weighted average of the monochromatic ones.
    """
    freq = np.abs(np.asarray(freq, float))
    wavelengths = np.atleast_1d(wavelengths)
    weights = np.ones(wavelengths.size) if weights is None else np.asarray(weights, float)
    out = np.zeros_like(freq)
    for lam, w in zip(wavelengths, weights):
        s = np.clip(freq / (2 * na / (lam * units_scale)), 0, 1)
        out += w * 2 / math.pi * (np.arccos(s) - s * np.sqrt(1 - s * s))
    return out / weights.sum()


def otf_from_psf(psf: dict):
    """2-D OTF (complex, normalised to 1 at zero frequency) of a PSF result,
    with its frequency axis.  Returns (freq, otf, otf_perfect), arrays in FFT order."""
    P = np.fft.ifftshift(psf["psf"])
    O = np.fft.fft2(P)
    Q = np.fft.fft2(np.fft.ifftshift(psf["perfect"]))
    f = np.fft.fftfreq(P.shape[0], psf["dx"])
    return f, O / O[0, 0], Q / Q[0, 0]


def mtf_from_psf(psf: dict, frequencies=None, max_freq=None):
    """Tangential / sagittal MTF slices of a PSF result.

    Without ``frequencies`` the native grid (0 .. cutoff) is returned;
    otherwise values are interpolated.  Phase (PTF, radians) is included.
    """
    f, O, Q = otf_from_psf(psf)
    n = f.size
    pos = f[: n // 2 + 1] if n % 2 == 0 else f[: (n + 1) // 2]
    pos = np.abs(pos)
    lam_min = min(psf["wavelengths"]) * psf["wavelength_scale"]
    cutoff = 2 * max(abs(psf["na"][0]), abs(psf["na"][1])) / lam_min
    t = O[: pos.size, 0]
    s = O[0, : pos.size]
    tq, sq = Q[: pos.size, 0], Q[0, : pos.size]
    if frequencies is None:
        m = pos <= (cutoff if max_freq is None else min(cutoff, max_freq)) * (1 + 1e-9)
        fr = pos[m]
        T, S, TQ, SQ = t[m], s[m], tq[m], sq[m]
    else:
        fr = np.asarray(frequencies, float)

        def it(v):
            return np.interp(fr, pos, v.real) + 1j * np.interp(fr, pos, v.imag)
        T, S, TQ, SQ = it(t), it(s), it(tq), it(sq)
    return {"freq": fr, "tangential": np.abs(T), "sagittal": np.abs(S),
            "tangential_phase": np.angle(T), "sagittal_phase": np.angle(S),
            "diffraction_limit_tangential": np.abs(TQ), "diffraction_limit_sagittal": np.abs(SQ),
            "field": psf["field"], "wavelengths": psf["wavelengths"], "cutoff": cutoff, "method": psf["method"]}


def fft_mtf(system, field=0, wavelengths=None, pupil_n: int = 64, frequencies=None, max_freq=None,
            image_n=None):
    """FFT MTF of one field point (``pupil_n`` sets accuracy; ``image_n`` x 2
    pupil_n zero-padding sets the frequency step = cutoff / (image_n / 2))."""
    psf = fft_psf(system, field, wavelengths, pupil_n=pupil_n, image_n=image_n)
    return mtf_from_psf(psf, frequencies, max_freq)


def huygens_mtf(system, field=0, wavelengths=None, pupil_n: int = 48, image_n: int = 64, frequencies=None,
                max_freq=None):
    psf = huygens_psf(system, field, wavelengths, pupil_n=pupil_n, image_n=image_n)
    return mtf_from_psf(psf, frequencies, max_freq)


def geometric_mtf(system, field=0, wavelengths=None, frequencies=None, max_freq=None, n_freq: int = 41,
                  grid: int = 48, scale_by_diffraction: bool = True):
    """Geometric MTF: Fourier transform of the ray-intercept density.

    With ``scale_by_diffraction`` the result is multiplied by the
    diffraction-limited MTF, which makes it a good approximation of the
    diffraction MTF for systems with more than a few waves of aberration.
    """
    hx, hy = resolve_field(system, field)
    wls = resolve_wavelengths(system, wavelengths)
    wts = resolve_weights(system, wls)
    px, py = pupil_grid("square", grid)
    xs, ys, ws = [], [], []
    for w, wt in zip(wls, wts):
        r = trace_rays(system, hx, hy, px, py, wavelength=w)
        xs.append(r.x[r.valid])
        ys.append(r.y[r.valid])
        ws.append(np.full(r.valid.sum(), wt / max(px.size, 1)))
    X, Y, Wt = np.concatenate(xs), np.concatenate(ys), np.concatenate(ws)
    pf = pupil_function(system, (hx, hy), system.primary, 16)
    na = max(abs(pf.na_x), abs(pf.na_y))
    lam_min = min(wls) * system.wavelength_scale
    cutoff = 2 * na / lam_min
    if frequencies is None:
        fr = np.linspace(0, cutoff if max_freq is None else max_freq, n_freq)
    else:
        fr = np.asarray(frequencies, float)
    Wn = Wt / Wt.sum()
    cx, cy = np.sum(Wn * X), np.sum(Wn * Y)
    T = np.abs(np.exp(-2j * math.pi * np.outer(fr, Y - cy)) @ Wn)
    S = np.abs(np.exp(-2j * math.pi * np.outer(fr, X - cx)) @ Wn)
    dl = diffraction_limited_mtf(fr, na, wls, wts, system.wavelength_scale)
    if scale_by_diffraction:
        T, S = T * dl, S * dl
    return {"freq": fr, "tangential": T, "sagittal": S, "diffraction_limit_tangential": dl,
            "diffraction_limit_sagittal": dl, "field": (hx, hy), "wavelengths": wls, "cutoff": cutoff,
            "method": "geometric"}


_METHODS = {"fft": fft_mtf, "huygens": huygens_mtf, "geometric": geometric_mtf}


def mtf(system, field=0, wavelengths=None, method: str = "fft", **kw):
    """Dispatch to :func:`fft_mtf`, :func:`huygens_mtf` or :func:`geometric_mtf`."""
    return _METHODS[method](system, field, wavelengths, **kw)


def mtf_at(system, frequency: float, field=0, wavelengths=None, method: str = "fft", **kw):
    """(tangential, sagittal) MTF at one frequency: a convenient merit-function operand."""
    r = mtf(system, field, wavelengths, method, frequencies=[frequency], **kw)
    return float(r["tangential"][0]), float(r["sagittal"][0])


def through_focus_mtf(system, frequency: float, field=0, wavelengths=None, focus_range=None, steps: int = 21,
                      method: str = "fft", **kw):
    """MTF at one frequency vs image-plane shift (lens units).

    ``focus_range`` is the total range centred on the current image plane;
    the default is +/- 4 lambda F#^2 (several depths of focus).
    """
    if focus_range is None:
        pf = pupil_function(system, field, system.primary, 16)
        na = max(abs(pf.na_x), abs(pf.na_y))
        focus_range = 8 * pf.wavelength_lens_units / (4 * na * na)
    dz = np.linspace(-focus_range / 2, focus_range / 2, steps)
    T, S = np.empty(steps), np.empty(steps)
    for i, d in enumerate(dz):
        T[i], S[i] = mtf_at(defocused(system, d), frequency, field, wavelengths, method, **kw)
    return {"focus": dz, "tangential": T, "sagittal": S, "frequency": frequency, "method": method}


def mtf_vs_field(system, frequencies, wavelengths=None, n_fields: int = 11, method: str = "fft", axis="y", **kw):
    """MTF at the given frequencies vs normalised field along ``axis`` ("y" or "x")."""
    frequencies = np.atleast_1d(np.asarray(frequencies, float))
    h = np.linspace(0, 1, n_fields)
    T = np.empty((n_fields, frequencies.size))
    S = np.empty_like(T)
    for i, v in enumerate(h):
        f = (0.0, v) if axis == "y" else (v, 0.0)
        r = mtf(system, f, wavelengths, method, frequencies=frequencies, **kw)
        T[i], S[i] = r["tangential"], r["sagittal"]
    return {"field": h, "frequencies": frequencies, "tangential": T, "sagittal": S, "method": method}
