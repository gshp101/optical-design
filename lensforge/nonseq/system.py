"""The non-sequential scene: objects, sources, ambient medium; JSON I/O."""

from __future__ import annotations

import json
import math
from typing import List, Optional

import numpy as np

from .objects import NSObject, Source, object_from_dict, source_from_dict

FORMAT = "lensforge-ns-1"


class NonSequentialSystem:
    """Objects and sources placed in one global frame (lens units)."""

    def __init__(self, name: str = "", units: str = "mm", ambient: str = "AIR", library=None):
        from ..system import shared_library
        self.name, self.units, self.ambient = name, units, ambient
        self.library = library or shared_library()
        self.objects: List[NSObject] = []
        self.sources: List[Source] = []
        self.notes = ""

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

    # -- tracing -----------------------------------------------------------
    def trace(self, **kw):
        from .trace import trace
        return trace(self, **kw)

    # -- serialisation ------------------------------------------------------------
    def to_dict(self):
        return {"format": FORMAT, "name": self.name, "units": self.units, "ambient": self.ambient,
                "notes": self.notes, "objects": [o.to_dict() for o in self.objects],
                "sources": [s.to_dict() for s in self.sources]}

    @classmethod
    def from_dict(cls, d, library=None):
        def num(x):
            if isinstance(x, dict):
                return {k: num(v) for k, v in x.items()}
            return math.inf if x == "inf" else -math.inf if x == "-inf" else x
        s = cls(d.get("name", ""), d.get("units", "mm"), d.get("ambient", "AIR"), library)
        s.notes = d.get("notes", "")
        s.objects = [object_from_dict({k: num(v) for k, v in o.items()}) for o in d.get("objects", [])]
        s.sources = [source_from_dict(x) for x in d.get("sources", [])]
        return s

    def copy(self):
        return NonSequentialSystem.from_dict(self.to_dict(), self.library)

    def describe(self) -> str:
        rows = [f"{'#':>3} {'Type':18} {'X':>9} {'Y':>9} {'Z':>9} {'TiltX':>7} {'TiltY':>7} {'TiltZ':>7} "
                f"{'Material':>10}  Comment"]
        for k, o in enumerate(self.objects, start=1):
            rows.append(f"{k:>3} {o.kind:18} {o.x:9.4g} {o.y:9.4g} {o.z:9.4g} {o.tilt_x:7.3g} {o.tilt_y:7.3g} "
                        f"{o.tilt_z:7.3g} {str(o.material or ''):>10}  {o.comment}")
        for k, s in enumerate(self.sources, start=1):
            rows.append(f"S{k:<2} {s.kind:18} {s.x:9.4g} {s.y:9.4g} {s.z:9.4g} {s.tilt_x:7.3g} {s.tilt_y:7.3g} "
                        f"{s.tilt_z:7.3g} {'':>10}  {s.comment} ({s.n_rays} rays, power {s.power:g})")
        return "\n".join(rows)

    def __repr__(self):
        return f"NonSequentialSystem({self.name!r}, {len(self.objects)} objects, {len(self.sources)} sources)"


def _dumps(system):
    def fix(x):
        if isinstance(x, float) and math.isinf(x):
            return "inf" if x > 0 else "-inf"
        if isinstance(x, dict):
            return {k: fix(v) for k, v in x.items()}
        if isinstance(x, list):
            return [fix(v) for v in x]
        return x
    return json.dumps(fix(system.to_dict()), indent=2)


def save_ns(system, path):
    with open(path, "w", encoding="utf-8") as f:
        f.write(_dumps(system))


def load_ns(path, library=None) -> NonSequentialSystem:
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    if d.get("format") != FORMAT:
        raise ValueError(f"{path} is not a lensforge non-sequential file")
    return NonSequentialSystem.from_dict(d, library)
