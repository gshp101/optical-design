"""Help pages for the Merit Function Editor (Help > Help Contents > Merit Function Editor, or the
editor's Help button / F1 while the editor has focus).

The operand reference is generated from :mod:`lensforge.optimize.operands`, so names, descriptions,
parameters and default bounds cannot drift from the code.  ``OPERAND_GROUPS`` must list every operand
once; ``tests/test_qt_app.py`` fails when a new operand is not filed in a group.
"""

from __future__ import annotations

import html
import inspect
import re
from typing import Dict, List, Optional, Tuple

from lensforge.optimize.operands import DEFAULT_BOUND, OPERAND_INFO, OPERANDS

TOPIC_PREFIX = ":topic:"
ROOT = TOPIC_PREFIX + "mfe"

#: group title -> operands, in the order they appear in the reference
OPERAND_GROUPS: Dict[str, List[str]] = {
    "First-order (paraxial) properties": [
        "EFFL", "BFL", "PMAG", "WFNO", "ISFN", "ISNA", "EPDI", "ENPP", "EXPP", "PIMH", "LINV", "TOTR", "POWR",
        "PARY", "PARB", "AXCL"],
    "Lens data and construction limits": [
        "PARV", "CVVA", "CVGT", "CVLT", "COVA", "COGT", "COLT", "CTVA", "CTGT", "CTLT", "ETVA", "ETGT", "ETLT",
        "TTHI", "MNCT", "MXCT", "MNCG", "MXCG", "MNCA", "MXCA", "MNET", "MXET", "MNEG", "MXEG", "MNEA", "MXEA",
        "INDX", "ABBE"],
    "Real rays (one ray each)": [
        "REAX", "REAY", "REAZ", "REAR", "REAB", "RANG", "RAID", "RAED", "TRAX", "TRAY", "TRAR", "OPDC"],
    "Image quality": [
        "RAYS", "OPDS", "RSCE", "RSCH", "GEOS", "RWCE", "STRH", "MTFT", "MTFS", "MTFA", "EERA", "ZERN", "DIST",
        "LACL", "RELI"],
    "Third-order (Seidel) aberrations": ["SPHA", "COMA", "ASTI", "FCUR", "DISW", "SEID"],
    "Maths on other rows, constants and user functions": [
        "BLNK", "CONS", "SUMM", "DIFF", "PROD", "DIVI", "ABSO", "SQRT", "OSUM", "MAXX", "MINN", "OPGT", "OPLT",
        "OPVA", "USER"],
}

#: parameter name -> meaning (shown under the operand reference)
PARAM_HELP: Dict[str, str] = {
    "surf": "Surface number as in the Lens Data Editor: the object is 0, the first lens surface 1, the image "
            "is the last. For REAX..RANG, leaving it out means the image surface. For SPHA..DISW, 0 means the "
            "sum over all surfaces.",
    "surf2": "Last surface of a range surf..surf2 (inclusive). Left out: the range runs to the surface before "
             "the image (MN../MX.. operands) or is surf alone (TTHI).",
    "hx, hy": "Normalised field coordinates, -1 to 1 (see Field and pupil coordinates).",
    "px, py": "Normalised pupil coordinates on the unit circle (see Field and pupil coordinates).",
    "field": "Which field point: an index counting from 0 (field=0 is the first row of the Fields table), or "
             "normalised coordinates written as a pair, field=(0, 0.7). For DIST it is a fraction of the full "
             "field instead (field=1.0 is the edge).",
    "wave": "Which wavelength: an index counting from 0 (wave=0 is the first row of the Wavelengths table). "
            "Left out: the primary wavelength for single-wavelength operands, and all wavelengths with their "
            "weights (polychromatic) for RSCE, RSCH, GEOS, STRH, MTF.., EERA.",
    "wavelengths": "For RAYS and OPDS: a list of wavelength indices, e.g. wavelengths=[1]. Left out: all "
                   "wavelengths, weighted by their wavelength weights.",
    "reference": "'centroid' (spot measured about its centroid; tilt removed for OPDS) or 'chief' (about the "
                 "chief ray of the primary wavelength).",
    "rings, arms": "Pupil sampling of RAYS / OPDS: Gaussian quadrature with rings x arms rays per field and "
                   "wavelength. 3 x 6 is accurate for most lenses; raise rings for fast or strongly aberrated "
                   "lenses. RSCE / RSCH / GEOS take rings only (a hexapolar grid).",
    "symmetric": "RAYS / OPDS: trace only half the pupil. Left out: decided automatically from the lens "
                 "(symmetric about the y-z plane with no x fields).",
    "freq": "Spatial frequency in cycles per mm.",
    "fraction": "EERA: the energy fraction, 0 to 1 (0.8 = radius holding 80% of the energy).",
    "param": "PARV: a lens parameter by name, e.g. 'curvature', 'thickness', 'conic', 'glass.nd', "
             "'glass.vd', an aspheric term such as 'coefficients[1]' or an XY polynomial term such as 'terms[3]'.",
    "term": "ZERN: Zernike term number (Fringe numbering from 1 by default; kind='standard' for Noll). SEID: "
            "a Seidel quantity name such as 'S1'..'S5', 'CL', 'CT'.",
    "kind": "ZERN: 'fringe' or 'standard'. DIST: 'ftan' (F-tan(theta)) or 'ftheta' (F-theta).",
    "height": "ETVA / ETGT / ETLT: the height at which the edge thickness is measured. Left out: the larger "
              "semi-diameter of the two surfaces.",
    "sampling": "Pupil grid size for RWCE and RELI (32 = 32 x 32).",
    "value": "CONS: the constant.",
    "a, b": "Row references for the maths operands. They count from 0, so the first row of the editor "
            "(row 1) is a=0 and row 5 is a=4. A row can only refer to rows above it.",
    "func": "USER (scripts only): a Python function f(system, **args) returning a number or a Block.",
}


