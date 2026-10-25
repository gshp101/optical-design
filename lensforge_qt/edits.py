"""Lens-editing operations used by the editors (pure Python, no Qt).

These sit on top of the public lensforge API and add what a spreadsheet
editor needs: parsing typed cell text, surface type changes, and inserting or
deleting surfaces with the surface numbers in variables, solves and merit
operands renumbered (as a lens data editor does).  Nothing here imports Qt, so
a web front end can reuse it.
"""

from __future__ import annotations

import ast
import math
from dataclasses import MISSING, fields as dc_fields
from typing import List, Tuple

import lensforge as lf
from lensforge import surfaces as S
from lensforge import optimize as opt
from lensforge.materials import ConstantIndex, Material, ModelGlass
from lensforge.optimize.variables import GLASS_PARAMS

# ---------------------------------------------------------------------------
# Surface types and their parameter columns
# ---------------------------------------------------------------------------

SURFACE_TYPES = {
    "STANDARD": ("Standard", S.Standard),
    "EVENASPH": ("Even Asphere", S.EvenAsphere),
    "ODDASPH": ("Odd Asphere", S.OddAsphere),
    "TOROIDAL": ("Toroidal", S.Toroidal),
    "XYPOLY": ("XY Polynomial", S.XYPolynomial),
    "BINARY2": ("Binary 2", S.BinaryPhase),
    "DGRATING": ("Diffraction Grating", S.DiffractionGrating),
    "PARAXIAL": ("Paraxial", S.Paraxial),
    "COORDBRK": ("Coordinate Break", S.CoordinateBreak),
}

N_PAR = 8  # number of "Par n" columns in the lens data editor

_ORD = ["2nd", "4th", "6th", "8th", "10th", "12th", "14th", "16th"]


def parameter_columns(surface) -> List[Tuple[str, str]]:
    """(label, parameter name) for the Par 1..N_PAR columns of ``surface``."""
    k = surface.kind
    if k == "EVENASPH":
        return [(f"{_ORD[i]} Order Term", f"coefficients[{i}]") for i in range(N_PAR)]
    if k == "ODDASPH":
        return [(f"Order {i + 1} Term", f"coefficients[{i}]") for i in range(N_PAR)]
    if k == "TOROIDAL":
        return [("Radius X", "radius_x")] + [(f"{_ORD[i]} Order Term", f"coefficients[{i}]") for i in range(N_PAR - 1)]
    if k == "XYPOLY":
        return [("Norm Radius", "norm_radius")]
    if k == "BINARY2":
        return ([("Diffract Order", "diffraction_order"), ("Norm Radius", "norm_radius")]
                + [(f"Coeff p^{2 * (i + 1)}", f"coefficients[{i}]") for i in range(N_PAR - 2)])
    if k == "DGRATING":
        return [("Lines/um", "lines_per_um"), ("Diff Order", "diffraction_order")]
    if k == "PARAXIAL":
        return [("Focal Length", "focal_length")]
    if k == "COORDBRK":
        return [("Decenter X", "decenter_x"), ("Decenter Y", "decenter_y"), ("Tilt About X", "tilt_x"),
                ("Tilt About Y", "tilt_y"), ("Tilt About Z", "tilt_z"), ("Order", "order")]
    return []


def has_radius(surface) -> bool:
    return hasattr(surface, "curvature") and not surface.is_coordinate_break


def get_value(surface, key: str):
    """Value of a lens data editor cell (``key`` = "radius", "thickness", a parameter name...)."""
    if key == "radius":
        return surface.radius
    if key == "radius_x":
        return math.inf if surface.curvature_x == 0 else 1.0 / surface.curvature_x
    if "[" in key:
        base, idx = key[:-1].split("[")
        arr = getattr(surface, base)
        idx = int(idx)
        return float(arr[idx]) if idx < len(arr) else 0.0
    return getattr(surface, key)


# ---------------------------------------------------------------------------
# Parsing typed text
# ---------------------------------------------------------------------------

def parse_number(text, allow_inf: bool = True) -> float:
    t = str(text).strip().lower()
    if t in ("inf", "infinity", "+inf", "infinite") and allow_inf:
        return math.inf
    if t in ("-inf", "-infinity") and allow_inf:
        return -math.inf
    v = float(t)
    if not allow_inf and not math.isfinite(v):
        raise ValueError("value must be finite")
    return v


