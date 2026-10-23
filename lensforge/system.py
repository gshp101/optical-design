"""The lens data model: an ordered list of surfaces plus system settings.

Conventions (same as most sequential design codes):

* Surface 0 is the object surface, the last surface is the image surface.
  ``thickness`` of a surface is the distance to the next surface; the object
  thickness may be ``inf`` (object at infinity).
* ``material`` is the medium *after* the surface; "MIRROR" reflects, and the
  thickness after a mirror is normally negative.
* Radii are positive when the centre of curvature lies to the right (+z).
* Lengths are in lens units (``units``, default mm); wavelengths in micrometres.
* Field angles are in degrees.  A positive field angle gives rays a positive
  slope, i.e. it corresponds to a negative object coordinate.
"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field as dc_field
from typing import List, Optional, Sequence

import numpy as np

from . import surfaces as S
from .materials import AIR, Material, MaterialLibrary, default_library

UNIT_SCALE_MM = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "in": 25.4}

APERTURE_TYPES = ("EPD", "IMAGE_FNUM", "OBJECT_NA", "STOP_SIZE", "WORKING_FNUM")
FIELD_TYPES = ("ANGLE", "OBJECT_HEIGHT", "PARAXIAL_IMAGE_HEIGHT", "REAL_IMAGE_HEIGHT")

_DEFAULT_LIBRARY: Optional[MaterialLibrary] = None


def shared_library() -> MaterialLibrary:
    """The process-wide material library (built-in catalogs + any loaded AGFs)."""
    global _DEFAULT_LIBRARY
    if _DEFAULT_LIBRARY is None:
        _DEFAULT_LIBRARY = default_library()
    return _DEFAULT_LIBRARY


@dataclass
class Field:
    x: float = 0.0
    y: float = 0.0
    weight: float = 1.0
    # vignetting factors (pupil compression / shift), as in common design codes
    vdx: float = 0.0
    vdy: float = 0.0
    vcx: float = 0.0
    vcy: float = 0.0


@dataclass
class Wavelength:
    value: float  # micrometres
    weight: float = 1.0


class OpticalSystem:
    def __init__(self, name: str = "", units: str = "mm", library: Optional[MaterialLibrary] = None):
        self.name = name
        self.units = units
        self.library = library or shared_library()
        self.surfaces: List[S.Surface] = [
            S.Standard(thickness=math.inf, comment="OBJECT"),
            S.Standard(thickness=0.0, comment="IMAGE"),
        ]
        self.aperture_type = "EPD"
        self.aperture_value = 10.0
        self.field_type = "ANGLE"
        self.fields: List[Field] = [Field(0.0, 0.0)]
        self.wavelengths: List[Wavelength] = [Wavelength(0.5875618)]
        self.primary_wavelength = 0  # index into wavelengths
        self.ray_aiming = "paraxial"  # or "real"
        self.notes = ""

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------
    @property
    def object(self) -> S.Surface:
        return self.surfaces[0]

    @property
    def image(self) -> S.Surface:
        return self.surfaces[-1]

    @property
    def image_index(self) -> int:
        return len(self.surfaces) - 1

    @property
    def num_surfaces(self) -> int:
        return len(self.surfaces)

    def insert(self, index: int, surface: S.Surface) -> S.Surface:
        if index <= 0 or index > self.image_index:
            raise IndexError("Surfaces can only be inserted between the object and image")
        self.surfaces.insert(index, surface)
        return surface

    def add_surface(self, surface: Optional[S.Surface] = None, **kw) -> S.Surface:
        """Append a surface just before the image surface.

        Either pass a Surface instance or keyword args for a Standard surface,
        e.g. ``add_surface(radius=50, thickness=5, material="N-BK7")``.
        """
        if surface is None:
            surface = S.Standard(**kw)
        return self.insert(self.image_index, surface)

    def remove(self, index: int):
        if index <= 0 or index >= self.image_index:
            raise IndexError("Cannot remove the object or image surface")
        del self.surfaces[index]

    def set_aperture(self, kind: str, value: float):
        kind = kind.upper()
        if kind not in APERTURE_TYPES:
            raise ValueError(f"aperture type must be one of {APERTURE_TYPES}")
        self.aperture_type, self.aperture_value = kind, float(value)

    def set_fields(self, values: Sequence, kind: str = "ANGLE"):
        """Set fields from a list of y values or (x, y) pairs (or Field objects)."""
        kind = kind.upper()
        if kind not in FIELD_TYPES:
            raise ValueError(f"field type must be one of {FIELD_TYPES}")
        self.field_type = kind
        out = []
        for v in values:
            if isinstance(v, Field):
                out.append(v)
            elif np.ndim(v) == 0:
                out.append(Field(0.0, float(v)))
            else:
                out.append(Field(*[float(a) for a in v]))
        self.fields = out

    def set_wavelengths(self, values: Sequence, primary: int = 0):
        self.wavelengths = [w if isinstance(w, Wavelength) else
                            Wavelength(*w) if np.ndim(w) else Wavelength(float(w)) for w in values]
        self.primary_wavelength = primary

    @property
    def primary(self) -> float:
        return self.wavelengths[self.primary_wavelength].value

    @property
    def stop_index(self) -> int:
        for i, s in enumerate(self.surfaces):
            if s.stop:
                return i
        return 1

    @stop_index.setter
    def stop_index(self, index: int):
        for i, s in enumerate(self.surfaces):
            s.stop = i == index

    @property
    def object_at_infinity(self) -> bool:
        return math.isinf(self.surfaces[0].thickness) or abs(self.surfaces[0].thickness) > 1e10

    @property
    def max_field(self) -> float:
        m = max((math.hypot(f.x, f.y) for f in self.fields), default=0.0)
        return m if m > 0 else 1.0

    def normalized_field(self, index: int):
        f = self.fields[index]
        return f.x / self.max_field, f.y / self.max_field

    @property
    def wavelength_scale(self) -> float:
        """Multiply a wavelength in um by this to get lens units."""
        return 1e-3 / UNIT_SCALE_MM[self.units]

    # ------------------------------------------------------------------
    # Materials
    # ------------------------------------------------------------------
    def material(self, index: int) -> Material:
        return self.library.resolve(self.surfaces[index].material)

    def media(self, wavelength: float):
        """Refractive indices of the medium after each surface at ``wavelength`` (um).

        Returns (n, mirror, n_signed): positive indices, a boolean array marking
        mirrors, and indices whose sign flips after each reflection (paraxial
        convention).
        """
        n = np.empty(self.num_surfaces)
        signed = np.empty(self.num_surfaces)
        mirror = np.zeros(self.num_surfaces, dtype=bool)
        cur, sign = 1.0, 1.0
        for i, s in enumerate(self.surfaces):
            m = self.library.resolve(s.material)
            if s.is_coordinate_break:
                # a coordinate break does not change the medium
                if s.material not in (None, "", "AIR") and not m.is_mirror and i > 0:
                    cur = float(m.index(wavelength))
            elif m.is_mirror:
                mirror[i] = True
                sign = -sign
            else:
                cur = float(m.index(wavelength))
            n[i] = cur
            signed[i] = sign * cur
        return n, mirror, signed

    # ------------------------------------------------------------------
    # Geometry
    # ------------------------------------------------------------------
    def surface_frames(self):
        """Global placement of each surface: list of (R, origin), where the
        columns of R are the surface's local axes in global coordinates.

        Surface 1's vertex is the global origin.  The object surface sits at
        z = -thickness (or is omitted, ``None``, when at infinity).
        """
        frames = []
        R = np.eye(3)
        O = np.zeros(3)
        for i, s in enumerate(self.surfaces):
            if i == 0:
                frames.append(None if self.object_at_infinity else (R.copy(), np.array([0, 0, -s.thickness])))
                continue
            if s.is_coordinate_break:
                frames.append((R.copy(), O.copy()))
                Rc, d = s.frame()
                O = O + R @ d
                R = R @ Rc
            else:
                frames.append((R.copy(), O.copy()))
            O = O + R @ np.array([0.0, 0.0, s.thickness])
        return frames

    # ------------------------------------------------------------------
    # Analysis entry points (thin wrappers so users have one object)
    # ------------------------------------------------------------------
    def paraxial(self, wavelength: Optional[float] = None):
        from .paraxial import ParaxialAnalysis
        return ParaxialAnalysis(self, wavelength)

    def trace(self, hx=0.0, hy=0.0, px=0.0, py=0.0, wavelength=None, **kw):
        from .raytrace import trace_rays
        return trace_rays(self, hx, hy, px, py, wavelength=wavelength, **kw)

    def update_semi_diameters(self, n_rays: int = 32, margin: float = 0.0):
        """Set each surface's semi-diameter to cover all fields and wavelengths
        (the "automatic" semi-diameter of commercial codes)."""
        from .raytrace import trace_rays
        th = np.linspace(0, 2 * np.pi, n_rays, endpoint=False)
        px, py = np.cos(th), np.sin(th)
        sd = np.zeros(self.num_surfaces)
        for k in range(len(self.fields)):
            hx, hy = self.normalized_field(k)
            for w in self.wavelengths:
                r = trace_rays(self, hx, hy, px, py, wavelength=w.value, apertures=False)
                rr = np.hypot(r.positions[..., 0], r.positions[..., 1])
                rr = np.where(r.valid[None, :], rr, 0.0)
                sd = np.maximum(sd, np.nanmax(rr, axis=1))
        for i, s in enumerate(self.surfaces):
            if i == 0 and self.object_at_infinity:
                continue
            if not s.is_coordinate_break:
                s.semi_diameter = float(sd[i]) * (1 + margin)
        return sd

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------
    def to_dict(self) -> dict:
        def num(x):
            return "inf" if isinstance(x, float) and math.isinf(x) else x

        surfs = []
        for s in self.surfaces:
            d = s.to_dict()
            surfs.append({k: num(v) for k, v in d.items()})
        return {
            "format": "lensforge-1",
            "name": self.name,
            "units": self.units,
            "aperture": {"type": self.aperture_type, "value": self.aperture_value},
            "fields": {"type": self.field_type, "values": [vars(f) for f in self.fields]},
            "wavelengths": {"values": [vars(w) for w in self.wavelengths], "primary": self.primary_wavelength},
            "ray_aiming": self.ray_aiming,
            "notes": self.notes,
            "surfaces": surfs,
            **self._optimization_dict(),
        }

    def _optimization_dict(self) -> dict:
        """Variables, solves and the attached merit function (see lensforge.optimize)."""
        opt = {}
        if getattr(self, "variables", None):
            opt["variables"] = [v.to_dict() for v in self.variables]
        if getattr(self, "solves", None):
            opt["solves"] = [s.to_dict() for s in self.solves]
        mf = getattr(self, "merit_function", None)
        if mf is not None:
            try:
                opt["merit_function"] = mf.to_dict()
            except TypeError:  # user-function operands cannot be saved
                pass
        return {"optimization": opt} if opt else {}

    @classmethod
    def from_dict(cls, d: dict, library: Optional[MaterialLibrary] = None) -> "OpticalSystem":
        def num(x):
            return math.inf if x == "inf" else -math.inf if x == "-inf" else x

        sys = cls(d.get("name", ""), d.get("units", "mm"), library)
        sys.aperture_type = d["aperture"]["type"]
        sys.aperture_value = float(d["aperture"]["value"])
        sys.field_type = d["fields"]["type"]
        sys.fields = [Field(**f) for f in d["fields"]["values"]]
        sys.wavelengths = [Wavelength(**w) for w in d["wavelengths"]["values"]]
        sys.primary_wavelength = d["wavelengths"].get("primary", 0)
        sys.ray_aiming = d.get("ray_aiming", "paraxial")
        sys.notes = d.get("notes", "")
        sys.surfaces = [S.surface_from_dict({k: num(v) for k, v in s.items()}) for s in d["surfaces"]]
        if d.get("optimization"):
            from .optimize import MeritFunction, Variable, VariableSet, solve_from_dict
            o = d["optimization"]
            sys.variables = VariableSet(Variable(**v) for v in o.get("variables", []))
            sys.solves = [solve_from_dict(x) for x in o.get("solves", [])]
            if "merit_function" in o:
                sys.merit_function = MeritFunction.from_dict(o["merit_function"])
        return sys

    def copy(self) -> "OpticalSystem":
        lib = self.library
        self.library = None
        try:
            c = copy.deepcopy(self)
        finally:
            self.library = lib
        c.library = lib
        return c

    # ------------------------------------------------------------------
    # Display
    # ------------------------------------------------------------------
    def prescription(self) -> str:
        rows = [f"{'#':>3} {'Type':9} {'Radius':>12} {'Thickness':>12} {'Material':>12} {'Conic':>9} {'Semi-Dia':>9}  Comment"]
        for i, s in enumerate(self.surfaces):
            r = getattr(s, "radius", math.inf)
            rad = "Infinity" if math.isinf(r) else f"{r:.6g}"
            t = "Infinity" if math.isinf(s.thickness) else f"{s.thickness:.6g}"
            mat = s.material if isinstance(s.material, (str, type(None))) else str(s.material)
            sd = "" if s.semi_diameter is None else f"{s.semi_diameter:.4g}"
            label = "STO" if s.stop else ("OBJ" if i == 0 else "IMA" if i == self.image_index else str(i))
            con = f"{getattr(s, 'conic', 0.0):.4g}"
            rows.append(f"{label:>3} {s.kind:9} {rad:>12} {t:>12} {mat or '':>12} {con:>9} {sd:>9}  {s.comment}")
        return "\n".join(rows)

    def __repr__(self):
        return f"OpticalSystem({self.name!r}, {self.num_surfaces} surfaces)"
