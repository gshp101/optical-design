"""Non-Sequential Component Editor: columns, cells and edits of the scene kept with the lens (no Qt).

The scene is ``system.nonseq`` (a :class:`lensforge.nonseq.NonSequentialSystem`), so it is saved
in the lens file and every edit is one undoable lens edit.  The editor has an object table and a
source table laid out as in Zemax's Non-Sequential Component Editor: Type, Comment, Ref (the
object whose frame the position is given in), X, Y, Z, Tilt X/Y/Z, then the material (objects)
or the ray settings (sources) and ``Par 1..`` columns whose meaning depends on the row's type
(their names are in the column header of the selected row and in each cell's tooltip).

Shared by the Qt window (ns_window.py) and the web front end (lensforge_web).
"""

from __future__ import annotations

import json
import math
import threading

from lensforge import nonseq as ns

POSE = ["x", "y", "z", "tilt_x", "tilt_y", "tilt_z"]
POSE_COLS = ["X", "Y", "Z", "Tilt X", "Tilt Y", "Tilt Z"]
N_OBJ_PAR = max(len(c.params) for c in ns.OBJECT_TYPES.values())
N_SRC_PAR = max(len(c.params) for c in ns.SOURCE_TYPES.values())
OBJ_COLS = ["Type", "Comment", "Ref"] + POSE_COLS + ["Material", "Coating R"] + [f"Par {k + 1}"
                                                                                   for k in range(N_OBJ_PAR)]
SRC_COLS = ["Type", "Comment", "Ref"] + POSE_COLS + ["Rays", "Power", "Wavelengths (um)", "Sampling"] + [
    f"Par {k + 1}" for k in range(N_SRC_PAR)]
OBJ_PAR0 = OBJ_COLS.index("Par 1")
SRC_PAR0 = SRC_COLS.index("Par 1")
MATERIAL_COL = OBJ_COLS.index("Material")

OBJECT_LABELS = {
    "STANDARD_LENS": "Standard Lens", "SPHERE": "Sphere", "RECT_VOLUME": "Rectangular Volume",
    "CYLINDER_VOLUME": "Cylinder Volume", "PRISM": "Prism", "STANDARD_SURFACE": "Standard Surface (mirror / absorber)",
    "ANNULUS": "Annulus", "RECTANGLE": "Rectangle (mirror / absorber)", "DETECTOR": "Detector Rectangle"}
SOURCE_LABELS = {"SOURCE_POINT": "Source Point", "SOURCE_ELLIPSE": "Source Ellipse",
                 "SOURCE_RECTANGLE": "Source Rectangle"}

#: what each column means (header tooltips)
COLUMN_TIPS = {
    "Type": "Object or source type. Choose another type from the cell's list; position, comment and Ref are kept.",
    "Comment": "Free text: a name for the row (shown in path analyses and detector titles).",
    "Ref": "Ref Object: the object number whose coordinate frame X..Tilt Z are given in (0 = global). "
           "Move the reference object and everything placed on it moves with it.",
    "X": "X position of the local origin (lens units).", "Y": "Y position of the local origin.",
    "Z": "Z position of the local origin.",
    "Tilt X": "Rotation about the local X axis (degrees), applied first.",
    "Tilt Y": "Rotation about the new Y axis (degrees), applied second.",
    "Tilt Z": "Rotation about the new Z axis (degrees), applied last.",
    "Material": "Glass inside a volume (any catalog glass), MIRROR or ABSORB for surfaces; empty = the "
                "scene's medium (air). Red: not in any loaded glass catalog.",
    "Coating R": "Reflectance of the refracting faces (0..1) instead of Fresnel's (uncoated) value; empty = "
                 "Fresnel. For mirrors and baffles the reflectance is a parameter.",
    "Rays": "Number of rays the source launches per trace.",
    "Power": "Total power of the source (watts, or any unit), split evenly over its rays.",
    "Wavelengths (um)": "Wavelengths of the source, comma separated; the rays are spread evenly over them.",
    "Sampling": "random (Monte Carlo, seeded so it repeats) or grid (a regular pattern).",
}
for _k in range(max(N_OBJ_PAR, N_SRC_PAR)):
    COLUMN_TIPS[f"Par {_k + 1}"] = ("Parameter of the row's type; its name is in the header when the row is "
                                     "selected and in the cell's tooltip.")

