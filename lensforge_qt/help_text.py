"""Help for every menu command: a one-line summary (status bar, tooltips) and a longer description
(Help > Help Contents, What's This?).

Keep this file in step with the menus: every command needs an entry. ``tests/test_qt_app.py``
fails when a menu command has no help, when an entry no longer matches a command, or when a
command has no toolbar icon (see icons.py).

Commands are keyed by menu path as in toolbar_dialog.menu_items ("File > Insert Lens");
analyses by their registry key and sample lenses by name, so those menus can grow from
their registries.
"""

from __future__ import annotations

from typing import Optional, Tuple

from .analyses import REGISTRY

# Fields tab of the System Explorer (Qt and web): column header and button tooltips
FIELD_TIPS = {"VDX": "Vignetting decentre x (fraction of the pupil radius)",
              "VDY": "Vignetting decentre y (fraction of the pupil radius)",
              "VCX": "Vignetting compression x (0 = none, 0.3 = pupil 30% narrower)",
              "VCY": "Vignetting compression y (0 = none, 0.3 = pupil 30% narrower)",
              "VAN": "Vignetting angle in degrees: rotates the compressed pupil counter-clockwise"}
SET_VIGNETTING_TIP = ("Compute VDX/VDY/VCX/VCY for every field so its whole ray bundle gets through all surface "
                      "apertures and fixed semi-diameters (VAN sets the axes of the compression)")
CLEAR_VIGNETTING_TIP = "Set the vignetting factors and angle of every field back to zero"

# Equal-Area Fields dialog (Qt and web): tooltips of its entries
EQUAL_AREA_TIPS = {
    "count": "Number of fields from the minimum to the maximum field (one side of the axis)",
    "full": "Add the mirrored negative fields too, so the fields cover the full field from -maximum to +maximum",
    "maximum": "Largest field value (in the units of the field type)",
    "minimum": "Smallest field value; 0 puts the first field on axis",
}

