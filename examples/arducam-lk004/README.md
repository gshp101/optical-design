# Arducam LK004 lens kit: approximate lensforge models

**These are NOT Arducam's real prescriptions.** Arducam publishes no design data. Each model is a
lensforge design optimised to match the published specs (focal length, F/#, back focal length, size,
horizontal FOV) on the Raspberry Pi HQ camera sensor (IMX477, 6.287 x 4.712 mm, 1.55 um pixels).

Use them for first-order work: field of view, depth of field, packaging, back focus, vignetting trends.
Do not use them to predict sharpness. The real lenses are probably sharper than these models
(RMS spots of 5 to 57 um here), so MTF from these files runs pessimistic.

## Results (`summary_table.md`, `lk004_gallery.png`)

| Lens | f spec / model | F/# spec / model | HFOV spec / model | Diag FOV | Back focus spec / model | Track | Max clear dia | Elements | RMS spot centre / corner | MTF @100 lp/mm centre / corner (T,S) | Corner distortion | Corner rel. illum. |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| CS1806ZM06 | 6 / 6.00 mm | 1.4 / 1.40 | 65° / 56.8° | 67.7° | 8.03 / 8.03 mm | 23.7 mm | 12.2 mm | 7 | 14.6 / 56.8 µm | 0.06 / 0.01,0.06 | -0.2% | 25% |
| CS2308ZM05 | 8 / 8.00 mm | 1.4 / 1.40 | 50° / 50.0° | 66.3° | 6.5 / 6.50 mm | 25.5 mm | 16.7 mm | 7 | 26.1 / 38.0 µm | 0.05 / 0.04,0.05 | -22.9% | 27% |
| CS1812ZM03 | 12 / 12.00 mm | 1.6 / 1.60 | 30° / 29.9° | 37.0° | 7.53 / 7.53 mm | 18.6 mm | 11.2 mm | 6 | 18.5 / 24.3 µm | 0.05 / 0.04,0.14 | -0.6% | 83% |
| CS2316ZM02 | 16 / 16.00 mm | 1.6 / 1.60 | 24° / 22.4° | 27.8° | 7.53 / 7.53 mm | 22.6 mm | 14.8 mm | 6 | 5.3 / 15.3 µm | 0.12 / 0.15,0.19 | -0.3% | 89% |
| CS2325ZM01 | 25 / 25.00 mm | 1.2 / 1.20 | 14° / 14.4° | 18.0° | 8.03 / 8.03 mm | 38.9 mm | 21.0 mm | 6 | 10.7 / 24.0 µm | 0.11 / 0.03,0.06 | -0.4% | 56% |

Notes
* Published HFOVs mostly imply barrel distortion. The 8 mm model is forced to the published 50 deg
  HFOV, so it has about -23% distortion at the corner. The 6 mm model could not combine the published 65 deg
  with usable sharpness at F/1.4. It is close to rectilinear instead (57 deg HFOV, 68 deg diagonal).
* The 6, 8 and 25 mm models vignette the edge field through element clear apertures, as fast CCTV lenses
  do (relative illumination at the sensor corner is 25 to 56%).
* The 16 mm HFOV comes out at 22.4 deg against 24 deg published. A 16 mm rectilinear lens cannot reach 24 deg on this sensor.

## Assumptions
6 or 7 spherical elements (double Gauss; retrofocus front element for the 6 and 8 mm lenses).
Schott glasses from lensforge's built-in catalog. A 1.0 mm N-BK7 plate 0.8 mm before the sensor
stands in for the HQ camera's IR-cut filter and cover glass. F, d and C wavelengths, object at infinity.
Back focal length is measured from the last lens vertex to the image (published value).

## Files
`<model>.lens.json`: open with `lf.load(...)` or the Qt app (`python -m lensforge_qt CS2316ZM02.lens.json`).
`scripts/`: the optimisation and analysis scripts used to make these models (`design2.py`, `analyse.py`). They were written for the project workspace, so adjust the paths at the top before running them.