#: Ray Trace Control settings kept with the scene: key -> (label, kind, tooltip)
TRACE_FIELDS = {
    "split": ("Split rays", "bool", "Follow both the reflected and the transmitted part at every refracting face "
                                    "(needed to see ghosts and stray light)."),
    "fresnel": ("Fresnel losses", "bool", "Lose the Fresnel-reflected power at refracting faces (always on when "
                                          "rays are split)."),
    "min_relative_intensity": ("Min. relative intensity", "float",
                               "Split rays weaker than this fraction of their source ray's power are dropped."),
    "max_segments": ("Max. segments per ray", "int", "A ray is stopped after this many segments."),
    "seed": ("Random seed", "int", "Seed of the random source sampling: the same seed gives the same rays."),
}

#: toolbar buttons of the editor: key -> (text, tooltip); icons in icon_svgs.NS_ICONS
BUTTONS = {
    "new": ("New Scene", "Clear the non-sequential scene of this lens (asks first if it has objects)."),
    "open": ("Import Scene", "Replace the scene with one from a .ns.json file (scripting: lensforge.nonseq.load)."),
    "save": ("Export Scene", "Save the scene alone to a .ns.json file (it is saved with the lens file anyway)."),
    "convert": ("From Current Lens", "Replace the scene with the sequential lens converted to non-sequential "
                                     "objects, one source per field and an image detector."),
    "add_object": ("Add Object", "Insert an object (lens, sphere, box, rod, prism, mirror, annulus, rectangle or "
                                 "detector) after the selected row."),
    "add_source": ("Add Source", "Insert a source (point, ellipse or rectangle) after the selected source."),
    "duplicate": ("Duplicate Row", "Insert a copy of the selected object or source below it."),
    "move_up": ("Move Up", "Move the selected row up one place (Ref numbers follow the move)."),
    "move_down": ("Move Down", "Move the selected row down one place (Ref numbers follow the move)."),
    "delete": ("Delete Row", "Delete the selected object or source (Ref numbers that pointed past it follow)."),
    "trace": ("Trace", "Trace all sources with the Ray Trace Control settings and show the summary (F5); the "
                       "non-sequential analysis windows update too."),
    "layout": ("NS Layout", "Open the Non-Sequential Layout analysis (Analysis > Non-Sequential)."),
    "detector": ("Detector Viewer", "Open the Detector Viewer analysis (Analysis > Non-Sequential)."),
    "paths": ("Path Analysis", "Open the Ray Path Analysis: the brightest ray paths to a detector, ghosts included."),
    "help": ("Help", "Open the help page of the Non-Sequential Component Editor (F1)."),
}


# ---------------------------------------------------------------------------- formatting
def _fmt(v):
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, float):
        if math.isinf(v):
            return "Infinity" if v > 0 else "-Infinity"
        return "0" if v == 0 else f"{v:.10g}"
    return str(v)


def _num(text):
    t = str(text).strip().lower()
    if t in ("inf", "infinity"):
        return math.inf
    if t in ("-inf", "-infinity"):
        return -math.inf
    return float(t)


def scene_of(system, create=False):
    """The lens's scene (``system.nonseq``); with ``create`` an empty one is made if it has none."""
    sc = getattr(system, "nonseq", None)
    if sc is None and create:
        sc = system.nonseq = ns.NonSequentialSystem(system.name or "Scene", system.units, library=system.library)
    return sc


def items(scene, table):
    return scene.objects if table == "objects" else scene.sources


def par_labels(item, n=None):
    """Header labels of the Par columns for a row (empty for unused columns)."""
    n = n if n is not None else (N_OBJ_PAR if isinstance(item, ns.NSObject) else N_SRC_PAR)
    labs = [lab for _, lab in item.params]
    return labs + [""] * (n - len(labs))


def object_cells(o):
    return ([OBJECT_LABELS.get(o.kind, o.kind), o.comment, str(o.ref)] + [_fmt(getattr(o, k)) for k in POSE]
            + ["" if o.is_detector else _fmt(o.material or ""), "" if o.coating is None else _fmt(o.coating)]
            + [_fmt(getattr(o, n)) for n, _ in o.params] + [""] * (N_OBJ_PAR - len(o.params)))


def source_cells(s):
    return ([SOURCE_LABELS.get(s.kind, s.kind), s.comment, str(s.ref)] + [_fmt(getattr(s, k)) for k in POSE]
            + [str(s.n_rays), _fmt(s.power), ", ".join(_fmt(w) for w in s.wavelengths), s.sampling]
            + [_fmt(getattr(s, n)) for n, _ in s.params] + [""] * (N_SRC_PAR - len(s.params)))


