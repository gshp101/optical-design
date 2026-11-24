"""Stock lens catalogs: .ZMF / .zmx import, search, insert (lensforge.stock)."""

import math

import pytest

import lensforge as lf
from lensforge import stock as ST


@pytest.fixture
def lib():
    return lf.StockLibrary(ST.demo_lenses())


def test_demo_parts_have_their_nominal_focal_lengths(lib):
    assert len(lib.lenses) >= 15
    for x in lib.lenses:
        f = float(x.part.split("-")[3].replace("M", "-"))
        assert x.efl == pytest.approx(f, rel=1e-6), x.part
        assert x.system().paraxial().efl == pytest.approx(f, rel=1e-4), x.part  # the stored text agrees
        assert x.vendor == "LensForge Demo" and x.diameter > 0 and x.glasses


def test_classification(lib):
    kinds = {x.part: x.kind for x in lib.lenses}
    assert kinds["LFD-PCX-25-50"] == "plano-convex"
    assert kinds["LFD-PCV-25-M50"] == "plano-concave"
    assert kinds["LFD-DCX-25-50"] == "bi-convex"
    assert kinds["LFD-DCV-25-M50"] == "bi-concave"
    assert kinds["LFD-MEN-25-100"] == "positive meniscus"
    assert kinds["LFD-MEN-25-M100"] == "negative meniscus"
    assert kinds["LFD-ACH-25-50"] == "cemented doublet"
    assert lib.get("LFD-ACH-25-50").elements == 2


def test_search_by_properties(lib):
    hits = lib.search(kind="plano-convex", efl=(40, 110), diameter=(20, 30), glass="bk7")
    assert [x.part for x in hits] == ["LFD-PCX-25-50", "LFD-PCX-25-100"]
    near = lib.search(efl=100)  # one number = +-5 %, closest first
    assert {x.part for x in near} == {"LFD-PCX-25-100", "LFD-PCX-50-100", "LFD-DCX-25-100",
                                      "LFD-MEN-25-100", "LFD-ACH-25-100"}
    assert all(x.efl < 0 for x in lib.search(positive=False))
    assert lib.search(kind="meniscus", positive=True)[0].part == "LFD-MEN-25-100"
    assert [x.part for x in lib.search(elements=2, diameter=(0, 15))] == ["LFD-ACH-12-30"]
    assert lib.search(text="doublet", limit=2)[0].kind == "cemented doublet"
    assert lib.search(vendor="nobody") == []
    assert [x.part for x in lib.search(glass="SILICA")] == ["LFD-PCX-25-50-FS"]


def test_insert_comments_and_reverse(lib):
    lens = lf.samples.singlet()
    n0 = lens.num_surfaces
    part = lib.get("LFD-ACH-25-50")
    rng = lf.insert_stock_lens(lens, part, at=1)
    assert list(rng) == [1, 2, 3] and lens.num_surfaces == n0 + 3
    assert lens.surfaces[1].comment == "LFD-ACH-25-50 (LensForge Demo)"
    assert lens.surfaces[3].comment == "LFD-ACH-25-50 (LensForge Demo)"
    assert lens.surfaces[2].comment == ""
    assert lens.surfaces[1].material == "N-BK7" and lens.surfaces[2].material == "N-SF5"
    assert lens.surfaces[1].semi_diameter == pytest.approx(12.7)

    rev = lf.samples.singlet()
    rng = lf.insert_stock_lens(rev, "LFD-ACH-25-50", at=1, reverse=True, library=lib)
    s = rev.surfaces
    assert s[1].comment == s[3].comment == "LFD-ACH-25-50 (LensForge Demo), reversed"
    assert s[1].material == "N-SF5" and s[2].material == "N-BK7" and s[3].material in (None, "", "AIR")
    fwd = lens.surfaces
    assert s[1].curvature == pytest.approx(-fwd[3].curvature)
    assert s[3].curvature == pytest.approx(-fwd[1].curvature)
    # same element, so the same focal length either way round
    a = lf.OpticalSystem("a")
    lf.insert_stock_lens(a, part)
    b = lf.OpticalSystem("b")
    lf.insert_stock_lens(b, part, reverse=True)
    for t in (a, b):
        t.set_aperture("EPD", 5)
    assert a.paraxial().efl == pytest.approx(50, rel=1e-6)
    assert b.paraxial().efl == pytest.approx(50, rel=1e-6)
    # each way round the last thickness is that orientation's back focal distance
    assert a.surfaces[3].thickness == pytest.approx(a.paraxial().bfl, abs=1e-4)
    assert b.surfaces[3].thickness == pytest.approx(b.paraxial().bfl, abs=1e-4)
    assert abs(a.surfaces[3].thickness - b.surfaces[3].thickness) > 1


