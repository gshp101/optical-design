"""Optimisation variables: named parameters of the lens that the optimiser may change.

A variable is addressed like a cell of a lens data editor: a surface index and
a parameter name.  Supported names

* any scalar surface parameter: ``"curvature"``, ``"radius"`` (varied as
  curvature), ``"thickness"``, ``"conic"``, ``"focal_length"``,
  ``"decenter_x"``, ``"tilt_x"``, ...
* list entries: ``"coefficients[1]"`` (aspheric / diffractive terms),
  ``"terms[3]"`` (XY polynomial),
* model-glass parameters of the material after the surface: ``"glass.nd"``,
  ``"glass.vd"``, ``"glass.dpgf"``.  A catalog glass is converted to the
  equivalent model glass when such a variable is created (as in other codes,
  where a glass must be a "model" glass to be varied).

Variables are stored on the system (``system.variables``) so they travel with
the lens, like the "V" flags of a lens data editor.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional

import numpy as np

from ..materials import ModelGlass

GLASS_PARAMS = ("glass.nd", "glass.vd", "glass.dpgf")


def _split_list(name):
    base, idx = name[:-1].split("[")
    return base, int(idx)


def get_param(system, surface: int, name: str) -> float:
    """Value of a parameter (see module docstring for names)."""
    s = system.surfaces[surface]
    if name in GLASS_PARAMS:
        m = system.library.resolve(s.material)
        if isinstance(m, ModelGlass):
            return {"glass.nd": m.nd_value, "glass.vd": m.vd_value, "glass.dpgf": m.dpgf}[name]
        if name == "glass.dpgf":
            return 0.0
        return float(m.nd if name == "glass.nd" else m.vd)
    if "[" in name:
        base, idx = _split_list(name)
        arr = list(getattr(s, base))
        return float(arr[idx]) if idx < len(arr) else 0.0
    return float(getattr(s, name))


def set_param(system, surface: int, name: str, value: float):
    s = system.surfaces[surface]
    value = float(value)
    if name in GLASS_PARAMS:
        m = system.library.resolve(s.material)
        if isinstance(m, ModelGlass):
            nd, vd, dp = m.nd_value, m.vd_value, m.dpgf
        else:
            nd, vd, dp = m.nd, m.vd, 0.0
        key = name.split(".")[1]
        nd, vd, dp = (value if key == "nd" else nd, value if key == "vd" else vd, value if key == "dpgf" else dp)
        s.material = ModelGlass(nd, vd, dp)
    elif name == "thickness":
        s.thickness = value
    else:
        s.set_param(name, value)


def to_model_glass(system, surface: int) -> ModelGlass:
    """Replace the surface's material by the model glass with the same nd / vd."""
    s = system.surfaces[surface]
    m = system.library.resolve(s.material)
    if not isinstance(m, ModelGlass):
        if m.is_mirror or m.nd == 1.0:
            raise ValueError(f"surface {surface}: material {m.name!r} cannot be a glass variable")
        m = ModelGlass(m.nd, m.vd)
        s.material = m
    return m


def typical_step(system, surface: int, name: str) -> float:
    """A parameter change producing a small (about 1e-6 lens units) geometric effect;
    used for finite-difference derivatives and to scale variables."""
    s = system.surfaces[surface]
    r = s.semi_diameter or 0.0
    if not r:
        try:
            r = 0.5 * system.paraxial().epd
        except Exception:  # pragma: no cover - degenerate systems
            r = 10.0
    r = max(r, 1e-3)
    if name in ("curvature", "curvature_x"):
        return 2e-6 / r**2
    if name in ("radius", "radius_x"):
        v = abs(get_param(system, surface, name))
        return 1e-6 * max(v, r) if math.isfinite(v) else 1e-6 * r
    if name == "conic":
        c = abs(getattr(s, "curvature", 0.0)) or 1.0 / (10 * r)
        return min(1e-3, 8e-6 / max(c**3 * r**4, 1e-30))
    if "[" in name:
        base, idx = _split_list(name)
        if base == "coefficients":
            kind = s.kind
            if kind == "EVENASPH":
                power = 2 * (idx + 2)  # coefficients[0] multiplies r^4
            elif kind == "ODDASPH":
                power = idx + 1
            else:
                return 1e-4  # diffractive phase coefficients (radians, normalised radius)
            return 1e-6 / r**power
        return 1e-6
    if name in ("tilt_x", "tilt_y", "tilt_z"):
        return 1e-5
    if name == "focal_length":
        return 1e-6 * max(abs(get_param(system, surface, name)), 1.0)
    if name == "glass.nd":
        return 1e-6
    if name == "glass.vd":
        return 1e-4
    if name == "glass.dpgf":
        return 1e-6
    return 1e-6 * max(abs(get_param(system, surface, name)), 1.0)


