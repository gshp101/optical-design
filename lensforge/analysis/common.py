"""Shared helpers for analyses."""

from __future__ import annotations

from typing import Optional, Sequence, Tuple, Union

FieldSpec = Union[int, Tuple[float, float]]


def resolve_field(system, field: FieldSpec):
    """Field index -> normalised (hx, hy); a 2-tuple is taken as (hx, hy) already."""
    if isinstance(field, (tuple, list)):
        return float(field[0]), float(field[1])
    return system.normalized_field(int(field))


def resolve_wavelengths(system, wavelengths: Optional[Sequence] = None):
    """None -> all system wavelengths; ints are indices; floats are um values."""
    if wavelengths is None:
        return [w.value for w in system.wavelengths]
    if isinstance(wavelengths, (int, float)):
        wavelengths = [wavelengths]
    out = []
    for w in wavelengths:
        out.append(system.wavelengths[w].value if isinstance(w, int) else float(w))
    return out


def resolve_weights(system, wavelengths):
    """Wavelength weights matching ``resolve_wavelengths`` output (1.0 if not a system wavelength)."""
    table = {w.value: w.weight for w in system.wavelengths}
    return [table.get(w, 1.0) for w in wavelengths]


def field_fractions(system, n: Optional[int] = None):
    """Normalised field coordinates hy in [0, 1] for "vs field" plots (n points, default 21)."""
    import numpy as np
    return np.linspace(0.0, 1.0, 21 if n is None else int(n))


def image_index_of(system):
    """Refractive index of image space at the primary wavelength."""
    return system.media(system.primary)[0][system.image_index - 1]


def defocused(system, dz: float):
    """Copy of ``system`` with the image surface moved by ``dz`` (lens units, + = away
    from the last surface along its thickness direction)."""
    s = system.copy()
    last = s.surfaces[s.image_index - 1]
    last.thickness = last.thickness + (dz if last.thickness >= 0 else -dz)
    return s


def bessel_j1(x):
    """Bessel function J1 (rational approximations, |error| < 1e-8), vectorised."""
    import numpy as np
    x = np.asarray(x, dtype=float)
    ax = np.abs(x)
    out = np.empty_like(ax)
    s = ax < 8.0
    y = x[s] ** 2
    a1 = x[s] * (72362614232.0 + y * (-7895059235.0 + y * (242396853.1 + y * (-2972611.439
                 + y * (15704.48260 + y * (-30.16036606))))))
    a2 = 144725228442.0 + y * (2300535178.0 + y * (18583304.74 + y * (99447.43394
                               + y * (376.9991397 + y))))
    out[s] = a1 / a2
    b = ~s
    z = 8.0 / ax[b]
    y = z * z
    xx = ax[b] - 2.356194491
    p1 = 1.0 + y * (0.183105e-2 + y * (-0.3516396496e-4 + y * (0.2457520174e-5 + y * (-0.240337019e-6))))
    p2 = 0.04687499995 + y * (-0.2002690873e-3 + y * (0.8449199096e-5 + y * (-0.88228987e-6
                              + y * 0.105787412e-6)))
    v = np.sqrt(0.636619772 / ax[b]) * (np.cos(xx) * p1 - z * np.sin(xx) * p2)
    out[b] = np.where(x[b] < 0, -v, v)
    return out
