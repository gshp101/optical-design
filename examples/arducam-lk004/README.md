# Arducam LK004 lens kit: approximate lensforge models

**These are NOT Arducam's real prescriptions.** Arducam publishes no design data. Each model is a
lensforge design optimised to match the published specs (focal length, F/#, back focal length, size,
horizontal FOV) on the Raspberry Pi HQ camera sensor (IMX477, 6.287 x 4.712 mm, 1.55 um pixels).

Use them for first-order work: field of view, depth of field, packaging, back focus, vignetting trends.
Do not use them to predict sharpness. The real lenses are probably sharper than these models
(RMS spots of 6 to 36 um here), so MTF from these files runs pessimistic.

## Results (`summary_table.md`, `lk004_gallery.png`)

| Lens | f spec / model | F/# spec / model | HFOV spec / model | Diag FOV | Back focus spec / model | Track | Max clear dia | Elements | RMS spot centre / corner | MTF @100 lp/mm centre / corner (T,S) | Corner distortion | Corner rel. illum. |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| CS1806ZM06 | 6 / 6.00 mm | 1.4 / 1.40 | 65° / 56.4° | 66.8° | 8.03 / 7.69 mm | 29.6 mm | 14.4 mm | 7 | 28.1 / 24.0 µm | 0.04 / 0.04,0.07 | -0.1% | 22% |
| CS2308ZM05 | 8 / 8.00 mm | 1.4 / 1.40 | 50° / 50.1° | 66.5° | 6.5 / 6.12 mm | 25.1 mm | 16.7 mm | 7 | 28.9 / 36.3 µm | 0.08 / 0.02,0.04 | -22.8% | 27% |
| CS1812ZM03 | 12 / 12.00 mm | 1.6 / 1.60 | 30° / 29.9° | 37.0° | 7.53 / 7.16 mm | 18.2 mm | 11.2 mm | 6 | 19.5 / 26.3 µm | 0.06 / 0.03,0.19 | -0.5% | 83% |
| CS2316ZM02 | 16 / 16.00 mm | 1.6 / 1.60 | 24° / 22.4° | 27.8° | 7.53 / 7.17 mm | 22.2 mm | 14.8 mm | 6 | 6.4 / 18.8 µm | 0.13 / 0.13,0.24 | -0.2% | 89% |
| CS2325ZM01 | 25 / 25.00 mm | 1.2 / 1.20 | 14° / 14.5° | 18.0° | 8.03 / 7.66 mm | 38.6 mm | 21.0 mm | 6 | 9.6 / 27.0 µm | 0.07 / 0.02,0.06 | -0.4% | 56% |

Notes
* Published HFOVs mostly imply barrel distortion. The 8 mm model is forced to the published 50 deg
  HFOV, so it has about -23% distortion at the corner. The 6 mm model could not combine the published 65 deg
  with usable sharpness at F/1.4. It is close to rectilinear instead (56 deg HFOV, 67 deg diagonal).
* The 6 mm model was redesigned on 2026-10-24. The first version passed only about half of the on-axis
  F/1.4 beam: the outer rays were totally internally reflected at a steep cemented-doublet surface
  (R = 2.0 mm) and the clear apertures then clipped more, so it really worked at about F/2. Its 14.6 um
  centre spot was measured on the surviving half. The current model passes the full axial beam
  (all 381 spot-diagram rays). `design2.py` now refuses to vignette the axial field, sizes apertures only
  from rays that get through, and limits the refraction angle at every surface (`S_MAX`, default 0.9).
* The 6, 8 and 25 mm models vignette the edge field through element clear apertures, as fast CCTV lenses
  do (relative illumination at the sensor corner is 22 to 56%).
* The 16 mm HFOV comes out at 22.4 deg against 24 deg published. A 16 mm rectilinear lens cannot reach 24 deg on this sensor.

## Assumptions
6 or 7 spherical elements (double Gauss; retrofocus front element for the 6 and 8 mm lenses).
Schott glasses from lensforge's built-in catalog. F, d and C wavelengths, object at infinity.
No IR-cut filter or sensor cover glass (removed 2026-10-24). The models were optimised with a 1.0 mm
N-BK7 plate 0.8 mm before the sensor, which matched the published back focal lengths. With the plate
removed, each lens is refocused, so its back focus (last lens vertex to image) is about 0.35 mm shorter
than published. Run `design2.py` with `FILTER=1` to design with the plate.

## Files
`<model>_<f>mm.lens.json` (for example `CS1806ZM06_6mm.lens.json`): open with `lf.load(...)` or the Qt app (`python -m lensforge_qt CS2316ZM02_16mm.lens.json`).
`scripts/`: the optimisation and analysis scripts used to make these models (`design2.py`, `analyse.py`). `design2.py` writes to `$WORK` (default: the project workspace), so set it before running.
