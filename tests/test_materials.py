import math

import numpy as np
import pytest

import lensforge as lf
from lensforge.materials import LAMBDA_C, LAMBDA_F, LAMBDA_d, default_library, load_agf


LIB = default_library()


@pytest.mark.parametrize("glass", [g for g in LIB.all_glasses() if g.nd_catalog is not None], ids=lambda g: g.name)
def test_builtin_glasses_match_catalog(glass):
    # Sumita lists vd to 0.1 and its power-series fit leaves ~1e-5 residuals (nd of K-VC89 is 1.80998).
    sumita = glass.catalog == "SUMITA"
    assert glass.nd == pytest.approx(glass.nd_catalog, abs=5e-5 if sumita else 2e-5)
    assert glass.vd == pytest.approx(glass.vd_catalog, abs=0.3 if sumita else 0.05)


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


# ---------------------------------------------------------------------------
# Other makers' catalogs and glass search
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("cat,name,nd,vd", [
    ("OHARA", "S-BSL7", 1.51633, 64.14), ("OHARA", "S-LAH66", 1.7725, 49.6),
    ("HOYA", "E-FD1", 1.71736, 29.5), ("HOYA", "TAF1", 1.7725, 49.6),
    ("CDGM", "H-K9L", 1.5168, 64.2), ("CDGM", "H-ZF52", 1.84666, 23.8),
    ("SUMITA", "K-VC89", 1.81, 41.0), ("HIKARI", "J-LASF016", 1.7725, 49.6),
])
def test_vendor_catalog_glasses(cat, name, nd, vd):
    g = LIB.resolve(f"{cat}:{name}")
    assert g.catalog == cat and g.extra["status"] != "obsolete"
    assert g.nd == pytest.approx(nd, abs=5e-5) and g.vd == pytest.approx(vd, abs=0.3)


def test_vendor_catalog_sizes_and_precedence():
    sizes = {c: len(LIB.catalogs[c]) for c in ("SCHOTT", "OHARA", "HOYA", "CDGM", "SUMITA", "HIKARI")}
    assert all(n > 100 for n in sizes.values()), sizes
    assert list(LIB.catalogs)[:6] == list(sizes)
    # plain names resolve to the first catalog that has them (F2 is in SCHOTT and CDGM)
    assert LIB.resolve("F2").catalog == "SCHOTT" and LIB.resolve("CDGM:F2").catalog == "CDGM"
    # obsolete OHARA / HOYA glasses kept for legacy designs
    assert LIB.resolve("LAM61").catalog == "OHARA" and LIB.resolve("BAF2").catalog == "HOYA"


def test_glass_search_substring():
    hits = LIB.search("bk7")
    assert hits[0] == "N-BK7" and {"N-BK7HT", "P-BK7", "K-BK7"} <= set(hits)
    assert LIB.search("nbk7")[0] == "N-BK7" and "N-BK7" in LIB.search("N-bk")
    assert LIB.search("k9l")[0] == "H-K9L"
    assert LIB.search("lah66")[0] == "S-LAH66"
    # duplicate names: the plain spec is the one find() returns, the others are qualified
    assert LIB.search("f2")[:2] == ["F2", "CDGM:F2"]
    cdgm = LIB.search("cdgm:f2")
    assert cdgm[0] == "CDGM:F2" and all(s.startswith("CDGM:") for s in cdgm)
    for spec in LIB.search("sf6", limit=20):
        LIB.resolve(spec)
    assert LIB.search("unobtainium") == []
