"""Multi-configuration: one lens, several states (zoom positions, focus settings, ...).

A :class:`MultiConfig` is a table, like the multi-configuration editor of
commercial design codes.  Each row is an operand naming one parameter of the
lens (a thickness, a curvature, a glass, the aperture, a field angle ...);
each column is a configuration holding that parameter's value.  The lens
itself (``system.surfaces``, ``system.fields`` ...) always shows the *current*
configuration, so every analysis, the paraxial data and the lens data editor
work on it unchanged.  Switching configuration first stores the lens's current
values of the controlled parameters back in the current column, then loads the
new column into the lens and re-applies the solves.

Configurations are numbered from 1, as in other codes.  Surfaces, fields and
wavelengths are referred to by the same indices as elsewhere in lensforge
(surface 0 is the object, field 0 and wave 0 are the first rows of the Fields
and Wavelengths tables).

Typical scripting use::

    import lensforge as lf

    lens = lf.load("Figure 20.1 short.lens.json")
    mc = lf.MultiConfig.create(lens, 3, names=["short", "mid", "long"])
    mc.add_row(lens, "THIC", 8, values=[59.24, 31.64, 7.21])
    mc.add_row(lens, "THIC", 19, values=[149.674, 167.189, 189.8])
    mc.add_row(lens, "APER", values=[28.6, 34.248, 41.8149])
    for k in mc.configs:
        print(k, mc.names[k - 1], lens.config_copy(k).paraxial().efl)
    lens.set_config(3)                   # the lens now shows the long position

In a merit function, a ``CONF`` row (``mf.add("CONF", cfg=2)``) switches the
configuration for the rows that follow, so one merit function can optimise
all zoom positions together; :func:`lensforge.optimize.default_merit` does
this automatically for a multi-configuration lens.  Cells of the table can be
optimisation variables too (:func:`lensforge.optimize.set_mc_variable`).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field as dc_field
from typing import Any, Callable, Iterable, List, Optional, Sequence

# operand -> (what the reference column holds, one-line description)
#   "surface", "field", "wave": an index; None: the operand needs no reference
MC_OPERANDS = {
    "THIC": ("surface", "Thickness of the surface (distance to the next surface)"),
    "CRVT": ("surface", "Curvature of the surface (1/radius)"),
    "CONN": ("surface", "Conic constant of the surface"),
    "GLSS": ("surface", "Material after the surface (a glass name, MIRROR, an index or 'nd,Vd')"),
    "SDIA": ("surface", "Semi-diameter of the surface ('auto' for automatic)"),
    "PARM": ("surface", "Any other surface parameter, named in the Param column (e.g. coefficients[0], "
                        "decenter_y, tilt_x, focal_length)"),
    "STPS": (None, "Stop surface number"),
    "APER": (None, "System aperture value (EPD, F/# or NA, depending on the aperture type)"),
    "XFIE": ("field", "x value of the field (angle or height, depending on the field type)"),
    "YFIE": ("field", "y value of the field"),
    "FLWT": ("field", "Field weight"),
    "FVDX": ("field", "Vignetting decentre x of the field"),
    "FVDY": ("field", "Vignetting decentre y of the field"),
    "FVCX": ("field", "Vignetting compression x of the field"),
    "FVCY": ("field", "Vignetting compression y of the field"),
    "WAVE": ("wave", "Wavelength in micrometres"),
    "WLWT": ("wave", "Wavelength weight"),
    "PRWV": (None, "Primary wavelength (index, counting from 0)"),
    "MOFF": (None, "Unused row (a comment or placeholder); has no effect"),
}

_SURFACE_ATTR = {"THIC": "thickness", "CRVT": "curvature", "CONN": "conic", "SDIA": "semi_diameter"}
_FIELD_ATTR = {"XFIE": "x", "YFIE": "y", "FLWT": "weight", "FVDX": "vdx", "FVDY": "vdy", "FVCX": "vcx",
               "FVCY": "vcy"}
_WAVE_ATTR = {"WAVE": "value", "WLWT": "weight"}


class MultiConfigError(ValueError):
    """A row refers to something the lens does not have (e.g. a deleted surface)."""


@dataclass
class MCRow:
    """One operand of the multi-configuration table: ``values[k - 1]`` is its value in configuration k."""

    type: str
    ref: Optional[int] = None
    param: Optional[str] = None
    values: List[Any] = dc_field(default_factory=list)
    comment: str = ""

    def __post_init__(self):
        self.type = self.type.upper()
        if self.type not in MC_OPERANDS:
            raise KeyError(f"Unknown multi-configuration operand {self.type!r}; see lensforge.MC_OPERANDS")
        if self.ref_kind is None:
            self.ref = None
        elif self.ref is None:
            self.ref = 0
        else:
            self.ref = int(self.ref)
        if self.type == "PARM" and not self.param:
            raise ValueError("a PARM row needs the parameter name, e.g. param='coefficients[0]'")
        if self.type != "PARM":
            self.param = None

    @property
    def ref_kind(self) -> Optional[str]:
        return MC_OPERANDS[self.type][0]

    @property
    def label(self) -> str:
        """Short name, e.g. 'THIC 8', 'YFIE 2', 'PARM 7 coefficients[0]', 'APER'."""
        s = self.type if self.ref is None else f"{self.type} {self.ref}"
        return f"{s} {self.param}" if self.param else s

    # -- reading / writing the lens ------------------------------------------
    def _check(self, system):
        n = {"surface": system.num_surfaces, "field": len(system.fields), "wave": len(system.wavelengths)}
        kind = self.ref_kind
        if kind is not None and not 0 <= self.ref < n[kind]:
            raise MultiConfigError(f"{self.label}: the lens has no {kind} {self.ref} "
                                   f"({kind}s are numbered 0 to {n[kind] - 1})")

    def get(self, system):
        """The parameter's value in the lens as it is now."""
        self._check(system)
        t = self.type
        if t == "MOFF":
            return None
        if t in _SURFACE_ATTR:
            s = system.surfaces[self.ref]
            if t in ("CRVT", "CONN") and not hasattr(s, _SURFACE_ATTR[t]):
                raise MultiConfigError(f"{self.label}: a {s.kind} surface has no {_SURFACE_ATTR[t]}")
            v = getattr(s, _SURFACE_ATTR[t])
            return None if v is None else float(v)
        if t == "GLSS":
            m = system.surfaces[self.ref].material
            if m is not None and not isinstance(m, (str, int, float, dict)):
                m = m.to_spec()
            return m
        if t == "PARM":
            from .optimize.variables import get_param
            try:
                return get_param(system, self.ref, self.param)
            except AttributeError:
                raise MultiConfigError(f"{self.label}: surface {self.ref} has no parameter {self.param!r}") from None
        if t == "STPS":
            return system.stop_index
        if t == "APER":
            return float(system.aperture_value)
        if t == "PRWV":
            return int(system.primary_wavelength)
        if t in _FIELD_ATTR:
            return float(getattr(system.fields[self.ref], _FIELD_ATTR[t]))
        return float(getattr(system.wavelengths[self.ref], _WAVE_ATTR[t]))

    def set(self, system, value):
        """Write ``value`` into the lens."""
        self._check(system)
        t = self.type
        if t == "MOFF":
            return
        if t in _SURFACE_ATTR:
            s = system.surfaces[self.ref]
            if t == "SDIA":
                s.semi_diameter = None if value is None else float(value)
            elif t == "THIC":
                s.thickness = float(value)
            else:
                if not hasattr(s, _SURFACE_ATTR[t]):
                    raise MultiConfigError(f"{self.label}: a {s.kind} surface has no {_SURFACE_ATTR[t]}")
                s.set_param(_SURFACE_ATTR[t], float(value))
        elif t == "GLSS":
            system.surfaces[self.ref].material = value
        elif t == "PARM":
            from .optimize.variables import set_param
            set_param(system, self.ref, self.param, value)
        elif t == "STPS":
            k = int(value)
            if not 0 < k < system.image_index:
                raise MultiConfigError(f"STPS: surface {k} cannot be the stop")
            system.stop_index = k
        elif t == "APER":
            system.aperture_value = float(value)
        elif t == "PRWV":
            k = int(value)
            if not 0 <= k < len(system.wavelengths):
                raise MultiConfigError(f"PRWV: the lens has no wavelength {k}")
            system.primary_wavelength = k
        elif t in _FIELD_ATTR:
            setattr(system.fields[self.ref], _FIELD_ATTR[t], float(value))
        else:
            setattr(system.wavelengths[self.ref], _WAVE_ATTR[t], float(value))

    def controls(self, surface: int, param: str) -> bool:
        """True if this row sets surface parameter ``param`` (as named by optimisation variables)."""
        if self.ref_kind != "surface" or self.ref != surface:
            return False
        own = self.param if self.type == "PARM" else _SURFACE_ATTR.get(self.type)
        if self.type == "GLSS":
            return param.startswith("glass.")
        if own in ("curvature", "radius"):
            return param in ("curvature", "radius")
        return own == param

    # -- serialisation ---------------------------------------------------------
    def to_dict(self) -> dict:
        d = {"type": self.type}
        if self.ref_kind is not None:
            d[self.ref_kind] = self.ref
        if self.param:
            d["param"] = self.param
        d["values"] = [_num_out(v) for v in self.values]
        if self.comment:
            d["comment"] = self.comment
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "MCRow":
        t = d["type"].upper()
        kind = MC_OPERANDS[t][0] if t in MC_OPERANDS else None
        return cls(t, d.get(kind) if kind else None, d.get("param"), [_num_in(v) for v in d.get("values", [])],
                   d.get("comment", ""))


