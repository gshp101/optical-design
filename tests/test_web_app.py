"""The web front end (lensforge_web): menus, help, icons, the Python session the page talks to, and the build.

The page itself (JavaScript) is exercised in a browser; these tests cover everything on the Python side,
including the standing rule that every menu command has help and its own icon.
"""

import json
import os

import pytest

pytest.importorskip("matplotlib")

from lensforge_web import menus  # noqa: E402
from lensforge_web.session import Session, dispatch  # noqa: E402

WEB_ONLY = {"File > Import from Disk", "File > Export to Disk"}
QT_ONLY = {"File > Exit"}


def _ids():
    return [iid for iid, _, _ in menus.commands()]


# ---------------------------------------------------------------------- menus, help, icons
def test_every_web_command_has_help_and_its_own_icon():
    data = menus.menu_data()
    seen = {}
    for iid, c in data["commands"].items():
        assert c["summary"] and c["details"], f"add help for {iid} (lensforge_qt/help_text.py or menus.WEB_HELP)"
        assert c["icon"], f"add an icon for {iid}"
        seen.setdefault(c["icon"], []).append(iid)
    # one command may sit in two menus (Undo History is in Edit and View, as in the Qt window)
    shared = [ids for ids in seen.values() if len({i.split(" > ")[-1] for i in ids}) > 1]
    assert shared == [], f"different commands sharing an icon: {shared}"


def test_shortcuts_are_unique_and_avoid_browser_keys():
    keys = {}
    for iid, c in menus.menu_data()["commands"].items():
        if c["shortcut"]:
            assert c["shortcut"] not in keys, f"{iid} and {keys[c['shortcut']]} share {c['shortcut']}"
            keys[c["shortcut"]] = iid
    for reserved in menus.SHORTCUT_CHANGES:
        assert reserved not in keys


def test_web_help_mentions_browser_storage():
    assert "browser" in menus.lookup("File > Save")[1].lower()
    assert "browser" in menus.lookup("File > Open")[1].lower()


def test_default_toolbar_uses_existing_commands():
    data = menus.menu_data()
    for iid in data["default_toolbar"]:
        assert iid == data["separator"] or iid in data["commands"]


def test_menus_match_the_qt_window(qtbot):
    pytest.importorskip("PySide6")
    from lensforge_qt.main_window import MainWindow
    w = MainWindow()
    qtbot.addWidget(w)
    qt = {iid for iid, _, _ in w.toolbar_items}
    web = set(_ids())
    assert web - qt == WEB_ONLY
    assert qt - web == QT_ONLY


# ---------------------------------------------------------------------- the session the page calls
def call(s, method, **args):
    out = json.loads(dispatch(method, json.dumps(args), s))
    assert "error" not in out, out.get("error")
    return out


def test_session_edit_undo_and_save_text():
    s = Session()
    out = call(s, "load_sample", name="Singlet")
    assert out["state"]["title"]
    rev = out["state"]["revision"]
    out = call(s, "set_cell", row=1, key="thickness", text="7.5")
    assert out["state"]["modified"] and out["state"]["revision"] > rev
    assert out["state"]["lde"]["rows"][1]["cells"][2]["t"] in ("7.5", "7.50")
    call(s, "undo")
    assert not call(s, "state")["result"]["modified"]
    text = call(s, "lens_text")["result"]
    assert json.loads(text)
    call(s, "mark_saved", path="my singlet")
    st = call(s, "state")["result"]
    assert st["title"] == "my singlet" and st["path"] == "my singlet" and not st["modified"]


def test_session_restore_round_trip():
    a = Session()
    call(a, "load_sample", name="Cemented Achromat")
    call(a, "set_cell", row=1, key="thickness", text="5")
    dump = call(a, "session_dump")["result"]
    b = Session()
    call(b, "session_restore", data=dump)
    st = call(b, "state")["result"]
    assert st["modified"]
    assert st["lde"]["rows"][1] == call(a, "state")["result"]["lde"]["rows"][1]


