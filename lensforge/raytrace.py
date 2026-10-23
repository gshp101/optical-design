"""Vectorised real (exact) sequential ray tracing.

The engine traces N rays at one wavelength through all surfaces with NumPy,
recording intersection points, directions, normals and cumulative optical path
at every surface.  Everything that needs real rays (spot diagrams, fans, OPD,
MTF, optimisation merit functions) is built on :func:`trace` and
:func:`trace_rays`.

Pupil coordinates (px, py) and field coordinates (hx, hy) are normalised to
[-1, 1], as in common design codes.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

import numpy as np

from .paraxial import ParaxialAnalysis

OK, MISS, TIR, VIGNETTED = 0, 1, 2, 3
ERROR_NAMES = {OK: "ok", MISS: "missed surface", TIR: "total internal reflection", VIGNETTED: "vignetted"}


@dataclass
class TraceResult:
    """Result of tracing N rays through S surfaces (index 0 = start point).

    Arrays: ``positions`` (S, N, 3) in each surface's local frame,
    ``directions`` (S, N, 3) unit vectors after each surface, ``normals``
    (S, N, 3), ``opl`` (S, N) cumulative optical path in lens units.
    ``status`` (N) holds the first error code and ``error_surface`` (N) where
    it happened (-1 if none).  ``valid`` is True for rays that reached the
    final surface unvignetted.
    """

    system: object
    wavelength: float
    positions: np.ndarray
    directions: np.ndarray
    normals: np.ndarray
    opl: np.ndarray
    status: np.ndarray
    error_surface: np.ndarray

    @property
    def valid(self):
        return self.status == OK

    @property
    def n_rays(self):
        return self.positions.shape[1]

    @property
    def image(self):
        """(N, 3) positions on the last traced surface."""
        return self.positions[-1]

    @property
    def x(self):
        return self.positions[-1, :, 0]

    @property
    def y(self):
        return self.positions[-1, :, 1]

    @property
    def z(self):
        return self.positions[-1, :, 2]

    @property
    def direction(self):
        return self.directions[-1]

    def global_positions(self):
        """(S, N, 3) positions in global coordinates (surface 1 vertex = origin).

        The start points (index 0) are expressed in surface 1's frame.
        """
        frames = self.system.surface_frames()
        out = np.empty_like(self.positions)
        R1, O1 = frames[1]
        for s in range(self.positions.shape[0]):
            fr = frames[s] if s > 0 else (R1, O1)
            if s == 0 or fr is None:
                fr = (R1, O1)
            R, O = fr
            out[s] = self.positions[s] @ R.T + O
        return out


def _as_array(a):
    return np.atleast_1d(np.asarray(a, dtype=float))


def _incoming_conjugate(system, index, wavelength):
    """Signed distance from surface ``index`` to the paraxial object point of the
    beam arriving there (inf when collimated), from the paraxial marginal ray."""
    par = ParaxialAnalysis(system, wavelength)
    Y, NU = par._marginal_unit()
    k = index - 1  # position of this surface in the 1..last arrays
    if k >= len(Y):
        return math.inf
    if index == 1:
        nu_in = 0.0 if system.object_at_infinity else par.n_object / (
            system.object.thickness + par.entrance_pupil_position)
    else:
        nu_in = NU[k - 1]
    if abs(nu_in) < 1e-300:
        return math.inf
    return float(Y[k] * par.n[index - 1] / nu_in)


def trace(system, P, D, wavelength, opl0=None, first: int = 1, last: Optional[int] = None,
          apertures: bool = True) -> TraceResult:
    """Trace rays starting at points P with unit directions D (both (N, 3)),
    expressed in the frame of surface ``first`` *before* it (i.e. the frame
    obtained after applying the thickness of surface ``first - 1``).

    ``wavelength`` is in micrometres.
    """
    sysm = system
    last = sysm.image_index if last is None else last
    P = np.array(P, dtype=float).reshape(-1, 3)
    D = np.array(D, dtype=float).reshape(-1, 3)
    D = D / np.linalg.norm(D, axis=1, keepdims=True)
    N = P.shape[0]
    n_media, mirror, _ = sysm.media(wavelength)
    wl = wavelength * sysm.wavelength_scale

    nsurf = last - first + 2
    pos = np.full((nsurf, N, 3), np.nan)
    dirs = np.full((nsurf, N, 3), np.nan)
    nrm = np.full((nsurf, N, 3), np.nan)
    opl = np.full((nsurf, N), np.nan)
    status = np.zeros(N, dtype=np.int8)
    err_surf = np.full(N, -1, dtype=np.int32)

    cur_opl = np.zeros(N) if opl0 is None else _as_array(opl0) * np.ones(N)
    pos[0], dirs[0], opl[0] = P, D, cur_opl
    nrm[0] = [0, 0, 1]
    alive = np.ones(N, dtype=bool)  # geometrically traceable

    def fail(mask, code, surf):
        new = mask & (status == OK)
        status[new] = code
        err_surf[new] = surf

    for k, i in enumerate(range(first, last + 1), start=1):
        s = sysm.surfaces[i]
        n1 = n_media[i - 1]
        if k > 1:
            P = P - np.array([0.0, 0.0, sysm.surfaces[i - 1].thickness])

        if s.is_coordinate_break:
            P, D = s.transform(P, D)
            # move to the new z = 0 plane (no optical effect)
            with np.errstate(divide="ignore", invalid="ignore"):
                t = -P[:, 2] / D[:, 2]
            t = np.where(np.isfinite(t), t, 0.0)
            P = P + t[:, None] * D
            cur_opl = cur_opl + n1 * t
            pos[k], dirs[k], opl[k] = P, D, cur_opl
            nrm[k] = [0, 0, 1]
            continue

        t, ok = s.intersect(P, D)
        ok &= alive
        fail(~ok & alive, MISS, i)
        alive &= ok
        t = np.where(alive, t, np.nan)
        P = P + t[:, None] * D
        cur_opl = cur_opl + n1 * t
        x, y = P[:, 0], P[:, 1]

        if apertures and s.aperture is not None:
            inside = s.aperture.inside(x, y)
            fail(alive & ~inside, VIGNETTED, i)

        Nv = s.normal(x, y)
        cos_i = np.einsum("ij,ij->i", D, Nv)
        Dt = D - cos_i[:, None] * Nv
        sgn = np.where(cos_i >= 0, 1.0, -1.0)

        if s.has_phase:
            dopl, gx, gy = s.phase(x, y, wl, wavelength_um=wavelength)
            g = np.stack([gx, gy, np.zeros_like(gx)], axis=1)
            g = g - np.einsum("ij,ij->i", g, Nv)[:, None] * Nv
            cur_opl = cur_opl + dopl
        else:
            g = 0.0

        if i == sysm.image_index:
            pass  # image: no change of direction
        elif s.has_deflect:
            D, dopl = s.deflect(P, D, n1, n_media[i], _incoming_conjugate(sysm, i, wavelength))
            cur_opl = cur_opl + dopl
        elif mirror[i]:
            Dt2 = Dt + g / n1
            c2 = 1.0 - np.einsum("ij,ij->i", Dt2, Dt2)
            bad = c2 < 0
            fail(alive & bad, TIR, i)
            D = Dt2 - (sgn * np.sqrt(np.where(bad, 0.0, c2)))[:, None] * Nv
        else:
            n2 = n_media[i]
            Dt2 = (n1 * Dt + g) / n2
            c2 = 1.0 - np.einsum("ij,ij->i", Dt2, Dt2)
            bad = c2 < 0
            fail(alive & bad, TIR, i)
            alive &= ~bad
            D = Dt2 + (sgn * np.sqrt(np.where(bad, 0.0, c2)))[:, None] * Nv
            D = np.where(alive[:, None], D, np.nan)

        pos[k], dirs[k], nrm[k], opl[k] = P, D, Nv, cur_opl

    return TraceResult(sysm, wavelength, pos, dirs, nrm, opl, status, err_surf)


# ---------------------------------------------------------------------------
# Ray generation from field / pupil coordinates
# ---------------------------------------------------------------------------

class RayGenerator:
    """Builds object-space rays for normalised field and pupil coordinates,
    with paraxial or real ray aiming."""

    def __init__(self, system, wavelength: Optional[float] = None, aiming: Optional[str] = None):
        self.system = system
        self.wavelength = system.primary if wavelength is None else wavelength
        # pupils are defined at the primary wavelength
        self.par = ParaxialAnalysis(system)
        self.z_ep = self.par.entrance_pupil_position
        self.r_ep = self.par.entrance_pupil_radius
        self.r_stop = self.par.stop_radius
        self.aiming = (aiming or system.ray_aiming).lower()
        n, _, _ = system.media(self.wavelength)
        self.n0 = n[0]
        if not math.isfinite(self.z_ep):
            raise NotImplementedError("Object-space telecentric systems are not supported yet")

    # object description ---------------------------------------------------
    def object_spec(self, hx, hy):
        sysm = self.system
        if sysm.field_type == "REAL_IMAGE_HEIGHT":
            return self._solve_real_image_height(hx, hy)
        return self.par.object_slope_for_field(hx, hy)

    def _rays_from_aim(self, spec, ax, ay):
        """Rays toward aim points (ax, ay) on the paraxial entrance pupil plane."""
        kind, a, b = spec[:3]
        ax, ay = np.broadcast_arrays(_as_array(ax), _as_array(ay))
        a = np.broadcast_to(a, ax.shape)
        b = np.broadcast_to(b, ax.shape)
        z_ep = self.z_ep
        A = np.stack([ax, ay, np.full(ax.shape, z_ep)], axis=1)
        if kind == "angle":
            D = np.stack([a, b, np.ones(ax.shape)], axis=1)
            D /= np.linalg.norm(D, axis=1, keepdims=True)
            z0 = min(z_ep, 0.0)
            t = (z0 - z_ep) / D[:, 2]
            P = A + t[:, None] * D
            ref = np.array([0.0, 0.0, z_ep])
            opl0 = self.n0 * np.einsum("ij,ij->i", P - ref, D)
        else:
            # ("point", x, y) sits on the object surface; ("point", x, y, z) anywhere
            # in object space (surface 1 frame)
            z0 = spec[3] if len(spec) > 3 else -self.system.object.thickness
            P = np.stack([a, b, np.full(ax.shape, z0)], axis=1)
            D = A - P
            if z_ep < z0:  # virtual pupil in front of the point: light still travels +z
                D = -D
            D /= np.linalg.norm(D, axis=1, keepdims=True)
            opl0 = np.zeros(ax.shape)
        return P, D, opl0

    def _stop_coords(self, spec, ax, ay):
        P, D, opl0 = self._rays_from_aim(spec, ax, ay)
        r = trace(self.system, P, D, self.wavelength, opl0, last=self.system.stop_index, apertures=False)
        return r.positions[-1, :, 0], r.positions[-1, :, 1]

    def aim(self, spec, px, py):
        """Aim points on the entrance-pupil plane for normalised pupil coords."""
        px, py = np.broadcast_arrays(_as_array(px), _as_array(py))
        ax, ay = px * self.r_ep, py * self.r_ep
        if self.aiming != "real" or self.system.stop_index == 0:
            return ax, ay
        tx, ty = px * self.r_stop, py * self.r_stop
        h = 1e-6 * max(self.r_ep, 1e-9)
        tol = 1e-10 * max(self.r_stop, 1e-9)
        for _ in range(30):
            sx, sy = self._stop_coords(spec, ax, ay)
            ex, ey = sx - tx, sy - ty
            if np.all(np.nan_to_num(np.hypot(ex, ey), nan=0.0) < tol):
                break
            sx1, sy1 = self._stop_coords(spec, ax + h, ay)
            sx2, sy2 = self._stop_coords(spec, ax, ay + h)
            j11, j21 = (sx1 - sx) / h, (sy1 - sy) / h
            j12, j22 = (sx2 - sx) / h, (sy2 - sy) / h
            det = j11 * j22 - j12 * j21
            with np.errstate(divide="ignore", invalid="ignore"):
                dx = (j22 * ex - j12 * ey) / det
                dy = (-j21 * ex + j11 * ey) / det
            dx = np.where(np.isfinite(dx), dx, 0.0)
            dy = np.where(np.isfinite(dy), dy, 0.0)
            ax, ay = ax - dx, ay - dy
        return ax, ay

    def rays(self, hx, hy, px, py):
        hx, hy, px, py = np.broadcast_arrays(*(_as_array(v) for v in (hx, hy, px, py)))
        P = np.empty(px.shape + (3,))
        D = np.empty_like(P)
        opl0 = np.empty(px.shape)
        # group by field point (usually one or a few)
        fields = np.stack([hx, hy], axis=1)
        uniq, inv = np.unique(fields, axis=0, return_inverse=True)
        inv = inv.reshape(-1)
        for k, (fx, fy) in enumerate(uniq):
            m = inv == k
            spec = self.object_spec(fx, fy)
            ax, ay = self.aim(spec, px[m], py[m])
            P[m], D[m], opl0[m] = self._rays_from_aim(spec, ax, ay)
        return P, D, opl0

    # real image height fields ------------------------------------------------
    def _solve_real_image_height(self, hx, hy):
        sysm = self.system
        fx, fy = hx * sysm.max_field, hy * sysm.max_field
        kind = "angle" if sysm.object_at_infinity else "point"
        k = self.par.image_height_per_unit_field()
        v = np.array([fx / k, fy / k])
        if fx == 0 and fy == 0:
            return (kind, 0.0, 0.0)

        def chief_xy(v):
            spec = (kind, v[0], v[1])
            ax, ay = self.aim(spec, 0.0, 0.0)
            P, D, o = self._rays_from_aim(spec, ax, ay)
            r = trace(sysm, P, D, self.wavelength, o, apertures=False)
            return np.array([r.x[0], r.y[0]])

        target = np.array([fx, fy])
        h = 1e-7 * max(abs(v).max(), 1e-6)
        for _ in range(30):
            f0 = chief_xy(v) - target
            if np.hypot(*f0) < 1e-11 * max(1.0, abs(target).max()):
                break
            J = np.column_stack([(chief_xy(v + [h, 0]) - target - f0) / h,
                                 (chief_xy(v + [0, h]) - target - f0) / h])
            if abs(np.linalg.det(J)) < 1e-300:
                # 1-D case (only one component non-zero): treat axes independently
                with np.errstate(divide="ignore", invalid="ignore"):
                    d = np.where(np.diag(J) != 0, f0 / np.diag(J), 0.0)
            else:
                d = np.linalg.solve(J, f0)
            v = v - d
        return (kind, float(v[0]), float(v[1]))


def trace_rays(system, hx=0.0, hy=0.0, px=0.0, py=0.0, wavelength=None, aiming=None,
               apertures: bool = True, last: Optional[int] = None) -> TraceResult:
    """Trace rays given normalised field (hx, hy) and pupil (px, py) coordinates.

    All four inputs broadcast against each other.  ``wavelength`` in um
    (default: primary).
    """
    gen = RayGenerator(system, wavelength, aiming)
    P, D, opl0 = gen.rays(hx, hy, px, py)
    return trace(system, P, D, gen.wavelength, opl0, apertures=apertures, last=last)


def chief_ray(system, hx=0.0, hy=0.0, wavelength=None, **kw) -> TraceResult:
    return trace_rays(system, hx, hy, 0.0, 0.0, wavelength, **kw)


def marginal_ray(system, wavelength=None, **kw) -> TraceResult:
    return trace_rays(system, 0.0, 0.0, 0.0, 1.0, wavelength, **kw)
