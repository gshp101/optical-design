"""Non-Sequential Editor tables: columns, labels and cell parsing (pure Python, no Qt).

Shared by the Qt window (ns_window.py) and the web front end (lensforge_web).
"""

from __future__ import annotations

import math

from .edits import parse_params

POSE = ["x", "y", "z", "tilt_x", "tilt_y", "tilt_z"]
OBJ_COLS = ["Type", "Comment"] + ["X", "Y", "Z", "Tilt X", "Tilt Y", "Tilt Z"] + ["Material", "Coating R",
                                                                                  "Parameters"]
SRC_COLS = ["Type", "Comment"] + ["X", "Y", "Z", "Tilt X", "Tilt Y", "Tilt Z"] + ["Rays", "Power", "Wavelengths (um)",
                                                                                  "Sampling", "Parameters"]
OBJECT_LABELS = {
    "STANDARD_LENS": "Standard Lens", "SPHERE": "Sphere", "RECT_VOLUME": "Rectangular Volume",
    "CYLINDER_VOLUME": "Cylinder Volume", "STANDARD_SURFACE": "Standard Surface (mirror / absorber)",
    "ANNULUS": "Annulus", "RECTANGLE": "Rectangle (mirror / absorber)", "DETECTOR": "Detector Rectangle"}
SOURCE_LABELS = {"SOURCE_POINT": "Source Point", "SOURCE_ELLIPSE": "Source Ellipse",
                 "SOURCE_RECTANGLE": "Source Rectangle"}

#: toolbar buttons of the window: key -> (text, tooltip); icons in icons.NS_ICONS
BUTTONS = {
    "new": ("New Scene", "Start an empty non-sequential scene (asks first if it has objects)."),
    "open": ("Open Scene", "Open a non-sequential scene file (.ns.json)."),
    "save": ("Save Scene", "Save the scene to a .ns.json file (scripting: lensforge.nonseq.save)."),
    "convert": ("From Current Lens", "Replace the scene with the current sequential lens converted to "
                                     "non-sequential objects, sources and an image detector."),
    "add_object": ("Add Object", "Add an object (lens, sphere, box, rod, mirror, annulus, rectangle or detector) "
                                 "after the selected row."),
    "add_source": ("Add Source", "Add a source (point, ellipse or rectangle) to the scene."),
    "delete": ("Delete Row", "Delete the selected object or source."),
    "trace": ("Trace", "Trace all sources with the settings below and show the rays and the detector (F5)."),
    "help": ("Help", "Open the help page of the non-sequential editor (F1)."),
}


def _fmt(v):
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, float):
        if math.isinf(v):
            return "Infinity" if v > 0 else "-Infinity"
        return "0" if v == 0 else f"{v:.10g}"
    return str(v)


def _num(text):
    t = text.strip().lower()
    if t in ("inf", "infinity"):
        return math.inf
    if t in ("-inf", "-infinity"):
        return -math.inf
    return float(t)


def apply_cell(target, c, text, is_obj):
    """Set column ``c`` of an object (``is_obj``) or source row from typed text."""
    if c == 1:
        target.comment = text
    elif 2 <= c <= 7:
        setattr(target, POSE[c - 2], _num(text))
    elif is_obj and c == 8:
        if not target.is_detector:
            target.material = text.strip() or None
    elif is_obj and c == 9:
        target.coating = None if not text.strip() else float(text)
    elif not is_obj and c == 8:
        target.n_rays = max(1, int(float(text)))
    elif not is_obj and c == 9:
        target.power = float(text)
    elif not is_obj and c == 10:
        target.wavelengths = [float(w) for w in text.replace(";", ",").split(",") if w.strip()] or [0.5875618]
    elif not is_obj and c == 11:
        if text.strip() not in ("random", "grid"):
            raise ValueError("sampling is random or grid")
        target.sampling = text.strip()
    elif c == len(OBJ_COLS if is_obj else SRC_COLS) - 1:
        names = {n for n, _ in target.params}
        for k, v in parse_params(text).items():
            if k not in names:
                raise ValueError(f"{k!r} is not a parameter of this {'object' if is_obj else 'source'} "
                                 f"(use {', '.join(sorted(names))})")
            old = getattr(target, k)
            if isinstance(old, bool):
                setattr(target, k, bool(int(float(v))))
            elif isinstance(old, int):
                setattr(target, k, int(float(v)))
            else:
                setattr(target, k, _num(str(v)))
        if hasattr(target, "surface1") and any(n in parse_params(text) for n in ("radius1", "conic1")):
            target.surface1 = None  # typed radii replace a converted surface shape
        if hasattr(target, "surface2") and any(n in parse_params(text) for n in ("radius2", "conic2")):
            target.surface2 = None
        if hasattr(target, "surface") and getattr(target, "surface", None) is not None and any(
                n in parse_params(text) for n in ("radius", "conic")):
            target.surface = None
