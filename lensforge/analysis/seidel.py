"""Third-order (Seidel) aberrations from the paraxial marginal and chief rays.

Per surface and summed, in lens units (Welford's notation, as reported by
Zemax "Seidel Coefficients"):

S1 spherical, S2 coma, S3 astigmatism, S4 Petzval, S5 distortion,
CL axial colour, CT lateral colour.

    A = n i = n (u + y c),  Abar = n (ubar + ybar c),  H = n (ubar y - u ybar)
    S1 = -A^2 y d(u/n)        S2 = -A Abar y d(u/n)    S3 = -Abar^2 y d(u/n)
    S4 = -H^2 c d(1/n)        S5 = (Abar / A)(S3 + S4)  (evaluated in a form valid for A = 0)
    CL = A y d(dn/n)          CT = Abar y d(dn/n)
    aspheric terms: dS1 = 8 b4 y^4 (n' - n), dS2 = dS1 (ybar/y), dS3 = dS1 (ybar/y)^2, dS5 = dS1 (ybar/y)^3
    with b4 the r^4 sag coefficient beyond the paraxial sphere.

Wavefront coefficients (lensforge OPD sign, waves at the primary wavelength):
W040 = S1/8, W131 = S2/2, W222 = S3/2, W220 = (S3+S4)/4 (sagittal), W220P = S4/4,
W311 = S5/2, W020 = CL/2, W111 = CT, so that

    W(H, rho, theta) = W040 rho^4 + W131 H rho^3 cos + W222 H^2 rho^2 cos^2 + W220 H^2 rho^2 + W311 H^3 rho cos

lensforge OPD maps are referenced to the real chief ray, so they contain no
W311 (distortion) tilt; compare W311 with :func:`lensforge.distortion` instead.

Transverse (T*) and longitudinal (L*) third-order aberrations are image-space
ray errors at full aperture / field (lens units).  Ideal ("paraxial")
surfaces contribute nothing; diffractive phase terms and odd/XY polynomial
departures are not included (listed under ``notes``).
"""

from __future__ import annotations

import math

import numpy as np

from ..paraxial import ParaxialAnalysis


def _quartic_departure(s):
    """r^4 sag coefficient beyond the paraxial sphere (y section)."""
    kind = s.kind
    c = getattr(s, "curvature", 0.0)
    k = getattr(s, "conic", 0.0)
    cp = s.paraxial_curvature
    q = (1 + k) * c**3 / 8
    if kind in ("EVENASPH", "TOROIDAL"):
        co = list(getattr(s, "coefficients", []))
        q += co[1] if len(co) > 1 else 0.0
    return q - cp**3 / 8


