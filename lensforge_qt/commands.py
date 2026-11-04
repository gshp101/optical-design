"""Front-end-neutral command defaults shared by the Qt app and the web app (no Qt).

The default toolbar, short toolbar captions and the File > Sample Lenses list.
"""

from __future__ import annotations

import os
import re

import lensforge as lf

SEPARATOR = "|"  # a toolbar separator in a list of menu paths (as in toolbar_dialog)
HERE = os.path.dirname(os.path.abspath(__file__))
EXAMPLES = os.path.join(os.path.dirname(HERE), "examples")
# Toolbar buttons out of the box (menu paths, see toolbar_dialog.menu_items); View > Customize Toolbar changes them.
DEFAULT_TOOLBAR = [
    "File > New", "File > Open", "File > Save", SEPARATOR,
    "Edit > Undo", "Edit > Redo", SEPARATOR,
    "File > System Explorer", "Analysis > Layout > 2D Layout", "Analysis > Rays & Spots > Standard Spot Diagram",
    "Analysis > Rays & Spots > Ray Aberration (Ray Fan)", "Analysis > Rays & Spots > Optical Path (OPD Fan)",
    "Analysis > PSF & MTF > MTF", "Analysis > PSF & MTF > PSF", "Analysis > Aberrations > Field Curvature / Distortion",
    "Analysis > Aberrations > Seidel Diagram", "Analysis > Reports > Prescription Data", SEPARATOR,
    "Tools > Merit Function Editor", "Tools > Optimization", "Tools > Tolerancing", "Tools > Python Shell",
]
# Short button captions (the menu text is still the tooltip); anything else shows its menu text.
SHORT_LABELS = {
    "File > System Explorer": "Sys", "Analysis > Layout > 2D Layout": "Lay",
    "Analysis > Rays & Spots > Standard Spot Diagram": "Spt", "Analysis > Rays & Spots > Ray Aberration (Ray Fan)": "Ray",
    "Analysis > Rays & Spots > Optical Path (OPD Fan)": "Opd", "Analysis > PSF & MTF > MTF": "Mtf",
    "Analysis > PSF & MTF > PSF": "Psf", "Analysis > Aberrations > Field Curvature / Distortion": "Fcd",
    "Analysis > Aberrations > Seidel Diagram": "Sei", "Analysis > Reports > Prescription Data": "Pre",
    "Tools > Merit Function Editor": "Mfe", "Tools > Optimization": "Opt", "Tools > Tolerancing": "Tol",
    "Tools > Python Shell": "Py",
}


def sample_list():
    """(name, function returning the lens) of File > Sample Lenses, in menu order."""
    out = [("Singlet", lf.samples.singlet), ("Cemented Achromat", lf.samples.achromat),
           ("Parabolic Mirror", lf.samples.parabolic_mirror), ("Classical Cassegrain", lf.samples.cassegrain)]
    for name, rel in (("Cooke Triplet (optimised)", "output/cooke_triplet.lens.json"),
                      ("Scripted Singlet", "best_singlet.lens.json"),
                      ("Diffraction Grating Demo", "grating_demo.lens.json"),
                      ("Spot Size Merit Example", "spot_size_merit.lens.json")):
        p = os.path.join(EXAMPLES, rel)
        if os.path.exists(p):
            out.append((name, lambda p=p: lf.load(p)))
    return out


# ---------------------------------------------------------------------------
# The Examples menu: every lens file under examples/, grouped by folder
# ---------------------------------------------------------------------------

#: menu labels of example folders (any other folder shows its own name)
EXAMPLE_FOLDER_LABELS = {
    "ModernLensDesignSmith": "Modern Lens Design (Smith)",
    "arducam-lk004": "Arducam LK004 Lens Kit (approximate models)",
}
#: folders whose lenses are listed with the top-level examples (the example scripts' output)
EXAMPLE_MERGED_FOLDERS = {"output"}
EXAMPLE_SUFFIXES = (".lens.json", ".json", ".zmx")


def _natural(text: str):
    """Sort key that puts "Figure 7.2" before "Figure 7.10" and "Chapter 9" before "Chapter 10"."""
    return [(0, int(t), "") if t.isdigit() else (1, 0, t.lower()) for t in re.split(r"(\d+)", text)]


def example_name(filename: str) -> str:
    """Menu text of an example file: its name without .lens.json / .json / .zmx."""
    for suffix in EXAMPLE_SUFFIXES:
        if filename.lower().endswith(suffix):
            return filename[:-len(suffix)]
    return filename


def is_example_file(filename: str) -> bool:
    f = filename.lower()
    return f.endswith(EXAMPLE_SUFFIXES) and not f.endswith(".ns.json") and not f.endswith(".state.json")


def example_index(root: str = None) -> list:
    """Every example lens under ``root`` (default: the repository's examples/ folder), in menu order.

    Each entry is ``{"path": "a/b/x.lens.json" (relative, "/"), "name": "x", "folders": [menu labels],
    "group": "Modern Lens Design (Smith) / Chapter 7 - ..." ("Examples" at the top level)}``.
    Lenses at the top level come first, then each folder (naturally sorted, so Chapter 9 precedes
    Chapter 10), recursively. Folders in EXAMPLE_MERGED_FOLDERS are listed as top-level lenses.
    """
    root = root or EXAMPLES
    out = []

    def listing(dirpath):
        try:
            entries = os.listdir(dirpath)
        except OSError:
            return [], []
        files = [f for f in entries if is_example_file(f) and os.path.isfile(os.path.join(dirpath, f))]
        dirs = sorted((d for d in entries if os.path.isdir(os.path.join(dirpath, d)) and not d.startswith((".", "_"))),
                      key=_natural)
        return files, dirs

    def walk(dirpath, rel, labels):
        files, dirs = listing(dirpath)
        here = [(f, rel) for f in files]
        if not labels:  # top level: the example scripts' output folder is listed here too
            for d in [d for d in dirs if d in EXAMPLE_MERGED_FOLDERS]:
                dirs.remove(d)
                here += [(f, rel + [d]) for f in listing(os.path.join(dirpath, d))[0]]
        for f, r in sorted(here, key=lambda fr: _natural(example_name(fr[0]))):
            out.append({"path": "/".join(r + [f]), "name": example_name(f), "folders": list(labels),
                        "group": " / ".join(labels) or "Examples"})
        for d in dirs:
            walk(os.path.join(dirpath, d), rel + [d], labels + [EXAMPLE_FOLDER_LABELS.get(d, d)])

    walk(root, [], [])
    return out


def example_tree(index: list) -> dict:
    """Nest :func:`example_index` entries by folder: ``{"files": [entry], "folders": {label: tree}}``
    (insertion order is menu order). Folders without lenses do not appear."""
    tree = {"files": [], "folders": {}}
    for x in index:
        node = tree
        for label in x["folders"]:
            node = node["folders"].setdefault(label, {"files": [], "folders": {}})
        node["files"].append(x)
    return tree
