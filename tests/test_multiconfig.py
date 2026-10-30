"""Multi-configuration: the table, switching, save/load, CONF merit rows and optimisation across configurations."""
import math
import os

import pytest

import lensforge as lf
from lensforge import optimize as opt
from lensforge.multiconfig import MultiConfigError, format_value, parse_value

HERE = os.path.dirname(os.path.abspath(__file__))
ZOOM = os.path.join(HERE, "..", "examples", "ModernLensDesignSmith", "Chapter 20 - Zoom Lenses")


def two_focus_singlet():
    """A singlet focused at infinity (config 1) and at 500 mm (config 2)."""
    lens = lf.samples.singlet()
    mc = lf.MultiConfig.create(lens, 2, ["far", "near"])
    mc.add_row(lens, "THIC", 0, values=[math.inf, 500.0])
    mc.add_row(lens, "THIC", lens.image_index - 1)
    return lens, mc


def test_create_and_switch():
    lens, mc = two_focus_singlet()
    assert lens.num_configs == 2 and lens.current_config == 1
    assert math.isinf(lens.surfaces[0].thickness)
    lens.set_config(2)
    assert lens.surfaces[0].thickness == 500.0 and lens.current_config == 2
    lens.set_config(1)
    assert math.isinf(lens.surfaces[0].thickness)
    with pytest.raises(IndexError):
        lens.set_config(3)


def test_edits_to_the_lens_are_kept_per_configuration():
    lens, mc = two_focus_singlet()
    bf = lens.image_index - 1
    lens.surfaces[bf].thickness = 40.0  # edit config 1 in the lens itself
    lens.set_config(2)
    lens.surfaces[bf].thickness = 45.0
    lens.set_config(1)
    assert lens.surfaces[bf].thickness == 40.0
    assert mc.value(1, 2) == 45.0
    # uncontrolled parameters are shared by all configurations
    lens.surfaces[1].thickness = 7.0
    assert lens.config_copy(2).surfaces[1].thickness == 7.0


def test_config_copy_leaves_the_lens_alone():
    lens, mc = two_focus_singlet()
    c = lens.config_copy(2)
    assert c.current_config == 2 and c.surfaces[0].thickness == 500.0
    assert lens.current_config == 1 and math.isinf(lens.surfaces[0].thickness)
    assert len(lf.config_systems(lens)) == 2


def test_operands_read_and_write_every_kind_of_parameter():
    lens = lf.samples.achromat()
    lens.set_fields([0, 3, 5])
    lens.set_wavelengths([0.5876, 0.4861, 0.6563])
    mc = lf.MultiConfig.create(lens, 2)
    rows = [("CRVT", 1, None, 0.01), ("CONN", 1, None, -0.5), ("GLSS", 2, None, "N-SF5"), ("SDIA", 1, None, 9.0),
            ("PARM", 3, "conic", -0.25), ("APER", None, None, 12.0), ("YFIE", 2, None, 7.0), ("XFIE", 1, None, 1.0),
            ("FLWT", 0, None, 2.0), ("WAVE", 1, None, 0.48), ("WLWT", 2, None, 0.5), ("PRWV", None, None, 1),
            ("STPS", None, None, 2), ("FVDY", 1, None, 0.1)]
    for t, ref, param, v in rows:
        r = mc.add_row(lens, t, ref, param)
        mc.set_value(lens, len(mc.rows) - 1, 2, v)
        assert r.values[0] == r.get(lens)  # config 1 holds the lens's value
    lens.set_config(2)
    for t, ref, param, v in rows:
        r = [x for x in mc.rows if (x.type, x.ref, x.param) == (t, ref, param)][0]
        assert r.get(lens) == v, t
    assert lens.stop_index == 2 and lens.primary_wavelength == 1
    lens.set_config(1)
    assert lens.stop_index == 1 and lens.surfaces[2].material != "N-SF5"


def test_bad_references_are_reported_not_fatal():
    lens, mc = two_focus_singlet()
    mc.add_row(None, "THIC", 40, values=[1.0, 2.0])
    assert mc.errors(lens)[-1] and "no surface 40" in mc.errors(lens)[-1]
    lens.set_config(2)  # the bad row is skipped
    with pytest.raises(MultiConfigError):
        mc.rows[-1].get(lens)
    assert "!" in mc.table(lens)


def test_insert_and_remove_configurations():
    lens, mc = two_focus_singlet()
    k = mc.insert_config(lens, copy_from=2, name="mid")
    assert k == 3 and mc.n_configs == 3 and mc.value(0, 3) == 500.0
    mc.set_value(lens, 0, 3, "1000")
    assert mc.value(0, 3) == 1000.0
    k = mc.insert_config(lens, at=1, name="first")
    assert mc.names == ["first", "far", "near", "mid"] and mc.current == 2
    lens.set_config(4)
    mc.remove_config(lens, 4)
    assert mc.current == 3 and lens.surfaces[0].thickness == 500.0
    with pytest.raises(ValueError):
        lf.MultiConfig.create(lens, 1).remove_config(lens, 1)


