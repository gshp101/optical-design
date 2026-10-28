"""The Smith "Modern Lens Design" examples must reproduce the book's paraxial data."""
import glob
import os
import re

import numpy as np
import pytest

import lensforge as lf

HERE = os.path.dirname(os.path.abspath(__file__))
MODELS = sorted(glob.glob(os.path.join(HERE, "..", "examples", "ModernLensDesignSmith", "*", "Figure *.lens.json")))


@pytest.mark.parametrize("path", MODELS, ids=[os.path.basename(p).removesuffix(".lens.json") for p in MODELS])
def test_matches_book(path):
    lens = lf.load(path)
    book = dict(re.findall(r"\b(EFL|BFL) (-?[\d.]+)", lens.notes))
    p = lens.paraxial()
    # 0.15 mm allows for glasses entered from rounded book nd/Vd (Fig. 6.6 LAK17)
    assert p.efl == pytest.approx(float(book["EFL"]), abs=0.15)
    assert p.bfl == pytest.approx(float(book["BFL"]), abs=0.15)
    g = np.linspace(-1, 1, 11)
    X, Y = np.meshgrid(g, g)
    m = X**2 + Y**2 <= 1
    for hy in (0.0, 0.7, 1.0):
        for w in lens.wavelengths:
            r = lens.trace(0.0, hy, X[m], Y[m], wavelength=w.value)
            assert r.valid.all(), f"{np.count_nonzero(~r.valid)} rays lost at hy={hy}, {w.value} um"


def test_models_found():
    assert len(MODELS) >= 15