def test_insert_renumbers_variables(lib):
    lens = lf.samples.singlet()
    lf.optimize.vary_curvatures(lens)
    before = sorted(v.surface for v in lf.optimize.variables(lens))
    lf.insert_stock_lens(lens, lib.get("LFD-PCX-25-50"), at=1)
    after = sorted(v.surface for v in lf.optimize.variables(lens))
    assert after == [i + 2 for i in before]


def test_zmf_round_trip(lib, tmp_path):
    p = tmp_path / "MY VENDOR.ZMF"
    ST.write_zmf(str(p), lib.lenses)
    raw = p.read_bytes()
    assert raw[:4] == (1001).to_bytes(4, "little")
    assert b"SURF" not in raw  # the prescriptions are masked
    other = lf.StockLibrary()
    got = other.import_file(str(p))
    assert len(got) == len(lib.lenses)
    for a, b in zip(lib.lenses, got):
        assert b.part == a.part and b.zmx == a.zmx
        assert b.vendor == "My Vendor" and b.catalog == "MY VENDOR"
        assert b.efl == pytest.approx(a.efl) and b.kind == a.kind
    assert other.catalogs == ["MY VENDOR"]
    with pytest.raises(ValueError):
        ST.read_zmf(b"\x00\x00\x00\x00")


def test_zmf_mask_matches_exact_formatting():
    import random
    random.seed(3)
    data = bytes(random.getrandbits(8) for _ in range(5000))
    efl, epd = 37.25, 12.5
    iv = math.cos(6 * efl + 3 * epd)
    iv = math.cos(655 * (math.pi / 180) * iv) + iv
    slow = bytes(b ^ ST._zmf_key_slow(13.2 * (iv + math.sin(17 * (p + 3))) * (p + 1)) for p, b in enumerate(data))
    assert ST._zmf_mask(data, efl, epd) == slow
    assert ST._zmf_mask(slow, efl, epd) == data


VENDOR_ZMX = """VERS 150514 200 30221
MODE SEQ
NAME Aspheric Lens, f=20 mm
NOTE 0 FOR INFORMATION ONLY. CONTACT TECHSUPPORT@THORL
NOTE 0 ABS.COM
UNIT MM X W X CM MR CPMM
ENPD 1.0E+1
WAVM 1 5.875618E-1 1
PWAV 1
SURF 0
  TYPE STANDARD
  CURV 0.0
  DISZ INFINITY
SURF 1
  TYPE STANDARD
  CURV 0.0
  DISZ 1.0
  STOP
SURF 2
  TYPE EVENASPH
  CURV 0.0975
  DISZ 4.0
  GLAS UNOBTAINIUM 0 0 1.5875 6.0E+1 0 0 0 0 0 0
  CONI -0.6
  DIAM 6.0 1 0 0 1 ""
SURF 3
  TYPE STANDARD
  CURV 0.0
  DISZ 17.5
  DIAM 6.0 1 0 0 1 ""
SURF 4
  TYPE STANDARD
  CURV 0.0
  DISZ 0
"""


def test_vendor_zmx_import_guesses_and_substitutes(tmp_path):
    p = tmp_path / "AL1220-Zemax(ZMX).zmx"
    p.write_bytes(VENDOR_ZMX.replace("\n", "\r\n").encode("utf-16"))
    lib = lf.StockLibrary()
    (x,) = lib.import_file(str(p))
    assert x.part == "AL1220" and x.vendor == "Thorlabs" and x.catalog == "Thorlabs"
    assert x.kind == "plano-convex" and x.aspheric and x.diameter == pytest.approx(12)
    assert x.element_range() == (2, 3)  # the maker's dummy stop surface is skipped
    assert x.missing_glasses() == {"UNOBTAINIUM": "1.5875,60"}
    assert x.efl == pytest.approx(1 / (0.5875 * 0.0975), rel=1e-6)
    lens = lf.OpticalSystem("t")
    rng = lf.insert_stock_lens(lens, x)
    assert list(rng) == [1, 2]
    assert lens.surfaces[1].material == "1.5875,60" and lens.surfaces[1].comment == "AL1220 (Thorlabs)"
    lens2 = lf.OpticalSystem("t")
    lf.insert_stock_lens(lens2, x, substitute_missing=False)
    assert lens2.surfaces[1].material == "UNOBTAINIUM"


def test_save_load_and_remove(lib, tmp_path):
    p = tmp_path / "VENDOR.ZMF"
    ST.write_zmf(str(p), lib.lenses[:3])
    user = tmp_path / "home" / "stock_lenses.json"
    a = lf.StockLibrary.default(path=str(user))
    n_demo = len(a.lenses)
    a.import_file(str(p))
    a.save()
    b = lf.StockLibrary.default(path=str(user))
    assert len(b.lenses) == n_demo + 3 and "VENDOR" in b.catalogs
    assert b.remove_catalog("VENDOR") == 3
    b.save()
    assert len(lf.StockLibrary.default(path=str(user)).lenses) == n_demo
    assert "LensForge Demo" not in str(user.read_text())  # demo parts are not saved


