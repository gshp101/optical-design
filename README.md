# lensforge

A sequential optical design toolkit in the spirit of Zemax OpticStudio, written in
pure Python + NumPy so the same core runs as a standalone program, inside a web
tool (server-side, or in the browser via Pyodide), and from user scripts.

Status: **v0.3**: lens data model, materials, paraxial optics, the real ray
tracer, a full analysis layer, and optimisation + tolerancing (merit function
editor, solves, damped least squares, global search / hammer, glass
substitution, sensitivity and Monte Carlo tolerancing); see the tables below.

## Quick start

```bash
pip install numpy pytest matplotlib # numpy is the only hard dependency; matplotlib only for lensforge.plot
python -m pytest tests              # 275 tests (84 for the Qt app, offscreen), ~70 s
python examples/scripting_demo.py   # build, analyse and run a scripted design study
python examples/optimization_demo.py # Cooke triplet: optimise, hammer, glass substitution, tolerancing (~2 min)
python examples/spot_size_merit.py  # hand-built merit function minimising RMS spot size (the help's example)
python examples/analysis_demo.py    # report + 16-panel plot gallery (examples/output/analysis_gallery.png)
python examples/point_source_demo.py # rays from 3-D object points to the image plane
python -m lensforge some_lens.zmx [--report]  # prescription, first-order data, spots [full analysis report]
```

```python
import lensforge as lf

lens = lf.OpticalSystem("Singlet")
lens.set_aperture("EPD", 20)
lens.set_fields([0, 5, 10])                       # degrees
lens.set_wavelengths([0.4861, 0.5876, 0.6563], primary=1)
lens.add_surface(radius=52.6, thickness=5, material="N-BK7", stop=True)
lens.add_surface(radius=-383, thickness=88)

print(lens.paraxial())                            # EFL, BFL, pupils, F/#, ...
res = lens.trace(hx=0, hy=1, px=[0, 0.5, 1], py=0)  # normalised field/pupil coords
spot = lf.spot_diagram(lens, field=2)
fan = lf.ray_fan(lens, field=1)
w = lf.wavefront(lens, field=0)                   # OPD map in waves
lf.save(lens, "singlet.lens.json")

# analyses return dicts of NumPy arrays; plotting is separate
m = lf.fft_mtf(lens, field=2)                     # m["freq"], m["tangential"], m["sagittal"], ...
print(lf.seidel_table(lens), lf.strehl(lens, 0), lf.distortion(lens, 1.0))
import lensforge.plot as P; P.mtf(m)              # optional matplotlib helpers

from lensforge.analysis import metrics            # scalar operands for optimisation / tolerancing
metrics.evaluate(lens, "MTFT", 50, field=1)
metrics.sensitivity(lens, [(1, "curvature"), (2, "thickness")], metrics.rms_spot)
```

## Desktop application (Qt)

`lensforge_qt` is a Zemax-style desktop front end (PySide6 + matplotlib) over the same public API;
the `lensforge` core has no UI code. Screenshots: `examples/output/qt/`.

```bash
pip install PySide6 matplotlib                      # pytest-qt too, for its tests
python -m lensforge_qt                              # empty lens
python -m lensforge_qt examples/output/cooke_triplet.lens.json --analyses layout,spot,mtf
python -m lensforge_qt --sample achromat            # singlet, achromat, parabola, cassegrain, triplet
```

