"""Command line: ``python -m lensforge LENSFILE`` prints prescription, first-order data and spots;
``--report`` prints the full analysis report (Seidel, Strehl, MTF, distortion)."""

import argparse
import sys

import numpy as np

from . import load, spot_diagram


def main(argv=None):
    ap = argparse.ArgumentParser(prog="lensforge", description=__doc__)
    ap.add_argument("lens", help=".json or .zmx lens file")
    ap.add_argument("--agf", action="append", default=[], help="extra AGF glass catalog(s)")
    ap.add_argument("--report", action="store_true", help="full analysis report")
    ap.add_argument("--mtf-freq", type=float, default=None, help="MTF frequency for the report")
    a = ap.parse_args(argv)
    from .system import shared_library
    for p in a.agf:
        shared_library().load_agf(p)
    lens = load(a.lens)
    if a.report:
        from .analysis import system_report
        print(system_report(lens, a.mtf_freq))
        return 0
    print(f"{lens.name}\n")
    print(lens.prescription())
    print("\nFirst-order properties (primary wavelength):")
    print(lens.paraxial())
    print("\nSpot RMS radius per field:")
    for i, f in enumerate(lens.fields):
        s = spot_diagram(lens, i)
        print(f"  field {i} ({f.x:g}, {f.y:g}): rms {s['rms_radius']:.6g}  geo {s['geo_radius']:.6g}  "
              f"({s['n_rays']}/{s['n_launched']} rays)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
