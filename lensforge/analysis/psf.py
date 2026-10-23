"""Diffraction point spread functions (FFT and Huygens) and Strehl ratio.

Both methods return a dict with

``x``, ``y``      1-D image axes (lens units) relative to ``center``,
``psf``           (ny, nx) array, fraction of the total energy per pixel
                  (so the sum is ~1 when the grid holds the whole PSF),
``dx``            pixel spacing (lens units),
``center``        image-surface (x, y) of the grid centre (primary chief ray),
``strehl``        peak / peak of the aberration-free PSF with the same
                  (possibly vignetted) pupil and wavelengths,
``peak``          maximum of ``psf``; ``wavelengths``/``weights`` used;
``na``            (na_x, na_y) image-space NA at the primary wavelength.

"FFT" evaluates the Fraunhofer integral of the exit-pupil function with a
separable matrix Fourier transform, so all wavelengths land on one common
grid (equivalent to a zero-padded FFT, but without resampling).  "Huygens"
sums spherical wavelets from every ray's point on the exit-pupil reference
sphere to every image point on the actual image surface; it is slower but
exact for tilted image surfaces and strongly anamorphic pupils.
"""

from __future__ import annotations

import math

import numpy as np

from ..raytrace import RayGenerator, trace
from .common import resolve_field, resolve_wavelengths, resolve_weights
from .fans import _Reference
from .pupilfn import pupil_function


