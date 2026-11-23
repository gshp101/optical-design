import base64, html, json, math, os, re, sys
from collections import OrderedDict

"""Write the HTML validation report from the JSON files that run.py collects.

Usage: python make_report.py DATA_DIR OUTPUT.html   (normally called by run.py)
"""
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from catalog import SECTIONS

REPO = os.path.dirname(os.path.dirname(HERE))
DATA = sys.argv[1]


def _load(name):
    with open(os.path.join(DATA, name)) as fh:
        return json.load(fh)


cap = _load("capture.json")
REC, OUT = cap["records"], cap["outcomes"]
MANUAL = _load("manual.json")
SMITH = _load("smith.json")
GLASS = _load("glass.json")
META = _load("meta.json")

esc = html.escape


def fmt(x):
    if x == 0:
        return "0"
    if not math.isfinite(x):
        return str(x)
    a = abs(x)
    if 1e-3 <= a < 1e4:
        return f"{x:.4g}"
    m, e = f"{x:.1e}".split("e")
    return f"{m}×10<sup>{int(e)}</sup>"


def cases(file, func):
    pre = f"{file}::{func}"
    ids = [n for n in OUT if n == pre or n.startswith(pre + "[")]
    return ids


def ratio(r):
    if r["tol"] > 0:
        return r["err"] / r["tol"]
    return math.inf if r["err"] > 0 else 0.0


def measure(e):
    ids = cases(e["file"], e["func"])
    outcomes = [OUT[i]["outcome"] for i in ids]
    recs = []
    for i in ids:
        rs = REC.get(i, [])
        if e.get("pick"):
            rs = [rs[k] for k in e["pick"] if k < len(rs)]
        recs += rs
    return ids, outcomes, recs


def measured_html(e, recs):
    unit = e.get("unit", "")
    u = f" {unit}" if unit else ""
    if e["func"] in MANUAL:
        v = MANUAL[e["func"]]
        return ("max |Δ| = " + fmt(v) + u + " (exact to machine precision)", 0.0)
    if not recs:
        return ("Exact: the flag or sign check passed", None)
    w = max(recs, key=ratio)
    rr = ratio(w)
    s = f"worst |Δ| = {fmt(w['err'])}{u} against an allowed {fmt(w['tol'])}"
    exp = w.get("expected")
    if "relative" in e["tol"] and exp is not None and isinstance(exp, float) and math.isfinite(exp) and abs(exp) > 0 and w["err"] > 0:
        s += f" (relative {fmt(w['err'] / abs(exp))})"
    s += f"; {len(recs)} comparison{'s' if len(recs) != 1 else ''}"
    return (s, rr)


def bar(rr):
    if rr is None:
        return '<span class="muted">n/a</span>'
    pct = 100 * rr
    w = max(1.5, min(100, pct)) if pct > 0 else 0
    label = "&lt;0.01 %" if 0 < pct < 0.01 else ("0 %" if pct == 0 else f"{pct:.2g} %")
    cls = "hi" if pct >= 50 else ("mid" if pct >= 10 else "lo")
    return f'<div class="bar"><span class="{cls}" style="width:{w:.1f}%"></span></div><span class="pct">{label}</span>'