def _num_out(v):
    if isinstance(v, float) and math.isinf(v):
        return "inf" if v > 0 else "-inf"
    return v


def _num_in(v):
    return math.inf if v == "inf" else -math.inf if v == "-inf" else v


class MultiConfig:
    """The multi-configuration table of a lens (``system.multiconfig``).

    ``rows`` are :class:`MCRow` objects, ``names`` one name per configuration and
    ``current`` the configuration the lens shows (counting from 1).  Methods that
    take ``system`` keep the lens in step with the table.
    """

    def __init__(self, n_configs: int = 1, names: Optional[Sequence[str]] = None, rows: Iterable[MCRow] = (),
                 current: int = 1):
        n_configs = max(1, int(n_configs))
        self.names: List[str] = list(names) if names is not None else [""] * n_configs
        if len(self.names) != n_configs:
            raise ValueError(f"{n_configs} configurations but {len(self.names)} names")
        self.rows: List[MCRow] = list(rows)
        self.current = int(current)
        for r in self.rows:
            self._fit(r)

    @classmethod
    def create(cls, system, n_configs: int = 2, names: Optional[Sequence[str]] = None) -> "MultiConfig":
        """Give ``system`` a new, empty table with ``n_configs`` configurations (replacing any old one)."""
        mc = cls(n_configs, names)
        system.multiconfig = mc
        return mc

    # -- shape -----------------------------------------------------------------
    @property
    def n_configs(self) -> int:
        return len(self.names)

    @property
    def configs(self) -> range:
        """Configuration numbers, 1 .. n_configs."""
        return range(1, self.n_configs + 1)

    def name(self, k: int) -> str:
        """Display name of configuration ``k``: 'Config 2' or 'Config 2 (mid)'."""
        n = self.names[k - 1]
        return f"Config {k}" + (f" ({n})" if n else "")

    def _fit(self, row: MCRow):
        """Pad or cut a row's values to one per configuration (padding repeats the last value)."""
        if len(row.values) < self.n_configs:
            fill = row.values[-1] if row.values else None
            row.values.extend([fill] * (self.n_configs - len(row.values)))
        del row.values[self.n_configs:]

    def _config(self, k) -> int:
        k = int(k)
        if not 1 <= k <= self.n_configs:
            raise IndexError(f"configuration {k} does not exist (there are {self.n_configs}, numbered from 1)")
        return k

    # -- editing rows ------------------------------------------------------------
    def add_row(self, system, type: str, ref: Optional[int] = None, param: Optional[str] = None,
                values: Optional[Sequence] = None, comment: str = "", index: Optional[int] = None) -> MCRow:
        """Add an operand row (at the end, or before row ``index``).

        ``values`` gives one value per configuration; left out, every
        configuration gets the lens's current value.  The current configuration's
        value is written into the lens.
        """
        row = MCRow(type, ref, param, [], comment)
        if values is None:
            row.values = [row.get(system)] * self.n_configs if system is not None else []
        else:
            row.values = [_parse_if_text(row, v) for v in values]
        self._fit(row)
        self.rows.insert(len(self.rows) if index is None else index, row)
        if system is not None:
            row.set(system, row.values[self.current - 1])
        return row

    def remove_row(self, index: int) -> MCRow:
        """Delete a row; the lens keeps the values it has now."""
        return self.rows.pop(index)

    def set_row_operand(self, system, index: int, type: str, ref: Optional[int] = None, param: Optional[str] = None):
        """Change what a row controls; all configurations take the lens's current value of the new parameter
        (or keep their values if the lens has no such parameter; the row is then reported by :meth:`errors`)."""
        old = self.rows[index]
        row = MCRow(type, ref, param, list(old.values), old.comment)
        if system is not None:
            try:
                row.values = [row.get(system)] * self.n_configs
            except MultiConfigError:
                pass
        self.rows[index] = row
        return row

    # -- editing configurations ---------------------------------------------------
    def insert_config(self, system=None, at: Optional[int] = None, copy_from: Optional[int] = None,
                      name: str = "") -> int:
        """Insert a configuration before number ``at`` (default: append).  Its values are copied from
        configuration ``copy_from`` (default: the current one).  Returns the new configuration's number."""
        if system is not None:
            self.capture(system)
        at = self.n_configs + 1 if at is None else max(1, min(int(at), self.n_configs + 1))
        src = self._config(copy_from or self.current) - 1
        for r in self.rows:
            r.values.insert(at - 1, r.values[src])
        self.names.insert(at - 1, name)
        if self.current >= at:
            self.current += 1
        return at

    def remove_config(self, system, k: int):
        """Delete configuration ``k``; the lens then shows the configuration that took its place."""
        k = self._config(k)
        if self.n_configs == 1:
            raise ValueError("the last configuration cannot be deleted")
        if system is not None:
            self.capture(system)
        for r in self.rows:
            del r.values[k - 1]
        del self.names[k - 1]
        cur = self.current
        if cur > k:
            cur -= 1
        cur = min(cur, self.n_configs)
        self.current = cur
        if system is not None:
            self.apply(system, cur)

    # -- cells ------------------------------------------------------------------
    def value(self, row: int, k: int):
        return self.rows[row].values[self._config(k) - 1]

    def set_value(self, system, row: int, k: int, value):
        """Set one cell (text is parsed as in the editor).  A cell of the current
        configuration is written into the lens at once."""
        r = self.rows[row]
        k = self._config(k)
        if system is not None and k != self.current:
            r._check(system)
        r.values[k - 1] = _parse_if_text(r, value)
        if system is not None and k == self.current:
            r.set(system, r.values[k - 1])

    # -- switching ----------------------------------------------------------------
    def capture(self, system):
        """Store the lens's values of every controlled parameter in the current configuration's column."""
        for r in self.rows:
            if r.type == "MOFF":
                continue
            try:
                r.values[self.current - 1] = r.get(system)
            except MultiConfigError:
                pass  # rows that refer to something missing keep their values (shown as errors in the editor)

    def apply(self, system, k: Optional[int] = None, solves: bool = True):
        """Load configuration ``k`` (default: the current one) into the lens, without storing the old values."""
        k = self._config(self.current if k is None else k)
        for r in self.rows:
            v = r.values[k - 1]
            if r.type == "MOFF" or (v is None and r.type != "SDIA"):
                continue
            try:
                r.set(system, v)
            except MultiConfigError:
                pass
        self.current = k
        if solves and getattr(system, "solves", None):
            from .optimize.solves import apply_solves
            apply_solves(system)

    def set_config(self, system, k: int):
        """Make configuration ``k`` the current one: store the lens's values, then load configuration ``k``."""
        k = self._config(k)
        self.capture(system)
        self.apply(system, k)

    # -- queries ----------------------------------------------------------------
    def controls(self, surface: int, param: str) -> bool:
        """True if some row sets the given surface parameter."""
        return any(r.controls(surface, param) for r in self.rows)

    def errors(self, system) -> List[Optional[str]]:
        """Per row: None, or why the row cannot be applied to the lens."""
        out = []
        for r in self.rows:
            try:
                r.get(system)
                out.append(None)
            except (MultiConfigError, AttributeError, IndexError) as e:
                out.append(str(e))
        return out

    def renumber_surfaces(self, fn: Callable[[int], Optional[int]]):
        """Apply ``fn(old) -> new or None (deleted)`` to surface references.  Rows on a deleted surface are
        removed; STPS values on a deleted surface move to ``fn(old + 1)`` or the surface before."""
        keep = []
        for r in self.rows:
            if r.ref_kind == "surface":
                n = fn(r.ref)
                if n is None:
                    continue
                r.ref = n
            elif r.type == "STPS":
                vals = []
                for v in r.values:
                    if v is None:
                        vals.append(v)
                        continue
                    n = fn(int(v))
                    j = int(v)
                    while n is None and j > 1:
                        j -= 1
                        n = fn(j)
                    vals.append(1 if n is None else n)
                r.values = vals
            keep.append(r)
        self.rows = keep

    def table(self, system=None) -> str:
        """Text listing of the table, one line per operand."""
        w = 14
        head = f"{'#':>3} {'Operand':22}" + "".join(
            f"{(('*' if k == self.current else '') + self.name(k))[:w]:>{w + 1}}" for k in self.configs)
        lines = [head]
        errs = self.errors(system) if system is not None else [None] * len(self.rows)
        for i, r in enumerate(self.rows):
            cells = "".join(f"{format_value(r, v)[:w]:>{w + 1}}" for v in r.values)
            lines.append(f"{i:>3} {r.label[:22]:22}{cells}" + (f"   ! {errs[i]}" if errs[i] else "")
                         + (f"   {r.comment}" if r.comment else ""))
        return "\n".join(lines)

    # -- serialisation -----------------------------------------------------------
    def to_dict(self) -> dict:
        return {"configs": self.n_configs, "current": self.current, "names": list(self.names),
                "rows": [r.to_dict() for r in self.rows]}

    @classmethod
    def from_dict(cls, d: dict) -> "MultiConfig":
        n = int(d.get("configs", len(d.get("names", [])) or 1))
        names = d.get("names") or [""] * n
        return cls(n, names, [MCRow.from_dict(r) for r in d.get("rows", [])], d.get("current", 1))

    def copy(self) -> "MultiConfig":
        return MultiConfig.from_dict(self.to_dict())

    def __repr__(self):
        return f"MultiConfig({self.n_configs} configurations, {len(self.rows)} operands, current {self.current})"


