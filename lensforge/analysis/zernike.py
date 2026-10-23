"""Zernike polynomials and wavefront decomposition.

Two orderings, as in Zemax:

* ``"fringe"`` (University of Arizona / Fringe, unnormalised, 37 terms
  conventionally; any count is allowed): Z1 piston, Z2 x-tilt, Z3 y-tilt,
  Z4 defocus, Z5/Z6 astigmatism, Z7/Z8 coma, Z9 spherical, ...
* ``"standard"`` (Noll ordering, orthonormal over the unit disk, so the RMS of
  a wavefront is the root-sum-square of its coefficients).

theta is measured from the +x axis towards +y (cos terms are x-like).
"""

from __future__ import annotations

import math
from functools import lru_cache

import numpy as np

from .pupilfn import pupil_function


@lru_cache(maxsize=None)
def noll_to_nm(j: int):
    """Noll index (1-based) -> (n, m) with m signed (m < 0 = sine term)."""
    if j < 1:
        raise ValueError("Zernike indices start at 1")
    n = 0
    while (n + 1) * (n + 2) // 2 < j:
        n += 1
    k = j - n * (n + 1) // 2 - 1  # 0-based position within radial order n
    ms = [m for m in range(n % 2, n + 1, 2)]
    # within an order, |m| increases; for m != 0 two terms: even j = cos, odd j = sin
    order = []
    for m in ms:
        order.extend([m] if m == 0 else [m, m])
    m = order[k]
    if m != 0:
        m = m if j % 2 == 0 else -m
    return n, m


@lru_cache(maxsize=None)
def _fringe_sequence(count: int):
    seq, g = [], 0
    while len(seq) < count + 2:
        for m in range(g, -1, -1):
            for sgn in ((1, -1) if m else (1,)):
                seq.append((2 * g - m, sgn * m))
        g += 1
    # the conventional 37-term Fringe set ends with 12th-order spherical
    seq.remove((12, 0))
    seq.insert(36, (12, 0))
    return tuple(seq)


def fringe_to_nm(j: int):
    """Fringe index (1-based) -> (n, m) with m signed (m < 0 = sine term)."""
    if j < 1:
        raise ValueError("Zernike indices start at 1")
    return _fringe_sequence(max(64, 2 * j))[j - 1]


def radial(n: int, m: int, rho):
    m = abs(m)
    R = np.zeros_like(rho, dtype=float)
    for k in range((n - m) // 2 + 1):
        c = (-1) ** k * math.factorial(n - k) / (
            math.factorial(k) * math.factorial((n + m) // 2 - k) * math.factorial((n - m) // 2 - k))
        R = R + c * rho ** (n - 2 * k)
    return R


def zernike(j: int, rho, theta, kind: str = "fringe"):
    """Evaluate term ``j`` at polar pupil coordinates."""
    n, m = (noll_to_nm if kind == "standard" else fringe_to_nm)(j)
    rho = np.asarray(rho, float)
    theta = np.asarray(theta, float)
    R = radial(n, m, rho)
    ang = np.cos(m * theta) if m >= 0 else np.sin(-m * theta)
    norm = 1.0
    if kind == "standard":
        norm = math.sqrt(n + 1) if m == 0 else math.sqrt(2 * (n + 1))
    return norm * R * ang


def zernike_xy(j: int, x, y, kind: str = "fringe"):
    x, y = np.asarray(x, float), np.asarray(y, float)
    return zernike(j, np.hypot(x, y), np.arctan2(y, x), kind)


def zernike_name(j: int, kind: str = "fringe") -> str:
    n, m = (noll_to_nm if kind == "standard" else fringe_to_nm)(j)
    names = {(0, 0): "piston", (1, 1): "tilt x", (1, -1): "tilt y", (2, 0): "defocus",
             (2, 2): "astigmatism 0/90", (2, -2): "astigmatism 45", (3, 1): "coma x", (3, -1): "coma y",
             (4, 0): "primary spherical", (3, 3): "trefoil x", (3, -3): "trefoil y",
             (6, 0): "secondary spherical", (8, 0): "tertiary spherical"}
    return names.get((n, m), f"Z(n={n}, m={m})")


def fit_zernike(x, y, w, n_terms: int = 37, kind: str = "fringe"):
    """Least-squares Zernike fit of samples ``w`` at unit-disk points (x, y).

    Returns dict: ``coefficients`` (index 0 = term 1), ``residual_rms``,
    ``fit`` (fitted values) and ``kind``."""
    x, y, w = (np.asarray(a, float).ravel() for a in (x, y, w))
    ok = np.isfinite(w)
    x, y, w = x[ok], y[ok], w[ok]
    A = np.column_stack([zernike_xy(j, x, y, kind) for j in range(1, n_terms + 1)])
    c, *_ = np.linalg.lstsq(A, w, rcond=None)
    fit = A @ c
    res = w - fit
    return {"coefficients": c, "residual_rms": float(np.sqrt(np.mean(res**2))),
            "residual_pv": float(res.max() - res.min()) if res.size else math.nan,
            "fit": fit, "kind": kind, "n_terms": n_terms}


def evaluate_zernike(coefficients, x, y, kind: str = "fringe"):
    out = np.zeros(np.broadcast(np.asarray(x), np.asarray(y)).shape)
    for j, c in enumerate(coefficients, start=1):
        if c:
            out = out + c * zernike_xy(j, x, y, kind)
    return out


def zernike_coefficients(system, field=0, wavelength=None, n_terms: int = 37, kind: str = "fringe",
                         sampling: int = 64):
    """Zernike decomposition of the wavefront (waves) of one field point, like
    Zemax's "Zernike Fringe/Standard Coefficients" report.

    Returns the fit plus ``pv``/``rms`` of the wavefront (to chief ray = with
    piston removed, and to centroid = with tilt also removed), the Marechal
    Strehl estimate and term names.
    """
    pf = pupil_function(system, field, wavelength, sampling)
    X, Y = np.meshgrid(pf.px, pf.px)
    m = pf.mask
    W = pf.opd[m]
    r = fit_zernike(X[m], Y[m], W, n_terms, kind)
    w0 = W - W.mean()
    # tilt removed: subtract best-fit plane
    A = np.column_stack([np.ones(W.size), X[m], Y[m]])
    ct, *_ = np.linalg.lstsq(A, W, rcond=None)
    wt = W - A @ ct
    r.update({
        "field": pf.field, "wavelength": pf.wavelength,
        "names": [zernike_name(j, kind) for j in range(1, n_terms + 1)],
        "pv": float(w0.max() - w0.min()), "rms_to_chief": float(np.sqrt(np.mean(w0**2))),
        "rms_to_centroid": float(np.sqrt(np.mean(wt**2))),
        "pv_to_centroid": float(wt.max() - wt.min()),
        "strehl_marechal": float(math.exp(-(2 * math.pi * np.sqrt(np.mean(wt**2))) ** 2)),
    })
    return r