#: menu path -> (summary, details)
HELP = {
    # ------------------------------------------------------------------ File
    "File > New": (
        "Start a new lens.",
        "Replaces the current lens with a minimal new system (object, one stop surface and the image). "
        "You are asked to save unsaved changes first."),
    "File > Open": (
        "Open a lens file (lensforge JSON or Zemax .zmx).",
        "Opens a lensforge .json lens, or imports a Zemax .zmx prescription (surfaces, glasses, fields, "
        "wavelengths, aperture). Imported .zmx files are saved as new JSON files. If the file uses a glass that "
        "no loaded catalog has, it still opens, but a warning names the glass and its surfaces, the Material cell "
        "turns red, and every analysis window is cleared and says why it cannot trace, so nothing from the "
        "previous lens stays on screen. Pick a replacement glass (Ctrl+G) or load a catalog that has it "
        "(File > Load Glass Catalog), and the analyses update. If the file cannot be read at all, the lens "
        "already open stays as it was."),
    "File > Save": (
        "Save the lens to its file.",
        "Writes the lens, variables, solves, merit function and the Input Rays settings to its JSON file. "
        "A lens that has never been saved asks for a file name."),
    "File > Save As": (
        "Save the lens under a new file name.",
        "Writes the lens to a new JSON file, which then becomes the current file."),
    "File > Inspect Lens File": (
        "Show the system report of a lens file in its own window, without opening the file.",
        "Choose a lens file (.json or .zmx). Its System Report (prescription, first-order data, cardinal "
        "points, Seidel coefficients and image quality per field) opens in a separate window; the current "
        "lens is not changed. The window is not modal, so you can keep editing and open several reports "
        "side by side to compare designs. <b>Copy</b> and <b>Save</b> take the report text; "
        "<b>Open in Editor</b> makes the file the current lens (you are asked to save changes first). "
        "Scripting: <code>lf.system_report(lf.load('file.json'))</code>."),
    "File > Insert Lens": (
        "Insert surfaces from a lens file into the current design, optionally scaled or reversed.",
        "Choose a lens file (.json or .zmx), the range of its surfaces to copy and the surface of the current "
        "lens to insert them in front of (the selected row by default). <b>Scale factor</b> multiplies every "
        "length: radii, thicknesses, semi-diameters, apertures, decentres and aspheric, freeform and phase "
        "terms. <b>Reverse</b> turns the group round: the surfaces are taken in the opposite order, curvatures "
        "and sag terms change sign, each surface takes the thickness and medium that preceded it, and "
        "coordinate breaks are inverted. The preview shows the surfaces exactly as they will be inserted and "
        "the group's focal length. Lenses in other units are converted to the current units. The current "
        "lens keeps its stop unless you tick the stop option. <b>Copy semi-diameters</b> gives each inserted "
        "surface the semi-diameter it has in the lens file, as a fixed value (marked U) and scaled with the "
        "lens; semi-diameters that are automatic in the file are computed from the file's own aperture, "
        "fields and wavelengths. Unticked, the inserted surfaces get automatic semi-diameters sized by the "
        "current lens's rays. Clear apertures set in Surface Properties are copied either way. One undo step "
        "removes the whole insertion. From Python: <code>lf.insert_lens(lens, 'file.json', at=3, scale=0.5, "
        "reverse=True, copy_semi_diameters=True)</code>."),
    "File > System Explorer": (
        "Set the aperture, fields, wavelengths and general system options.",
        "Opens the System Explorer: aperture type and value, field type and field points (with their "
        "vignetting factors, which Set Vignetting computes and Clear Vignetting resets), wavelengths and "
        "weights with the primary wavelength, units, ray aiming and notes."),
    "File > Fields": (
        "Edit the field points and their vignetting factors.",
        "Opens the System Explorer on the Fields tab: the field type (angle in degrees, object height, "
        "paraxial or real image height) and the x/y field points with weights."
        "<p><b>Equal-Area Fields...</b> opens a dialog that replaces the fields by y fields spaced so "
        "each zone between neighbouring fields covers the same area: <b>Fields in half field</b> sets how "
        "many fields run from the <b>Minimum field</b> to the <b>Maximum field</b> (field squared is evenly "
        "spaced, so 5 fields from 0 to 20 give 0, 10, 14.14, 17.32, 20), and <b>Full field</b> adds the "
        "mirrored negative fields too (one on-axis field, never two). The new fields have weight 1 and no "
        "vignetting; OK or Apply in the System Explorer writes them to the lens. From Python: "
        "<code>lens.set_equal_area_fields(5, 20.0, minimum=0.0, full=True)</code> or "
        "<code>lf.equal_area_fields(5, 20.0)</code>.</p>"
        "<p><b>Vignetting factors.</b> Each field has VDX / VDY (decentre of the pupil, as fractions of its "
        "radius), VCX / VCY (compression: 0 = none, 0.3 = 30% narrower) and <b>VAN</b>, the vignetting "
        "angle in degrees, which rotates the compressed pupil counter-clockwise about its centre so a field "
        "off the y axis can be compressed along its own direction. A ray at pupil coordinates (Px, Py) of "
        "that field is traced at R(VAN)&middot;(Px(1&minus;VCX), Py(1&minus;VCY)) + (VDX, VDY). Spot "
        "diagrams, ray fans, layouts, geometric MTF, the optimizer's ray operands and automatic "
        "semi-diameters use the factors, so every ray drawn or counted gets through the lens. Diffraction "
        "analyses (PSF, FFT MTF, wavefront), field curvature / distortion, relative illumination and the "
        "Vignetting plot trace the full pupil and let the apertures clip it, and the factors only apply "
        "at the defined field points.</p>"
        "<p><b>Set Vignetting</b> computes VDX, VDY, VCX and VCY for every field, at the primary "
        "wavelength, from the settings in the dialog. It works iteratively from the factors already in "
        "the table: starting at the centre of each field's present vignetted pupil (or the point of it "
        "nearest the centre whose ray gets through), it finds the top, bottom, left and right edges of "
        "the part of the pupil whose rays pass every surface aperture and every fixed semi-diameter "
        "(automatic semi-diameters never clip), along the axes set by each field's VAN, centres the pupil "
        "on them and then compresses it until rays all round its rim get through too. So factors that "
        "already let rays through always lead to new factors, and pressing Set Vignetting again on its "
        "own result changes nothing. Fields that are not clipped get zeros. If no ray of a field gets "
        "through at all, Set Vignetting says so and leaves that field's factors as they were. "
        "<b>Clear Vignetting</b> sets all five factors, VAN included, back to zero. "
        "Both fill the table only; OK or Apply writes it to the lens as one undo step.</p>"
        "<p>From Python: <code>lens.set_vignetting()</code> (or "
        "<code>lf.set_vignetting(lens, fields=[2, 3], angle='auto', strict=True)</code>; "
        "<code>angle='auto'</code> lines VAN up with each field's direction) and "
        "<code>lens.clear_vignetting()</code>. Zemax files bring their VDXN / VDYN / VCXN / VCYN / VANN "
        "factors with them, and the Multi-Configuration Editor's FVAN operand varies the angle.</p>"),
    "File > Wavelengths": (
        "Edit the wavelengths.",
        "Opens the System Explorer on the Wavelengths tab: wavelengths in micrometres, weights, presets "
        "(F, d, C ...) and the primary wavelength."),
    "File > Input Rays": (
        "Choose the rays drawn and traced by the ray-based analyses, and define your own rays.",
        "Sets how many rays the layout draws and in which plane, which fields and wavelengths are shown, the "
        "spot diagram pattern and size (with a small diagram of where those rays cross the pupil), ray fan and footprint sampling, and a table of user-defined rays "
        "(field and pupil coordinates) that the layout draws and the User Ray Trace report lists. Saved with "
        "the lens."),
    "File > Load Glass Catalog (AGF)": (
        "Load a Zemax AGF glass catalog so its glasses can be used.",
        "Adds the glasses of an .agf catalog file to the glass library. They then appear in the material "
        "picker and can be typed into the Material column. The catalog is remembered and loaded again every "
        "time lensforge starts (also when loaded from the material picker), until you use File > Forget "
        "Loaded Glass Catalogs. Built in are the current catalogs of SCHOTT (every preferred and inquiry "
        "glass plus common obsolete types), OHARA, HOYA, CDGM, SUMITA and HIKARI (about 1250 glasses, from "
        "each maker's own data sheet, plus obsolete OHARA and HOYA types used by older designs), and the "
        "INFRARED catalog with GERMANIUM, SILICON, ZNSE, ZNS_BROAD and AMTIR1 (type these names in the "
        "Material column; they have no visible-light index, so the picker, which lists glasses by nd and Vd, "
        "leaves them out). A glass name found in more than one catalog (F2 is both SCHOTT and CDGM) means "
        "the first catalog in that order; write CDGM:F2 for another one. An AGF file with the same name as a "
        "built-in catalog (e.g. OHARA.AGF) replaces it."),
    "File > Forget Loaded Glass Catalogs": (
        "Stop loading your AGF catalogs at start-up.",
        "Clears the list of AGF catalogs that lensforge loads at every start. Catalogs already loaded stay "
        "available until the program closes. Built-in glasses are not affected."),
    "File > Export Prescription": (
        "Save the prescription report as a text file.",
        "Writes the Prescription Data report (surface data, materials, paraxial data) to a .txt file."),
    "File > Exit": (
        "Close the program.",
        "Closes lensforge, asking to save unsaved changes first."),

    # ------------------------------------------------------------------ Edit
    "Edit > Undo": (
        "Undo the last change to the lens.",
        "Every edit (cells, surface insertion, optimisation results, scripts) is one undo step."),
    "Edit > Redo": (
        "Redo the change that was undone last.",
        "Re-applies the most recently undone edit."),
    "Edit > Undo History": (
        "Show the list of edits; click one to go back to it.",
        "Opens the Undo History panel listing every edit since the lens was opened. Clicking an entry "
        "returns the lens to that state; later entries stay available for redo."),
    "Edit > Insert Surface": (
        "Insert a new surface before the selected row.",
        "Adds a flat surface in air before the selected surface. Variables, solves and merit operands that "
        "refer to later surfaces are renumbered."),
    "Edit > Insert Surface After": (
        "Insert a new surface after the selected row.",
        "Adds a flat surface in air after the selected surface, renumbering later references."),
    "Edit > Delete Surface": (
        "Delete the selected surface, or all selected surfaces.",
        "Removes the selected surface (not the object or image). Variables and solves on it are removed; "
        "merit operands that referred to it move to the previous surface. If several rows are selected "
        "(shift-click or shift+arrow keys in the Lens Data Editor), all of those surfaces are deleted after "
        "you confirm, as with Delete Surfaces."),
    "Edit > Delete Surfaces": (
        "Delete a contiguous range of surfaces, after confirming.",
        "Opens a dialog to pick the first and last surface to delete (it starts from the rows selected in "
        "the Lens Data Editor) and previews what goes. The object and image surfaces cannot be deleted. "
        "Before anything is removed you are asked to confirm, with a list of the surfaces and of the "
        "variables and solves that are dropped. Merit operands that referred to a deleted surface move to "
        "the surface before the range, and later surface numbers are renumbered. If the stop is deleted, "
        "the surface that takes its place becomes the stop. The whole deletion is one undo step. From a "
        "script: lf.delete_surfaces(lens, first, last)."),
    "Edit > Toggle Variable": (
        "Make the selected cell a variable for optimisation, or fixed again.",
        "Marks the radius, thickness, conic or parameter in the current cell as an optimisation variable "
        "('V' marker), or removes the variable. For solves use Edit > Solve (Ctrl+Shift+L) or right-click "
        "(long-press on a touch screen) a cell."),
    "Edit > Solve": (
        "Make the selected cell a solve: computed from other cells instead of typed (pickups, formulas, ray solves).",
        "<p>Opens the Solve dialog for the selected cell. Choose the <b>Solve type</b>: <b>Fixed</b> (no "
        "solve: the cell keeps the value you type) or one of the solves the cell allows, then fill in its "
        "parameters. The same solves are on the cell's right-click menu (on an iPad or other touch screen, "
        "press and hold the cell).</p>"
        "<p><b>Thickness</b>: marginal ray height (height 0 on the last surface puts the image at paraxial "
        "focus), chief ray height, edge thickness, position (a fixed total length from an earlier surface). "
        "<b>Radius</b>: marginal or chief ray angle, F number, concentric with another surface. "
        "<b>Any numeric cell</b> (radius, thickness, conic, Par columns): <b>Pickup</b> (scale times another "
        "cell plus offset) and <b>Formula</b>. <b>Material</b>: pickup copies another surface's glass.</p>"
        "<p><b>Formula</b> is a pickup from several cells, like a spreadsheet formula. You can also type it "
        "straight into the cell: <code>=2*T2 - 0.5</code>, <code>=-(R1 + R2)/2</code>, "
        "<code>=T(s-1) * N1 / N3</code>. Cells: <code>R3</code> radius, <code>C3</code> curvature, "
        "<code>T3</code> thickness, <code>K3</code> conic, <code>SD3</code> semi-diameter, <code>N3</code> "
        "refractive index after surface 3 (primary wavelength), <code>PAR3_2</code> Par 2 of surface 3, and "
        "<code>PARAM(3, \"coefficients[1]\")</code> for any optimisation parameter. <code>R(s-1)</code>, "
        "<code>T(s+1)</code>, <code>PAR(s, 2)</code> count from the formula's own surface <code>s</code>. "
        "Maths: + - * / ** ( ), pi, sqrt, sin, cos, tan, asin, acos, atan, atan2, exp, log, log10, abs, min, "
        "max, round, floor, ceil, hypot and <code>a if condition else b</code>. The dialog shows the value "
        "the formula gives as you type. A formula cell shows '=' and its formula when you edit it; typing a "
        "plain number makes it fixed again. Inserting or deleting surfaces renumbers the surfaces a "
        "formula refers to (a formula that refers to a deleted surface is removed), and a formula that "
        "would refer to itself through other pickups is refused.</p>"
        "<p>Solves are re-applied after every edit and during optimisation, and are saved in the lens file. "
        "A solved cell has a blue background and a letter: M marginal, C chief, F F number, S concentric, "
        "E edge, T position, P pickup, = formula. Scripting: <code>opt.set_solve(lens, "
        "opt.Formula(3, 'thickness', '2*T2 - 0.5'))</code>, <code>opt.set_solve(lens, opt.Pickup(4, "
        "'radius', 2, scale=-1))</code>, <code>opt.remove_solve(lens, 3, 'thickness')</code>.</p>"),
    "Edit > Choose Material": (
        "Pick a glass or other material for the selected surface from a dialog.",
        "Opens the material picker: catalog glasses with a filterable table and an n-V glass map (hover a "
        "point for its name, or tick Show names on map to label every glass; names are off by default so "
        "they don't cover the points or the red ring of the selected glass), a model "
        "glass (index and Abbe number), or air, mirror or a constant index. Also opened by the ... button in "
        "a Material cell. Choose a maker (SCHOTT, OHARA, HOYA, CDGM, SUMITA, HIKARI or a loaded AGF "
        "catalog) or All, and filter by any part of the name: BK7 finds N-BK7, N-BK7HT and so on. Typing in "
        "a Material cell offers the same matches: any glass whose name contains what you typed, ignoring "
        "case, hyphens and spaces (bk7 offers N-BK7, nbk7 too; k9l offers H-K9L). Take a suggestion with "
        "the arrow keys and Enter, or click (tap) it; Enter on its own keeps what you typed."),
    "Edit > Surface Properties": (
        "Edit the selected surface's comment, stop, aperture and extra parameters.",
        "Opens the Surface Properties dialog: comment, stop, clear aperture or obscuration (optionally "
        "decentred) and parameters without a column (XY polynomial terms)."),
    "Edit > Quick Focus (paraxial)": (
        "Set the last thickness so the image is at paraxial focus.",
        "Adjusts the thickness before the image surface to the paraxial back focal distance."),
    "Edit > Fix Semi-Diameters at Current Values": (
        "Freeze every automatic semi-diameter at its current value.",
        "Copies the automatically computed semi-diameters into the lens as fixed values, so they stop "
        "following the rays."),
    "Edit > Make All Semi-Diameters Automatic": (
        "Let every semi-diameter follow the rays again.",
        "Clears the fixed semi-diameters so each is computed from the marginal and chief rays of all fields "
        "and wavelengths."),

    # ------------------------------------------------------------------ Analysis (window commands)
    "Analysis > Tab All Analysis Windows": (
        "Dock all analysis windows as tabs in one place.",
        "Docks every open analysis window and stacks them as tabs."),
    "Analysis > Close All Analysis Windows": (
        "Close every analysis window.",
        "Closes all open analysis windows."),

    # ------------------------------------------------------------------ Tools
    "Tools > Optimization": (
        "Optimise the variables to minimise the merit function.",
        "Runs damped least squares, orthogonal descent, Hammer, global (multi-start) or glass substitution "
        "optimisation on the lens's variables against the merit function, in the background with live "
        "progress. Stop keeps the best design found so far; the result is one undo step. Damped least squares "
        "uses derivatives and is fastest for smooth merit functions. Orthogonal descent uses no derivatives: "
        "it searches along a set of orthogonal directions that turn to follow the valley, so it copes with "
        "noisy or jumpy merit functions such as the non-sequential operands NSDP and NSRR (stray light, "
        "ghosts) or rays that clip an aperture; it meets hard constraints (negative weight) only to about "
        "1e-6, so use a solve where one must hold exactly. Cycles limits either local optimiser. Glass "
        "substitution tries the catalog glasses nearest each current glass; Glass catalog limits them to one "
        "maker (e.g. only OHARA)."),
    "Tools > Tolerancing": (
        "Estimate how manufacturing errors degrade the lens.",
        "Builds a tolerance list (radius, thickness, index, Abbe, decentre and tilt tolerances), then runs a "
        "sensitivity analysis and a Monte Carlo simulation of the chosen criterion (RMS spot, RMS wavefront, "
        "MTF) with a focus compensator."),
    "Tools > Python Shell": (
        "Script the lens in Python.",
        "Opens the Python Shell, where <code>lens</code> is the current system, <code>lf</code> the "
        "lensforge package and <code>opt</code> the optimisation module. Changes made by a script are one "
        "undo step; a script that fails leaves the lens unchanged."),
    "Tools > Merit Function Editor": (
        "Show the merit function: the targets optimisation works towards.",
        "Opens the Merit Function Editor, a table of operands (focal length, spot size, wavefront, "
        "boundaries ...) with targets and weights, their current values and contributions. The merit "
        "function is the weighted RMS of the rows' errors: sqrt(&Sigma; W (Value &minus; Target)<sup>2</sup> / "
        "&Sigma; W). A positive weight makes a row part of it, weight 0 only shows the row, a negative weight "
        "makes it a hard constraint. The wizard builds a default image-quality merit function. The "
        "<b>Merit Function Editor</b> pages of this help (the editor's Help button, or F1 in the editor) "
        "explain every column, how weights work and how to balance them, the field and pupil coordinates "
        "Hx, Hy, Px, Py used by ray operands, every operand with its parameters, and a worked example that "
        "minimises the RMS spot size (File &gt; Sample Lenses &gt; Spot Size Merit Example)."),
    "Tools > Non-Sequential > Non-Sequential Component Editor": (
        "Edit the lens's non-sequential scene: objects anywhere in 3-D, sources, detectors and the ray-trace settings.",
        "Opens the Non-Sequential Component Editor, laid out like Zemax's NSC Editor. A non-sequential scene "
        "holds <b>objects</b> placed anywhere and <b>sources</b>; rays go to whichever object they meet next, in "
        "any order, so stray light, ghosts, light pipes, prisms, reflectors and fold mirrors are traced as they "
        "really behave. The scene is kept <b>with the lens</b>: it is saved in the lens file, every edit can be "
        "undone with Edit &gt; Undo, and a lens file that has a scene opens with this editor.<br><br>"
        "<b>Columns.</b> Type (pick another type from the cell's list: position, comment and Ref are kept), "
        "Comment, <b>Ref</b> (Ref Object: the number of the object whose coordinate frame the position and "
        "tilts are given in, 0 = global; move a lens and everything placed on it moves too), X, Y, Z, "
        "Tilt X, Tilt Y, Tilt Z (degrees, about the local X, then Y, then Z axis), then Material and Coating R "
        "for objects, or Rays, Power, Wavelengths and Sampling for sources, and <b>Par 1</b>, Par 2 ... whose "
        "meaning depends on the type: select a row and the column headers show its parameter names (a cell's "
        "tooltip names it too). Grey cells do not apply to the row. A Material cell turns red when no loaded "
        "catalog has the glass; right-click it for Choose Material.<br><br>"
        "<b>Objects</b> (Add Object): Standard Lens (Radius 1, Conic 1, Thickness, Radius 2, Conic 2, "
        "Semi-diameter), Sphere (Radius), Rectangular Volume (X and Y half widths, Length), Cylinder Volume "
        "(Radius, Length: light pipes), Prism (Base length, Apex angle, X half width: 60 deg for a dispersing "
        "prism, 90 deg for a right-angle prism), Standard Surface (one mirror or absorbing surface: Radius, "
        "Conic, Semi-diameter, Inner radius), Annulus (flat ring: stops and baffles), Rectangle (fold mirror "
        "or baffle) and Detector Rectangle (half widths, X and Y pixels, Transparent 1/0). Volumes take a "
        "glass; surfaces take MIRROR or ABSORB. Coating R sets the reflectance of a volume's faces (empty = "
        "uncoated Fresnel). Volumes must not overlap, except that touching faces (a cemented doublet) pass "
        "light straight from one glass to the other.<br><br>"
        "<b>Sources</b> (Add Source): Source Point (cone half-angle), Source Ellipse and Source Rectangle "
        "(half widths, divergence half-angle; collimated at 0); all have a <b>cosine exponent</b> (0 = uniform "
        "in angle, 1 = Lambertian like an LED). Rays leave along the source's local +z axis; the power is "
        "shared evenly by its rays and wavelengths. Sampling is random (Monte Carlo, seeded) or grid.<br><br>"
        "<b>Ray Trace Control</b> (saved with the scene): <b>Split rays</b> follows both the reflected and the "
        "transmitted part at each refracting face (unpolarised Fresnel or the coating reflectance), which is "
        "what shows ghosts; split rays weaker than <b>Min. relative intensity</b> times their source ray are "
        "dropped, and no ray has more than <b>Max. segments</b>. Total internal reflection is always followed. "
        "Without splitting, rays take the transmitted path and lose the reflected power when <b>Fresnel "
        "losses</b> is on. <b>Trace</b> (F5) traces every source and shows where the power went and the "
        "statistics of each detector.<br><br>"
        "<b>Analyses</b> (buttons here, or Analysis &gt; Non-Sequential): NS Layout and NS 3D Layout draw the "
        "objects and rays, the Detector Viewer shows a detector (irradiance, true colour, cross-sections, "
        "angle space), Ray Path Analysis lists the brightest ray paths to a detector (the ghost and "
        "stray-light paths) and NS Trace Report gives the numbers. They trace the scene themselves and "
        "update after every edit; windows of one scene share the trace.<br><br>"
        "The toolbar also has New Scene, Import Scene and Export Scene (.ns.json files), From Current Lens "
        "(converts the sequential lens), Duplicate Row, Move Up and Move Down (Ctrl+Up / Ctrl+Down; Ref numbers "
        "follow the moves) and Delete Row. Examples &gt; Non-Sequential has ready-made scenes. From Python: "
        "<code>from lensforge import nonseq as ns</code>; <code>lens.nonseq = ns.from_sequential(lens)</code>; "
        "<code>r = lens.nonseq.trace(split=True)</code>; <code>r.detector(0).image('ghost')</code>; "
        "<code>r.paths(0)</code>; plots with <code>lensforge.plot.ns_layout</code>, <code>ns_layout_3d</code> "
        "and <code>ns_detector</code>."),
    "Tools > Non-Sequential > Convert Lens to Non-Sequential": (
        "Turn the current lens into its non-sequential scene and show it in the Non-Sequential Component Editor.",
        "Every glass element becomes a Standard Lens object with the exact surface shapes (aspheres, toroids "
        "and freeforms included); cemented groups become touching lenses. Mirrors become mirror surfaces (a "
        "Cassegrain primary gets the central hole the returning beam needs), the stop gets an absorbing "
        "annulus and the image surface a detector. Each field becomes a source that fills the entrance pupil: "
        "collimated for objects at infinity, a point source otherwise. Ideal (paraxial) and phase surfaces "
        "cannot be converted. The scene replaces any scene the lens had (Edit &gt; Undo brings it back); the "
        "sequential lens is not changed. Ray splitting is switched on, so the NS Layout, the Detector Viewer "
        "and the Ray Path Analysis show the ghosts; the two-reflection light matches Analysis &gt; Stray Light "
        "&gt; Ghost Image. From Python: <code>lens.nonseq = lensforge.nonseq.from_sequential(lens)</code>."),
    "Tools > Multi-Configuration Editor": (
        "Edit the configurations of the lens: zoom positions, focus settings and other states.",
        "Opens the Multi-Configuration Editor. One lens can hold several <b>configurations</b>, such as the "
        "zoom positions of a zoom lens or the far and near settings of a focusing lens. Each row of the table "
        "is an operand naming one parameter, and each column after Type, Ref and Param holds that parameter's "
        "value in one configuration. Everything not in the table is shared by all configurations."
        "<p><b>Operands</b> (Ref is a surface number, or a field or wavelength number counting from 0): "
        "THIC thickness, CRVT curvature, CONN conic, GLSS material, SDIA semi-diameter ('auto' for "
        "automatic), PARM any other surface parameter named in the Param column (an aspheric term "
        "coefficients[0], decenter_y, tilt_x, focal_length ...), STPS stop surface, APER aperture value, "
        "XFIE / YFIE field x / y, FLWT field weight, FVDX / FVDY / FVCX / FVCY / FVAN vignetting factors, WAVE "
        "wavelength, WLWT wavelength weight, PRWV primary wavelength, MOFF an unused row.</p>"
        "<p><b>Current configuration.</b> The Lens Data Editor, the status bar and every analysis show the "
        "current configuration (its column is shaded and its header starred). Double-click a configuration "
        "header, use <b>Make Current</b>, or Tools &gt; Next / Previous Configuration (Ctrl+] / Ctrl+[) to "
        "switch. Editing a controlled value in the Lens Data Editor changes the current configuration's cell, "
        "and switching back restores each configuration's own values. Every analysis window has a "
        "<b>Config</b> box: Current follows the switch, a number keeps the window on that configuration, so "
        "two spot diagrams can show two zoom positions side by side. Analysis &gt; Layout &gt; Multi-Configuration "
        "Layout draws all configurations one above the other.</p>"
        "<p><b>Editing.</b> Insert Operand adds a THIC row taking the lens's current value in every "
        "configuration; type a different operand, Ref or Param, then the values. Add Config copies the "
        "selected configuration; Rename names it; header right-click has the same commands. A row that "
        "refers to something the lens does not have (a deleted surface, a field number beyond the last) is "
        "shown red and skipped. Deleting a surface deletes the rows on it.</p>"
        "<p><b>Optimisation.</b> Select value cells and press Ctrl+Shift+V (Toggle Variable) to make them "
        "variables (shown blue with a V), for example the back focus of each zoom position. In the Merit "
        "Function Editor a <b>CONF</b> row (Parameters cfg=2) switches the configuration for the rows below "
        "it, so one merit function can cover every configuration; the Merit Function Wizard writes one group "
        "of rows per configuration. A Lens Data Editor variable on a parameter the table controls is refused "
        "when optimising, because each configuration has its own value; make the table's cells variable "
        "instead.</p>"
        "<p>The table is saved in the lens file under <code>multiconfig</code>. Scripting: "
        "<code>mc = lf.MultiConfig.create(lens, 3, names=['short', 'mid', 'long'])</code>, "
        "<code>mc.add_row(lens, 'THIC', 8, values=[59.24, 31.64, 7.21])</code>, <code>lens.set_config(2)</code>, "
        "<code>lens.config_copy(3)</code>, <code>opt.set_mc_variable(lens, row, config)</code>. Examples: the "
        "zoom lenses in Chapter 20 of the Smith examples (Figure 20.N zoom.lens.json)."),
    "Tools > Next Configuration": (
        "Show the next configuration of a multi-configuration lens.",
        "Makes the next configuration current (after the last comes the first again). The Lens Data Editor, "
        "the status bar and the analysis windows set to Current update. One undo step."),
    "Tools > Previous Configuration": (
        "Show the previous configuration of a multi-configuration lens.",
        "Makes the previous configuration current (before the first comes the last). One undo step."),
    "Tools > Variables and Solves > Make All Curvatures Variable": (
        "Make every surface curvature an optimisation variable.",
        "Adds a variable for the curvature of every refracting or reflecting surface."),
    "Tools > Variables and Solves > Make All Air Spaces Variable": (
        "Make every air thickness an optimisation variable.",
        "Adds a variable for every thickness that is followed by air."),
    "Tools > Variables and Solves > Remove All Variables": (
        "Remove every optimisation variable.",
        "Fixes all parameters again by removing every variable."),
    "Tools > Variables and Solves > Remove All Solves": (
        "Remove every solve.",
        "Removes all solves (marginal ray height, angle, pick-ups ...); the values stay as they are."),

    # ------------------------------------------------------------------ Examples
    "Examples > Browse Examples": (
        "Open one of the example lenses shipped with LensForge.",
        "The Examples menu lists every lens file in the examples folder, grouped by subfolder: the "
        "lenses written by the example scripts (Cooke triplet, scripted singlet, grating demo, spot size "
        "merit, hyperspectral imager), the non-sequential scenes (Non-Sequential: achromat ghosts, Cassegrain, ball lens, dispersing prism, retroreflecting prism, LED reflector, light pipe, periscope; they open with the Non-Sequential Component Editor), the approximate Arducam LK004 lens kit models, and the prescriptions "
        "from Warren Smith's <i>Modern Lens Design</i> by chapter (Modern Lens Design (Smith) &gt; Chapter 7 "
        "- Eyepieces and Magnifiers &gt; Figure 7.1 ...). Pick a lens to open it; hovering an entry shows "
        "its file. Browse Examples... opens the Open dialog in the examples folder instead, to search or "
        "preview the files. An example opens as an untitled copy, so File &gt; Save asks for a new file "
        "name and the example itself is never changed. You are asked to save changes to the current lens "
        "first. The menu is built from the folder when the program starts, so lens files added there "
        "appear the next time."),

    # ------------------------------------------------------------------ View
    "View > Show Toolbar": (
        "Show or hide the toolbar.",
        "Toggles the toolbar of quick buttons. Whether it is shown is remembered between sessions."),
    "View > Customize Toolbar": (
        "Choose which commands appear on the toolbar, and how buttons look.",
        "Opens a dialog listing every menu command, grouped by menu. Add commands to the toolbar, remove "
        "them, reorder them, add separators, choose icons and/or text on the buttons, or reset to the "
        "defaults. Also on the toolbar's right-click menu. Saved between sessions."),
    "View > Undo History": (
        "Show the list of edits; click one to go back to it.",
        "Opens the Undo History panel (the same as Edit > Undo History)."),

    # ------------------------------------------------------------------ Help
    "Help > Help Contents": (
        "Browse and search help for every menu command.",
        "Opens this help window: every menu command with its shortcut, icon and description."),
    "Help > What's This?": (
        "Click a button or menu item to see what it does.",
        "Turns the pointer into a question mark; click any toolbar button or other control to see its "
        "description."),
    "Help > Keyboard Shortcuts": (
        "List the keyboard shortcuts.",
        "Shows the keyboard shortcuts of the editors, menus and analyses."),
    "Help > About": (
        "Version and program information.",
        "Shows the lensforge version."),
}

