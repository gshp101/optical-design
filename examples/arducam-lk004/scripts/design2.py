"""Approximate designs for the Arducam LK004 CS-mount lenses on the Pi HQ camera (IMX477).

Resumable: the lens and the stage reached are checkpointed in WORK after every step.
usage: design2.py NAME [start.lens.json stage F fs]
"""
import sys, os, json, math, time, copy
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
import numpy as np
import lensforge as lf
from lensforge import optimize as opt

WORK = os.environ.get("WORK", "/mnt/project-files/arducam-lk004/work")
os.makedirs(WORK, exist_ok=True)
HALF_W, HALF_DIAG = 6.287 / 2, 7.857 / 2          # IMX477 active area 6.287 x 4.712 mm
SPECS = {  # model: f, F/#, HFOV, BFL, diameter, length, retrofocus front, match HFOV exactly
    "CS1806ZM06": (6, 1.4, 65, 8.03, 28, 28.5, True, True),
    "CS2308ZM05": (8, 1.4, 50, 6.50, 28, 23, True, True),
    "CS1812ZM03": (12, 1.6, 30, 7.53, 30, 29, False, False),
    "CS2316ZM02": (16, 1.6, 24, 7.53, 30, 29, False, False),
    "CS2325ZM01": (25, 1.2, 14, 8.03, 28, 29, False, False),
}
name = sys.argv[1]
f, fno, hfov, bfl, dia, length, retro, match_fov = SPECS[name]
if os.environ.get('MATCH') is not None: match_fov = os.environ['MATCH'] == '1'
th = hfov / 2
CK, ST = f"{WORK}/{name}.ckpt.lens.json", f"{WORK}/{name}.state.json"
logf = open(f"{WORK}/{name}.log", "a")
def log(*a):
    s = time.strftime("%H:%M:%S ") + " ".join(map(str, a)); print(s, flush=True); logf.write(s + "\n"); logf.flush()

DG = [(54.153, 8.747, "N-SK16", 0), (152.522, 0.5, None, 0), (35.951, 14, "N-SK16", 0), (0, 3.777, "F2", 0),
      (22.27, 14.253, None, 0), (0, 12.428, None, 1), (-25.685, 3.777, "F2", 0), (0, 10.834, "N-SK16", 0),
      (-36.98, 0.5, None, 0), (196.417, 6.858, "N-SK16", 0), (-67.148, 57.315, None, 0)]
FRONT = [(150, 6, "N-BK7", 0), (50, 35, None, 0)]  # negative meniscus for the retrofocus lenses
F0 = max(2 * fno, 2.8)
FILTER = os.environ.get("FILTER") == "1"   # add a 1 mm N-BK7 IR filter / cover glass plate 0.8 mm before the sensor

def last_lens(system):
    """Index of the last powered lens surface (any flat plate after it is a filter)."""
    return max(i for i in range(1, system.image_index) if system.surfaces[i].curvature != 0)

def fresh():
    L = lf.OpticalSystem(f"Arducam {name} (approximation)")
    L.set_wavelengths([0.4861327, 0.5875618, 0.6562725], primary=1)
    for r, t, m, st in (FRONT if retro else []) + DG:
        L.add_surface(radius=r if r else math.inf, thickness=t, material=m, stop=bool(st))
    n = L.image_index - 1
    if FILTER:
        L.add_surface(radius=math.inf, thickness=1.0, material="N-BK7", comment="IR filter + cover glass (assumed)")
        L.add_surface(radius=math.inf, thickness=0.8)
    s = f / L.paraxial().efl
    for srf in L.surfaces[1:n + 1]:
        srf.curvature /= s
        srf.thickness *= s
    L.surfaces[n].thickness = bfl - 1.8 if FILTER else bfl
    for i in range(1, n + 1):
        if i != L.stop_index:
            opt.set_variable(L, i, "curvature")
        if i == n:
            opt.set_variable(L, i, "thickness", min=0.3)
        elif L.surfaces[i].material:
            L.surfaces[i].thickness = max(L.surfaces[i].thickness, 0.6)
            opt.set_variable(L, i, "thickness", min=0.6, max=8.0)
        else:
            L.surfaces[i].thickness = max(L.surfaces[i].thickness, 0.1)
            opt.set_variable(L, i, "thickness", min=0.1, max=20.0)
        if L.surfaces[i].material:
            opt.set_variable(L, i, "glass.nd", 1.48, 1.90)
            opt.set_variable(L, i, "glass.vd", 23.0, 75.0)
    return L