def format_number(v, digits: int = 8) -> str:
    """Compact display of a cell value (``digits`` significant digits)."""
    if v is None:
        return ""
    if isinstance(v, int) and not isinstance(v, bool):
        return str(v)
    try:
        v = float(v)
    except (TypeError, ValueError):
        return str(v)
    if math.isinf(v):
        return "Infinity" if v > 0 else "-Infinity"
    if math.isnan(v):
        return "NaN"
    return f"{v:.{digits}g}"


def material_text(system, spec) -> str:
    """Text shown in the Material column for a material spec."""
    if spec is None or spec == "":
        return ""
    if isinstance(spec, ModelGlass):
        return f"{spec.nd_value:.6g},{spec.vd_value:.6g}" + (f",{spec.dpgf:.4g}" if spec.dpgf else "")
    if isinstance(spec, dict) and "model" in spec:
        return ",".join(f"{float(v):.6g}" for v in spec["model"])
    if isinstance(spec, ConstantIndex):
        return "" if spec.n == 1.0 else f"{spec.n:.6g}"
    if isinstance(spec, Material):
        return spec.to_spec() if isinstance(spec.to_spec(), str) else spec.name
    if isinstance(spec, float):
        return f"{spec:.6g}"
    return str(spec)


def parse_material(system, text: str):
    """Validated material spec for typed text ("" = air)."""
    t = text.strip()
    if not t or t.upper() == "AIR":
        return None
    system.library.resolve(t)  # raises KeyError for unknown glasses
    return t.upper() if t.upper() == "MIRROR" else t


def parse_params(text: str) -> dict:
    """``"surf=3, hy=1, py=1"`` -> dict (values as Python literals or bare words)."""
    out = {}
    text = text.strip()
    if not text:
        return out
    # split on commas that are not inside brackets
    parts, depth, cur = [], 0, ""
    for ch in text:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    parts.append(cur)
    for p in parts:
        if not p.strip():
            continue
        if "=" not in p:
            raise ValueError(f"parameter {p.strip()!r} must be written name=value")
        k, v = p.split("=", 1)
        k, v = k.strip(), v.strip()
        if not k.isidentifier():
            raise ValueError(f"bad parameter name {k!r}")
        try:
            out[k] = ast.literal_eval(v)
        except (ValueError, SyntaxError):
            out[k] = v  # bare word such as reference=centroid
    return out


def format_params(params: dict) -> str:
    return ", ".join(f"{k}={v!r}" if isinstance(v, str) else f"{k}={v}" for k, v in params.items()
                     if not callable(v))


# ---------------------------------------------------------------------------
# Cell edits
# ---------------------------------------------------------------------------

def set_cell(system, index: int, key: str, text: str):
    """Set one lens data editor cell from typed text."""
    s = system.surfaces[index]
    if key == "comment":
        s.comment = text
        return
    if key == "material":
        if s.is_coordinate_break:
            raise ValueError("a coordinate break has no material")
        s.material = parse_material(system, text)
        return
    if key == "semi_diameter":
        t = text.strip()
        s.semi_diameter = None if t == "" or t.lower() == "auto" else abs(parse_number(t, allow_inf=False))
        return
    if key == "radius":
        if not has_radius(s):
            raise ValueError(f"a {s.kind} surface has no radius")
        r = parse_number(text) if text.strip() else math.inf
        s.radius = r
        return
    if key == "radius_x":
        r = parse_number(text) if text.strip() else math.inf
        s.curvature_x = 0.0 if math.isinf(r) or r == 0 else 1.0 / r
        return
    if key == "thickness":
        v = parse_number(text)
        if math.isinf(v) and index != 0:
            raise ValueError("only the object thickness can be infinite")
        s.thickness = v
        return
    if key == "order":
        s.order = int(parse_number(text, allow_inf=False))
        return
    v = parse_number(text, allow_inf=False)
    s.set_param(key, v)
    if "[" in key:  # drop trailing zero coefficients so the lens file stays tidy
        base = key.split("[")[0]
        arr = list(getattr(s, base))
        while arr and arr[-1] == 0.0:
            arr.pop()
        setattr(s, base, arr)


