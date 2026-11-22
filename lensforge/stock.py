"""Stock (catalog) lenses: import vendor catalogs, search them by properties, insert a part.

Lens makers publish their stock lenses as Zemax files: one ``.zmx`` prescription per part
(Thorlabs, Edmund Optics, Newport and others, on each product page) and whole catalogs in
Zemax's ``.ZMF`` format (OpticStudio ships them; some makers offer them for download).
This module reads both into a :class:`StockLibrary` you can search and insert from::

    import lensforge as lf

    lib = lf.StockLibrary.default()          # demo parts + the catalogs you imported before
    lib.import_file("THORLABS.ZMF")          # a whole catalog (or a single part's .zmx)
    lib.save()                               # remembered for scripts and both apps
    hits = lib.search(vendor="thorlabs", kind="plano-convex", efl=(45, 55),
                      diameter=(20, 30), glass="N-BK7")
    lens = lf.samples.singlet()
    lf.insert_stock_lens(lens, hits[0], at=3, reverse=True)
    lens.surfaces[3].comment                 # 'LA1131 (Thorlabs)'

The first and last inserted surfaces carry a comment naming the part. Vendor data is not
bundled with lensforge (it is the makers' copyright); only a few generic demo parts are.
"""

from __future__ import annotations

import json
import math
import os
import re
import struct
from dataclasses import asdict, dataclass, field
from typing import Iterable, List, Optional, Sequence, Tuple, Union

from . import surfaces as S

DEMO_CATALOG = "LensForge Demo"

#: materials stock-lens files often name that lensforge's catalogs know under another name
#: (or not at all: then a model glass with the maker's nd, vd)
EQUIVALENTS = {
    "BK7": "N-BK7", "C79-80": "F_SILICA", "C7980": "F_SILICA", "CORNING7980": "F_SILICA", "UVFS": "F_SILICA",
    "FUSEDSILICA": "F_SILICA", "FUSED_SILICA": "F_SILICA", "SILICA": "F_SILICA", "B270": "1.5230,58.5",
    "CAF2": "CAF2", "CALCIUMFLUORIDE": "CAF2", "MGF2": "MGF2", "SAPPHIRE": "SAPPHIRE", "ZNSE": "ZNSE",
    "GE": "GERMANIUM", "SI": "SILICON",
}
_AIR = (None, "", "AIR")

# ---------------------------------------------------------------------------
# .ZMF catalog files
# ---------------------------------------------------------------------------
# Layout (little-endian): int32 format version (1001), then per lens a 160-byte header
#   char name[100]; uint32 version, elements, shape, aspheric, grin, toroidal, text_length;
#   double efl, epd
# followed by text_length bytes of the lens's .zmx text, XOR-masked with a key stream that
# depends on efl and epd (the same operation masks and unmasks).
_ZMF_HEAD = struct.Struct("<100s7I2d")
_ZMF_SHAPES = "?EBPM"  # unknown, equi-, bi-, plano-, meniscus


def _zmf_key_slow(k: float) -> int:
    return int(f"{k:.8e}"[4:7]) & 0xFF


