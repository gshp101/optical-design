"""Complex pupil functions: the common input of all diffraction analyses.

A pupil function samples the normalised entrance pupil on an ``n x n`` grid and
stores, for one field point and wavelength,

* ``amplitude``: 1 where a ray reaches the image unvignetted, 0 elsewhere
  (outside the unit circle, vignetted, missed or TIR),
* ``opd``: optical path difference in waves (NaN where amplitude is 0),
* the image-space numerical apertures ``na_x``/``na_y`` mapping normalised pupil
  coordinates to image-space direction cosines (fitted from real rays, so they
  include the real F/# change with field), used to scale diffraction images.

Sign convention: the complex field is ``A * exp(-2 pi i W)`` and the image of a
pupil point (px, py) seen from image point (x, y) adds the phase
``-2 pi (na_x x px + na_y y py) / lambda``, which places a wavefront tilt at the
same image position as the geometric rays.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from ..raytrace import RayGenerator, trace
from .common import resolve_field
from .fans import _Reference


@dataclass
class PupilFunction:
    field: tuple
    wavelength: float  # um
    px: np.ndarray  # 1-D normalised pupil axis (n)
    amplitude: np.ndarray  # (n, n), rows = py
    opd: np.ndarray  # (n, n) waves
    na_x: float
    na_y: float
    chief: np.ndarray  # chief-ray image point (3,)
    wavelength_lens_units: float

    @property
    def n(self):
        return self.px.size

    @property
    def mask(self):
        return self.amplitude > 0

    @property
    def complex(self):
        W = np.where(self.mask, self.opd, 0.0)
        return self.amplitude * np.exp(-2j * math.pi * W)

    @property
    def rms(self):
        """RMS OPD (waves) about the mean, over the transmitted pupil."""
        w = self.opd[self.mask]
        return float(np.sqrt(np.mean((w - w.mean()) ** 2))) if w.size else math.nan

    @property
    def transmission(self):
        """Fraction of the unit-circle pupil that is transmitted."""
        X, Y = np.meshgrid(self.px, self.px)
        return float(self.mask.sum() / max((X**2 + Y**2 <= 1).sum(), 1))


def pupil_function(system, field=0, wavelength=None, n: int = 64, reference=None) -> PupilFunction:
    """Sample the pupil of one field point at one wavelength.

    Pupil samples sit at cell centres, ``px = -1 + (j + 0.5) * 2 / n``, as in
    FFT-based diffraction codes.  ``reference`` may be a precomputed
    reference sphere (the ``_Reference`` used by :func:`opd`).
    """
    wavelength = system.primary if wavelength is None else float(wavelength)
    hx, hy = resolve_field(system, field)
    ref = reference or _Reference(system, hx, hy)
    v = -1.0 + (np.arange(n) + 0.5) * 2.0 / n
    X, Y = np.meshgrid(v, v)
    inside = X**2 + Y**2 <= 1.0
    px, py = X[inside], Y[inside]
    gen = RayGenerator(system, wavelength)
    P, D, o = gen.rays(np.full(px.size + 1, hx), np.full(px.size + 1, hy),
                       np.append(px, 0.0), np.append(py, 0.0))
    res = trace(system, P, D, wavelength, o)
    L = ref.opl_to_sphere(res)
    wl = wavelength * system.wavelength_scale
    W = (L[-1] - L[:-1]) / wl
    ok = res.valid[:-1] & np.isfinite(W)

    amp = np.zeros(X.shape)
    opd = np.full(X.shape, np.nan)
    amp[inside] = ok.astype(float)
    opd[inside] = np.where(ok, W, np.nan)

    # image-space NA per unit normalised pupil coordinate, fitted from real rays
    n_img = system.media(wavelength)[0][system.image_index - 1]
    d = res.direction[:-1][ok] * n_img
    if ok.sum() >= 3:
        A = np.column_stack([np.ones(ok.sum()), px[ok], py[ok]])
        cL, *_ = np.linalg.lstsq(A, d[:, 0], rcond=None)
        cM, *_ = np.linalg.lstsq(A, d[:, 1], rcond=None)
        na_x, na_y = -cL[1], -cM[2]
    else:
        na_x = na_y = math.nan
    return PupilFunction((hx, hy), wavelength, v, amp, opd, float(na_x), float(na_y), ref.center.copy(), wl)