# ------------------------------------------------------------------------- build sections
sec_html, toc, summary_rows = [], [], []
tot_funcs = tot_cases = tot_pass = 0
for key, title, intro, entries in SECTIONS:
    rows = []
    s_cases = s_pass = 0
    worst = 0.0
    for e in entries:
        ids, outcomes, recs = measure(e)
        assert ids, (e["file"], e["func"])
        npass = sum(o == "passed" for o in outcomes)
        s_cases += len(ids)
        s_pass += npass
        meas, rr = measured_html(e, recs)
        if rr is not None:
            worst = max(worst, rr)
        status = "Pass" if npass == len(ids) else f"{len(ids) - npass} failed"
        ncase = f'<div class="muted small">{len(ids)} cases</div>' if len(ids) > 1 else ""
        note = f'<div class="note">{esc(e["note"])}</div>' if e.get("note") else ""
        rows.append(f"""<tr>
<td><div class="tname">{esc(e['title'])}</div><code class="small fn">{esc(e['func'])}</code><div class="muted small">{esc(os.path.basename(e['file']))}</div>{ncase}</td>
<td>{esc(e['checks'])}</td>
<td>{esc(e['ref'])}</td>
<td class="tol">{esc(e['tol'])}</td>
<td>{meas}{note}</td>
<td class="margin">{bar(rr)}</td>
<td><span class="pill {'ok' if status == 'Pass' else 'bad'}">{status}</span></td>
</tr>""")
    tot_funcs += len(entries)
    tot_cases += s_cases
    tot_pass += s_pass
    toc.append(f'<a href="#{key}">{esc(title)}</a>')
    summary_rows.append(f'<tr><td><a href="#{key}">{esc(title)}</a></td><td class="num">{len(entries)}</td>'
                        f'<td class="num">{s_cases}</td><td class="num">{s_pass}</td><td class="margin">{bar(worst)}</td></tr>')
    sec_html.append(f"""<section id="{key}"><h2>{esc(title)}</h2>{f'<p class="intro">{intro}</p>' if intro else ''}
<div class="tablewrap"><table class="tests"><thead><tr><th>Test</th><th>What it checks</th><th>Truth (reference)</th>
<th>Tolerance</th><th>How LensForge did</th><th>Share of tolerance used</th><th>Result</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></div></section>""")

# ------------------------------------------------------------------------- Smith group
ok = [r for r in SMITH if not r.get("skipped")]
skipped = [r["name"] for r in SMITH if r.get("skipped")]
smith_ids = cases("tests/test_smith_examples.py", "test_matches_book")
smith_pass = sum(OUT[i]["outcome"] == "passed" for i in smith_ids)


def pct(vals, q):
    v = sorted(vals)
    k = (len(v) - 1) * q / 100
    f = math.floor(k)
    c = min(f + 1, len(v) - 1)
    return v[f] + (v[c] - v[f]) * (k - f)


de = [abs(r["de"]) for r in ok]
db = [abs(r["db"]) for r in ok]
rel = [abs(r["de"]) / abs(r["efl"]) for r in ok]
dist_rows = "".join(
    f"<tr><td>{lab}</td><td class='num'>{pct(de, q):.4f}</td><td class='num'>{pct(db, q):.4f}</td><td class='num'>{fmt(pct(rel, q))}</td></tr>"
    for lab, q in (("Median", 50), ("90th percentile", 90), ("99th percentile", 99), ("Largest", 100)))
wide_reasons = {
    "Figure 16.21": "mirrors not exactly afocal; image 0.33 short of the ideal-lens focus",
    "Figure 20.3 long": "the zoom tables give an EFL about 0.1 % longer than the book in every position",
    "Figure 21.7": "catalog silicon, 0.004 below the book’s index",
    "Figure 21.12": "nearly afocal IR telescope: EFL/BFL behind the ideal lens follow the 4th decimal of the germanium index",
    "Figure 21.13": "as Figure 21.12",
    "Figure 21.14": "as Figure 21.12",
    "Figure 22.5": "allowance widened in the test; no reason recorded there",
}
seen = set()
wide_rows = ""
for r in ok:
    if (r["etol"] > 0.15 or r["btol"] > 0.15) and r["name"] not in seen and r["efl"] < 4000:
        seen.add(r["name"])
        wide_rows += (f"<tr><td>{esc(r['name'])}</td><td class='num'>{r['de']:+.3f} / ±{r['etol']:g}</td>"
                      f"<td class='num'>{r['db']:+.3f} / ±{r['btol']:g}</td><td>{esc(wide_reasons.get(r['name'], ''))}</td></tr>")