def _fmt_default(v) -> str:
    return repr(v) if isinstance(v, str) else str(v)


def operand_signature(name: str) -> str:
    """The parameters of an operand as typed in the Parameters column, with defaults:
    ``"surf, hx=0.0, hy=0.0, px=0.0, py=0.0, wave=None"``."""
    parts = []
    for p in list(inspect.signature(OPERANDS[name]).parameters.values())[1:]:  # skip ctx
        if p.kind is p.VAR_KEYWORD:
            parts.append("...")
        elif p.default is p.empty:
            parts.append(p.name)
        else:
            parts.append(f"{p.name}={_fmt_default(p.default)}")
    return ", ".join(parts)


def operand_tooltip(name: str) -> str:
    """Tooltip of a row in the editor: description, parameters and default bound."""
    sig = operand_signature(name)
    return (f"{name}: {OPERAND_INFO[name]}\nParameters: {sig or '(none)'}\n"
            f"Default bound: {DEFAULT_BOUND[name]}\nF1: Merit Function Editor help")


COLUMN_TIPS = {
    "Type": "Four-letter operand name. Double-click for a list; Operands... describes them all.",
    "Parameters": "name=value pairs separated by commas, e.g. surf=4, hy=1, py=1. Left-out parameters take "
                  "their defaults.",
    "Bound": "= aim for the target; > at least the target; < at most the target (no penalty once satisfied).",
    "Target": "The value this row should reach (or stay above / below).",
    "Weight": "How much this row counts. > 0: part of the merit function; 0: shown only; < 0: hard "
              "constraint met exactly by damped least squares.",
    "Value": "Current value, recomputed after every change (RMS of all rays for RAYS / OPDS rows).",
    "% Contrib": "Share of the merit function's weighted sum of squares that comes from this row.",
    "Comment": "Free text.",
}


# --------------------------------------------------------------------------- pages

