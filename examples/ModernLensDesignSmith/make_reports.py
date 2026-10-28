"""Write report.html in each chapter folder: how closely each model matches the book.

The book values are read from each model's notes, so the report always reflects
the files as committed.  Run from the repository root:

    python examples/ModernLensDesignSmith/make_reports.py
"""
import datetime
import glob
import html
import math
import os
import re
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", ".."))
import lensforge as lf  # noqa: E402

# (key, label, digits shown) in table order
QUANTITIES = [
    ("EFL", "EFL", 2),
    ("BFL", "BFL", 2),
    ("NA", "NA", 4),
    ("GIH", "GIH", 2),
    ("VL", "VL", 2),
    ("PTZF", "PTZ/F", 3),
]
FIRST_ORDER = ("EFL", "BFL", "GIH", "VL")
GRADES = ("exact", "close", "off")
GRADE_TEXT = {"exact": "Exact", "close": "Close", "off": "Off"}


def figure_key(path):
    return tuple(int(x) for x in re.search(r"Figure (\d+)\.(\d+)", path).groups())


def book_values(notes):
    """Book values and their printed precision (one unit of the last digit)."""
    out = {}
    for key, pat in [("EFL", r"EFL (-?[\d.]+)"), ("BFL", r"BFL (-?[\d.]+)"), ("NA", r"NA (-?[\d.]+)"),
                     ("GIH", r"GIH (-?[\d.]+)"), ("PTZF", r"PTZ/F (-?[\d.]+)"), ("VL", r"VL (-?[\d.]+)")]:
        m = re.search(pat, notes)
        if m:
            s = m.group(1)
            unit = 10.0 ** -len(s.split(".")[1]) if "." in s else 1.0
            out[key] = (float(s), unit)
    m = re.search(r"Figure ([\d.]+), p\. (\d+)", notes)
    out["page"] = m.group(2) if m else ""
    m = re.search(r"\(F/([\d.]+)\)", notes)
    out["F"] = m.group(1) if m else ""
    return out


def petzval_ratio(lens, efl):
    """Petzval radius over EFL, -1/(EFL * sum c (n' - n)/(n n')), with d-line indices."""
    lib = lf.shared_library()
    total, n0 = 0.0, 1.0
    for s in lens.surfaces[1:-1]:
        n1 = lib.resolve(s.material).nd if s.material else 1.0
        total += s.curvature * (n1 - n0) / (n0 * n1)
        n0 = n1
    return -1.0 / total / efl


def full_field_transmission(lens, wavelength):
    g = np.linspace(-1, 1, 21)
    X, Y = np.meshgrid(g, g)
    m = X ** 2 + Y ** 2 <= 1
    hy = 1.0
    r = lens.trace(0.0, hy, X[m], Y[m], wavelength=wavelength)
    return np.count_nonzero(r.valid) / r.valid.size


def axial_ok(lens):
    g = np.linspace(-1, 1, 11)
    X, Y = np.meshgrid(g, g)
    m = X ** 2 + Y ** 2 <= 1
    for w in lens.wavelengths:
        if not lens.trace(0.0, 0.0, X[m], Y[m], wavelength=w.value).valid.all():
            return False
        for hy in (0.7, 1.0):
            if not lens.trace(0.0, hy, np.zeros(1), np.zeros(1), wavelength=w.value).valid.all():
                return False
    return True


def grade(book, unit, model):
    """exact: within the book's printed precision (one unit of the last digit, 0.05 %, or 0.001);
    close: within 0.5 % (or 0.01); off: anything larger."""
    diff = abs(model - book)
    if diff <= max(unit * 1.0001, 0.0005 * abs(book), 0.001):
        return "exact"
    if diff <= max(0.005 * abs(book), 0.01):
        return "close"
    return "off"


def analyse(path):
    lens = lf.load(path)
    book = book_values(lens.notes)
    w0 = lens.wavelengths[lens.primary_wavelength].value
    p = lens.paraxial()
    surfs = lens.surfaces
    model = {
        "EFL": p.efl,
        "BFL": p.image_distance,
        "NA": -1.0 / (2.0 * p.working_fnum),
        "GIH": p.paraxial_image_height,
        "VL": sum(s.thickness for s in surfs[1:-2]),
        "PTZF": petzval_ratio(lens, p.efl),
    }
    rows = {}
    for key, _, _ in QUANTITIES:
        if key in book:
            b, unit = book[key]
            rows[key] = (b, model[key], model[key] - b, grade(b, unit, model[key]))
    # a model's notes can flag a book GIH that is not a paraxial value (e.g. Fig. 9.17); it is then not graded
    ungraded = {"GIH"} if re.search(r"book's GIH [\d.]+ is not the paraxial", lens.notes) else set()
    first = [rows[k][3] for k in FIRST_ORDER if k in rows and k not in ungraded]
    overall = max(first, key=GRADES.index) if first else "off"
    glass = re.search(r"Glass: (.*?\.)(?: [A-Z]|$)", lens.notes)
    return {
        "fig": "%d.%d" % figure_key(path),
        "file": os.path.basename(path),
        "name": re.sub(r"\s*\(Smith, Modern Lens Design, Fig\. [\d.]+\)", "", lens.name),
        "page": book["page"],
        "fnum": book["F"],
        "hfov": max(abs(f.y) for f in lens.fields),
        "nsurf": len(surfs) - 2,
        "rows": rows,
        "overall": overall,
        "trace_ok": axial_ok(lens),
        "transmission": full_field_transmission(lens, w0),
        "glass": glass.group(1).rstrip(".") if glass else "",
        "ungraded": ungraded,
    }