#: analysis registry key -> (summary, details)
#: sampling paragraph shared by the diffraction analyses (PSF, MTF, encircled energy)
_PSF_ZOOM = (' Zoom magnifies the middle of the PSF window (2x to 64x, centred on the chief ray), or Auto '
             '(fit PSF) centres on the PSF and sizes the view from its encircled energy, so the core and the '
             'first rings fill the plot. Zoom and Log scale only redraw the plot; they never recompute the PSF. You can also zoom '
             'with the mouse: the wheel zooms about the cursor and dragging a box zooms to it (in the desktop '
             'app use the magnifier button of the plot toolbar for the box; Home goes back). In the web app '
             'drag directly on the plot, and double-click or Reset Zoom goes back to the Zoom setting. A mouse '
             'zoom stays in place when the lens changes and the PSF is recomputed. From Python use '
             'lensforge.plot.psf(result, zoom=4) or zoom="auto". Zooming shows the PSF pixels as they are; for a '
             'finer image at high zoom set a smaller PSF pixel size.')

_SAMPLING = (' Pupil sampling is the grid across the exit pupil: more points follow strong aberrations more '
             'accurately and push the edge of the PSF window further out. Image sampling is the size of the '
             'padded FFT image grid (Auto = 2 x pupil). The PSF pixel stays at Nyquist, so a larger image '
             'grid makes the PSF window wider and the MTF frequency step finer (step = cutoff / (image grid /'
             ' 2)); the pupil grid is raised automatically when the wider window needs it. Large grids are '
             'slow, Huygens most of all: a Huygens run that would take more than about five minutes is '
             'refused with a message; use the FFT method for fine sampling.')

