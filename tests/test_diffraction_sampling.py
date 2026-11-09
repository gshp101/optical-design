"""Pupil / image (FFT padding) / pixel sampling settings of the PSF and MTF windows."""

import numpy as np

import lensforge as lf
from lensforge_qt.analyses import REGISTRY

DIFFRACTION = ("psf", "psf_cross", "mtf", "through_focus_mtf", "mtf_vs_field", "encircled_energy")


def test_sampling_settings_present():
    for key in DIFFRACTION:
        names = [s.name for s in REGISTRY[key].settings]
        assert "pupil_n" in names and "image_n" in names, key
    for key in ("psf", "psf_cross"):
        assert "pixel_um" in [s.name for s in REGISTRY[key].settings]


def test_image_sampling_refines_mtf_frequency_step():
    s = lf.samples.achromat()
    mtf = REGISTRY["mtf"].compute
    auto = mtf(s, field=0, pupil_n=32)[0][1]
    padded = mtf(s, field=0, pupil_n=32, image_n=256)[0][1]
    step = lambda r: r["freq"][1] - r["freq"][0]  # noqa: E731
    assert step(padded) < step(auto) / 3
    assert np.isclose(auto["cutoff"], padded["cutoff"], rtol=1e-3)
    assert REGISTRY["mtf"].compute(s, field=0, method="geometric", pupil_n=32)[0][1]["method"] == "geometric"


def test_psf_pixel_and_image_sampling():
    s = lf.samples.achromat()
    psf = REGISTRY["psf"].compute
    base = psf(s, pupil_n=32)
    fine = psf(s, pupil_n=32, image_n=128, pixel_um=0.5)
    assert fine["psf"].shape == (128, 128)
    assert np.isclose(fine["dx"], 0.5e-3)
    assert base["psf"].shape == (64, 64)
    assert psf(s, method="huygens", pupil_n=32, image_n=64)["psf"].shape == (64, 64)