_OVERVIEW = f"""
<h2>Merit Function Editor</h2>
<p><b>Tools &gt; Merit Function Editor</b> (F6). The merit function is the single number the optimiser
makes as small as it can. The editor builds it from rows called <b>operands</b>. Each row computes one
property of the lens (a focal length, a ray height, the RMS spot of a field, a lens thickness ...),
compares it with a <b>target</b>, and adds the squared difference times a <b>weight</b> to the total.
The merit function is shown at the bottom of the editor and on the main window's status bar, and is
saved with the lens.</p>
<p>A typical merit function has three parts:</p>
<ol>
<li><b>Requirements</b> that must hold: focal length, F-number, total length, magnification. Usually
hard constraints (negative weight).</li>
<li><b>Manufacturing limits</b>: minimum and maximum glass and air thicknesses, edge thicknesses.
These are one-sided boundaries that cost nothing while they are satisfied.</li>
<li><b>Image quality</b>: the rays of every field should land on one point (RMS spot) or the
wavefront should be flat (RMS wavefront), or the MTF should be high. The <b>Wizard...</b> button
writes these rows for you.</li>
</ol>
<p>Then mark radii and thicknesses as variables in the Lens Data Editor (Ctrl+Shift+V, or Tools &gt;
Variables and Solves) and run <b>Tools &gt; Optimization</b>.</p>
<h3>On these pages</h3>
<ul>
<li><a href="help:mfe/columns">Columns and toolbar</a>: what each column means and how to type parameters.</li>
<li><a href="help:mfe/value">How the merit function is computed</a>: the formula, bounds and % Contrib.</li>
<li><a href="help:mfe/weights">Weights</a>: positive, zero and negative weights, and how to balance them.</li>
<li><a href="help:mfe/coordinates">Field and pupil coordinates (Hx, Hy, Px, Py)</a>: which ray an
operand traces, ray heights on surfaces.</li>
<li><a href="help:mfe/operands">Operand reference</a>: every operand with its parameters.</li>
<li><a href="help:mfe/example">Example: minimise the RMS spot size</a>: a complete merit function,
step by step.</li>
</ul>
"""

_COLUMNS = """
<h2>Columns and toolbar</h2>
<p>One row per operand; the numbers on the left count rows from 1. Double-click a cell (or start
typing) to edit it. Every edit is one undo step (Ctrl+Z).</p>
<table border="1" cellspacing="0" cellpadding="4">
<tr><th>Column</th><th>Meaning</th></tr>
<tr><td><b>Type</b></td><td>The operand's four-letter name, such as EFFL or RAYS. The editor offers a
list with completion. Changing the type resets the Bound to that operand's default (= for most, &gt;
for MN.. / ..GT, &lt; for MX.. / ..LT). <b>BLNK</b> rows compute nothing; use them as headings with
a comment.</td></tr>
<tr><td><b>Parameters</b></td><td>The operand's inputs, typed as <code>name=value</code> pairs
separated by commas: <code>surf=5, hy=1, py=1</code>. Values are numbers, text in quotes
(<code>reference='chief'</code>), lists (<code>wavelengths=[0, 2]</code>) or pairs
(<code>field=(0, 0.7)</code>). Parameters you leave out take their default values, listed in the
<a href="help:mfe/operands">operand reference</a>; hover over a row to see them too. A misspelt
parameter name makes the row fail and the error is shown under the table.</td></tr>
<tr><td><b>Bound</b></td><td><b>=</b> the value should equal the target. <b>&gt;</b> the value should
be at least the target. <b>&lt;</b> the value should be at most the target. With &gt; or &lt; the row
adds nothing while the condition holds, and only the amount by which it is violated counts.</td></tr>
<tr><td><b>Target</b></td><td>The desired value, in the operand's units: lens units (mm by default)
for lengths, waves for wavefront operands, degrees for RAID / RAED, radians for RANG, percent for
DIST, a plain number for F-numbers, MTF and Strehl.</td></tr>
<tr><td><b>Weight</b></td><td>How much the row counts. Positive: part of the merit function. Zero:
computed and shown, not optimised (greyed). Negative: a hard constraint (pink row). See
<a href="help:mfe/weights">Weights</a>.</td></tr>
<tr><td><b>Value</b></td><td>The current value, recomputed in the background after every change to
the lens. For RAYS and OPDS rows it is the RMS over all their rays: the RMS spot radius or RMS
wavefront of that field. For MN.. / MX.. rows, which check many surfaces at once, it is the
smallest (MN..) or largest (MX..) thickness found. Blank when the row failed.</td></tr>
<tr><td><b>% Contrib</b></td><td>The row's share of the weighted sum of squares, so it shows which
rows dominate the merit function. Rows with positive weight add up to 100. Blank for weight 0 and for
hard constraints.</td></tr>
<tr><td><b>Comment</b></td><td>Free text: say what the row is for.</td></tr>
</table>
<h3>Toolbar</h3>
<ul>
<li><b>Add Row</b> (Ctrl+Shift+A) adds a BLNK row at the end; <b>Insert Row</b> (Insert) adds one above
the selected row; <b>Delete Rows</b> (Shift+Delete) deletes the selected rows.</li>
<li><b>Wizard...</b> writes a default image-quality merit function: one RAYS (RMS spot), OPDS (RMS
wavefront) or MTFA row per field, weighted by the field weights, plus optional glass and air
thickness limits. With <i>Keep my other operands</i> ticked, your own rows stay above the new
ones.</li>
<li><b>Operands...</b> lists every operand with a description and a filter; Insert puts the chosen
one above the selected row.</li>
<li><b>Clear</b> removes all rows (undoable). <b>Help</b> opens these pages; F1 in the editor does
the same.</li>
</ul>
<p>Below the table: the merit function value, and the error of the first row that failed (for
example a ray that misses a surface). Note that row numbers in error messages count from 0, like
the a / b row references.</p>
"""

