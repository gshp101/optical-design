"""Everything the web page asks of Python: one :class:`Session` per page.

The page (lensforge_web/static/app.js) runs this module inside Pyodide, in a Web Worker, and calls
``dispatch(method, json_args)``. Each public method returns plain JSON data. Methods that change
the lens return the new :meth:`Session.state` too (see :func:`dispatch`), so the page redraws the
editors from one place. Nothing here is specific to the browser, so tests/test_web_app.py drives
the same methods under ordinary CPython.

The logic mirrors the Qt editors (lensforge_qt/lde.py, mfe.py, mce.py, system_dialog.py,
rays_dialog.py, material_dialog.py, opt_dialogs.py, ns_window.py) and reuses their Qt-free helpers
(edits, analyses, rays, opt_runner, ns_table, help_text, mfe_help).
"""

from __future__ import annotations

import base64
import contextlib
import html
import io
import json
import math
import os
import sys
import time
import traceback

os.environ.setdefault("MPLBACKEND", "Agg")

import numpy as np  # noqa: E402

import lensforge as lf  # noqa: E402
from lensforge import optimize as opt  # noqa: E402
from lensforge import surfaces as S  # noqa: E402
from lensforge.compose import lens_surfaces, remove_mc_rows  # noqa: E402
from lensforge.materials import ConstantIndex, ModelGlass, _squash  # noqa: E402
from lensforge.multiconfig import MC_OPERANDS, format_value  # noqa: E402
from lensforge.system import APERTURE_TYPES, FIELD_TYPES, Field, Wavelength  # noqa: E402

from lensforge_qt import edits as E  # noqa: E402
from lensforge_qt import mfe_help  # noqa: E402
from lensforge_qt import ns_table as NT  # noqa: E402
from lensforge_qt import rays as R  # noqa: E402
from lensforge_qt.analyses import REGISTRY  # noqa: E402
from lensforge_qt.commands import sample_list  # noqa: E402
from lensforge_qt.help_text import OVERVIEW  # noqa: E402
from lensforge_qt.icon_svgs import APP_ICON, ns_svg  # noqa: E402
from lensforge_qt.opt_runner import (ALGORITHMS, COMPENSATORS, CRITERIA, DISTRIBUTIONS,  # noqa: E402
                                     StopRequested, run_optimization, watched_criterion)

from . import menus  # noqa: E402
from .document import WebDocument  # noqa: E402

#: how to fix a lens whose glass is missing (as lensforge_qt.analysis_window.MISSING_HINT, for the browser)
MISSING_HINT = ("Choose a replacement in the Material column of the Lens Data Editor (Ctrl+G), "
                "or load a catalog that has it with File > Load Glass Catalog (AGF).")

LDE_FIXED = [("surf", "Surf"), ("type", "Surf:Type"), ("comment", "Comment"), ("radius", "Radius"),
             ("thickness", "Thickness"), ("material", "Material"), ("semi_diameter", "Semi-Diameter"),
             ("conic", "Conic")]
PAR0 = len(LDE_FIXED)

MFE_COLUMNS = ["Type", "Parameters", "Bound", "Target", "Weight", "Value", "% Contrib", "Comment"]
MCE_FIXED = ["Type", "Ref", "Param"]
MCE_REF_HELP = {"surface": "surface number (0 = object)", "field": "field number, counting from 0",
                "wave": "wavelength number, counting from 0", None: "no reference"}

APERTURE_LABELS = {"EPD": "Entrance Pupil Diameter", "IMAGE_FNUM": "Image Space F/#",
                   "OBJECT_NA": "Object Space NA", "STOP_SIZE": "Float By Stop Size",
                   "WORKING_FNUM": "Paraxial Working F/#"}
FIELD_LABELS = {"ANGLE": "Angle (degrees)", "OBJECT_HEIGHT": "Object Height",
                "PARAXIAL_IMAGE_HEIGHT": "Paraxial Image Height", "REAL_IMAGE_HEIGHT": "Real Image Height"}
WAVE_PRESETS = {
    "F, d, C (visible)": ([0.4861327, 0.5875618, 0.6562725], 1),
    "F', e, C' (visible)": ([0.4799914, 0.5460740, 0.6438470], 1),
    "d (0.5876)": ([0.5875618], 0), "e (0.5461)": ([0.5460740], 0), "HeNe (0.6328)": ([0.6328], 0),
    "Nd:YAG (1.064)": ([1.064], 0), "NIR 0.8 / 0.85 / 0.9": ([0.8, 0.85, 0.9], 1),
    "SWIR 1.0 / 1.3 / 1.55": ([1.0, 1.3, 1.55], 1), "LWIR 8 / 10 / 12": ([8.0, 10.0, 12.0], 1),
}
FIELD_ATTRS = ["x", "y", "weight", "vdx", "vdy", "vcx", "vcy"]
APERTURE_KINDS = [("None", None, ()), ("Circular aperture", "CIRCULAR", ("r_max", "r_min", "dx", "dy")),
                  ("Circular obscuration", "OBSCURATION", ("radius", "dx", "dy")),
                  ("Rectangular aperture", "RECTANGULAR", ("half_x", "half_y", "dx", "dy")),
                  ("Elliptical aperture", "ELLIPTICAL", ("half_x", "half_y", "dx", "dy"))]
SOLVE_INT_FIELDS = ("from_surface", "center_surface")
SCRIPT_EXAMPLE = """# Python against the open lens: `lens`, `lf`, `opt`, `np` are defined.
# Changes to `lens` become one undoable edit (Ctrl+Enter runs).
print(lens.paraxial())
for i in range(len(lens.fields)):
    print(i, lf.spot_diagram(lens, i)["rms_radius"])
"""


