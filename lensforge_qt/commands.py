"""Front-end-neutral command defaults shared by the Qt app and the web app (no Qt).

The default toolbar, short toolbar captions and the File > Sample Lenses list.
"""

from __future__ import annotations

import os

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
