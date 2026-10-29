"""Optical materials: dispersion formulas, glass catalogs and material lookup.

Wavelengths are always in micrometres. Indices are relative to air (air = 1.0),
which matches the default behaviour of commercial sequential design codes.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, Optional, Sequence, Union

import numpy as np

# Fraunhofer reference lines (micrometres)
LAMBDA_d = 0.5875618
LAMBDA_F = 0.4861327
LAMBDA_C = 0.6562725
LAMBDA_e = 0.5460740
LAMBDA_g = 0.4358343


# ---------------------------------------------------------------------------
# Dispersion formulas.  Each takes (wavelength_um ndarray, coefficients) and
# returns the refractive index.  Numbering follows the Zemax AGF convention so
# AGF catalogs can be loaded directly.
# ---------------------------------------------------------------------------

def _schott(w, c):
    w2 = w * w
    n2 = c[0] + c[1] * w2 + c[2] / w2 + c[3] / w2**2 + c[4] / w2**3 + c[5] / w2**4
    return np.sqrt(n2)


def _sellmeier_terms(w, ks, ls, const=1.0):
    w2 = w * w
    n2 = const + sum(k * w2 / (w2 - l) for k, l in zip(ks, ls))
    return np.sqrt(n2)


def _sellmeier1(w, c):
    return _sellmeier_terms(w, c[0:6:2], c[1:6:2])


def _herzberger(w, c):
    w2 = w * w
    L = 1.0 / (w2 - 0.028)
    return c[0] + c[1] * L + c[2] * L * L + c[3] * w2 + c[4] * w2**2 + c[5] * w2**3


def _sellmeier2(w, c):
    w2 = w * w
    return np.sqrt(1.0 + c[0] + c[1] * w2 / (w2 - c[2] ** 2) + c[3] / (w2 - c[4] ** 2))


def _conrady(w, c):
    return c[0] + c[1] / w + c[2] / w**3.5


def _sellmeier3(w, c):
    return _sellmeier_terms(w, c[0:8:2], c[1:8:2])


def _handbook1(w, c):
    w2 = w * w
    return np.sqrt(c[0] + c[1] / (w2 - c[2]) - c[3] * w2)


def _handbook2(w, c):
    w2 = w * w
    return np.sqrt(c[0] + c[1] * w2 / (w2 - c[2]) - c[3] * w2)


def _sellmeier4(w, c):
    w2 = w * w
    return np.sqrt(c[0] + c[1] * w2 / (w2 - c[2]) + c[3] * w2 / (w2 - c[4]))


def _extended(w, c):
    w2 = w * w
    n2 = c[0] + c[1] * w2 + sum(c[i] / w2 ** (i - 1) for i in range(2, 8))
    return np.sqrt(n2)


def _sellmeier5(w, c):
    return _sellmeier_terms(w, c[0:10:2], c[1:10:2])


def _extended2(w, c):
    w2 = w * w
    n2 = (c[0] + c[1] * w2 + c[2] / w2 + c[3] / w2**2 + c[4] / w2**3 + c[5] / w2**4
          + c[6] * w2**2 + c[7] * w2**3)
    return np.sqrt(n2)


def _extended3(w, c):
    w2 = w * w
    n2 = (c[0] + c[1] * w2 + c[2] * w2**2 + c[3] / w2 + c[4] / w2**2 + c[5] / w2**3
          + c[6] / w2**4 + c[7] / w2**5 + c[8] / w2**6)
    return np.sqrt(n2)


def _cauchy(w, c):
    """n = A + B/w^2 + C/w^4 (not an AGF formula; used for model glasses)."""
    return c[0] + c[1] / w**2 + c[2] / w**4


FORMULAS: Dict[int, Callable] = {
    1: _schott,
    2: _sellmeier1,
    3: _herzberger,
    4: _sellmeier2,
    5: _conrady,
    6: _sellmeier3,
    7: _handbook1,
    8: _handbook2,
    9: _sellmeier4,
    10: _extended,
    11: _sellmeier5,
    12: _extended2,
    13: _extended3,
}

FORMULA_NAMES = {
    "schott": 1, "sellmeier1": 2, "herzberger": 3, "sellmeier2": 4, "conrady": 5,
    "sellmeier3": 6, "handbook1": 7, "handbook2": 8, "sellmeier4": 9, "extended": 10,
    "sellmeier5": 11, "extended2": 12, "extended3": 13,
}


# ---------------------------------------------------------------------------
# Material classes
# ---------------------------------------------------------------------------

class Material:
    """Base class.  Subclasses implement :meth:`index`."""


    def index(self, wavelength_um):
        raise NotImplementedError

    # Convenience properties -------------------------------------------------
    @property
    def nd(self) -> float:
        return float(self.index(LAMBDA_d))

    @property
    def vd(self) -> float:
        nd, nf, nc = (float(self.index(w)) for w in (LAMBDA_d, LAMBDA_F, LAMBDA_C))
        return (nd - 1.0) / (nf - nc) if nf != nc else math.inf

    @property
    def is_mirror(self) -> bool:
        return False

    def to_spec(self) -> str:
        return self.name

    def __repr__(self):
        return f"{type(self).__name__}({self.name!r})"


class ConstantIndex(Material):
    def __init__(self, n: float, name: Optional[str] = None):
        self.n = float(n)
        self.name = name or (f"{self.n:.6g}" if self.n != 1.0 else "AIR")

    def index(self, wavelength_um):
        return np.full_like(np.asarray(wavelength_um, dtype=float), self.n) if np.ndim(wavelength_um) else self.n

    def to_spec(self):
        return self.name if self.name in ("AIR", "VACUUM") else self.n


AIR = ConstantIndex(1.0, "AIR")


class Mirror(Material):
    """Marker material: the surface reflects; the medium after it is the medium before it."""

    name = "MIRROR"

    def index(self, wavelength_um):  # pragma: no cover - never called directly
        raise TypeError("MIRROR has no index; use the medium preceding the mirror")

    @property
    def is_mirror(self):
        return True


MIRROR = Mirror()


@dataclass(eq=False)
class Glass(Material):
    """A catalog glass defined by a dispersion formula."""

    name: str
    formula: int
    coefficients: Sequence[float]
    catalog: str = ""
    nd_catalog: Optional[float] = None
    vd_catalog: Optional[float] = None
    wavelength_range: tuple = (0.0, math.inf)
    extra: dict = field(default_factory=dict)

    def __post_init__(self):
        self.coefficients = tuple(float(c) for c in self.coefficients)
        if self.formula not in FORMULAS:
            raise ValueError(f"Unsupported dispersion formula {self.formula} for {self.name}")
        self._fn = FORMULAS[self.formula]

    def index(self, wavelength_um):
        w = np.asarray(wavelength_um, dtype=float)
        with np.errstate(invalid="ignore"):  # NaN far outside the data range (e.g. germanium in the visible)
            n = self._fn(w, self.coefficients)
        return float(n) if n.ndim == 0 else n

    def __repr__(self):
        return f"Glass({self.name!r}, catalog={self.catalog!r})"


class ModelGlass(Material):
    """A glass defined only by nd, Vd (and optional partial dispersion offset).

    Uses a Cauchy form n = A + B/w^2 + C/w^4 fitted exactly through nd and Vd,
    with C fixed so the partial dispersion follows a normal-glass line.  This is
    smooth in nd/Vd, which makes it suitable as an optimisation variable.
    """

    def __init__(self, nd: float, vd: float, dpgf: float = 0.0, name: Optional[str] = None):
        self.nd_value = float(nd)
        self.vd_value = float(vd)
        self.dpgf = float(dpgf)
        self.name = name or f"MODEL({self.nd_value:.5f},{self.vd_value:.2f})"
        self._fit()

    def _fit(self):
        nd, vd = self.nd_value, self.vd_value
        dn = (nd - 1.0) / vd  # nF - nC
        # Normal line for P_gF ~ 0.6438 - 0.001682*vd (Schott normal-line glasses)
        pgf = 0.6438 - 0.001682 * vd + self.dpgf
        dg = pgf * dn  # ng - nF
        # Solve for A,B,C:  n(w) = A + B x + C x^2 with x = 1/w^2
        xs = [1 / LAMBDA_d**2, 1 / LAMBDA_F**2, 1 / LAMBDA_C**2, 1 / LAMBDA_g**2]
        M = np.array([[1, xs[0], xs[0] ** 2],
                      [0, xs[1] - xs[2], xs[1] ** 2 - xs[2] ** 2],
                      [0, xs[3] - xs[1], xs[3] ** 2 - xs[1] ** 2]])
        self.coefficients = np.linalg.solve(M, [nd, dn, dg])

    def index(self, wavelength_um):
        w = np.asarray(wavelength_um, dtype=float)
        n = _cauchy(w, self.coefficients)
        return float(n) if n.ndim == 0 else n

    def to_spec(self):
        return {"model": [self.nd_value, self.vd_value, self.dpgf]}


class TabulatedMaterial(Material):
    """Index given as a table of (wavelength, n); cubic-ish interpolation via np.interp."""

    def __init__(self, name: str, wavelengths: Sequence[float], indices: Sequence[float]):
        self.name = name
        order = np.argsort(wavelengths)
        self.w = np.asarray(wavelengths, float)[order]
        self.n = np.asarray(indices, float)[order]

    def index(self, wavelength_um):
        n = np.interp(wavelength_um, self.w, self.n)
        return float(n) if np.ndim(n) == 0 else n


# ---------------------------------------------------------------------------
# Catalogs
# ---------------------------------------------------------------------------

class GlassCatalog:
    """A named collection of glasses."""

    def __init__(self, name: str, glasses: Iterable[Glass] = ()):
        self.name = name
        self.glasses: Dict[str, Material] = {}
        for g in glasses:
            self.add(g)

    def add(self, glass: Material):
        self.glasses[glass.name.upper()] = glass

    def get(self, name: str) -> Optional[Material]:
        return self.glasses.get(name.upper())

    def __contains__(self, name):
        return name.upper() in self.glasses

    def __len__(self):
        return len(self.glasses)

    def __iter__(self):
        return iter(self.glasses.values())

    def names(self):
        return list(self.glasses)


def load_agf(path_or_text: str, name: Optional[str] = None) -> GlassCatalog:
    """Load a Zemax AGF glass catalog from a file path or the file's text.

    Handles UTF-8 / UTF-16 encodings.  Thermal (TD) data is stored in
    ``glass.extra`` but not yet applied.
    """
    text = path_or_text
    if "\n" not in path_or_text and not path_or_text.lstrip().startswith("NM"):
        raw = open(path_or_text, "rb").read()
        if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
            text = raw.decode("utf-16")
        else:
            try:
                text = raw.decode("utf-8-sig")
            except UnicodeDecodeError:
                text = raw.decode("latin-1")
        if name is None:
            import os
            name = os.path.splitext(os.path.basename(path_or_text))[0].upper()
    cat = GlassCatalog(name or "AGF")
    cur = None
    for line in text.splitlines():
        parts = line.split()
        if not parts:
            continue
        key = parts[0]
        if key == "NM":
            if cur:
                _finish_agf_glass(cat, cur)
            cur = {"name": parts[1], "formula": int(float(parts[2])),
                   "nd": float(parts[4]) if len(parts) > 4 else None,
                   "vd": float(parts[5]) if len(parts) > 5 else None,
                   "cd": [], "ld": None, "td": None}
        elif cur is None:
            continue
        elif key == "CD":
            cur["cd"] = [float(x) for x in parts[1:]]
        elif key == "LD":
            cur["ld"] = (float(parts[1]), float(parts[2]))
        elif key == "TD":
            cur["td"] = [float(x) for x in parts[1:]]
    if cur:
        _finish_agf_glass(cat, cur)
    return cat


def _finish_agf_glass(cat, cur):
    try:
        g = Glass(cur["name"], cur["formula"], cur["cd"] + [0.0] * 10, catalog=cat.name,
                  nd_catalog=cur["nd"], vd_catalog=cur["vd"],
                  wavelength_range=cur["ld"] or (0.0, math.inf),
                  extra={"td": cur["td"]} if cur["td"] else {})
    except ValueError:
        return  # unsupported formula, skip
    cat.add(g)


class MaterialLibrary:
    """Resolves material specifications to :class:`Material` objects.

    Accepted specs: ``None``/"" / "AIR" (air), "MIRROR", a glass name found in
    any loaded catalog, ``"CATALOG:NAME"``, a number (constant index),
    a string "1.5168,64.17" (model glass), a dict ``{"model": [nd, vd, dpgf]}``,
    or a :class:`Material` instance.
    """

    def __init__(self, catalogs: Iterable[GlassCatalog] = ()):
        self.catalogs: Dict[str, GlassCatalog] = {}
        for c in catalogs:
            self.add_catalog(c)

    def add_catalog(self, catalog: GlassCatalog):
        self.catalogs[catalog.name.upper()] = catalog

    def load_agf(self, path: str, name: Optional[str] = None) -> GlassCatalog:
        cat = load_agf(path, name)
        self.add_catalog(cat)
        return cat

    def find(self, name: str) -> Optional[Material]:
        if ":" in name:
            cname, gname = name.split(":", 1)
            cat = self.catalogs.get(cname.upper())
            return cat.get(gname) if cat else None
        for cat in self.catalogs.values():
            g = cat.get(name)
            if g is not None:
                return g
        return None

    def resolve(self, spec) -> Material:
        if isinstance(spec, Material):
            return spec
        if spec is None:
            return AIR
        if isinstance(spec, (int, float)):
            return AIR if spec == 1.0 else ConstantIndex(spec)
        if isinstance(spec, dict) and "model" in spec:
            return ModelGlass(*spec["model"])
        if isinstance(spec, str):
            s = spec.strip()
            u = s.upper()
            if u in ("", "AIR", "VACUUM"):
                return AIR
            if u == "MIRROR":
                return MIRROR
            m = re.fullmatch(r"\s*([0-9.]+)\s*,\s*([0-9.]+)\s*(?:,\s*(-?[0-9.]+))?\s*", s)
            if m:
                return ModelGlass(float(m.group(1)), float(m.group(2)), float(m.group(3) or 0))
            try:
                return ConstantIndex(float(s))
            except ValueError:
                pass
            g = self.find(s)
            if g is not None:
                return g
            raise KeyError(f"Unknown material {spec!r}")
        raise TypeError(f"Cannot interpret material spec {spec!r}")

    def all_glasses(self):
        for cat in self.catalogs.values():
            yield from cat


def default_library() -> MaterialLibrary:
    from .glass_data import builtin_catalogs
    return MaterialLibrary(builtin_catalogs())
