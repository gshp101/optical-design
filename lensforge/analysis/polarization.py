"""Polarization ray tracing with Fresnel coefficients (uncoated interfaces).

Each ray accumulates a 3x3 polarization ray-tracing matrix (Chipman's PRT
formalism) in global coordinates:

    P_k = t_s s s^T + t_p p' p^T + k' k^T,     s = k x eta / |k x eta|,  p = k x s,  p' = k' x s

with amplitude coefficients scaled by sqrt(n' cos t / n cos i) so that
|P E|^2 / |E|^2 is the power transmittance.  Mirrors are ideal (r_s = -1,
r_p = 1) unless ``mirror_index`` (complex, e.g. 1.2+7j for aluminium) is
given.  Bulk absorption and thin-film coatings are not modelled.

Input polarisation is a Jones vector (Ex, Ey) in object space, projected
onto the plane normal to each ray.
"""

from __future__ import annotations

import math

import numpy as np

from ..raytrace import trace_rays
from .common import resolve_field

POLARIZATIONS = {"x": (1, 0), "y": (0, 1), "lcp": (1 / math.sqrt(2), 1j / math.sqrt(2)),
                 "rcp": (1 / math.sqrt(2), -1j / math.sqrt(2)), "45": (1 / math.sqrt(2), 1 / math.sqrt(2))}


def fresnel(n1, n2, cos_i):
    """Amplitude coefficients (t_s, t_p, r_s, r_p) and cos of the refraction angle."""
    n1 = np.asarray(n1, complex)
    n2 = np.asarray(n2, complex)
    ci = np.asarray(cos_i, complex)
    st2 = (n1 / n2) ** 2 * (1 - ci * ci)
    ct = np.sqrt(1 - st2)
    rs = (n1 * ci - n2 * ct) / (n1 * ci + n2 * ct)
    rp = (n2 * ci - n1 * ct) / (n2 * ci + n1 * ct)
    ts = 2 * n1 * ci / (n1 * ci + n2 * ct)
    tp = 2 * n1 * ci / (n2 * ci + n1 * ct)
    return ts, tp, rs, rp, ct


def _basis(k, eta):
    s = np.cross(k, eta)
    ns = np.linalg.norm(s, axis=1)
    small = ns < 1e-12
    if small.any():  # normal incidence: any vector perpendicular to k
        alt = np.cross(k[small], np.array([1.0, 0.0, 0.0]))
        bad = np.linalg.norm(alt, axis=1) < 1e-12
        alt[bad] = np.cross(k[small][bad], np.array([0.0, 1.0, 0.0]))
        s[small] = alt
        ns = np.linalg.norm(s, axis=1)
    return s / ns[:, None]


def polarization_trace(system, hx=0.0, hy=0.0, px=0.0, py=0.0, wavelength=None, mirror_index=None):
    """Trace rays and return per-ray accumulated PRT matrices.

    Returns dict with ``P`` (N, 3, 3) complex (global frame), ``k_in``/``k_out``
    global unit directions, ``valid`` and the underlying ``trace`` result.
    """
    wl = system.primary if wavelength is None else wavelength
    r = trace_rays(system, hx, hy, px, py, wavelength=wl)
    n_media, mirror, _ = system.media(wl)
    frames = system.surface_frames()
    N = r.n_rays
    P = np.tile(np.eye(3, dtype=complex), (N, 1, 1))
    R1 = frames[1][0]
    k_in = r.directions[0] @ R1.T
    for k, i in enumerate(range(1, system.image_index), start=1):
        s = system.surfaces[i]
        if s.is_coordinate_break:
            continue
        R = frames[i][0]
        d0 = r.directions[k - 1]
        d1 = r.directions[k]
        # d0 is in this surface's frame: frames change only at coordinate breaks,
        # and the trace stores post-break directions in the new frame
        eta = r.normals[k]
        ok = np.all(np.isfinite(d1), axis=1) & np.all(np.isfinite(d0), axis=1)
        d0 = np.where(ok[:, None], d0, [0, 0, 1])
        d1 = np.where(ok[:, None], d1, [0, 0, 1])
        eta = np.where(ok[:, None], eta, [0, 0, 1])
        sv = _basis(d0, eta)
        p0 = np.cross(d0, sv)
        p1 = np.cross(d1, sv)
        ci = np.abs(np.einsum("ij,ij->i", d0, eta))
        n1, n2 = n_media[i - 1], n_media[i]
        if s.has_deflect:  # ideal lens: lossless, no polarisation change
            a_s = a_p = np.ones(N, complex)
        elif mirror[i]:
            if mirror_index is None:
                a_s, a_p = -np.ones(N, complex), np.ones(N, complex)
            else:
                _, _, a_s, a_p, _ = fresnel(n1, mirror_index, ci)
        else:
            ts, tp, _, _, ct = fresnel(n1, n2, ci)
            f = np.sqrt((n2 * ct.real) / (n1 * ci))
            a_s, a_p = ts * f, tp * f
        Pk = (a_s[:, None, None] * np.einsum("ni,nj->nij", sv, sv)
              + a_p[:, None, None] * np.einsum("ni,nj->nij", p1, p0)
              + np.einsum("ni,nj->nij", d1, d0))
        Pg = np.einsum("ij,njk,lk->nil", R, Pk, R)  # to global: R Pk R^T
        P = np.einsum("nij,njk->nik", Pg, P)
    k_out = r.directions[-1] @ frames[system.image_index][0].T
    return {"P": P, "k_in": k_in, "k_out": k_out, "valid": r.valid, "trace": r}