def editable(item, c, is_obj):
    """False for cells that do not apply to the row (Type is edited from its list)."""
    par0, n = (OBJ_PAR0, len(item.params)) if is_obj else (SRC_PAR0, len(item.params))
    if c >= par0:
        return c - par0 < n
    if is_obj and c in (MATERIAL_COL, MATERIAL_COL + 1) and item.is_detector:
        return False
    if is_obj and c == MATERIAL_COL + 1 and not item.is_volume:
        return False
    return c != 0


def cell_tip(item, c, is_obj):
    cols = OBJ_COLS if is_obj else SRC_COLS
    par0 = OBJ_PAR0 if is_obj else SRC_PAR0
    if c >= par0:
        k = c - par0
        return f"{item.params[k][1]} ({item.params[k][0]})" if k < len(item.params) else "Not used by this type"
    return COLUMN_TIPS.get(cols[c], "")


def table_rows(scene, table, missing=()):
    """Rows of a table for the editors: {"cells", "labels" (Par column names), "tips", "editable", "bad"}."""
    is_obj = table == "objects"
    out = []
    for r, it in enumerate(items(scene, table)):
        cells = object_cells(it) if is_obj else source_cells(it)
        bad = []
        if is_obj and r in missing:
            bad.append(MATERIAL_COL)
        out.append({"cells": cells, "labels": par_labels(it), "editable": [editable(it, c, is_obj)
                                                                            for c in range(len(cells))],
                    "tips": [cell_tip(it, c, is_obj) for c in range(len(cells))], "bad": bad,
                    "detector": bool(is_obj and it.is_detector), "kind": it.kind})
    return out


def missing_rows(scene):
    """Object rows whose glass no loaded catalog has."""
    out = set()
    for rows in scene.missing_materials().values():
        out.update(rows)
    return out


def detectors(scene):
    """[(object index, label)] of the scene's detectors."""
    return [(k, f"{k + 1}: {o.comment or 'detector'}") for k, o in enumerate(scene.objects) if o.is_detector]


# ---------------------------------------------------------------------------- edits (on the scene)
def apply_cell(target, c, text, is_obj):
    """Set column ``c`` of an object (``is_obj``) or source row from typed text."""
    text = str(text)
    par0 = OBJ_PAR0 if is_obj else SRC_PAR0
    if c == 0:
        raise ValueError("choose the type from the list")
    if c == 1:
        target.comment = text
    elif c == 2:
        v = int(float(text or 0))
        if v < 0:
            raise ValueError("Ref is an object number (0 = global)")
        target.ref = v
    elif 3 <= c <= 8:
        setattr(target, POSE[c - 3], _num(text))
    elif c >= par0:
        k = c - par0
        if k >= len(target.params):
            raise ValueError("this column is not used by this type")
        name = target.params[k][0]
        old = getattr(target, name)
        if isinstance(old, bool):
            setattr(target, name, bool(int(float(text))))
        elif isinstance(old, int):
            setattr(target, name, int(float(text)))
        else:
            setattr(target, name, _num(text))
        # typed radii replace a converted surface shape
        if name in ("radius1", "conic1") and getattr(target, "surface1", None) is not None:
            target.surface1 = None
        if name in ("radius2", "conic2") and getattr(target, "surface2", None) is not None:
            target.surface2 = None
        if name in ("radius", "conic") and getattr(target, "surface", None) is not None:
            target.surface = None
    elif is_obj and c == MATERIAL_COL:
        if target.is_detector:
            raise ValueError("a detector has no material")
        target.material = text.strip() or None
    elif is_obj and c == MATERIAL_COL + 1:
        if not text.strip():
            target.coating = None
        else:
            v = float(text)
            if not 0 <= v <= 1:
                raise ValueError("the coating reflectance is between 0 and 1")
            target.coating = v
    elif not is_obj and c == par0 - 4:
        target.n_rays = max(1, int(float(text)))
    elif not is_obj and c == par0 - 3:
        target.power = float(text)
    elif not is_obj and c == par0 - 2:
        wl = [float(w) for w in text.replace(";", ",").split(",") if w.strip()]
        if not wl or any(w <= 0 for w in wl):
            raise ValueError("give one or more wavelengths in um, comma separated")
        target.wavelengths = wl
    elif not is_obj and c == par0 - 1:
        if text.strip() not in ("random", "grid"):
            raise ValueError("sampling is random or grid")
        target.sampling = text.strip()


