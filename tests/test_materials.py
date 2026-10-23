import math

import numpy as np
import pytest

import lensforge as lf
from lensforge.materials import LAMBDA_C, LAMBDA_F, LAMBDA_d, default_library, load_agf


LIB = default_library()


@pytest.mark.parametrize("glass", [g for g in LIB.all_glasses() if g.nd_catalog is not None], ids=lambda g: g.name)
def test_builtin_glasses_match_catalog(glass):
    assert glass.nd == pytest.approx(glass.nd_catalog, abs=2e-5)
    assert glass.vd == pytest.approx(glass.vd_catalog, abs=0.05)


def test_index_is_vectorised():
    g = LIB.resolve("N-BK7")
    w = np.array([LAMBDA_F, LAMBDA_d, LAMBDA_C])
    n = g.index(w)
    assert n.shape == (3,) and n[0] > n[1] > n[2]


def test_model_glass_exact_nd_vd():
    m = LIB.resolve("1.6,40")
    assert m.nd == pytest.approx(1.6, abs=1e-12)
    assert m.vd == pytest.approx(40, abs=1e-9)


def test_specs():
    assert LIB.resolve(None).nd == 1.0
    assert LIB.resolve("AIR").nd == 1.0
    assert LIB.resolve(1.7).nd == 1.7
    assert LIB.resolve("MIRROR").is_mirror
    assert LIB.resolve("schott:n-bk7").name == "N-BK7"
    with pytest.raises(KeyError):
        LIB.resolve("UNOBTAINIUM")


AGF = """CC Test catalog
NM N-BK7 2 517642.251 1.5168 64.167336 0 1
GC
ED 7.1 -0.0 2.51 0 0
CD 1.03961212 0.00600069867 0.231792344 0.0200179144 1.01046945 103.560653 0 0 0 0
TD 1.86E-06 1.31E-08 -1.37E-11 4.34E-07 6.27E-10 0.17 20
LD 0.3 2.5
NM MYSCHOTT 1 0 1.5 60 0 1
CD 2.25 0 0 0 0 0
"""


def test_agf_loader():
    cat = load_agf(AGF, "TEST")
    assert len(cat) == 2
    assert cat.get("N-BK7").nd == pytest.approx(1.5168, abs=1e-5)
    assert cat.get("MYSCHOTT").index(0.55) == pytest.approx(1.5)
    lib = lf.MaterialLibrary([cat])
    assert lib.resolve("TEST:N-BK7").wavelength_range == (0.3, 2.5)
