"""The Arducam LK004 example models must pass their full axial beam (no TIR, no clipping)."""
import glob
import os

import numpy as np
import pytest

import lensforge as lf

HERE = os.path.dirname(os.path.abspath(__file__))
MODELS = sorted(glob.glob(os.path.join(HERE, "..", "examples", "arducam-lk004", "*.lens.json")))


@pytest.mark.parametrize("path", MODELS, ids=[os.path.basename(p).split(".")[0] for p in MODELS])
def test_axial_beam_unvignetted(path):
    lens = lf.load(path)
    g = np.linspace(-1, 1, 21)
    X, Y = np.meshgrid(g, g)
    m = X**2 + Y**2 <= 1
    for w in lens.wavelengths:
        r = lens.trace(0.0, 0.0, X[m], Y[m], wavelength=w.value)
        assert r.valid.all(), f"{np.count_nonzero(~r.valid)} axial rays lost at {w.value} um"
    spot = lf.spot_diagram(lens, 0)
    assert spot["n_rays"] == spot["n_launched"]


def test_models_found():
    assert len(MODELS) == 5


@pytest.mark.parametrize("path", MODELS, ids=[os.path.basename(p).split(".")[0] for p in MODELS])
def test_no_filter_and_focal_length_in_name(path):
    lens = lf.load(path)
    assert not any(s.material and s.curvature == 0 for s in lens.surfaces[1:lens.image_index])
    f = int(os.path.basename(path).split("_")[1].removesuffix("mm.lens.json"))
    assert lens.paraxial().efl == pytest.approx(f, abs=1e-3)
