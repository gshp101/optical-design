"""Convert a sequential lens into a non-sequential scene."""

from __future__ import annotations

import math

import numpy as np

from ..analysis.ghost import _medium_names
from ..paraxial import ParaxialAnalysis
from ..raytrace import RayGenerator
from .objects import Annulus, Detector, SourceEllipse, SourcePoint, StandardLens, StandardSurface, direction_angles
from .system import NonSequentialSystem


def _bare(surface):
    s = surface.copy()
    s.thickness, s.material, s.stop, s.comment = 0.0, None, False, ""
    s.aperture = None
    return s


def _hole_radius(system, k, frames):
    """Radius of the hole a mirror needs so the beam after it can pass through its vertex plane later
    (the central hole of a Cassegrain primary).  0 when the beam never comes back through."""
    from ..raytrace import trace_rays
    th = np.linspace(0, 2 * np.pi, 16, endpoint=False)
    px, py = np.concatenate([[0.0], np.cos(th)]), np.concatenate([[0.0], np.sin(th)])
    R, O = frames[k]
    r_max = 0.0
    for f in range(len(system.fields)):
        hx, hy = system.normalized_field(f)
        t = trace_rays(system, hx, hy, px, py, apertures=False)
        G = t.global_positions()
        L = (G - O) @ R  # in the mirror's frame
        for a in range(k + 1, G.shape[0] - 1):
            z0, z1 = L[a, :, 2], L[a + 1, :, 2]
            cross = (z0 * z1 < 0) & np.isfinite(z0) & np.isfinite(z1)
            if a == k + 1:
                cross &= np.abs(z0) > 1e-9
            if not cross.any():
                continue
            u = z0[cross] / (z0[cross] - z1[cross])
            p = L[a, cross] + u[:, None] * (L[a + 1, cross] - L[a, cross])
            r_max = max(r_max, float(np.hypot(p[:, 0], p[:, 1]).max()))
    sd = abs(system.surfaces[k].semi_diameter or 0.0)
    return 1.02 * r_max if 0 < r_max < sd else 0.0


