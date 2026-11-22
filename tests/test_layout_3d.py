"""3-D layout, combined spot diagram and the wavelength colour scheme (core, plots, Qt window, web session)."""

import json
import math
import os

import numpy as np
import pytest

import lensforge as lf

pytest.importorskip("matplotlib")
import matplotlib  # noqa: E402

matplotlib.use("Agg", force=False)
from matplotlib.figure import Figure  # noqa: E402

import lensforge.plot as P  # noqa: E402

HERE = os.path.dirname(__file__)
TRIPLET = os.path.join(HERE, "..", "examples", "output", "cooke_triplet.lens.json")
RED, GREEN, BLUE = "#d62728", "#2ca02c", "#1f4fd6"


def _fold_mirror():
    """Singlet, 45 deg fold mirror between coordinate breaks, image 40 below."""
    s = lf.OpticalSystem("fold")
    s.set_aperture("EPD", 10.0)
    s.set_fields([0.0, 3.0])
    s.add_surface(radius=50, thickness=4, material="N-BK7", stop=True)
    s.add_surface(radius=-50, thickness=30)
    s.add_surface(lf.CoordinateBreak(tilt_x=45))
    s.add_surface(thickness=0, material="MIRROR", semi_diameter=8)
    s.add_surface(lf.CoordinateBreak(tilt_x=45, thickness=-40))
    return s


# ---------------------------------------------------------------------- wavelength colours
def test_three_wavelengths_are_red_green_blue_by_length_not_entry_order():
    assert P.wavelength_colors([0.4861, 0.5876, 0.6563]) == [BLUE, GREEN, RED]
    assert P.wavelength_colors([0.5876, 0.6563, 0.4861]) == [GREEN, RED, BLUE]


def test_wavelength_colours_run_red_through_green_to_blue():
    cols = P.wavelength_colors([0.45, 0.5, 0.55, 0.6, 0.65])
    assert cols[-1] == RED and cols[2] == GREEN and cols[0] == BLUE
    assert len(set(cols)) == 5
    # a wavelength keeps its colour in a plot showing only some of the lens's wavelengths
    allw = [0.4861, 0.5876, 0.6563]
    assert P.wavelength_colors([0.5876], allw) == [GREEN]
    assert P.wavelength_color(0.6563, allw) == RED
    assert P.wavelength_colors([1.0]) == [P.SINGLE_WAVELENGTH_COLOR]


def test_analysis_plots_use_the_wavelength_colours():
    s = lf.load(TRIPLET)
    waves = [w.value for w in s.wavelengths]
    want = P.wavelength_colors(waves, waves)
    for draw in (lambda ax: P.spot(lf.spot_diagram(s, 1), ax, waves=waves),
                 lambda ax: P.lateral_color(lf.lateral_color(s), ax, waves=waves),
                 lambda ax: P.longitudinal_aberration(lf.longitudinal_aberration(s), ax, waves=waves)):
        ax = Figure().add_subplot(111)
        draw(ax)
        got = [matplotlib.colors.to_hex(ln.get_color()) for ln in ax.get_lines() if ln.get_label() in
               {f"{w:.4f} um" for w in waves}]
        assert got == want
    fig = Figure()
    axes = [fig.add_subplot(121), fig.add_subplot(122)]
    P.ray_fan(lf.ray_fan(s, 1), axes, waves=waves)
    assert [matplotlib.colors.to_hex(ln.get_color()) for ln in axes[1].get_lines()][:3] == want


# ---------------------------------------------------------------------- 3-D layout (core + plot)
def test_layout_3d_places_surfaces_and_rays_through_a_fold():
    s = _fold_mirror()
    r = lf.layout_3d(s, rays="ring", n_rays=8)
    frames = s.surface_frames()
    by = {w["surface"]: w for w in r["surfaces"]}
    assert 4 in by and 3 not in by and 5 not in by  # coordinate breaks are not drawn
    for i, w in by.items():
        R, O = frames[i]
        rim_local = (w["rim"] - O) @ R  # back into the surface's own axes
        np.testing.assert_allclose(np.hypot(rim_local[:, 0], rim_local[:, 1]), w["semi_diameter"], atol=1e-9)
    # the fold mirror's rim is tilted 45 deg: its y and z spans are equal
    rim = by[4]["rim"]
    assert np.ptp(rim[:, 1]) == pytest.approx(np.ptp(rim[:, 2]), rel=1e-6)
    # the image lies 40 from the mirror, folded into y, and the rays end on it
    img = by[len(s.surfaces) - 1]
    R, O = frames[len(s.surfaces) - 1]
    assert abs(O[1]) == pytest.approx(40.0, abs=1e-6)
    for ray in r["rays"]:
        end = ray["path"][-1]
        np.testing.assert_allclose((end - O) @ R[:, 2], 0.0, atol=1e-6)  # on the image plane
        assert ray["path"].shape[1] == 9  # ring of 8 + the chief ray
    assert img["semi_diameter"] > 0
    # element edges join the singlet's two faces, and none cross the air gaps
    assert {(e["from"], e["to"]) for e in r["edges"]} == {(1, 2)}


