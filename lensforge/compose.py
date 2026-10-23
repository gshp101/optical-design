"""Combine lenses: scale a prescription, reverse surface order, insert one lens into another.

>>> import lensforge as lf
>>> sys = lf.samples.singlet()
>>> lf.insert_lens(sys, lf.load("doublet.lens.json"), at=3, scale=0.5, reverse=True)
range(3, 6)

All three work on surface lists from any lensforge system, so the same calls serve
"Insert Lens" in the desktop app and scripts.
"""

from __future__ import annotations

import math
from typing import List, Optional, Sequence

from . import surfaces as S

#: per surface type, the scalar parameters that are lengths (scale with the lens)
_LENGTHS = {"thickness", "semi_diameter", "norm_radius", "focal_length", "decenter_x", "decenter_y"}
_CURVATURES = {"curvature", "curvature_x"}  # 1 / length


def _scale_aperture(ap: Optional[dict], k: float):
    if not ap:
        return ap
    return {key: (v * k if isinstance(v, (int, float)) and key != "type" else v) for key, v in ap.items()}


def scale_surface(surface: S.Surface, factor: float) -> S.Surface:
    """A copy of ``surface`` with every length multiplied by ``factor``.

    Radii, thicknesses, semi-diameters, apertures, decentres, focal lengths and
    asphere/freeform/phase coefficients are scaled so the shape (and the optical
    path a phase surface adds) scales exactly; conics and tilts are unchanged.
    Grating line density is divided by ``factor`` (the period scales with the lens).
    """
    k = float(factor)
    if k <= 0 or not math.isfinite(k):
        raise ValueError("scale factor must be a positive number")
    d = surface.to_dict()
    kind = d["type"]
    for key, v in list(d.items()):
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            continue
        if key in _LENGTHS and math.isfinite(v):
            d[key] = v * k
        elif key in _CURVATURES:
            d[key] = v / k
    if "aperture" in d:
        d["aperture"] = _scale_aperture(d["aperture"], k)
    c = d.get("coefficients")
    if c:
        if kind in ("EVENASPH", "TOROIDAL"):  # a_i r^(2i)
            d["coefficients"] = [a * k ** (1 - 2 * i) for i, a in enumerate(c, start=1)]
        elif kind == "ODDASPH":  # b_i r^i, i = 1..
            d["coefficients"] = [b * k ** (1 - i) for i, b in enumerate(c, start=1)]
        elif kind == "BINARY2":  # phase in normalised radius; R0 scales, the added path scales with k
            d["coefficients"] = [a * k for a in c]
    if kind == "XYPOLY":  # coefficients are sag in lens units of normalised x, y
        d["terms"] = [[i, j, cc * k] for i, j, cc in d.get("terms", [])]
    if kind == "DGRATING":
        d["lines_per_um"] = d["lines_per_um"] / k
    return S.surface_from_dict(d)


def scale_system(system, factor: float):
    """Scale a whole system in place (all surfaces, aperture value when it is a length,
    and fields when they are heights). Returns the system."""
    k = float(factor)
    system.surfaces = [scale_surface(s, k) for s in system.surfaces]
    if system.aperture_type in ("EPD", "FLOAT"):
        system.aperture_value *= k
    if system.field_type in ("OBJECT_HEIGHT", "IMAGE_HEIGHT", "PARAXIAL_IMAGE_HEIGHT"):
        for f in system.fields:
            f.x *= k
            f.y *= k
    return system


def _is_mirror(system, surface) -> bool:
    try:
        return bool(system.library.resolve(surface.material).is_mirror)
    except Exception:
        return False


def _medium_after(system, surfaces: Sequence[S.Surface], before=None) -> List:
    """Material spec of the medium light is in after each surface (mirrors and plain
    coordinate breaks keep the medium they were in)."""
    out, cur = [], before
    for s in surfaces:
        if _is_mirror(system, s):
            pass
        elif s.is_coordinate_break:
            if s.material not in (None, "", "AIR"):
                cur = s.material
        else:
            cur = s.material
        out.append(cur)
    return out