# ---------------------------------------------------------------------------
# Cell text (shared by the Qt editor and any other front end)
# ---------------------------------------------------------------------------

def parse_value(row: MCRow, text: str):
    """Interpret what was typed into a cell of ``row``."""
    t = row.type
    s = str(text).strip()
    if t == "MOFF":
        return None
    if t == "GLSS":
        return s or None
    if t == "SDIA" and s.lower() in ("", "auto", "automatic"):
        return None
    if t in ("STPS", "PRWV"):
        return int(float(s))
    if s.lower() in ("inf", "infinity", "+inf"):
        return math.inf
    if s.lower() in ("-inf", "-infinity"):
        return -math.inf
    return float(s)


def _parse_if_text(row, v):
    return parse_value(row, v) if isinstance(v, str) and row.type != "GLSS" else v


def format_value(row: MCRow, v) -> str:
    """Cell text for a value."""
    if row.type == "MOFF":
        return ""
    if v is None:
        return "auto" if row.type == "SDIA" else ""
    if row.type == "GLSS":
        if isinstance(v, dict) and "model" in v:
            return ",".join(f"{x:g}" for x in v["model"][:2])
        return str(v)
    if isinstance(v, float):
        if math.isinf(v):
            return "Infinity" if v > 0 else "-Infinity"
        return f"{v:.10g}"
    return str(v)


def multiconfig(system) -> Optional[MultiConfig]:
    """The lens's multi-configuration table, or None."""
    return getattr(system, "multiconfig", None)


def config_systems(system) -> list:
    """One copy of the lens per configuration (just ``[copy]`` for a lens without a table)."""
    mc = multiconfig(system)
    if mc is None:
        return [system.copy()]
    return [system.config_copy(k) for k in mc.configs]