def test_layout_3d_ray_patterns_and_plot():
    s = lf.load(TRIPLET)
    counts = {p: lf.layout_3d(s, fields=[0], rays=p, n_rays=5)["rays"][0]["path"].shape[1]
              for p in lf.analysis.geometry.LAYOUT_3D_RAYS}
    assert counts == {"y_fan": 5, "x_fan": 5, "fans": 9, "ring": 6, "grid": 13}
    with pytest.raises(ValueError):
        lf.layout_3d(s, rays="spiral")
    r = lf.layout_3d(s, rays="fans")
    ax = Figure().add_subplot(111, projection="3d")
    P.layout_3d(r, ax, elevation=0, azimuth=-90, waves=[w.value for w in s.wavelengths])
    assert ax.elev == 0 and ax.azim == -90
    labels = [t.get_text() for t in ax.get_legend().get_texts()]
    assert labels == ["field 1", "field 2", "field 3"]
    # one field: coloured by wavelength, red longest
    lines = P.layout_3d_lines(lf.layout_3d(s, fields=[0], wavelengths=[0, 1, 2]), "auto",
                              [w.value for w in s.wavelengths])
    leg = {ln["label"]: ln["color"] for ln in lines if ln["label"]}
    assert leg == {"0.6563 um": RED, "0.5876 um": GREEN, "0.4861 um": BLUE}
    # failed rays are split at the NaN, never drawn through it
    assert all(np.isfinite(ln["points"]).all() for ln in lines)


# ---------------------------------------------------------------------- combined spot diagram
def test_spot_combined_overlay_and_image_positions():
    s = lf.load(TRIPLET)
    waves = [w.value for w in s.wavelengths]
    spots = [(f, lf.spot_diagram(s, f)) for f in range(len(s.fields))]
    ax = Figure().add_subplot(111)
    P.spot_combined(spots, ax, scale=1000, waves=waves, units="um")
    data = [ln for ln in ax.get_lines() if ln.get_marker() in P.FIELD_MARKERS and len(ln.get_xdata())]
    assert len(data) == len(s.fields) * len(waves)  # every field and wavelength in the one plot
    assert {ln.get_marker() for ln in data} == set(P.FIELD_MARKERS[:3])
    legend = [t.get_text() for t in ax.get_legend().get_texts()]
    assert legend[:3] == ["0.6563 um", "0.5876 um", "0.4861 um"]
    assert legend[3].startswith("Field 1: RMS") and legend[3].endswith("um")
    # image positions: each spot about its chief ray, magnified so the spots don't overlap
    ax = Figure().add_subplot(111)
    P.spot_combined(spots, ax, mode="image", scale=1000, waves=waves, units="um", image_units="mm")
    m = ax.magnification
    assert m > 1 and float(f"{m:.0e}".split("e")[0]) in (1, 2, 5)
    for f, sp in spots:
        pts = [ln for ln in ax.get_lines() if ln.get_marker() in P.FIELD_MARKERS and len(ln.get_xdata())]
        ys = np.concatenate([ln.get_ydata() for ln in pts[f * 3:(f + 1) * 3]])
        geo = sp["geo_radius"] * m
        assert np.all(np.abs(ys - sp["reference"][1]) <= geo * 1.0001)


# ---------------------------------------------------------------------- web session
def test_web_session_sends_the_3d_scene_and_combined_spots():
    from lensforge_web.session import Session, dispatch

    def call(s, method, **args):
        out = json.loads(dispatch(method, json.dumps(args), s))
        assert "error" not in out, out.get("error")
        return out["result"]

    s = Session()
    call(s, "load_sample", name="Cooke Triplet (optimised)")
    specs = call(s, "analysis_specs")
    assert specs["layout_3d"]["view3d"] and not specs["layout"]["view3d"]
    sc = call(s, "run_analysis", key="layout_3d", opts={"rays": "ring", "color_by": "wavelength"})["scene"]
    assert sc["elevation"] == 20 and sc["azimuth"] == -60 and sc["units"] == "mm"
    kinds = {ln["k"] for ln in sc["lines"]}
    assert kinds == {"surface", "edge", "ray"}
    assert all(len(ln["p"]) % 3 == 0 and len(ln["p"]) >= 6 for ln in sc["lines"])
    assert [lab for _, lab in sc["legend"]] == ["0.5876 um"]  # Input Rays: primary wavelength only
    json.dumps(sc, allow_nan=False)  # no NaN reaches the page
    for show in ("overlay", "image"):
        out = call(s, "run_analysis", key="spot", opts={"show": show}, width=500, height=400)
        assert len(out["png"]) > 1000


# ---------------------------------------------------------------------- desktop window
def test_qt_3d_layout_keeps_the_mouse_rotation(qtbot, tmp_path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    pytest.importorskip("pytestqt")
    from PySide6.QtCore import QSettings
    from lensforge_qt import workers
    from lensforge_qt.main_window import MainWindow
    workers.SYNC = True
    try:
        w = MainWindow(settings=QSettings(str(tmp_path / "s.ini"), QSettings.IniFormat))
        w.doc.reset(lf.load(TRIPLET))
        win = w.open_analysis("layout_3d")
        ax = win.figure.axes[0]
        assert ax.name == "3d" and ax.elev == 20 and ax.azim == -60
        ax.view_init(elev=35, azim=10)  # what a mouse drag does
        win._released_3d(None)
        from lensforge_qt.analysis_window import zoom_axes_3d
        zoom_axes_3d(ax, 2.0)
        win._keep_view_3d()
        w.doc.modify("thickness", lambda s: setattr(s.surfaces[2], "thickness", s.surfaces[2].thickness + 0.1))
        ax = win.figure.axes[0]
        assert (ax.elev, ax.azim) == (35, 10)
        assert win.view3d["zoom"] == pytest.approx(2.0)
        win.reset_zoom()  # Home: back to the Elevation / Azimuth settings
        ax = win.figure.axes[0]
        assert (ax.elev, ax.azim) == (20, -60)
        spot = w.open_analysis("spot")
        spot.settings.widgets["show"][1].setCurrentIndex(1)  # All fields in one plot
        assert len([a for a in spot.figure.axes if a.get_lines()]) == 1
        w.doc.undo_stack.setClean()
        w.close()
    finally:
        workers.SYNC = False