def test_session_runs_analyses():
    s = Session()
    call(s, "load_sample", name="Cooke Triplet (optimised)")
    specs = call(s, "analysis_specs")["result"]
    assert set(specs) >= {"layout", "spot", "mtf"}
    assert all(spec["id"] in _ids() for spec in specs.values())
    png = call(s, "run_analysis", key="spot", width=400, height=300)["result"]
    assert "png" in png and len(png["png"]) > 1000
    txt = call(s, "run_analysis", key="prescription")["result"]
    assert "text" in txt and "THICKNESS" in txt["text"].upper()


def test_session_non_sequential_editor_and_analyses():
    from lensforge_qt import ns_table as NT
    s = Session()
    call(s, "load_sample", name="Cemented Achromat")
    st = call(s, "state")["result"]
    assert st["nonseq"]["objects"] == [] and st["nonseq"]["trace"]["split"] is False
    info = call(s, "ns_info")["result"]
    assert info["obj_cols"] == NT.OBJ_COLS and len(info["buttons"]) == len(NT.BUTTONS)
    out = call(s, "ns_from_lens")
    ns_st = out["state"]["nonseq"]
    assert [r["kind"] for r in ns_st["objects"]] == ["STANDARD_LENS", "STANDARD_LENS", "ANNULUS", "DETECTOR"]
    assert ns_st["objects"][0]["labels"][0] == "Radius 1" and ns_st["trace"]["split"] is True
    assert out["state"]["undo"] == "Convert lens to non-sequential"
    out = call(s, "ns_set_cell", table="objects", r=3, c=NT.OBJ_PAR0 + 2, text="51")
    assert out["state"]["nonseq"]["objects"][3]["cells"][NT.OBJ_PAR0 + 2] == "51"
    args = {"table": "objects", "r": 0, "c": NT.OBJ_PAR0, "text": "x"}
    bad = json.loads(dispatch("ns_set_cell", json.dumps(args), s))
    assert "error" in bad
    r = call(s, "ns_add", kind="PRISM", after=0)["result"]
    assert r == {"table": "objects", "row": 1}
    assert call(s, "ns_move", table="objects", r=1, delta=1)["result"]["row"] == 2
    assert call(s, "ns_duplicate", table="objects", r=2)["result"]["row"] == 3
    call(s, "ns_delete", table="objects", r=3)
    call(s, "ns_delete", table="objects", r=2)
    call(s, "ns_change_type", table="sources", r=0, kind="SOURCE_RECTANGLE")
    out = call(s, "ns_set_trace", key="max_segments", value=60)
    assert out["state"]["nonseq"]["trace"]["max_segments"] == 60
    report = call(s, "ns_trace")["result"]
    assert "Detector 4 (image)" in report
    for key in ("ns_layout", "ns_layout_3d", "ns_detector"):
        assert "png" in call(s, "run_analysis", key=key, width=400, height=300)["result"], key
    paths = call(s, "run_analysis", key="ns_paths")["result"]["text"]
    assert "S -> 1 front T" in paths
    # the scene goes into the lens text, and opening it says so
    text = call(s, "lens_text")["result"]
    assert json.loads(text)["nonseq"]["trace_settings"]["max_segments"] == 60
    scene_text = call(s, "ns_text")["result"]
    call(s, "ns_new")
    assert call(s, "state")["result"]["nonseq"]["objects"] == []
    call(s, "ns_open", text=scene_text, filename="x.ns.json")
    assert len(call(s, "state")["result"]["nonseq"]["objects"]) == 4
    call(s, "undo")
    assert call(s, "state")["result"]["nonseq"]["objects"] == []
    b = Session()
    assert call(b, "open_text", text=text, filename="a.lens.json")["result"]["nonseq"] is True


def test_session_errors_come_back_as_messages():
    s = Session()
    out = json.loads(dispatch("load_sample", json.dumps({"name": "no such lens"}), s))
    assert "error" in out and out["error_type"] == "KeyError"