td0 = th * HALF_DIAG / HALF_W if match_fov else math.degrees(math.atan(HALF_DIAG / f))
if os.path.exists(ST):
    state = json.load(open(ST)); L = lf.load(CK); log("resume", state)
elif len(sys.argv) > 2:
    L = lf.load(sys.argv[2])
    state = dict(stage=sys.argv[3], F=float(sys.argv[4]), fs=float(sys.argv[5]), td=L.fields[-1].y / float(sys.argv[5]))
    log("start from", sys.argv[2], state)
else:
    L = fresh(); state = dict(stage="field", F=F0, fs=0.35 if retro else 1.0, td=td0); log("fresh start")
nlens = last_lens(L)
if os.environ.get("REGLASS") == "1":
    for i in range(1, nlens + 1):
        if L.surfaces[i].material:
            opt.set_variable(L, i, "glass.nd", 1.48, 1.90); opt.set_variable(L, i, "glass.vd", 23.0, 75.0)
sd_max, track_max = dia / 2 - 2.0, length + 10.0

def set_fields():
    k, td = state["fs"], state["td"]
    L.set_fields([0, 0.5 * td * k, 0.75 * td * k, (th if match_fov else 0.9 * td) * k, td * k])
    L.set_aperture("EPD", f / state["F"])

def build_merit(rings=2, arms=4):
    lean = os.environ.get("LEAN") == "1"
    if lean:
        mf = opt.default_merit(L, "spot", rings=rings, arms=arms)
        mf.add("MNCG", 0.8, 1); mf.add("MNCA", 0.05, 1); mf.add("MNEG", 0.3, 1)
    else:
        mf = opt.default_merit(L, "spot", rings=rings, arms=arms, glass_min=1.0, glass_edge=0.8, air_min=0.1,
                               air_edge=0.1, boundary_weight=10)
    mf.add("EFFL", f, -1)
    mf.add("TTHI", bfl, -1, surf=nlens, surf2=L.image_index - 1, comment="back focal distance")
    mf.add("TOTR", track_max, 1 if lean else 10, bound="<")
    for i in ([1, nlens] if lean else range(1, nlens + 1)):
        for hy, py in ((1, 1), (1, -1), (0, 1)):
            mf.add("REAR", sd_max, 1 if lean else 10, bound="<", surf=i, hy=hy, py=py)
    if match_fov:
        mf.add("REAY", HALF_W * state["fs"], -1, surf=L.image_index, hy=L.fields[3].y / L.fields[-1].y,
               comment="HFOV spec")
    else:
        mf.add("DIST", 0.0, 0.0002, field=1.0, comment="keep distortion low")
    return vig_merit(mf) if VIG else mf

def run(cycles, fine=False):
    mf = build_merit(3, 6) if fine else build_merit(); L.merit_function = mf
    return mf, opt.optimize(L, mf, cycles=cycles)

def save():
    m = L.merit_function; L.merit_function = None
    lf.save(L, CK); L.merit_function = m; json.dump(state, open(ST, "w"))

def trial(**changes):
    """Apply state changes and optimise; roll back and return None if the design breaks."""
    global L
    good, old = copy.deepcopy(L), dict(state)
    state.update(changes); set_fields()
    try:
        mf, res = run(int(os.environ.get('STEPC', '25')))
    except RuntimeError as e:
        log("  failed", changes, str(e)[:120]); L = good; state.clear(); state.update(old); set_fields(); return False
    log(f"  ok {changes}: {res}"); save(); return True

def ramp(key, target, steps):
    while abs(state[key] - target) > 1e-9:
        for s in steps:
            nxt = state[key] + s if key == "fs" else state[key] / s
            nxt = min(nxt, target) if key == "fs" else max(nxt, target)
            if trial(**{key: nxt}): break
        else:
            log(f"ramp {key} stuck at {state[key]}"); return False
    return True

def corner_angle():
    tmax = L.fields[-1].y; a, b = 0.5 * tmax, 1.6 * tmax
    for _ in range(40):
        m = 0.5 * (a + b); h = abs(L.trace(hy=m / tmax).image[0, 1])
        a, b = (m, b) if np.isfinite(h) and h < HALF_DIAG else (a, m)
    return 0.5 * (a + b)


