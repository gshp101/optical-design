"""Build one multi-configuration lens per Chapter 20 zoom lens from its per-position files.

For each figure, "Figure 20.N zoom.lens.json" holds every zoom position the book lists (short, mid, long and,
for Fig. 20.5, macro) as configurations of one lens; the per-position files stay as they are. The
multi-configuration table gets one row for each parameter that differs between the positions (the moving air
spaces, the aperture, the field angles, the object distance of the macro setting ...). The variables of the
position files are kept, except that a lens variable on a parameter the table now sets (the back focus) becomes
one variable cell per configuration. The merit function is the default RMS spot merit for all configurations,
each group headed by a CONF row and an EFFL row (weight 0) showing that position's focal length against the
book's.

The notes keep the book's values for each position in the form "[short] Figure 20.1 short, p. 376. Book: EFL
100, BFL 149.7, ..." so tests/test_smith_examples.py and make_reports.py can check every configuration.

Run from anywhere: python examples/ModernLensDesignSmith/make_zoom_multiconfig.py
"""

import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", ".."))
import lensforge as lf  # noqa: E402
from lensforge import optimize as opt  # noqa: E402

ZOOM = os.path.join(HERE, "Chapter 20 - Zoom Lenses")
POSITIONS = ("short", "mid", "long", "macro")

_SURFACE_OPERAND = {"thickness": "THIC", "curvature": "CRVT", "conic": "CONN", "material": "GLSS",
                    "semi_diameter": "SDIA"}
_FIELD_OPERAND = {"x": "XFIE", "y": "YFIE", "weight": "FLWT", "vdx": "FVDX", "vdy": "FVDY", "vcx": "FVCX",
                  "vcy": "FVCY"}


def position_files(fig):
    out = []
    for pos in POSITIONS:
        p = os.path.join(ZOOM, f"Figure {fig} {pos}.lens.json")
        if os.path.exists(p):
            out.append((pos, p))
    return out


def differences(dicts):
    """(operand, ref, param, values) for every parameter that differs between the position files."""
    rows = []

    def differ(vals):
        return len({json.dumps(v, sort_keys=True) for v in vals}) > 1

    if differ([d["aperture"]["type"] for d in dicts]) or differ([d["fields"]["type"] for d in dicts]):
        raise ValueError("aperture or field type differs between positions")
    if differ([d["aperture"]["value"] for d in dicts]):
        rows.append(("APER", None, None, [d["aperture"]["value"] for d in dicts]))
    for i in range(len(dicts[0]["fields"]["values"])):
        for key, op in _FIELD_OPERAND.items():
            vals = [d["fields"]["values"][i][key] for d in dicts]
            if differ(vals):
                rows.append((op, i, None, vals))
    for i in range(len(dicts[0]["wavelengths"]["values"])):
        vals = [d["wavelengths"]["values"][i]["value"] for d in dicts]
        if differ(vals):
            rows.append(("WAVE", i, None, vals))
    for i in range(len(dicts[0]["surfaces"])):
        surfs = [d["surfaces"][i] for d in dicts]
        if differ([s["type"] for s in surfs]) or differ([s.get("stop", False) for s in surfs]):
            raise ValueError(f"surface {i}: type or stop differs between positions")
        for key in sorted(set().union(*surfs)):
            vals = [s.get(key) for s in surfs]
            if not differ(vals):
                continue
            if key == "radius":
                key, vals = "curvature", [0.0 if v in (None, "inf", "-inf") else 1.0 / v for v in vals]
            op = _SURFACE_OPERAND.get(key, "PARM")
            vals = [float("inf") if v == "inf" else v for v in vals]
            rows.append((op, i, key if op == "PARM" else None, vals))
    return rows


def book_segment(notes):
    """The page and 'Book: ...' sentence of a position file's notes."""
    page = re.search(r"Figure [\d.]+ \w+, p\. (\d+)", notes)
    book = re.search(r"Book: (.*?\.)(?= [A-Z])", notes)
    return page.group(1) if page else "", book.group(1)