ANALYSIS_HELP = {
    "ns_layout": ("Objects and traced rays of the non-sequential scene, in the YZ or XZ plane.",
                  "Traces the lens's non-sequential scene (Tools &gt; Non-Sequential &gt; Non-Sequential Component "
                  "Editor) with its Ray Trace Control settings and draws each object's section and the ray "
                  "segments, with the object numbers. <b>Color by</b> reflections (blue direct, green one "
                  "Fresnel reflection, red two or more: ghosts), source, wavelength or power. <b>Rays</b> keeps "
                  "only direct light, ghosts or an exact number of reflections. <b>Path</b> k draws only the "
                  "k-th brightest ray path to the <b>Detector</b> (numbered as in the Ray Path Analysis), which "
                  "shows exactly where a ghost goes. At most <b>Segments drawn</b> are drawn (whole ray paths, "
                  "picked within each reflection order so faint ghosts stay visible). Mouse wheel zooms. From "
                  "Python: <code>lensforge.plot.ns_layout(lens.nonseq.trace(), plane='y')</code>."),
    "ns_layout_3d": ("3-D wireframe of the non-sequential scene and its rays.",
                     "Draws every object as a wireframe (both sections plus rims and edges) and the traced ray "
                     "segments in 3-D, z across. Elevation and Azimuth turn the view (in the desktop app you can "
                     "also drag the plot to rotate it). Color by, Rays and Path work as in the NS Layout. From "
                     "Python: <code>lensforge.plot.ns_layout_3d(result)</code>."),
    "ns_detector": ("What a detector of the non-sequential scene received.",
                    "The Detector Viewer: <b>Irradiance</b> (power per area in each pixel), <b>True color</b> (the "
                    "pixels coloured by the wavelengths that reached them: dispersion), <b>Cross-section</b> X or "
                    "Y (the row through y = 0 or the column through x = 0) and <b>Angle space</b> (power against "
                    "the direction cosines of the arriving rays: the radiant intensity pattern). Detector is "
                    "the object number of the detector (0 = the first one); Rays keeps all light, direct light, "
                    "ghosts or an exact number of reflections; Source picks one source (0 = all); Log scale "
                    "shows faint ghosts and stray light. The title gives the total power. The NS Trace Report "
                    "lists hits, power, peak irradiance, centroid and RMS radius. From Python: "
                    "<code>r.detector(0).image('ghost')</code>, <code>lensforge.plot.ns_detector(r, 0)</code>."),
    "ns_paths": ("The brightest ray paths to a detector: ghost and stray-light analysis.",
                 "Groups every ray that reached the detector (0 = every detector) by the sequence of objects, "
                 "faces and events it went through and lists the paths by power, with their share of the "
                 "detector power, the number of rays and of Fresnel reflections. Events: T transmitted, R "
                 "Fresnel (partial) reflection, X total internal reflection, M mirror, D detected, P passed a "
                 "transparent detector; for example <i>S -&gt; 1 front T -&gt; 2 back R -&gt; 1 front R -&gt; "
                 "... -&gt; 4 D</i> is a ghost that reflected at the back of object 2 and then at the front of "
                 "object 1. Turn on Split rays in the editor's Ray Trace Control to see ghosts. Set Path in the "
                 "NS Layout to a path's number to draw it. From Python: <code>r.paths(det)</code>."),
    "ns_report": ("Numbers of the non-sequential trace: where the power went and what each detector got.",
                  "Rays launched and traced (with split rays), the ray-trace settings, the power that was "
                  "absorbed, detected, escaped or stopped, and for each detector the hits, power, peak "
                  "irradiance, centroid and RMS radius of all light, direct light, one-reflection light and "
                  "ghosts. From Python: <code>print(lens.nonseq.trace().summary())</code>."),
    "ghost_focus": ("Table of every two-bounce ghost: where it focuses, how big and how bright it is.",
                    "The Ghost Focus Generator. For every pair of refracting surfaces i > j it follows the light "
                    "that reflects at surface i, goes back, reflects again at surface j and then reaches the "
                    "image. Each row gives the reflectances R_i and R_j (uncoated Fresnel at normal incidence, "
                    "or the coating reflectance you set), the ghost power R = R_i R_j, the paraxial ghost focus "
                    "relative to the image surface (negative = in front of it), the ghost beam radius on the "
                    "image and its F-number, and the irradiance ratio: an estimate of the ghost's peak "
                    "irradiance relative to the peak of the diffraction-limited image, used to rank ghosts. Real "
                    "rays give the RMS radius of the ghost footprint and the fraction of ghost rays that get "
                    "through clear apertures. Set an image surface reflectance above 0 to include ghosts off "
                    "the detector. Groups with coordinate breaks, mirrors, ideal or phase surfaces between the "
                    "two reflections are skipped (use the non-sequential tracer for those). From Python: "
                    "<code>lf.format_ghost_table(lf.ghost_focus(lens, coating=0.005))</code>; "
                    "<code>lf.ghost_system(lens, i, j)</code> returns the unfolded lens of one ghost for any "
                    "other analysis."),
    "ghost_image": ("Irradiance on the image surface from all ghosts of one field point.",
                    "Traces a grid of rays across the entrance pupil along every two-bounce ghost path and bins "
                    "their power on the image surface. Each ray carries the angle-dependent unpolarised Fresnel "
                    "reflectances at its two reflections (or the coating reflectance) and the transmittances of "
                    "the other surfaces. Show the ghosts only, the nominal image, or both; a log colour scale "
                    "makes faint ghosts visible. The title gives the fraction of the beam power that ends up "
                    "in ghosts. From Python: <code>lf.ghost_image(lens, field=1)</code>, plotted with "
                    "<code>lensforge.plot.ghost_image</code>."),
    "ghost_layout": ("Cross-section of the lens with the rays of one ghost.",
                     "Draws the lens and the path of the ghost that reflects at surface i and then at surface j "
                     "(the brightest ghost when both are 0), so you can see where it goes and which surfaces it "
                     "uses. From Python: <code>lf.ghost_layout(lens, i, j)</code>."),
    "mc_layout": ("2D layouts of every configuration, one above the other.",
                  "Draws the 2D layout of each configuration of a multi-configuration lens (or one, chosen in "
                  "Show) on a common z axis, titled with the configuration's name and focal length, so the "
                  "moving groups of a zoom lens can be compared. Ray sampling comes from Input Rays. A lens "
                  "with one configuration shows a single layout."),
    "layout": ("2D cross-section of the lens with traced rays.",
               "Draws the surfaces and rays in the YZ or XZ plane, coloured by field (or by wavelength when one "
               "field is shown). The number of rays, plane, fields and wavelengths are set in Input Rays; user "
               "rays are drawn dashed. Coordinate breaks are followed exactly: every surface after a "
               "decentre or tilt (either order flag) is drawn where it really is, so fold mirrors, tilted or "
               "decentred elements, wedges and tilted image planes appear as they are, and the rays meet the "
               "drawn surfaces. The breaks themselves are not drawn, and rays run straight from the surface "
               "before a break to the one after it. Each surface is cut along the plotted plane (YZ or XZ); "
               "a fold out of that plane shows edge-on, so switch the plane in Input Rays to see it. Lens "
               "edges are joined across breaks inside the glass. From Python: <code>lf.layout(lens)</code>."),
    "footprint": ("Where the rays land on a chosen surface.",
                  "Plots the ray intercepts of every field on one surface, with its semi-diameter, to check "
                  "clear apertures and vignetting."),
    "sag": ("Sag profile of a surface.",
            "Plots the sag (z) of one surface against height, or its departure from the best-fit sphere."),
    "ray_fan": ("Transverse ray aberration against pupil coordinate.",
                "Plots ey against py (tangential) and ex against px (sagittal) for each field and wavelength. "
                "Ray errors are in lens units (shown in the plot titles); pupil coordinates are normalised."),
    "opd_fan": ("Optical path difference against pupil coordinate.",
                "Plots the wavefront error in waves (at each wavelength) along the tangential and sagittal "
                "normalised pupil axes."),
    "spot": ("Spot diagram: ray intercepts on the image for each field.",
             "Shows ray intercepts per field and wavelength with RMS and GEO radii and the Airy disc; pattern "
             "and density are set in Input Rays."),
    "through_focus_spot": ("Spot diagrams through focus.",
                           "Spot diagrams at several defocus positions either side of the image plane."),
    "rms_vs_field": ("RMS spot radius against field.",
                     "Plots the RMS spot radius (polychromatic and per wavelength) across the field."),
    "wavefront": ("Wavefront error map over the pupil.",
                  "False-colour map of the OPD over the exit pupil with P-V and RMS, optionally with tilt removed."),
    "interferogram": ("Simulated interferogram of the wavefront.",
                      "Shows the wavefront as interference fringes, with adjustable X and Y tilt fringes."),
    "zernike": ("Zernike fit of the wavefront (plot).",
                "Bar chart of the Fringe or Standard Zernike coefficients fitted to the wavefront."),
    "zernike_text": ("Zernike fit of the wavefront (table).",
                     "Lists the Zernike coefficients with their names, P-V and RMS."),
    "psf": ("Point spread function image.",
            "FFT or Huygens PSF of one field, on a linear or log scale." + _SAMPLING +
            " PSF pixel size (in um) samples the PSF more finely than Nyquist; 0 keeps Nyquist." + _PSF_ZOOM),
    "psf_cross": ("Cross sections through the PSF.",
                  "X and Y cross-sections through the point spread function." + _SAMPLING +
                  " PSF pixel size (in um) samples the PSF more finely than Nyquist; 0 keeps Nyquist." + _PSF_ZOOM),
    "mtf": ("Modulation transfer function.",
            "Tangential and sagittal MTF against spatial frequency for each field, with the diffraction limit "
            "(FFT, Huygens or geometric). Spatial frequency is in cycles per lens unit (cycles/mm for a "
            "lens in mm, cycles/in for one in inches)." + _SAMPLING +
            " For the geometric method the pupil sampling is the ray grid. Input Rays does not affect the MTF."),
    "through_focus_mtf": ("MTF through focus at one frequency.",
                          "MTF at a chosen spatial frequency (cycles per lens unit) against defocus, to find the best "
                          "focus and depth."
                          + _SAMPLING),
    "mtf_vs_field": ("MTF against field.",
                     "Tangential and sagittal MTF at chosen frequencies (cycles per lens unit) across the field." + _SAMPLING),
    "encircled_energy": ("Fraction of energy inside a radius.",
                         "Encircled, ensquared or line energy against distance for each field, from diffraction or geometric rays."
                         + _SAMPLING + " For the geometric method the pupil sampling is the ray grid."),
    "field_curvature": ("Field curvature and distortion.",
                        "Tangential and sagittal focus shift against field, and percentage distortion "
                        "(F-tan(theta) or F-theta)."),
    "grid_distortion": ("Distorted image of a regular grid.",
                        "Overlays the real image of a grid of field points on the ideal grid."),
    "lateral_color": ("Lateral colour against field.",
                      "Image height difference between wavelengths across the field."),
    "longitudinal": ("Longitudinal aberration against pupil height.",
                     "Axial focus position of each pupil zone, for each wavelength (spherical aberration and "
                     "axial colour)."),
    "focal_shift": ("Chromatic focal shift.",
                    "Paraxial focus position against wavelength."),
    "seidel": ("Seidel aberrations per surface (chart).",
               "Bar chart of the third-order spherical, coma, astigmatism, field curvature, distortion and "
               "colour contributions of each surface."),
    "seidel_text": ("Seidel aberration coefficients (table).",
                    "Lists the Seidel sums per surface and in total."),
    "pupil_aberration": ("Pupil aberration.",
                         "Error of the real chief ray at the stop against field, compared with paraxial."),
    "relative_illumination": ("Relative illumination against field.",
                              "Image irradiance relative to the axis, including pupil distortion and vignetting."),
    "vignetting": ("Vignetting against field.",
                   "Fraction of the pupil that reaches the image for each field."),
    "polarization_pupil": ("Polarization state over the pupil.",
                           "Polarization ellipses over the exit pupil for a chosen input polarization."),
    "transmission": ("Transmission of the lens.",
                     "Fraction of the light transmitted through the lens for each field."),
    "prescription": ("Prescription report.",
                     "Text report of surface data, materials, indices and first-order properties."),
    "system_report": ("System data report.",
                      "Aperture, fields, wavelengths, EFL, F-number, pupils and other first-order data."),
    "ray_trace": ("Trace one ray and list it surface by surface.",
                  "Lists the coordinates, direction cosines and path of a single ray at every surface."),
    "user_rays": ("Trace the rays defined in Input Rays.",
                  "Lists the image intercepts and errors of the user-defined rays from File > Input Rays."),
    "cardinal_points": ("Focal points, principal planes and nodal points.",
                        "First-order cardinal points of the lens, measured from the first and last surfaces."),
    "dispersion": ("Refractive index against wavelength of a material in the lens.",
                   "Plots the dispersion curve of the material after a chosen surface."),
}