_VALUE = """
<h2>How the merit function is computed</h2>
<p>For every row the editor computes the value <i>V</i> and the error against the target <i>T</i>:</p>
<ul>
<li>Bound <b>=</b>: error = <i>V</i> &minus; <i>T</i></li>
<li>Bound <b>&gt;</b>: error = <i>V</i> &minus; <i>T</i> if <i>V</i> &lt; <i>T</i>, otherwise 0</li>
<li>Bound <b>&lt;</b>: error = <i>V</i> &minus; <i>T</i> if <i>V</i> &gt; <i>T</i>, otherwise 0</li>
</ul>
<p>The merit function is the weighted root-mean-square of the errors of all rows with a positive
weight <i>W</i>:</p>
<p style="margin-left:24px"><b>MF</b> = sqrt( &Sigma; <i>W</i><sub>i</sub> &times; error<sub>i</sub><sup>2</sup>
&nbsp;/&nbsp; &Sigma; <i>W</i><sub>i</sub> )</p>
<p>Because it is divided by the sum of the weights, the merit function stays in the units of its
operands. A merit function made only of RAYS rows is the RMS spot radius in lens units, averaged
over the fields (in the sense of an RMS: the square root of the field-weighted mean of the squared
RMS spot radii).</p>
<h3>Rows that hold many values</h3>
<p>RAYS and OPDS rows trace a whole bundle of rays and contribute every ray's error separately: x and
y ray errors for RAYS, the optical path difference for OPDS. Inside the row each ray carries its
pupil-sampling (Gaussian quadrature) weight times its wavelength weight; together they count as
<i>one</i> unit of the row's weight in the denominator. So a RAYS row with weight 1 adds exactly
(RMS spot radius)<sup>2</sup> to the numerator and 1 to the denominator. Giving the optimiser every
ray, instead of one RMS number, is what makes RAYS converge faster than RSCE.</p>
<p>The MN.. / MX.. thickness rows check every surface in a range and add a penalty for each one that
breaks the limit, but add nothing to the denominator, so they do not dilute the merit function while
they are satisfied. (Single-surface limits such as CTGT count once in the denominator like any other
row.)</p>
<h3>Rows that are left out</h3>
<ul>
<li>Weight 0: computed and shown only.</li>
<li>Negative weight: hard constraints are handled separately by the optimiser and are not part of
the number.</li>
<li>BLNK rows have weight 0 by default.</li>
</ul>
<h3>% Contrib</h3>
<p>Each row's <i>W</i> &times; error<sup>2</sup> as a percentage of the total. A row with 60% is where
the design is worst; raising its weight makes the optimiser work harder on it, lowering it lets it
go.</p>
<h3>When something fails</h3>
<p>If any row cannot be computed (a ray misses a surface or is totally internally reflected, a row
refers to a row below it, a parameter is misspelt), the merit function is infinite and the first
error is shown under the table. The optimiser treats such designs as unusable and steps back.</p>
<h3>Worked numbers</h3>
<p>Three RAYS rows with weight 1 whose Values are 0.0135, 0.0193 and 0.0268 mm give<br>
MF = sqrt((0.0135<sup>2</sup> + 0.0193<sup>2</sup> + 0.0268<sup>2</sup>) / 3) = 0.0206 mm, and
% Contrib of 14%, 29% and 56%: the edge field dominates.</p>
"""