@dataclass
class Variable:
    """One optimisation variable with optional bounds.

    ``step`` overrides the finite-difference step (see :func:`typical_step`).
    ``radius`` is varied internally as curvature, which is smooth through flat.
    """

    surface: int
    param: str
    min: Optional[float] = None
    max: Optional[float] = None
    step: Optional[float] = None

    def __post_init__(self):
        if self.param == "radius":
            self.param = "curvature"
            lo = None if self.min is None else 1.0 / self.min
            hi = None if self.max is None else 1.0 / self.max
            self.min, self.max = (None, None) if (lo is None or hi is None) else (min(lo, hi), max(lo, hi))
        if self.param == "radius_x":
            self.param = "curvature_x"

    @property
    def name(self) -> str:
        return f"S{self.surface}.{self.param}"

    def get(self, system) -> float:
        return get_param(system, self.surface, self.param)

    def set(self, system, value: float):
        set_param(system, self.surface, self.param, value)

    def clip(self, value: float) -> float:
        if self.min is not None:
            value = max(value, self.min)
        if self.max is not None:
            value = min(value, self.max)
        return value

    def fd_step(self, system) -> float:
        return self.step or typical_step(system, self.surface, self.param)

    def to_dict(self):
        return {k: v for k, v in vars(self).items() if v is not None}

    def __repr__(self):
        b = "" if self.min is None and self.max is None else f" in [{self.min}, {self.max}]"
        return f"Variable({self.name}{b})"


class VariableSet(list):
    """List of :class:`Variable` with vector get/set helpers."""

    def values(self, system) -> np.ndarray:
        return np.array([v.get(system) for v in self], float)

    def apply(self, system, x):
        for v, val in zip(self, x):
            v.set(system, val)

    def bounds(self):
        lo = np.array([-np.inf if v.min is None else v.min for v in self], float)
        hi = np.array([np.inf if v.max is None else v.max for v in self], float)
        return lo, hi

    def steps(self, system) -> np.ndarray:
        return np.array([v.fd_step(system) for v in self], float)

    def names(self) -> List[str]:
        return [v.name for v in self]


def variables(system) -> VariableSet:
    """The variables stored on ``system`` (created empty if missing)."""
    if not isinstance(getattr(system, "variables", None), VariableSet):
        system.variables = VariableSet(getattr(system, "variables", None) or [])
    return system.variables


def set_variable(system, surface: int, param: str, min: Optional[float] = None, max: Optional[float] = None,
                 step: Optional[float] = None) -> Variable:
    """Mark a parameter as variable (replaces an existing variable on the same cell)."""
    if param in GLASS_PARAMS and min is None and max is None:
        # keep model glasses inside the region covered by real glasses
        min, max = {"glass.nd": (1.45, 1.95), "glass.vd": (20.0, 90.0), "glass.dpgf": (-0.02, 0.05)}[param]
    var = Variable(surface, param, min, max, step)
    if var.param in GLASS_PARAMS:
        to_model_glass(system, surface)
    vs = variables(system)
    vs[:] = [v for v in vs if (v.surface, v.param) != (var.surface, var.param)]
    vs.append(var)
    return var


def remove_variable(system, surface: int, param: str):
    p = "curvature" if param == "radius" else param
    vs = variables(system)
    vs[:] = [v for v in vs if (v.surface, v.param) != (surface, p)]


def clear_variables(system):
    variables(system).clear()


def vary_curvatures(system, surfaces=None, **kw) -> List[Variable]:
    """Make the curvature of every refracting/reflecting surface (or ``surfaces``) variable."""
    out = []
    idx = range(1, system.image_index) if surfaces is None else surfaces
    for i in idx:
        s = system.surfaces[i]
        if hasattr(s, "curvature") and not s.is_coordinate_break:
            out.append(set_variable(system, i, "curvature", **kw))
    return out


def vary_thicknesses(system, surfaces=None, air_only: bool = False, **kw) -> List[Variable]:
    out = []
    idx = range(1, system.image_index - 1) if surfaces is None else surfaces
    for i in idx:
        s = system.surfaces[i]
        if s.is_coordinate_break:
            continue
        if air_only and system.library.resolve(s.material).nd != 1.0:
            continue
        out.append(set_variable(system, i, "thickness", **kw))
    return out