def _reverse_one(s: S.Surface) -> dict:
    """The surface seen from the other side (rotated 180 degrees about the y axis):
    sags change sign and x becomes -x."""
    d = s.to_dict()
    kind = d["type"]
    for key in ("curvature", "curvature_x"):
        if key in d:
            d[key] = -d[key]
    if kind in ("EVENASPH", "ODDASPH", "TOROIDAL") and d.get("coefficients"):
        d["coefficients"] = [-a for a in d["coefficients"]]
    if kind == "XYPOLY":
        d["terms"] = [[i, j, -c * (-1) ** i] for i, j, c in d.get("terms", [])]
    if kind == "COORDBRK":
        # inverse transform, seen in the flipped frame
        d["decenter_y"] = -d.get("decenter_y", 0.0)
        d["tilt_y"] = -d.get("tilt_y", 0.0)
        d["order"] = 1 - int(d.get("order", 0))
    ap = d.get("aperture")
    if ap and "dx" in ap:
        ap["dx"] = -ap["dx"]
    return d


def reverse_surfaces(system, surfaces: Sequence[S.Surface], medium_before=None,
                     last_thickness: Optional[float] = None) -> List[S.Surface]:
    """``surfaces`` (consecutive surfaces of ``system``) in reverse order, as the light
    would meet them travelling the other way.

    Curvatures and sag coefficients change sign, each surface takes the thickness
    and material of the gap/medium that came before it, and coordinate breaks are
    inverted. ``medium_before`` is the material in front of the first surface (air
    by default); the reversed group's last surface gets ``last_thickness`` (default:
    the original last surface's thickness, e.g. the back focal distance).
    """
    surfaces = list(surfaces)
    n = len(surfaces)
    if not n:
        return []
    media = _medium_after(system, surfaces, medium_before)
    out = []
    for j in range(n - 1, -1, -1):
        s = surfaces[j]
        d = _reverse_one(s)
        d["thickness"] = surfaces[j - 1].thickness if j > 0 else (
            surfaces[-1].thickness if last_thickness is None else last_thickness)
        if _is_mirror(system, s):
            d["material"] = s.material
        elif not s.is_coordinate_break:
            d["material"] = media[j - 1] if j > 0 else medium_before
        out.append(S.surface_from_dict(d))
    return out


def lens_surfaces(source, first: int = 1, last: Optional[int] = None, scale: float = 1.0,
                  reverse: bool = False, keep_stop: bool = False) -> List[S.Surface]:
    """Copies of surfaces ``first``..``last`` of ``source`` (default: everything between
    the object and image), scaled and optionally reversed, ready to insert."""
    last = source.image_index - 1 if last is None else last
    if not 1 <= first <= last <= source.image_index - 1:
        raise ValueError(f"surface range {first}..{last} is outside 1..{source.image_index - 1}")
    group = [s.copy() for s in source.surfaces[first:last + 1]]
    if reverse:
        before = _medium_after(source, source.surfaces[:first])[-1]
        group = reverse_surfaces(source, group, before)
    if scale != 1.0:
        group = [scale_surface(s, scale) for s in group]
    if not keep_stop:
        for s in group:
            s.stop = False
    return group


def insert_lens(target, source, at: Optional[int] = None, first: int = 1, last: Optional[int] = None,
                scale: float = 1.0, reverse: bool = False, keep_stop: bool = False,
                convert_units: bool = True) -> range:
    """Insert surfaces ``first``..``last`` of ``source`` (a system, or a path to a lens
    file) into ``target`` before surface ``at`` (default: just before the image).

    ``scale`` multiplies every length, ``reverse`` flips the group end for end, and
    ``keep_stop`` moves the target's stop to the inserted lens's stop surface (otherwise
    the target keeps its stop). With ``convert_units`` a lens in other units (inches,
    say) is converted to the target's units on top of ``scale``. Glasses are copied by name, so they must be in the
    target's catalogs. Returns the range of new surface indices. Variables, solves
    and merit operands of the target are not renumbered here (the desktop app does
    that); call this before setting them up.
    """
    if isinstance(source, str):
        from .io import load
        source = load(source)
    if convert_units and source.units != target.units:
        from .system import UNIT_SCALE_MM
        scale = scale * UNIT_SCALE_MM[source.units] / UNIT_SCALE_MM[target.units]
    at = target.image_index if at is None else int(at)
    if not 1 <= at <= target.image_index:
        raise IndexError(f"surfaces can only be inserted before surfaces 1..{target.image_index}")
    group = lens_surfaces(source, first, last, scale, reverse, keep_stop)
    if keep_stop and any(s.stop for s in group):
        for s in target.surfaces:
            s.stop = False
    for i, s in enumerate(group):
        target.insert(at + i, s)
    return range(at, at + len(group))
