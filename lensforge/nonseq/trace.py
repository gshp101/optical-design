"""Non-sequential ray tracing with optional ray splitting.

Rays are traced in global coordinates in any order through all objects: each
step finds the nearest face hit by every live ray, then refracts, reflects,
absorbs or records it.  Volumes are entered and left through their faces;
touching volumes (a cemented doublet) pass light directly from one glass to
the other when their faces coincide.  Objects must not otherwise overlap.

At refracting faces the unpolarised Fresnel reflectance R (or the object's
``coating`` reflectance) decides the power split.  With ``split=True`` both
the transmitted ray (power x (1 - R)) and the reflected ray (power x R) are
followed, which is what reveals ghosts and stray light; a reflected child is
only kept while its power stays above ``min_relative_intensity`` of the power
its source ray started with.  Without splitting rays follow the transmitted
path (losing R with ``fresnel=True``), and total internal reflection is
followed either way.  ``n_reflections`` counts the Fresnel (partial)
reflections a ray has taken: 0 for direct light, 2 for two-bounce ghosts.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from typing import List, Optional

import numpy as np

# segment events
REFRACT, REFLECT, TIR, MIRROR, ABSORBED, DETECTED, ESCAPED, CUTOFF, PASSED = range(9)
EVENT_NAMES = {REFRACT: "refracted", REFLECT: "split reflection", TIR: "total internal reflection",
               MIRROR: "mirror", ABSORBED: "absorbed", DETECTED: "detected", ESCAPED: "escaped",
               CUTOFF: "stopped (segments or intensity limit)", PASSED: "passed through"}


def _fresnel_R(n1, n2, cos_i):
    ci = np.clip(cos_i, 0.0, 1.0)
    st2 = (n1 / n2) ** 2 * (1 - ci * ci)
    tir = st2 >= 1.0
    ct = np.sqrt(np.clip(1 - st2, 0.0, 1.0))
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = (n1 * ci - n2 * ct) / (n1 * ci + n2 * ct)
        rp = (n2 * ci - n1 * ct) / (n2 * ci + n1 * ct)
    R = np.nan_to_num(0.5 * (rs * rs + rp * rp), nan=1.0)
    return np.where(tir, 1.0, R), tir, ct


@dataclass
class DetectorData:
    """Hits recorded on one detector (local detector coordinates)."""

    object_index: int
    detector: object
    x: np.ndarray
    y: np.ndarray
    power: np.ndarray
    n_reflections: np.ndarray
    n_tir: np.ndarray
    wavelength: np.ndarray
    source: np.ndarray
    direction: np.ndarray

    def select(self, rays="all", wavelength=None, source=None, tir=None):
        """Mask of hits: rays "all", "direct" (no Fresnel reflection), "ghost" (two or more),
        or an int (exactly that many Fresnel reflections).  ``tir`` False keeps only rays that
        never totally internally reflected, True only those that did."""
        m = np.ones(len(self.x), dtype=bool)
        if tir is not None:
            m &= (self.n_tir > 0) == bool(tir)
        if rays == "direct":
            m &= self.n_reflections == 0
        elif rays == "ghost":
            m &= self.n_reflections >= 2
        elif isinstance(rays, (int, np.integer)):
            m &= self.n_reflections == rays
        elif rays != "all":
            raise ValueError("rays must be 'all', 'direct', 'ghost' or a number of reflections")
        if wavelength is not None:
            m &= np.isclose(self.wavelength, wavelength)
        if source is not None:
            m &= self.source == source
        return m

    def total_power(self, rays="all", **kw):
        return float(self.power[self.select(rays, **kw)].sum())

    def image(self, rays="all", **kw):
        """Irradiance map (power per unit area), shape (ny, nx), row 0 at -y."""
        d = self.detector
        m = self.select(rays, **kw)
        ex = np.linspace(-d.half_x, d.half_x, d.nx + 1)
        ey = np.linspace(-d.half_y, d.half_y, d.ny + 1)
        H, _, _ = np.histogram2d(self.y[m], self.x[m], bins=[ey, ex], weights=self.power[m])
        return H / ((ex[1] - ex[0]) * (ey[1] - ey[0]))

    def centroid(self, rays="all", **kw):
        m = self.select(rays, **kw)
        w = self.power[m]
        if w.sum() <= 0:
            return np.nan, np.nan
        return float(np.average(self.x[m], weights=w)), float(np.average(self.y[m], weights=w))

    def rms_radius(self, rays="all", **kw):
        m = self.select(rays, **kw)
        w = self.power[m]
        if w.sum() <= 0:
            return np.nan
        cx, cy = self.centroid(rays, **kw)
        return float(np.sqrt(np.average((self.x[m] - cx) ** 2 + (self.y[m] - cy) ** 2, weights=w)))

    @property
    def extent(self):
        d = self.detector
        return (-d.half_x, d.half_x, -d.half_y, d.half_y)


@dataclass
class NSTraceResult:
    """Everything a non-sequential trace produced.

    ``segments`` holds one row per straight ray segment: ``start``, ``end``
    (global), ``power`` carried, ``ray`` / ``parent`` ids, ``source``,
    ``wavelength``, ``n_reflections``, the ``object`` hit at the end (-1 none)
    and the ``event`` there (see ``EVENT_NAMES``).
    """

    system: object
    segments: dict
    detectors: List[DetectorData]
    launched_power: float
    n_launched: int
    n_rays_total: int
    settings: dict = dc_field(default_factory=dict)

    def detector(self, det=0) -> DetectorData:
        """Detector data by detector number (0 = first detector), object index or object."""
        k = self.system.detector_index(det)
        for d in self.detectors:
            if d.object_index == k:
                return d
        raise KeyError(det)

    def power_by_event(self):
        ev = self.segments["event"]
        pw = self.segments["power"]
        return {EVENT_NAMES[e]: float(pw[ev == e].sum()) for e in (ABSORBED, DETECTED, ESCAPED, CUTOFF)}

    def summary(self) -> str:
        pb = self.power_by_event()
        lines = [f"Non-sequential trace of {self.system.name or 'scene'}: {self.n_launched} rays launched, "
                 f"{self.n_rays_total} rays in total (with split rays), {len(self.segments['power'])} segments.",
                 f"Launched power {self.launched_power:.6g}.",
                 "Power ending: " + ", ".join(f"{k} {v:.4g}" for k, v in pb.items()) + "."]
        for d in self.detectors:
            o = d.detector
            name = o.comment or f"object {d.object_index + 1}"
            lines.append(f"Detector {name}: {len(d.x)} hits, total {d.total_power():.6g}, direct "
                         f"{d.total_power('direct'):.6g}, ghosts (2+ reflections) {d.total_power('ghost'):.4g}; "
                         f"RMS radius {d.rms_radius():.4g}")
        return "\n".join(lines)


def _object_tables(system, wavelengths):
    objs = system.objects
    W = len(wavelengths)
    n_tab = np.ones((len(objs) + 1, W))
    for w, wl in enumerate(wavelengths):
        n_tab[0, w] = system.index(None, wl)
        for k, o in enumerate(objs):
            n_tab[k + 1, w] = system.index(o.material, wl) if o.is_volume else n_tab[0, w]
    return n_tab


def launch(system, seed=0):
    """Rays of every source: (P, D, power, wavelength index into ``system.wavelengths``, source index)."""
    rng = np.random.default_rng(seed)
    wls = system.wavelengths
    Ps, Ds, pw, wi, si = [], [], [], [], []
    for k, s in enumerate(system.sources):
        P, D, p, w = s.rays(rng)
        Ps.append(P)
        Ds.append(D)
        pw.append(p)
        wi.append(np.array([wls.index(s.wavelengths[j]) for j in w], dtype=int))
        si.append(np.full(len(P), k))
    if not Ps:
        z = np.zeros((0, 3))
        return z, z, np.zeros(0), np.zeros(0, int), np.zeros(0, int)
    return np.concatenate(Ps), np.concatenate(Ds), np.concatenate(pw), np.concatenate(wi), np.concatenate(si)


def trace(system, split: bool = False, fresnel: bool = True, min_relative_intensity: float = 1e-6,
          max_segments: int = 100, max_rays: int = 2_000_000, seed: int = 0, rays=None,
          escape_length: Optional[float] = None, record_segments: bool = True) -> NSTraceResult:
    """Trace all sources of ``system`` (or explicit ``rays``) non-sequentially.

    ``rays``: optional (P, D, power, wavelength_um) to launch instead of the
    sources (P, D global (N, 3); power (N,) or scalar; one wavelength or (N,)).
    """
    objs = system.objects
    if rays is not None:
        P, D, pw, wl_um = rays
        P = np.atleast_2d(np.asarray(P, float))
        D = np.atleast_2d(np.asarray(D, float))
        N = len(P)
        pw = np.broadcast_to(np.asarray(pw, float), (N,)).copy()
        wl_um = np.broadcast_to(np.asarray(wl_um, float), (N,))
        wls = sorted(set(wl_um.tolist()))
        wi = np.array([wls.index(w) for w in wl_um], dtype=int)
        si = np.full(N, -1)
    else:
        wls = system.wavelengths
        P, D, pw, wi, si = launch(system, seed)
        N = len(P)
    D = D / np.linalg.norm(D, axis=1, keepdims=True)
    n_tab = _object_tables(system, wls)
    wls_arr = np.array(wls)
    launched = float(pw.sum())
    L_esc = escape_length if escape_length is not None else 0.25 * system.extent()

    # per-object geometry, built once
    poses = [(o.R, o.origin) for o in objs]
    faces = [o.faces() for o in objs]
    actions = [o.action for o in objs]
    is_vol = np.array([o.is_volume for o in objs] + [False])  # index -1 -> False

    # live ray state
    ray_id = np.arange(N)
    parent = np.full(N, -1)
    p0 = pw.copy()  # power each ray's ancestor started with
    medium = np.full(N, -1)
    nref = np.zeros(N, dtype=int)
    ntir = np.zeros(N, dtype=int)
    nseg = np.zeros(N, dtype=int)
    next_id = N

    seg = {k: [] for k in ("start", "end", "power", "ray", "parent", "source", "wavelength", "n_reflections",
                           "object", "event")}
    dets = {k: {f: [] for f in ("x", "y", "power", "n_reflections", "n_tir", "wavelength", "source", "direction")}
            for k, o in enumerate(objs) if o.is_detector}

    def record(mask, end, obj, event):
        if not record_segments and event not in (ABSORBED, DETECTED, ESCAPED, CUTOFF):
            return
        if not np.any(mask):
            return
        seg["start"].append(P[mask])
        seg["end"].append(end[mask])
        seg["power"].append(pw[mask])
        seg["ray"].append(ray_id[mask])
        seg["parent"].append(parent[mask])
        seg["source"].append(si[mask])
        seg["wavelength"].append(wls_arr[wi[mask]])
        seg["n_reflections"].append(nref[mask])
        seg["object"].append(np.broadcast_to(obj, P.shape[:1])[mask] if np.ndim(obj) else np.full(mask.sum(), obj))
        seg["event"].append(np.full(mask.sum(), event))

    total_rays = N
    for _ in range(100000):
        if len(P) == 0:
            break
        M = len(objs)
        T = np.full((len(P), max(M, 1)), np.inf)
        F = np.zeros((len(P), max(M, 1)), dtype=int)
        for k in range(M):
            R, O = poses[k]
            Pl, Dl = (P - O) @ R, D @ R
            for f, face in enumerate(faces[k]):
                t = face.intersect(Pl, Dl)
                t = np.where(np.isnan(t), np.inf, t)
                better = t < T[:, k]
                T[better, k] = t[better]
                F[better, k] = f
        k_hit = np.argmin(T, axis=1)
        t_hit = T[np.arange(len(P)), k_hit]
        hit = np.isfinite(t_hit)
        G = P + np.where(hit, t_hit, L_esc)[:, None] * D

        # rays that leave the scene
        esc = ~hit
        record(esc, G, -1, ESCAPED)

        # second object hit at (almost) the same point: shared faces of touching volumes
        T2 = T.copy()
        T2[np.arange(len(P)), k_hit] = np.inf
        k2 = np.argmin(T2, axis=1) if M > 1 else np.full(len(P), -1)
        t2 = T2[np.arange(len(P)), k2] if M > 1 else np.full(len(P), np.inf)
        with np.errstate(invalid="ignore"):
            coincident = hit & np.isfinite(t2) & (np.abs(t2 - t_hit) <= 1e-6 * (1 + np.abs(t_hit)))

        # normals (global) at the hits
        Nrm = np.zeros_like(P)
        for k in range(M):
            mk = hit & (k_hit == k)
            if not mk.any():
                continue
            R, O = poses[k]
            Gl = (G[mk] - O) @ R
            fk = F[mk, k]
            nl = np.zeros_like(Gl)
            for f, face in enumerate(faces[k]):
                mf = fk == f
                if mf.any():
                    nl[mf] = face.normal(Gl[mf])
            Nrm[mk] = nl @ R.T

        newP, newD = G.copy(), D.copy()
        new_pw, new_med, new_nref, new_ntir = pw.copy(), medium.copy(), nref.copy(), ntir.copy()
        alive = hit.copy()
        children = []  # (mask, D, power, medium)

        act = np.array([actions[k] for k in k_hit]) if len(P) else np.array([])
        cos_dn = np.einsum("ij,ij->i", D, Nrm)
        Nin = np.where((cos_dn > 0)[:, None], -Nrm, Nrm)  # normal facing the incoming ray
        cos_i = np.abs(cos_dn)
        reflected = D + 2 * cos_i[:, None] * Nin

        # detectors
        mdet = hit & (act == "detect")
        if mdet.any():
            for k in np.unique(k_hit[mdet]):
                m = mdet & (k_hit == k)
                R, O = poses[k]
                Gl = (G[m] - O) @ R
                d = dets[k]
                d["x"].append(Gl[:, 0])
                d["y"].append(Gl[:, 1])
                d["power"].append(pw[m])
                d["n_reflections"].append(nref[m])
                d["n_tir"].append(ntir[m])
                d["wavelength"].append(wls_arr[wi[m]])
                d["source"].append(si[m])
                d["direction"].append(D[m] @ R)
                if objs[k].transparent:
                    record(m, G, k, PASSED)
                else:
                    record(m, G, k, DETECTED)
                    alive &= ~m

        mabs = hit & (act == "absorb")
        record(mabs, G, k_hit, ABSORBED)
        alive &= ~mabs

        mpass = hit & (act == "pass")
        record(mpass, G, k_hit, PASSED)

        mmir = hit & (act == "mirror")
        if mmir.any():
            record(mmir, G, k_hit, MIRROR)
            refl = np.array([getattr(objs[k], "reflectance", 1.0) for k in k_hit[mmir]])
            newD[mmir] = reflected[mmir]
            new_pw[mmir] = pw[mmir] * refl

        mref = hit & (act == "refract")
        if mref.any():
            idx = np.flatnonzero(mref)
            kh = k_hit[idx]
            inside = medium[idx] == kh
            other = np.where(coincident[idx] & is_vol[k2[idx]], k2[idx], -1)
            m2 = np.where(inside, np.where(other != kh, other, -1), kh)
            n1 = n_tab[medium[idx] + 1, wi[idx]]
            n2 = n_tab[m2 + 1, wi[idx]]
            R, tir, ct = _fresnel_R(n1, n2, cos_i[idx])
            coat = np.array([objs[k].coating if objs[k].coating is not None else np.nan for k in kh])
            R = np.where(np.isnan(coat) | tir, R, coat)
            eta = n1 / n2
            Dt = eta[:, None] * D[idx] + (eta * cos_i[idx] - ct)[:, None] * Nin[idx]
            Dt /= np.linalg.norm(Dt, axis=1, keepdims=True)
            # TIR: reflect fully
            ti = idx[tir]
            record(np.isin(np.arange(len(P)), ti), G, k_hit, TIR)
            newD[ti] = reflected[ti]
            new_ntir[ti] += 1
            # transmission
            tr = idx[~tir]
            record(np.isin(np.arange(len(P)), tr), G, k_hit, REFRACT)
            newD[tr] = Dt[~tir]
            new_med[tr] = m2[~tir]
            if fresnel or split:
                new_pw[tr] = pw[tr] * (1 - R[~tir])
            if split:
                cpow = pw[tr] * R[~tir]
                keep = (cpow >= min_relative_intensity * p0[tr]) & (cpow > 0)
                if keep.any():
                    ci = tr[keep]
                    children.append((ci, reflected[ci], cpow[keep]))

        # bookkeeping for continuing rays
        nseg_new = nseg + 1
        weak = new_pw < min_relative_intensity * p0
        long_ = nseg_new >= max_segments
        stop = alive & (weak | long_)
        if stop.any():
            # record a zero-length cutoff marker carrying the remaining power
            P_save, pw_save = P, pw
            P, pw = G, new_pw
            record(stop, G, k_hit, CUTOFF)
            P, pw = P_save, pw_save
        alive &= ~stop

        nP = [newP[alive]]
        nD = [newD[alive]]
        npw = [new_pw[alive]]
        nmed = [new_med[alive]]
        nnref = [new_nref[alive]]
        nntir = [new_ntir[alive]]
        nnseg = [nseg_new[alive]]
        nid = [ray_id[alive]]
        npar = [parent[alive]]
        np0 = [p0[alive]]
        nwi = [wi[alive]]
        nsi = [si[alive]]
        for ci, cD, cp in children:
            room = max(0, max_rays - total_rays)
            ci, cD, cp = ci[:room], cD[:room], cp[:room]
            if len(ci) == 0:
                continue
            ok = nseg_new[ci] < max_segments
            ci, cD, cp = ci[ok], cD[ok], cp[ok]
            nP.append(G[ci])
            nD.append(cD)
            npw.append(cp)
            nmed.append(medium[ci])
            nnref.append(nref[ci] + 1)
            nntir.append(ntir[ci])
            nnseg.append(nseg_new[ci])
            nid.append(np.arange(next_id, next_id + len(ci)))
            npar.append(ray_id[ci])
            np0.append(p0[ci])
            nwi.append(wi[ci])
            nsi.append(si[ci])
            next_id += len(ci)
            total_rays += len(ci)
        P, D = np.concatenate(nP), np.concatenate(nD)
        pw, medium = np.concatenate(npw), np.concatenate(nmed)
        nref, nseg, ntir = np.concatenate(nnref), np.concatenate(nnseg), np.concatenate(nntir)
        ray_id, parent, p0 = np.concatenate(nid), np.concatenate(npar), np.concatenate(np0)
        wi, si = np.concatenate(nwi), np.concatenate(nsi)

    def cat(v, shape=(0,)):
        return np.concatenate(v) if v else np.zeros(shape)

    segments = {k: cat(v, (0, 3) if k in ("start", "end") else (0,)) for k, v in seg.items()}
    for k in ("ray", "parent", "source", "n_reflections", "object", "event"):
        segments[k] = segments[k].astype(int)
    det_out = []
    for k, d in dets.items():
        det_out.append(DetectorData(k, objs[k], cat(d["x"]), cat(d["y"]), cat(d["power"]),
                                    cat(d["n_reflections"]).astype(int), cat(d["n_tir"]).astype(int),
                                    cat(d["wavelength"]),
                                    cat(d["source"]).astype(int), cat(d["direction"], (0, 3))))
    return NSTraceResult(system, segments, det_out, launched, N, total_rays,
                         {"split": split, "fresnel": fresnel, "min_relative_intensity": min_relative_intensity,
                          "max_segments": max_segments, "seed": seed})
