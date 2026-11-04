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


# ---------------------------------------------------------------------- the build
def test_build_writes_a_complete_site(tmp_path):
    from lensforge_web.build import build
    out = build(str(tmp_path / "site"), "https://example.invalid/pyodide/")
    for f in ("index.html", "app.css", "worker.js", "sw.js", "config.js", "app-icon.svg", "py/lensforge.zip",
              "examples/index.json", "js/app.js", "js/core.js", "js/engine.js", "js/storage.js"):
        assert os.path.exists(os.path.join(out, f)), f
    assert "example.invalid" in open(os.path.join(out, "config.js")).read()
    examples = json.load(open(os.path.join(out, "examples/index.json")))
    assert examples and all(os.path.exists(os.path.join(out, "examples", x["path"])) for x in examples)
    # the Examples menu is built from the index: folders nest the menus, in the desktop app's order
    from lensforge_qt.commands import example_index
    assert examples == example_index()
    assert any(x["folders"][:1] == ["Modern Lens Design (Smith)"] and len(x["folders"]) == 2 for x in examples)
    assert "Examples > Browse Examples" in menus.menu_data()["commands"]