def _new(kind):
    if kind in ns.OBJECT_TYPES:
        return ns.OBJECT_TYPES[kind]()
    return ns.SOURCE_TYPES[kind](z=-10.0)


def _shift_refs(scene, fn):
    """Renumber every Ref through ``fn(old number) -> new number`` (0 stays 0)."""
    for it in scene.objects + scene.sources:
        if it.ref:
            it.ref = fn(it.ref)


def insert(scene, kind, after=-1):
    """Insert a new object or source of ``kind`` after row ``after`` (-1: at the end); returns (table, row)."""
    item = _new(kind)
    table = "objects" if kind in ns.OBJECT_TYPES else "sources"
    lst = items(scene, table)
    at = len(lst) if after < 0 or after >= len(lst) else after + 1
    if table == "objects":
        _shift_refs(scene, lambda r: r + 1 if r > at else r)
    lst.insert(at, item)
    return table, at


def delete(scene, table, row):
    lst = items(scene, table)
    if not 0 <= row < len(lst):
        raise ValueError("select a row first")
    del lst[row]
    if table == "objects":
        gone = row + 1
        _shift_refs(scene, lambda r: 0 if r == gone else r - 1 if r > gone else r)


def duplicate(scene, table, row):
    lst = items(scene, table)
    if not 0 <= row < len(lst):
        raise ValueError("select a row first")
    if table == "objects":
        _shift_refs(scene, lambda r: r + 1 if r > row + 1 else r)
    lst.insert(row + 1, lst[row].copy())
    return row + 1


def move(scene, table, row, delta):
    """Move a row up (delta -1) or down (+1); Ref numbers follow.  Returns the new row."""
    lst = items(scene, table)
    new = row + delta
    if not (0 <= row < len(lst) and 0 <= new < len(lst)):
        return row
    lst[row], lst[new] = lst[new], lst[row]
    if table == "objects":
        a, b = row + 1, new + 1
        _shift_refs(scene, lambda r: b if r == a else a if r == b else r)
    return new


def change_type(scene, table, row, kind):
    """Give a row another type, keeping its comment, Ref and position (and its glass, volume to volume)."""
    lst = items(scene, table)
    old = lst[row]
    if (kind in ns.OBJECT_TYPES) != (table == "objects"):
        raise ValueError("objects and sources cannot change into each other")
    if old.kind == kind:
        return
    new = ns.OBJECT_TYPES[kind]() if table == "objects" else ns.SOURCE_TYPES[kind]()
    for k in POSE + ["comment", "ref"]:
        setattr(new, k, getattr(old, k))
    if table == "objects":
        if old.is_volume and new.is_volume:
            new.material = old.material
            new.coating = old.coating
    else:
        new.n_rays, new.power, new.sampling = old.n_rays, old.power, old.sampling
        new.wavelengths = list(old.wavelengths)
    # parameters with the same name carry over (a box's widths into a rectangle ...)
    names = {n for n, _ in new.params}
    for n, _ in old.params:
        if n in names:
            setattr(new, n, type(getattr(new, n))(getattr(old, n)))
    lst[row] = new


def set_trace_setting(scene, key, value):
    if key not in TRACE_FIELDS:
        raise ValueError(f"unknown ray-trace setting {key}")
    kind = TRACE_FIELDS[key][1]
    if kind == "bool":
        v = value if isinstance(value, bool) else str(value).strip().lower() in ("1", "true", "yes", "on")
    elif kind == "int":
        v = int(float(value))
        if key == "max_segments" and v < 2:
            raise ValueError("at least 2 segments per ray")
    else:
        v = float(value)
        if not 0 <= v <= 1:
            raise ValueError("the minimum relative intensity is between 0 and 1")
    scene.trace_settings[key] = v


def from_lens(system):
    """The sequential part of ``system`` as a scene, ready to trace ghosts (rays split)."""
    scene = ns.from_sequential(system, n_rays=1000, sampling="random")
    scene.trace_settings.update(split=True, min_relative_intensity=1e-5)
    return scene


# ---------------------------------------------------------------------------- tracing (cached)
_CACHE = []  # [(key, result)] most recent last
_CACHE_SIZE = 4
_LOCK = threading.Lock()


