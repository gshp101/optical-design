"""A merit function that minimises the RMS spot size (the worked example of the Merit Function
Editor help: Help > Help Contents > Merit Function Editor > Example).

Run from the project folder:  python examples/spot_size_merit.py   (about 15 seconds)
Writes examples/spot_size_merit.lens.json: the unoptimised Cooke triplet with its variables and this
merit function (File > Sample Lenses > Spot Size Merit Example), then optimises a copy and prints the
merit function before and after.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import lensforge as lf  # noqa: E402
from lensforge import optimize as opt  # noqa: E402

OUT = os.path.join(os.path.dirname(__file__), "spot_size_merit.lens.json")


def starting_lens():
    """Cooke triplet start: crown / flint / crown, EPD 25 mm, fields 0, 10, 14 degrees, F d C light."""
    lens = lf.OpticalSystem("Cooke triplet: spot size merit example")
    lens.set_aperture("EPD", 25)
    lens.set_fields([0, 10, 14])
    lens.set_wavelengths([0.4861327, 0.5875618, 0.6562725], primary=1)
    lens.add_surface(radius=40, thickness=6, material="N-SK16")
    lens.add_surface(radius=-200, thickness=8)
    lens.add_surface(radius=-40, thickness=2, material="F2", stop=True)
    lens.add_surface(radius=40, thickness=8)
    lens.add_surface(radius=200, thickness=6, material="N-SK16")
    lens.add_surface(radius=-40, thickness=80)
    # variables: every curvature, both air gaps and the back focus (so the optimiser finds best focus)
    for i in range(1, 7):
        opt.set_variable(lens, i, "curvature")
    for i in (2, 4, 6):
        opt.set_variable(lens, i, "thickness", min=1.0)
    return lens


def spot_size_merit(lens):
    """Hard focal length, thickness limits, RMS spot of every field, and weight-0 monitors."""
    mf = opt.MeritFunction()
    mf.add("BLNK", weight=0, comment="First-order requirements")
    mf.add("EFFL", 100.0, -1, comment="focal length exactly 100 mm (hard)")
    mf.add("BLNK", weight=0, comment="Manufacturing limits")
    mf.add("MNCG", 2.0, 1, comment="glass at least 2 mm thick at the centre")
    mf.add("MNEG", 1.0, 1, comment="glass at least 1 mm thick at the edge")
    mf.add("MNCA", 1.0, 1, comment="air gaps at least 1 mm")
    mf.add("BLNK", weight=0, comment="Image quality: RMS spot radius per field")
    for k, name in enumerate(("on axis", "10 degrees", "14 degrees")):
        mf.add("RAYS", 0.0, 1.0, comment=name, field=k, reference="centroid", rings=3, arms=6)
    mf.add("BLNK", weight=0, comment="Monitors (weight 0: shown, not optimised)")
    mf.add("RSCE", 0.0, 0.0, comment="RMS spot on axis, hexapolar grid", field=0)
    mf.add("RSCE", 0.0, 0.0, comment="RMS spot at 14 degrees", field=2)
    mf.add("DIST", 0.0, 0.0, comment="distortion at the field edge (%)", field=1.0)
    mf.add("TOTR", 0.0, 0.0, comment="total track")
    return mf


def main():
    lens = starting_lens()
    lens.merit_function = spot_size_merit(lens)
    lf.save(lens, OUT)
    print(f"wrote {OUT}\n\nStarting merit function\n{lens.merit_function.table(lens)}")

    res = opt.optimize(lens, lens.merit_function, cycles=100)
    print(f"\n{res}\n\nOptimised merit function\n{lens.merit_function.table(lens)}\n")
    print(lens.prescription())
    for k in range(len(lens.fields)):
        print(f"field {lens.fields[k].y:4.0f} deg: RMS spot {1000 * lf.spot_diagram(lens, k)['rms_radius']:6.2f} um")


if __name__ == "__main__":
    main()