_WEIGHTS = """
<h2>Weights</h2>
<p>The weight says how much a row matters compared with the other rows. Its sign chooses what kind
of row it is:</p>
<table border="1" cellspacing="0" cellpadding="4">
<tr><th>Weight</th><th>Effect</th><th>Use it for</th></tr>
<tr><td><b>&gt; 0</b></td><td>Soft target: the squared error times the weight is added to the merit
function. The optimiser trades it against every other row.</td><td>Image quality, and goals that may
give a little.</td></tr>
<tr><td><b>0</b></td><td>Monitor: the Value is shown but nothing is optimised. Greyed
text.</td><td>Watching distortion, total length, a single RSCE spot radius ... while optimising
something else.</td></tr>
<tr><td><b>&lt; 0</b></td><td>Hard constraint: damped least squares meets it exactly (to about
1e-9) using Lagrange multipliers, whatever it costs the other rows. With bound &gt; or &lt; it is an
inequality that is only enforced when violated. The size of the number does not matter, only the
sign. Pink row.</td><td>Focal length, F-number, magnification, total track: requirements that are not
negotiable.</td></tr>
</table>
<p><b>A single row always counts.</b> When the merit function has only one row (other than BLNK),
a weight of 0 would make the merit function always 0, so nothing could change. That row is given
weight 1 automatically: when you choose its operand type, when the lens file is opened, and when
optimisation starts.</p>
<h3>Only ratios matter</h3>
<p>Because the merit function divides by the sum of the weights, multiplying every weight by 10
changes nothing: neither the value nor the optimum. What matters is how the weights compare. A
row with weight 4 counts like a row with weight 1 whose error is twice as large.</p>
<h3>Balancing rows with different units</h3>
<p>Errors are squared in the operand's own units, so rows in different units must be balanced by
their weights. Example: an RMS spot of 0.02 mm and a focal length 0.5 mm off its target, both weight
1. The squared errors are 0.0004 and 0.25, so the focal length takes 99.8% of the merit function and
the optimiser ignores the image. A good rule:</p>
<p style="margin-left:24px">weight &asymp; (error you accept in the image-quality rows / error you
accept in this row)<sup>2</sup></p>
<p>If 0.1 mm of focal length error is as bad as 0.02 mm of RMS spot, use weight (0.02 / 0.1)<sup>2</sup>
= 0.04 on the EFFL row. Or, simpler and exact, make the focal length a hard constraint with weight
&minus;1.</p>
<h3>Weighting fields and wavelengths</h3>
<ul>
<li>The wizard gives each field's RAYS / OPDS row the field's weight from the Fields table. Raise
the weight of a row to make that field sharper at the expense of the others; set it to 0 to ignore
the field.</li>
<li>Wavelength weights (Wavelengths table) are applied <i>inside</i> RAYS, OPDS and the polychromatic
image-quality operands, so change them there, not in the merit function.</li>
</ul>
<h3>Boundaries</h3>
<p>MN.. / MX.. and ..GT / ..LT rows with a positive weight cost nothing until they are violated. Since
image-quality errors are small (hundredths of a mm), a thickness that is 0.1 mm too thin already
outweighs them with weight 1. If a limit still creeps past, raise its weight (10 or 100) or make it
hard (&minus;1).</p>
<h3>Reading the result</h3>
<p>Use <b>% Contrib</b> to see where the merit function comes from. If one row holds most of it and
you can live with that row, lower its weight; if a row you care about is near 0%, raise it. After
changing weights, optimise again.</p>
"""

