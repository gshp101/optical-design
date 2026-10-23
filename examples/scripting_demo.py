"""Scripting demo: build a lens, analyse it, and run a simple scripted design loop.

Run from the project folder:  python examples/scripting_demo.py
"""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import lensforge as lf  # noqa: E402
from lensforge.samples import focus_paraxial  # noqa: E402

# 1. Build a lens from scratch ------------------------------------------------
lens = lf.OpticalSystem("Scripted singlet")
lens.set_aperture("EPD", 20)
lens.set_fields([0, 5, 10])                      # field angles in degrees
lens.set_wavelengths([0.4861, 0.5876, 0.6563], primary=1)
front = lens.add_surface(radius=60, thickness=5, material="N-BK7", stop=True)
back = lens.add_surface(radius=-200, thickness=90)
focus_paraxial(lens)                             # put the image at paraxial focus

print(lens.prescription())
print(lens.paraxial())

# 2. Trace rays directly ------------------------------------------------------
px, py = lf.pupil_grid("hexapolar", 6)
res = lens.trace(hx=0, hy=1, px=px, py=py)      # normalised field/pupil coordinates
print(f"\n{res.n_rays} rays, {res.valid.sum()} reached the image; "
      f"image y range {np.nanmin(res.y):.4f} .. {np.nanmax(res.y):.4f}")

# 3. Analyses ------------------------------------------------------------------
for i in range(len(lens.fields)):
    sp = lf.spot_diagram(lens, i)
    wf = lf.wavefront(lens, i, n=32)
    print(f"field {i}: RMS spot {1000 * sp['rms_radius']:.1f} um, RMS wavefront {wf['rms']:.3f} waves")

# 4. A scripted design study: bend the lens at constant focal length -----------
target_efl = lens.paraxial().efl
best = None
for c1 in np.linspace(0.002, 0.03, 29):
    trial = lens.copy()
    trial.surfaces[1].curvature = c1
    # solve the back curvature for the same EFL (power is linear in c2 for a thin-ish lens)
    def efl_err(c2):
        trial.surfaces[2].curvature = c2
        return 1 / trial.paraxial().efl - 1 / target_efl
    a, b = -0.05, 0.05
    for _ in range(60):                          # bisection
        m = 0.5 * (a + b)
        if efl_err(a) * efl_err(m) <= 0:
            b = m
        else:
            a = m
    focus_paraxial(trial)
    rms = lf.spot_diagram(trial, 0)["rms_radius"]
    if best is None or rms < best[0]:
        best = (rms, c1, trial)

rms, c1, best_lens = best
print(f"\nBest bending: R1 = {1 / c1:.2f}, R2 = {best_lens.surfaces[2].radius:.2f}, "
      f"on-axis RMS spot {1000 * rms:.1f} um")

# 5. Save / load -----------------------------------------------------------------
out = os.path.join(os.path.dirname(__file__), "best_singlet.lens.json")
lf.save(best_lens, out)
print(f"saved {out}; reloaded EFL = {lf.load(out).paraxial().efl:.4f}")
