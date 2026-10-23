"""Analysis demo: run the main analyses on a sample lens and save a plot gallery.

Run from the project folder:  python examples/analysis_demo.py [lensfile]
Writes examples/output/analysis_gallery.png (needs matplotlib) and prints a report.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import lensforge as lf  # noqa: E402
from lensforge.analysis import metrics  # noqa: E402

lens = lf.load(sys.argv[1]) if len(sys.argv) > 1 else lf.samples.achromat()
lens.set_aperture("EPD", 10)            # stop the sample down to F/7 so it is near diffraction limited
lf.samples.focus_paraxial(lens)

# --- numbers (all analyses return dicts of NumPy arrays) ---------------------------
print(lf.system_report(lens, mtf_frequency=50))
s = lf.seidel(lens)
print("\nW040 = %.3f waves, W131 = %.3f waves" % (s["wavefront"]["W040"], s["wavefront"]["W131"]))
z = lf.zernike_coefficients(lens, field=2, kind="standard", n_terms=15)
print("Standard Zernikes, field 2:", " ".join(f"{c:+.3f}" for c in z["coefficients"]))
print("80%% encircled energy radius (field 0): %.4f mm" % metrics.ee_radius(lens, 0.8, method="fft"))
print("Merit operands: EFFL=%.3f  MTFT(50)=%.3f  DIST=%.4f%%" % (
    metrics.evaluate(lens, "EFFL"), metrics.evaluate(lens, "MTFT", 50, field=2), metrics.evaluate(lens, "DIST")))

# --- plots (optional) -----------------------------------------------------------------
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import lensforge.plot as P
except ImportError:
    sys.exit("matplotlib not installed: skipping plots")

fig, ax = plt.subplots(4, 4, figsize=(20, 18))
ax = ax.ravel()
P.layout(lf.layout(lens), ax[0]); ax[0].set_title("Layout")
P.spot(lf.spot_diagram(lens, 2), ax[1])
P.ray_fan(lf.ray_fan(lens, 2), ax[2:4])
P.wavefront(lf.wavefront(lens, 2), ax[4])
P.psf(lf.fft_psf(lens, 2), ax[5])
P.mtf(lf.fft_mtf(lens, 2), ax[6]); ax[6].set_title("FFT MTF, field 2")
P.through_focus_mtf(lf.through_focus_mtf(lens, 50, 0), ax[7])
P.energy(lf.diffraction_energy(lens, 0), ax[8]); ax[8].set_title("Encircled energy")
P.field_curvature(lf.field_curvature(lens), ax[9:11])
P.lateral_color(lf.lateral_color(lens), ax[11])
P.chromatic_focal_shift(lf.chromatic_focal_shift(lens), ax[12])
P.relative_illumination(lf.relative_illumination(lens), ax[13])
P.seidel(s, ax[14]); ax[14].set_title("Seidel diagram")
P.zernike(z, ax[15])
fig.tight_layout()
out = os.path.join(os.path.dirname(__file__), "output")
os.makedirs(out, exist_ok=True)
fig.savefig(os.path.join(out, "analysis_gallery.png"), dpi=70)
print("\nsaved", os.path.join(out, "analysis_gallery.png"))