_COORDS = """
<h2>Field and pupil coordinates (Hx, Hy, Px, Py)</h2>
<p>Operands that trace a single ray (REAX, REAY, REAR, TRAY, OPDC, PARY ...) pick it with four
normalised coordinates, typed in the Parameters column as <code>hx</code>, <code>hy</code>,
<code>px</code>, <code>py</code>. All four default to 0.</p>
<ul>
<li><b>hx, hy</b>: where the ray comes from in the field, as a fraction of the largest field in
the Fields table (in whatever field type you use: angle, object height or image height).
<code>hy=1</code> is the full field along y, <code>hy=0.7</code> is 70% of it, <code>hy=-1</code> the
other side.</li>
<li><b>px, py</b>: where the ray passes through the entrance pupil, as a fraction of the pupil
radius. <code>py=1</code> is the top edge of the pupil, <code>py=-1</code> the bottom,
<code>px=1</code> the side edge (sagittal), (0, 0) the centre. Keep px<sup>2</sup> + py<sup>2</sup>
&le; 1.</li>
</ul>
<table border="1" cellspacing="0" cellpadding="4">
<tr><th>Ray</th><th>Parameters</th></tr>
<tr><td>Axial marginal ray (top of the pupil, on axis)</td><td><code>hy=0, py=1</code></td></tr>
<tr><td>Chief ray of the full field</td><td><code>hy=1, py=0</code></td></tr>
<tr><td>Upper rim ray of the full field</td><td><code>hy=1, py=1</code></td></tr>
<tr><td>Lower rim ray of the full field</td><td><code>hy=1, py=-1</code></td></tr>
<tr><td>Sagittal rim ray of the full field</td><td><code>hy=1, px=1</code></td></tr>
<tr><td>Zonal ray (70% of the pupil, on axis)</td><td><code>py=0.7071</code></td></tr>
</table>
<p><b>wave</b> picks the wavelength by its row in the Wavelengths table counting from 0; left out
it is the primary wavelength. <b>surf</b> is the surface number shown in the Lens Data Editor (object
0, then 1, 2 ... up to the image); left out, REA.. operands use the image surface.</p>
<h3>Ray heights on a surface</h3>
<ul>
<li><b>REAY</b> / <b>REAX</b>: the real ray's y / x coordinate on a surface, in that surface's local
coordinates and lens units.</li>
<li><b>REAR</b>: the radial height sqrt(x<sup>2</sup> + y<sup>2</sup>).</li>
<li><b>PARY</b>: the paraxial ray height (first-order optics). It takes hy and py only; its default
py=1 is the marginal ray.</li>
</ul>
<p>Example: keep the full-field upper rim ray below 9 mm on surface 5 (so the lens fits a 18 mm
mount): Type <code>REAY</code>, Parameters <code>surf=5, hy=1, py=1</code>, Bound <code>&lt;</code>,
Target 9, Weight 1. Add a second row with <code>py=-1</code> and Bound <code>&gt;</code>, Target &minus;9
for the lower rim ray.</p>
<p>Example: telecentric image space, the chief ray parallel to the axis: <code>RANG</code>,
<code>surf=6, hy=1</code>, Target 0, for a lens whose last surface before the image is 6.</p>
<h3>Transverse ray errors</h3>
<p><b>TRAY</b> / <b>TRAX</b> / <b>TRAR</b> give how far a ray lands from the chief ray of the same
field (primary wavelength) on the image. A hand-made spot-size merit function is a set of TRAY and
TRAX rows with target 0 for several pupil points per field, e.g. <code>hy=1, py=1</code>,
<code>hy=1, py=-1</code>, <code>hy=1, px=1</code>, <code>hy=1, py=0.5</code>. RAYS does exactly that
for a whole Gaussian-quadrature ray set, with the right weights, in one row.</p>
<h3>Fields for image-quality operands</h3>
<p>RAYS, OPDS, RSCE, MTF.. and the like take <b>field</b>: an index counting from 0 (field=0 is the
first row of the Fields table), or a pair of normalised coordinates, <code>field=(0, 0.7)</code>.</p>
"""