def _grid(n_img, dx):
    return (np.arange(n_img) - n_img // 2) * dx


def _default_spacing(pfs):
    lam = min(p.wavelength_lens_units for p in pfs)
    na = max(max(abs(p.na_x), abs(p.na_y)) for p in pfs)
    return lam / (4.0 * na)  # Nyquist for the incoherent PSF at the shortest wavelength


def _mft(pf, xs, ys, field):
    """|U|^2 normalised to fraction of energy per unit area, on the grid xs, ys."""
    lam = pf.wavelength_lens_units
    p = pf.px
    dp = 2.0 / pf.n
    Ex = np.exp(-2j * math.pi * np.outer(xs, p) * pf.na_x / lam)
    Ey = np.exp(-2j * math.pi * np.outer(ys, p) * pf.na_y / lam)
    dO = abs(pf.na_x * pf.na_y) * dp * dp
    U = Ey @ field @ Ex.T * dO
    E = lam**2 * np.sum(np.abs(field) ** 2) * dO
    return np.abs(U) ** 2 / E


def fft_psf(system, field=0, wavelengths=None, pupil_n: int = 64, image_n=None, dx=None,
            pupil_functions=None):
    """FFT (Fraunhofer) PSF.  ``image_n`` defaults to ``2 * pupil_n`` and ``dx`` to
    Nyquist sampling at the shortest wavelength, giving an image width of
    about ``pupil_n * lambda * F#`` as in FFT-based codes."""
    wls = resolve_wavelengths(system, wavelengths)
    wts = resolve_weights(system, wls)
    hx, hy = resolve_field(system, field)
    ref = _Reference(system, hx, hy)
    if pupil_functions is None:
        pupil_functions = [pupil_function(system, (hx, hy), w, pupil_n, ref) for w in wls]
    pfs = pupil_functions
    image_n = 2 * pfs[0].n if image_n is None else int(image_n)
    dx = _default_spacing(pfs) if dx is None else float(dx)
    # the sampled pupil makes the image periodic: keep the grid within one period
    need = max(math.ceil(2 * max(abs(p.na_x), abs(p.na_y)) * image_n * dx / p.wavelength_lens_units)
               for p in pfs)
    if need > pfs[0].n:
        pfs = [pupil_function(system, (hx, hy), p.wavelength, need, ref) for p in pfs]
    xs = _grid(image_n, dx)
    psf = np.zeros((image_n, image_n))
    perfect = np.zeros_like(psf)
    for pf, w in zip(pfs, wts):
        if not pf.mask.any():
            continue
        psf += w * _mft(pf, xs, xs, pf.complex) * dx * dx
        perfect += w * _mft(pf, xs, xs, pf.amplitude.astype(complex)) * dx * dx
    tw = sum(wts)
    psf /= tw
    perfect /= tw
    prim = pfs[min(range(len(wls)), key=lambda i: abs(wls[i] - system.primary))]
    warnings = []
    if psf.sum() < 0.95 * perfect.sum():
        warnings.append(f"only {psf.sum():.1%} of the energy falls on the PSF grid; increase pupil_n")
    return {"method": "fft", "warnings": warnings, "x": xs, "y": xs, "psf": psf, "dx": dx, "center": tuple(prim.chief[:2]),
            "strehl": float(psf.max() / perfect.max()) if perfect.max() > 0 else math.nan,
            "peak": float(psf.max()), "perfect": perfect, "wavelengths": wls, "weights": wts,
            "na": (prim.na_x, prim.na_y), "field": (hx, hy), "pupil_functions": pfs,
            "wavelength_scale": system.wavelength_scale}


def huygens_psf(system, field=0, wavelengths=None, pupil_n: int = 48, image_n: int = 64, dx=None,
                center=None):
    """Huygens PSF on the image surface itself.

    ``center`` (x, y) on the image surface defaults to the primary chief ray.
    """
    wls = resolve_wavelengths(system, wavelengths)
    wts = resolve_weights(system, wls)
    hx, hy = resolve_field(system, field)
    ref = _Reference(system, hx, hy)
    pfs = [pupil_function(system, (hx, hy), w, pupil_n, ref) for w in wls]
    dx = _default_spacing(pfs) if dx is None else float(dx)
    xs = _grid(image_n, dx)
    cx, cy = (ref.center[0], ref.center[1]) if center is None else center
    X, Y = np.meshgrid(xs + cx, xs + cy)
    G = np.stack([X.ravel(), Y.ravel(), np.full(X.size, ref.center[2])], axis=1)
    v = pfs[0].px
    PX, PY = np.meshgrid(v, v)
    inside = PX**2 + PY**2 <= 1
    psf = np.zeros(X.size)
    perfect = np.zeros(X.size)
    for pf, w in zip(pfs, wts):
        gen = RayGenerator(system, pf.wavelength)
        px, py = PX[inside], PY[inside]
        P, D, o = gen.rays(np.full(px.size, hx), np.full(px.size, hy), px, py)
        res = trace(system, P, D, pf.wavelength, o)
        ok = res.valid
        if not ok.any():
            continue
        n_img = system.media(pf.wavelength)[0][system.image_index - 1]
        L = ref.opl_to_sphere(res)[ok]
        Dk = res.direction[ok]
        # point on the reference sphere: back along the ray from the image surface
        S = res.image[ok] - ((res.opl[-1][ok] - L) / n_img)[:, None] * Dk
        lam = pf.wavelength_lens_units
        k0 = 2 * math.pi / lam
        r0 = np.linalg.norm(ref.center - S, axis=1)
        L = L - L.mean()
        dO = abs(pf.na_x * pf.na_y) * (2.0 / pf.n) ** 2
        U = np.zeros(X.size, complex)
        U0 = np.zeros(X.size, complex)
        for a in range(0, X.size, 512):
            g = G[a:a + 512]
            d = np.linalg.norm(g[:, None, :] - S[None, :, :], axis=2)
            obl = np.einsum("gkj,kj->gk", g[:, None, :] - S[None, :, :], Dk) / d
            U[a:a + 512] = (obl * np.exp(1j * k0 * (L[None, :] + n_img * (d - r0[None, :])))).sum(1)
            U0[a:a + 512] = (obl * np.exp(1j * k0 * n_img * (d - r0[None, :]))).sum(1)
        E = lam**2 * ok.sum() * dO
        psf += w * np.abs(U * dO) ** 2 / E * dx * dx
        perfect += w * np.abs(U0 * dO) ** 2 / E * dx * dx
    tw = sum(wts)
    psf = psf.reshape(X.shape) / tw
    perfect = perfect.reshape(X.shape) / tw
    prim = pfs[min(range(len(wls)), key=lambda i: abs(wls[i] - system.primary))]
    return {"method": "huygens", "x": xs, "y": xs, "psf": psf, "dx": dx, "center": (float(cx), float(cy)),
            "strehl": float(psf.max() / perfect.max()) if perfect.max() > 0 else math.nan,
            "peak": float(psf.max()), "perfect": perfect, "wavelengths": wls, "weights": wts,
            "na": (prim.na_x, prim.na_y), "field": (hx, hy),
            "wavelength_scale": system.wavelength_scale}


def psf_cross_section(psf: dict, axis: str = "y"):
    """Central row/column of a PSF result, normalised to the peak of the
    aberration-free PSF (so the peak value is the Strehl ratio)."""
    P, ref = psf["psf"], psf["perfect"].max()
    c = P.shape[0] // 2
    prof = P[:, c] if axis == "y" else P[c, :]
    return psf["x"], prof / ref


def strehl(system, field=0, wavelengths=None, method: str = "fft", **kw) -> float:
    """Strehl ratio from the diffraction PSF ("fft" or "huygens"), or the
    extended Marechal approximation exp(-(2 pi sigma)^2) with method="marechal"."""
    if method == "marechal":
        wls = resolve_wavelengths(system, wavelengths)
        wts = resolve_weights(system, wls)
        hx, hy = resolve_field(system, field)
        ref = _Reference(system, hx, hy)
        s = [math.exp(-(2 * math.pi * pupil_function(system, (hx, hy), w, kw.get("pupil_n", 64), ref).rms) ** 2)
             for w in wls]
        return float(np.average(s, weights=wts))
    fn = fft_psf if method == "fft" else huygens_psf
    return fn(system, field, wavelengths, **kw)["strehl"]


def image_simulation(image, psf: dict, pixel_size: float):
    """Convolve a 2-D object image (array, object pixels mapped to image
    space with ``pixel_size`` lens units) with a PSF result, assuming the PSF
    is constant over the image (isoplanatic).  Returns the blurred image with
    the same shape (the kernel has unit sum; light blurred past the edges is lost)."""
    img = np.asarray(image, float)
    P = psf["psf"]
    # resample the PSF onto the image pixel pitch
    xs = psf["x"]
    n = int(np.ceil((xs[-1] - xs[0]) / pixel_size)) | 1
    g = (np.arange(n) - n // 2) * pixel_size
    from numpy import interp
    rows = np.array([interp(g, xs, P[i]) for i in range(P.shape[0])])
    K = np.array([interp(g, xs, rows[:, j]) for j in range(n)]).T
    K = np.clip(K, 0, None)
    K /= K.sum() if K.sum() > 0 else 1.0
    sh = (img.shape[0] + n - 1, img.shape[1] + n - 1)
    out = np.fft.irfft2(np.fft.rfft2(img, sh) * np.fft.rfft2(K, sh), sh)
    a = n // 2
    return out[a:a + img.shape[0], a:a + img.shape[1]]