def _zmf_mask(data: bytes, efl: float, epd: float) -> bytes:
    """XOR ``data`` with the ZMF key stream (byte p: digits 4..6 of ``'%.8e' % k_p``)."""
    import numpy as np
    n = len(data)
    if not n:
        return b""
    iv = math.cos(6 * efl + 3 * epd)
    iv = math.cos(655 * (math.pi / 180) * iv) + iv
    p = np.arange(n, dtype=float)
    k = 13.2 * (iv + np.sin(17 * (p + 3))) * (p + 1)
    # digits of the 9-digit mantissa that '%.8e' prints, vectorised; values whose rounding is
    # in doubt (close to a half) are formatted exactly
    a = np.abs(k)
    with np.errstate(divide="ignore", invalid="ignore"):
        e = np.floor(np.log10(np.where(a > 0, a, 1.0)))
        m = a / 10.0 ** e * 1e8
    mi = np.rint(m)
    mi = np.where(mi >= 1e9, np.rint(m / 10), mi)
    mi = np.where(mi < 1e8, np.rint(m * 10), mi)
    neg = k < 0
    key = np.where(neg, (mi // 1e4) % 1000, (mi // 1e3) % 1000).astype(np.int64)
    frac = np.abs(m - np.floor(m) - 0.5)
    doubt = np.nonzero((frac < 1e-3) | (m < 1.0001e8) | (m > 9.9998e8) | (a == 0))[0]
    for i in doubt:
        key[i] = int(f"{k[i]:.8e}"[4:7])
    out = np.frombuffer(bytes(data), dtype=np.uint8) ^ (key & 0xFF).astype(np.uint8)
    return out.tobytes()


def read_zmf(data: Union[str, bytes], catalog: Optional[str] = None) -> List["StockLens"]:
    """The lenses in a Zemax ``.ZMF`` lens catalog (a path or the file's bytes)."""
    if isinstance(data, str):
        catalog = catalog or os.path.splitext(os.path.basename(data))[0]
        with open(data, "rb") as f:
            data = f.read()
    catalog = catalog or "ZMF"
    if len(data) < 4:
        raise ValueError("not a ZMF lens catalog (file too short)")
    (fmt,) = struct.unpack_from("<I", data, 0)
    if fmt != 1001:
        raise ValueError(f"not a ZMF lens catalog (format {fmt}, expected 1001)")
    pos, out = 4, []
    while pos + _ZMF_HEAD.size <= len(data):
        name, ver, elements, shape, asph, grin, toric, n, efl, epd = _ZMF_HEAD.unpack_from(data, pos)
        pos += _ZMF_HEAD.size
        if pos + n > len(data):
            raise ValueError(f"ZMF catalog truncated in lens {len(out) + 1}")
        text = _zmf_mask(data[pos:pos + n], efl, epd).decode("latin-1")
        pos += n
        part = name.split(b"\0", 1)[0].decode("latin-1").strip()
        lens = StockLens.from_zmx(text, part=part, vendor=vendor_name(catalog), catalog=catalog,
                                  efl=efl, elements=elements)
        if not lens.shape and 0 < shape < len(_ZMF_SHAPES):
            lens.shape = _ZMF_SHAPES[shape]
        lens.aspheric = lens.aspheric or bool(asph)
        lens.grin = bool(grin)
        lens.toroidal = lens.toroidal or bool(toric)
        if not lens.diameter and epd > 0:
            lens.diameter = float(epd)
        out.append(lens)
    return out


def write_zmf(path: str, lenses: Sequence["StockLens"]):
    """Write ``lenses`` as a ``.ZMF`` catalog (for exchanging catalogs and for tests)."""
    blob = bytearray(struct.pack("<I", 1001))
    for s in lenses:
        text = s.zmx.encode("latin-1", "replace")
        vers = re.match(r"VERS\s+(\d+)", s.zmx)
        efl = s.efl if math.isfinite(s.efl) else 0.0
        epd = s.diameter or 0.0
        blob += _ZMF_HEAD.pack(s.part.encode("latin-1", "replace")[:99], int(vers.group(1)) if vers else 0,
                               s.elements, max(0, _ZMF_SHAPES.find(s.shape or "?")), int(s.aspheric),
                               int(s.grin), int(s.toroidal), len(text), efl, epd)
        blob += _zmf_mask(text, efl, epd)
    with open(path, "wb") as f:
        f.write(bytes(blob))


def vendor_name(catalog: str) -> str:
    """A catalog file's stem as a maker's name: 'THORLABS' -> 'Thorlabs', 'EDMUND OPTICS' -> 'Edmund Optics'."""
    c = re.sub(r"[_]+", " ", catalog or "").strip()
    return c.title() if c.isupper() or c.islower() else c


# ---------------------------------------------------------------------------
# One stock lens
# ---------------------------------------------------------------------------

KINDS = ("plano-convex", "plano-concave", "bi-convex", "bi-concave", "positive meniscus", "negative meniscus",
         "cemented doublet", "air-spaced doublet", "cemented triplet", "multi-element", "window", "other")


@dataclass
class StockLens:
    """A catalog part: its prescription (Zemax text) and the properties a search uses."""
    part: str
    vendor: str = ""
    catalog: str = ""
    zmx: str = ""
    description: str = ""
    efl: float = math.nan          # effective focal length, lens units
    diameter: float = 0.0          # largest clear diameter of the element surfaces
    thickness: float = 0.0         # first to last element surface (centre)
    elements: int = 0
    shape: str = ""                # Zemax shape letter: E equi-, B bi-, P plano-, M meniscus
    kind: str = ""                 # one of KINDS
    glasses: List[str] = field(default_factory=list)
    aspheric: bool = False
    grin: bool = False
    toroidal: bool = False
    units: str = "mm"
    unsupported: List[str] = field(default_factory=list)   # surface types lensforge imports as STANDARD
    glass_data: dict = field(default_factory=dict)          # glass -> [nd, vd] from the maker's file

    @property
    def key(self) -> str:
        """Unique within a library: 'catalog:part'."""
        return f"{self.catalog}:{self.part}"

    @property
    def label(self) -> str:
        """'LA1131 (Thorlabs)': the comment the inserted surfaces get."""
        return f"{self.part} ({self.vendor})" if self.vendor else self.part

    def system(self, library=None, substitute_missing: bool = False):
        """The part as an :class:`~lensforge.OpticalSystem` (as the maker's file describes it).

        With ``substitute_missing`` a glass that is in none of ``library``'s catalogs is
        replaced by a model glass with the maker's nd and vd (see :meth:`missing_glasses`)."""
        from .io.zmx import load_zmx
        s = load_zmx(self.zmx if "\n" in self.zmx else self.zmx + "\n", library)
        if not s.name:
            s.name = self.label
        if substitute_missing:
            subs = self.missing_glasses(s.library)
            for x in s.surfaces:
                if x.material in subs and subs[x.material]:
                    x.material = subs[x.material]
        return s

    def missing_glasses(self, library=None) -> dict:
        """Glasses of the part that ``library`` (default: the shared one) cannot resolve:
        {name: substitute}. The substitute is a common equivalent (:data:`EQUIVALENTS`, e.g.
        Corning C79-80 -> F_SILICA), else a model glass 'nd,vd' with the maker's nd and vd,
        or None when the file has no data for it."""
        from .system import shared_library
        lib = library or shared_library()
        out = {}
        for g in self.glasses:
            try:
                lib.resolve(g)
                continue
            except Exception:
                pass
            sub = EQUIVALENTS.get(g.upper().replace(" ", ""))
            if sub:
                try:
                    lib.resolve(sub)
                except Exception:
                    sub = None
            d = self.glass_data.get(g)
            if not sub and d and d[0] > 1 and d != [1.5, 40.0]:
                sub = f"{d[0]:.6g},{d[1]:.6g}"
            out[g] = sub
        return out

    def element_range(self, system=None) -> Tuple[int, int]:
        """First and last surface of the glass (the element surfaces, without the maker's
        object, stop or image dummies)."""
        s = system or self.system()
        return _element_range(s)

    def to_dict(self) -> dict:
        d = asdict(self)
        if not math.isfinite(d["efl"]):
            d["efl"] = None
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "StockLens":
        d = dict(d)
        d["efl"] = math.nan if d.get("efl") is None else float(d["efl"])
        known = cls.__dataclass_fields__
        return cls(**{k: v for k, v in d.items() if k in known})

    @classmethod
    def from_zmx(cls, text: str, part: str = "", vendor: str = "", catalog: str = "", efl: float = None,
                 elements: int = None, library=None) -> "StockLens":
        """Properties from a part's ``.zmx`` text. ``efl`` is computed by a paraxial trace
        unless given (ZMF headers carry it)."""
        from .io.zmx import load_zmx
        s = load_zmx(text if "\n" in text else text + "\n", library)
        gdata = _glass_data(text)
        unsupported = sorted(set(re.findall(r"surface type (\S+)", s.notes or "")))
        first, last = _element_range(s)
        surfs = s.surfaces[first:last + 1]
        glasses = []
        for x in surfs:
            if x.material not in _AIR and str(x.material).upper() not in ("AIR", "MIRROR"):
                if x.material not in glasses:
                    glasses.append(str(x.material))
        n_el = sum(1 for x in surfs[:-1] if x.material not in _AIR and str(x.material).upper() != "AIR")
        sds = [x.semi_diameter for x in surfs if x.semi_diameter]
        lens = cls(part=part or s.name or "part", vendor=vendor, catalog=catalog or vendor or "Imported",
                   zmx=text, description=_description(text, s.name, part),
                   diameter=2 * max(sds) if sds else 0.0,
                   thickness=sum(x.thickness for x in surfs[:-1] if math.isfinite(x.thickness)),
                   elements=elements if elements else n_el, glasses=glasses, units=s.units,
                   aspheric=any(x.kind in ("EVENASPH", "ODDASPH") or getattr(x, "conic", 0.0) for x in surfs),
                   toroidal=any(x.kind == "TOROIDAL" for x in surfs), unsupported=unsupported,
                   glass_data={g: gdata[g] for g in glasses if g in gdata})
        if efl is None or not math.isfinite(efl) or efl == 0:
            subs = lens.missing_glasses(s.library)
            for x in s.surfaces:
                if subs.get(x.material):
                    x.material = subs[x.material]
            efl = _paraxial_efl(s, first, last)
        lens.efl = float(efl)
        lens.shape, lens.kind = _classify(surfs, lens.efl, n_el)
        return lens


def _description(text, name, part):
    m = re.search(r"^NOTE\s+\d+\s+(.+)$", text, re.M)
    d = name if name and name != part else ""
    if m and m.group(1).strip():
        d = (d + " " + m.group(1).strip()).strip()
    return d


def _glass_data(text) -> dict:
    """{glass: [nd, vd]} from the .zmx GLAS lines (name, then 3 fields, then nd and vd)."""
    out = {}
    for m in re.finditer(r"^\s+GLAS\s+(\S+)\s+\S+\s+\S+\s+(\S+)\s+(\S+)", text, re.M):
        try:
            out[m.group(1)] = [float(m.group(2)), float(m.group(3))]
        except ValueError:
            pass
    return out


def _element_range(s) -> Tuple[int, int]:
    glass = [i for i in range(1, s.image_index)
             if s.surfaces[i].material not in _AIR and str(s.surfaces[i].material).upper() != "AIR"]
    if not glass:
        n = s.image_index - 1
        if n < 1:
            raise ValueError("the lens has no surfaces between object and image")
        return 1, n
    return glass[0], min(glass[-1] + 1, s.image_index - 1)


def _paraxial_efl(s, first, last) -> float:
    from .system import OpticalSystem
    try:
        t = OpticalSystem("efl", s.units, s.library)
        t.wavelengths = s.wavelengths
        t.primary_wavelength = s.primary_wavelength
        for i, x in enumerate(s.surfaces[first:last + 1]):
            c = x.copy()
            c.stop = i == 0
            c.semi_diameter = None
            t.insert(t.image_index, c)
        t.set_aperture("EPD", 1.0)
        f = t.paraxial().efl
        return float(f) if math.isfinite(f) and abs(f) < 1e12 else math.inf
    except Exception:
        return math.nan


def _group_bfd(system, rng) -> float:
    """Paraxial back focal distance of surfaces ``rng`` of ``system`` on their own (object at infinity)."""
    from .system import OpticalSystem
    try:
        t = OpticalSystem("bfd", system.units, system.library)
        t.wavelengths = system.wavelengths
        t.primary_wavelength = system.primary_wavelength
        for k, i in enumerate(rng):
            c = system.surfaces[i].copy()
            c.stop = k == 0
            c.semi_diameter = None
            t.insert(t.image_index, c)
        t.set_aperture("EPD", 1.0)
        f = float(t.paraxial().bfl)
        return round(f, 6) if abs(f) < 1e9 else math.nan
    except Exception:
        return math.nan


def _classify(surfs, efl, n_el) -> Tuple[str, str]:
    if n_el == 1 and len(surfs) == 2:
        c1, c2 = (getattr(x, "curvature", 0.0) for x in surfs)
        tol = 1e-9
        if abs(c1) < tol and abs(c2) < tol:
            return "P", "window"
        pos = efl > 0 if math.isfinite(efl) else (c1 - c2) > 0
        if abs(c1) < tol or abs(c2) < tol:
            return "P", "plano-convex" if pos else "plano-concave"
        if c1 * c2 > 0:
            return "M", "positive meniscus" if pos else "negative meniscus"
        shape = "E" if abs(abs(c1) - abs(c2)) <= 1e-6 * max(abs(c1), abs(c2)) else "B"
        return shape, "bi-convex" if pos else "bi-concave"
    cemented = all(x.material not in _AIR and str(x.material).upper() != "AIR" for x in surfs[:-1])
    if n_el == 2:
        return "", "cemented doublet" if cemented else "air-spaced doublet"
    if n_el == 3 and cemented:
        return "", "cemented triplet"
    return "", "multi-element" if n_el > 1 else "other"


# ---------------------------------------------------------------------------
# A searchable collection of catalogs
# ---------------------------------------------------------------------------

def user_library_path() -> str:
    """Where :meth:`StockLibrary.save` keeps imported catalogs: ``$LENSFORGE_HOME/stock_lenses.json``
    (default ``~/.lensforge``). The desktop app and scripts share it."""
    home = os.environ.get("LENSFORGE_HOME") or os.path.join(os.path.expanduser("~"), ".lensforge")
    return os.path.join(home, "stock_lenses.json")


def _rng(v) -> Optional[Tuple[float, float]]:
    """A search range: None, a (min, max) pair (either may be None), or one number (+-5 %)."""
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        d = abs(v) * 0.05
        return (v - d, v + d)
    lo, hi = v
    return (-math.inf if lo is None or lo == "" else float(lo), math.inf if hi is None or hi == "" else float(hi))


class StockLibrary:
    """Stock lenses from any number of catalogs, searchable by properties."""

    def __init__(self, lenses: Iterable[StockLens] = (), path: Optional[str] = None):
        self.lenses: List[StockLens] = []
        self.path = path
        self.add(lenses)

    # -- building
    @classmethod
    def default(cls, path: Optional[str] = None, demo: bool = True) -> "StockLibrary":
        """The demo parts plus the catalogs saved at ``path`` (default :func:`user_library_path`)."""
        lib = cls(demo_lenses() if demo else (), path=path or user_library_path())
        if os.path.exists(lib.path):
            lib.load(lib.path)
        return lib

    def add(self, lenses: Iterable[StockLens], replace: bool = True) -> int:
        idx = {x.key: i for i, x in enumerate(self.lenses)}
        n = 0
        for x in lenses:
            if x.key in idx:
                if replace:
                    self.lenses[idx[x.key]] = x
            else:
                idx[x.key] = len(self.lenses)
                self.lenses.append(x)
            n += 1
        return n

    def import_file(self, path: str, vendor: str = None, catalog: str = None, part: str = None) -> List[StockLens]:
        """Add a ``.ZMF`` catalog or one part's ``.zmx`` file; returns the lenses added."""
        with open(path, "rb") as f:
            data = f.read()
        return self.import_data(os.path.basename(path), data, vendor, catalog, part)

    def import_data(self, filename: str, data: bytes, vendor: str = None, catalog: str = None,
                    part: str = None) -> List[StockLens]:
        """As :meth:`import_file`, from a file's name and bytes (the web app's upload)."""
        stem = os.path.splitext(os.path.basename(filename))[0]
        if filename.lower().endswith(".zmf"):
            lenses = read_zmf(bytes(data), catalog or stem)
            if vendor:
                for x in lenses:
                    x.vendor = vendor
        else:
            text = _decode(bytes(data))
            vendor = vendor or _guess_vendor(text) or ""
            lenses = [StockLens.from_zmx(text, part=part or _guess_part(text, stem), vendor=vendor,
                                         catalog=catalog or vendor or "Imported")]
        self.add(lenses)
        return lenses

    def remove_catalog(self, catalog: str) -> int:
        n = len(self.lenses)
        self.lenses = [x for x in self.lenses if x.catalog != catalog]
        return n - len(self.lenses)

    @property
    def catalogs(self) -> List[str]:
        return sorted({x.catalog for x in self.lenses}, key=str.lower)

    @property
    def vendors(self) -> List[str]:
        return sorted({x.vendor for x in self.lenses if x.vendor}, key=str.lower)

    def get(self, key_or_part: str) -> StockLens:
        """A lens by key ('catalog:part') or part number (first match, case-insensitive)."""
        for x in self.lenses:
            if x.key == key_or_part:
                return x
        k = key_or_part.lower()
        for x in self.lenses:
            if x.part.lower() == k:
                return x
        raise KeyError(f"no stock lens {key_or_part!r}")

    # -- saving
    def to_dict(self, catalogs: Optional[Sequence[str]] = None) -> dict:
        keep = [x for x in self.lenses if x.catalog != DEMO_CATALOG and (catalogs is None or x.catalog in catalogs)]
        return {"format": "lensforge-stock", "version": 1, "lenses": [x.to_dict() for x in keep]}

    def load_dict(self, d: dict) -> int:
        return self.add(StockLens.from_dict(x) for x in d.get("lenses", []))

    def save(self, path: Optional[str] = None):
        """Write the imported catalogs (not the demo parts) as JSON."""
        path = path or self.path or user_library_path()
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f)
        self.path = path

    def load(self, path: str) -> int:
        with open(path, encoding="utf-8") as f:
            return self.load_dict(json.load(f))

    # -- searching
    def search(self, text: str = None, vendor: str = None, catalog: str = None, kind: str = None,
               efl=None, diameter=None, thickness=None, elements=None, glass: str = None,
               aspheric: Optional[bool] = None, positive: Optional[bool] = None,
               sort: str = "efl", limit: Optional[int] = None) -> List[StockLens]:
        """Lenses matching every criterion given.

        ``text`` matches part number or description, ``vendor``/``catalog``/``glass`` match
        case-insensitive substrings, ``kind`` one of :data:`KINDS` (substring, so 'meniscus'
        finds both), ``efl``/``diameter``/``thickness`` take a (min, max) pair (either None) or
        one number (+-5 %), ``elements`` a count or (min, max), ``positive`` the sign of the
        focal length. ``sort`` is a property name ('efl', 'diameter', 'part', ...); with an
        ``efl`` target the closest focal length comes first.
        """
        lo = lambda v: (v or "").lower()  # noqa: E731
        rs = {k: _rng(v) for k, v in (("efl", efl), ("diameter", diameter), ("thickness", thickness))}
        el = _rng(elements) if not isinstance(elements, int) else (elements, elements)
        out = []
        for x in self.lenses:
            if text and lo(text) not in lo(x.part) and lo(text) not in lo(x.description):
                continue
            if vendor and lo(vendor) not in lo(x.vendor):
                continue
            if catalog and lo(catalog) != lo(x.catalog):
                continue
            if kind and lo(kind) not in lo(x.kind):
                continue
            if glass and not any(lo(glass) in lo(g) for g in x.glasses):
                continue
            if aspheric is not None and bool(x.aspheric) != bool(aspheric):
                continue
            if positive is not None and (not math.isfinite(x.efl) or (x.efl > 0) != bool(positive)):
                continue
            if el and not el[0] <= x.elements <= el[1]:
                continue
            ok = True
            for k, r in rs.items():
                v = getattr(x, k)
                if r and not (math.isfinite(v) and r[0] <= v <= r[1]):
                    ok = False
            if ok:
                out.append(x)
        target = efl if isinstance(efl, (int, float)) and not isinstance(efl, bool) else None
        if target is not None:
            out.sort(key=lambda x: (abs(x.efl - target), x.part))
        elif sort:
            def key(x):
                v = getattr(x, sort, x.part)
                if isinstance(v, float) and not math.isfinite(v):
                    v = math.inf
                return (v, x.part) if not isinstance(v, str) else (0, v.lower())
            out.sort(key=key)
        return out[:limit] if limit else out


def _decode(raw: bytes) -> str:
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


_VENDORS = ("Thorlabs", "Edmund Optics", "Newport", "Ross Optical", "Melles Griot", "CVI", "Optosigma",
            "Qioptiq", "Linos", "Lightpath", "Esco", "Knight Optical", "Sigma Koki", "Anchor Optics", "Ealing")


def _guess_vendor(text: str) -> str:
    lines = text.splitlines()[:60]
    head = " ".join(l for l in lines if l.startswith("NAME")) + " " + "".join(
        l[7:] if l.startswith("NOTE 0 ") else "" for l in lines)
    head = head.lower()
    for v in _VENDORS:
        if v.lower() in head or v.lower().replace(" ", "") in head.replace(" ", ""):
            return v
    return ""


def _guess_part(text: str, stem: str) -> str:
    """The part number: the file name without the makers' '-Zemax(ZMX)' style suffixes."""
    part = re.sub(r"[-_ ]*(zemax)?[-_ ]*(\(zmx\)|zmx)?$", "", stem, flags=re.I).strip()
    if part:
        return part
    m = re.search(r"^NAME\s+(\S.*)$", text, re.M)
    return m.group(1).strip() if m else stem


# ---------------------------------------------------------------------------
# Inserting
# ---------------------------------------------------------------------------

def insert_stock_lens(target, part: Union[StockLens, str], at: Optional[int] = None, reverse: bool = False,
                      library: Optional[StockLibrary] = None, copy_semi_diameters: bool = True,
                      comment: bool = True, renumber: bool = True, substitute_missing: bool = True) -> range:
    """Insert a stock part's element surfaces into ``target`` before surface ``at`` (default:
    before the image).

    ``part`` is a :class:`StockLens` or a part number / key looked up in ``library``
    (default :meth:`StockLibrary.default`). ``reverse`` turns the part round (light enters
    the back surface first). The first and last inserted surfaces get the comment
    ``'<part> (<vendor>)'`` (plus ', reversed'). Semi-diameters are copied from the part
    as fixed values unless ``copy_semi_diameters`` is False. The last surface keeps the
    thickness the maker's file gives it (usually the back focal distance). With
    ``renumber`` variables, solves and merit operands on later surfaces move with them.
    With ``substitute_missing`` glasses that are in none of the target's catalogs are
    replaced as :meth:`StockLens.missing_glasses` says (an equivalent, or a model glass).
    Returns the range of new surface indices.
    """
    from .compose import insert_lens, renumber_surface_refs
    if isinstance(part, str):
        part = (library or StockLibrary.default()).get(part)
    src = part.system(target.library, substitute_missing=substitute_missing)
    first, last = _element_range(src)
    at = target.image_index if at is None else int(at)
    n0 = target.num_surfaces
    rng = insert_lens(target, src, at=at, first=first, last=last, reverse=reverse,
                      copy_semi_diameters=copy_semi_diameters)
    n = target.num_surfaces - n0
    if renumber:
        renumber_surface_refs(target, lambda i: i + n if i >= at else i)
    if reverse:
        # the maker's last thickness is the forward back focal distance; turned round, use the
        # turned part's own paraxial back focal distance instead
        bfd = _group_bfd(target, rng)
        if math.isfinite(bfd):
            target.surfaces[rng[-1]].thickness = bfd
    if comment:
        label = part.label + (", reversed" if reverse else "")
        target.surfaces[rng[0]].comment = label
        target.surfaces[rng[-1]].comment = label
    return rng


# ---------------------------------------------------------------------------
# Demo parts (generic, made up for lensforge: not any maker's products)
# ---------------------------------------------------------------------------

def _zmx(name, note, surfaces, epd, wavelengths=(0.4861327, 0.5875618, 0.6562725)) -> str:
    """Minimal .zmx text: surfaces = [(curvature, thickness, glass or None, semi-diameter)]."""
    lines = ["VERS 190513 80 123457", "MODE SEQ", f"NAME {name}", f"NOTE 0 {note}", "UNIT MM X W X CM MR CPMM",
             f"ENPD {epd:.6g}", "FTYP 0 0 1 3 0 0 0", "XFLN 0 0 0", "YFLN 0 0 0", "FWGN 1 1 1"]
    for i, w in enumerate(wavelengths, start=1):
        lines.append(f"WAVM {i} {w} 1")
    lines.append("PWAV 2")
    rows = [(0.0, math.inf, None, 0.0)] + list(surfaces) + [(0.0, 0.0, None, 0.0)]
    for i, (c, t, g, sd) in enumerate(rows):
        lines.append(f"SURF {i}")
        lines.append("  TYPE STANDARD")
        lines.append(f"  CURV {float(c)!r}")
        lines.append("  DISZ " + ("INFINITY" if math.isinf(t) else repr(float(t))))
        if g:
            lines.append(f"  GLAS {g} 0 0 1.5 40 0 0 0 0 0 0")
        if sd:
            lines.append(f"  DIAM {float(sd)!r} 1 0 0 1 \"\"")
        if i == 1:
            lines.append("  STOP")
    return "\n".join(lines) + "\n"


def _singlet(n, f, d, ct, form):
    """Curvatures of a thick singlet of focal length f: form 'pcx' (curved side first), 'dcx' (equi), 'men'."""
    phi = 1.0 / f
    if form == "p":
        c1 = phi / (n - 1)
        return [c1, 0.0]
    if form == "e":  # equi: phi = (n-1)(2c) - (n-1)^2 c^2 t / n
        a, b, cc = -(n - 1) ** 2 * ct / n, 2 * (n - 1), -phi
        c = (-b + math.sqrt(b * b - 4 * a * cc)) / (2 * a) if a else -cc / b
        return [c, -c]
    # meniscus, shape factor 2 (positive) / -2
    q = 2.0 if f > 0 else -2.0
    c1 = phi / (n - 1) * (q + 1) / 2
    return [c1, c1 - phi / (n - 1)]


def _scale_to(curvs, ts, glasses, f, library):
    """Scale curvatures so the thick lens has focal length f exactly (a few paraxial passes)."""
    from .system import OpticalSystem
    for _ in range(6):
        t = OpticalSystem("x", "mm", library)
        for i, (c, th, g) in enumerate(zip(curvs, ts, glasses)):
            t.insert(t.image_index, S.Standard(curvature=c, thickness=th, material=g, stop=i == 0))
        t.set_aperture("EPD", 1.0)
        got = t.paraxial().efl
        if not math.isfinite(got) or abs(got - f) < 1e-9 * abs(f):
            break
        curvs = [c * got / f for c in curvs]
    return curvs, got


_DEMO = [
    # part, kind, f, diameter, centre thickness(s), glass(es)
    ("LFD-PCX-12-25", "p", 25.0, 12.7, [3.8], ["N-BK7"]),
    ("LFD-PCX-25-50", "p", 50.0, 25.4, [5.3], ["N-BK7"]),
    ("LFD-PCX-25-100", "p", 100.0, 25.4, [3.6], ["N-BK7"]),
    ("LFD-PCX-25-200", "p", 200.0, 25.4, [2.8], ["N-BK7"]),
    ("LFD-PCX-50-100", "p", 100.0, 50.8, [8.2], ["N-BK7"]),
    ("LFD-PCV-25-M50", "p", -50.0, 25.4, [3.0], ["N-BK7"]),
    ("LFD-PCV-25-M100", "p", -100.0, 25.4, [3.0], ["N-BK7"]),
    ("LFD-DCX-25-50", "e", 50.0, 25.4, [5.9], ["N-BK7"]),
    ("LFD-DCX-25-100", "e", 100.0, 25.4, [3.9], ["N-BK7"]),
    ("LFD-DCV-25-M50", "e", -50.0, 25.4, [3.0], ["N-BK7"]),
    ("LFD-MEN-25-100", "m", 100.0, 25.4, [4.0], ["N-BK7"]),
    ("LFD-MEN-25-M100", "m", -100.0, 25.4, [3.0], ["N-BK7"]),
    ("LFD-PCX-25-50-FS", "p", 50.0, 25.4, [5.0], ["F_SILICA"]),
    ("LFD-ACH-12-30", "a", 30.0, 12.7, [4.0, 2.0], ["N-BK7", "N-SF5"]),
    ("LFD-ACH-25-50", "a", 50.0, 25.4, [7.0, 2.5], ["N-BK7", "N-SF5"]),
    ("LFD-ACH-25-100", "a", 100.0, 25.4, [6.0, 2.5], ["N-BK7", "N-SF5"]),
    ("LFD-ACH-25-200", "a", 200.0, 25.4, [4.0, 2.5], ["N-BK7", "N-SF5"]),
]

_DEMO_CACHE: Optional[List[StockLens]] = None


def demo_lenses() -> List[StockLens]:
    """Generic stock parts made up for lensforge (catalog 'LensForge Demo'), so search and
    insert work without any vendor catalog."""
    global _DEMO_CACHE
    if _DEMO_CACHE is None:
        from .system import shared_library
        lib = shared_library()
        n_of = lambda g: float(lib.resolve(g).index(0.5875618))  # noqa: E731
        out = []
        for part, form, f, dia, ts, gl in _DEMO:
            sd = dia / 2
            if form == "a":
                n1, n2 = n_of(gl[0]), n_of(gl[1])
                v1, v2 = 64.17, 32.25  # N-BK7, N-SF5
                p1, p2 = (1 / f) * v1 / (v1 - v2), -(1 / f) * v2 / (v1 - v2)
                c1 = p1 / (2 * (n1 - 1))
                c2 = -c1
                c3 = c2 - p2 / (n2 - 1)
                curvs, ths, glasses = [c1, c2, c3], ts + [0.0], gl + [None]
            else:
                curvs = _singlet(n_of(gl[0]), f, dia, ts[0], form)
                ths, glasses = ts + [0.0], gl + [None]
            curvs, got = _scale_to(curvs, ths, glasses, f, lib)
            # back focal distance as the last thickness (as makers' files do)
            from .system import OpticalSystem
            t = OpticalSystem("x", "mm", lib)
            for i, (c, th, g) in enumerate(zip(curvs, ths, glasses)):
                t.insert(t.image_index, S.Standard(curvature=c, thickness=th, material=g, stop=i == 0))
            t.set_aperture("EPD", 1.0)
            bfd = float(t.paraxial().bfl)
            ths[-1] = round(bfd, 4) if math.isfinite(bfd) else 0.0
            name = {"p": "Plano-convex" if f > 0 else "Plano-concave", "e": "Bi-convex" if f > 0 else "Bi-concave",
                    "m": "Positive meniscus" if f > 0 else "Negative meniscus", "a": "Achromatic doublet"}[form]
            note = f"{name} lens, f = {f:g} mm, diameter {dia:g} mm, {'/'.join(gl)} (generic demo part)"
            text = _zmx(part, note, [(c, th, g, sd) for c, th, g in zip(curvs, ths, glasses)], epd=min(dia * 0.8, 20))
            out.append(StockLens.from_zmx(text, part=part, vendor="LensForge Demo", catalog=DEMO_CATALOG, efl=got))
        _DEMO_CACHE = out
    return [StockLens.from_dict(x.to_dict()) for x in _DEMO_CACHE]