_EXAMPLE = """
<h2>Example: minimise the RMS spot size</h2>
<p>A Cooke triplet, f = 100 mm, F/4 (entrance pupil 25 mm), fields 0, 10 and 14 degrees, visible
light (F, d, C). The task: make the image as sharp as possible over the whole field while keeping
the focal length at exactly 100 mm and the lens buildable.</p>
<p><b>Open it ready-made:</b> File &gt; Sample Lenses &gt; Spot Size Merit Example. The file is
<code>examples/spot_size_merit.lens.json</code>; the script that builds and optimises it is
<code>examples/spot_size_merit.py</code>.</p>
<h3>The merit function</h3>
<table border="1" cellspacing="0" cellpadding="3">
<tr><th>#</th><th>Type</th><th>Parameters</th><th>Bound</th><th>Target</th><th>Weight</th><th>Comment</th></tr>
<tr><td>1</td><td>BLNK</td><td></td><td>=</td><td>0</td><td>0</td><td>First-order requirements</td></tr>
<tr><td>2</td><td>EFFL</td><td></td><td>=</td><td>100</td><td>&minus;1</td><td>focal length exactly 100 mm (hard)</td></tr>
<tr><td>3</td><td>BLNK</td><td></td><td>=</td><td>0</td><td>0</td><td>Manufacturing limits</td></tr>
<tr><td>4</td><td>MNCG</td><td></td><td>&gt;</td><td>2</td><td>1</td><td>glass at least 2 mm thick at the centre</td></tr>
<tr><td>5</td><td>MNEG</td><td></td><td>&gt;</td><td>1</td><td>1</td><td>glass at least 1 mm thick at the edge</td></tr>
<tr><td>6</td><td>MNCA</td><td></td><td>&gt;</td><td>1</td><td>1</td><td>air gaps at least 1 mm</td></tr>
<tr><td>7</td><td>BLNK</td><td></td><td>=</td><td>0</td><td>0</td><td>Image quality: RMS spot radius per field</td></tr>
<tr><td>8</td><td>RAYS</td><td>field=0, reference='centroid', rings=3, arms=6</td><td>=</td><td>0</td><td>1</td><td>on axis</td></tr>
<tr><td>9</td><td>RAYS</td><td>field=1, reference='centroid', rings=3, arms=6</td><td>=</td><td>0</td><td>1</td><td>10 degrees</td></tr>
<tr><td>10</td><td>RAYS</td><td>field=2, reference='centroid', rings=3, arms=6</td><td>=</td><td>0</td><td>1</td><td>14 degrees</td></tr>
<tr><td>11</td><td>BLNK</td><td></td><td>=</td><td>0</td><td>0</td><td>Monitors (weight 0: shown, not optimised)</td></tr>
<tr><td>12</td><td>RSCE</td><td>field=0</td><td>=</td><td>0</td><td>0</td><td>RMS spot on axis, hexapolar grid</td></tr>
<tr><td>13</td><td>RSCE</td><td>field=2</td><td>=</td><td>0</td><td>0</td><td>RMS spot at 14 degrees</td></tr>
<tr><td>14</td><td>DIST</td><td>field=1.0</td><td>=</td><td>0</td><td>0</td><td>distortion at the field edge (%)</td></tr>
<tr><td>15</td><td>TOTR</td><td></td><td>=</td><td>0</td><td>0</td><td>total track</td></tr>
</table>
<h3>Why each row is there</h3>
<ul>
<li><b>EFFL, weight &minus;1</b>: the focal length is a requirement, not a wish, so it is a hard
constraint. With a positive weight it would have to be balanced against spot sizes of a few
hundredths of a mm (see <a href="help:mfe/weights">Weights</a>).</li>
<li><b>MNCG / MNEG / MNCA, bound &gt;</b>: without them the optimiser happily makes lenses with
negative edge thickness or touching elements. They cost nothing while they hold. The Value column
shows the thinnest glass or air found.</li>
<li><b>RAYS, one per field, target 0, weight 1</b>: these are the rows being minimised. Each traces
3 rings x 6 arms of rays in every wavelength and asks for every ray to land on the spot's centroid.
Their Value is that field's polychromatic RMS spot radius in mm, and the merit function is the RMS
of the three. Equal weights treat the fields equally; give the 14 degree row weight 2 to favour the
edge.</li>
<li><b>RSCE, DIST, TOTR, weight 0</b>: monitors you can watch while optimising. RSCE computes the
RMS spot the way the spot diagram does (a hexapolar grid of rays); it uses different rays from
RAYS, so the two numbers differ somewhat, mostly off axis.</li>
</ul>
<h3>Variables</h3>
<p>All six curvatures (surfaces 1 to 6) and the thicknesses of surfaces 2, 4 and 6 (the two air
gaps and the back focus, each at least 1 mm). Varying the back focus lets the optimiser find the
best focus for the spot size rather than paraxial focus.</p>
<h3>Run it</h3>
<ol>
<li>File &gt; Sample Lenses &gt; Spot Size Merit Example, then F6 for this editor. The merit
function starts near 0.89 mm: the starting lens is far from focused.</li>
<li>Tools &gt; Optimization, Damped least squares, Start.</li>
<li>After about 55 cycles (10 to 20 seconds) the merit function is about 0.021 mm: RAYS values
(RMS spot radii) of about 0.014, 0.019 and 0.027 mm, EFFL at 100.000, the glass exactly at its 2 mm
limit (MNCG Value 2) and the total track grown from 110 to 118 mm. The edge field holds over half the merit
function in % Contrib; this is where a better design (more glass choices, Hammer, glass
substitution) would help.</li>
<li>Open Analysis &gt; Rays &amp; Spots &gt; Standard Spot Diagram (Ctrl+D) to see the spots.</li>
</ol>
<h3>Build it yourself</h3>
<ol>
<li>Clear the editor, press <b>Wizard...</b>, choose RMS spot radius, Centroid, 3 rings, 6 arms, tick
Glass min centre 2, Glass min edge 1, Air min centre 1, OK. This writes the BLNK heading, the
MNCG / MNEG / MNCA limits and one RAYS row per field.</li>
<li>Select the first row, press Insert, and type EFFL in Type, 100 in Target and &minus;1 in
Weight.</li>
<li>Add the monitor rows with Add Row: type the operand name, its parameters, and weight 0.</li>
</ol>
<h3>From Python (Tools &gt; Python Shell or a script)</h3>
<pre>
mf = opt.MeritFunction()
mf.add("EFFL", 100.0, -1)
mf.add("MNCG", 2.0, 1)
mf.add("MNEG", 1.0, 1)
mf.add("MNCA", 1.0, 1)
for k in range(len(lens.fields)):
    mf.add("RAYS", 0.0, 1.0, field=k, reference="centroid", rings=3, arms=6)
mf.add("RSCE", 0.0, 0.0, field=0)
lens.merit_function = mf
print(mf.table(lens))
opt.optimize(lens, mf, cycles=100)
</pre>
<h3>Variations</h3>
<ul>
<li><b>Chief-ray reference</b> (<code>reference='chief'</code>): measures the spot about the chief
ray, so it also penalises lateral colour and coma-like asymmetry.</li>
<li><b>RSCE instead of RAYS</b>: also works, but each row gives the optimiser a single number per
field rather than every ray, so it converges more slowly (about twice the cycles here and a worse
result).</li>
<li><b>Sharpness for a sensor</b>: replace the RAYS rows with OPDS (RMS wavefront, waves) for
near-diffraction-limited lenses, or MTFA rows (target 1) at the sensor's frequency.</li>
<li><b>One wavelength</b>: <code>wavelengths=[1]</code> on the RAYS rows optimises for the d line
only.</li>
</ul>
"""


