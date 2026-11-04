"""Menus, shortcuts, help and icons of the web front end.

The menu bar mirrors the Qt main window (lensforge_qt/main_window.py) item for item, with the
same menu paths as command ids ("File > Open", "Analysis > Layout > 2D Layout"), so the help
text (lensforge_qt/help_text.py), the icons (lensforge_qt/icon_svgs.py) and the default toolbar
(lensforge_qt/commands.py) are shared. Differences, all because the program runs in a browser:

* lens files live in the browser's own storage (IndexedDB); File > Import from Disk and
  File > Export to Disk move them to and from ordinary files, and there is no File > Exit;
* a few shortcuts the browser keeps for itself (Ctrl+N, Ctrl+W, Ctrl+Shift+T ...) use Alt
  instead (see SHORTCUT_CHANGES).

Every command needs help and its own icon; tests/test_web_app.py checks both (Joe's standing rule).
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from lensforge_qt.analyses import GROUPS, REGISTRY
from lensforge_qt.commands import DEFAULT_TOOLBAR, SEPARATOR, SHORT_LABELS, sample_list
from lensforge_qt.help_text import lookup as qt_lookup
from lensforge_qt.icon_svgs import GREEN, INK, ORANGE, svg as qt_svg

SEP = None  # a separator in a menu list

# shortcuts the browser reserves (new window/tab, close tab, clear browsing data, private window ...)
SHORTCUT_CHANGES = {
    "Ctrl+N": "Alt+N", "Ctrl+Shift+N": "Alt+Shift+N", "Ctrl+W": "Alt+W", "Ctrl+Shift+T": "Alt+Shift+T",
    "Ctrl+Shift+Del": "Alt+Shift+Del", "Ctrl+Shift+P": "Alt+Shift+P", "Ctrl+Shift+O": "Alt+Shift+O",
}


def _sc(qt: Optional[str]) -> Optional[str]:
    return SHORTCUT_CHANGES.get(qt, qt) if qt else None


def _item(label, shortcut=None, checkable=False, dialog=False):
    """A command: label as shown ("Open..." for one that opens a dialog), shortcut, checkable."""
    return {"label": label + ("..." if dialog else ""), "shortcut": _sc(shortcut), "checkable": checkable}


def _sub(label, items):
    return {"label": label, "items": items}


def menu_tree() -> List[dict]:
    """The menu bar: [{label, items: [command | submenu | None]}]; ids are filled in by :func:`commands`."""
    analysis = []
    for g in GROUPS:
        analysis.append(_sub(g, [_item(spec.title, spec.shortcut) for spec in REGISTRY.values() if spec.group == g]))
    analysis += [SEP, _item("Tab All Analysis Windows"), _item("Close All Analysis Windows")]
    return [
        _sub("File", [
            _item("New", "Ctrl+N"), _item("Open", "Ctrl+O", dialog=True), _sub("Open Recent", []),
            _item("Save", "Ctrl+S"), _item("Save As", "Ctrl+Shift+S", dialog=True), SEP,
            _item("Import from Disk", "Ctrl+Alt+O", dialog=True), _item("Export to Disk", "Ctrl+Alt+S", dialog=True),
            SEP,
            _item("Insert Lens", "Ctrl+I", dialog=True), _item("Inspect Lens File", "Ctrl+Shift+O", dialog=True),
            _item("System Explorer", "F2", dialog=True), _item("Fields", "F3", dialog=True),
            _item("Wavelengths", "F4", dialog=True), _item("Input Rays", "F5", dialog=True), SEP,
            _sub("Sample Lenses", [_item(name) for name, _ in sample_list()]),
            _item("Load Glass Catalog (AGF)", dialog=True), _item("Forget Loaded Glass Catalogs"),
            _item("Export Prescription", dialog=True),
        ]),
        _sub("Edit", [
            _item("Undo", "Ctrl+Z"), _item("Redo", "Ctrl+Y"), _item("Undo History"), SEP,
            _item("Insert Surface", "Ins"), _item("Insert Surface After", "Ctrl+Ins"),
            _item("Delete Surface", "Shift+Del"), _item("Delete Surfaces", "Ctrl+Shift+Del", dialog=True),
            _item("Toggle Variable", "Ctrl+Shift+V"), _item("Choose Material", "Ctrl+G", dialog=True),
            _item("Surface Properties", "Ctrl+Shift+P", dialog=True), SEP,
            _item("Quick Focus (paraxial)", "Ctrl+Shift+F"), _item("Fix Semi-Diameters at Current Values"),
            _item("Make All Semi-Diameters Automatic"),
        ]),
        _sub("Analysis", analysis),
        _sub("Tools", [
            _item("Optimization", "Ctrl+U", dialog=True), _item("Tolerancing", "Ctrl+Shift+T", dialog=True),
            _item("Python Shell", "F8"), SEP,
            _item("Merit Function Editor", "F6"), _item("Multi-Configuration Editor", "F7"),
            _item("Next Configuration", "Ctrl+]"), _item("Previous Configuration", "Ctrl+["),
            _sub("Non-Sequential", [_item("Non-Sequential Editor", "Ctrl+Shift+N"),
                                    _item("Convert Lens to Non-Sequential")]),
            _sub("Variables and Solves", [_item("Make All Curvatures Variable"), _item("Make All Air Spaces Variable"),
                                          _item("Remove All Variables"), _item("Remove All Solves")]),
        ]),
        # the lens entries (examples/index.json) are added by the page, like Open Recent's
        _sub("Examples", [_item("Browse Examples", dialog=True)]),
        _sub("View", [_item("Show Toolbar", checkable=True), _item("Customize Toolbar", dialog=True), SEP,
                      _item("Undo History")]),
        _sub("Help", [_item("Help Contents", "F1"), _item("What's This?", "Shift+F1"), SEP,
                      _item("Keyboard Shortcuts"), _item("About")]),
    ]


def plain(label: str) -> str:
    return label[:-3] if label.endswith("...") else label


def commands() -> List[Tuple[str, Tuple[str, ...], dict]]:
    """Every command as (id, path, item) in menu order (Open Recent's entries change, so it has none)."""
    return commands_of(menu_tree())


# ---------------------------------------------------------------------------
# Help: the Qt help text, with the commands that work differently in a browser rewritten
# ---------------------------------------------------------------------------

_STORAGE = ("Lens files are kept in this browser's own storage (IndexedDB) for this web address; they stay "
            "when you close the tab or restart the browser, but are lost if you clear the site's data, so "
            "use File > Export to Disk for anything you want to keep elsewhere.")

WEB_HELP: Dict[str, Tuple[str, str]] = {
    "File > Open": (
        "Open a lens saved in this browser.",
        "Lists the lenses saved in this browser (name, size, when saved). Double-click one, or select it and "
        "press Open. The list can also rename, delete and export lenses, and Import from Disk... opens a "
        "lensforge .json or Zemax .zmx file from your computer. " + _STORAGE + " If the lens uses a glass that "
        "no loaded catalog has, it still opens, the Material cell turns red and the analysis windows say why "
        "they cannot trace; pick a replacement glass (Ctrl+G) or load a catalog that has it (File > Load Glass "
        "Catalog)."),
    "File > Save": (
        "Save the lens in this browser.",
        "Stores the lens, variables, solves, merit function, multi-configuration table and the Input Rays "
        "settings under its name in this browser's storage. A lens that has never been saved asks for a "
        "name. " + _STORAGE),
    "File > Save As": (
        "Save the lens in this browser under a new name.",
        "Asks for a name and stores the lens under it in this browser's storage (a name that is already used "
        "is replaced after you confirm). The lens on screen then has the new name. " + _STORAGE),
    "File > Import from Disk": (
        "Open a lens file from your computer (.json or .zmx).",
        "Opens a lensforge .json lens or imports a Zemax .zmx prescription chosen from your computer, as an "
        "unsaved lens named after the file. Save (Ctrl+S) then keeps it in this browser. You can also drop a "
        "lens file onto the window."),
    "File > Export to Disk": (
        "Download the lens as a .lens.json file.",
        "Saves the lens, with its variables, solves, merit function and Input Rays settings, as a lensforge "
        ".lens.json file in your downloads, for backups, other computers, the desktop app or Python scripts "
        "(lensforge.load). The copy in the browser is unchanged."),
    "File > Insert Lens": (
        "Insert surfaces from another lens, scaled and optionally reversed.",
        "Choose a lens saved in this browser or a .json / .zmx file from your computer, the range of its "
        "surfaces, where to insert them, a scale factor, whether to reverse their order, whether its stop "
        "becomes the stop, unit conversion and whether to copy its semi-diameters. A preview shows the "
        "surfaces exactly as they will be inserted. Variables, solves and merit operands that refer to later "
        "surfaces are renumbered. One undo step."),
    "File > Inspect Lens File": (
        "Show the system report of a lens without opening it.",
        "Choose a lens saved in this browser or a file from your computer; its full system report (first-order "
        "data, prescription, aberrations) appears in its own window while the current lens stays open. "
        "The window can copy or download the report, or open the lens in the editor."),
    "File > Load Glass Catalog (AGF)": (
        "Load a Zemax AGF glass catalog file from your computer.",
        "Adds the glasses of an .agf catalog to the material library, so lenses that use them can be traced "
        "and the material picker lists them. The catalog is kept in this browser's storage and loaded again "
        "every time the program starts, until File > Forget Loaded Glass Catalogs."),
    "File > Forget Loaded Glass Catalogs": (
        "Stop loading your AGF catalogs at start-up.",
        "Removes the AGF catalogs you loaded from this browser's storage. They stay loaded until the page is "
        "reloaded; the built-in catalogs (SCHOTT, OHARA, HOYA, CDGM, Sumita, Hikari ...) are not affected."),
    "File > Export Prescription": (
        "Download the prescription report as a text file.",
        "Writes the prescription (surfaces, radii, thicknesses, glasses, semi-diameters, first-order data) "
        "to a .txt file in your downloads."),
    "Tools > Python Shell": (
        "Run Python against the open lens, in the browser.",
        "A Python editor and output pane (bottom dock). Python runs inside this page (Pyodide), with the same "
        "lensforge library as the desktop app: `lens` is the open lens, and `lf` (lensforge), `opt` "
        "(lensforge.optimize) and `np` (NumPy) are defined. Changes the script makes to `lens` become one "
        "undoable edit; print() output appears below. Variables you define stay for the next run. Ctrl+Enter "
        "runs the script."),
    "Tools > Non-Sequential > Non-Sequential Editor": (
        "Build and trace a non-sequential scene (objects, sources, detectors).",
        "Opens the Non-Sequential Editor window: a table of objects (lenses, spheres, boxes, rods, mirrors, "
        "annuli, rectangles, detectors) and a table of sources (point, ellipse, rectangle), each with a "
        "position, tilts and parameters. Trace (F5 in the window) follows every ray, splitting it at "
        "refracting faces when Split rays is on (ghosts and stray light), and shows the rays and the "
        "irradiance on a detector. Scenes are saved in this browser's storage and can be downloaded or "
        "loaded from .ns.json files (scripting: lensforge.nonseq)."),
    "Examples > Browse Examples": (
        "Open one of the example lenses that come with LensForge.",
        "The Examples menu lists every lens file of the examples folder, grouped by subfolder: the lenses "
        "written by the example scripts (Cooke triplet, scripted singlet, grating demo, spot size merit, "
        "hyperspectral imager), the approximate Arducam LK004 lens kit models, and the prescriptions from "
        "Warren Smith's <i>Modern Lens Design</i> by chapter (Modern Lens Design (Smith) &gt; Chapter 7 - "
        "Eyepieces and Magnifiers &gt; Figure 7.1 ...). The examples are part of this web site, so they load "
        "without a server or an internet search. Pick a lens to open it; hovering an entry shows its file. "
        "Browse Examples... opens the Open dialog on its Examples tab, with a filter box and a short "
        "description of the selected lens. An example opens as an unsaved copy named after the file: "
        "File &gt; Save keeps it in this browser's storage and the example itself never changes. You are "
        "asked to save changes to the current lens first."),
    "Help > What's This?": (
        "Click any button or menu command to see what it does.",
        "Turns the pointer into a question mark; the next button, menu command or editor you click shows its "
        "help instead of running. Press Esc to cancel."),
    "Help > About": (
        "Version and credits.",
        "Shows the lensforge version, the Python version running in the browser (Pyodide) and the license."),
}


def lookup(item_id: str) -> Optional[Tuple[str, str]]:
    """(summary, details) of a web command."""
    if item_id in WEB_HELP:
        return WEB_HELP[item_id]
    return qt_lookup(item_id)


# ---------------------------------------------------------------------------
# Icons: the Qt app's, plus the commands only the web app has
# ---------------------------------------------------------------------------

_WEB_ICONS = {
    "File > Import from Disk": (
        '<rect x="3" y="15" width="18" height="6" rx="1" fill="#e9eef3"/><path d="M6 18h3"/>'
        f'<path d="M15 3v9m-3.5-3.5L15 12l3.5-3.5" stroke="{GREEN}" stroke-width="2.2"/>'
        '<path d="M4 4h6v7H4z" fill="#fff"/>'),
    "File > Export to Disk": (
        '<rect x="3" y="15" width="18" height="6" rx="1" fill="#e9eef3"/><path d="M6 18h3"/>'
        f'<path d="M15 12V3m-3.5 3.5L15 3l3.5 3.5" stroke="{ORANGE}" stroke-width="2.2"/>'
        '<path d="M4 4h6v7H4z" fill="#fff"/>'),
}


def svg(item_id: str) -> Optional[str]:
    body = _WEB_ICONS.get(item_id)
    if body is not None:
        return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="24" height="24" fill="none" '
                f'stroke="{INK}" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">{body}</svg>')
    return qt_svg(item_id)


def menu_data() -> dict:
    """Everything the page needs to build the menu bar, toolbar and help browser."""
    tree = menu_tree()
    cmds = commands_of(tree)
    info = {}
    for iid, path, it in cmds:
        h = lookup(iid)
        info[iid] = {"path": list(path), "label": it["label"], "shortcut": it["shortcut"],
                     "checkable": it["checkable"], "icon": svg(iid), "summary": h[0] if h else "",
                     "details": h[1] if h else "", "short": SHORT_LABELS.get(iid)}
    return {"tree": tree, "commands": info, "default_toolbar": list(DEFAULT_TOOLBAR), "separator": SEPARATOR}


def commands_of(tree) -> List[Tuple[str, Tuple[str, ...], dict]]:
    out = []

    def walk(items, path):
        for it in items:
            if it is None:
                continue
            p = path + (plain(it["label"]),)
            if "items" in it:
                walk(it["items"], p)
            else:
                it["id"] = " > ".join(p)
                out.append((it["id"], p, it))

    walk(tree, ())
    return out
