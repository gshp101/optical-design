# Arducam LK004 lens kit: approximate lensforge models

**These are NOT Arducam's real prescriptions.** Arducam publishes no design data. Each model is a
lensforge design optimised to match the published specs (focal length, F/#, back focal length, size,
horizontal FOV) on the Raspberry Pi HQ camera sensor (IMX477, 6.287 x 4.712 mm, 1.55 um pixels).

Use them for first-order work: field of view, depth of field, packaging, back focus, vignetting trends.
Do not use them to predict sharpness. The real lenses are probably sharper than these models
(RMS spots of 6 to 36 um here; the 6 mm model, which starts from a real published design, is the sharpest), so MTF from these files runs pessimistic.

## Results (`summary_table.md`, `lk004_gallery.png`)

| Lens | f spec / model | F/# spec / model | HFOV spec / model | Diag FOV | Back focus spec / model | Track | Max clear dia | Elements | RMS spot centre / corner | MTF @100 lp/mm centre / corner (T,S) | Corner distortion | Corner rel. illum. |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| CS1806ZM06 | 6 / 6.00 mm | 1.4 / 1.40 | 65° / 57.0° | 68.3° | 8.03 / 7.68 mm | 39.8 mm | 18.8 mm | 7 | 6.8 / 13.2 µm | 0.17 / 0.15,0.14 | -3.0% | 48% |
| CS2308ZM05 | 8 / 8.00 mm | 1.4 / 1.40 | 50° / 50.1° | 66.5° | 6.5 / 6.12 mm | 25.1 mm | 16.7 mm | 7 | 28.9 / 36.3 µm | 0.08 / 0.02,0.04 | -22.8% | 27% |
| CS1812ZM03 | 12 / 12.00 mm | 1.6 / 1.60 | 30° / 29.9° | 37.0° | 7.53 / 7.16 mm | 18.2 mm | 11.2 mm | 6 | 19.5 / 26.3 µm | 0.06 / 0.03,0.19 | -0.5% | 83% |
| CS2316ZM02 | 16 / 16.00 mm | 1.6 / 1.60 | 24° / 22.4° | 27.8° | 7.53 / 7.17 mm | 22.2 mm | 14.8 mm | 6 | 6.4 / 18.8 µm | 0.13 / 0.13,0.24 | -0.2% | 89% |
| CS2325ZM01 | 25 / 25.00 mm | 1.2 / 1.20 | 14° / 14.5° | 18.0° | 8.03 / 7.66 mm | 38.6 mm | 21.0 mm | 6 | 9.6 / 27.0 µm | 0.07 / 0.02,0.06 | -0.4% | 56% |

Notes
* Published HFOVs mostly imply barrel distortion. The 8 mm model is forced to the published 50 deg
  HFOV, so it has about -23% distortion at the corner.
* The 6 mm model (redesigned 2026-10-24, `scripts/patent6mm.py`) starts from a real CCTV lens:
  US 6,549,344 B2 (Fuji Photo Optical), Example 1, a 7-element retrofocus lens for CCD cameras at
  F/1.25 with an IR-filter block. It was scaled from f' = 1 to 6 mm with the patent's own glasses
  (Schott N-LAF34, N-SF6, N-LAK8), the filter block was removed, and the lens was re-optimised at F/1.4
  for the IMX477 corner, the Arducam back focus and at most 3% distortion. It keeps the patent's form
  and both stops. Arducam's 65 deg is most likely the diagonal field: a distortion-free 6 mm lens covers
  66.7 deg on this sensor, and this model covers 68.3 deg diagonal (57 deg horizontal). It passes the
  full F/1.4 beam at every field (no vignetting), with RMS spots of 6 to 13 um against 24 to 28 um for the
  previous double-Gauss model. It is longer (39.8 mm track, 18.8 mm front element) than the barrel
  suggests, so treat its length as approximate.
* The 8 and 25 mm models vignette the edge field through element clear apertures, as fast CCTV lenses
  do (relative illumination at the sensor corner is 27 and 56%).
* The 16 mm HFOV comes out at 22.4 deg against 24 deg published. A 16 mm rectilinear lens cannot reach 24 deg on this sensor.

## Assumptions
6 or 7 spherical elements (double Gauss, with a retrofocus front element for the 8 mm lens; the 6 mm lens follows US6549344).
Schott glasses from lensforge's built-in catalog. F, d and C wavelengths, object at infinity.
No IR-cut filter or sensor cover glass (removed 2026-10-24). The models were optimised with a 1.0 mm
N-BK7 plate 0.8 mm before the sensor, which matched the published back focal lengths. With the plate
removed, each lens is refocused, so its back focus (last lens vertex to image) is about 0.35 mm shorter
than published. Run `design2.py` with `FILTER=1` to design with the plate. The 6 mm model was designed
without a plate, for the same back focus as the others (7.68 mm).

## Files
`<model>_<f>mm.lens.json` (for example `CS1806ZM06_6mm.lens.json`): open with `lf.load(...)` or the Qt app (`python -m lensforge_qt CS2316ZM02_16mm.lens.json`).
`scripts/`: the optimisation and analysis scripts used to make these models (`design2.py`, `patent6mm.py` for the 6 mm lens, `analyse.py`). `design2.py` writes to `$WORK` (default: the project workspace), so set it before running.