def _input_field(k_in, jones):
    """Object-space field: Jones (Ex, Ey) projected perpendicular to each ray."""
    E = np.zeros((k_in.shape[0], 3), complex)
    E[:, 0], E[:, 1] = jones[0], jones[1]
    E = E - np.einsum("ni,ni->n", E, k_in)[:, None] * k_in
    nrm = np.sqrt(np.sum(np.abs(E) ** 2, axis=1))
    return E / nrm[:, None]


def polarization_pupil_map(system, field=0, wavelength=None, polarization="y", n: int = 11, mirror_index=None):
    """Output polarisation state across the pupil (Zemax "Polarization Pupil Map").

    Returns per pupil point the output field (global), power transmittance,
    ellipse parameters (orientation angle in degrees, ellipticity b/a with
    sign = handedness) in the image-plane x/y projection, and the total
    transmission averaged over the pupil.
    """
    jones = POLARIZATIONS[polarization] if isinstance(polarization, str) else polarization
    hx, hy = resolve_field(system, field)
    px, py = pupil_grid_square(n)
    pr = polarization_trace(system, hx, hy, px, py, wavelength, mirror_index)
    E0 = _input_field(pr["k_in"], jones)
    E = np.einsum("nij,nj->ni", pr["P"], E0)
    T = np.sum(np.abs(E) ** 2, axis=1)
    ok = pr["valid"]
    Ex, Ey = E[:, 0], E[:, 1]
    # polarisation ellipse from Stokes parameters of the x/y projection
    S0 = np.abs(Ex) ** 2 + np.abs(Ey) ** 2
    S1 = np.abs(Ex) ** 2 - np.abs(Ey) ** 2
    S2 = 2 * np.real(Ex * np.conj(Ey))
    S3 = -2 * np.imag(Ex * np.conj(Ey))
    psi = 0.5 * np.degrees(np.arctan2(S2, S1))
    with np.errstate(invalid="ignore", divide="ignore"):
        chi = 0.5 * np.arcsin(np.clip(S3 / S0, -1, 1))
    return {"px": px, "py": py, "E": E, "transmission": np.where(ok, T, np.nan), "orientation_deg": psi,
            "ellipticity": np.tan(chi), "total_transmission": float(np.mean(np.where(ok, T, 0.0))),
            "valid": ok, "field": (hx, hy)}


def pupil_grid_square(n):
    v = np.linspace(-1, 1, n)
    X, Y = np.meshgrid(v, v)
    m = X**2 + Y**2 <= 1 + 1e-12
    return X[m], Y[m]


def transmission(system, wavelength=None, n_fields: int = 5, sampling: int = 21, mirror_index=None):
    """Polarisation-averaged power transmission (Fresnel losses and vignetting)
    vs normalised field; unpolarised = mean of two orthogonal polarisations."""
    h = np.linspace(0, 1, n_fields)
    t = np.empty(n_fields)
    for i, f in enumerate(h):
        a = polarization_pupil_map(system, (0.0, f), wavelength, "x", sampling, mirror_index)["total_transmission"]
        b = polarization_pupil_map(system, (0.0, f), wavelength, "y", sampling, mirror_index)["total_transmission"]
        t[i] = 0.5 * (a + b)
    return {"field": h, "transmission": t}


def diattenuation(system, field=0, wavelength=None, n: int = 11, mirror_index=None):
    """Diattenuation (Tmax - Tmin)/(Tmax + Tmin) of each ray's PRT matrix,
    from its singular values restricted to the plane normal to the input ray."""
    hx, hy = resolve_field(system, field)
    px, py = pupil_grid_square(n)
    pr = polarization_trace(system, hx, hy, px, py, wavelength, mirror_index)
    D = np.full(px.size, np.nan)
    for k in range(px.size):
        if not pr["valid"][k]:
            continue
        ki = pr["k_in"][k]
        a = np.cross(ki, [1.0, 0, 0]) if abs(ki[0]) < 0.9 else np.cross(ki, [0, 1.0, 0])
        a /= np.linalg.norm(a)
        b = np.cross(ki, a)
        J = pr["P"][k] @ np.column_stack([a, b])
        sv = np.linalg.svd(J, compute_uv=False)
        D[k] = (sv[0] ** 2 - sv[-1] ** 2) / (sv[0] ** 2 + sv[-1] ** 2)
    return {"px": px, "py": py, "diattenuation": D, "max": float(np.nanmax(D))}