#: sample lens name -> summary
SAMPLE_HELP = {
    "Singlet": "Load a simple N-BK7 singlet lens.",
    "Cemented Achromat": "Load a cemented achromatic doublet.",
    "Parabolic Mirror": "Load a parabolic mirror telescope.",
    "Classical Cassegrain": "Load a classical Cassegrain telescope (two mirrors).",
    "Cooke Triplet (optimised)": "Load the Cooke triplet optimised by the example script.",
    "Scripted Singlet": "Load the singlet built and optimised by the scripting example.",
    "Diffraction Grating Demo": "Load a transmission grating followed by a lens, showing the dispersed orders.",
    "Spot Size Merit Example": "Load the Merit Function Editor help's example: a Cooke triplet with variables and "
                               "a merit function that minimises the RMS spot size (run Tools > Optimization).",
}

SAMPLE_PREFIX = "File > Sample Lenses > "
ANALYSIS_PREFIX = "Analysis > "


def analysis_key(item_id: str) -> Optional[str]:
    """Registry key of an "Analysis > group > title" menu path."""
    for k, spec in REGISTRY.items():
        if item_id == f"{ANALYSIS_PREFIX}{spec.group} > {spec.title}":
            return k
    return None


def lookup(item_id: str) -> Optional[Tuple[str, str]]:
    """(summary, details) for a menu path, or None when the command has no help yet."""
    if item_id in HELP:
        return HELP[item_id]
    if item_id.startswith(SAMPLE_PREFIX):
        s = SAMPLE_HELP.get(item_id[len(SAMPLE_PREFIX):])
        return (s, s + " It replaces the current lens (you are asked to save changes).") if s else None
    k = analysis_key(item_id)
    if k is not None and k in ANALYSIS_HELP:
        summary, details = ANALYSIS_HELP[k]
        return summary, details + (" Opens in a dockable window that updates when the lens changes. If this "
                                   "analysis is already open, its window is brought to the front instead. "
                                   "Drag the divider beside a docked window to resize it: in a narrow window "
                                   "its settings wrap onto more rows, and the Lens Data Editor always keeps "
                                   "a minimum size, so docked windows never cover it.")
    return None