| Window | What it does |
|---|---|
| Menus | File (New, Open, Open Recent, Save, Save As, Insert Lens, Inspect Lens File, System Explorer, Fields, Wavelengths, Input Rays, samples, AGF catalogs), Edit (Undo, Redo, surface editing), Analysis (all plots and reports), Tools (Optimization, Tolerancing, Python Shell, Merit Function Editor), View (toolbar on/off, Customize Toolbar), Help (Help Contents, What's This?, Keyboard Shortcuts). The menu bar is inside the window on every platform, macOS included. |
| Lens Data Editor (centre) | Spreadsheet of surfaces: type (combo), comment, radius, thickness, material (glass name completion, `nd,vd` model glass, index, MIRROR, or the material picker: "..." button in the cell, right-click or Ctrl+G opens a dialog with the catalog table, a clickable glass map, model glass and air/mirror/constant index), semi-diameter (automatic in grey, typed = fixed `U`), conic, Par 1-8 with headers per surface type (asphere terms, toroid radius X, coordinate-break decentres/tilts, paraxial focal length, binary-2 terms, grating lines/um and order). Cell markers: `V` variable, `M`/`C`/`F`/`E`/`T`/`S`/`P` solves. Right-click: make variable, solves (marginal/chief ray height and angle, F/#, concentric, edge thickness, position, pickup), surface type, stop, surface properties (apertures, obscurations, XY-polynomial terms). Insert / Ctrl+Insert / Shift+Delete insert and delete surfaces, renumbering variables, solves and merit operands. |
| Input Rays (F5) | Rays drawn in the layout (rays per fan, fan plane, fields, wavelengths), pupil sampling of spot diagrams, fans and footprints, and user-defined rays (Hx, Hy, Px, Py, wavelength) drawn in red on the layout and listed in Analysis > Reports > User Ray Trace. Saved in the lens file's `"ui"` section and undoable. |
| System Explorer (F2-F4) | Aperture type/value, ray aiming, field type and field table (weights, vignetting factors, equal-area helper), wavelengths with presets and primary, units, title, notes. |
| Merit Function Editor (F6) | Operand spreadsheet (type with completion, `name=value` parameters, bound, target, weight, live value and % contribution computed in the background), wizard (default spot / wavefront / MTF merit with glass/air boundaries), searchable operand list, column and operand tooltips. Its help pages (Help button or F1 in the editor) cover the columns, the merit function formula, weights, Hx/Hy/Px/Py ray coordinates, a reference of every operand generated from the code, and a worked spot-size example (File > Sample Lenses > Spot Size Merit Example). |
| Toolbar | Hidden by default. Every menu command has its own icon and a tooltip saying what it does (name, shortcut, one-line description). View > Customize Toolbar (or right-click the toolbar) opens a dialog listing every menu command by menu; add, remove, reorder and separate buttons, choose icons only / icons with text / text only, or reset to the defaults. The layout, button style and whether the toolbar is shown are saved between sessions. |
| Insert Lens (Ctrl+I) | File > Insert Lens copies a range of surfaces from a `.json` or `.zmx` file into the current lens before a chosen surface, with a scale factor (all lengths, aspheric/freeform/phase terms) and an option to reverse the surface order (curvatures and sag terms change sign, thicknesses and media shift, coordinate breaks are inverted). "Copy semi-diameters" brings in the lens's semi-diameters as fixed values (automatic ones computed in the source lens), otherwise the inserted surfaces are automatic. Preview with the group's focal length; one undo step. Scripting: `lf.insert_lens(lens, 'file.json', at=3, scale=0.5, reverse=True, copy_semi_diameters=True)`, plus `lf.scale_surface`, `lf.scale_system`, `lf.reverse_surfaces`, `lf.lens_surfaces`. |
| Delete Surfaces (Ctrl+Shift+Delete) | Edit > Delete Surfaces deletes a contiguous range of surfaces chosen by first and last surface (prefilled from the rows selected in the Lens Data Editor, where shift-click selects a range; Shift+Delete on a multi-row selection does the same). The object and image surfaces cannot be deleted. A confirmation prompt lists the surfaces and the variables and solves that will be dropped; merit operands on deleted surfaces move to the surface before the range and later references are renumbered. One undo step. Scripting: `lf.delete_surfaces(lens, 2, 4)`. |
| Inspect Lens File (Ctrl+Shift+O) | File > Inspect Lens File shows the System Report of a `.json` or `.zmx` file in its own non-modal window without changing the current lens; open several to compare designs. Copy, Save, or Open in Editor. Scripting: `lf.system_report(lf.load('file.json'))`. |
| Help (F1) | Help > Help Contents is a searchable browser with a page for every menu command (icon, menu path, shortcut, description) and every menu. Status-bar tips, tooltips and Help > What's This? (Shift+F1) use the same text; Help > Keyboard Shortcuts is generated from the menus. |
| Analysis windows | 36 dockable windows (Analysis menu): layout, footprint, sag; ray / OPD fans, spot, through-focus spot, RMS vs field; wavefront, interferogram, Zernike; FFT/Huygens PSF and cross-section; FFT/Huygens/geometric MTF, through-focus MTF, MTF vs field, encircled energy; field curvature/distortion, grid distortion, lateral colour, longitudinal aberration, chromatic focal shift, Seidel diagram and coefficients, pupil aberration; relative illumination, vignetting, polarisation pupil map, transmission; prescription, system report, single ray trace, cardinal points, glass dispersion, user ray trace. Choosing an analysis that is already open brings its window to the front. Each has its own settings bar, matplotlib zoom/pan/save toolbar, and recomputes in a worker thread when the lens changes. |
| Diffractive surfaces | Diffraction Grating (`DGRATING`: linear grating on a conic surface, lines/um and order, transmissive or reflective, `n'M' = nM + m lambda T`; follow it with a coordinate break onto the diffracted order, see `examples/grating_demo.lens.json`) and Binary 2 (rotationally symmetric diffractive phase). |
| Optimization (Ctrl+U) | Damped least squares, hammer, global search, glass substitution, on a copy of the lens in the background with live merit plot and Stop (keeps the best design so far); the result is one undo step. |
| Tolerancing (Ctrl+Shift+T) | Tolerance wizard, editable tolerance table, criterion (RMS spot / wavefront / MTF / merit function), compensator, sensitivity analysis with worst offenders, Monte Carlo with histogram and "load worst lens". |
| Python script (F8) | Runs Python against the open lens (`lens`, `lf`, `opt`, `np`); changes become one undo step, a failing script leaves the lens unchanged. |

Also: undo/redo of every edit (Edit > Undo History), open `.json` / import `.zmx`, save, recent files,
sample lenses, AGF catalog loading, prescription export, quick focus, fix/auto semi-diameters,
vary all curvatures / air spaces. `lensforge_qt/edits.py` holds the Qt-free editing helpers (cell
parsing, surface type changes, insert/delete with renumbering) so a web front end can reuse them.

**Adding a menu command:** write its help in `lensforge_qt/help_text.py` (summary + description) and draw
its icon in `lensforge_qt/icons.py` (24 x 24 SVG). The Qt tests fail for a command without help or an icon,
for help or icons left behind by a removed command, for two commands sharing an icon, and for clashing
shortcuts, so the help cannot fall behind the menus. A new merit function operand must be filed in a group
in `OPERAND_GROUPS` (`lensforge_qt/mfe_help.py`); its reference entry is generated from the code.

## Analyses

All in `lensforge.analysis` (also exported at top level as `lf.<name>`). Each returns a dict;
plotting helpers with the same names are in `lensforge.plot`.

| Zemax analysis | lensforge |
|---|---|
| Ray fan, OPD fan, wavefront map, spot diagram | `ray_fan`, `opd_fan`, `wavefront`, `spot_diagram` |
| Single ray trace from an arbitrary 3-D source point (any pupil pattern) | `point_source_trace` (see below) |
| Through-focus / full-field spot | `through_focus_spot`, `full_field_spot` |
| FFT PSF, Huygens PSF, PSF cross-section | `fft_psf`, `huygens_psf`, `psf_cross_section` |
| Strehl ratio | `strehl(method="fft" / "huygens" / "marechal")` |
| FFT / Huygens / geometric MTF (+ diffraction limit) | `fft_mtf`, `huygens_mtf`, `geometric_mtf`, `mtf`, `mtf_at`, `diffraction_limited_mtf` |
| Through-focus MTF, MTF vs field | `through_focus_mtf`, `mtf_vs_field` |
| Diffraction / geometric encircled, ensquared, line (x, y) energy | `diffraction_energy`, `geometric_energy`, `radius_for_energy` |
| Seidel coefficients and diagram (S1..S5, CL, CT; W040..W111; transverse; longitudinal) | `seidel`, `seidel_table` |
| Zernike Fringe and Standard coefficients | `zernike_coefficients`, `fit_zernike`, `evaluate_zernike` |
| Field curvature / distortion (f-tan and f-theta), grid distortion | `field_curvature`, `distortion`, `grid_distortion` |
| Lateral colour, longitudinal aberration, chromatic focal shift, pupil aberration | `lateral_color`, `longitudinal_aberration`, `chromatic_focal_shift`, `pupil_aberration` |
| Relative illumination (+ effective F/#), vignetting plot | `relative_illumination`, `vignetting` |
| 2-D/3-D layout data, footprint diagram, surface sag and best-fit-sphere departure | `layout`, `surface_profiles`, `footprint`, `surface_sag` |
| Interferogram, image simulation (isoplanatic) | `interferogram`, `image_simulation` |
| Polarisation ray trace, pupil map, transmission, diattenuation (Fresnel, uncoated) | `polarization_trace`, `polarization_pupil_map`, `transmission`, `diattenuation` |
| Cardinal points, single ray trace, dispersion, system report | `cardinal_points`, `ray_trace_table`, `dispersion`, `system_report` |
| Merit operands, sensitivities, universal plot | `metrics.OPERANDS` / `evaluate`, `sensitivity`, `sweep` |

Diffraction analyses share one pupil sampler (`pupil_function`): real-ray OPD on an n x n
grid, vignetting as zero amplitude and image-space NA fitted from real ray directions (so
off-axis F/# changes are included). The FFT PSF uses a matrix Fourier transform so all
wavelengths land on one grid; PSFs are in fraction of energy per pixel and every PSF carries
its aberration-free counterpart, which gives the Strehl ratio and diffraction-limit curves.
Encircled/ensquared energies are integrated exactly through the OTF (no pixelation error).
If an aberrated PSF does not fit on the grid, the result's `warnings` says to raise `pupil_n`.

### Point-source trace

`point_source_trace` traces rays from one source point anywhere in object space, given as
(x, y, z), through a pupil sampling pattern and returns where each ray lands on the image plane.
The point does not have to lie on the object surface or match a field definition, so it covers
near and off-axis points, through-object-distance studies and lenses whose object is at infinity.

```python
r = lf.point_source_trace("examples/arducam-lk004/CS2308ZM05_8mm.lens.json",  # lens or file path
                          (0.0, 100.0, -500.0),   # x, y, z (lens units; surface 1 vertex at origin)
                          wavelength=0.5876,      # um; an int picks a system wavelength; None = primary
                          pattern="hexapolar", n=8,  # see below
                          size=1.0,               # fraction of the pupil radius filled
                          aiming="real")          # or "paraxial" (default: the lens's setting)
r["x"], r["y"]          # image-plane coordinates per ray (NaN where a ray failed)
r["valid"], r["vignetted"], r["status"], r["error_surface"], r["reasons"]
r["px"], r["py"]        # normalised pupil coordinates of each ray
r["chief"], r["centroid"], r["rms_radius"], r["geo_radius"], r["trace"]  # trace = full TraceResult
import lensforge.plot as P; P.point_source(r, scale=1000)
```

* `point=(x, y)` puts the point on the object surface; `frame="object"` measures z from the object
  surface instead of from surface 1.
* Patterns (from `lf.pupil_grid`): `"hexapolar"` (n rings), `"square"` / `"grid"` (n x n),
  `"random"` and `"dithered"` (n² points), `"ring"` (n points on the rim; with `size` < 1 a zone),
  `"cross"`, `"xfan"`, `"yfan"` (n points per fan). Explicit `px=`, `py=` arrays override the pattern.
* Status codes: 0 ok, 1 missed a surface, 2 total internal reflection, 3 clipped by an aperture;
  `apertures=False` ignores clear apertures. Real aiming maps pupil coordinates onto the stop exactly,
  which matters for wide-angle lenses with strong pupil aberration.

## Optimisation and tolerancing

All in `lensforge.optimize` (`from lensforge import optimize as opt`). Variables, solves and an attached
merit function (`lens.merit_function`) are stored on the lens and saved in the `.lens.json` file.

```python
opt.set_variable(lens, 1, "curvature")                  # also "thickness", "conic", "coefficients[0]",
opt.set_variable(lens, 2, "glass.vd")                   #   "tilt_x", ... and model-glass nd / vd / dPgF
opt.set_solve(lens, opt.FNumber(6, 4.0))                # curvature solve: F/4
opt.set_solve(lens, opt.MarginalRayHeight(6))           # thickness solve: image at paraxial focus
mf = opt.default_merit(lens, "spot", glass_min=2, air_min=1)  # or "wavefront", "mtf"
mf.add("EFFL", 100.0, -1)                               # weight < 0: exact (Lagrange) constraint
mf.add("REAY", 0.0, 1.0, surf=4, hy=1, py=1)            # any operand, target, weight, bound
print(mf.table(lens))                                   # merit function editor listing
opt.optimize(lens, mf)                                  # damped least squares, in place
opt.hammer(lens, mf, trials=50); opt.global_search(lens, mf, starts=20)
opt.glass_substitution(lens, mf, nearest=5)             # trial glasses + re-optimisation
tols = opt.default_tolerances(lens)
opt.sensitivity_analysis(lens, tols); opt.monte_carlo(lens, tols, trials=200)
```

| Zemax feature | lensforge.optimize |
|---|---|
| Variables (V), bounds | `set_variable(sys, surface, param, min, max)`, `vary_curvatures`, `vary_thicknesses`; radius varied as curvature; catalog glass auto-converted to a model glass for `glass.nd` / `glass.vd` / `glass.dpgf` |
| Solves | `MarginalRayHeight` (paraxial or real at a pupil zone), `ChiefRayHeight`, `MarginalRayAngle`, `ChiefRayAngle`, `FNumber`, `Concentric`, `EdgeThickness`, `Position`, `Pickup` (any parameter or material, scale + offset); re-applied at every evaluation |
| Merit function editor | `MeritFunction`: `add` / `insert` / `remove`, targets, weights, bounds (`=`, `>`, `<`), `table`, `evaluate` (values and % contribution), JSON |
| Operands (`operand_help()` lists ~80) | first order (EFFL, WFNO, ISFN, PMAG, TOTR, EPDI, EXPP, PIMH, POWR, PARY/PARB, AXCL), real rays (REAX/Y/Z/R, REAB, RANG, RAID, RAED, TRAX/Y/R, OPDC), image quality (RSCE, RSCH, GEOS, RWCE, STRH, MTFT/S/A, EERA, ZERN, DIST, LACL, RELI), Seidel (SPHA, COMA, ASTI, FCUR, DISW, SEID), construction (CT/ET/CV/CO VA/GT/LT, MNCT..MXEA, TTHI, PARV, INDX, ABBE), maths on rows (CONS, SUMM, DIFF, PROD, DIVI, ABSO, SQRT, OSUM, MAXX, MINN, OPGT, OPLT, OPVA), USER (any Python function) |
| Default merit function | `default_merit(kind="spot" / "wavefront" / "mtf", reference="centroid" / "chief", rings, arms)`: Gaussian quadrature pupil sampling (half pupil for symmetric systems), field and wavelength weights, glass / air centre and edge thickness boundaries |
| Local optimisation | `optimize`: damped least squares (Levenberg-Marquardt with Marquardt scaling, several damping values per cycle), bound handling, Lagrange-multiplier hard constraints with second-order correction |
| Global optimisation | `global_search` (Latin-hypercube multi-start, keeps the best distinct designs), `hammer` (perturb + re-optimise, optional glass moves) |
| Glass substitution | `glass_substitution` (trial substitution with re-optimisation), `nearest_glasses`, `snap_to_catalog` (model glass to nearest real glass) |
| Tolerancing | operands TRAD, TCUR, TFRN, TCON, TTHI, TPAR, TIND, TABB, TSDX/Y, TSTX/Y, TEDX/Y, TETX/Y; `default_tolerances`; compensators (back focus by optimisation, paraxial focus, or any list of parameters); criteria RMS spot / RMS wavefront / MTF / merit function / callable; `sensitivity_analysis` (+ RSS estimate, worst offenders), `inverse_sensitivity`, `monte_carlo` (normal / uniform / parabolic / endpoint, yield, percentiles, best and worst lenses) |

Decentres and tilts are modelled with coordinate breaks around the surface or element plus an exact
coordinate return, so the rest of the lens stays put (tested to 1e-14). Perturbed lenses are copies.

## Layout

| Module | Contents |
|---|---|
| `materials.py`, `glass_data.py` | Dispersion formulas (all 13 Zemax AGF formulas), built-in SCHOTT catalog (all 156 current preferred and inquiry glasses from the 2025 SCHOTT data sheet, `schott_catalog.py`, plus obsolete types such as SF58, FK54, KZFS1, LAF10, LAF21) + fused silica, CaF2, sapphire, MgF2, PMMA, polycarbonate; model glasses (nd/Vd); AGF catalog loader; `MaterialLibrary` resolving names like `"N-BK7"`, `"SCHOTT:N-BK7"`, `"1.62,36.4"`, `1.5`, `"MIRROR"`. |
| `surfaces.py` | Standard (sphere/conic), EvenAsphere, OddAsphere, Toroidal (incl. cylinders), XYPolynomial freeform, Paraxial (ideal lens), BinaryPhase (diffractive), DiffractionGrating (linear grating), CoordinateBreak; circular/annular/rectangular/elliptical apertures and obscurations. |
| `system.py` | `OpticalSystem`: surfaces + aperture (EPD, image F/#, object NA, stop size, working F/#), fields (angle, object height, paraxial or real image height), wavelengths, ray aiming, global surface frames, JSON serialisation. |
| `paraxial.py` | y-nu trace; EFL/BFL/FFL, entrance/exit pupils, marginal and chief rays, magnification, F/#, NA, Lagrange invariant. Works with mirrors. |
| `raytrace.py` | Vectorised exact ray trace (N rays per call): intersections, normals, directions, cumulative OPL per surface, miss/TIR/vignetting flags; ray generation from normalised field/pupil coordinates with paraxial or real ray aiming. |
| `analysis/` | All analyses (table above); `metrics.py` holds scalar operands for optimisation and tolerancing. |
| `optimize/` | Variables, solves, operands and merit function editor, damped least squares, global search / hammer, glass substitution, tolerancing (see above). |
| `plot.py` | Optional matplotlib helpers that draw analysis dicts (no computation). |
| `io/` | Native JSON format; Zemax `.zmx` importer (common subset). |
| `compose.py` | Scale surfaces and systems, reverse a group of surfaces, insert one lens into another (`insert_lens`), delete a range of surfaces with variables, solves and merit operands renumbered (`delete_surfaces`). |
| `samples.py` | Example systems (singlet, achromat, parabola, Cassegrain) and a paraxial focus solve. |

## Conventions

* Surface 0 = object, last = image; `thickness` is to the next surface; `material` is the medium after the surface.
* Radii positive with centre of curvature to the right. Mirrors use `material="MIRROR"` and negative thickness afterwards.
* Lens units mm by default; wavelengths in micrometres; field angles in degrees. A positive field angle means rays with positive slope (object at negative y), as in Zemax.
* OPD sign: `W = OPL(chief) - OPL(ray)` referenced to a sphere centred on the primary chief-ray image point through the paraxial exit pupil, so `ey = -(R/n') dW/dy`.

## Validation highlights (see `tests/`)

Glass indices match catalog nd/Vd for every built-in glass; thick-lens EFL/BFL match closed form to 1e-12;
single-surface spherical aberration matches the exact trigonometric formula; tilted-plate displacement exact;
parabola, classical Cassegrain and ellipsoidal mirror (finite conjugates) image perfectly (RMS < 1e-10, OPD < 1e-5 waves);
ideal lens is perfect off-axis; real rays converge to paraxial values; ray fans and OPD agree via ey = -(R/n') dW/dy;
fold mirrors, coordinate-break round trips, real ray aiming, real-image-height fields, diffractive lens dispersion.

Analysis tests (`tests/test_analysis_quality.py`): perfect-lens FFT and Huygens PSF peak = Airy peak (1%), Strehl 1;
FFT/Huygens MTF = analytic diffraction MTF (3e-3); Airy encircled energy 0.838 / 0.910 at the first two dark rings;
Strehl of a known defocus = Marechal and Zernike Z4 = W020/2; geometric MTF and encircled energy of a uniform blur disk
= 2 J1(x)/x and (r/b)^2; Seidel transverse/longitudinal spherical, distortion, lateral colour, field curvature and axial
colour agree with small-aperture real rays (<0.5%), W040/W131/W220 agree with the OPD map, parabola S1 = 0, asphere
term = 8 a4 y^4 dn; ideal-lens distortion 0 (f-tan) and tan(t)/t - 1 (f-theta); relative illumination = cos^4;
vignetting area fraction; Fresnel plate transmission (1-R)^2 and full p-transmission at Brewster's angle; thick-lens
principal planes; Zernike orthonormality and exact fit recovery.

## Not yet implemented

Thermal glass effects, gradient index, non-sequential mode, Zernike sag surfaces, object-space
telecentric systems, multi-configuration. Optimisation gaps vs Zemax: orthogonal descent, multi-start genetic global search,
TIRR (irregularity) tolerances, multi-configuration merit functions.
Analysis gaps vs Zemax: physical optics propagation / Gaussian beams, ghost focus, extended-source geometric image
analysis, thin-film coatings and bulk absorption in polarisation/transmission, annular Zernikes, diffractive and
odd/XY-polynomial terms in the Seidel sums. The FFT PSF/MTF ignores off-diagonal pupil scaling (fields with both
x and y components on strongly anamorphic systems); use the Huygens PSF there. The ideal `Paraxial` surface's OPD
is exact only for collimated input, so diffraction results of ideal lenses at finite conjugates show spurious OPD.
