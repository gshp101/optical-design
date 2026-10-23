"""Scalar figures of merit for optimisation and tolerancing.

Every function takes the system first and returns a float, so merit
functions can be assembled from them directly.  :data:`OPERANDS` maps short
Zemax-like names to these functions and :func:`evaluate` calls one by name.
:func:`sensitivity` gives finite-difference derivatives of any metric with
respect to surface parameters (the basis of both damped-least-squares
optimisation and sensitivity tolerancing).
"""

from __future__ import annotations

import math
from typing import Callable, Dict, Iterable, Sequence, Tuple

import numpy as np

from .energy import diffraction_energy, geometric_energy, radius_for_energy
from .fans import wavefront
from .field import chromatic_focal_shift, distortion as _distortion, lateral_color
from .illumination import relative_illumination
from .mtf import mtf_at
from .psf import strehl as _strehl
from .seidel import seidel
from .spot import spot_diagram
from .zernike import zernike_coefficients


def rms_spot(system, field=0, wavelengths=None, reference="centroid", rings: int = 6) -> float:
    return spot_diagram(system, field, wavelengths, rings=rings, reference=reference)["rms_radius"]


def geo_spot(system, field=0, wavelengths=None, reference="centroid", rings: int = 6) -> float:
    return spot_diagram(system, field, wavelengths, rings=rings, reference=reference)["geo_radius"]


def rms_wavefront(system, field=0, wavelength=None, sampling: int = 32, remove_tilt: bool = True) -> float:
    """RMS OPD in waves (to centroid, i.e. tilt removed, by default)."""
    return wavefront(system, field, wavelength, sampling, remove_tilt=remove_tilt)["rms"]


def strehl_ratio(system, field=0, wavelengths=None, method="fft", **kw) -> float:
    return _strehl(system, field, wavelengths, method, **kw)


def mtf_tangential(system, frequency, field=0, wavelengths=None, method="fft", **kw) -> float:
    return mtf_at(system, frequency, field, wavelengths, method, **kw)[0]


def mtf_sagittal(system, frequency, field=0, wavelengths=None, method="fft", **kw) -> float:
    return mtf_at(system, frequency, field, wavelengths, method, **kw)[1]


def mtf_average(system, frequency, field=0, wavelengths=None, method="fft", **kw) -> float:
    return float(np.mean(mtf_at(system, frequency, field, wavelengths, method, **kw)))


def ee_radius(system, fraction=0.8, field=0, wavelengths=None, method="geometric", kind="encircled", **kw) -> float:
    """Radius (lens units) containing ``fraction`` of the energy."""
    fn = geometric_energy if method == "geometric" else diffraction_energy
    return radius_for_energy(fn(system, field, wavelengths, kind=kind, n_radii=200, **kw), fraction)


def efl(system) -> float:
    return float(system.paraxial().efl)


def bfl(system) -> float:
    return float(system.paraxial().bfl)


def working_fnum(system) -> float:
    return float(system.paraxial().working_fnum)


def image_fnum(system) -> float:
    return float(system.paraxial().image_space_fnum)


def total_track(system) -> float:
    return float(system.paraxial().total_track)


def magnification(system) -> float:
    return float(system.paraxial().magnification)


def distortion_percent(system, field=1.0, wavelength=None, kind="ftan") -> float:
    return _distortion(system, field, wavelength, kind)


def seidel_sum(system, term="S1") -> float:
    r = seidel(system)
    for group in ("totals", "wavefront", "transverse", "longitudinal"):
        if term in r[group]:
            return float(r[group][term])
    raise KeyError(term)


def zernike_term(system, term=4, field=0, wavelength=None, kind="fringe") -> float:
    return float(zernike_coefficients(system, field, wavelength, max(term, 4), kind)["coefficients"][term - 1])


def lateral_color_max(system) -> float:
    return float(np.nanmax(np.abs(lateral_color(system, n_fields=11)["extreme"])))


def axial_color(system) -> float:
    """Paraxial focus difference shortest minus longest wavelength."""
    from ..paraxial import ParaxialAnalysis
    w = sorted(x.value for x in system.wavelengths)
    return float(ParaxialAnalysis(system, w[0]).image_distance - ParaxialAnalysis(system, w[-1]).image_distance)


def relative_illumination_edge(system, sampling: int = 32) -> float:
    return float(relative_illumination(system, n_fields=2, sampling=sampling)["relative_illumination"][-1])


def field_weighted(system, metric: Callable, **kw) -> float:
    """Field-weight averaged metric over all system fields (metric(system, field=i, ...))."""
    w = np.array([f.weight for f in system.fields], float)
    v = np.array([metric(system, field=i, **kw) for i in range(len(system.fields))])
    return float(np.sum(w * v) / np.sum(w))


OPERANDS: Dict[str, Callable] = {
    "RSCE": rms_spot, "GEOS": geo_spot, "RWCE": rms_wavefront, "STRH": strehl_ratio,
    "MTFT": mtf_tangential, "MTFS": mtf_sagittal, "MTFA": mtf_average, "EERA": ee_radius,
    "EFFL": efl, "BFL": bfl, "WFNO": working_fnum, "ISFN": image_fnum, "TTHI": total_track,
    "PMAG": magnification, "DIST": distortion_percent, "SEID": seidel_sum, "ZERN": zernike_term,
    "LACL": lateral_color_max, "AXCL": axial_color, "RELI": relative_illumination_edge,
}


def evaluate(system, operand: str, *args, **kw) -> float:
    """Evaluate a metric by its operand name, e.g. ``evaluate(lens, "MTFT", 50, field=1)``."""
    return OPERANDS[operand.upper()](system, *args, **kw)


ParamSpec = Tuple[int, str]  # (surface index, parameter name, e.g. "curvature", "thickness", "coefficients[1]")


def _get(system, spec):
    i, name = spec
    s = system.surfaces[i]
    if "[" in name:
        base, idx = name[:-1].split("[")
        arr = list(getattr(s, base))
        idx = int(idx)
        return arr[idx] if idx < len(arr) else 0.0
    return float(getattr(s, name))


def set_parameter(system, spec: ParamSpec, value: float):
    i, name = spec
    s = system.surfaces[i]
    if name == "thickness":
        s.thickness = float(value)
    else:
        s.set_param(name, value)


def sensitivity(system, params: Sequence[ParamSpec], metric: Callable, step: float = 1e-6,
                relative: bool = True, **kw):
    """Central-difference derivatives d metric / d parameter.

    ``step`` is relative to the parameter magnitude (absolute for zero values)
    when ``relative``.  Returns dict with ``nominal``, ``derivatives`` and the
    steps used.  The system is not modified.
    """
    base = metric(system, **kw)
    der, steps = [], []
    for spec in params:
        v = _get(system, spec)
        h = step * max(abs(v), 1.0) if relative else step
        sp, sm = system.copy(), system.copy()
        set_parameter(sp, spec, v + h)
        set_parameter(sm, spec, v - h)
        der.append((metric(sp, **kw) - metric(sm, **kw)) / (2 * h))
        steps.append(h)
    return {"nominal": float(base), "params": list(params), "derivatives": np.array(der), "steps": np.array(steps)}


def sweep(system, spec: ParamSpec, values: Iterable[float], metric: Callable, **kw):
    """Metric vs one parameter (Zemax "Universal Plot" 1-D)."""
    values = np.asarray(list(values), float)
    out = np.empty(values.size)
    for k, v in enumerate(values):
        t = system.copy()
        set_parameter(t, spec, v)
        try:
            out[k] = metric(t, **kw)
        except Exception:
            out[k] = math.nan
    return {"values": values, "metric": out}