VIG = os.environ.get("VIG") == "1"
KEEP = float(os.environ.get('KEEP', '0.6'))   # fraction of the edge-field pupil (in y) the clear apertures must pass
S_MAX = float(os.environ.get('S_MAX', '0.9'))  # largest sin(refraction angle) allowed for axial / kept edge rays
from lensforge.optimize.operands import Block, gaussian_quadrature, _wave_set, is_symmetric
from lensforge.raytrace import trace_rays, OK
from lensforge.surfaces import CircularAperture

def set_apertures(system):
    """Size every lens clear aperture to pass the axial bundle and +-KEEP of the edge-field pupil."""
    n = last_lens(system)
    for i in range(1, n + 1):
        system.surfaces[i].aperture = None
    hs = []
    for hy, py in ((0.0, 1.0), (1.0, KEEP), (1.0, -KEEP), (1.0, 0.0)):
        for w in system.wavelengths:
            r = trace_rays(system, 0.0, hy, 0.0, py, wavelength=w.value, apertures=False)
            if r.status[0] != OK:   # never size apertures from a ray that TIRs or misses
                raise RuntimeError(f"ray hy={hy} py={py} fails at surface {r.error_surface[0]}")
            hs.append(np.abs(r.positions[1:n + 1, 0, 1]))
    h = np.max(np.array(hs), axis=0) * 1.01 + 1e-3
    for i in range(1, n + 1):
        system.surfaces[i].aperture = CircularAperture(float(h[i - 1]))
    return float(np.nanmax(h))

def rays_vig(system, field=0, rings=2, arms=4):
    """RAYS (centroid reference), but rays that miss a surface count as blocked by the barrel."""
    hx, hy = system.normalized_field(int(field))
    sym = is_symmetric(system)
    px, py, q = gaussian_quadrature(rings, arms, sym)
    class C: pass
    c = C(); c.system = system
    waves, ww = _wave_set(c, None)
    bundle = []
    for wl, w in zip(waves, ww):
        r = trace_rays(system, hx, hy, px, py, wavelength=wl)
        if int(field) == 0 and not np.all(r.status == OK):
            raise ValueError("axial rays blocked")   # vignetting is only allowed off axis
        bundle.append((w, r, r.status == OK))
    sw = sum((w * q * k).sum() for w, r, k in bundle)
    if sw == 0:
        raise ValueError("all rays vignetted")
    cx = 0.0 if sym else sum(np.sum(w * q * k * np.where(k, r.x, 0)) for w, r, k in bundle) / sw
    cy = sum(np.sum(w * q * k * np.where(k, r.y, 0)) for w, r, k in bundle) / sw
    vals, wts = [], []
    for w, r, k in bundle:
        qq = w * q * k
        vals += [np.where(k, r.x - cx, 0.0), np.where(k, r.y - cy, 0.0)]
        wts += [qq, qq]
    total = sum(w * np.sum(q * k) for w, r, k in bundle)
    W = np.concatenate(wts)
    return Block(np.concatenate(vals), W, W / (2 * total))

def transmitted(system, n=15):
    """Unvignetted fraction of the edge-field pupil."""
    g = np.linspace(-1, 1, n); X, Y = np.meshgrid(g, g); m = X**2 + Y**2 <= 1
    r = trace_rays(system, 0.0, 1.0, X[m], Y[m])
    return float(np.mean(r.status == OK))

def tir_margin(system):
    """sin(refraction angle) on every lens surface for axial and kept edge-field rays (> 1 is TIR)."""
    n_lens = last_lens(system)
    vals = []
    for hy, py in ((0.0, 0.5), (0.0, 0.75), (0.0, 0.9), (0.0, 1.0), (1.0, KEEP), (1.0, -KEEP)):
        for w in system.wavelengths:
            r = trace_rays(system, 0.0, hy, 0.0, py, wavelength=w.value, apertures=False)
            nn = system.media(w.value)[0]
            for k in range(1, n_lens + 1):
                s = nn[k - 1] / nn[k] * np.linalg.norm(np.cross(r.directions[k - 1, 0], r.normals[k, 0]))
                vals.append(s if np.isfinite(s) else 0.0)
    vals = np.array(vals)
    return Block(vals, np.ones_like(vals), np.zeros_like(vals))