for r in ok:
    if r["name"] == "Figure 16.21" and r["name"] not in seen:
        seen.add(r["name"])
        wide_rows += (f"<tr><td>{esc(r['name'])}</td><td class='num'>{r['de']:+.3f} / ±{r['etol']:g}</td>"
                      f"<td class='num'>{r['db']:+.3f} / ±{r['btol']:g}</td><td>{esc(wide_reasons[r['name']])}</td></tr>")
mismatch = {
    "Figure 13.14": "the table gives the last surface as plane; a radius near −340 would reproduce the book’s EFL",
    "Figure 15.2": "the book’s EFL 151.5 is n′f with n′ = 1.515, but the table’s image medium is K5 (1.522)",
    "Figure 16.17": "the table as printed gives EFL −120.8 instead of 95.79",
    "Figure 22.14": "the table as printed gives EFL 73.5 and image distance 113.7 instead of 100 and 154.7",
}
mm_rows = "".join(f"<tr><td>{esc(k)}</td><td>{esc(v)}</td></tr>" for k, v in mismatch.items())
n01 = sum(x <= 0.01 for x in de)
n05 = sum(x <= 0.05 for x in de)
b01 = sum(x <= 0.01 for x in db)
b05 = sum(x <= 0.05 for x in db)
smith_html = f"""<section id="smith"><h2>Group: Smith, <i>Modern Lens Design</i> prescriptions</h2>
<p class="intro"><code class="small">test_smith_examples.py::test_matches_book</code> loads each of the {len(smith_ids)} lens files transcribed from Warren Smith’s
<i>Modern Lens Design</i> (2nd ed.), one per figure, and compares LensForge’s paraxial EFL and back focus against the values printed in the book. Each zoom file is checked
once per zoom position, which gives {len(SMITH)} configurations. It also checks that every axial ray at every wavelength passes, and that the chief ray passes at 0.7 and 1.0 field.</p>
<div class="tiles small-tiles">
<div class="tile"><div class="big">{smith_pass}/{len(smith_ids)}</div><div class="lab">lens files pass</div></div>
<div class="tile"><div class="big">{len(ok)}</div><div class="lab">configurations compared</div></div>
<div class="tile"><div class="big">{n05}</div><div class="lab">EFL within 0.05 mm of the book ({n01} within 0.01)</div></div>
<div class="tile"><div class="big">{b05}</div><div class="lab">BFL within 0.05 mm of the book ({b01} within 0.01)</div></div>
</div>
<p><b>Reference:</b> EFL and BFL printed in the book with each prescription. <b>Tolerance:</b> 0.15 mm (or 1e-4 of the EFL, whichever is larger), which allows for glasses entered from the book’s rounded n<sub>d</sub>/V<sub>d</sub>, plus a few documented exceptions below.</p>
<div class="two">
<div><h3>How close the paraxial data are</h3>
<div class="tablewrap"><table class="mini"><thead><tr><th></th><th>|ΔEFL| mm</th><th>|ΔBFL| mm</th><th>|ΔEFL| / EFL</th></tr></thead><tbody>{dist_rows}</tbody></table></div>
<p class="muted small">The largest differences are the nearly afocal infrared telescopes of Chapter 21, where the image distance behind the ideal lens swings by tens of mm with the 4th decimal of the germanium index.</p></div>
<div><h3>Configurations with a wider allowance (Δ / allowance, mm)</h3>
<div class="tablewrap"><table class="mini"><thead><tr><th>Figure</th><th>EFL</th><th>BFL</th><th>Why</th></tr></thead><tbody>{wide_rows}</tbody></table></div></div>
</div>
<h3>Figures whose printed table does not reproduce the book’s own EFL (paraxial check skipped, ray checks still run)</h3>
<div class="tablewrap"><table class="mini"><tbody>{mm_rows}</tbody></table></div>
</section>"""