def test_session_optimizes_and_stops():
    s = Session()
    call(s, "load_sample", name="Cooke Triplet (optimised)")
    call(s, "set_cell", row=2, key="thickness", text="13")
    before = call(s, "mfe_evaluate")["result"]["value"]
    r = call(s, "optimize", algorithm="dls", cycles=10)["result"]
    assert r["merit"] <= before
    call(s, "load_optimization_result")
    assert call(s, "mfe_evaluate")["result"]["value"] == pytest.approx(r["merit"], rel=1e-6)


def test_session_merit_wizard_options():
    s = Session()
    call(s, "load_sample", name="Cooke Triplet (optimised)")
    info = call(s, "wizard_info")["result"]
    assert ["angular", "Angular radius"] in info["criteria"] and info["help"].endswith("mfe/wizard")
    kw = {"kind": "spot_y", "optimization": "ptv", "reference": "chief", "pupil": "rectangular", "grid": 8,
          "obscuration": 0.2, "wavelength_weighting": "equal", "symmetric": None, "delete_vignetted": True,
          "field_weighting": "system", "weight": 2, "glass_min": 1.5, "boundary_weight": 1, "start_at": 0}
    call(s, "mfe_wizard", kw=kw, keep=True)
    info = call(s, "wizard_info")["result"]
    assert info["wizard"]["kind"] == "spot_y" and info["wizard"]["start_at"] == 0
    rows = call(s, "state")["result"]["mfe"]["rows"]
    assert rows[0]["type"] == "BLNK" and sum(r["type"] == "RAYS" for r in rows) == 3
    assert call(s, "mfe_evaluate")["result"]["value"] > 0
    help_keys = [t["key"] for t in call(s, "help_data")["result"]["topics"]]
    assert info["help"] in help_keys


# ---------------------------------------------------------------------- the build
def test_build_writes_a_complete_site(tmp_path):
    from lensforge_web.build import build
    out = build(str(tmp_path / "site"), "https://example.invalid/pyodide/")
    for f in ("index.html", "app.css", "worker.js", "sw.js", "config.js", "app-icon.svg", "py/lensforge.zip",
              "examples/index.json", "js/app.js", "js/core.js", "js/engine.js", "js/storage.js", "popout.html"):
        assert os.path.exists(os.path.join(out, f)), f
    assert "example.invalid" in open(os.path.join(out, "config.js")).read()
    examples = json.load(open(os.path.join(out, "examples/index.json")))
    assert examples and all(os.path.exists(os.path.join(out, "examples", x["path"])) for x in examples)
    # the Examples menu is built from the index: folders nest the menus, in the desktop app's order
    from lensforge_qt.commands import example_index
    assert examples == example_index()
    assert any(x["folders"][:1] == ["Modern Lens Design (Smith)"] and len(x["folders"]) == 2 for x in examples)
    assert "Examples > Browse Examples" in menus.menu_data()["commands"]


def test_operand_menus_list_every_operand_once():
    from lensforge.multiconfig import MC_OPERANDS
    from lensforge.optimize import OPERANDS
    s = Session()
    names = [k for g in s.operand_menu() for k, _ in g["items"]]
    assert sorted(names) == sorted(OPERANDS)
    assert all(d for g in s.operand_menu() for _, d in g["items"])
    mc = [k for g in s.state()["mce"]["operand_menu"] for k, _ in g["items"]]
    assert sorted(mc) == sorted(MC_OPERANDS)


def test_popout_help_and_page():
    for iid in menus.POPOUT_COMMANDS:
        assert "Open in New Tab" in menus.lookup(iid)[1], iid
    assert "Type column is a menu" in menus.lookup("Tools > Merit Function Editor")[1]
    page = open(os.path.join(os.path.dirname(menus.__file__), "static", "popout.html")).read()
    assert "LensForgePopout" in page
