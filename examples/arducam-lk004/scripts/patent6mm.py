"""CS1806ZM06 (6 mm F/1.4) model built from a published CCTV lens prescription.

Start: US 6,549,344 B2 (Fuji Photo Optical, "Retro focus type wide-angle lens"), Example 1,
scaled from f' = 1 to f = 6 mm. Its glasses are Schott N-LAF34, N-SF6 and N-LAK8 (exact nd/vd
matches). The patent's IR-filter block is removed, then the lens is re-optimised at F/1.4 for the
IMX477 corner field, the Arducam back focus and low distortion.

usage: patent6mm.py OUT.lens.json [seed]      (about 15 minutes)
"""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
import numpy as np
import lensforge as lf
from lensforge import optimize as opt

F, FNO = 6.0, 1.4
HALF_DIAG = 7.857 / 2          # IMX477 active area 6.287 x 4.712 mm
BFD = 8.03 - 0.35              # published back focus, less the removed filter plate (as for the other models)
TRACK = 40.0                   # first surface to image
DIST = 3.0                     # |distortion| at the sensor corner, percent
SD_MAX = 12.0                  # front element clear semi-diameter (28 mm barrel)
EDGE_GLASS, EDGE_AIR = 0.8, 0.3  # minimum edge thicknesses, mm

# US6549344 Example 1, f' = 1: radius, thickness, glass. Surfaces 7 and 10 are the flare and aperture
# stops; the patent's last two surfaces (a 0.81 thick filter, nd 1.5163) are left out.
EXAMPLE1 = [
    (4.010, 0.24, "N-LAF34"), (2.053, 0.49, None), (3.413, 0.70, "N-SF6"), (-31.731, 0.03, None),
    (2.289, 0.16, "N-LAF34"), (0.891, 0.91, None), (0, 0.52, None), (-2.478, 0.89, "N-LAK8"),
    (-1.882, 0.31, None), (0, 0.72, None), (47.662, 0.21, "N-SF6"), (1.633, 0.94, "N-LAK8"),
    (-3.235, 0.03, None), (2.518, 0.62, "N-LAF34"), (-101.693, 0.00, None),
]


def patent_lens():
    L = lf.OpticalSystem("Arducam CS1806ZM06 (approximation after US6549344 Example 1)")
    L.set_wavelengths([0.4861327, 0.5875618, 0.6562725], primary=1)
    for k, (r, d, g) in enumerate(EXAMPLE1):
        L.add_surface(radius=r * F if r else math.inf, thickness=d * F, material=g, stop=(k == 9),
                      comment={6: "flare stop", 9: "aperture stop"}.get(k, ""))
    L.set_aperture("EPD", F / FNO)
    L.surfaces[L.image_index - 1].thickness = L.paraxial().bfl
    n = L.image_index - 1
    for i in range(1, n + 1):
        if L.surfaces[i].curvature != 0:
            opt.set_variable(L, i, "curvature")
        if i == n:
            opt.set_variable(L, i, "thickness", min=0.3)
        elif L.surfaces[i].material:
            opt.set_variable(L, i, "thickness", min=0.6, max=8.0)
        else:
            opt.set_variable(L, i, "thickness", min=0.1, max=20.0)
    return L


def corner_angle(L):
    """Field angle whose chief ray lands on the sensor corner."""
    L.set_fields([0, 40]); a, b = 0.0, 40.0
    for _ in range(50):
        m = 0.5 * (a + b); y = abs(L.trace(hy=m / 40).image[0, 1])
        a, b = (m, b) if np.isfinite(y) and y < HALF_DIAG else (a, m)
    return 0.5 * (a + b)


def set_fields(L):
    hd = corner_angle(L)
    L.set_fields([0, 0.5 * hd, 0.75 * hd, 0.9 * hd, hd])
    for k, w in enumerate([1, 1, 1, 1, 0.5]):
        L.fields[k].weight = w


def merit(L, final):
    n = L.image_index - 1
    mf = opt.default_merit(L, "spot", rings=3, arms=6)
    mf.add("MNCG", 0.8, 1); mf.add("MNCA", 0.1, 1)
    mf.add("MNEG", EDGE_GLASS, 10); mf.add("MNEA", EDGE_AIR, 10)   # edges from 5%-padded clear apertures
    mf.add("EFFL", F, -1)
    if final:
        mf.add("TTHI", BFD, -1, surf=n, surf2=n, comment="back focus")
        mf.add("TOTR", TRACK, 1, bound="<")
        mf.add("DIST", -DIST, 1, bound=">", field=1.0); mf.add("DIST", DIST, 1, bound="<", field=1.0)
        for hy, py in ((1, 1), (1, -1), (0, 1)):
            mf.add("REAR", SD_MAX, 1, bound="<", surf=1, hy=hy, py=py)
    else:  # first pass: rebalance the patent lens without its filter block, back focus and length free
        mf.add("TOTR", 60.0, 1, bound="<")
    return mf


if __name__ == "__main__":
    out = sys.argv[1]; seed = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    L = patent_lens()
    set_fields(L)
    print("patent, filter removed:", opt.optimize(L, merit(L, False), cycles=150))
    for _ in range(3):
        set_fields(L)
        print("fit Arducam specs:", opt.optimize(L, merit(L, True), cycles=80))
    set_fields(L)
    mf = merit(L, True)
    print("hammer:", opt.hammer(L, mf, trials=6, cycles=20, seed=seed))
    print("polish:", opt.optimize(L, mf, cycles=150))
    L.update_semi_diameters(margin=0.05)
    L.notes = ("Approximation, not Arducam's design: US6549344 Example 1 rescaled to 6 mm and re-optimised "
               "at F/1.4 without its IR filter. No IR filter or cover glass.")
    lf.save(L, out)
    print(L.prescription())
