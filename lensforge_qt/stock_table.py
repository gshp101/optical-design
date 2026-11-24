"""File > Insert Stock Lens: the search form, result table and preview, without Qt.

Shared by the desktop dialog (stock_dialog.py) and the web app (lensforge_web.session), so both
search, preview and insert exactly the same way. The search itself is
:meth:`lensforge.StockLibrary.search`; this module turns form values into its arguments and
lenses into table rows.
"""

from __future__ import annotations

import math
import re
from typing import List, Optional

import lensforge as lf
from lensforge import stock as ST

COLUMNS = ["Part", "Vendor", "Type", "EFL", "Diameter", "Thickness", "Elements", "Glass", "Description"]
COLUMN_TIPS = {
    "Part": "The maker's part number (it becomes the comment of the first and last inserted surfaces)",
    "EFL": "Effective focal length in the part's units, at the primary wavelength of the maker's file",
    "Diameter": "Largest clear diameter of the element surfaces",
    "Thickness": "Centre thickness from the first to the last element surface",
    "Glass": "Materials as the maker's file names them",
}
ELEMENT_CHOICES = [("Any", None), ("1", 1), ("2", 2), ("3", 3), ("4 or more", (4, None))]
MAX_ROWS = 500


def _num(v) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v) if math.isfinite(v) else None
    v = str(v).strip()
    if not v:
        return None
    try:
        return float(v)
    except ValueError:
        raise ValueError(f"{v!r} is not a number")


def search_args(form: dict) -> dict:
    """Arguments for StockLibrary.search from the dialog's fields:
    text, vendor, kind, efl_min, efl_max, dia_min, dia_max, glass, elements (index into ELEMENT_CHOICES)."""
    out = {}
    for k in ("text", "vendor", "kind", "glass"):
        v = (form.get(k) or "").strip()
        if v and v != "All":
            out[k] = v
    for key, lo, hi in (("efl", "efl_min", "efl_max"), ("diameter", "dia_min", "dia_max")):
        a, b = _num(form.get(lo)), _num(form.get(hi))
        if a is not None or b is not None:
            out[key] = (a, b)
    el = form.get("elements") or 0
    el = ELEMENT_CHOICES[int(el)][1] if 0 <= int(el) < len(ELEMENT_CHOICES) else None
    if el is not None:
        out["elements"] = el
    return out


def fmt(v, digits=6) -> str:
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return "-"
    return f"{v:.{digits}g}"


def row(x: ST.StockLens) -> List[str]:
    return [x.part, x.vendor, x.kind, fmt(x.efl), fmt(x.diameter, 5), fmt(x.thickness, 5), str(x.elements),
            " / ".join(x.glasses), x.description]


def _sort_key(column: str):
    """Key for sorting lenses by a table column: numbers numerically (missing values last),
    text without regard to case, with digit runs compared as numbers (LA1131 before LA11310)."""
    num = {"EFL": "efl", "Diameter": "diameter", "Thickness": "thickness", "Elements": "elements"}
    if column in num:
        attr = num[column]

        def key(x):
            v = getattr(x, attr)
            ok = v is not None and math.isfinite(v)
            return (not ok, v if ok else 0.0, x.part.lower())
        return key
    idx = COLUMNS.index(column)

    def key(x):
        text = row(x)[idx].lower()
        return ([(0, int(t), "") if t.isdigit() else (1, 0, t) for t in re.findall(r"\d+|\D+", text)], x.part.lower())
    return key


def sort_lenses(found, column: Optional[str] = None, descending: bool = False):
    """``found`` sorted by a column of :data:`COLUMNS` (unchanged for no column)."""
    if not column or column not in COLUMNS:
        return list(found)
    key = _sort_key(column)
    if column in ("EFL", "Diameter", "Thickness", "Elements"):
        ok = [x for x in found if not key(x)[0]]
        missing = [x for x in found if key(x)[0]]
        return sorted(ok, key=key, reverse=descending) + missing   # parts without a value stay last
    return sorted(found, key=key, reverse=descending)


def search(library: lf.StockLibrary, form: dict):
    """(lenses, rows, message) for the form values. ``form['sort']`` (a column name) and
    ``form['descending']`` sort the list as a click on the table header asks."""
    found = sort_lenses(library.search(**search_args(form)), form.get("sort"), bool(form.get("descending")))
    msg = f"{len(found)} part(s)"
    if len(found) > MAX_ROWS:
        msg += f", showing the first {MAX_ROWS}; narrow the search"
        found = found[:MAX_ROWS]
    return found, [row(x) for x in found], msg


def preview(system, part: ST.StockLens, reverse: bool = False, copy_semi_diameters: bool = True) -> dict:
    """{'text': surfaces as they will be inserted, 'info': html-free notes, 'ok': bool}."""
    try:
        trial = lf.OpticalSystem("preview", system.units, system.library)
        lf.insert_stock_lens(trial, part, reverse=reverse, copy_semi_diameters=copy_semi_diameters)
    except Exception as e:  # noqa: BLE001
        return {"text": f"Cannot insert: {e}", "info": "", "ok": False}
    lines = trial.prescription().splitlines()
    notes = [f"{part.label}: {part.kind or 'lens'}, {part.elements} element(s), f = {fmt(part.efl)} {part.units}, "
             f"diameter {fmt(part.diameter, 5)} {part.units}."]
    if part.description:
        notes.append(part.description)
    subs = part.missing_glasses(system.library)
    for g, sub in subs.items():
        notes.append(f"{g} is in none of the loaded glass catalogs: " +
                     (f"{sub} is used instead." if sub else "the inserted surfaces cannot be traced until you "
                      "load a catalog that has it (File > Load Glass Catalog) or choose another material."))
    if part.unsupported:
        notes.append("Not supported, imported as Standard surfaces: " + ", ".join(part.unsupported) +
                     ". Check the prescription against the maker's data.")
    if part.units != system.units:
        notes.append(f"Converted from {part.units} to {system.units}.")
    return {"text": "\n".join(lines[:1] + lines[2:-1]), "info": "\n".join(notes), "ok": True}


def insert(system, part: ST.StockLens, at: int, reverse: bool = False, copy_semi_diameters: bool = True) -> range:
    """Insert into ``system`` (variables, solves and merit operands on later surfaces renumbered)."""
    at = max(1, min(int(at), system.image_index))
    return lf.insert_stock_lens(system, part, at=at, reverse=reverse, copy_semi_diameters=copy_semi_diameters)