def _operands_html() -> str:
    parts = ["<h2>Operand reference</h2>",
             "<p>Every operand, grouped by what it measures. <i>Parameters</i> lists what can be typed in "
             "the Parameters column, with the default used when a parameter is left out (no default: "
             "required). <i>Bound</i> is the default bound set when the type is chosen. Lengths are in "
             "lens units.</p>"]
    for group, names in OPERAND_GROUPS.items():
        parts.append(f"<h3>{html.escape(group)}</h3>"
                     "<table border='1' cellspacing='0' cellpadding='3'>"
                     "<tr><th>Type</th><th>Description</th><th>Parameters</th><th>Bound</th></tr>")
        for n in names:
            sig = operand_signature(n)
            parts.append(f"<tr><td><b>{n}</b></td><td>{html.escape(OPERAND_INFO[n])}</td>"
                         f"<td><code>{html.escape(sig)}</code></td>"
                         f"<td align='center'>{html.escape(DEFAULT_BOUND[n])}</td></tr>")
        parts.append("</table>")
    parts.append("<h3>Parameters</h3><table border='1' cellspacing='0' cellpadding='3'>")
    for k, v in PARAM_HELP.items():
        parts.append(f"<tr><td valign='top'><code>{html.escape(k)}</code></td><td>{html.escape(v)}</td></tr>")
    parts.append("</table><p><code>...</code> in a parameter list means the operand passes further "
                 "options on to the analysis it uses (e.g. <code>method='huygens'</code> for MTF..).</p>")
    return "".join(parts)


#: (key, tree title, page) in tree order; the first is the parent of the others
_PAGES = [
    (ROOT, "Merit Function Editor", lambda: _OVERVIEW),
    (ROOT + "/columns", "Columns and toolbar", lambda: _COLUMNS),
    (ROOT + "/value", "How the merit function is computed", lambda: _VALUE),
    (ROOT + "/weights", "Weights", lambda: _WEIGHTS),
    (ROOT + "/coordinates", "Field and pupil coordinates (Hx, Hy, Px, Py)", lambda: _COORDS),
    (ROOT + "/operands", "Operand reference", _operands_html),
    (ROOT + "/example", "Example: minimise the RMS spot size", lambda: _EXAMPLE),
]
TOPICS: List[Tuple[str, str]] = [(k, t) for k, t, _ in _PAGES]


def topic_html(key: str) -> Optional[str]:
    for k, _, page in _PAGES:
        if k == key:
            return page()
    return None


def topic_text(key: str) -> str:
    """Plain text of a page, for the help browser's search."""
    page = topic_html(key) or ""
    return html.unescape(re.sub(r"<[^>]+>", " ", page))