OVERVIEW = """
<h2>lensforge help</h2>
<p>lensforge is a sequential optical design program. The <b>Lens Data Editor</b> in the middle of the
window is the lens: one row per surface, from the object to the image. Type radii, thicknesses and
materials into the cells; right-click a cell (press and hold on a touch screen) for variables, solves and
surface types, or use Edit &gt; Solve. Type <code>=2*T2</code> in a cell to make it a formula of other
cells.</p>
<p>The menus hold every command:</p>
<ul>
<li><b>File</b>: open, save, insert lenses from files, system settings (aperture, fields, wavelengths),
input rays, sample lenses.</li>
<li><b>Edit</b>: undo/redo and surface editing.</li>
<li><b>Analysis</b>: plots and reports, each in a window that updates as you edit. Choosing an
analysis that is already open brings its window to the front.</li>
<li><b>Tools</b>: optimisation, tolerancing, merit function and the Python shell. The <b>Merit Function
Editor</b> pages below the Overview explain merit functions in detail, with a worked example.</li>
<li><b>Examples</b>: every example lens shipped with the program, by folder (script output,
Arducam lens kit, Smith's <i>Modern Lens Design</i> by chapter); each opens as an untitled copy.</li>
<li><b>View</b>: the toolbar (View &gt; Customize Toolbar puts any command on it).</li>
</ul>
<p>Pick a command on the left to read about it, or type in the filter box. Hovering a toolbar button
shows what it does; Help &gt; What's This? explains any button you click.</p>
"""
