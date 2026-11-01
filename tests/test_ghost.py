"""Ghost analysis (two-bounce reflections) in sequential systems."""

import math

import numpy as np
import pytest

import lensforge as lf


def plate_after_singlet():
    s = lf.samples.singlet()
    t = s.surfaces[2].thickness
    s.surfaces[2].thickness = 20
    s.add_surface(radius=math.inf, thickness=3, material="N-BK7")
    s.add_surface(radius=math.inf, thickness=t - 23)
    lf.samples.focus_paraxial(s)
    return s


def test_ghost_pairs_and_system_layout():
    s = plate_after_singlet()
    assert lf.ghost_pairs(s) == [(2, 1), (3, 1), (3, 2), (4, 1), (4, 2), (4, 3)]
    assert (5, 4) in lf.ghost_pairs(s, include_image=True)
    g = lf.ghost_system(s, 4, 2)
    assert g.ghost_map == [0, 1, 2, 3, 4, 3, 2, 3, 4, 5]
    mats = [x.material for x in g.surfaces]
    assert mats[4] == "MIRROR" and mats[6] == "MIRROR"
    assert mats[5] in (None, "", "AIR")  # backwards through surface 3: the air before it
    assert g.surfaces[5].thickness == pytest.approx(-20)
    assert g.surfaces[6].thickness == pytest.approx(20)
    # the original lens is untouched
    assert s.num_surfaces == 6 and all(x.material != "MIRROR" for x in s.surfaces)


def test_plate_ghost_focus_shift_is_2t_over_n():
    s = plate_after_singlet()
    r = lf.ghost_focus(s, sort="pairs")
    row = [x for x in r["rows"] if (x["i"], x["j"]) == (4, 3)][0]
    n = s.material(3).index(s.primary)
    assert row["focus_distance"] == pytest.approx(-2 * 3 / n, rel=1e-9)
    R = ((n - 1) / (n + 1)) ** 2
    assert row["R_i"] == pytest.approx(R) and row["R_j"] == pytest.approx(R)
    assert row["R"] == pytest.approx(R * R)
    assert row["throughput"] == 1.0
    # the brightest ghost is the plate ghost (focused nearest the image)
    assert (lf.ghost_focus(s)["rows"][0]["i"], lf.ghost_focus(s)["rows"][0]["j"]) == (4, 3)
    assert "4-3" in lf.format_ghost_table(r)


def test_real_rays_focus_where_the_paraxial_ghost_focuses():
    s = lf.samples.singlet()
    r = lf.ghost_focus(s, real_rays=False)
    row = r["rows"][0]
    assert (row["i"], row["j"]) == (2, 1)
    t = lf.ghost_trace(s, 2, 1, 0.0, 0.0, 0.0, [0.0, 0.002])
    y, d = t.positions[-1, 1, 1], t.directions[-1, 1]
    z_cross = -y * d[2] / d[1]  # where the near-axis ray crosses the axis, from the image surface
    assert z_cross == pytest.approx(row["focus_distance"], rel=1e-4)


def test_ghost_image_power_with_constant_coating():
    s = lf.samples.achromat()
    im = lf.ghost_image(s, 0, coating=0.01, fresnel_losses=False, n_rays=24, pixels=41, half_width=2000)
    assert len(im["pairs"]) == 3
    p = dict(zip(map(tuple, im["pairs"]), im["pair_power"]))
    assert p[(3, 1)] == pytest.approx(1e-4, rel=1e-9) and p[(3, 2)] == pytest.approx(1e-4, rel=1e-9)
    assert 0 < p[(2, 1)] < 1e-4  # the edge of this ghost beam is totally reflected at the last surface
    assert im["nominal_power"] == pytest.approx(1.0)
    dA = (im["x"][1] - im["x"][0]) ** 2
    assert im["ghost"].sum() * dA == pytest.approx(im["ghost_power"], rel=1e-9)
    # uncoated, angle-dependent Fresnel: the cemented interface reflects much less than the air surfaces
    im = lf.ghost_image(s, 1, n_rays=24, pixels=41)
    p = dict(zip(map(tuple, im["pairs"]), im["pair_power"]))
    assert p[(3, 1)] > 10 * p[(2, 1)]
    assert 0.85 < im["nominal_power"] < 0.95


def test_coating_dict_and_image_reflectance():
    s = lf.samples.singlet()
    r = lf.ghost_focus(s, coating={1: 0.002}, include_image=True, image_reflectance=0.1, sort="pairs")
    rows = {(x["i"], x["j"]): x for x in r["rows"]}
    assert set(rows) == {(2, 1), (3, 1), (3, 2)}
    assert rows[(3, 1)]["R"] == pytest.approx(0.1 * 0.002)
    assert rows[(2, 1)]["R_j"] == pytest.approx(0.002)


def test_ghost_layout_and_unsupported_groups():
    s = lf.samples.achromat()
    L = lf.ghost_layout(s, 3, 1, n_rays=5)
    assert L["path"].shape[1] == 5 and L["pair"] == (3, 1)
    s.insert(2, lf.CoordinateBreak(tilt_x=1.0))
    with pytest.raises(NotImplementedError):
        lf.ghost_system(s, 4, 1)
    assert (4, 3) in lf.ghost_pairs(s) and (4, 1) not in lf.ghost_pairs(s)
