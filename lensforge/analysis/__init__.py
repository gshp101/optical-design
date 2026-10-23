"""Analyses built on the real ray tracer (pure NumPy, no plotting).

Every analysis returns a dict of NumPy arrays and scalars; plotting helpers
live in :mod:`lensforge.plot`.  Scalar figures of merit for optimisation and
tolerancing are in :mod:`lensforge.analysis.metrics`.

=====================  ============================================================
Module                 Analyses
=====================  ============================================================
``fans``, ``spot``     ray fans, OPD fans, wavefront maps, spot diagrams
``pupilfn``            complex pupil function (input of all diffraction analyses)
``psf``                FFT and Huygens PSF, Strehl ratio, image simulation
``mtf``                FFT / Huygens / geometric MTF, through-focus MTF, MTF vs field
``energy``             diffraction and geometric encircled / ensquared / line energy
``seidel``             Seidel sums, wavefront / transverse / longitudinal coefficients
``zernike``            Fringe and Standard (Noll) Zernike polynomials and fits
``field``              field curvature, distortion, grid distortion, lateral colour,
                       longitudinal aberration, chromatic focal shift, pupil aberration
``illumination``       relative illumination, vignetting
``geometry``           layout rays, surface profiles and sag, footprints,
                       through-focus / full-field spots, interferograms
``polarization``       polarisation ray trace, pupil maps, transmission, diattenuation
``report``             cardinal points, single ray trace, dispersion, system report
``metrics``            scalar operands, sensitivity, parameter sweeps
=====================  ============================================================

Note: the functions ``seidel`` and ``mtf`` re-exported here share their
module's name; import from the module path (``lensforge.analysis.mtf``) for
the less common helpers.
"""

from .fans import opd, opd_fan, ray_fan, wavefront
from .spot import spot_diagram
from .pupilfn import PupilFunction, pupil_function
from .psf import fft_psf, huygens_psf, image_simulation, psf_cross_section, strehl
from .mtf import (diffraction_limited_mtf, fft_mtf, geometric_mtf, huygens_mtf, mtf, mtf_at, mtf_from_psf,
                  mtf_vs_field, through_focus_mtf)
from .energy import diffraction_energy, energy_from_psf, geometric_energy, radius_for_energy
from .seidel import seidel, seidel_table
from .zernike import evaluate_zernike, fit_zernike, zernike_coefficients, zernike_name, zernike_xy
from .field import (chromatic_focal_shift, distortion, field_curvature, grid_distortion, lateral_color,
                    longitudinal_aberration, pupil_aberration)
from .illumination import relative_illumination, vignetting
from .geometry import (footprint, full_field_spot, interferogram, layout, surface_profiles, surface_sag,
                       through_focus_spot)
from .polarization import diattenuation, fresnel, polarization_pupil_map, polarization_trace, transmission
from .report import cardinal_points, dispersion, format_ray_table, ray_trace_table, system_report
from . import metrics

__all__ = [
    "opd", "opd_fan", "ray_fan", "wavefront", "spot_diagram", "PupilFunction", "pupil_function",
    "fft_psf", "huygens_psf", "image_simulation", "psf_cross_section", "strehl",
    "diffraction_limited_mtf", "fft_mtf", "geometric_mtf", "huygens_mtf", "mtf", "mtf_at", "mtf_from_psf",
    "mtf_vs_field", "through_focus_mtf",
    "diffraction_energy", "energy_from_psf", "geometric_energy", "radius_for_energy",
    "seidel", "seidel_table",
    "evaluate_zernike", "fit_zernike", "zernike_coefficients", "zernike_name", "zernike_xy",
    "chromatic_focal_shift", "distortion", "field_curvature", "grid_distortion", "lateral_color",
    "longitudinal_aberration", "pupil_aberration",
    "relative_illumination", "vignetting",
    "footprint", "full_field_spot", "interferogram", "layout", "surface_profiles", "surface_sag",
    "through_focus_spot",
    "diattenuation", "fresnel", "polarization_pupil_map", "polarization_trace", "transmission",
    "cardinal_points", "dispersion", "format_ray_table", "ray_trace_table", "system_report", "metrics",
]
