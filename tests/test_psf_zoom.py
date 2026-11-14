"""Zoom into the PSF: core plot helper, plot-only settings, Qt mouse zoom, web re-plot and view."""

import json

import numpy as np
import pytest

import lensforge as lf
import lensforge.plot as P
from lensforge_qt.analyses import REGISTRY


@pytest.fixture(scope="module")
def psf():
    return lf.fft_psf(lf.samples.parabolic_mirror(), 0, pupil_n=64)  # diffraction limited


def test_zoom_limits(psf):
    x, y = psf["x"], psf["y"]
    (a, b), (c, d) = P.psf_zoom_limits(psf, 1)
    assert (a, b, c, d) == (x[0], x[-1], y[0], y[-1])
    (a4, b4), (c4, d4) = P.psf_zoom_limits(psf, 4)
    assert np.isclose(b4 - a4, (x[-1] - x[0]) / 4) and np.isclose(d4 - c4, (y[-1] - y[0]) / 4)
    assert np.isclose(a4 + b4, x[0] + x[-1])
    (aa, ba), (ca, da) = P.psf_zoom_limits(psf, "auto")
    assert x[0] - 1e-12 <= aa < ba <= x[-1] + 1e-12 and ba - aa < (x[-1] - x[0]) / 3
    # the bright core sits inside the auto frame
    r, c = np.unravel_index(np.argmax(psf["psf"]), psf["psf"].shape)
    assert aa < x[c] < ba and ca < y[r] < da
    # a PSF filling its window (badly aberrated) gets the whole window
    big = lf.fft_psf(lf.samples.achromat(), 0, pupil_n=32)
    (ab, bb), _ = P.psf_zoom_limits(big, "auto")
    assert big["x"][0] - 1e-12 <= ab < bb <= big["x"][-1] + 1e-12
    with pytest.raises(ValueError):
        P.psf_zoom_limits(psf, -2)


def test_plot_helper_zoom(psf):
    from matplotlib.figure import Figure
    ax = Figure().add_subplot(111)
    P.psf(psf, ax, zoom=8)
    assert np.isclose(np.diff(ax.get_xlim())[0], (psf["x"][-1] - psf["x"][0]) / 8)


def test_zoom_is_a_plot_only_setting():
    for key in ("psf", "psf_cross"):
        spec = REGISTRY[key]
        assert spec.zoomable
        zoom = next(s for s in spec.settings if s.name == "zoom")
        assert zoom.plot_only and zoom.default == 1 and "auto" in [v for _, v in zoom.choices]
        vals = {s.name: s.default for s in spec.settings}
        assert "zoom" not in spec.compute_values(vals) and "log" not in spec.compute_values(vals)
        spec.compute(lf.samples.achromat(), **spec.compute_values({**vals, "pupil_n": 32}))  # accepted


# --------------------------------------------------------------------------- Qt
def _qt_window(qtbot, monkeypatch, key):
    pytest.importorskip("PySide6")
    from lensforge_qt import workers
    from lensforge_qt.analysis_window import AnalysisWindow
    from lensforge_qt.document import LensDocument
    monkeypatch.setattr(workers, "SYNC", True)
    doc = LensDocument(lf.samples.achromat())
    w = AnalysisWindow(key, doc, {"pupil_n": 32})
    qtbot.addWidget(w)
    return w, doc


def test_qt_zoom_setting_replots_without_recomputing(qtbot, monkeypatch):
    w, doc = _qt_window(qtbot, monkeypatch, "psf")
    assert w.result is not None and w.updates == 1
    full = np.diff(w.figure.axes[0].get_xlim())[0]
    st, combo = w.settings.widgets["zoom"]
    combo.setCurrentIndex(combo.findData(4))
    assert w.updates == 1  # no recompute
    assert np.isclose(np.diff(w.figure.axes[0].get_xlim())[0], full / 4)
    log = w.settings.widgets["log"][1]
    log.setChecked(True)
    assert w.updates == 1
    pc = w.settings.widgets["pupil_n"][1]
    pc.setCurrentIndex(pc.findData(64))  # a compute setting does recompute
    assert w.updates == 2


def test_qt_wheel_zoom_survives_recompute_and_home_resets(qtbot, monkeypatch):
    from matplotlib.backend_bases import MouseEvent
    w, doc = _qt_window(qtbot, monkeypatch, "psf")
    ax = w.figure.axes[0]
    full = ax.get_xlim()
    w.canvas.draw()
    cx, cy = ax.transData.transform((0.0, 0.0))
    ev = MouseEvent("scroll_event", w.canvas, cx, cy, step=1)
    w._wheel(ev)
    zoomed = w.figure.axes[0].get_xlim()
    assert np.isclose((full[1] - full[0]) / (zoomed[1] - zoomed[0]), 1.25)
    w.request_update()  # recompute (as after a lens change): the mouse zoom stays
    assert w.updates == 2
    assert np.allclose(w.figure.axes[0].get_xlim(), zoomed)
    w.toolbar.home()
    assert w.user_view is None
    assert np.allclose(w.figure.axes[0].get_xlim(), full)


# --------------------------------------------------------------------------- web
def _call(s, method, **args):
    from lensforge_web.session import dispatch
    out = json.loads(dispatch(method, json.dumps(args), s))
    assert "error" not in out, out.get("error")
    return out["result"]


def test_web_view_and_replot_cache(monkeypatch):
    from lensforge_web.session import Session
    s = Session()
    _call(s, "load_sample", name="Cooke Triplet (optimised)")
    assert _call(s, "analysis_specs")["psf"]["zoomable"]
    n = {"compute": 0}
    spec = REGISTRY["psf"]
    real = spec.compute

    def counting(*a, **k):
        n["compute"] += 1
        return real(*a, **k)
    monkeypatch.setattr(spec, "compute", counting)
    opts = {"pupil_n": 32}
    r = _call(s, "run_analysis", key="psf", opts=opts, width=400, height=300, cache="an1", replot=True)
    a = r["axes"]
    assert 0 <= a["box"][0] < a["box"][2] <= 1 and 0 <= a["box"][1] < a["box"][3] <= 1
    view = [a["xlim"][0] / 4, a["xlim"][1] / 4, a["ylim"][0] / 4, a["ylim"][1] / 4]
    z = _call(s, "run_analysis", key="psf", opts={**opts, "zoom": 2, "log": True}, width=400, height=300,
              view=view, cache="an1", replot=True)
    assert n["compute"] == 1  # re-plotted from the cache
    assert np.allclose(z["axes"]["xlim"], view[:2], rtol=1e-6) or z["axes"]["xlim"][1] - z["axes"]["xlim"][0] \
        >= view[1] - view[0] - 1e-12  # (equal aspect may widen one axis)
    _call(s, "run_analysis", key="psf", opts={**opts, "pupil_n": 64}, cache="an1", replot=True)
    assert n["compute"] == 2  # a compute setting changed
    _call(s, "run_analysis", key="psf", opts={**opts, "pupil_n": 64}, cache="an1", replot=False)
    assert n["compute"] == 3  # Update always recomputes
    _call(s, "forget_analysis", cache="an1")
    assert "an1" not in s._analysis_cache
