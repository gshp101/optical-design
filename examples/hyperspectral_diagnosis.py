"""Why rays stop at surfaces 36-37 in examples/output/hyperspectral.lens.json.

Run from the project folder:  python examples/hyperspectral_diagnosis.py

The lens file is not modified; every experiment works on a copy.  Layout:
objective 1-13, slit 14, collimator 15-25, grating 26-28 (rulings turned
parallel to y by the +/-90 degree z breaks), 7 x 1 mm spacers 29-35, coaxial
camera 36-48, image 49.
"""

import copy
import json
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import lensforge as lf  # noqa: E402
from lensforge.raytrace import ERROR_NAMES, trace_rays  # noqa: E402

here = os.path.dirname(__file__)
data = json.load(open(os.path.join(here, "output", "hyperspectral.lens.json")))
WAVES = (0.4, 0.7, 1.0)
GRATING, CAMERA, CAMERA_STOP = 27, 36, 43


def throughput(system, fields=(0.0, 1.0, -1.0), n=11):
    """Percent of a square pupil grid (inside the unit circle) reaching the image, per wavelength,
    plus the most common failures."""
    g = np.linspace(-1, 1, n)
    px, py = np.meshgrid(g, g)
    m = px ** 2 + py ** 2 <= 1
    pct, fails = [], {}
    for w in WAVES:
        ok = 0
        for hy in fields:
            r = trace_rays(system, hy=hy, px=px[m], py=py[m], wavelength=w)
            ok += r.valid.sum()
            for st, es in zip(r.status[~r.valid], r.error_surface[~r.valid]):
                key = f"{ERROR_NAMES[int(st)]} at {int(es)}"
                fails[key] = fails.get(key, 0) + 1
        pct.append(100.0 * ok / (m.sum() * len(fields)))
    top = ", ".join(f"{k} ({v})" for k, v in sorted(fails.items(), key=lambda kv: -kv[1])[:3])
    return "  ".join(f"{w} um {p:3.0f}%" for w, p in zip(WAVES, pct)), top


def without_apertures(d):
    d = copy.deepcopy(d)
    for s in d["surfaces"]:
        s.pop("aperture", None)
    return d


def with_gap(d, gap):
    """Grating-to-camera distance `gap` (the file has 10 + 7 x 1 = 17 mm)."""
    d = copy.deepcopy(d)
    d["surfaces"][GRATING]["thickness"] = float(gap)
    for k in range(GRATING + 2, CAMERA):
        d["surfaces"][k]["thickness"] = 0.0
    return d


lens = lf.OpticalSystem.from_dict(data)

print("1. The grating obeys sin(theta) = m lambda T, turned into x by the z breaks")
T = data["surfaces"][GRATING]["lines_per_um"]
for w in WAVES:
    r = trace_rays(lens, wavelength=w)
    d = r.directions[GRATING + 1, 0]
    print(f"   {w} um: direction after the -90 break ({d[0]:+.4f}, {d[1]:+.4f}, {d[2]:.4f}), "
          f"expected x = -{w * T:.4f}  ->  {math.degrees(math.asin(w * T)):.1f} deg")

print("\n2. The beam reaching the grating is collimated (direction spread across the pupil)")
r = trace_rays(lens, px=np.array([-1.0, 0.0, 1.0]), wavelength=0.7)
print(f"   x direction cosines after surface 25: {np.round(r.directions[25][:, 0], 4)}")

print("\n3. The camera on its own handles every wavelength's angle when the beam is centred on its stop")
cam = copy.deepcopy(data)
cam["surfaces"] = ([data["surfaces"][0], {"type": "STANDARD", "curvature": 0.0, "thickness": 1.0, "material": None}]
                   + copy.deepcopy(data["surfaces"][CAMERA:]))
for s in cam["surfaces"]:
    s.pop("stop", None)
cam["surfaces"][2 + CAMERA_STOP - CAMERA]["stop"] = True
cam["aperture"] = {"type": "EPD", "value": 3.1}
angles = [math.degrees(math.asin(w * T)) for w in WAVES]
cam["fields"] = {"type": "ANGLE", "values": [{"x": 0.0, "y": a, "weight": 1.0} for a in [0.0] + angles]}
camera = lf.OpticalSystem.from_dict(cam)
pa = camera.paraxial(0.7)
row = []
for a in angles:
    g = np.linspace(-1, 1, 15)
    px, py = np.meshgrid(g, g)
    m = px ** 2 + py ** 2 <= 1
    r = trace_rays(camera, hy=a / max(angles), px=px[m], py=py[m], wavelength=0.7)
    row.append(f"{a:.1f} deg {100 * r.valid.mean():.0f}%")
ep_behind_36 = pa.entrance_pupil_position - 1.0
print(f"   {'   '.join(row)}")
print(f"   camera EFL {pa.efl:.2f} mm; entrance pupil {ep_behind_36:.1f} mm BEHIND surface 36 (inside the lens)")

print("\n4. In the system every wavelength pivots at the grating instead, 17 mm in front of surface 36")
print("   so the beam lands (17 + %.1f) tan(theta) off the camera's pupil centre:" % ep_behind_36)
stop_r = data["surfaces"][CAMERA_STOP]["aperture"]["r_max"]
ep_r = stop_r * pa.entrance_pupil_radius / pa.stop_radius
for w, a in zip(WAVES, angles):
    print(f"   {w} um: {(17 + ep_behind_36) * math.tan(math.radians(a)):.1f} mm offset "
          f"(beam radius 1.55 mm, camera entrance pupil radius about {ep_r:.2f} mm)")

print("\n5. Throughput of the whole system (slit centre and both slit ends)")
for label, d in [("as in the file (17 mm gap)", data),
                 ("file, hard apertures removed", without_apertures(data))] + \
        [(f"gap {g:2d} mm", with_gap(data, g)) for g in (10, 5, 2, 0)] + \
        [(f"gap {g:2d} mm, no hard apertures", without_apertures(with_gap(data, g))) for g in (0,)]:
    pct, top = throughput(lf.OpticalSystem.from_dict(d))
    print(f"   {label:32s} {pct}   [{top}]")
