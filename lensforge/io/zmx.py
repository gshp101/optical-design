"""Import of Zemax OpticStudio sequential ``.zmx`` files (common subset).

Supported: STANDARD, EVENASPH, ODDASPH, TOROIDAL, PARAXIAL, DGRATING, COORDBRK surfaces;
CURV, DISZ, GLAS (catalog name, model glass, MIRROR), CONI, PARM, DIAM, STOP,
circular apertures/obscurations (CLAP/OBSC); aperture ENPD/FNUM/OBNA/FLOA;
fields XFLN/YFLN/FTYP/FWGN; wavelengths WAVM/PWAV; UNIT.  Unknown keywords are
ignored and listed in ``system.notes``.
"""

from __future__ import annotations

import math

from .. import surfaces as S
from ..system import Field, OpticalSystem, Wavelength


def _read_text(path):
    raw = open(path, "rb").read()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def load_zmx(path_or_text: str, library=None) -> OpticalSystem:
    text = path_or_text if "\n" in path_or_text else _read_text(path_or_text)
    surfs = []
    cur = None
    sysd = {"units": "mm", "xfln": [], "yfln": [], "fwgn": [], "waves": {}, "pwav": 1,
            "ftyp": 0, "aper": ("ENPD", 10.0), "name": ""}
    ignored = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = line.split()
        key = parts[0]
        indented = raw[:1] in (" ", "\t")
        if key == "SURF":
            cur = {"type": "STANDARD", "curv": 0.0, "disz": 0.0, "glas": None, "conic": 0.0,
                   "parm": {}, "diam": None, "stop": False, "comment": "", "clap": None, "obsc": None}
            surfs.append(cur)
            continue
        if cur is not None and indented:
            if key == "TYPE":
                cur["type"] = parts[1]
            elif key == "CURV":
                cur["curv"] = float(parts[1])
            elif key == "DISZ":
                cur["disz"] = math.inf if parts[1].upper() == "INFINITY" else float(parts[1])
            elif key == "GLAS":
                name = parts[1]
                if name == "___BLANK" and len(parts) >= 6:
                    cur["glas"] = f"{float(parts[4])},{float(parts[5])}"
                else:
                    cur["glas"] = name
            elif key == "CONI":
                cur["conic"] = float(parts[1])
            elif key == "PARM":
                cur["parm"][int(parts[1])] = float(parts[2])
            elif key == "DIAM":
                cur["diam"] = float(parts[1])
            elif key == "STOP":
                cur["stop"] = True
            elif key == "COMM":
                cur["comment"] = line[5:].strip()
            elif key == "CLAP":
                cur["clap"] = (float(parts[1]), float(parts[2]))
            elif key == "OBSC":
                cur["obsc"] = (float(parts[1]), float(parts[2]))
            else:
                ignored.add(key)
            continue
        cur = None
        if key == "NAME":
            sysd["name"] = line[5:].strip()
        elif key == "UNIT":
            sysd["units"] = {"MM": "mm", "CM": "cm", "METER": "m", "IN": "in"}.get(parts[1].upper(), "mm")
        elif key == "ENPD":
            sysd["aper"] = ("EPD", float(parts[1]))
        elif key == "FNUM":
            sysd["aper"] = ("IMAGE_FNUM", float(parts[1]))
        elif key == "OBNA":
            sysd["aper"] = ("OBJECT_NA", float(parts[1]))
        elif key == "FLOA":
            sysd["aper"] = ("STOP_SIZE", None)
        elif key == "FTYP":
            sysd["ftyp"] = int(parts[1])
        elif key == "XFLN":
            sysd["xfln"] = [float(v) for v in parts[1:]]
        elif key == "YFLN":
            sysd["yfln"] = [float(v) for v in parts[1:]]
        elif key == "FWGN":
            sysd["fwgn"] = [float(v) for v in parts[1:]]
        elif key == "WAVM":
            sysd["waves"][int(parts[1])] = (float(parts[2]), float(parts[3]) if len(parts) > 3 else 1.0)
        elif key == "PWAV":
            sysd["pwav"] = int(parts[1])
        else:
            ignored.add(key)

    lens = OpticalSystem(sysd["name"], sysd["units"], library)
    lens.surfaces = []
    for d in surfs:
        common = dict(thickness=d["disz"], material=d["glas"], stop=d["stop"], comment=d["comment"],
                      semi_diameter=d["diam"])
        p = d["parm"]
        t = d["type"]
        if t == "EVENASPH":
            coeffs = [p.get(i, 0.0) for i in range(1, 9)]
            s = S.EvenAsphere(curvature=d["curv"], conic=d["conic"], coefficients=_trim(coeffs), **common)
        elif t == "ODDASPH":
            coeffs = [p.get(i, 0.0) for i in range(1, 9)]
            s = S.OddAsphere(curvature=d["curv"], conic=d["conic"], coefficients=_trim(coeffs), **common)
        elif t == "TOROIDAL":
            rx = p.get(1, 0.0)
            coeffs = [p.get(i, 0.0) for i in range(2, 10)]
            s = S.Toroidal(curvature=d["curv"], conic=d["conic"], radius_x=rx if rx else math.inf,
                           coefficients=_trim(coeffs), **common)
        elif t == "PARAXIAL":
            common.pop("material", None)
            s = S.Paraxial(focal_length=p.get(1, 100.0), material=d["glas"], **common)
        elif t == "DGRATING":
            s = S.DiffractionGrating(curvature=d["curv"], conic=d["conic"], lines_per_um=p.get(1, 0.0),
                                     diffraction_order=p.get(2, 0.0), **common)
        elif t == "COORDBRK":
            s = S.CoordinateBreak(decenter_x=p.get(1, 0.0), decenter_y=p.get(2, 0.0), tilt_x=p.get(3, 0.0),
                                  tilt_y=p.get(4, 0.0), tilt_z=p.get(5, 0.0), order=int(p.get(6, 0)),
                                  thickness=d["disz"], comment=d["comment"])
        else:
            if t != "STANDARD":
                ignored.add(f"surface type {t}")
            s = S.Standard(curvature=d["curv"], conic=d["conic"], **common)
        if d["clap"] is not None:
            s.aperture = S.CircularAperture(d["clap"][1], d["clap"][0])
        if d["obsc"] is not None:
            s.aperture = S.CircularObscuration(d["obsc"][1])
        lens.surfaces.append(s)

    kind, val = sysd["aper"]
    if kind == "STOP_SIZE":
        val = lens.surfaces[lens.stop_index].semi_diameter or 1.0
    lens.set_aperture(kind, val)
    ftyp = {0: "ANGLE", 1: "OBJECT_HEIGHT", 2: "PARAXIAL_IMAGE_HEIGHT", 3: "REAL_IMAGE_HEIGHT"}.get(sysd["ftyp"], "ANGLE")
    ys = sysd["yfln"]
    xs = sysd["xfln"] or [0.0] * len(ys)
    ws = sysd["fwgn"] or [1.0] * len(ys)
    n = max(len(ys), 1)
    fields = [Field(xs[i] if i < len(xs) else 0.0, ys[i] if i < len(ys) else 0.0, ws[i] if i < len(ws) else 1.0)
              for i in range(n)]
    # Zemax stores 12 field slots; keep only the populated leading ones
    used = [f for i, f in enumerate(fields) if i == 0 or f.x or f.y]
    lens.field_type = ftyp
    lens.fields = used or [Field()]
    if sysd["waves"]:
        keys = sorted(sysd["waves"])
        lens.wavelengths = [Wavelength(*sysd["waves"][k]) for k in keys]
        lens.primary_wavelength = keys.index(sysd["pwav"]) if sysd["pwav"] in keys else 0
    if ignored:
        lens.notes = "ZMX import ignored: " + ", ".join(sorted(ignored))
    return lens


def _trim(c):
    c = list(c)
    while c and c[-1] == 0.0:
        c.pop()
    return c
