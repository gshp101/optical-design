"""Non-sequential ray tracing: objects anywhere in 3-D, rays in any order, ray splitting.

Typical use::

    import lensforge as lf
    from lensforge import nonseq as ns

    scene = ns.NonSequentialSystem("Ball lens")
    scene.add(ns.SourceEllipse(half_x=1, half_y=1, n_rays=5000, z=-10))
    scene.add(ns.Sphere(radius=5, material="N-BK7"))
    scene.add(ns.Detector(half_x=2, half_y=2, z=8, nx=101, ny=101))
    r = scene.trace(split=True)            # NSTraceResult
    print(r.summary())
    det = r.detector(0)
    E = det.image("ghost")                 # irradiance of light reflected twice or more

    scene = ns.from_sequential(lf.samples.achromat())   # any sequential lens

Plot helpers: :func:`lensforge.plot.ns_layout`, :func:`lensforge.plot.ns_detector`.
"""

from .objects import (Annulus, CylinderVolume, Detector, NSObject, OBJECT_TYPES, Rectangle, RectangularVolume,
                      SOURCE_TYPES, Source, SourceEllipse, SourcePoint, SourceRectangle, Sphere, StandardLens,
                      StandardSurface, angles_from_matrix, direction_angles, object_from_dict, source_from_dict)
from .system import NonSequentialSystem, load_ns, save_ns
from .trace import EVENT_NAMES, DetectorData, NSTraceResult, trace
from .convert import from_sequential

load = load_ns
save = save_ns

__all__ = ["Annulus", "CylinderVolume", "Detector", "NSObject", "OBJECT_TYPES", "Rectangle", "RectangularVolume",
           "SOURCE_TYPES", "Source", "SourceEllipse", "SourcePoint", "SourceRectangle", "Sphere", "StandardLens",
           "StandardSurface", "angles_from_matrix", "direction_angles", "object_from_dict", "source_from_dict",
           "NonSequentialSystem", "load_ns", "save_ns", "load", "save", "EVENT_NAMES", "DetectorData",
           "NSTraceResult", "trace", "from_sequential"]