def from_sequential(system, fields=None, wavelengths=None, n_rays: int = 2000, sampling: str = "grid",
                    detector_pixels: int = 101, stop_aperture: bool = True, coating=None) -> NonSequentialSystem:
    """Build a non-sequential scene from a sequential lens.

    Each glass element becomes a :class:`StandardLens` (cemented groups are
    touching lenses whose shared faces pass light glass to glass), mirrors
    become :class:`StandardSurface` mirrors, the stop gets an absorbing
    :class:`Annulus` (``stop_aperture``) and the image surface a
    :class:`Detector`.  One source per field (index list, default all)
    fills the entrance pupil: a collimated :class:`SourceEllipse` for objects
    at infinity, a :class:`SourcePoint` otherwise.  ``coating`` sets the
    reflectance of every lens face (None: uncoated Fresnel).
    Surfaces keep their exact shape (aspheres, toroids, freeforms ...); ideal
    (paraxial) and phase surfaces cannot be converted.
    """
    sysm = system
    lib = sysm.library
    work = sysm.copy()
    if any(s.semi_diameter is None for s in work.surfaces[1:-1]):
        work.update_semi_diameters()
    frames = work.surface_frames()
    _, mirror, _ = work.media(work.primary)
    med = _medium_names(work)
    img = work.image_index
    ns = NonSequentialSystem(f"{sysm.name or 'Lens'} (non-sequential)", sysm.units, library=lib)
    sd = [abs(s.semi_diameter or 0.0) for s in work.surfaces]

    def is_glass(k):
        m = med[k]
        return m not in (None, "", "AIR") and not lib.resolve(m).is_mirror

    k = 1
    while k < img:
        s = work.surfaces[k]
        if s.has_deflect or s.has_phase:
            raise NotImplementedError(f"surface {k} ({s.kind}) is an ideal or phase surface and has no "
                                      "non-sequential equivalent")
        if s.is_coordinate_break:
            k += 1
            continue
        R, O = frames[k]
        if mirror[k]:
            hole = _hole_radius(work, k, frames)
            o = StandardSurface(radius=getattr(s, "radius", math.inf), conic=getattr(s, "conic", 0.0),
                                semi_diameter=sd[k], inner_radius=hole, material="MIRROR", surface=_bare(s),
                                comment=f"S{k} mirror" + (" (with hole)" if hole > 0 else ""))
            o.set_pose(R, O)
            ns.add(o)
            k += 1
            continue
        if is_glass(k):
            q = k
            group = [k]
            while is_glass(q) and q + 1 < img:
                nxt = work.surfaces[q + 1]
                if nxt.is_coordinate_break or mirror[q + 1] or nxt.has_deflect or nxt.has_phase:
                    raise NotImplementedError(f"surface {q + 1} inside a glass element cannot be converted")
                group.append(q + 1)
                q += 1
            g_sd = max(sd[j] for j in group)
            for a in group[:-1]:
                s1, s2 = work.surfaces[a], work.surfaces[a + 1]
                Ra, Oa = frames[a]
                o = StandardLens(radius1=getattr(s1, "radius", math.inf), conic1=getattr(s1, "conic", 0.0),
                                 thickness=s1.thickness, radius2=getattr(s2, "radius", math.inf),
                                 conic2=getattr(s2, "conic", 0.0), semi_diameter=g_sd, material=med[a],
                                 surface1=_bare(s1), surface2=_bare(s2), coating=coating,
                                 comment=f"S{a}-S{a + 1}")
                o.set_pose(Ra, Oa)
                ns.add(o)
            k = q + 1
            continue
        k += 1

    par = ParaxialAnalysis(work)
    r_ep = par.entrance_pupil_radius
    if stop_aperture and 0 < work.stop_index < img:
        st = work.stop_index
        R, O = frames[st]
        r_in = par.stop_radius
        o = Annulus(r_in, max(3 * r_in, max(sd) * 1.5), material="ABSORB", comment="stop")
        o.set_pose(R, O)
        ns.add(o)

    R, O = frames[img]
    try:
        h = abs(par.paraxial_image_height)
    except Exception:  # pragma: no cover
        h = 0.0
    half = 1.2 * max(sd[img], h, 1e-3 * max(r_ep, 1.0))
    det = Detector(half, half, detector_pixels, detector_pixels, comment="image")
    det.set_pose(R, O)
    ns.add(det)

    wls = [w.value for w in sysm.wavelengths] if wavelengths is None else list(np.atleast_1d(wavelengths))
    fields = range(len(sysm.fields)) if fields is None else np.atleast_1d(fields)
    gen = RayGenerator(work)
    z_ep = gen.z_ep
    pts = [frames[j][1] for j in range(1, img) if frames[j] is not None]
    z_first = min(p[2] for p in pts) if pts else 0.0
    z_start = min(z_first, z_ep) - (max(sd) + 1.0)
    for f in fields:
        f = int(f)
        hx, hy = work.normalized_field(f)
        spec = gen.object_spec(hx, hy)
        if spec[0] == "angle":
            d = np.array([spec[1], spec[2], 1.0])
            d /= np.linalg.norm(d)
            c = np.array([0.0, 0.0, z_ep]) + (z_start - z_ep) / d[2] * d
            tx, ty = direction_angles(d)
            src = SourceEllipse(half_x=r_ep * 1.02, half_y=r_ep * 1.02, n_rays=n_rays, wavelengths=wls,
                                sampling=sampling, x=c[0], y=c[1], z=c[2], tilt_x=tx, tilt_y=ty,
                                comment=f"field {f + 1}")
        else:
            p = np.array([spec[1], spec[2], spec[3] if len(spec) > 3 else -work.object.thickness])
            d = np.array([0.0, 0.0, z_ep]) - p
            dist = np.linalg.norm(d)
            tx, ty = direction_angles(d)
            cone = math.degrees(math.atan(1.02 * r_ep / dist)) + 1.0 * math.degrees(
                math.atan(abs(r_ep) * abs(math.hypot(p[0], p[1])) / max(dist, 1e-9) ** 2))
            src = SourcePoint(cone_angle=cone, n_rays=n_rays, wavelengths=wls, sampling=sampling,
                              x=p[0], y=p[1], z=p[2], tilt_x=tx, tilt_y=ty, comment=f"field {f + 1}")
        ns.add(src)
    return ns