def vig_merit(mf):
    from lensforge.optimize.merit import Operand
    rows = [Operand("USER", sd_max, 1.0, "<", {"func": set_apertures}, "set clear apertures (max <= sd_max)")]
    for r in mf.rows:
        if r.type == "RAYS":
            rows.append(Operand("USER", 0.0, r.weight, None,
                                {"func": rays_vig, "field": r.params.get("field", 0),
                                 "rings": r.params.get("rings", 2), "arms": r.params.get("arms", 4)}, "RAYS (vignetted)"))
        elif r.type == "REAR":
            continue
        else:
            rows.append(r)
    mf.rows = rows
    mf.add("USER", S_MAX, 10, bound="<", func=tir_margin, comment="refraction angle margin (no TIR)")
    mf.add("USER", 0.5, 1 if os.environ.get("LEAN") == "1" else 10, bound=">", func=transmitted, comment="edge field >= 50% unvignetted")
    return mf

t0 = time.time()
set_fields()
if state["stage"] == "field":
    run(30); save()
    ramp("fs", 1.0, [0.1, 0.05, 0.025, 0.012])
    state["stage"] = "fnum"; save()
if state["stage"] == "fnum":
    ramp("F", fno, [float(x) for x in os.environ.get("FSTEPS", "1.12,1.06,1.03,1.015").split(",")])
    state["stage"] = "refield"; save()
if state["stage"] == "refield":
    for it in range(3):
        td_new = corner_angle() / state["fs"]; log("corner angle", td_new)
        if abs(td_new - state["td"]) < 0.05: break
        if not trial(td=td_new):
            if not trial(td=0.5 * (td_new + state["td"])): break
    state["stage"] = "hammer"; save()
if state["stage"] == "hammer":
    mf = build_merit(); L.merit_function = mf
    log("hammer:", opt.hammer(L, mf, trials=int(os.environ.get("HTRIALS", "4")), cycles=15, seed=1))
    mf, res = run(80); log("after hammer:", res); save()
    save(); m = L.merit_function; L.merit_function = None; lf.save(L, f"{WORK}/{name}_model_glass.lens.json"); L.merit_function = m
    state["stage"] = "snap1"; save()
if state["stage"] == "snap1":
    from lensforge.optimize.glass import glass_surfaces, nearest_glasses
    from lensforge.materials import ModelGlass
    for i in glass_surfaces(L):
        if not isinstance(L.library.resolve(L.surfaces[i].material), ModelGlass):
            continue
        cands = nearest_glasses(L.library.resolve(L.surfaces[i].material), L.library, 3, ["SCHOTT"])
        for spec, *_ in cands:
            good = copy.deepcopy(L)
            L.surfaces[i].material = spec
            opt.variables(L)[:] = [v for v in opt.variables(L) if not (v.surface == i and v.param.startswith("glass."))]
            try:
                mf, res = run(25); log("snap1", i, spec, res); save(); break
            except RuntimeError as e:
                log("snap1 failed", i, spec, str(e)[:80]); L = good
    state["stage"] = "snap"; save()
if state["stage"] == "snap":
    log("snap:", opt.snap_to_catalog(L, catalogs=["SCHOTT"]))
    mf, res = run(120, fine=True); log("catalog:", res)
    log(mf.table(L))
    L.merit_function = None
    if VIG:
        set_apertures(L); log("edge field transmitted", transmitted(L))
    else:
        L.update_semi_diameters(margin=0.05)
    lf.save(L, f"{WORK}/{name}.lens.json")
    state["stage"] = "done"; save()
    log(L.prescription())
if state["stage"] == "polish":
    for k in range(int(os.environ.get("POLISH", "3"))):
        mf, res = run(100, fine=True); log("polish:", res); save()
        log(mf.table(L).splitlines()[-1])
    mf = build_merit(3, 6); L.merit_function = None
    if VIG:
        set_apertures(L); log("edge field transmitted", transmitted(L))
    else:
        L.update_semi_diameters(margin=0.05)
    lf.save(L, f"{WORK}/{name}.lens.json"); state["stage"] = "done"; save()
log("done", state, f"{time.time() - t0:.0f}s")