# ------------------------------------------------------------------------- glass group
gl_ids = cases("tests/test_materials.py", "test_builtin_glasses_match_catalog")
gl_pass = sum(OUT[i]["outcome"] == "passed" for i in gl_ids)
order = ["SCHOTT", "OHARA", "HOYA", "CDGM", "SUMITA", "HIKARI", "CORNING", "MISC"]
grows = ""
for c in order:
    if c not in GLASS:
        continue
    g = GLASS[c]
    tn, tv = ("5e-5", "0.3") if c == "SUMITA" else ("2e-5", "0.05")
    grows += (f"<tr><td>{c}</td><td class='num'>{g['n']}</td><td class='num'>{fmt(g['med_dn'])}</td><td class='num'>{fmt(g['dn'])}</td>"
              f"<td class='num'>{tn}</td><td class='num'>{g['dv']:.3f}</td><td class='num'>{tv}</td></tr>")
ngl = sum(GLASS[c]["n"] for c in GLASS)
vend = cases("tests/test_materials.py", "test_vendor_catalog_glasses")
vend_pass = sum(OUT[i]["outcome"] == "passed" for i in vend)
mg = REC.get("tests/test_materials.py::test_model_glass_exact_nd_vd", [])
mg_w = max(mg, key=ratio) if mg else None
glass_html = f"""<section id="glass"><h2>Group: glass catalogs</h2>
<p class="intro"><code class="small">test_materials.py::test_builtin_glasses_match_catalog</code> runs once per catalog glass ({len(gl_ids)} cases, {gl_pass} pass).
It evaluates each glass’s dispersion formula at the d, F and C lines and compares the resulting n<sub>d</sub> and V<sub>d</sub> with the values printed in the maker’s catalog.
This checks both the dispersion coefficients and the dispersion formula code.</p>
<div class="tablewrap"><table class="mini"><thead><tr><th>Catalog</th><th>Glasses</th><th>median |Δn<sub>d</sub>|</th><th>max |Δn<sub>d</sub>|</th><th>allowed</th><th>max |ΔV<sub>d</sub>|</th><th>allowed</th></tr></thead><tbody>{grows}</tbody></table></div>
<p class="muted small">Sumita prints V<sub>d</sub> to 0.1 and its power-series fit leaves residuals of about 1e-5, which is why it has a wider allowance.</p>
<ul>
<li><b>Vendor spot checks</b> (<code class="small">test_vendor_catalog_glasses</code>, {len(vend)} cases, {vend_pass} pass): S-BSL7, S-LAH66, E-FD1, TAF1, H-K9L, H-ZF52, K-VC89 and J-LASF016 resolve to the right maker and match the published n<sub>d</sub> to 5e-5 and V<sub>d</sub> to 0.3.</li>
<li><b>Model glass</b> (<code class="small">test_model_glass_exact_nd_vd</code>): a “1.6,40” model glass gives n<sub>d</sub> = 1.6 and V<sub>d</sub> = 40{(' (worst |Δ| ' + fmt(mg_w['err']) + ')') if mg_w else ''}.</li>
<li><b>AGF loader</b> (<code class="small">test_agf_loader</code>): a Zemax AGF entry for N-BK7 reproduces n<sub>d</sub> 1.5168 to 1e-5.</li>
</ul></section>"""

# ------------------------------------------------------------------------- images


def img(path, alt):
    b = base64.b64encode(open(path, "rb").read()).decode()
    return f'<figure><img alt="{esc(alt)}" src="data:image/png;base64,{b}"><figcaption>{esc(alt)}</figcaption></figure>'


figs = (img(os.path.join(REPO, "docs/mtf-validation/analytic_defocus.png"),
            "FFT MTF of a perfect F/10 lens with 0, 0.25, 0.5 and 1 wave of defocus against Hopkins’ closed form.")
        + img(os.path.join(REPO, "docs/mtf-validation/cooke_vs_optiland.png"),
              "Cooke triplet FFT MTF, LensForge against Optiland 0.6.3, at 0°, 14° and 20°."))

