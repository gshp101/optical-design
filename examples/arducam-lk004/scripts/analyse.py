"""Summarise the approximate Arducam LK004 designs and draw a gallery."""
import sys, os, math, json
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
import numpy as np
import lensforge as lf
import lensforge.plot as P
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt

D = sys.argv[1]; OUT = sys.argv[2]
HALF_W, HALF_DIAG = 6.287 / 2, 7.857 / 2
SPEC = {"CS1806ZM06": (6, 1.4, 65, 8.03, 28, 28.5), "CS2308ZM05": (8, 1.4, 50, 6.50, 28, 23),
        "CS1812ZM03": (12, 1.6, 30, 7.53, 30, 29), "CS2316ZM02": (16, 1.6, 24, 7.53, 30, 29),
        "CS2325ZM01": (25, 1.2, 14, 8.03, 28, 29)}

def angle_for_height(L, h):
    tmax = L.fields[-1].y; a, b = 0.0, 1.5 * tmax
    for _ in range(50):
        m = 0.5 * (a + b)
        y = abs(L.trace(hy=m / tmax).image[0, 1])
        a, b = (m, b) if np.isfinite(y) and y < h else (a, m)
    return 0.5 * (a + b)

rows, lenses = [], []
for name in SPEC:
    p = f"{D}/{name}.lens.json"
    if os.environ.get("ONLY") and name not in os.environ["ONLY"]: continue
    if not os.path.exists(p): continue
    L = lf.load(p); lenses.append((name, L))
    par = L.paraxial()
    lastlens = L.image_index - 3
    bfd = sum(L.surfaces[i].thickness for i in range(lastlens, L.image_index))
    sd = max((s.aperture.r_max if s.aperture is not None else (s.semi_diameter or 0)) for s in L.surfaces[1:lastlens + 1])
    if all(s.semi_diameter is None for s in L.surfaces[1:lastlens + 1]) and L.surfaces[1].aperture is None: L.update_semi_diameters(margin=0.05); sd = max(s.semi_diameter for s in L.surfaces[1:lastlens + 1])
    hf = 2 * angle_for_height(L, HALF_W); df = 2 * angle_for_height(L, HALF_DIAG)
    nel = sum(1 for s in L.surfaces[1:lastlens + 1] if s.material)
    rms = [1000 * lf.spot_diagram(L, k)["rms_radius"] for k in range(len(L.fields))]
    m100 = [lf.mtf_at(L, 100, k) for k in (0, len(L.fields) - 1)]
    dist = lf.distortion(L, 1.0)
    ri = lf.analysis.metrics.relative_illumination_edge(L)
    glasses = [str(s.material) for s in L.surfaces[1:lastlens + 1] if s.material]
    rows.append(dict(name=name, spec=SPEC[name], efl=par.efl, fno=par.working_fnum, bfd=bfd, track=par.total_track,
                     sd=sd, hfov=hf, dfov=df, n=nel, rms=rms, mtf100=m100, dist=dist, ri=ri, glasses=glasses,
                     fields=[fl.y for fl in L.fields]))

lines = ["| Lens | f spec / model | F/# spec / model | HFOV spec / model | Diag FOV | Back focus spec / model | Track | Max clear dia | Elements | RMS spot centre / corner | MTF @100 lp/mm centre / corner (T,S) | Corner distortion | Corner rel. illum. |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
for r in rows:
    f, F, H, B, dia, ln = r["spec"]
    lines.append(f"| {r['name']} | {f} / {r['efl']:.2f} mm | {F} / {r['fno']:.2f} | {H}° / {r['hfov']:.1f}° | {r['dfov']:.1f}° | "
                 f"{B} / {r['bfd']:.2f} mm | {r['track']:.1f} mm | {2*r['sd']:.1f} mm | {r['n']} | "
                 f"{r['rms'][0]:.1f} / {r['rms'][-1]:.1f} µm | {r['mtf100'][0][0]:.2f} / {r['mtf100'][1][0]:.2f},{r['mtf100'][1][1]:.2f} | "
                 f"{r['dist']:+.1f}% | {100*r['ri']:.0f}% |")
open(f"{OUT}/summary_table.md", "w").write("\n".join(lines) + "\n")
json.dump(rows, open(f"{OUT}/summary.json", "w"), indent=1, default=float)
print("\n".join(lines))
for r in rows: print(r["name"], r["glasses"], [f"{x:.1f}" for x in r["rms"]])

n = len(lenses)
fig, axes = plt.subplots(n, 3, figsize=(16, 3.6 * n))
axes = np.atleast_2d(axes)
for (name, L), ax in zip(lenses, axes):
    P.layout(lf.layout(L, n_rays=5), ax=ax[0]); ax[0].set_title(f"{name}  (approximation)")
    m = lf.fft_mtf(L, field=0, max_freq=330); P.mtf(m, ax=ax[1])
    m2 = lf.fft_mtf(L, field=len(L.fields) - 1, max_freq=330)
    ax[1].plot(m2["freq"], m2["tangential"], "r--", label="corner T"); ax[1].plot(m2["freq"], m2["sagittal"], "r:", label="corner S")
    ax[1].set_title("MTF (axis solid, sensor corner red)"); ax[1].set_xlim(0, 330); ax[1].legend(fontsize=7)
    fc = lf.field_curvature(L)
    ax[2].plot(fc["field_value"], np.atleast_2d(fc["distortion_percent"])[len(np.atleast_2d(fc["distortion_percent"]))//2]); ax[2].set_xlabel("field angle (deg)")
    ax[2].set_ylabel("distortion %"); ax[2].set_title("f-tan distortion (to sensor corner)"); ax[2].grid(alpha=.3)
fig.tight_layout(); fig.savefig(f"{OUT}/lk004_gallery.png", dpi=90)