def change_type(system, index: int, kind: str):
    """Replace surface ``index`` by a surface of type ``kind`` keeping the shared data."""
    old = system.surfaces[index]
    if old.kind == kind:
        return
    if index in (0, system.image_index) and kind == "COORDBRK":
        raise ValueError("the object and image surfaces cannot be coordinate breaks")
    cls = SURFACE_TYPES[kind][1]
    common = dict(thickness=old.thickness, semi_diameter=old.semi_diameter, stop=old.stop, comment=old.comment)
    if kind != "COORDBRK" and not old.is_coordinate_break:
        common["material"] = old.material
    if kind == "COORDBRK":
        new = cls(**common)
    elif kind == "PARAXIAL":
        new = cls(focal_length=getattr(old, "focal_length", 100.0), **common)
    else:
        new = cls(radius=getattr(old, "radius", math.inf), conic=getattr(old, "conic", 0.0), **common)
        if hasattr(old, "coefficients") and hasattr(new, "coefficients"):
            new.coefficients = list(old.coefficients)
    new.aperture = old.aperture
    system.surfaces[index] = new
    # variables / solves on parameters the new type lacks are dropped
    valid = {"thickness", "material", "glass.nd", "glass.vd", "glass.dpgf"}
    valid |= set(new.scalar_params) | {p for _, p in parameter_columns(new)}
    if has_radius(new):
        valid |= {"curvature", "radius"}
    vs = opt.variables(system)
    vs[:] = [v for v in vs if v.surface != index or v.param in valid]
    sl = opt.solves(system)
    sl[:] = [x for x in sl if x.surface != index or x.cell[1] in valid]


def set_stop(system, index: int):
    if index <= 0 or index >= system.image_index:
        raise ValueError("the stop must be between the object and the image")
    system.stop_index = index


# ---------------------------------------------------------------------------
# Inserting / deleting surfaces with renumbering
# ---------------------------------------------------------------------------

_renumber = lf.compose.renumber_surface_refs


def insert_surface(system, index: int, surface=None):
    """Insert a surface before row ``index`` (between object and image)."""
    index = max(1, min(index, system.image_index))
    system.insert(index, surface or S.Standard(thickness=0.0))
    _renumber(system, lambda i: i + 1 if i >= index else i)


def insert_lens(system, source, at: int, **kw) -> range:
    """Insert surfaces of another lens before row ``at`` (see :func:`lensforge.insert_lens`
    for ``first``, ``last``, ``scale``, ``reverse``, ``keep_stop``), shifting variables,
    solves and merit operands that refer to later surfaces."""
    at = max(1, min(int(at), system.image_index))
    n0 = system.num_surfaces
    rng = lf.insert_lens(system, source, at=at, **kw)
    n = system.num_surfaces - n0
    _renumber(system, lambda i: i + n if i >= at else i)
    return rng


def delete_surface(system, index: int):
    """Delete surface ``index``; variables and solves on it are dropped, merit
    operands that referred to it move to the previous surface."""
    delete_surfaces(system, index, index)


def delete_surfaces(system, first: int, last: int) -> int:
    """Delete surfaces ``first``..``last`` (see :func:`lensforge.delete_surfaces`)."""
    return lf.delete_surfaces(system, first, last)


def describe_deletion(system, first: int, last: int) -> List[str]:
    """Lines saying what deleting surfaces ``first``..``last`` removes or changes,
    for a confirmation prompt. Raises ValueError for a range that cannot be deleted."""
    first, last = lf.compose.check_surface_range(system, first, last)
    gone = range(first, last + 1)
    lines = []
    for i in gone:
        s = system.surfaces[i]
        bits = [f"Surface {i}: {SURFACE_TYPES.get(s.kind, (s.kind,))[0]}"]
        if has_radius(s):
            bits.append(f"R {format_number(get_value(s, 'radius'), 6)}")
        bits.append(f"T {format_number(s.thickness, 6)}")
        mat = material_text(system, s.material)
        if mat:
            bits.append(mat)
        if s.comment:
            bits.append(f'"{s.comment}"')
        if s.stop:
            bits.append("(stop)")
        lines.append(", ".join(bits))
    nv = sum(1 for v in opt.variables(system) if v.surface in gone)
    ns = sum(1 for x in opt.solves(system)
             if any(getattr(x, n, None) in gone for n in lf.compose._SOLVE_REFS
                    if isinstance(getattr(x, n, None), int)))
    mf = getattr(system, "merit_function", None)
    nm = 0 if mf is None else sum(
        1 for row in mf.rows
        if any(isinstance(row.params.get(n), int) and not isinstance(row.params.get(n), bool)
               and row.params.get(n) in gone for n in lf.compose._OPERAND_REFS))
    if nv:
        lines.append(f"{nv} variable{'s' if nv > 1 else ''} on these surfaces will be removed.")
    if ns:
        lines.append(f"{ns} solve{'s' if ns > 1 else ''} referring to these surfaces will be removed.")
    if nm:
        lines.append(f"{nm} merit operand{'s' if nm > 1 else ''} will move to surface {first - 1}.")
    if any(system.surfaces[i].stop for i in gone):
        lines.append("The stop moves to the surface that takes the place of the first deleted one.")
    return lines


