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
        "wavelengths, aperture). Imported .zmx files are saved as new JSON files."),
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
        "Opens the System Explorer: aperture type and value, field type and field points, wavelengths and "
        "weights with the primary wavelength, units, ray aiming and notes."),
    "File > Fields": (
        "Edit the field points.",
        "Opens the System Explorer on the Fields tab: field type (angle, object height, image height) and "
        "the x/y field points with weights."),
    "File > Wavelengths": (
        "Edit the wavelengths.",
        "Opens the System Explorer on the Wavelengths tab: wavelengths in micrometres, weights, presets "
        "(F, d, C ...) and the primary wavelength."),
    "File > Input Rays": (
        "Choose the rays drawn and traced by the ray-based analyses, and define your own rays.",
        "Sets how many rays the layout draws and in which plane, which fields and wavelengths are shown, the "
        "spot diagram pattern and size, ray fan and footprint sampling, and a table of user-defined rays "
        "(field and pupil coordinates) that the layout draws and the User Ray Trace report lists. Saved with "
        "the lens."),
    "File > Load Glass Catalog (AGF)": (
        "Load a Zemax AGF glass catalog so its glasses can be used.",
        "Adds the glasses of an .agf catalog file to the glass library. They then appear in the material "
        "picker and can be typed into the Material column. The catalog is remembered and loaded again every "
        "time lensforge starts (also when loaded from the material picker), until you use File > Forget "
        "Loaded Glass Catalogs. The built-in SCHOTT catalog already holds every current SCHOTT glass "
        "(preferred and inquiry) plus common obsolete types."),
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
        "('V' marker), or removes the variable. Right-click a cell for solves."),
    "Edit > Choose Material": (
        "Pick a glass or other material for the selected surface from a dialog.",
        "Opens the material picker: catalog glasses with a filterable table and an n-V glass map, a model "
        "glass (index and Abbe number), or air, mirror or a constant index. Also opened by the ... button in "
        "a Material cell."),
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
        "Runs damped least squares, Hammer, global (multi-start) or glass substitution optimisation on the "
        "lens's variables against the merit function, in the background with live progress. Stop keeps the "
        "best design found so far; the result is one undo step."),
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
ANALYSIS_HELP = {
    "layout": ("2D cross-section of the lens with traced rays.",
               "Draws the surfaces and rays in the YZ or XZ plane, coloured by field (or by wavelength when one "
               "field is shown). The number of rays, plane, fields and wavelengths are set in Input Rays; user "
               "rays are drawn dashed."),
    "footprint": ("Where the rays land on a chosen surface.",
                  "Plots the ray intercepts of every field on one surface, with its semi-diameter, to check "
                  "clear apertures and vignetting."),
    "sag": ("Sag profile of a surface.",
            "Plots the sag (z) of one surface against height, or its departure from the best-fit sphere."),
    "ray_fan": ("Transverse ray aberration against pupil coordinate.",
                "Plots ey against py (tangential) and ex against px (sagittal) for each field and wavelength."),
    "opd_fan": ("Optical path difference against pupil coordinate.",
                "Plots the wavefront error in waves along the tangential and sagittal pupil axes."),
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
            "FFT or Huygens PSF of one field, on a linear or log scale."),
    "psf_cross": ("Cross sections through the PSF.",
                  "X and Y cross-sections through the point spread function."),
    "mtf": ("Modulation transfer function.",
            "Tangential and sagittal MTF against spatial frequency for each field, with the diffraction limit "
            "(FFT, Huygens or geometric)."),
    "through_focus_mtf": ("MTF through focus at one frequency.",
                          "MTF at a chosen spatial frequency against defocus, to find the best focus and depth."),
    "mtf_vs_field": ("MTF against field.",
                     "Tangential and sagittal MTF at chosen frequencies across the field."),
    "encircled_energy": ("Fraction of energy inside a radius.",
                         "Encircled, ensquared or line energy against distance for each field, from diffraction or geometric rays."),
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
                                   "analysis is already open, its window is brought to the front instead.")
    return None


OVERVIEW = """
<h2>lensforge help</h2>
<p>lensforge is a sequential optical design program. The <b>Lens Data Editor</b> in the middle of the
window is the lens: one row per surface, from the object to the image. Type radii, thicknesses and
materials into the cells; right-click a cell for variables, solves and surface types.</p>
<p>The menus hold every command:</p>
<ul>
<li><b>File</b>: open, save, insert lenses from files, system settings (aperture, fields, wavelengths),
input rays, sample lenses.</li>
<li><b>Edit</b>: undo/redo and surface editing.</li>
<li><b>Analysis</b>: plots and reports, each in a window that updates as you edit. Choosing an
analysis that is already open brings its window to the front.</li>
<li><b>Tools</b>: optimisation, tolerancing, merit function and the Python shell. The <b>Merit Function
Editor</b> pages below the Overview explain merit functions in detail, with a worked example.</li>
<li><b>View</b>: the toolbar (View &gt; Customize Toolbar puts any command on it).</li>
</ul>
<p>Pick a command on the left to read about it, or type in the filter box. Hovering a toolbar button
shows what it does; Help &gt; What's This? explains any button you click.</p>
"""
