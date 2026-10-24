"""Point-source demo: trace rays from 3-D object points to the image plane.

Run from the project folder:  python examples/point_source_demo.py
"""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import lensforge as lf  # noqa: E402

here = os.path.dirname(__file__)
lens_file = os.path.join(here, "arducam-lk004", "CS2308ZM05_8mm.lens.json")
lens = lf.load(lens_file)
print(lens.prescription())

# 1. A point 500 mm in front of the lens, 100 mm off axis (coordinates: surface 1
#    vertex at the origin, z along the axis).  The lens file can be passed directly.
#    Real ray aiming fills the stop exactly; this wide-angle lens has strong pupil
#    aberration, so paraxial aiming would clip most off-axis rays at the stop.
r = lf.point_source_trace(lens_file, (0.0, 100.0, -500.0), wavelength=0.5876,
                          pattern="hexapolar", n=8, aiming="real")
print(f"\n{r['n_valid']} of {r['n_launched']} rays reach the image; chief ray at "
      f"({r['chief'][0]:.4f}, {r['chief'][1]:.4f}) mm, centroid "
      f"({r['centroid'][0]:.4f}, {r['centroid'][1]:.4f}), RMS radius {1000 * r['rms_radius']:.2f} um")

# 2. The same point with other pupil patterns and sizes.  Each ray carries its
#    pupil coordinates, image position and vignetting flag.
for pattern, n, size in [("square", 16, 1.0), ("ring", 36, 1.0), ("ring", 36, 0.5),
                         ("yfan", 11, 1.0), ("random", 20, 1.0)]:
    r = lf.point_source_trace(lens, (0.0, 100.0, -500.0), pattern=pattern, n=n, size=size,
                              aiming="real")
    print(f"{pattern:>8s} n={n:<3d} size={size:.1f}: {r['n_valid']:4d}/{r['n_launched']:<4d} rays, "
          f"RMS {1000 * r['rms_radius']:7.2f} um, vignetted {int(r['vignetted'].sum())}")

r = lf.point_source_trace(lens, (0.0, 100.0, -500.0), pattern="yfan", n=7, size=1.3, aiming="real")
print("\n  py        y_image   status")
for py, y, why in zip(r["py"], r["y"], r["reasons"]):
    print(f"{py:5.2f}  {y:10.5f}   {why}")

# 3. Through-object-distance study: the focus is set for infinity, so near points blur.
print("\n object z (mm)   RMS spot (um)")
for z in (-1e6, -5000, -1000, -500, -200, -100):
    r = lf.point_source_trace(lens, (0.0, 0.0, z), wavelength=0.5876, pattern="hexapolar", n=8)
    print(f"{z:14.0f}   {1000 * r['rms_radius']:10.2f}")

# 4. Optional plot of a few points (needs matplotlib).
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import lensforge.plot as P
except ImportError:
    sys.exit(0)
fig, axes = plt.subplots(1, 3, figsize=(11, 4))
for ax, pt in zip(axes, [(0, 0, -500), (0, 50, -500), (0, 100, -500)]):
    P.point_source(lf.point_source_trace(lens, pt, pattern="hexapolar", n=10, aiming="real"), ax, scale=1000)
    ax.set_xlabel("x (um)")
    ax.set_ylabel("y (um)")
fig.tight_layout()
out = os.path.join(here, "output", "point_source_demo.png")
fig.savefig(out, dpi=110)
print(f"\nsaved {out}")