def trace(scene, library=None):
    """Trace a scene with its ``trace_settings``; the last few results are kept, so several
    analysis windows of one scene share a trace."""
    if scene is None or not scene.objects and not scene.sources:
        raise ValueError("This lens has no non-sequential scene: open Tools > Non-Sequential > "
                         "Non-Sequential Component Editor and add objects and a source (or press From Current Lens).")
    if library is not None:
        scene.library = library
    miss = scene.missing_materials()
    if miss:
        raise ValueError("Cannot trace: " + "; ".join(
            f"{m} (object {', '.join(str(k + 1) for k in rows)})" for m, rows in miss.items())
            + " is not in any loaded glass catalog. Choose another glass in the Material column.")
    if not scene.sources:
        raise ValueError("The scene has no source: add one with Add Source in the Non-Sequential Component Editor.")
    key = json.dumps(scene.to_json_dict(), sort_keys=True, default=str)
    with _LOCK:
        for k, r in _CACHE:
            if k == key:
                return r
    r = scene.trace()
    with _LOCK:
        _CACHE.append((key, r))
        del _CACHE[:-_CACHE_SIZE]
    return r


def trace_report(result) -> str:
    """Text report of a trace: settings, power balance and per-detector statistics."""
    st = result.settings
    lines = [result.summary(), "",
             f"Settings: split rays {'on' if st.get('split') else 'off'}, Fresnel losses "
             f"{'on' if st.get('fresnel') else 'off'}, min. relative intensity {st.get('min_relative_intensity'):g}, "
             f"max. segments {st.get('max_segments')}, seed {st.get('seed')}.", ""]
    lines.append("Power by where rays end:")
    tot = result.launched_power or 1.0
    for k, v in result.power_by_event().items():
        lines.append(f"  {k:<40} {v:12.6g}  ({100 * v / tot:7.3f} % of launched)")
    for d in result.detectors:
        o = d.detector
        name = o.comment or f"object {d.object_index + 1}"
        lines += ["", f"Detector {d.object_index + 1} ({name}): {o.nx} x {o.ny} pixels, "
                      f"{2 * o.half_x:g} x {2 * o.half_y:g}"]
        lines.append(f"  {'rays':<28} {'hits':>8} {'power':>13} {'peak irradiance':>16} {'centroid x':>11} "
                     f"{'centroid y':>11} {'RMS radius':>11}")
        for lab, sel in (("all", "all"), ("direct (no reflection)", "direct"), ("1 reflection", 1),
                         ("ghosts (2+ reflections)", "ghost")):
            m = d.select(sel)
            pw = d.total_power(sel)
            peak = float(d.image(sel).max()) if m.any() else 0.0
            cx, cy = d.centroid(sel)
            lines.append(f"  {lab:<28} {int(m.sum()):8d} {pw:13.6g} {peak:16.6g} {cx:11.5g} {cy:11.5g} "
                         f"{d.rms_radius(sel):11.5g}")
    return "\n".join(lines)


def paths_report(result, det=None, rays="all", max_paths=25) -> str:
    """Text table of the brightest ray paths to a detector (ghost / stray-light analysis)."""
    sys = result.system
    paths = result.paths(det, rays=rays)
    target = "every detector" if det is None else f"detector {sys.detector_index(det) + 1}"
    total = sum(p["power"] for p in paths)
    lines = [f"Ray paths to {target} ({rays} rays): {len(paths)} distinct paths, total power {total:.6g}.",
             "Each step is: object number, face, event (T transmitted, R Fresnel reflection, X total internal "
             "reflection, M mirror, D detected, P passed a transparent detector).", ""]
    names = "\n".join(f"  {k + 1:>3}: {o.comment or OBJECT_LABELS.get(o.kind, o.kind)}"
                      for k, o in enumerate(sys.objects))
    lines.append(f"{'#':>3} {'power':>12} {'% of total':>11} {'rays':>6} {'refl.':>5}  path")
    for k, p in enumerate(paths[:max_paths]):
        lines.append(f"{k + 1:>3} {p['power']:12.5g} {100 * p['fraction']:10.5f}% {p['rays']:6d} "
                     f"{p['n_reflections']:5d}  {p['label']}")
    if len(paths) > max_paths:
        rest = sum(p["power"] for p in paths[max_paths:])
        lines.append(f"... {len(paths) - max_paths} more paths carrying {rest:.4g}")
    lines += ["", "Objects:", names]
    return "\n".join(lines)
