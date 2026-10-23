# Arducam LK004 lens kit: approximate lensforge models (work in progress)

**These are NOT Arducam's real prescriptions.** Arducam publishes no design data. Each model is a
lensforge design optimised to match the published specs (focal length, F/#, back focal length, size,
horizontal FOV) on the Raspberry Pi HQ camera sensor (IMX477, 6.287 x 4.712 mm, 1.55 um pixels).
Use them for first-order work (FOV, depth of field, packaging, vignetting trends), not as a prediction
of the real lenses' sharpness: the models' image quality is likely worse than the real lenses.

| File | Status |
|---|---|
| CS1812ZM03.lens.json (12 mm F/1.6) | first version |
| CS2316ZM02.lens.json (16 mm F/1.6) | first version |
| CS2325ZM01.lens.json (25 mm F/1.2) | first version, edge-field vignetting by clear apertures |
| CS2308ZM05 (8 mm F/1.4), CS1806ZM06 (6 mm F/1.4) | still optimising |

Assumptions: 6 or 7 spherical elements (double Gauss; retrofocus front element for 6/8 mm),
Schott glasses, a 1.0 mm N-BK7 plate 0.8 mm before the sensor standing in for the HQ camera's
IR-cut filter and cover glass, F/C/d wavelengths, object at infinity.
Back focal length is held from the last lens vertex to the image (published value).

`lk004_gallery.png`: layout, MTF (axis and sensor corner) and distortion per lens.
Optimisation scripts, logs and checkpoints are kept out of the repo.