CSS = """
:root{--bg:#fbfaf7;--fg:#1d1d1b;--muted:#6b6a65;--line:#e3e1da;--card:#ffffff;
--exact:#1f7a4a;--exact-bg:#e3f3ea;--close:#8a5a00;--close-bg:#fbf0d6;--off:#a8322d;--off-bg:#f8e1df;--accent:#2f5d8a}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#17181a;--fg:#e8e6e1;--muted:#9b9a94;
--line:#2e3034;--card:#1f2124;--exact:#6fcf97;--exact-bg:#17331f;--close:#e8c06a;--close-bg:#3a2f12;--off:#f08a80;
--off-bg:#3d1c1a;--accent:#8ab4e0}}
:root[data-theme="dark"]{--bg:#17181a;--fg:#e8e6e1;--muted:#9b9a94;--line:#2e3034;--card:#1f2124;--exact:#6fcf97;
--exact-bg:#17331f;--close:#e8c06a;--close-bg:#3a2f12;--off:#f08a80;--off-bg:#3d1c1a;--accent:#8ab4e0}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
main{max-width:1180px;margin:0 auto;padding:32px 16px 64px}
h1{font-size:26px;margin:0 0 4px}
h2{font-size:18px;margin:36px 0 10px}
.sub{color:var(--muted);margin:0 0 24px}
.tiles{display:flex;gap:12px;flex-wrap:wrap;margin:0 0 8px}
.tile{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 16px;min-width:130px}
.tile b{display:block;font-size:24px;font-variant-numeric:tabular-nums}
.tile span{color:var(--muted);font-size:13px}
.wrap{overflow-x:auto;border:1px solid var(--line);border-radius:10px;background:var(--card)}
table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}
th,td{padding:7px 10px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap;vertical-align:top}
th{font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);font-weight:600;background:var(--card);position:sticky;top:0}
th.l,td.l{text-align:left}
tr:last-child td{border-bottom:0}
td.name{white-space:normal;min-width:220px;max-width:320px}
td.name small{color:var(--muted);display:block}
.q{display:block}
.q i{font-style:normal;color:var(--muted);font-size:12px;display:block}
.exact{background:var(--exact-bg)} .close{background:var(--close-bg)} .off{background:var(--off-bg)}
.badge{display:inline-block;padding:1px 8px;border-radius:999px;font-size:12px;font-weight:600}
.badge.exact{color:var(--exact)} .badge.close{color:var(--close)} .badge.off{color:var(--off)}
td.exact i,td.close i,td.off i{color:inherit;opacity:.75}
ul{padding-left:20px} li{margin:4px 0}
code{font-size:13px}
.notes{color:var(--muted);font-size:14px}
"""


def fmt(v, d):
    return f"{v:.{d}f}"


