"""The non-sequential scene: objects, sources, ambient medium; JSON I/O."""

from __future__ import annotations

import json
import math
from typing import List, Optional

import numpy as np

from .objects import NSObject, Source, object_from_dict, source_from_dict

FORMAT = "lensforge-ns-1"

#: ray-trace settings a scene keeps (``NonSequentialSystem.trace_settings``) and their defaults
#: (those of :func:`lensforge.nonseq.trace`; the editor turns ray splitting on for converted lenses)
TRACE_DEFAULTS = {"split": False, "fresnel": True, "min_relative_intensity": 1e-6, "max_segments": 100, "seed": 0,
                  "max_rays": 2_000_000}


class NonSequentialSystem:
    """Objects and sources placed in one global frame (lens units)."""

    def __init__(self, name: str = "", units: str = "mm", ambient: str = "AIR", library=None):
        from ..system import shared_library
        self.name, self.units, self.ambient = name, units, ambient
        self.library = library or shared_library()
        self.objects: List[NSObject] = []
        self.sources: List[Source] = []
        self.notes = ""
        self.trace_settings = dict(TRACE_DEFAULTS)

    def __deepcopy__(self, memo):
        # (the glass library is shared, never copied: lenses holding a scene are deep-copied for undo)
        return self.copy()

    def add(self, item):
        """Add an object or a source; returns it."""
        (self.sources if isinstance(item, Source) else self.objects).append(item)
        return item

    @property
    def detectors(self):
        return [o for o in self.objects if o.is_detector]

    def detector_index(self, det) -> int:
        """Object index of a detector given as object, object index or detector number (from 0)."""
        if isinstance(det, NSObject):
            return self.objects.index(det)
        dets = [k for k, o in enumerate(self.objects) if o.is_detector]
        if det in dets:
            return det
        return dets[det]

    @property
    def wavelengths(self):
        out = []
        for s in self.sources:
            for w in s.wavelengths:
                if w not in out:
                    out.append(w)
        return out or [0.5875618]

    def index(self, material, wavelength):
        if material in (None, "", "AIR"):
            material = self.ambient
        if material in (None, "", "AIR"):
            return 1.0
        return float(self.library.resolve(material).index(wavelength))

    def missing_materials(self):
        out = {}
        for k, o in enumerate(self.objects):
            if o.is_volume:
                try:
                    self.library.resolve(o.material)
                except (KeyError, TypeError):
                    out.setdefault(str(o.material), []).append(k)
        return out

    def extent(self):
        """Rough size of the scene (for drawing escaping rays)."""
        pts = [o.origin for o in self.objects] + [s.origin for s in self.sources]
        if not pts:
            return 10.0
        pts = np.array(pts)
        return float(max(np.ptp(pts, axis=0).max(), 10.0))

    # -- placement ----------------------------------------------------------
    def global_pose(self, item):
        """(R, origin) of an object or source in global coordinates, following its ``ref`` chain."""
        seen = set()

        def pose(it):
            ref = int(getattr(it, "ref", 0) or 0)
            if not ref:
                return it.R, it.origin
            if not 1 <= ref <= len(self.objects):
                raise ValueError(f"Ref object {ref} does not exist (the scene has {len(self.objects)} objects)")
            target = self.objects[ref - 1]
            if id(target) in seen or target is it:
                raise ValueError("Ref objects form a loop: an object is placed relative to itself")
            seen.add(id(target))
            R0, O0 = pose(target)
            return R0 @ it.R, R0 @ it.origin + O0

        return pose(item)

    def resolved(self) -> "NonSequentialSystem":
        """A copy with every pose global (``ref`` 0); the scene itself unless some ``ref`` is set."""
        if not any(getattr(x, "ref", 0) for x in self.objects + self.sources):
            return self
        poses = [self.global_pose(x) for x in self.objects + self.sources]
        out = self.copy()
        for x, (R, O) in zip(out.objects + out.sources, poses):
            x.set_pose(R, O)
            x.ref = 0
        return out

    # -- tracing -----------------------------------------------------------
    def trace(self, **kw):
        """Trace with ``trace_settings``; keywords override them (see :func:`lensforge.nonseq.trace`)."""
        from .trace import trace
        return trace(self, **{**self.trace_settings, **kw})

    # -- serialisation ------------------------------------------------------------
    def to_dict(self):
        return {"format": FORMAT, "name": self.name, "units": self.units, "ambient": self.ambient,
                "notes": self.notes, "trace_settings": dict(self.trace_settings),
                "objects": [o.to_dict() for o in self.objects],
                "sources": [s.to_dict() for s in self.sources]}

    def to_json_dict(self):
        """:meth:`to_dict` with infinities written as "inf" / "-inf" (plain JSON)."""
        return _fix_inf(self.to_dict())

    @classmethod
    def from_dict(cls, d, library=None):
        def num(x):
            if isinstance(x, dict):
                return {k: num(v) for k, v in x.items()}
            return math.inf if x == "inf" else -math.inf if x == "-inf" else x
        s = cls(d.get("name", ""), d.get("units", "mm"), d.get("ambient", "AIR"), library)
        s.notes = d.get("notes", "")
        s.trace_settings = {**TRACE_DEFAULTS, **{k: v for k, v in (d.get("trace_settings") or {}).items()
                                                  if k in TRACE_DEFAULTS}}
        s.objects = [object_from_dict({k: num(v) for k, v in o.items()}) for o in d.get("objects", [])]
        s.sources = [source_from_dict(x) for x in d.get("sources", [])]
        return s

    def copy(self):
        return NonSequentialSystem.from_dict(self.to_dict(), self.library)

    def describe(self) -> str:
        rows = [f"{'#':>3} {'Type':18} {'Ref':>3} {'X':>9} {'Y':>9} {'Z':>9} {'TiltX':>7} {'TiltY':>7} "
                f"{'TiltZ':>7} {'Material':>10}  Comment"]
        for k, o in enumerate(self.objects, start=1):
            rows.append(f"{k:>3} {o.kind:18} {o.ref:>3} {o.x:9.4g} {o.y:9.4g} {o.z:9.4g} {o.tilt_x:7.3g} "
                        f"{o.tilt_y:7.3g} {o.tilt_z:7.3g} {str(o.material or ''):>10}  {o.comment}")
        for k, s in enumerate(self.sources, start=1):
            rows.append(f"S{k:<2} {s.kind:18} {s.ref:>3} {s.x:9.4g} {s.y:9.4g} {s.z:9.4g} {s.tilt_x:7.3g} "
                        f"{s.tilt_y:7.3g} {s.tilt_z:7.3g} {'':>10}  {s.comment} ({s.n_rays} rays, power {s.power:g})")
        return "\n".join(rows)

    def __repr__(self):
        return f"NonSequentialSystem({self.name!r}, {len(self.objects)} objects, {len(self.sources)} sources)"


def _fix_inf(x):
    if isinstance(x, float) and math.isinf(x):
        return "inf" if x > 0 else "-inf"
    if isinstance(x, dict):
        return {k: _fix_inf(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_fix_inf(v) for v in x]
    return x


def _dumps(system):
    return json.dumps(system.to_json_dict(), indent=2)


def save_ns(system, path):
    with open(path, "w", encoding="utf-8") as f:
        f.write(_dumps(system))


def load_ns(path, library=None) -> NonSequentialSystem:
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    if d.get("format") != FORMAT:
        raise ValueError(f"{path} is not a lensforge non-sequential file")
    return NonSequentialSystem.from_dict(d, library)