def common_notes(notes, fig, names, ops):
    """The first position's notes without its figure/page/book sentences, the old 'one file per position'
    sentence replaced by one describing the multi-configuration table."""
    body = re.sub(r"^.*?Book: .*?\.(?= [A-Z])\s*", "", notes)
    zoom = (f"Zoom lens: the configurations are the zoom positions the book lists ({', '.join(names)}); "
            f"the per-position files Figure {fig} {'/'.join(names)}.lens.json hold the same data one position "
            f"per file. The multi-configuration table sets {', '.join(ops)}.")
    body, n = re.subn(r"Zoom lens: lensforge has no multi-configuration support, so each zoom position the "
                      r"book lists is a separate file \([^)]*\)\.", zoom, body)
    if n != 1:
        raise ValueError(f"Figure {fig}: zoom sentence not found")
    # the table says exactly what changes, so the position files' summary of it goes
    body = re.sub(r" Between positions only [^.]*\.", "", body)
    # Fig. 20.6 explains its folded dummy surfaces with the numbers of one position
    body = re.sub(r"(folded into the air space after surface 9: [-\d. ]+= [\d.]+\.)",
                  r"\1 (These are the numbers of the short position; the mid and long positions are folded the "
                  "same way.)", body)
    return body


def build(fig):
    files = position_files(fig)
    names = [pos for pos, _ in files]
    dicts = []
    for _, p in files:
        with open(p) as fh:
            dicts.append(json.load(fh))
    lens = lf.load(files[0][1])
    lens.name = re.sub(r",? (short EFL|short)(?= \()", "", lens.name).replace(f"Fig. {fig} short", f"Fig. {fig} zoom")
    mc = lf.MultiConfig.create(lens, len(files), names)
    rows = differences(dicts)
    for op, ref, param, vals in rows:
        mc.add_row(lens, op, ref, param, values=vals)

    # the back focus (and anything else the table now sets) is varied per configuration
    keep = opt.VariableSet()
    for v in opt.variables(lens):
        if mc.controls(v.surface, v.param):
            row = next(i for i, r in enumerate(mc.rows) if r.controls(v.surface, v.param))
            keep.extend(opt.MCVariable(row, k) for k in mc.configs)
        else:
            keep.append(v)
    lens.variables = keep

    segs = []
    for name, d in zip(names, dicts):
        page, book = book_segment(d["notes"])
        segs.append(f"[{name}] Figure {fig} {name}, p. {page}. Book: {book}")
    ops = [r.label for r in mc.rows]
    page0 = book_segment(dicts[0]["notes"])[0]
    lens.notes = (f"Warren J. Smith, Modern Lens Design, 2nd ed., Figure {fig} (zoom), p. {page0}. "
                  f"Multi-configuration model: configuration {', '.join(f'{k} = {n}' for k, n in zip(mc.configs, names))}. "
                  f"Book values by configuration: {' '.join(segs)} [end] "
                  + common_notes(dicts[0]["notes"], fig, names, ops))

    mf = opt.default_merit(lens)
    for k, name, d in zip(reversed(list(mc.configs)), reversed(names), reversed(dicts)):
        at = next(i for i, r in enumerate(mf.rows) if r.type == "CONF" and r.params["cfg"] == k)
        efl = float(re.search(r"EFL (-?[\d.]+)", book_segment(d["notes"])[1]).group(1))
        mf.insert(at + 1, "EFFL", efl, 0, comment=f"book EFL, {name}")
    lens.merit_function = mf
    lens.set_config(1)
    out = os.path.join(ZOOM, f"Figure {fig} zoom.lens.json")
    lf.save(lens, out)
    return out, mc


def main():
    figs = sorted({re.search(r"Figure (20\.\d+) ", p).group(1)
                   for p in glob.glob(os.path.join(ZOOM, "Figure 20.* short.lens.json"))},
                  key=lambda f: int(f.split(".")[1]))
    for fig in figs:
        out, mc = build(fig)
        print(f"{os.path.basename(out)}: {mc.n_configs} configurations, operands {', '.join(r.label for r in mc.rows)}")


if __name__ == "__main__":
    main()
