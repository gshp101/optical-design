"""Optimisation demo: design, optimise, choose glasses for and tolerance a Cooke triplet.

Run from the project folder:  python examples/optimization_demo.py   (about 2 minutes)
Writes examples/output/cooke_triplet.lens.json and examples/output/optimization_report.txt.
"""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import lensforge as lf  # noqa: E402
from lensforge import optimize as opt  # noqa: E402
from lensforge.optimize.tolerance import sensitivity_table  # noqa: E402

OUT = os.path.join(os.path.dirname(__file__), "output")
os.makedirs(OUT, exist_ok=True)
report = []


def log(*a):
    text = " ".join(str(x) for x in a)
    print(text)
    report.append(text)


# 1. A rough starting point: crown / flint / crown, F/4, f = 100 mm, +-14 degrees -------------
lens = lf.OpticalSystem("Cooke triplet")
lens.set_aperture("EPD", 25)
lens.set_fields([0, 10, 14])
lens.set_wavelengths([0.4861327, 0.5875618, 0.6562725], primary=1)
lens.add_surface(radius=40, thickness=6, material="N-SK16")
lens.add_surface(radius=-200, thickness=8)
lens.add_surface(radius=-40, thickness=2, material="F2", stop=True)
lens.add_surface(radius=40, thickness=8)
lens.add_surface(radius=200, thickness=6, material="N-SK16")
lens.add_surface(radius=-40, thickness=80)

# 2. Variables and solves ----------------------------------------------------------------------
for i in range(1, 6):
    opt.set_variable(lens, i, "curvature")
opt.set_variable(lens, 2, "thickness", min=1.0)
opt.set_variable(lens, 4, "thickness", min=1.0)
opt.set_solve(lens, opt.FNumber(6, 4.0))            # last curvature holds F/4 (so f = 100 mm)
opt.set_solve(lens, opt.MarginalRayHeight(6))       # image at paraxial focus

# 3. Merit function: default RMS spot + thickness boundaries + a distortion target --------------
mf = opt.default_merit(lens, "spot", glass_min=2.0, glass_edge=1.0, air_min=1.0)
mf.add("DIST", 0.0, 0.0, field=1.0, comment="monitor only (weight 0)")
lens.merit_function = mf
log("Starting design\n" + lens.prescription())
log(mf.table(lens))

# 4. Local optimisation (damped least squares) ---------------------------------------------------
res = opt.optimize(lens, mf, cycles=100)
log("\nDLS:", res)

# 5. Hammer: perturb and re-optimise to escape the local minimum ----------------------------------
h = opt.hammer(lens, mf, trials=6, cycles=12, seed=1)
log("Hammer:", h)

# 6. Glass substitution among the nearest catalog glasses ----------------------------------------
g = opt.glass_substitution(lens, mf, surfaces=[1, 3, 5], nearest=4, cycles=10, passes=1)
log("Glass substitution:", g)
opt.optimize(lens, mf, cycles=100)
log("\nOptimised design\n" + lens.prescription())
log(mf.table(lens))
par = lens.paraxial()
log(f"EFL {par.efl:.4f}  F/{par.working_fnum:.3f}  total track {par.total_track:.3f}")
for k in range(len(lens.fields)):
    sp = lf.spot_diagram(lens, k)
    log(f"field {lens.fields[k].y:5.1f} deg: RMS spot {1000 * sp['rms_radius']:6.2f} um, "
        f"MTF(50/mm) T/S = {lf.mtf_at(lens, 50, k)[0]:.3f}/{lf.mtf_at(lens, 50, k)[1]:.3f}")
lf.save(lens, os.path.join(OUT, "cooke_triplet.lens.json"))     # variables, solves and merit included

# 7. Tolerancing --------------------------------------------------------------------------------
lens.update_semi_diameters(margin=0.05)
tols = opt.default_tolerances(lens, fringes=2, thickness=0.05, surface_decenter=0.01, surface_tilt=0.01,
                              element_decenter=0.02, element_tilt=0.02, index=0.0005, abbe_percent=0.5)
t0 = time.time()
sa = opt.sensitivity_analysis(lens, tols, criterion="rms_spot", compensators="focus")
log(f"\nSensitivity analysis ({len(tols)} tolerances, back-focus compensator, {time.time() - t0:.1f} s)")
log(sensitivity_table(sa, n=12))
mc = opt.monte_carlo(lens, tols, trials=40, criterion="rms_spot", compensators="focus", seed=0)
log("\n" + mc.summary())
log(f"Yield for RMS spot <= 20.5 um: {100 * mc.yield_fraction(0.0205):.0f}%")

# 8. Inverse sensitivity: how loose can the element tilts be for at most +2 um RMS? -------------
tilts = [t for t in tols if t.type in ("TETX", "TETY")]
inv = opt.inverse_sensitivity(lens, tilts, max_change=0.002, compensators="focus")
for t in inv:
    log(f"{t.label():14} -> +-{min(abs(t.min), abs(t.max)):.3f} deg")

with open(os.path.join(OUT, "optimization_report.txt"), "w") as f:
    f.write("\n".join(report) + "\n")
print(f"\nwrote {OUT}/cooke_triplet.lens.json and optimization_report.txt")