# ---------------------------------------------------------------------------
# Variables and solves on cells
# ---------------------------------------------------------------------------

def cell_param(key: str) -> str:
    """Optimisation parameter name for a column key."""
    return {"radius": "curvature", "radius_x": "curvature_x"}.get(key, key)


def variable_on(system, index: int, key: str):
    p = cell_param(key)
    for v in getattr(system, "variables", None) or []:
        if v.surface == index and v.param == p:
            return v
    if key == "material":
        for v in getattr(system, "variables", None) or []:
            if v.surface == index and v.param in GLASS_PARAMS:
                return v
    return None


def solve_on(system, index: int, key: str):
    p = cell_param(key)
    for x in getattr(system, "solves", None) or []:
        if x.cell == (index, p):
            return x
    return None


SOLVE_CODES = {"MarginalRayHeight": "M", "ChiefRayHeight": "C", "MarginalRayAngle": "M", "ChiefRayAngle": "C",
               "FNumber": "F", "Concentric": "S", "EdgeThickness": "E", "Position": "T", "Pickup": "P"}

#: solves available for each kind of cell (column key -> solve class names)
SOLVES_FOR = {
    "radius": ["MarginalRayAngle", "ChiefRayAngle", "FNumber", "Concentric", "Pickup"],
    "thickness": ["MarginalRayHeight", "ChiefRayHeight", "EdgeThickness", "Position", "Pickup"],
    "material": ["Pickup"],
}

SOLVE_TITLES = {"MarginalRayHeight": "Marginal ray height", "ChiefRayHeight": "Chief ray height",
                "MarginalRayAngle": "Marginal ray angle", "ChiefRayAngle": "Chief ray angle",
                "FNumber": "F number", "Concentric": "Concentric with surface", "EdgeThickness": "Edge thickness",
                "Position": "Position", "Pickup": "Pickup"}


def solve_class(name):
    from lensforge.optimize.solves import SOLVE_TYPES
    return SOLVE_TYPES[name]


def solve_fields(name) -> list:
    """Editable (field name, default) pairs of a solve class, excluding the solved cell."""
    out = []
    for f in dc_fields(solve_class(name)):
        if f.name in ("surface", "param"):
            continue
        out.append((f.name, None if f.default is MISSING else f.default))
    return out


def make_solve(name, index: int, key: str, values: dict):
    cls = solve_class(name)
    if name == "Pickup":
        return cls(surface=index, param=key if key != "radius" else "radius", **values)
    return cls(surface=index, **values)


def describe_solve(x) -> str:
    vals = {k: v for k, v in vars(x).items() if k not in ("surface", "param")}
    return f"{SOLVE_TITLES.get(type(x).__name__, type(x).__name__)} solve: " + ", ".join(
        f"{k}={format_number(v) if isinstance(v, float) else v}" for k, v in vals.items())


def fill_auto_semi_diameters(system):
    """Copy of ``system`` with every automatic (None) semi-diameter computed."""
    c = system.copy()
    auto = [i for i, s in enumerate(c.surfaces) if s.semi_diameter is None and not s.is_coordinate_break]
    if not auto:
        return c, {}
    try:
        sd = system.copy().update_semi_diameters()
    except Exception:
        return c, {}
    vals = {}
    for i in auto:
        if i == 0 and c.object_at_infinity:
            continue
        v = float(sd[i])
        if math.isfinite(v):
            c.surfaces[i].semi_diameter = v
            vals[i] = v
    return c, vals
