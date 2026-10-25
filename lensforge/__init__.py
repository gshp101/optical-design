"""lensforge: a sequential optical design and analysis toolkit (pure Python + NumPy).

Typical scripting use::

    import lensforge as lf

    lens = lf.OpticalSystem("Singlet")
    lens.set_aperture("EPD", 20)
    lens.set_fields([0, 5, 10])
    lens.set_wavelengths([0.4861, 0.5876, 0.6563], primary=1)
    lens.add_surface(radius=51.68, thickness=4, material="N-BK7", stop=True)
    lens.add_surface(radius=-51.68, thickness=48)
    print(lens.paraxial())
    spot = lf.spot_diagram(lens, field=2)
    m = lf.fft_mtf(lens, field=1)          # all analyses return dicts of arrays
    lf.plot.mtf(m)                          # optional matplotlib helpers (import lensforge.plot)
"""

from .materials import (AIR, MIRROR, ConstantIndex, Glass, GlassCatalog, Material, MaterialLibrary,
                        ModelGlass, TabulatedMaterial, load_agf)
from .surfaces import (BinaryPhase, CircularAperture, CircularObscuration, CoordinateBreak, DiffractionGrating,
                       EllipticalAperture, EvenAsphere, OddAsphere, Paraxial, RectangularAperture,
                       Standard, Surface, Toroidal, XYPolynomial)
from .system import Field, OpticalSystem, Wavelength, shared_library
from .paraxial import ParaxialAnalysis
from .raytrace import TraceResult, RayGenerator, chief_ray, marginal_ray, trace, trace_rays
from .pupil import pupil_grid
from .analysis import *  # noqa: F401,F403  (all analyses, see lensforge.analysis)
from .analysis import metrics
from . import optimize
from . import samples
from .io import load, save, load_zmx
from .compose import delete_surfaces, insert_lens, lens_surfaces, reverse_surfaces, scale_surface, scale_system

__version__ = "0.3.0"
