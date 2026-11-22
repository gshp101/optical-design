"""Equal-Area Fields: core helper, Qt dialog, web session call."""

import json
import math

import pytest

import lensforge as lf


def test_equal_area_values():
    ys = lf.equal_area_fields(5, 20.0)
    assert ys == pytest.approx([0, 10, math.sqrt(200), math.sqrt(300), 20])
    # equal areas: the zones between neighbouring fields have the same y^2 step
    steps = [b * b - a * a for a, b in zip(ys, ys[1:])]
    assert steps == pytest.approx([steps[0]] * 4)
    assert lf.equal_area_fields(3, 20.0, 5.0) == pytest.approx([5, math.sqrt(212.5), 20])
    assert lf.equal_area_fields(1, 7.0) == [7.0]


def test_full_field_mirrors_without_a_second_zero():
    assert lf.equal_area_fields(3, 20.0, full=True) == pytest.approx([-20, -math.sqrt(200), 0, math.sqrt(200), 20])
    assert lf.equal_area_fields(2, 20.0, 5.0, full=True) == pytest.approx([-20, -5, 5, 20])


@pytest.mark.parametrize("args", [(0, 10.0), (3, 10.0, 10.0), (3, 5.0, 10.0), (3, -1.0)])
def test_bad_settings(args):
    with pytest.raises(ValueError):
        lf.equal_area_fields(*args)


def test_system_helper_keeps_field_type():
    s = lf.samples.singlet()
    s.set_equal_area_fields(4, 12.0, full=True)
    assert [f.y for f in s.fields] == pytest.approx(lf.equal_area_fields(4, 12.0, full=True))
    assert s.field_type == "ANGLE" and all(f.x == 0 and f.weight == 1 for f in s.fields)
    s.set_equal_area_fields(3, 2.0, kind="OBJECT_HEIGHT")
    assert s.field_type == "OBJECT_HEIGHT" and len(s.fields) == 3


def test_web_session_call():
    from lensforge_web.session import Session, dispatch
    s = Session()
    out = json.loads(dispatch("equal_area_fields", json.dumps({"n": 3, "maximum": "20", "minimum": "", "full": True}), s))
    assert "state" not in out and [float(v) for v in out["result"]] == pytest.approx([-20, -math.sqrt(200), 0,
                                                                                         math.sqrt(200), 20])
    bad = json.loads(dispatch("equal_area_fields", json.dumps({"n": 3, "maximum": "1", "minimum": "2"}), s))
    assert "maximum field must be larger" in bad["error"]
    d = json.loads(dispatch("system_settings", "{}", s))["result"]
    assert set(d["equal_area_tips"]) == {"count", "full", "maximum", "minimum"}


def test_qt_equal_area_dialog(qtbot, tmp_path):
    pytest.importorskip("PySide6")
    from PySide6.QtCore import QSettings, QTimer
    from PySide6.QtWidgets import QApplication
    from lensforge_qt.main_window import MainWindow
    from lensforge_qt.system_dialog import EqualAreaDialog, SystemExplorer
    w = MainWindow(settings=QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat))
    try:
        d = SystemExplorer(w.doc, w, tab=1)
        e = EqualAreaDialog(d, maximum=20.0)
        assert e.count.value() == 5 and not e.full.isChecked() and e.minimum.text() == "0"
        assert all(x.toolTip() for x in (e.count, e.full, e.maximum, e.minimum))
        e.count.setValue(3)
        e.full.setChecked(True)
        assert e.preview.text() == "-20, -14.1421, 0, 14.1421, 20"
        e.minimum.setText("30")
        assert "larger" in e.preview.text()
        e.close()

        # the Fields tab button opens the dialog and fills the table from it
        def accept():
            dlg = next(x for x in QApplication.topLevelWidgets() if isinstance(x, EqualAreaDialog) and x.isVisible())
            dlg.count.setValue(2)
            dlg.maximum.setText("12")
            dlg.minimum.setText("3")
            dlg.full.setChecked(True)
            dlg._ok()
        QTimer.singleShot(0, accept)
        assert d._equal_area()
        ys = [float(d.field_table.item(r, 1).text()) for r in range(d.field_table.rowCount())]
        assert ys == pytest.approx([-12, -3, 3, 12])
        assert d.apply() and [f.y for f in w.doc.system.fields] == pytest.approx([-12, -3, 3, 12])
        QTimer.singleShot(0, lambda: next(x for x in QApplication.topLevelWidgets()
                                          if isinstance(x, EqualAreaDialog) and x.isVisible()).reject())
        assert not d._equal_area() and d.field_table.rowCount() == 4  # Cancel leaves the table alone
        d.close()
    finally:
        w.doc.undo_stack.setClean()
        w.close()
        w.deleteLater()