def render(chapter, results):
    counts = {g: sum(r["overall"] == g for r in results) for g in GRADES}
    out = [
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width,initial-scale=1'>",
        f"<title>{html.escape(chapter)} match report</title><style>{CSS}</style></head><body><main>",
        f"<h1>{html.escape(chapter)}</h1>",
        "<p class='sub'>How closely each lensforge model reproduces the data printed in Warren J. Smith, "
        f"<i>Modern Lens Design</i>, 2nd ed. Generated {datetime.date.today().isoformat()} by "
        "<code>make_reports.py</code> from the committed <code>.lens.json</code> files.</p>",
        "<div class='tiles'>",
        f"<div class='tile'><b>{len(results)}</b><span>models</span></div>",
    ]
    for g in GRADES:
        out.append(f"<div class='tile'><b>{counts[g]}</b><span class='badge {g}'>{GRADE_TEXT[g]}</span></div>")
    out.append("</div>")

    out.append("<h2>Summary</h2><div class='wrap'><table><thead><tr><th class='l'>Figure</th><th class='l'>Lens</th>"
               "<th class='l'>Match</th>")
    for _, label, _ in QUANTITIES:
        out.append(f"<th>{label}<br>book / model</th>")
    out.append("<th>Rays</th><th class='l'>Glass substitutions</th></tr></thead><tbody>")
    for r in results:
        out.append(f"<tr><td class='l'><b>{r['fig']}</b></td>"
                   f"<td class='l name'>{html.escape(r['name'])}<small>p. {r['page'] or '?'} · F/{r['fnum']} · "
                   f"HFOV {r['hfov']:g}° · {r['nsurf']} surfaces</small></td>"
                   f"<td class='l'><span class='badge {r['overall']}'>{GRADE_TEXT[r['overall']]}</span></td>")
        for key, _, d in QUANTITIES:
            if key not in r["rows"]:
                out.append("<td>–</td>")
                continue
            b, m, diff, g = r["rows"][key]
            rel = f"{100 * diff / b:+.2f} %" if b else f"{diff:+.{d}f}"
            rel = rel.replace("-0.00 ", "+0.00 ")
            out.append(f"<td class='{g}'><span class='q'>{fmt(b, d)}<br>{fmt(m, d)}<i>{rel}</i></span></td>")
        rays = "all pass" if r["trace_ok"] else "<span class='badge off'>lost</span>"
        if r["transmission"] < 0.999:
            rays += f"<br><i class='notes'>{100 * (1 - r['transmission']):.0f}% vignetted<br>at full field</i>"
        out.append(f"<td>{rays}</td><td class='l name'>{html.escape(r['glass']) or '–'}</td></tr>")
    out.append("</tbody></table></div>")

    off = [r for r in results if r["overall"] != "exact"]
    ungraded = [r for r in results if r["ungraded"]]
    ptz = [r for r in results if "PTZF" in r["rows"] and r["rows"]["PTZF"][3] == "off"]
    out.append("<h2>Notes</h2><ul class='notes'>")
    out.append("<li><b>Match</b> is the worst grade among the first-order quantities EFL, BFL, GIH and VL. "
               "<span class='badge exact'>Exact</span> means within the precision the book prints (one unit of the "
               "last digit, or 0.05 % where the book's rounded field angle limits GIH), "
               "<span class='badge close'>Close</span> within 0.5 %, <span class='badge off'>Off</span> anything larger.</li>")
    out.append("<li>Model values are paraxial at the primary wavelength (d line). NA is 1/(2 × working F/#), "
               "GIH is the paraxial image height at the largest field, VL is the sum of all thicknesses except "
               "the last, and PTZ/F is −1/(EFL Σ c(n′−n)/(n n′)).</li>")
    out.append("<li>NA reflects the entrance pupil entered in the model rather than the prescription, so it "
               "is shown but not graded. Chapter 6 models use EPD = 100/F# from the book's rounded F/#, which "
               "puts NA a few tenths of a percent from the book's value; later chapters use EPD = 2 EFL |NA|, "
               "or for a finite object the EPD that gives the book's working NA.</li>")
    out.append("<li>PTZ/F is shown for reference but not graded into Match. Where it differs by a few percent "
               "while EFL, BFL and VL agree, the difference is most likely in how the book's software defines "
               "it rather than in the prescription.</li>")
    out.append("<li><b>Rays</b>: a full axial beam and the chief rays at 0.7 and 1.0 field are traced at every "
               "wavelength. Vignetting at full field is reported when the book's semi-apertures clip the beam. "
               "Models with a half field of 60° or more use real ray aiming.</li>")
    if off:
        out.append("<li>Models not graded Exact: " + ", ".join(
            f"Fig {r['fig']} ({', '.join(k for k in FIRST_ORDER if k in r['rows'] and r['rows'][k][3] != 'exact' and k not in r['ungraded'])})"
            for r in off) + ". These use glasses entered from the book's rounded nd/Vd or a modern substitute "
            "with slightly different dispersion (see the glass column).</li>")
    if ungraded:
        out.append("<li>The book's GIH is not the paraxial image height on Fig " + ", ".join(r["fig"] for r in ungraded)
                   + ", so it is shown but not graded into Match (see the notes in the model file).</li>")
    if ptz:
        out.append("<li>PTZ/F differs by more than 0.5 % on Fig " + ", ".join(r["fig"] for r in ptz) + ".</li>")
    out.append("</ul></main></body></html>\n")
    return "".join(out)


def main():
    for chapter_dir in sorted(glob.glob(os.path.join(HERE, "Chapter *"))):
        files = sorted(glob.glob(os.path.join(chapter_dir, "Figure *.lens.json")), key=figure_key)
        if not files:
            continue
        results = [analyse(f) for f in files]
        path = os.path.join(chapter_dir, "report.html")
        with open(path, "w") as fh:
            fh.write(render(os.path.basename(chapter_dir), results))
        print(f"{path}: " + ", ".join(f"{sum(r['overall'] == g for r in results)} {g}" for g in GRADES))


if __name__ == "__main__":
    main()