def seidel(system, wavelength=None):
    """Seidel sums.  Returns a dict with per-surface arrays (``surface`` numbers)
    and totals for S1..S5, CL, CT, wavefront, transverse and longitudinal terms."""
    sysm = system
    lam = sysm.primary if wavelength is None else wavelength
    par = ParaxialAnalysis(sysm, lam)
    phi, ns = par.phi, par.n
    last = par.last
    t0 = sysm.object.thickness
    ze = par.entrance_pupil_position
    r = par.entrance_pupil_radius
    kind, a, b = par.object_slope_for_field(0.0, 1.0)
    if sysm.object_at_infinity:
        ym, num = r, 0.0
        yc, nuc = -ze * b, ns[0] * b
    else:
        u = 1.0 / (t0 + ze)
        ym, num = r * u * t0, r * ns[0] * u
        uc = -1.0 / (t0 + ze)
        yc, nuc = (1.0 + uc * t0) * b, ns[0] * uc * b
    H = nuc * ym - num * yc

    wls = sorted(w.value for w in sysm.wavelengths)
    lam_s, lam_l = wls[0], wls[-1]
    n_s, n_l = sysm.media(lam_s)[2], sysm.media(lam_l)[2]

    keys = ("S1", "S2", "S3", "S4", "S5", "CL", "CT")
    per = {k: np.zeros(last + 1) for k in keys}
    notes = []
    for i in range(1, last + 1):
        s = sysm.surfaces[i]
        n0, n1 = ns[i - 1], ns[i]
        num_a = num - ym * phi[i]
        nuc_a = nuc - yc * phi[i]
        if not s.is_coordinate_break and not s.has_deflect:
            c = s.paraxial_curvature
            A = num + n0 * ym * c
            Ab = nuc + n0 * yc * c
            du = num_a / n1**2 - num / n0**2
            d1 = 1 / n1 - 1 / n0
            d2 = 1 / n1**2 - 1 / n0**2
            S1 = -A * A * ym * du
            S2 = -A * Ab * ym * du
            S3 = -Ab * Ab * ym * du
            S4 = -H * H * c * d1
            S5 = -Ab * Ab * H * d2 + Ab * H * c * yc * d1 - Ab * Ab * yc * du
            q = _quartic_departure(s)
            if q != 0.0 and ym != 0.0:
                dS = 8 * q * ym**4 * (n1 - n0)
                e = yc / ym
                S1 += dS
                S2 += dS * e
                S3 += dS * e * e
                S5 += dS * e**3
            dn0, dn1 = n_s[i - 1] - n_l[i - 1], n_s[i] - n_l[i]
            dd = dn1 / n1 - dn0 / n0
            for k, v in zip(keys, (S1, S2, S3, S4, S5, A * ym * dd, Ab * ym * dd)):
                per[k][i] = v
            if s.has_phase:
                notes.append(f"surface {i}: diffractive phase not included")
            if s.kind in ("ODDASPH", "XYPOLY"):
                notes.append(f"surface {i}: {s.kind} polynomial terms not included")
        num, nuc = num_a, nuc_a
        if i < last:
            ym = ym + s.thickness * num / n1
            yc = yc + s.thickness * nuc / n1

    nu_img = num  # n'u' of the marginal ray in image space
    u_img = nu_img / ns[last]
    wl = lam * sysm.wavelength_scale
    tot = {k: float(v.sum()) for k, v in per.items()}

    def wave(S):
        return {"W040": S["S1"] / 8, "W131": S["S2"] / 2, "W222": S["S3"] / 2, "W220": (S["S3"] + S["S4"]) / 4,
                "W220P": S["S4"] / 4, "W220T": (3 * S["S3"] + S["S4"]) / 4, "W311": S["S5"] / 2,
                "W020": S["CL"] / 2, "W111": S["CT"]}

    def trans(S):
        k = 1.0 / (2 * nu_img) if nu_img else math.nan
        t = {"TSPH": k * S["S1"], "TTCO": 3 * k * S["S2"], "TSCO": k * S["S2"], "TAST": 2 * k * S["S3"],
             "TPFC": k * S["S4"], "TSFC": k * (S["S3"] + S["S4"]), "TTFC": k * (3 * S["S3"] + S["S4"]),
             "TDIS": k * S["S5"], "TAXC": 2 * k * S["CL"], "TLAC": 2 * k * S["CT"]}
        lon = {"L" + key[1:]: -v / u_img for key, v in t.items() if key in ("TSPH", "TAST", "TPFC", "TSFC", "TTFC", "TAXC")}
        return t, lon

    wave_per = {k: np.array(v) for k, v in wave(per).items()}
    t_tot, l_tot = trans(tot)
    return {
        "surface": np.arange(last + 1),
        "per_surface": per,
        "totals": tot,
        "wavefront_per_surface": {k: v / wl for k, v in wave_per.items()},
        "wavefront": {k: v / wl for k, v in wave(tot).items()},
        "transverse": t_tot,
        "longitudinal": l_tot,
        "lagrange_invariant": float(H),
        "image_nu": float(nu_img),
        "wavelength": lam,
        "color_wavelengths": (lam_s, lam_l),
        "notes": notes,
    }


def seidel_table(system, wavelength=None) -> str:
    """Text table of per-surface Seidel coefficients (like Zemax's report)."""
    r = seidel(system, wavelength)
    keys = ("S1", "S2", "S3", "S4", "S5", "CL", "CT")
    lines = ["Surf " + "".join(f"{k:>13}" for k in keys)]
    for i in r["surface"][1:]:
        lines.append(f"{i:>4} " + "".join(f"{r['per_surface'][k][i]:13.6g}" for k in keys))
    lines.append(" TOT " + "".join(f"{r['totals'][k]:13.6g}" for k in keys))
    lines.append("")
    lines.append("Wavefront (waves): " + ", ".join(f"{k}={v:.5g}" for k, v in r["wavefront"].items()))
    lines.append("Transverse: " + ", ".join(f"{k}={v:.5g}" for k, v in r["transverse"].items()))
    lines.append("Longitudinal: " + ", ".join(f"{k}={v:.5g}" for k, v in r["longitudinal"].items()))
    lines.extend(r["notes"])
    return "\n".join(lines)
