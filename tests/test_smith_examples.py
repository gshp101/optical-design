"""The Smith "Modern Lens Design" examples must reproduce the book's paraxial data."""
import glob
import os
import re

import numpy as np
import pytest

import lensforge as lf

HERE = os.path.dirname(os.path.abspath(__file__))
MODELS = sorted(glob.glob(os.path.join(HERE, "..", "examples", "ModernLensDesignSmith", "*", "Figure *.lens.json")))
# Figures entered exactly as printed whose printed table does not reproduce the book's own EFL/BFL
BOOK_TABLE_MISMATCH = {
    "Figure 13.14": "the table gives the last surface as plane; a radius near -340 would reproduce the book's EFL",
    "Figure 15.2": "the book's EFL 151.5 is n' f with n' = 1.515, but the table's image medium is K5 (1.522)",
}


@pytest.mark.parametrize("path", MODELS, ids=[os.path.basename(p).removesuffix(".lens.json") for p in MODELS])
def test_matches_book(path):
    lens = lf.load(path)
    name = os.path.basename(path).removesuffix(".lens.json")
    book = dict(re.findall(r"\b(EFL|BFL) (-?[\d.]+)", lens.notes))
    p = lens.paraxial()
    if name in BOOK_TABLE_MISMATCH:
        p = None
    # 0.15 mm allows for glasses entered from rounded book nd/Vd (Fig. 6.6 LAK17, Figs 7.9/7.22 SF52)
    if p is not None:
        # the book's EFL is n' f, which differs from f only for an image inside an immersion medium (Chapter 15)
        assert p.efl * p.n_image == pytest.approx(float(book["EFL"]), abs=0.15)
        # the book's BFL is the image distance for the actual object (the same as BFL at infinite conjugate)
        assert p.image_distance == pytest.approx(float(book["BFL"]), abs=0.15)
    g = np.linspace(-1, 1, 11)
    X, Y = np.meshgrid(g, g)
    m = X**2 + Y**2 <= 1
    for w in lens.wavelengths:
        r = lens.trace(0.0, 0.0, X[m], Y[m], wavelength=w.value)
        assert r.valid.all(), f"{np.count_nonzero(~r.valid)} axial rays lost at {w.value} um"
        # off axis the book's semi-apertures may vignette (e.g. Fig. 7.2), but the chief ray must pass
        for hy in (0.7, 1.0):
            assert lens.trace(0.0, hy, np.zeros(1), np.zeros(1), wavelength=w.value).valid.all()


def test_models_found():
    assert len(MODELS) >= 147
