# Aberration, fan and spot validation

How lensforge's Seidel coefficients, ray fans, OPD fans, spot diagrams and Zernike
terms were checked (November 2026). The numbers are pinned in
`tests/test_aberration_reference.py`. MTF and PSF are covered separately in
[mtf-validation.md](mtf-validation.md). [validation-report.html](validation-report.html) lists every
test that compares lensforge with known truth, with the agreement measured on a test run
(regenerate it with `python tools/validation_report/run.py`).

## 1. Closed-form references

| Case | Analyses | Truth | Agreement |
|---|---|---|---|
| Thin lens, stop at lens, 5 bendings x 2 conjugates | S1..S5, CL, CT | Welford's thin-lens formulas (Aberrations of Optical Systems, 7.5) | 1e-9 relative |
| Same thin lens, bending swept | S1 minimum | B = -2(n^2-1)C/(n+2) | within the 0.01 sweep step |
| One refracting sphere (R 50, n 1.5), semi-apertures 5, 10, 15 | ray fan (T and S), OPD fan | Snell's law traced by hand to the paraxial focus; exact path length to the reference sphere | 1e-12 mm, 1e-7 relative waves |
| Same sphere | spot RMS and GEO radius | the exact ray errors at the same hexapolar points; continuous RMS by quadrature | 1e-10; 0.3 % for a 300 x 300 grid |
| Same sphere | Fringe Z1, Z4, Z9, Z16, Z25 | least-squares fit of the exact wavefront on a fine grid | 0.2 % of the largest term |
| Ideal lens defocused by 1 mm, 0 and 10 deg | ray fans | -h dz / f exactly, at every field | 1e-12 mm |
| Same, on axis | OPD fan | exact path difference between the focus sphere and the reference sphere | 1e-8 waves |
| Same | spot RMS / GEO | uniform blur disc: GEO = b, RMS = b/sqrt(2) (and the exact hexapolar sum) | 1e-10; 0.1 % for a dense grid |

The pre-existing `test_seidel_matches_real_rays_at_small_aperture` (Seidel vs real rays)
and `test_single_surface_spherical_aberration_closed_form` (the ray trace itself) stay as they are.

## 2. Optiland 0.6.3 on a published lens

The lens is the Cooke triplet from the MTF validation (the Zemax "Cooke 40 degree field" sample,
EFL 50, F/5, 0/14/20 deg, 0.48/0.55/0.65 um). The reference values were computed with Optiland's
`Aberrations`, `RayFan`, `OPDFan`, `SpotDiagram` and `ZernikeOPD`. `test_live_optiland_comparison`
recomputes them wherever Optiland is installed.

| Analysis | Agreement |
|---|---|
| Seidel S1..S5, per surface and total | 1e-7 relative (opposite sign, see below) |
| Third-order transverse TSPH, TSCO, TAST, TPFC, TSFC, TTFC, TDIS, TAXC, TLAC | 1e-7 relative |
| Ray fans, 3 fields x 3 wavelengths, T and S | 3e-14 mm (identical ray aiming) |
| OPD fans, primary wavelength and on axis | 5e-5 waves |
| Spot RMS radius, 3 fields x 3 wavelengths, 6 hexapolar rings | 1.1e-7 relative |
| Fringe Zernike Z1..Z16 | 1e-3 waves (different pupil sampling) |

## 3. Differences found

* **Seidel sign.** Optiland's Seidel sums are the negative of lensforge's. lensforge follows
  Welford and Zemax (S1 > 0 for an under-corrected positive lens), and the thin-lens test confirms
  Welford's signs, including S2, when H is Welford's n(u ybar - ubar y). The docstring in
  `lensforge/analysis/seidel.py` writes H with the opposite sign. That doesn't change any result,
  because H only appears squared.
* **TAST was twice Optiland's TAC.** lensforge reported TAST = S3 / (n'u') = TTFC - TSFC, the
  separation of the tangential and sagittal fans. Optiland and Zemax report S3 / (2 n'u'), with
  TSFC = TAST + TPFC and TTFC = 3 TAST + TPFC. Fixed (Joe's decision, 2026-11-22): TAST and LAST are
  now half their old values and match Optiland to 1e-7. TSFC and TTFC are unchanged.
* **OPD fans of non-primary wavelengths off axis.** lensforge centres every wavelength's reference
  sphere on the primary-wavelength chief ray. Optiland uses each wavelength's own chief ray. The two
  differ by a tilt of up to 0.03 waves here, plus a trace (< 1e-3 waves) of focus. The test checks
  that the difference is a tilt.
* **Spot GEO radius.** Both codes use 6 hexapolar rings, but the rings start at different angles,
  so the largest sampled ray differs by up to 0.5 % at the edge of the field. The RMS radius doesn't
  depend on the starting angle and agrees to about 1e-7.

## 4. Still not covered

* Published Seidel tables from a textbook or from Zemax output (only Optiland and closed form).
* Off-axis OPD against a closed form, and higher-order (5th order) aberration coefficients.
* Spot diagrams and fans through aspheres, gratings or decentred systems against another code.