def _num(x):
    """JSON-safe float (None for NaN / infinity)."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _png(fig, dpr=1.0) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=fig.dpi * dpr)
    return base64.b64encode(buf.getvalue()).decode()


def _figure(width, height, dpi=90):
    from matplotlib.figure import Figure
    w = max(2.0, float(width or 600) / dpi)
    h = max(1.5, float(height or 400) / dpi)
    return Figure(figsize=(w, h), dpi=dpi, layout="tight")


class _Never:
    def is_set(self):
        return False


class Session:
    def __init__(self):
        self.doc = WebDocument()
        self.namespace = {}          # Python Shell variables kept between runs
        self.opt_result = None       # optimised lens waiting for Load Result
        self.mc_result = None        # last Monte Carlo result (Load Worst)
        self.ns_scene = lf.nonseq.NonSequentialSystem("Scene")
        self.ns_result = None
        self.ns_path = None
        self.agf_names = []          # AGF catalogs loaded this session (name -> reloaded at start-up by the page)
        # hooks the worker replaces: progress reports to the page and the Stop button's flag
        self.report = lambda data: None
        self.stop = _Never()

    # ======================================================================== state
    def state(self) -> dict:
        """Everything the editors and the status bar show."""
        d = self.doc
        s = d.system
        mc = getattr(s, "multiconfig", None)
        return {
            "revision": d.revision,
            "title": d.display_name, "path": d.path, "modified": d.modified,
            "undo": d.undo_text, "redo": d.redo_text,
            "history": [t for t, _, _ in d.undo_stack], "history_index": d.index,
            "status": self._status(),
            "config": "" if mc is None or mc.n_configs < 2 else f"{mc.name(mc.current)} of {mc.n_configs}",
            "lde": self._lde(),
            "mfe": self._mfe_rows(),
            "mce": self._mce(),
            "fields": [f"{k + 1}: ({f.x:g}, {f.y:g})" for k, f in enumerate(s.fields)],
            "waves": [f"{k + 1}: {w.value:.4f} um" for k, w in enumerate(s.wavelengths)],
            "primary": s.primary_wavelength,
            "configs": [] if mc is None else [[k, mc.name(k)] for k in mc.configs],
            "current_config": None if mc is None else mc.current,
            "image_index": s.image_index,
            "missing": s.missing_materials_message(),
            "units": s.units,
        }

    def _status(self):
        s = self.doc.system
        missing = s.missing_materials()
        if missing:
            return {"text": f"Cannot trace: missing glass {', '.join(missing)}", "error": True}
        try:
            p = s.paraxial()
            txt = (f"EFL {p.efl:.6g}   WFNO {p.working_fnum:.4g}   ENPD {p.epd:.5g}   "
                   f"TOTR {sum(x.thickness for x in s.surfaces[1:-1]):.6g}   {s.units}")
            return {"text": txt, "error": False}
        except Exception as e:  # noqa: BLE001 - incomplete lens
            return {"text": f"first-order data unavailable ({type(e).__name__}: {e})", "error": True}

    # ======================================================================== menus / help
    def menus(self) -> dict:
        data = menus.menu_data()
        data["samples"] = [name for name, _ in sample_list()]
        return data

    def help_data(self) -> dict:
        topics = []
        for key, title in mfe_help.TOPICS:
            topics.append({"key": key, "title": title, "html": mfe_help.topic_html(key) or "",
                           "text": mfe_help.topic_text(key)})
        overview = OVERVIEW.replace("lensforge help", "LensForge help").replace(
            "Hovering a toolbar button", "Lens files are kept in this browser's storage (File &gt; Open, File &gt; "
            "Export to Disk). Hovering a toolbar button")
        return {"overview": overview, "topics": topics, "root": mfe_help.ROOT}

    def about(self) -> dict:
        return {"version": lf.__version__, "python": sys.version.split()[0], "numpy": np.__version__,
                "icon": APP_ICON}

    # ======================================================================== files
    def new_lens(self):
        self.doc.reset(E.new_system())
        return True

    def samples(self):
        return [name for name, _ in sample_list()]

    def load_sample(self, name):
        for n, fn in sample_list():
            if n == name:
                s = fn()
                if not s.name:
                    s.name = n
                self.doc.reset(s)
                return True
        raise KeyError(f"no sample lens {name!r}")

    def open_text(self, text, filename, path=None):
        """Open a lens from file text. ``path`` is its name in browser storage (None for an import:
        the lens is unsaved and named after the file)."""
        system = self.doc.load_text(text, filename)
        base = os.path.basename(filename or "lens")
        for ext in (".lens.json", ".json", ".zmx", ".zos"):
            if base.lower().endswith(ext):
                base = base[: -len(ext)]
                break
        self.doc.reset(system, path=path, import_name=None if path else base)
        notes = system.notes if system.notes.startswith("ZMX import ignored") else ""
        return {"missing": system.missing_materials_message(), "notes": notes, "name": self.doc.display_name}

    def lens_text(self):
        return self.doc.to_text()

    def mark_saved(self, path):
        self.doc.path = path
        self.doc.import_name = None
        self.doc.set_clean()
        return True

    def suggested_name(self):
        n = self.doc.display_name
        return n if n != "Untitled" else (self.doc.system.name or "Untitled")

    def lens_info(self, text, filename):
        """Name, surfaces and first-order data of a lens file (for the Open dialog's preview)."""
        try:
            s = self.doc.load_text(text, filename)
        except Exception as e:  # noqa: BLE001
            return {"error": f"{type(e).__name__}: {e}"}
        out = {"name": s.name, "surfaces": s.num_surfaces, "units": s.units, "missing": s.missing_materials_message()}
        try:
            p = s.paraxial()
            out["efl"], out["fnum"] = _num(p.efl), _num(p.working_fnum)
        except Exception:  # noqa: BLE001
            pass
        return out

    def session_dump(self):
        """The open lens and its name, for restoring the page after a reload."""
        return {"text": self.doc.to_text(), "path": self.doc.path, "import_name": self.doc.import_name,
                "modified": self.doc.modified}

    def session_restore(self, data):
        system = self.doc.load_text(data["text"], "session.lens.json")
        self.doc.reset(system, path=data.get("path"), import_name=data.get("import_name"))
        if data.get("modified"):
            self.doc.clean_index = -1
        return True

    def prescription(self):
        return REGISTRY["prescription"].compute(self.doc.system)

    def load_agf(self, name, text):
        cat = lf.load_agf(text, os.path.splitext(os.path.basename(name))[0])
        lf.shared_library().add_catalog(cat)
        self.agf_names.append(cat.name)
        self.doc.refresh()  # the new glasses may be the ones the lens was missing
        return {"catalog": cat.name, "glasses": len(cat.names())}

    # ======================================================================== undo
    def undo(self):
        return self.doc.undo()

    def redo(self):
        return self.doc.redo()

    def undo_to(self, index):
        self.doc.undo_to(index)
        return True

    def _modify(self, text, fn):
        ok = self.doc.modify(text, fn)
        if not ok:
            raise ValueError(self.doc.last_error)
        return True

    # ======================================================================== Lens Data Editor
    def _lde(self):
        s = self.doc.system
        _, auto_sd = E.fill_auto_semi_diameters(s)
        rows = []
        for i, srf in enumerate(s.surfaces):
            pars = E.parameter_columns(srf)
            cells = []
            for col in range(2, PAR0 + E.N_PAR):
                if col < PAR0:
                    key = LDE_FIXED[col][0]
                else:
                    k = col - PAR0
                    key = pars[k][1] if k < len(pars) else None
                cells.append(self._lde_cell(s, i, key, auto_sd))
            rows.append({
                "label": "OBJ" if i == 0 else ("IMA" if i == s.image_index else ("STO" if srf.stop else str(i))),
                "stop": bool(srf.stop), "kind": srf.kind, "type": E.SURFACE_TYPES.get(srf.kind, (srf.kind,))[0],
                "pars": [lab for lab, _ in pars], "cells": cells,
            })
        return {"rows": rows, "fixed": [lab for _, lab in LDE_FIXED], "n_par": E.N_PAR,
                "types": [[k, lab] for k, (lab, _) in E.SURFACE_TYPES.items()]}

    def _applies(self, s, row, key):
        if key is None:
            return False
        srf = s.surfaces[row]
        if key in ("radius", "conic"):
            return E.has_radius(srf)
        if key == "material":
            return not srf.is_coordinate_break and row != s.image_index
        if key == "thickness":
            return row != s.image_index
        if key == "semi_diameter":
            return not srf.is_coordinate_break
        return True

    def _missing(self, s, row):
        try:
            s.library.resolve(s.surfaces[row].material)
        except (KeyError, TypeError):
            return True
        return False

    def _lde_cell(self, s, row, key, auto_sd):
        if not self._applies(s, row, key):
            return {"k": key, "t": "", "na": True}
        srf = s.surfaces[row]
        out = {"k": key}
        if key == "comment":
            out["t"] = out["e"] = srf.comment
        elif key == "material":
            out["t"] = out["e"] = E.material_text(s, srf.material)
        elif key == "semi_diameter":
            if srf.semi_diameter is None:
                v = auto_sd.get(row)
                out["t"] = "" if v is None else E.format_number(v)
                out["e"] = out["t"]
                out["auto"] = True
            else:
                out["t"] = E.format_number(srf.semi_diameter)
                out["e"] = repr(srf.semi_diameter)
        else:
            v = E.get_value(srf, key)
            out["t"] = E.format_number(v)
            out["e"] = "Infinity" if isinstance(v, float) and math.isinf(v) else repr(v)
        # markers and colours (as LensDataModel.data)
        x = E.solve_on(s, row, key)
        var = E.variable_on(s, row, key)
        if x is not None:
            out["m"] = E.SOLVE_CODES.get(type(x).__name__, "S")
            out["solve"] = True
        elif var is not None:
            out["m"] = "V"
            out["var"] = True
        elif key == "semi_diameter" and srf.semi_diameter is not None:
            out["m"] = "U"
        if key == "material" and self._missing(s, row):
            out["missing"] = True
        parts = [f"Surface {row}: {key}"]
        if x is not None:
            parts.append(E.describe_solve(x))
        if var is not None:
            b = "" if var.min is None and var.max is None else f" in [{var.min}, {var.max}]"
            parts.append(f"Variable {var.param}{b}")
        if key == "semi_diameter":
            parts.append("fixed (type a value; clear the cell for automatic)" if srf.semi_diameter is not None
                         else "automatic")
        if key == "material" and out.get("missing"):
            parts.append(f"{srf.material} is not in any loaded glass catalog: this lens cannot be traced")
        if key == "material":
            parts.append("catalog glass (e.g. N-BK7, SCHOTT:N-SF6), model glass 'nd,vd', index, or MIRROR")
        out["tip"] = "\n".join(parts)
        out["ro"] = x is not None  # a solved cell is not typed into
        return out

    def _key(self, row, col):
        if col < PAR0:
            return LDE_FIXED[col][0]
        pars = E.parameter_columns(self.doc.system.surfaces[row])
        k = col - PAR0
        return pars[k][1] if k < len(pars) else None

    def set_cell(self, row, key, text):
        if key == "type":
            return self.set_type(row, text)
        label = dict(LDE_FIXED).get(key, key)
        return self._modify(f"Surface {row} {label} = {text}", lambda s: E.set_cell(s, row, key, text))

    def set_type(self, row, kind):
        if kind not in E.SURFACE_TYPES:
            kind = next((k for k, (lab, _) in E.SURFACE_TYPES.items() if lab == kind), kind)
        return self._modify(f"Surface {row} type {kind}", lambda s: E.change_type(s, row, kind))

    def insert_surface(self, row, after=False):
        row = min(row + 1, self.doc.system.image_index) if after else max(1, row)
        self._modify(f"Insert surface {row}", lambda s: E.insert_surface(s, row))
        return row

    def delete_surface(self, row):
        self._modify(f"Delete surface {row}", lambda s: E.delete_surface(s, row))
        return row

    def describe_deletion(self, first, last):
        try:
            return {"lines": E.describe_deletion(self.doc.system, first, last)}
        except ValueError as e:
            return {"error": str(e)}

    def delete_range(self, first, last):
        text = f"Delete surface {first}" if first == last else f"Delete surfaces {first}-{last}"
        return self._modify(text, lambda s: E.delete_surfaces(s, first, last))

    def make_stop(self, row):
        return self._modify(f"Stop on surface {row}", lambda s: E.set_stop(s, row))

    def can_vary(self, row, key):
        s = self.doc.system
        if key is None or not self._applies(s, row, key):
            return False
        if key in ("comment", "semi_diameter", "order"):
            return False
        if key == "thickness" and math.isinf(s.surfaces[row].thickness):
            return False
        if key == "material":
            try:
                m = s.material(row)
            except KeyError:  # missing glass
                return False
            return not m.is_mirror and m.nd != 1.0
        return True

    def toggle_variable(self, row, key):
        s = self.doc.system
        if not self.can_vary(row, key):
            raise ValueError("This cell cannot be a variable")
        v = E.variable_on(s, row, key)
        if v is not None:
            return self._modify(f"Remove variable S{row} {v.param}", lambda x: opt.remove_variable(x, row, v.param))
        if key == "material":
            def fn(x):
                opt.remove_solve(x, row, "material")
                opt.set_variable(x, row, "glass.nd")
                opt.set_variable(x, row, "glass.vd")
            return self._modify(f"Vary glass on S{row} (model nd, Vd)", fn)

        def fn(x):
            opt.remove_solve(x, row, E.cell_param(key))
            opt.set_variable(x, row, E.cell_param(key))
        return self._modify(f"Variable S{row} {key}", fn)

    def context_menu(self, row, col):
        """The Lens Data Editor's right-click menu for a cell (as LensDataEditor._context_menu)."""
        s = self.doc.system
        key = self._key(row, col) if col >= 2 else None
        items = []
        if col >= 3 and self._applies(s, row, key):
            if self.can_vary(row, key):
                is_var = E.variable_on(s, row, key) is not None
                items.append({"label": "Remove Variable" if is_var else
                              ("Vary Glass (model nd, Vd)" if key == "material" else "Make Variable"),
                              "cmd": "toggle_variable", "args": [row, key]})
            names = E.SOLVES_FOR.get(key, ["Pickup"] if key not in ("comment", "semi_diameter") else [])
            if names and row != 0 and not (key == "thickness" and row == s.image_index):
                sub = [{"label": E.SOLVE_TITLES[n] + "...", "cmd": "solve_dialog", "args": [row, key, n]}
                       for n in names]
                if E.solve_on(s, row, key) is not None:
                    sub += [None, {"label": "Remove Solve (fixed)", "cmd": "remove_solve", "args": [row, key]}]
                items.append({"label": "Solve", "items": sub})
            if key == "semi_diameter" and s.surfaces[row].semi_diameter is not None:
                items.append({"label": "Automatic Semi-Diameter", "cmd": "set_cell", "args": [row, "semi_diameter", ""]})
            items.append(None)
        if self._applies(s, row, "material"):
            items.append({"label": "Choose Material...", "cmd": "material_dialog", "args": [row]})
        items.append({"label": "Surface Type", "items": [
            {"label": lab, "cmd": "set_type", "args": [row, k], "checked": s.surfaces[row].kind == k}
            for k, (lab, _) in E.SURFACE_TYPES.items()]})
        if 0 < row < s.image_index:
            items.append({"label": "Make Stop", "cmd": "make_stop", "args": [row]})
        items.append({"label": "Surface Properties...", "cmd": "surface_properties", "args": [row],
                      "id": "Edit > Surface Properties"})
        items.append(None)
        for lab, iid in (("Insert Surface", "Edit > Insert Surface"), ("Insert Surface After", "Edit > Insert Surface After"),
                         ("Delete Surface", "Edit > Delete Surface"), ("Delete Surfaces...", "Edit > Delete Surfaces")):
            items.append({"label": lab, "id": iid})
        return items

    # -- solves ------------------------------------------------------------------------------
    def solve_form(self, row, key, name):
        current = E.solve_on(self.doc.system, row, key)
        if type(current).__name__ != name:
            current = None
        fields = []
        for f, default in E.solve_fields(name):
            if name == "Pickup" and key == "material" and f in ("scale", "offset", "from_param"):
                continue
            v = getattr(current, f) if current is not None else default
            if name == "Pickup" and f == "from_surface" and v is None:
                v = max(1, row - 1)
            ph = ""
            if f == "from_param":
                ph = f"same as this cell ({key})"
            if f == "height" and name == "EdgeThickness":
                ph = "larger semi-diameter"
            fields.append({"name": f, "label": f.replace("_", " ").capitalize(), "value": "" if v is None else str(v),
                           "placeholder": ph})
        doc = " ".join((E.solve_class(name).__doc__ or "").split())
        return {"title": f"{E.SOLVE_TITLES[name]} solve on surface {row} ({key})", "doc": doc, "fields": fields}

    def set_solve(self, row, key, name, values):
        out = {}
        for f, t in values.items():
            t = str(t).strip()
            if not t:
                if f == "from_surface":
                    raise ValueError("from surface is required")
                continue
            if f in SOLVE_INT_FIELDS:
                out[f] = int(t)
            elif f == "from_param":
                out[f] = E.cell_param(t)
            else:
                out[f] = E.parse_number(t)

        def fn(s):
            opt.remove_variable(s, row, E.cell_param(key))
            opt.set_solve(s, E.make_solve(name, row, key, out))
        return self._modify(f"{E.SOLVE_TITLES[name]} solve on S{row} {key}", fn)

    def remove_solve(self, row, key):
        return self._modify(f"Remove solve S{row} {key}", lambda s: opt.remove_solve(s, row, E.cell_param(key)))

    # -- surface properties ---------------------------------------------------------------------
    def surface_properties(self, row):
        s = self.doc.system
        srf = s.surfaces[row]
        ap = srf.aperture
        vals = {}
        for name in ("r_max", "r_min", "radius", "half_x", "half_y", "dx", "dy"):
            vals[name] = E.format_number(getattr(ap, name), 10) if ap is not None and hasattr(ap, name) else ""
        return {"title": f"Surface {row} properties ({E.SURFACE_TYPES.get(srf.kind, (srf.kind,))[0]})",
                "comment": srf.comment, "stop": bool(srf.stop), "stop_enabled": 0 < row < s.image_index,
                "kinds": [[lab, k, list(names)] for lab, k, names in APERTURE_KINDS],
                "aperture": ap.kind if ap is not None else None, "values": vals,
                "terms": "\n".join(f"{i} {j} {c!r}" for i, j, c in srf.terms) if srf.kind == "XYPOLY" else None}

    def set_surface_properties(self, row, data):
        kind = data.get("aperture")
        names = next(n for _, k, n in APERTURE_KINDS if k == kind)
        aperture = None
        if kind is not None:
            vals = {n: E.parse_number(str(data["values"].get(n) or "0"), allow_inf=False) for n in names}
            aperture = S.aperture_from_dict({"type": kind, **vals})
        terms = None
        if data.get("terms") is not None:
            terms = []
            for line in str(data["terms"]).splitlines():
                if line.strip():
                    i, j, c = line.replace(",", " ").split()
                    terms.append([int(i), int(j), float(c)])

        def fn(s):
            srf = s.surfaces[row]
            srf.comment = data.get("comment", "")
            srf.aperture = aperture
            if data.get("stop") and 0 < row < s.image_index:
                s.stop_index = row
            if terms is not None:
                srf.terms = terms
        return self._modify(f"Surface {row} properties", fn)

    # -- materials ----------------------------------------------------------------------------
    def material_search(self, text):
        t = str(text).strip()
        if not t or "," in t:
            return []
        try:
            float(t)
            return []
        except ValueError:
            pass
        hits = self.doc.system.library.search(t, limit=200)
        if "MIRROR".startswith(t.upper()):
            hits.append("MIRROR")
        return hits

    def catalog_rows(self):
        lib = self.doc.system.library
        return {"catalogs": list(lib.catalogs), "rows": [[spec, cat, name, round(nd, 6), round(vd, 3)]
                                                          for spec, cat, name, nd, vd in E.catalog_rows(lib)]}

    def material_dialog(self, row):
        """The material picker's starting state for the material after surface ``row``."""
        s = self.doc.system
        if not self._applies(s, row, "material"):
            raise ValueError("This surface has no material")
        current = s.surfaces[row].material
        out = {"title": f"Material after surface {row}", "row": row, "tab": 0, "spec": None,
               "nd": 1.5168, "vd": 64.17, "dpgf": 0.0, "other": "air", "n": 1.333}
        m = None
        try:
            m = s.library.resolve(current)
        except Exception:  # noqa: BLE001
            pass
        if current is None or current == "" or (m is not None and not m.is_mirror and m.nd == 1.0
                                                 and isinstance(m, ConstantIndex)):
            out.update(tab=2, other="air")
        elif m is not None and m.is_mirror:
            out.update(tab=2, other="mirror")
        elif isinstance(m, ModelGlass):
            out.update(tab=1, nd=m.nd_value, vd=m.vd_value, dpgf=m.dpgf)
        elif isinstance(m, ConstantIndex):
            out.update(tab=2, other="const", n=m.n)
        elif m is not None:
            name = getattr(m, "name", "")
            cat = getattr(m, "catalog", None)
            rows = E.catalog_rows(s.library)
            out.update(tab=0, spec=next((r[0] for r in rows if r[2] == name and (cat is None or r[1] == cat)), None))
        return out

    def material_preview(self, spec):
        if spec is None:
            return "Select a glass."
        if spec in ("", "MIRROR"):
            return "Air" if spec == "" else "Mirror"
        s = self.doc.system
        try:
            m = s.library.resolve(spec)
            idx = ", ".join(f"n({w.value:.4f}) = {float(m.index(w.value)):.6f}" for w in s.wavelengths)
            return f"<b>{html.escape(spec)}</b>: nd {m.nd:.6f}, Vd {m.vd:.3f}<br>{idx}"
        except Exception as e:  # noqa: BLE001
            return f"{html.escape(str(spec))}: {html.escape(str(e))}"

    def squash(self, text):
        return _squash(text)

    # -- whole-lens edits (Edit and Tools menus) ---------------------------------------------------
    def quick_focus(self):
        return self._modify("Quick focus", lambda s: lf.samples.focus_paraxial(s))

    def fix_semi_diameters(self):
        def fn(s):
            _, vals = E.fill_auto_semi_diameters(s)
            for i, v in vals.items():
                s.surfaces[i].semi_diameter = v
        return self._modify("Fix semi-diameters", fn)

    def auto_semi_diameters(self):
        def fn(s):
            for x in s.surfaces:
                x.semi_diameter = None
        return self._modify("Automatic semi-diameters", fn)

    def vary_curvatures(self):
        return self._modify("Vary all curvatures", lambda s: opt.vary_curvatures(s))

    def vary_air_spaces(self):
        return self._modify("Vary air spaces", lambda s: opt.vary_thicknesses(s, air_only=True))

    def clear_variables(self):
        return self._modify("Remove all variables", lambda s: opt.clear_variables(s))

    def clear_solves(self):
        return self._modify("Remove all solves", lambda s: setattr(s, "solves", []))

    # ======================================================================== System Explorer
    def system_settings(self):
        s = self.doc.system
        return {
            "aperture_types": [[k, APERTURE_LABELS[k]] for k in APERTURE_TYPES],
            "field_types": [[k, FIELD_LABELS[k]] for k in FIELD_TYPES],
            "aperture_type": s.aperture_type, "aperture_value": repr(s.aperture_value), "ray_aiming": s.ray_aiming,
            "field_type": s.field_type,
            "fields": [[E.format_number(getattr(f, a), 10) for a in FIELD_ATTRS] for f in s.fields],
            "waves": [[f"{w.value:.10g}", E.format_number(w.weight, 10)] for w in s.wavelengths],
            "primary": s.primary_wavelength, "name": s.name, "units": s.units, "notes": s.notes,
            "presets": {k: [[f"{w:g}" for w in v[0]], v[1]] for k, v in WAVE_PRESETS.items()},
        }

    def apply_system_settings(self, d):
        def num(t, default):
            t = str(t).strip()
            return default if not t else E.parse_number(t, allow_inf=False)
        fields = [Field(**{a: num(row[c] if c < len(row) else "", 1.0 if a == "weight" else 0.0)
                           for c, a in enumerate(FIELD_ATTRS)}) for row in d["fields"]]
        waves = [Wavelength(num(row[0], 0.0), num(row[1] if len(row) > 1 else "", 1.0)) for row in d["waves"]]
        if not fields or not waves:
            raise ValueError("at least one field and one wavelength are needed")
        if any(w.value <= 0 for w in waves):
            raise ValueError("wavelengths must be positive")
        value = E.parse_number(str(d["aperture_value"]), allow_inf=False)
        if value <= 0:
            raise ValueError("the aperture value must be positive")
        vals = dict(aperture_type=d["aperture_type"], aperture_value=value, ray_aiming=d["ray_aiming"],
                    field_type=d["field_type"], fields=fields, wavelengths=waves,
                    primary_wavelength=max(0, min(int(d.get("primary", 0)), len(waves) - 1)),
                    name=d.get("name", ""), units=d.get("units", "mm"), notes=d.get("notes", ""))

        def fn(s):
            for k, v in vals.items():
                setattr(s, k, v)
        return self._modify("System settings", fn)

    # ======================================================================== Input Rays
    def input_rays(self):
        s = self.doc.system
        ir = R.get(s)
        lw = ir["layout_waves"]
        if lw == "primary":
            lwi = [s.primary_wavelength]
        elif lw == "all":
            lwi = list(range(len(s.wavelengths)))
        else:
            lwi = [int(i) for i in lw]
        return {"settings": ir, "patterns": R.PATTERNS,
                "fields": [f"Field {k + 1}: ({x.x:g}, {x.y:g})" for k, x in enumerate(s.fields)],
                "waves": [f"{w.value:.4f} um" + (" (primary)" if k == s.primary_wavelength else "")
                          for k, w in enumerate(s.wavelengths)],
                "layout_fields": R.fields(s, ir["layout_fields"]), "layout_waves": lwi}

    def set_input_rays(self, d):
        s = self.doc.system
        nf, nw = len(s.fields), len(s.wavelengths)
        out = dict(d)
        f = sorted(int(i) for i in d.get("layout_fields", []))
        out["layout_fields"] = "all" if f == list(range(nf)) or not f else f
        w = sorted(int(i) for i in d.get("layout_waves", []))
        if w == list(range(nw)) and nw > 1:
            out["layout_waves"] = "all"
        elif not w or w == [s.primary_wavelength]:
            out["layout_waves"] = "primary"
        else:
            out["layout_waves"] = w
        return self._modify("Input rays", lambda x: R.set(x, out))

    def pupil_pattern(self, pattern, n):
        px, py = lf.pupil_grid(pattern, int(n))
        return {"x": [round(float(v), 4) for v in px], "y": [round(float(v), 4) for v in py]}

    # ======================================================================== analyses
    def analysis_specs(self):
        out = {}
        for k, spec in REGISTRY.items():
            out[k] = {"key": k, "title": spec.title, "group": spec.group, "text": spec.plot is None,
                      "uses_rays": spec.uses_rays, "shortcut": spec.shortcut,
                      "id": f"Analysis > {spec.group} > {spec.title}",
                      "settings": [{"name": st.name, "label": st.label, "kind": st.kind, "default": st.default,
                                    "choices": st.choices, "min": st.minimum, "max": st.maximum}
                                   for st in spec.settings]}
        return out

    def _analysis_system(self, config):
        s = self.doc.system
        mc = getattr(s, "multiconfig", None)
        k = int(config or 0)
        if k and mc is not None and k <= mc.n_configs and k != mc.current:
            return s.config_copy(k)
        return s.copy()

    def run_analysis(self, key, opts=None, config=0, width=600, height=400, dpr=1.0):
        """Compute one analysis: {"png": base64} for a plot, {"text": ...} for a report, or {"error": ...}."""
        spec = REGISTRY[key]
        missing = self.doc.system.missing_materials_message()
        if missing:  # cannot trace: say why instead of showing old results
            return {"error": f"Cannot trace this lens. {missing} {MISSING_HINT}"}
        values = {st.name: st.default for st in spec.settings}
        values.update({k: v for k, v in (opts or {}).items() if k in values})
        for st in spec.settings:  # the page sends numbers as numbers, but be forgiving
            v = values[st.name]
            if st.kind in ("int", "surface") and v is not None:
                values[st.name] = int(v)
            elif st.kind == "float" and v is not None:
                values[st.name] = float(v)
        system = self._analysis_system(config)
        try:
            result = spec.compute(system, **values)
        except Exception as e:  # noqa: BLE001
            return {"error": f"{type(e).__name__}: {e}"}
        if spec.plot is None:
            return {"text": result if isinstance(result, str) else str(result)}
        try:
            fig = _figure(width, height)
            spec.plot(fig, result, values, system)
            return {"png": _png(fig, dpr)}
        except Exception as e:  # noqa: BLE001
            return {"error": f"Plot failed: {type(e).__name__}: {e}"}

    # ======================================================================== Merit Function Editor
    def _mf(self, system=None, create=False):
        s = system if system is not None else self.doc.system
        mf = getattr(s, "merit_function", None)
        if mf is None and create:
            mf = opt.MeritFunction()
            s.merit_function = mf
        return mf

    def _mfe_rows(self):
        mf = self._mf()
        rows = []
        for r in (mf.rows if mf is not None else []):
            rows.append({"type": r.type, "params": E.format_params(r.params), "bound": r.bound,
                         "target": E.format_number(r.target, 8), "target_e": repr(r.target),
                         "weight": E.format_number(r.weight, 8), "weight_e": repr(r.weight), "comment": r.comment,
                         "w": r.weight, "tip": mfe_help.operand_tooltip(r.type)})
        return {"rows": rows, "columns": MFE_COLUMNS,
                "column_tips": [mfe_help.COLUMN_TIPS[c] for c in MFE_COLUMNS]}

    def mfe_evaluate(self):
        """Values and % contributions of the merit rows (the slow part; the page asks after each change)."""
        mf = self._mf()
        rev = self.doc.revision
        if mf is None or not mf.rows:
            return {"revision": rev, "value": None, "rows": []}
        try:
            ev = mf.copy().evaluate(self.doc.system.copy())
        except Exception as e:  # noqa: BLE001
            return {"revision": rev, "value": None, "rows": [], "error": f"{type(e).__name__}: {e}"}
        rows = []
        for i, r in enumerate(mf.rows):
            v = ev.scalars[i] if i < len(ev.scalars) else None
            val = "" if v is None or (isinstance(v, float) and math.isnan(v)) else E.format_number(v, 8)
            con = "" if r.weight <= 0 or i >= len(ev.contributions) else f"{100 * ev.contributions[i]:.3f}"
            rows.append([val, con])
        return {"revision": rev, "value": _num(ev.value), "rows": rows, "error": ev.error or ""}

    def mfe_set(self, r, c, text):
        text = str(text)

        def fn(s):
            row = self._mf(s).rows[r]
            if c == 0:
                t = text.strip().upper()
                opt.Operand(t, params={})  # validates the name
                row.type = t
                from lensforge.optimize.operands import DEFAULT_BOUND
                row.bound = DEFAULT_BOUND[t]
                self._mf(s).auto_weight()
            elif c == 1:
                row.params = E.parse_params(text)
            elif c == 2:
                if text.strip() not in ("=", ">", "<"):
                    raise ValueError("bound must be =, > or <")
                row.bound = text.strip()
            elif c == 3:
                row.target = E.parse_number(text, allow_inf=False)
            elif c == 4:
                row.weight = E.parse_number(text, allow_inf=False)
            elif c == 7:
                row.comment = text
        return self._modify(f"Merit row {r + 1} {MFE_COLUMNS[c]}", fn)

    def mfe_add(self):
        self._modify("Add merit row", lambda s: self._mf(s, True).add("BLNK", weight=0))
        return len(self._mf().rows) - 1

    def mfe_insert(self, r):
        self._modify("Insert merit row", lambda s: self._mf(s, True).insert(r, "BLNK", weight=0))
        return r

    def mfe_delete(self, rows):
        rows = sorted({int(r) for r in rows}, reverse=True)
        if not rows:
            return False

        def fn(s):
            for r in rows:
                self._mf(s).remove(r)
        return self._modify(f"Delete {len(rows)} merit row(s)", fn)

    def mfe_clear(self):
        return self._modify("Clear merit function", lambda s: self._mf(s, True).clear())

    def operands(self):
        return [[k, opt.OPERAND_INFO[k]] for k in sorted(opt.OPERAND_INFO)]

    def operand_names(self):
        return sorted(opt.OPERANDS)

    def mfe_insert_operand(self, r, t):
        self._modify(f"Insert {t}", lambda s: self._mf(s, True).insert(r, t, weight=1.0))
        return r

    def wizard_info(self):
        mc = getattr(self.doc.system, "multiconfig", None)
        n = mc.n_configs if mc is not None else 1
        return {"configs": n}

    def mfe_wizard(self, kw, keep=True):
        kw = dict(kw)
        if kw.get("kind") != "mtf":
            kw.pop("frequency", None)

        def fn(s):
            new = opt.default_merit(s, **kw)
            old = self._mf(s, True)
            if keep:  # keep the user's rows that are not part of a default merit function
                user = [r for r in old.rows if r.type not in ("RAYS", "OPDS", "MTFA", "CONF") and
                        not (r.type == "BLNK" and r.comment.startswith("Default merit"))
                        and r.type not in ("MNCG", "MXCG", "MNEG", "MNCA", "MXCA", "MNEA")]
                new.rows = user + new.rows
            s.merit_function = new
        return self._modify("Default merit function", fn)

    # ======================================================================== Multi-Configuration Editor
    def _mce(self):
        s = self.doc.system
        mc = getattr(s, "multiconfig", None)
        if mc is None:
            return {"n": 0, "rows": [], "label": "Single configuration. Insert an operand or add a configuration "
                    "to start a multi-configuration lens.", "operands": sorted(MC_OPERANDS)}
        errs = mc.errors(s)
        rows = []
        for i, r in enumerate(mc.rows):
            cells = []
            for k in range(1, mc.n_configs + 1):
                cells.append({"t": format_value(r, r.values[k - 1]), "var": bool(opt.is_mc_variable(s, i, k))})
            rows.append({"type": r.type, "ref": "" if r.ref is None else str(r.ref), "param": r.param or "",
                         "has_ref": r.ref is not None, "has_param": r.type == "PARM", "fixed": r.type == "MOFF",
                         "glass": r.type == "GLSS", "error": errs[i] if i < len(errs) else None,
                         "tip": f"{r.label}: {MC_OPERANDS[r.type][1]}",
                         "ref_tip": f"Ref: {MCE_REF_HELP.get(r.ref_kind, '')}", "cells": cells})
        bad = sum(1 for e in errs if e)
        nv = sum(1 for v in opt.variables(s) if isinstance(v, opt.MCVariable))
        txt = f"{mc.n_configs} configurations, {len(mc.rows)} operands. Current: {mc.name(mc.current)}."
        if nv:
            txt += f" {nv} variable cell{'s' if nv > 1 else ''}."
        if bad:
            txt += f" {bad} row{'s' if bad > 1 else ''} cannot be applied (red)."
        return {"n": mc.n_configs, "current": mc.current, "names": list(mc.names),
                "labels": [mc.name(k) for k in mc.configs], "rows": rows, "label": txt, "bad": bad,
                "operands": sorted(MC_OPERANDS)}

    def mce_set(self, i, c, text):
        text = str(text).strip()

        def fn(s):
            mc = E.multiconfig(s)
            r = mc.rows[i]
            if c == 0:
                t = text.upper()
                if t not in MC_OPERANDS:
                    raise ValueError(f"unknown operand {text!r}")
                param = r.param if t == "PARM" else None
                if t == "PARM" and not param:
                    param = "conic"
                mc.set_row_operand(s, i, t, r.ref, param)
                E.drop_row_variables(s, i)
            elif c == 1:
                mc.set_row_operand(s, i, r.type, int(text), r.param)
                E.drop_row_variables(s, i)
            elif c == 2:
                mc.set_row_operand(s, i, r.type, r.ref, text)
                E.drop_row_variables(s, i)
            else:
                mc.set_value(s, i, c - 2, text)
        what = MCE_FIXED[c] if c < 3 else f"config {c - 2}"
        return self._modify(f"Multi-config row {i + 1} {what}", fn)

    def mce_insert(self, r):
        def fn(s):
            E.multiconfig(s, create=True).add_row(s, "THIC", 1, index=r)
            E.shift_mc_variables(s, r, +1)
        self._modify("Insert multi-config operand", fn)
        return r

    def mce_delete(self, rows):
        rows = sorted({int(r) for r in rows})
        if not rows or E.multiconfig(self.doc.system) is None:
            return False
        return self._modify(f"Delete {len(rows)} multi-config operand(s)", lambda s: remove_mc_rows(s, rows))

    def mce_add_config(self, k):
        def fn(s):
            mc = E.multiconfig(s, create=True)
            new = mc.insert_config(s, at=k + 1, copy_from=k)
            E.shift_mc_configs(s, new, +1)
        return self._modify("Add configuration", fn)

    def mce_delete_config(self, k):
        mc = E.multiconfig(self.doc.system)
        if mc is None or mc.n_configs < 2:
            raise ValueError("The last configuration cannot be deleted")

        def fn(s):
            E.shift_mc_configs(s, k, -1)
            E.multiconfig(s).remove_config(s, k)
        return self._modify(f"Delete configuration {k}", fn)

    def mce_rename_config(self, k, name):
        def fn(s):
            E.multiconfig(s).names[k - 1] = str(name).strip()
        return self._modify(f"Rename configuration {k}", fn)

    def switch_config(self, k):
        mc = E.multiconfig(self.doc.system)
        if mc is None or not 1 <= k <= mc.n_configs or k == mc.current:
            return False
        return self._modify(f"Switch to {mc.name(k)}", lambda s: s.set_config(k))

    def step_config(self, step):
        mc = getattr(self.doc.system, "multiconfig", None)
        if mc is None or mc.n_configs < 2:
            raise ValueError("This lens has a single configuration (Tools > Multi-Configuration Editor adds more)")
        return self.switch_config((mc.current - 1 + step) % mc.n_configs + 1)

    def mce_toggle_variable(self, cells):
        cells = [(int(r), int(k)) for r, k in cells]
        if not cells:
            raise ValueError("Select value cells (configuration columns) to make them variable")

        def fn(s):
            for row, k in cells:
                if opt.is_mc_variable(s, row, k):
                    opt.remove_mc_variable(s, row, k)
                else:
                    opt.set_mc_variable(s, row, k)
        return self._modify("Toggle multi-config variable", fn)

    # ======================================================================== Python Shell
    def script_example(self):
        return SCRIPT_EXAMPLE

    def run_script(self, code):
        buf = io.StringIO()
        failed = []

        def fn(lens):
            ns = dict(self.namespace, lens=lens, lf=lf, opt=opt, np=np)
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                try:
                    exec(compile(code, "<script>", "exec"), ns)
                except Exception:  # noqa: BLE001 - the traceback is shown to the user
                    failed.append(traceback.format_exc(limit=-3))
            self.namespace = {k: v for k, v in ns.items() if k not in ("lens", "__builtins__")}
            if failed:
                raise RuntimeError("the script raised an exception; the lens was left unchanged")

        rev = self.doc.revision
        self.doc.modify("Script", fn)
        unchanged = self.doc.revision == rev
        out = buf.getvalue()
        if failed:
            out += failed[0]
        return out.rstrip() or ("(no output)" if unchanged else "(lens updated)")

    # ======================================================================== Optimization
    def opt_info(self):
        s = self.doc.system
        vs = getattr(s, "variables", None) or []
        mf = getattr(s, "merit_function", None)
        names = ", ".join(v.name for v in vs[:12]) + (" ..." if len(vs) > 12 else "")
        merit = None
        if mf is not None and mf.rows:
            try:
                merit = _num(mf.value(s))
            except Exception:  # noqa: BLE001
                merit = None
        return {"info": f"{len(vs)} variable(s): {names or 'none (right-click a cell in the Lens Data Editor)'}"
                        f"\n{len(mf.rows) if mf else 0} merit function row(s)",
                "n_vars": len(vs), "n_rows": len(mf.rows) if mf else 0, "merit": merit,
                "algorithms": [[k, lab] for lab, k in ALGORITHMS],
                "catalogs": [c for c in s.library.catalogs if c not in ("MISC", "INFRARED")],
                "has_result": self.opt_result is not None}

    def optimize(self, algorithm, cycles=50, trials=50, time_limit=0.0, nearest=5, catalog=None):
        """Run one algorithm on a copy of the lens (progress goes to :attr:`report`; :attr:`stop` stops it).
        The result waits in :attr:`opt_result` until :meth:`load_optimization_result`."""
        s = self.doc.system
        if not getattr(s, "variables", None) and algorithm != "glass":
            raise ValueError("There are no variables. Right-click a radius, thickness, conic or material cell in "
                             "the Lens Data Editor and choose Make Variable.")
        mf = getattr(s, "merit_function", None)
        if mf is None or not mf.rows:
            raise ValueError("The merit function is empty. Use the Merit Function Editor (its Wizard builds a "
                             "default merit function).")
        if mf.copy().auto_weight():
            self._modify("Merit weight 1", lambda x: x.merit_function.auto_weight())
            s, mf = self.doc.system, self.doc.system.merit_function
        system, merit = s.copy(), mf.copy()
        t0 = time.time()

        def report(p):
            self.report({"kind": "optimize", "best": _num(p["best"]), "evaluations": p["evaluations"],
                         "seconds": round(time.time() - t0, 1)})
        res, msg, hist = run_optimization(system, merit, algorithm, self.stop, report, cycles=int(cycles),
                                          trials=int(trials), starts=int(trials), time_limit=float(time_limit or 0),
                                          nearest=int(nearest), catalogs=[catalog] if catalog else None)
        self.opt_result = res
        try:
            mv = res.merit_function.value(res) if getattr(res, "merit_function", None) else math.nan
        except Exception:  # noqa: BLE001
            mv = math.nan
        return {"message": msg, "history": [_num(v) for v in hist], "merit": _num(mv)}

    def load_optimization_result(self, label="Optimization"):
        if self.opt_result is None:
            return False
        self.doc.replace(label, self.opt_result)
        self.opt_result = None
        return True

    def history_plot(self, values, width=400, height=150, dpr=1.0):
        fig = _figure(width, height, dpi=80)
        ax = fig.add_subplot(111)
        h = [v for v in values if v is not None and math.isfinite(v) and v > 0]
        if h:
            ax.semilogy(h, ".-", ms=3)
        ax.set_xlabel("progress updates", fontsize=8)
        ax.set_ylabel("merit", fontsize=8)
        ax.tick_params(labelsize=7)
        return _png(fig, dpr)

    # ======================================================================== Tolerancing
    def tolerance_setup(self):
        return {"criteria": [[k, lab] for lab, k in CRITERIA], "compensators": [[k, lab] for lab, k in COMPENSATORS],
                "distributions": DISTRIBUTIONS, "types": list(opt.tolerance.TOLERANCE_TYPES),
                "wizard": [["fringes", "Power (fringes)", 2.0, 2], ["thickness", "Thickness", 0.05, 4],
                           ["surface_decenter", "Surface decenter", 0.01, 4],
                           ["surface_tilt", "Surface tilt (deg)", 0.01, 4],
                           ["element_decenter", "Element decenter", 0.02, 4],
                           ["element_tilt", "Element tilt (deg)", 0.02, 4], ["index", "Index", 0.0005, 5],
                           ["abbe_percent", "Abbe (%)", 0.5, 2]]}

    def default_tolerances(self, wiz):
        tols = opt.default_tolerances(self.doc.system, **{k: float(v) for k, v in wiz.items()})
        return [[t.type, str(t.surface), "" if t.surface2 is None else str(t.surface2), t.param or "",
                 f"{t.min:.6g}", f"{t.max:.6g}", t.comment] for t in tols]

    def tolerance_run(self, what, rows, criterion="rms_spot", frequency=30.0, compensator="focus", trials=100,
                      distribution="normal", seed=0, width=420, height=300, dpr=1.0):
        tols = []
        for v in rows:
            v = [str(x).strip() for x in list(v) + [""] * (7 - len(v))]
            if not v[0]:
                continue
            tols.append(opt.Tolerance(v[0].upper(), int(v[1]), float(v[4]), float(v[5]),
                                      int(v[2]) if v[2] else None, v[3] or None, None, v[6]))
        if not tols:
            raise ValueError("the tolerance list is empty")
        system = self.doc.system.copy()
        if criterion == "merit" and not (getattr(system, "merit_function", None) and system.merit_function.rows):
            raise ValueError("The lens has no merit function.")
        total = 1 + (2 * len(tols) if what == "sensitivity" else int(trials))
        t0 = time.time()

        def report(p):
            self.report({"kind": "tolerance", "done": p["done"], "total": p["total"],
                         "seconds": round(time.time() - t0, 1)})
        crit = watched_criterion(system, criterion, float(frequency), self.stop, report, total)
        fig = _figure(width, height, dpi=80)
        ax = fig.add_subplot(111)
        from lensforge.optimize.tolerance import sensitivity_table
        try:
            if what == "sensitivity":
                r = opt.sensitivity_analysis(system, tols, crit, compensators=compensator, frequency=float(frequency))
            else:
                r = opt.monte_carlo(system, tols, int(trials), crit, compensators=compensator,
                                    frequency=float(frequency), distribution=distribution, seed=int(seed))
        except StopRequested:
            return {"text": "Stopped.", "png": None, "worst": False}
        if what == "sensitivity":
            text = sensitivity_table(r) + "\n\nWorst offenders:\n" + sensitivity_table(r, 10).split("\n", 2)[2]
            worst = r["worst"][:12]
            labels = [w["label"] for w in worst][::-1]
            vals = [max(abs(w["change_min"]), abs(w["change_max"])) for w in worst][::-1]
            ax.barh(range(len(vals)), vals)
            ax.set_yticks(range(len(vals)))
            ax.set_yticklabels(labels, fontsize=7)
            ax.set_xlabel(f"change in {r['criterion']}", fontsize=8)
            ax.set_title("Worst offenders", fontsize=9)
            has_worst = False
        else:
            self.mc_result = r
            text = r.summary() + f"\n  ({r.seconds:.1f} s)"
            v = r.values[np.isfinite(r.values)]
            if v.size:
                ax.hist(v, bins=min(40, max(5, v.size // 4)), color="C0", alpha=0.8)
                ax.axvline(r.nominal, color="k", lw=1, label="nominal")
                ax.legend(fontsize=7)
            ax.set_xlabel(r.criterion, fontsize=8)
            ax.set_ylabel("trials", fontsize=8)
            ax.set_title("Monte Carlo", fontsize=9)
            has_worst = r.worst is not None
        ax.tick_params(labelsize=7)
        return {"text": text, "png": _png(fig, dpr), "worst": has_worst}

    def load_worst_monte_carlo(self):
        s = getattr(self.mc_result, "worst", None)
        if s is None:
            return False
        self.doc.replace("Load worst Monte Carlo lens", s.copy())
        return True

    # ======================================================================== Insert / Inspect Lens
    def insert_preview(self, text, filename, opts):
        try:
            src = self.doc.load_text(text, filename)
        except Exception as e:  # noqa: BLE001
            return {"error": f"Cannot read {filename}: {e}"}
        n = src.image_index - 1
        out = {"n": max(1, n), "ok": src.image_index > 1, "image_index": self.doc.system.image_index}
        if not out["ok"]:
            out["preview"] = "This file has no surfaces between object and image."
            return out
        o = self._insert_opts(opts, n)
        try:
            trial = lf.OpticalSystem("preview", self.doc.system.units, self.doc.system.library)
            E.insert_lens(trial, src, 1, **o)
            group = lens_surfaces(src, o["first"], o["last"], 1.0, o["reverse"], o["keep_stop"])
        except Exception as e:  # noqa: BLE001
            out.update(ok=False, preview=f"Cannot insert: {e}")
            return out
        lines = trial.prescription().splitlines()
        out["preview"] = "\n".join(lines[:1] + lines[2:-1])
        info = f"{src.name or 'Lens'}: {len(group)} surface(s), {src.units}. "
        try:
            trial.set_aperture("EPD", 1.0)
            f = trial.paraxial().efl
            if math.isfinite(f) and abs(f) < 1e12:
                info += f"Focal length of the inserted group: {f:.6g} {self.doc.system.units}."
        except Exception:  # noqa: BLE001
            pass
        out["info"] = info
        return out

    @staticmethod
    def _insert_opts(opts, n):
        first = max(1, min(int(opts.get("first", 1)), max(1, n)))
        last = max(first, min(int(opts.get("last", n)), max(1, n)))
        return dict(first=first, last=last, scale=float(opts.get("scale", 1.0)),
                    reverse=bool(opts.get("reverse")), keep_stop=bool(opts.get("keep_stop")),
                    convert_units=bool(opts.get("convert_units", True)),
                    copy_semi_diameters=bool(opts.get("copy_semi_diameters")))

    def insert_lens(self, text, filename, at, opts):
        src = self.doc.load_text(text, filename)
        o = self._insert_opts(opts, src.image_index - 1)
        name = os.path.basename(filename or "lens")
        return self._modify(f"Insert lens {name}", lambda s: E.insert_lens(s, src, int(at), **o))

    def inspect(self, text, filename):
        try:
            s = self.doc.load_text(text, filename)
        except Exception as e:  # noqa: BLE001
            return {"error": f"Cannot read {filename}: {type(e).__name__}: {e}"}
        info = f"{s.name or 'Lens'}: {s.num_surfaces} surfaces, {s.units}"
        missing = s.missing_materials_message()
        if missing:
            return {"info": info, "report": f"This lens cannot be traced.\n{missing}"}
        try:
            report = lf.system_report(s)
        except Exception as e:  # noqa: BLE001
            report = f"The system report failed:\n{type(e).__name__}: {e}"
        return {"info": info, "report": report}

    # ======================================================================== Non-Sequential Editor
    def ns_state(self):
        sc = self.ns_scene
        objs = []
        for o in sc.objects:
            vals = [NT.OBJECT_LABELS.get(o.kind, o.kind), o.comment] + [NT._fmt(getattr(o, k)) for k in NT.POSE] + [
                NT._fmt(o.material or "") if not o.is_detector else "",
                "" if o.coating is None else NT._fmt(o.coating),
                ", ".join(f"{n}={NT._fmt(getattr(o, n))}" for n, _ in o.params)]
            objs.append({"cells": vals, "tip": "; ".join(f"{n}: {lab}" for n, lab in o.params),
                         "detector": bool(o.is_detector)})
        srcs = []
        for s in sc.sources:
            vals = [NT.SOURCE_LABELS.get(s.kind, s.kind), s.comment] + [NT._fmt(getattr(s, k)) for k in NT.POSE] + [
                str(s.n_rays), NT._fmt(s.power), ", ".join(NT._fmt(w) for w in s.wavelengths), s.sampling,
                ", ".join(f"{n}={NT._fmt(getattr(s, n))}" for n, _ in s.params)]
            srcs.append({"cells": vals, "tip": "; ".join(f"{n}: {lab}" for n, lab in s.params)})
        return {"name": sc.name or "Scene", "objects": objs, "sources": srcs, "obj_cols": NT.OBJ_COLS,
                "src_cols": NT.SRC_COLS, "object_types": [[k, v] for k, v in NT.OBJECT_LABELS.items()],
                "source_types": [[k, v] for k, v in NT.SOURCE_LABELS.items()],
                "detectors": [[k, f"{k + 1}: {o.comment or 'detector'}"] for k, o in enumerate(sc.objects)
                              if o.is_detector],
                "buttons": [[k, t, tip, ns_svg(k)] for k, (t, tip) in NT.BUTTONS.items()],
                "traced": self.ns_result is not None, "summary": self.ns_result.summary() if self.ns_result else ""}

    def ns_set_cell(self, table, r, c, text):
        is_obj = table == "objects"
        target = (self.ns_scene.objects if is_obj else self.ns_scene.sources)[r]
        NT.apply_cell(target, c, str(text), is_obj)
        return True

    def ns_add(self, kind, after=-1):
        if kind in lf.nonseq.OBJECT_TYPES:
            at = len(self.ns_scene.objects) if after < 0 else after + 1
            self.ns_scene.objects.insert(at, lf.nonseq.OBJECT_TYPES[kind]())
            return {"table": "objects", "row": at}
        self.ns_scene.sources.append(lf.nonseq.SOURCE_TYPES[kind](z=-10.0))
        return {"table": "sources", "row": len(self.ns_scene.sources) - 1}

    def ns_delete(self, table, r):
        items = self.ns_scene.objects if table == "objects" else self.ns_scene.sources
        if 0 <= r < len(items):
            del items[r]
        return True

    def ns_new(self):
        self.ns_scene, self.ns_result, self.ns_path = lf.nonseq.NonSequentialSystem("Scene"), None, None
        return True

    def ns_from_lens(self):
        try:
            scene = lf.nonseq.from_sequential(self.doc.system, n_rays=1000, sampling="random")
        except Exception as e:  # noqa: BLE001
            raise ValueError(f"This lens cannot be converted: {e}") from e
        self.ns_scene, self.ns_result = scene, None
        return True

    def ns_open(self, text, filename):
        tmp = "/tmp/lensforge_web_scene.ns.json"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
        self.ns_scene, self.ns_result, self.ns_path = lf.nonseq.load(tmp), None, filename
        return True

    def ns_text(self):
        tmp = "/tmp/lensforge_web_scene_out.ns.json"
        lf.nonseq.save(self.ns_scene, tmp)
        with open(tmp, encoding="utf-8") as f:
            return f.read()

    def ns_trace(self, split=True, fresnel=True, min_relative_intensity=1e-5, max_segments=100):
        scene = self.ns_scene.copy()
        miss = scene.missing_materials()
        if miss:
            return {"summary": "Cannot trace: " + "; ".join(
                f"{m} (objects {', '.join(str(k + 1) for k in rows)})" for m, rows in miss.items())
                + " not in any loaded glass catalog.", "traced": False}
        if not scene.sources:
            return {"summary": "Add a source first (Add Source on the toolbar).", "traced": False}
        self.ns_result = lf.nonseq.trace(scene, split=bool(split), fresnel=bool(fresnel),
                                         min_relative_intensity=float(min_relative_intensity),
                                         max_segments=int(max_segments))
        return {"summary": self.ns_result.summary(), "traced": True}

    def ns_plot(self, detector=None, rays="all", log=True, plane="y", width=900, height=380, dpr=1.0):
        import lensforge.plot as P
        r = self.ns_result
        if r is None:
            return None
        fig = _figure(width, height)
        ax1 = fig.add_subplot(1, 2, 1)
        P.ns_layout(r, ax1, plane=plane)
        if r.detectors and detector is not None:
            ax2 = fig.add_subplot(1, 2, 2)
            try:
                P.ns_detector(r, int(detector), ax2, rays=rays, log=bool(log))
            except KeyError:  # detector added after the trace
                ax2.set_title("Trace again to see this detector")
        return _png(fig, dpr)


# ============================================================================ dispatch
SESSION = None
#: methods that never change the lens (the page skips redrawing the editors after them)
READ_ONLY = {"state", "menus", "help_data", "about", "samples", "lens_text", "suggested_name", "lens_info",
             "session_dump", "prescription", "describe_deletion", "context_menu", "can_vary", "solve_form",
             "surface_properties", "material_search", "catalog_rows", "material_dialog", "material_preview",
             "squash", "system_settings", "input_rays", "pupil_pattern", "analysis_specs", "run_analysis",
             "mfe_evaluate", "operands", "operand_names", "wizard_info", "script_example", "opt_info",
             "history_plot", "tolerance_setup", "default_tolerances", "insert_preview", "inspect", "ns_state",
             "ns_text", "ns_plot"}


def session() -> Session:
    global SESSION
    if SESSION is None:
        SESSION = Session()
    return SESSION


def dispatch(method: str, args_json: str = "{}", s: Session = None) -> str:
    """Call ``Session.<method>(**args)`` (on the page's session unless ``s`` is given); returns JSON
    {"result", "state"?, "error"?, "error_type"?}."""
    s = s or session()
    args = json.loads(args_json or "{}")
    if method.startswith("_") or not hasattr(s, method):
        return json.dumps({"error": f"unknown method {method}"})
    rev = s.doc.revision
    out = {}
    try:
        out["result"] = getattr(s, method)(**args)
    except StopRequested:
        out["error"] = "Stopped"
    except Exception as e:  # noqa: BLE001 - shown in the page's status bar
        if os.environ.get("LENSFORGE_WEB_DEBUG"):
            traceback.print_exc()
        out["error"] = str(e) or type(e).__name__
        out["error_type"] = type(e).__name__
    if s.doc.revision != rev or (method not in READ_ONLY and "error" not in out):
        out["state"] = s.state()
    return json.dumps(_clean(out), default=_json_default)


def _clean(o):
    """NaN and infinity become null (JSON has neither)."""
    if isinstance(o, float):
        return o if math.isfinite(o) else None
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    return o


def _json_default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return _num(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, (set, tuple)):
        return list(o)
    return str(o)
