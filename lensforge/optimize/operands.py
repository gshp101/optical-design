"""Merit function operands (Zemax-style four-letter names).

Each operand is a function ``f(ctx, **params)`` returning either a float or a
:class:`Block` (a vector of values with per-element weights, used by the
default merit functions so one row can hold all rays of a field).  ``ctx`` is
an :class:`EvalContext`, which caches traces, the paraxial analysis and the
Seidel sums during one evaluation of a merit function.

Common parameters: ``surf`` / ``surf2`` (surface indices), ``wave`` (index into
the system wavelengths; default primary), ``hx, hy, px, py`` (normalised field
and pupil coordinates), ``field`` (field index or (hx, hy) tuple), ``freq``
(cycles/mm).  ``OPERAND_INFO`` lists every operand with a one-line description.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Dict, Optional

import numpy as np

from ..analysis import metrics as M
from ..analysis.fans import _Reference, opd as _opd
from ..paraxial import ParaxialAnalysis
from ..raytrace import MISS, TIR, VIGNETTED, trace_rays
from .variables import get_param


@dataclass
class Block:
    """A vector-valued operand result.

    ``values`` are compared with the row target element-wise; ``weights``
    multiply the squared errors and ``norm`` (default ``weights``) is what the
    elements add to the merit function's total weight.
    """

    values: np.ndarray
    weights: Optional[np.ndarray] = None
    norm: Optional[np.ndarray] = None

    def __post_init__(self):
        self.values = np.asarray(self.values, float).ravel()
        self.weights = np.ones_like(self.values) if self.weights is None else np.asarray(self.weights, float).ravel()
        self.norm = self.weights.copy() if self.norm is None else np.asarray(self.norm, float).ravel()


class OperandError(RuntimeError):
    """Raised when an operand cannot be computed (e.g. a ray failed)."""


class EvalContext:
    def __init__(self, system):
        self.system = system
        self.values = []  # scalar value of each row evaluated so far
        self._cache: Dict = {}

    def cached(self, key, fn):
        if key not in self._cache:
            self._cache[key] = fn()
        return self._cache[key]

    def wavelength(self, wave):
        s = self.system
        return s.primary if wave is None else s.wavelengths[int(wave)].value

    def paraxial(self, wave=None):
        return self.cached(("par", wave), lambda: ParaxialAnalysis(self.system, self.wavelength(wave)))

    def seidel(self):
        from ..analysis.seidel import seidel
        return self.cached("seidel", lambda: seidel(self.system))

    def trace(self, hx, hy, px, py, wave=None):
        key = ("ray", hx, hy, px, py, wave)

        def run():
            r = trace_rays(self.system, hx, hy, px, py, wavelength=self.wavelength(wave))
            if not r.valid[0]:
                raise OperandError(f"ray (hx={hx}, hy={hy}, px={px}, py={py}) failed")
            return r
        return self.cached(key, run)

    def chief(self, hx, hy):
        def run():
            r = trace_rays(self.system, hx, hy, 0.0, 0.0, wavelength=self.system.primary, apertures=False)
            if not r.valid[0]:
                raise OperandError("chief ray failed")
            return r
        return self.cached(("chief", hx, hy), run)

    def semi_diameters(self):
        """Semi-diameter of every surface: the stored value, or the extent of the
        marginal rays of all fields at the primary wavelength."""
        def run():
            s = self.system
            th = np.linspace(0, 2 * np.pi, 16, endpoint=False)
            px, py = np.cos(th), np.sin(th)
            sd = np.zeros(s.num_surfaces)
            for k in range(len(s.fields)):
                hx, hy = s.normalized_field(k)
                r = trace_rays(s, hx, hy, px, py, apertures=False)
                rr = np.hypot(r.positions[..., 0], r.positions[..., 1])
                rr = np.where(r.valid[None, :], rr, 0.0)
                sd = np.maximum(sd, np.nanmax(rr, axis=1))
            for i, surf in enumerate(s.surfaces):
                if surf.semi_diameter is not None:
                    sd[i] = surf.semi_diameter
            return sd
        return self.cached("sd", run)


OPERANDS: Dict[str, Callable] = {}
OPERAND_INFO: Dict[str, str] = {}
DEFAULT_BOUND: Dict[str, str] = {}


def operand(name, doc, bound="="):
    def deco(fn):
        OPERANDS[name] = fn
        OPERAND_INFO[name] = doc
        DEFAULT_BOUND[name] = bound
        return fn
    return deco


def _fieldspec(field, hx, hy):
    return field if field is not None else (hx, hy)


# ---------------------------------------------------------------------------
# First-order properties
# ---------------------------------------------------------------------------

@operand("EFFL", "Effective focal length (wave)")
def _effl(ctx, wave=None):
    return float(ctx.paraxial(wave).efl)


@operand("BFL", "Back focal length")
def _bfl(ctx, wave=None):
    return float(ctx.paraxial(wave).bfl)


@operand("PMAG", "Paraxial magnification")
def _pmag(ctx, wave=None):
    return float(ctx.paraxial(wave).magnification)


@operand("WFNO", "Working F/# (paraxial)")
def _wfno(ctx, wave=None):
    return float(ctx.paraxial(wave).working_fnum)


@operand("ISFN", "Image-space F/# (EFL / EPD)")
def _isfn(ctx, wave=None):
    return float(ctx.paraxial(wave).image_space_fnum)


@operand("ISNA", "Image-space numerical aperture")
def _isna(ctx, wave=None):
    return float(ctx.paraxial(wave).image_space_na)


@operand("EPDI", "Entrance pupil diameter")
def _epdi(ctx):
    return float(ctx.paraxial().epd)


@operand("ENPP", "Entrance pupil position (from surface 1)")
def _enpp(ctx):
    return float(ctx.paraxial().entrance_pupil_position)


@operand("EXPP", "Exit pupil position (from the last surface)")
def _expp(ctx):
    return float(ctx.paraxial().exit_pupil_position)


@operand("PIMH", "Paraxial image height at the paraxial image plane (wave)")
def _pimh(ctx, wave=None):
    return float(ctx.paraxial(wave).paraxial_image_height)


@operand("LINV", "Lagrange invariant")
def _linv(ctx):
    return float(ctx.paraxial().lagrange_invariant)


@operand("TOTR", "Total track (surface 1 to image)")
def _totr(ctx):
    return float(ctx.paraxial().total_track)


@operand("POWR", "Paraxial power of a surface (surf, wave)")
def _powr(ctx, surf, wave=None):
    return float(ctx.paraxial(wave).phi[surf])


def _parray(ctx, surf, hy, py, wave):
    par = ctx.paraxial(wave)
    ym, num = par.marginal_ray
    yc, nuc = par.chief_ray
    k = surf - 1
    return py * ym[k] + hy * yc[k], (py * num[k] + hy * nuc[k]) / par.n[surf]


@operand("PARY", "Paraxial ray height on a surface (surf, hy, py, wave)")
def _pary(ctx, surf, hy=0.0, py=1.0, wave=None):
    return float(_parray(ctx, surf, hy, py, wave)[0])


@operand("PARB", "Paraxial ray slope after a surface (surf, hy, py, wave)")
def _parb(ctx, surf, hy=0.0, py=1.0, wave=None):
    return float(_parray(ctx, surf, hy, py, wave)[1])


@operand("AXCL", "Axial colour: paraxial focus shift shortest - longest wavelength")
def _axcl(ctx):
    return M.axial_color(ctx.system)


# ---------------------------------------------------------------------------
# Lens data / construction constraints
# ---------------------------------------------------------------------------

@operand("PARV", "Value of any lens parameter (surf, param), e.g. param='conic' or 'glass.nd'")
def _parv(ctx, surf, param):
    return get_param(ctx.system, surf, param)


for _n, _b in (("CVVA", "="), ("CVGT", ">"), ("CVLT", "<")):
    operand(_n, f"Curvature of surf ({'value' if _b == '=' else 'greater than' if _b == '>' else 'less than'} target)",
            _b)(lambda ctx, surf: float(ctx.system.surfaces[surf].curvature))
for _n, _b in (("COVA", "="), ("COGT", ">"), ("COLT", "<")):
    operand(_n, "Conic constant of surf", _b)(lambda ctx, surf: float(ctx.system.surfaces[surf].conic))
for _n, _b in (("CTVA", "="), ("CTGT", ">"), ("CTLT", "<")):
    operand(_n, "Centre thickness of surf", _b)(lambda ctx, surf: float(ctx.system.surfaces[surf].thickness))


def _edge_thickness(ctx, surf, height=None):
    s = ctx.system
    h = ctx.semi_diameters()[surf:surf + 2].max() if height is None else height
    z1 = s.surfaces[surf].sag(np.array([h]), np.array([0.0]))[0]
    z2 = s.surfaces[surf + 1].sag(np.array([h]), np.array([0.0]))[0]
    return float(s.surfaces[surf].thickness - np.nan_to_num(z1) + np.nan_to_num(z2))


for _n, _b in (("ETVA", "="), ("ETGT", ">"), ("ETLT", "<")):
    operand(_n, "Edge thickness of surf at its semi-diameter (or height)", _b)(_edge_thickness)


@operand("TTHI", "Sum of thicknesses of surfaces surf..surf2")
def _tthi(ctx, surf, surf2=None):
    surf2 = surf if surf2 is None else surf2
    return float(sum(ctx.system.surfaces[k].thickness for k in range(surf, surf2 + 1)))


def _is_glass(system, i):
    m = system.library.resolve(system.surfaces[i].material)
    return (not m.is_mirror) and (m.nd != 1.0)


def _range_block(ctx, surf, surf2, which, edge):
    s = ctx.system
    surf = 1 if surf is None else surf
    surf2 = s.image_index - 2 if surf2 is None else surf2
    vals = []
    for i in range(surf, surf2 + 1):
        if s.surfaces[i].is_coordinate_break or s.surfaces[i + 1].is_coordinate_break:
            continue
        if s.library.resolve(s.surfaces[i].material).is_mirror:
            continue
        g = _is_glass(s, i)
        if which == "glass" and not g or which == "air" and g:
            continue
        vals.append(_edge_thickness(ctx, i) if edge else s.surfaces[i].thickness)
    return Block(np.array(vals), norm=np.zeros(len(vals)))


for _n, _which, _edge, _b, _d in (
        ("MNCT", "all", False, ">", "Minimum centre thickness"), ("MXCT", "all", False, "<", "Maximum centre thickness"),
        ("MNCG", "glass", False, ">", "Minimum centre thickness, glass"),
        ("MXCG", "glass", False, "<", "Maximum centre thickness, glass"),
        ("MNCA", "air", False, ">", "Minimum centre thickness, air"),
        ("MXCA", "air", False, "<", "Maximum centre thickness, air"),
        ("MNET", "all", True, ">", "Minimum edge thickness"), ("MXET", "all", True, "<", "Maximum edge thickness"),
        ("MNEG", "glass", True, ">", "Minimum edge thickness, glass"),
        ("MXEG", "glass", True, "<", "Maximum edge thickness, glass"),
        ("MNEA", "air", True, ">", "Minimum edge thickness, air"),
        ("MXEA", "air", True, "<", "Maximum edge thickness, air")):
    operand(_n, _d + " over surfaces surf..surf2 (one-sided boundary)", _b)(
        (lambda w, e: (lambda ctx, surf=None, surf2=None: _range_block(ctx, surf, surf2, w, e)))(_which, _edge))


@operand("INDX", "Refractive index after surf (wave)")
def _indx(ctx, surf, wave=None):
    return float(ctx.system.media(ctx.wavelength(wave))[0][surf])


@operand("ABBE", "Abbe number Vd of the material after surf")
def _abbe(ctx, surf):
    return float(ctx.system.library.resolve(ctx.system.surfaces[surf].material).vd)


# ---------------------------------------------------------------------------
# Real rays
# ---------------------------------------------------------------------------

def _ray(ctx, surf, hx, hy, px, py, wave):
    r = ctx.trace(hx, hy, px, py, wave)
    surf = ctx.system.image_index if surf is None else surf
    return r, surf


@operand("REAX", "Real ray x on surf (local coordinates)")
def _reax(ctx, surf=None, hx=0.0, hy=0.0, px=0.0, py=0.0, wave=None):
    r, k = _ray(ctx, surf, hx, hy, px, py, wave)
    return float(r.positions[k, 0, 0])


@operand("REAY", "Real ray y on surf (local coordinates)")
def _reay(ctx, surf=None, hx=0.0, hy=0.0, px=0.0, py=0.0, wave=None):
    r, k = _ray(ctx, surf, hx, hy, px, py, wave)
    return float(r.positions[k, 0, 1])


@operand("REAZ", "Real ray z on surf (local coordinates)")
def _reaz(ctx, surf=None, hx=0.0, hy=0.0, px=0.0, py=0.0, wave=None):
    r, k = _ray(ctx, surf, hx, hy, px, py, wave)
    return float(r.positions[k, 0, 2])


@operand("REAR", "Real ray radial height on surf")
def _rear(ctx, surf=None, hx=0.0, hy=0.0, px=0.0, py=0.0, wave=None):
    r, k = _ray(ctx, surf, hx, hy, px, py, wave)
    return float(np.hypot(*r.positions[k, 0, :2]))


@operand("REAB", "Real ray y direction cosine after surf")
def _reab(ctx, surf=None, hx=0.0, hy=0.0, px=0.0, py=0.0, wave=None):
    r, k = _ray(ctx, surf, hx, hy, px, py, wave)
    return float(r.directions[k, 0, 1])


@operand("RANG", "Real ray angle (radians) to the local z axis after surf")
def _rang(ctx, surf=None, hx=0.0, hy=0.0, px=0.0, py=0.0, wave=None):
    r, k = _ray(ctx, surf, hx, hy, px, py, wave)
    return float(math.acos(min(1.0, abs(r.directions[k, 0, 2]))))


def _angles(ctx, surf, hx, hy, px, py, wave):
    r, k = _ray(ctx, surf, hx, hy, px, py, wave)
    D, N = r.directions[k, 0], r.normals[k, 0]
    c_out = min(1.0, abs(float(D @ N)))
    s_out = math.sqrt(max(0.0, 1 - c_out**2))
    n, mirror, _ = ctx.system.media(ctx.wavelength(wave))
    if mirror[k]:
        return math.degrees(math.asin(s_out)), math.degrees(math.asin(s_out))
    s_in = s_out * n[k] / n[k - 1]
    return math.degrees(math.asin(min(1.0, s_in))), math.degrees(math.asin(s_out))


@operand("RAID", "Real ray angle of incidence on surf (degrees)")
def _raid(ctx, surf, hx=0.0, hy=0.0, px=0.0, py=0.0, wave=None):
    return _angles(ctx, surf, hx, hy, px, py, wave)[0]


@operand("RAED", "Real ray angle of exitance from surf (degrees)")
def _raed(ctx, surf, hx=0.0, hy=0.0, px=0.0, py=0.0, wave=None):
    return _angles(ctx, surf, hx, hy, px, py, wave)[1]


def _transverse(ctx, hx, hy, px, py, wave):
    r = ctx.trace(hx, hy, px, py, wave)
    c = ctx.chief(hx, hy)
    return r.x[0] - c.x[0], r.y[0] - c.y[0]


@operand("TRAX", "Transverse ray error x on the image (relative to the primary chief ray)")
def _trax(ctx, hx=0.0, hy=0.0, px=0.0, py=0.0, wave=None):
    return float(_transverse(ctx, hx, hy, px, py, wave)[0])


@operand("TRAY", "Transverse ray error y on the image (relative to the primary chief ray)")
def _tray(ctx, hx=0.0, hy=0.0, px=0.0, py=0.0, wave=None):
    return float(_transverse(ctx, hx, hy, px, py, wave)[1])


@operand("TRAR", "Radial transverse ray error on the image")
def _trar(ctx, hx=0.0, hy=0.0, px=0.0, py=0.0, wave=None):
    return float(np.hypot(*_transverse(ctx, hx, hy, px, py, wave)))


@operand("OPDC", "Optical path difference (waves) relative to the chief ray")
def _opdc(ctx, hx=0.0, hy=0.0, px=0.0, py=0.0, wave=None):
    ref = ctx.cached(("ref", hx, hy), lambda: _Reference(ctx.system, hx, hy))
    v = _opd(ctx.system, hx, hy, px, py, ctx.wavelength(wave), ref)[0]
    if not np.isfinite(v):
        raise OperandError("OPD ray failed")
    return float(v)


# ---------------------------------------------------------------------------
# Image quality (wrapping lensforge.analysis.metrics)
# ---------------------------------------------------------------------------

def _waves(wave):
    return None if wave is None else [int(wave)]


@operand("RSCE", "RMS spot radius, centroid reference (field, wave=None: polychromatic)")
def _rsce(ctx, field=0, wave=None, rings=6):
    return M.rms_spot(ctx.system, field, _waves(wave), "centroid", rings)


@operand("RSCH", "RMS spot radius, chief-ray reference")
def _rsch(ctx, field=0, wave=None, rings=6):
    return M.rms_spot(ctx.system, field, _waves(wave), "chief", rings)


@operand("GEOS", "Geometric (max) spot radius, centroid reference")
def _geos(ctx, field=0, wave=None, rings=6):
    return M.geo_spot(ctx.system, field, _waves(wave), "centroid", rings)


@operand("RWCE", "RMS wavefront error (waves), tilt removed")
def _rwce(ctx, field=0, wave=None, sampling=32):
    return M.rms_wavefront(ctx.system, field, ctx.wavelength(wave), sampling)


@operand("STRH", "Strehl ratio")
def _strh(ctx, field=0, wave=None, **kw):
    return M.strehl_ratio(ctx.system, field, _waves(wave), **kw)


@operand("MTFT", "Tangential MTF at freq (cycles/mm)")
def _mtft(ctx, freq, field=0, wave=None, **kw):
    return M.mtf_tangential(ctx.system, freq, field, _waves(wave), **kw)


@operand("MTFS", "Sagittal MTF at freq")
def _mtfs(ctx, freq, field=0, wave=None, **kw):
    return M.mtf_sagittal(ctx.system, freq, field, _waves(wave), **kw)


@operand("MTFA", "Average of tangential and sagittal MTF at freq")
def _mtfa(ctx, freq, field=0, wave=None, **kw):
    return M.mtf_average(ctx.system, freq, field, _waves(wave), **kw)


@operand("EERA", "Radius enclosing a fraction of the energy (geometric by default)")
def _eera(ctx, fraction=0.8, field=0, wave=None, **kw):
    return M.ee_radius(ctx.system, fraction, field, _waves(wave), **kw)


@operand("ZERN", "Zernike coefficient (waves) of the wavefront (term, field, wave, kind)")
def _zern(ctx, term=4, field=0, wave=None, kind="fringe"):
    return M.zernike_term(ctx.system, term, field, ctx.wavelength(wave), kind)


@operand("DIST", "Real distortion in percent at a field fraction (field=1.0 is the edge)")
def _dist(ctx, field=1.0, wave=None, kind="ftan"):
    return M.distortion_percent(ctx.system, field, None if wave is None else ctx.wavelength(wave), kind)


@operand("LACL", "Maximum lateral colour over the field")
def _lacl(ctx):
    return M.lateral_color_max(ctx.system)


@operand("RELI", "Relative illumination at the edge of the field")
def _reli(ctx, sampling=32):
    return M.relative_illumination_edge(ctx.system, sampling)


def _seidel_term(ctx, key, surf):
    r = ctx.seidel()
    if not surf:
        return float(r["wavefront"][key])
    return float(np.asarray(r["wavefront_per_surface"][key])[surf])


@operand("SPHA", "Seidel spherical aberration W040 (waves) of surf, or total if surf=0")
def _spha(ctx, surf=0):
    return _seidel_term(ctx, "W040", surf)


@operand("COMA", "Seidel coma W131 (waves) of surf, or total")
def _coma(ctx, surf=0):
    return _seidel_term(ctx, "W131", surf)


@operand("ASTI", "Seidel astigmatism W222 (waves) of surf, or total")
def _asti(ctx, surf=0):
    return _seidel_term(ctx, "W222", surf)


@operand("FCUR", "Seidel field curvature W220 (waves) of surf, or total")
def _fcur(ctx, surf=0):
    return _seidel_term(ctx, "W220", surf)


@operand("DISW", "Seidel distortion W311 (waves) of surf, or total")
def _disw(ctx, surf=0):
    return _seidel_term(ctx, "W311", surf)


@operand("SEID", "Any Seidel quantity by name (term='S1'..'S5','CL','CT','TSPH', ...)")
def _seid(ctx, term="S1"):
    return M.seidel_sum(ctx.system, term)


# ---------------------------------------------------------------------------
# Default-merit-function blocks
# ---------------------------------------------------------------------------

def gaussian_quadrature(rings: int = 3, arms: int = 6, symmetric: bool = False):
    """Gaussian quadrature pupil sampling (Forbes 1988): ``rings`` radii from a
    Gauss-Legendre rule in r^2 and ``arms`` equally spaced azimuths.  With
    ``symmetric`` only the half pupil px >= 0 is sampled (systems symmetric
    about the y-z plane).  Returns (px, py, weights) with weights summing to 1;
    weighted sums integrate polynomials of degree 2*rings-1 in r^2 exactly."""
    x, w = np.polynomial.legendre.leggauss(rings)
    r = np.sqrt((x + 1) / 2)
    w = w / 2
    if symmetric:
        th = -np.pi / 2 + (np.arange(arms) + 0.5) * np.pi / arms
    else:
        th = (np.arange(arms) + 0.5) * 2 * np.pi / arms
    R, T = np.meshgrid(r, th, indexing="ij")
    W = np.repeat(w[:, None], arms, axis=1) / arms
    return (R * np.cos(T)).ravel(), (R * np.sin(T)).ravel(), W.ravel()


def is_symmetric(system) -> bool:
    """True if the system and its fields are symmetric about the y-z plane."""
    if any(f.x != 0 for f in system.fields):
        return False
    for s in system.surfaces:
        if s.is_coordinate_break and (s.decenter_x or s.tilt_y or s.tilt_z):
            return False
        if s.kind == "XYPOLY":
            return False
        ap = s.aperture
        if ap is not None and getattr(ap, "dx", 0.0):
            return False
    return True


def _wave_set(ctx, wavelengths):
    s = ctx.system
    idx = range(len(s.wavelengths)) if wavelengths is None else wavelengths
    vals = [s.wavelengths[i].value for i in idx]
    w = np.array([s.wavelengths[i].weight for i in idx], float)
    return vals, w / w.sum()


def _ray_bundle(ctx, field, wavelengths, rings, arms, symmetric):
    s = ctx.system
    hx, hy = (field if isinstance(field, (tuple, list)) else s.normalized_field(int(field)))
    sym = is_symmetric(s) if symmetric is None else symmetric
    px, py, q = gaussian_quadrature(rings, arms, sym)
    waves, ww = _wave_set(ctx, wavelengths)
    out = []
    for wl, w in zip(waves, ww):
        r = trace_rays(s, hx, hy, px, py, wavelength=wl)
        bad = (r.status == MISS) | (r.status == TIR)
        if bad.any():
            raise OperandError(f"{int(bad.sum())} rays failed (miss/TIR) at field ({hx:g}, {hy:g})")
        keep = r.status != VIGNETTED
        out.append((wl, w, r, keep))
    return hx, hy, px, py, q, sym, out


@operand("RAYS", "Default-merit block: transverse ray errors of one field over a Gaussian-quadrature pupil "
                 "(field, reference='centroid'|'chief', rings, arms, wavelengths)")
def _rays(ctx, field=0, reference="centroid", rings=3, arms=6, wavelengths=None, symmetric=None):
    hx, hy, px, py, q, sym, bundle = _ray_bundle(ctx, field, wavelengths, rings, arms, symmetric)
    if reference == "centroid":
        sx = sy = sw = 0.0
        for wl, w, r, keep in bundle:
            qq = w * q * keep
            sx += np.sum(qq * np.where(keep, r.x, 0.0))
            sy += np.sum(qq * np.where(keep, r.y, 0.0))
            sw += qq.sum()
        if sw == 0:
            raise OperandError("all rays vignetted")
        cx, cy = (0.0 if sym else sx / sw), sy / sw
    else:
        c = ctx.chief(hx, hy)
        cx, cy = c.x[0], c.y[0]
    vals, wts = [], []
    for wl, w, r, keep in bundle:
        qq = w * q * keep
        vals += [np.where(keep, r.x - cx, 0.0), np.where(keep, r.y - cy, 0.0)]
        wts += [qq, qq]
    total = sum(w * np.sum(q * keep) for wl, w, r, keep in bundle)
    W = np.concatenate(wts)
    return Block(np.concatenate(vals), W, W / (2 * total))


@operand("OPDS", "Default-merit block: OPD (waves) of one field over a Gaussian-quadrature pupil, "
                 "piston removed (and tilt for reference='centroid')")
def _opds(ctx, field=0, reference="centroid", rings=3, arms=6, wavelengths=None, symmetric=None):
    s = ctx.system
    hx, hy = (field if isinstance(field, (tuple, list)) else s.normalized_field(int(field)))
    sym = is_symmetric(s) if symmetric is None else symmetric
    px, py, q = gaussian_quadrature(rings, arms, sym)
    waves, ww = _wave_set(ctx, wavelengths)
    ref = ctx.cached(("ref", hx, hy), lambda: _Reference(s, hx, hy))
    vals, wts = [], []
    for wl, w in zip(waves, ww):
        W = _opd(s, hx, hy, px, py, wl, ref)
        if not np.all(np.isfinite(W)):
            raise OperandError(f"OPD rays failed at field ({hx:g}, {hy:g})")
        cols = [np.ones_like(px)]
        if reference == "centroid":
            cols += [py] if sym else [px, py]
        A = np.column_stack(cols)
        sq = np.sqrt(q)
        c, *_ = np.linalg.lstsq(A * sq[:, None], W * sq, rcond=None)
        vals.append(W - A @ c)
        wts.append(w * q)
    Wt = np.concatenate(wts)
    return Block(np.concatenate(vals), Wt, Wt)


# ---------------------------------------------------------------------------
# Maths on other rows and user operands
# ---------------------------------------------------------------------------

def _row(ctx, k):
    if k >= len(ctx.values) or k < 0:
        raise OperandError(f"operand refers to row {k}, which is not before this row")
    return ctx.values[k]


@operand("BLNK", "Blank row / comment")
def _blnk(ctx, **kw):
    return 0.0


@operand("CONS", "Constant value")
def _cons(ctx, value=0.0):
    return float(value)


@operand("SUMM", "Row a + row b")
def _summ(ctx, a, b):
    return _row(ctx, a) + _row(ctx, b)


@operand("DIFF", "Row a - row b")
def _diff(ctx, a, b):
    return _row(ctx, a) - _row(ctx, b)


@operand("PROD", "Row a * row b")
def _prod(ctx, a, b):
    return _row(ctx, a) * _row(ctx, b)


@operand("DIVI", "Row a / row b")
def _divi(ctx, a, b):
    return _row(ctx, a) / _row(ctx, b)


@operand("ABSO", "|row a|")
def _abso(ctx, a):
    return abs(_row(ctx, a))


@operand("SQRT", "sqrt(row a)")
def _sqrt(ctx, a):
    return math.sqrt(_row(ctx, a))


@operand("OSUM", "Sum of rows a..b")
def _osum(ctx, a, b):
    return float(sum(_row(ctx, k) for k in range(a, b + 1)))


@operand("MAXX", "Maximum of rows a..b")
def _maxx(ctx, a, b):
    return float(max(_row(ctx, k) for k in range(a, b + 1)))


@operand("MINN", "Minimum of rows a..b")
def _minn(ctx, a, b):
    return float(min(_row(ctx, k) for k in range(a, b + 1)))


@operand("OPGT", "Row a, constrained greater than target", ">")
def _opgt(ctx, a):
    return _row(ctx, a)


@operand("OPLT", "Row a, constrained less than target", "<")
def _oplt(ctx, a):
    return _row(ctx, a)


@operand("OPVA", "Row a, constrained equal to target")
def _opva(ctx, a):
    return _row(ctx, a)


@operand("USER", "User function func(system, **args) -> float or Block")
def _user(ctx, func, **kw):
    return func(ctx.system, **kw)