def test_save_and_load_round_trip(tmp_path):
    lens, mc = two_focus_singlet()
    mc.add_row(lens, "GLSS", 1, values=["N-BK7", "1.6,40"])
    opt.set_mc_variable(lens, 1, 2)
    lens.set_config(2)
    lens.surfaces[lens.image_index - 1].thickness = 47.5
    p = tmp_path / "mc.lens.json"
    lf.save(lens, str(p))
    text = p.read_text()
    assert '"multiconfig"' in text and '"inf"' in text and '"mc_row": 1' in text
    back = lf.load(str(p))
    assert back.current_config == 2 and back.surfaces[0].thickness == 500.0
    assert back.surfaces[back.image_index - 1].thickness == 47.5  # captured before saving
    assert back.multiconfig.names == ["far", "near"]
    assert isinstance(back.variables[-1], opt.MCVariable)
    back.set_config(1)
    assert math.isinf(back.surfaces[0].thickness) and back.surfaces[1].material == "N-BK7"


def test_surface_insertion_and_deletion_renumber_the_table():
    lens, mc = two_focus_singlet()
    bf = lens.image_index - 1
    mc.add_row(lens, "STPS", values=[1, 1])
    opt.set_mc_variable(lens, 1, 1)
    lf.compose.renumber_surface_refs(lens, lambda i: i + 1 if i >= 1 else i)  # as if a surface went in at 1
    assert mc.rows[1].ref == bf + 1 and mc.rows[2].values == [2, 2]
    lf.compose.renumber_surface_refs(lens, lambda i: None if i == bf + 1 else i)
    assert [r.type for r in mc.rows] == ["THIC", "STPS"]
    assert not any(isinstance(v, opt.MCVariable) for v in lens.variables)  # its row is gone


def test_cell_text():
    lens, mc = two_focus_singlet()
    assert parse_value(mc.rows[0], "Infinity") == math.inf
    assert format_value(mc.rows[0], math.inf) == "Infinity"
    sd = mc.add_row(lens, "SDIA", 1)
    assert parse_value(sd, "auto") is None and format_value(sd, None) == "auto"
    assert format_value(mc.add_row(lens, "GLSS", 1, values=[{"model": [1.6, 40, 0]}] * 2), {"model": [1.6, 40, 0]}) \
        == "1.6,40"


def test_conf_rows_switch_configuration_and_restore_it():
    lens, mc = two_focus_singlet()
    mf = opt.MeritFunction()
    mf.add("CONF", weight=0, cfg=2)
    mf.add("PMAG", 0, 0)
    mf.add("CONF", weight=0, cfg=1)
    mf.add("PMAG", 0, 0)
    ev = mf.evaluate(lens)
    assert ev.error is None
    assert ev.scalars[1] < -0.05 and abs(ev.scalars[3]) < 1e-9
    assert lens.current_config == 1  # put back
    bad = opt.MeritFunction()
    bad.add("CONF", cfg=5)
    assert "does not exist" in bad.evaluate(lens).error


def test_default_merit_repeats_for_every_configuration():
    lens, mc = two_focus_singlet()
    mf = opt.default_merit(lens)
    confs = [r for r in mf.rows if r.type == "CONF"]
    assert [r.params["cfg"] for r in confs] == [1, 2]
    assert sum(r.type == "RAYS" for r in mf.rows) == 2 * len(lens.fields)
    assert not any(r.type == "CONF" for r in opt.default_merit(lens, configs=[]).rows)


def test_optimise_back_focus_of_each_configuration():
    lens, mc = two_focus_singlet()
    for k in (1, 2):
        opt.set_mc_variable(lens, 1, k)
    mf = opt.default_merit(lens)
    before = mf.value(lens)
    res = opt.optimize(lens, mf, cycles=20)
    assert res.merit < 0.5 * before
    far, near = mc.value(1, 1), mc.value(1, 2)
    # focusing from infinity to 500 mm moves the image back by about f^2 / (500 - f) (Newton)
    f = lens.paraxial().efl
    assert near - far == pytest.approx(f * f / (500 - f), rel=0.2)
    assert lens.current_config == 1


def test_lens_variables_on_controlled_parameters_are_refused():
    lens, mc = two_focus_singlet()
    opt.set_variable(lens, lens.image_index - 1, "thickness")
    with pytest.raises(ValueError, match="multi-configuration"):
        opt.optimize(lens, opt.default_merit(lens))


@pytest.mark.parametrize("fig", ["20.1", "20.2", "20.3", "20.4", "20.5", "20.6"])
def test_smith_zoom_multiconfig_matches_position_files(fig):
    lens = lf.load(os.path.join(ZOOM, f"Figure {fig} zoom.lens.json"))
    mc = lens.multiconfig
    assert mc.n_configs >= 2 and all(mc.names)
    for k in mc.configs:
        single = lf.load(os.path.join(ZOOM, f"Figure {fig} {mc.names[k - 1]}.lens.json"))
        c = lens.config_copy(k)
        assert c.to_dict()["surfaces"] == single.to_dict()["surfaces"]
        assert (c.aperture_type, c.aperture_value) == (single.aperture_type, single.aperture_value)
        assert [vars(f) for f in c.fields] == [vars(f) for f in single.fields]
        assert c.paraxial().efl == pytest.approx(single.paraxial().efl, rel=1e-12)