def test_default_library_honours_lensforge_home(tmp_path, monkeypatch):
    monkeypatch.setenv("LENSFORGE_HOME", str(tmp_path))
    assert ST.user_library_path() == str(tmp_path / "stock_lenses.json")


def _write_folder(tmp_path, lib):
    d = tmp_path / "my parts"
    (d / "sub").mkdir(parents=True)
    (d / "AL1220-Zemax(ZMX).zmx").write_bytes(VENDOR_ZMX.replace("\n", "\r\n").encode("utf-16"))
    (d / "sub" / "LB1761.ZMX").write_text(VENDOR_ZMX.replace("f=20 mm", "LB1761"))
    ST.write_zmf(str(d / "ACME OPTICS.ZMF"), lib.lenses[:3])
    (d / "readme.pdf").write_bytes(b"%PDF")
    (d / "broken.zmf").write_bytes(b"\x00\x00\x00\x00")
    return d


def test_import_folder_one_catalog_and_reload(lib, tmp_path):
    d = _write_folder(tmp_path, lib)
    user = tmp_path / "home" / "stock_lenses.json"
    a = lf.StockLibrary.default(path=str(user))
    r = a.import_folder(str(d))
    assert r.catalog == "my parts"
    assert r.files == 3 and len(r.lenses) == 5
    assert r.skipped == ["readme.pdf"] and len(r.errors) == 1 and "broken.zmf" in r.errors[0]
    assert "5 part(s) from 3 file(s)" in str(r) and "could not be read" in r.report()
    got = {x.part: x for x in a.search(catalog="my parts")}
    assert set(got) == {"AL1220", "LB1761"} | {x.part for x in lib.lenses[:3]}
    assert got["AL1220"].vendor == "Thorlabs" and got[lib.lenses[0].part].vendor == "Acme Optics"
    assert "my parts" in a.catalogs
    a.save()
    b = lf.StockLibrary.default(path=str(user))   # remembered between sessions
    assert len(b.search(catalog="my parts")) == 5
    # files deleted from the folder vanish when it is loaded again; new ones appear
    (d / "ACME OPTICS.ZMF").unlink()
    (d / "LA1131.zmx").write_text(VENDOR_ZMX)
    r2 = b.import_folder(str(d))
    assert {x.part for x in b.search(catalog="my parts")} == {"AL1220", "LB1761", "LA1131"}
    assert len(r2.lenses) == 3
    # not recursive, own name, forced vendor
    c = lf.StockLibrary()
    r3 = c.import_folder(str(d), catalog="Top", vendor="Me", recursive=False)
    assert {x.part for x in r3.lenses} == {"AL1220", "LA1131"} and {x.vendor for x in r3.lenses} == {"Me"}
    with pytest.raises(FileNotFoundError):
        c.import_folder(str(tmp_path / "nope"))
    with pytest.raises(ValueError):
        c.import_files([], ST.DEMO_CATALOG)


def test_import_zip_and_duplicates(lib, tmp_path):
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("parts/AL1220.zmx", VENDOR_ZMX)
        z.writestr("parts/copy/AL1220.zmx", VENDOR_ZMX)
        z.writestr("parts/notes.txt", "x")
    p = tmp_path / "thorlabs.zip"
    p.write_bytes(buf.getvalue())
    x = lf.StockLibrary()
    got = x.import_file(str(p))
    assert [g.part for g in got] == ["AL1220"] and x.catalogs == ["thorlabs"]
    r = x.import_files([("thorlabs.zip", buf.getvalue())], "T")
    assert len(r.duplicates) == 1 and "duplicate" in str(r)
    r = x.import_files([("bad.zip", b"not a zip")], "T")
    assert r.errors and not r.lenses


def test_table_sort_numbers_text_and_missing_values():
    from lensforge_qt import stock_table as T
    a = ST.StockLens("LA11310", vendor="B", efl=50.0)
    b = ST.StockLens("LA1131", vendor="a", efl=-20.0)
    c = ST.StockLens("LA2", vendor="C")  # no focal length
    assert [x.part for x in T.sort_lenses([a, b, c], "Part")] == ["LA2", "LA1131", "LA11310"]
    assert [x.part for x in T.sort_lenses([a, b, c], "EFL")] == ["LA1131", "LA11310", "LA2"]
    assert [x.part for x in T.sort_lenses([a, b, c], "EFL", True)] == ["LA11310", "LA1131", "LA2"]
    assert [x.part for x in T.sort_lenses([a, b, c], "Vendor")] == ["LA1131", "LA11310", "LA2"]
    assert T.sort_lenses([a, b], None) == [a, b] and T.sort_lenses([a, b], "nope") == [a, b]