n_groups = len(smith_ids) + len(gl_ids) + len(vend)
all_cases = tot_cases + n_groups
all_pass = tot_pass + smith_pass + gl_pass + vend_pass

page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>LensForge Validation Report</title>
<style>
:root {{ --bg:#fbfbf9; --panel:#ffffff; --ink:#1d1f23; --muted:#62666d; --line:#e3e3de; --accent:#2f5d9e; --ok:#1f7a4a; --okbg:#e5f3ea;
 --bad:#a1291f; --badbg:#f8e3e0; --lo:#4f8f6a; --mid:#c79a2a; --hi:#c0582f; --track:#ecece7; --code:#f2f2ee; }}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{ --bg:#15171a; --panel:#1d2024; --ink:#e7e7e3; --muted:#a0a4aa; --line:#30343a;
 --accent:#8db4ec; --ok:#7fd3a3; --okbg:#1c3428; --bad:#f19a8f; --badbg:#3b221f; --lo:#69b98a; --mid:#d9b24b; --hi:#e07a52; --track:#2b2f35; --code:#262a2f; }} }}
:root[data-theme="dark"] {{ --bg:#15171a; --panel:#1d2024; --ink:#e7e7e3; --muted:#a0a4aa; --line:#30343a;
 --accent:#8db4ec; --ok:#7fd3a3; --okbg:#1c3428; --bad:#f19a8f; --badbg:#3b221f; --lo:#69b98a; --mid:#d9b24b; --hi:#e07a52; --track:#2b2f35; --code:#262a2f; }}
* {{ box-sizing:border-box }}
body {{ margin:0; background:var(--bg); color:var(--ink); font:15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }}
main {{ max-width:1280px; margin:0 auto; padding:32px 16px 64px; }}
h1 {{ font-size:28px; margin:0 0 4px; letter-spacing:-0.01em }}
h2 {{ font-size:20px; margin:40px 0 8px; padding-top:8px; border-top:1px solid var(--line) }}
h3 {{ font-size:15px; margin:20px 0 6px }}
a {{ color:var(--accent) }}
.sub {{ color:var(--muted); margin:0 0 20px }}
.intro {{ color:var(--muted); max-width:900px }}
code.fn {{ word-break:normal; overflow-wrap:anywhere }}
code {{ font-family:ui-monospace, SFMono-Regular, Menlo, monospace; background:var(--code); padding:1px 4px; border-radius:4px; word-break:break-all }}
.small {{ font-size:12px }} .muted {{ color:var(--muted) }}
.tiles {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(180px, 1fr)); gap:12px; margin:20px 0 }}
.tile {{ background:var(--panel); border:1px solid var(--line); border-radius:10px; padding:14px 16px }}
.tile .big {{ font-size:26px; font-weight:650; font-variant-numeric:tabular-nums }}
.tile .lab {{ color:var(--muted); font-size:13px }}
.small-tiles .big {{ font-size:20px }}
.tablewrap {{ overflow-x:auto; border:1px solid var(--line); border-radius:10px; background:var(--panel) }}
table {{ border-collapse:collapse; width:100% }}
th, td {{ text-align:left; vertical-align:top; padding:9px 10px; border-bottom:1px solid var(--line) }}
th {{ font-size:12px; text-transform:uppercase; letter-spacing:0.04em; color:var(--muted); font-weight:600; background:var(--panel); }}
table.tests {{ min-width:1100px; font-size:13.5px }}
table.tests td:nth-child(1) {{ width:17% }} table.tests td:nth-child(2) {{ width:21% }} table.tests td:nth-child(3) {{ width:18% }}
table.tests td:nth-child(4) {{ width:11% }} table.tests td:nth-child(5) {{ width:20% }} table.tests td:nth-child(6) {{ width:9% }}
tr:last-child td {{ border-bottom:none }}
.tname {{ font-weight:600; margin-bottom:2px }}
.note {{ margin-top:6px; color:var(--muted); font-size:12.5px }}
.num {{ text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap }}
.pill {{ display:inline-block; padding:2px 8px; border-radius:999px; font-size:12px; font-weight:600 }}
.pill.ok {{ color:var(--ok); background:var(--okbg) }} .pill.bad {{ color:var(--bad); background:var(--badbg) }}
.bar {{ height:6px; background:var(--track); border-radius:3px; overflow:hidden; margin:6px 0 3px; min-width:70px }}
.bar span {{ display:block; height:100%; border-radius:3px }}
.bar .lo {{ background:var(--lo) }} .bar .mid {{ background:var(--mid) }} .bar .hi {{ background:var(--hi) }}
.pct {{ font-size:12px; color:var(--muted); font-variant-numeric:tabular-nums }}
table.mini {{ font-size:13.5px }}
.tablewrap + p, .tablewrap {{ margin-bottom:10px }}
.two {{ display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1fr); gap:20px }}
@media (max-width: 860px) {{ .two {{ grid-template-columns:minmax(0,1fr) }} }}
nav.toc {{ display:flex; flex-wrap:wrap; gap:6px 14px; font-size:13.5px; margin:8px 0 0 }}
figure {{ margin:12px 0; background:#fff; border:1px solid var(--line); border-radius:10px; padding:10px }}
figure img {{ max-width:100%; height:auto; display:block; margin:0 auto }}
figcaption {{ color:#555; font-size:12.5px; margin-top:6px }}
.figs {{ display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1fr); gap:16px }}
@media (max-width: 860px) {{ .figs {{ grid-template-columns:minmax(0,1fr) }} }}
ul.conv li {{ margin-bottom:8px; max-width:950px }}
.summary td a {{ text-decoration:none }}
</style></head><body><main>
<h1>LensForge validation against known truth</h1>
<p class="sub">Every test in the suite that compares a LensForge result with an independent truth: closed-form optics, published values, another optical code (Optiland 0.6.3), book prescriptions and glass catalogs.
Measured on main at commit <code>{META['commit']}</code> ({META['date']}), Python {META['python']}, NumPy {META['numpy']}, Optiland {META['optiland']}. Report generated {META['generated']}.</p>

<div class="tiles">
<div class="tile"><div class="big">{all_pass} / {all_cases}</div><div class="lab">truth-comparison test cases passed</div></div>
<div class="tile"><div class="big">{tot_funcs}</div><div class="lab">individual tests described below ({tot_cases} cases)</div></div>
<div class="tile"><div class="big">{len(smith_ids)}</div><div class="lab">Smith book lenses checked against printed EFL/BFL</div></div>
<div class="tile"><div class="big">{ngl}</div><div class="lab">catalog glasses checked against printed n<sub>d</sub>, V<sub>d</sub></div></div>
</div>

<h3>How to read this report</h3>
<p class="intro" style="max-width:1000px">“How LensForge did” comes from running the tests for this report. A small pytest plugin recorded every numeric comparison each test made (pytest.approx, numpy assert_allclose, and plain <code>error &lt; bound</code> asserts), and the table shows the one that came closest to its tolerance. Parametrised tests are pooled over all their cases.
“Share of tolerance used” is that worst error divided by the allowed error: a short bar means LensForge agrees with the truth by much more than the test demands. A few tests check a flag or a sign rather than a number, and are marked as exact. To regenerate this page, run <code>python tools/validation_report/run.py</code>.</p>

<h3>Summary by area</h3>
<div class="tablewrap"><table class="summary"><thead><tr><th>Area</th><th class="num">Tests</th><th class="num">Cases</th><th class="num">Passed</th><th>Worst share of tolerance</th></tr></thead>
<tbody>{''.join(summary_rows)}
<tr><td><a href="#smith">Group: Smith book prescriptions</a></td><td class="num">1</td><td class="num">{len(smith_ids)}</td><td class="num">{smith_pass}</td><td class="muted small">see section</td></tr>
<tr><td><a href="#glass">Group: glass catalogs</a></td><td class="num">2</td><td class="num">{len(gl_ids) + len(vend)}</td><td class="num">{gl_pass + vend_pass}</td><td class="muted small">see section</td></tr>
</tbody></table></div>

{''.join(sec_html)}

<section id="figs"><h2>MTF validation figures</h2>
<p class="intro">From docs/mtf-validation.md. The left plot backs the Hopkins test; the right one backs the Optiland MTF tests.</p>
<div class="figs">{figs}</div></section>

{smith_html}
{glass_html}

<section id="conventions"><h2>Convention differences found and how the tests handle them</h2>
<ul class="conv">
<li><b>Seidel sign.</b> Optiland’s Seidel sums are the negative of LensForge’s. LensForge follows Welford and Zemax (S1 &gt; 0 for an under-corrected positive lens), and the thin-lens test confirms Welford’s signs. The Optiland tests compare against −Optiland. The docstring in <code>lensforge/analysis/seidel.py</code> writes the Lagrange invariant H with the opposite sign to Welford; that changes no result because H only appears squared.</li>
<li><b>TAST.</b> LensForge used to report TAST = S3/(n′u′), the full separation of the tangential and sagittal foci. Since PR #76 it follows Zemax and Optiland, S3/(2n′u′), and LAST halved with it. TSFC and TTFC did not change, and the test checks TTFC − TSFC = 2 TAST.</li>
<li><b>OPD reference sphere for non-primary wavelengths.</b> LensForge centres every wavelength’s reference sphere on the primary-wavelength chief ray; Optiland uses each wavelength’s own chief ray. Off axis the fans differ by a tilt of up to 0.03 waves on this lens, so the test removes a linear term before comparing and requires the residual to be under 1e-3 waves.</li>
<li><b>GEO spot sampling.</b> Both codes trace 6 hexapolar rings, but Optiland starts each ring at a different angle, so the largest sampled ray (GEO radius) differs by up to 0.45 % at full field. The RMS radius does not depend on the starting angle and agrees to about 1e-7.</li>
<li><b>MTF frequency scale off axis.</b> LensForge fits the image-space NA to all pupil rays; Optiland uses marginal-ray direction differences projected on the image plane. This is the largest remaining FFT MTF difference (up to 0.008 off axis, 0.001 on axis).</li>
<li><b>Strehl definition.</b> LensForge’s Strehl is peak / perfect peak, as in OpticStudio, so at 1 wave of defocus it reports the brightest ring rather than the dark centre.</li>
</ul></section>

<section id="gaps"><h2>Not yet covered by a truth comparison</h2>
<ul class="conv">
<li>Published Seidel tables from a textbook or from Zemax output. Seidel sums are checked only against closed form and Optiland.</li>
<li>Off-axis OPD against a closed form, and fifth-order aberration coefficients.</li>
<li>Spot diagrams and fans through aspheres, gratings or decentred systems against another code.</li>
<li>Polychromatic MTF against another code (Optiland’s MTF is monochromatic only).</li>
<li>Tolerancing and global optimisation results. Those tests check behaviour (bounds, reproducibility, compensators), not agreement with an external truth, and are left out of this report, as are file-format, UI and layout tests.</li>
</ul>
<p class="muted small">Left out on purpose: tests that only compare LensForge with itself (for example JSON round trips, multi-configuration copies, or the default merit function against the analysis it mirrors). The non-sequential vs sequential comparison is kept because the two tracers are separate code.</p>
</section>
</main></body></html>"""

out = sys.argv[2]
os.makedirs(os.path.dirname(out), exist_ok=True)
open(out, "w").write(page)
print("wrote", out, len(page))
