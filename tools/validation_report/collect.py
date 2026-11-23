"""Collect the numbers the report needs beyond the pytest capture.

Writes into DATA_DIR:
  smith.json   EFL/BFL difference from the book for every Smith configuration
  glass.json   per-catalog |nd - nd_catalog| and |vd - vd_catalog|
  manual.json  measured errors for the few tests that compare with np.allclose (not captured)
  meta.json    commit, versions and date

Usage: python collect.py DATA_DIR   (normally called by run.py)
"""
import collections
import datetime
import json
import math
import os
import platform
import re
import subprocess
import sys
from importlib.metadata import PackageNotFoundError, version

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path[:0] = [REPO, os.path.join(REPO, "tests")]

import lensforge as lf  # noqa: E402
from lensforge.materials import default_library  # noqa: E402

DATA = sys.argv[1]


def dump(name, obj):
    with open(os.path.join(DATA, name), "w") as fh:
        json.dump(obj, fh)


def smith():
    import test_smith_examples as T
    rows = []
    for path in T.MODELS:
        for name, lens, notes in T.configurations(path):
            if name in T.BOOK_TABLE_MISMATCH:
                rows.append(dict(name=name, skipped=True))
                continue
            book = dict(re.findall(r"\b(EFL|BFL) (-?[\d.]+)", notes))
            p = lens.paraxial()
            efl, bfl = float(book["EFL"]), float(book["BFL"])
            rows.append(dict(name=name, efl=efl, bfl=bfl,
                             de=float(p.efl * abs(p.n_image) - efl),
                             db=float(p.image_distance * np.sign(p.n_image) - bfl),
                             etol=T.EFL_TOL.get(name, max(0.15, 1e-4 * abs(efl))),
                             btol=T.BFL_TOL.get(name, 0.15)))
    return rows


def glass():
    st = collections.defaultdict(lambda: dict(n=0, dn=0.0, dv=0.0, dns=[]))
    for g in default_library().all_glasses():
        if g.nd_catalog is None:
            continue
        s = st[g.catalog]
        s["n"] += 1
        s["dn"] = max(s["dn"], abs(g.nd - g.nd_catalog))
        s["dv"] = max(s["dv"], abs(g.vd - g.vd_catalog))
        s["dns"].append(abs(g.nd - g.nd_catalog))
    for s in st.values():
        s["med_dn"] = float(np.median(s.pop("dns")))
    return st


def manual():
    from test_grating import grating_system
    from lensforge.system import Field
    out = {}
    w = 0.0
    for m in (-2, -1, 0, 1, 2):
        r = grating_system(T=0.6, m=m).trace(0, 0, [0, 0.5, -1], [0, 0.3, 1])
        w = max(w, np.abs(r.directions[-1][:, 1] - m * 0.55 * 0.6).max(), np.abs(r.directions[-1][:, 0]).max())
    out["test_grating_equation_normal_incidence"] = float(w)
    lam, T = 0.6, 1.2
    s = lf.OpticalSystem()
    s.set_aperture("EPD", 2.0)
    s.set_wavelengths([lam])
    s.set_fields([0, math.degrees(math.asin(lam * T / 2))])
    s.add_surface(lf.DiffractionGrating(lines_per_um=T, diffraction_order=-1, thickness=-10, material="MIRROR",
                                        stop=True))
    r = s.trace(0, 1, 0, 0)
    out["test_reflective_grating_littrow"] = float(np.abs(r.directions[-1][0] + r.directions[0][0]).max())
    f = Field(0, 1, vdx=0.1, vdy=-0.2, vcx=0.25, vcy=0.5, van=90.0)
    u, v = f.vignette_pupil(np.array([1.0, 0.0]), np.array([0.0, 1.0]))
    out["test_vignette_pupil_formula_and_angle"] = float(max(np.abs(u - [0.1, -0.4]).max(),
                                                            np.abs(v - [0.55, -0.2]).max()))
    return out


def meta():
    def git(*a):
        return subprocess.run(["git", *a], cwd=REPO, capture_output=True, text=True).stdout.strip()

    try:
        opt = version("optiland")
    except PackageNotFoundError:
        opt = "not installed (live Optiland tests skipped)"
    return dict(commit=git("log", "-1", "--format=%h"), date=git("log", "-1", "--format=%cs"),
                python=platform.python_version(), numpy=np.__version__, optiland=opt,
                generated=datetime.date.today().strftime("%d %B %Y").lstrip("0"))


if __name__ == "__main__":
    os.makedirs(DATA, exist_ok=True)
    dump("smith.json", smith())
    dump("glass.json", glass())
    dump("manual.json", manual())
    dump("meta.json", meta())
