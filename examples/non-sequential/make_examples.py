"""Build the non-sequential example lenses of this folder (Examples > Non-Sequential in the apps).

Each example is an ordinary .lens.json file whose ``nonseq`` key holds a non-sequential scene;
opening it in the desktop or web app shows the Non-Sequential Component Editor, and the
Analysis > Non-Sequential windows (NS Layout, NS 3D Layout, Detector Viewer, Ray Path Analysis,
NS Trace Report) trace it.  Scenes converted from a sequential lens keep that lens as the
sequential part; the others carry a one-surface placeholder lens.

Run from anywhere: python examples/non-sequential/make_examples.py
"""

import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", ".."))
import lensforge as lf  # noqa: E402
from lensforge import nonseq as ns  # noqa: E402


def placeholder(name, notes):
    """The sequential part of a scene-only example: object at infinity, a stop, the image."""
    s = lf.OpticalSystem(name)
    s.set_aperture("EPD", 10.0)
    s.set_fields([0.0])
    s.set_wavelengths([0.5875618])
    s.add_surface(radius=float("inf"), thickness=0.0, stop=True)
    s.notes = notes
    return s


def scene(name, notes, **settings):
    sc = ns.NonSequentialSystem(name)
    sc.notes = notes
    sc.trace_settings.update(settings)
    return sc


def save(lens, sc, filename):
    sc.library = lens.library
    lens.nonseq = sc
    path = os.path.join(HERE, filename)
    lf.save(lens, path)
    r = sc.trace()
    print(f"{filename}: {r.n_launched} rays, {r.n_rays_total} with splits; "
          + "; ".join(f"det {d.object_index + 1}: {d.total_power():.4g}" for d in r.detectors))


# -- 1. ghosts of a cemented achromat (converted from the sequential lens) ---------------------------------
def achromat_ghosts():
    lens = lf.samples.achromat()
    lens.notes = ("Non-sequential example: the sample cemented achromat converted to a scene "
                  "(Tools > Non-Sequential > Convert Lens to Non-Sequential) with ray splitting on. Open the "
                  "Ray Path Analysis to see the two-reflection ghost paths, then set Path in the NS Layout to "
                  "draw one; the Detector Viewer with Rays = Ghosts and Log scale shows the ghost halo.")
    sc = ns.from_sequential(lens, n_rays=2000, sampling="random")
    sc.name = "Cemented achromat ghosts"
    sc.notes = lens.notes
    sc.trace_settings.update(split=True, min_relative_intensity=1e-6)
    save(lens, sc, "Cemented Achromat Ghosts.lens.json")


# -- 2. Cassegrain telescope converted (mirrors, the primary's hole, the secondary's obscuration) ---------------
def cassegrain():
    lens = lf.samples.cassegrain()
    lens.notes = ("Non-sequential example: the sample classical Cassegrain converted to a scene. The primary "
                  "gets a central hole for the returning beam; light that misses the secondary or goes "
                  "straight through the hole is the stray light the Ray Path Analysis lists.")
    sc = ns.from_sequential(lens, n_rays=3000, sampling="random")
    sc.name = "Cassegrain telescope"
    sc.notes = lens.notes
    save(lens, sc, "Cassegrain Telescope.lens.json")


# -- 3. ball lens focusing a collimated beam ---------------------------------------------------------------------
def ball_lens():
    n_notes = ("A 4 mm N-BK7 ball lens focuses a 3 mm collimated beam. The ball's strong spherical aberration "
               "shows in the NS Layout (the marginal rays cross well before the paraxial focus where the "
               "detector is) and in the Detector Viewer's cross-section. Rays are split, so the Ray Path "
               "Analysis also lists the light reflected inside the ball.")
    sc = scene("Ball lens", n_notes, split=True, min_relative_intensity=1e-4)
    sc.add(ns.SourceEllipse(half_x=1.5, half_y=1.5, n_rays=3000, z=-6, comment="collimated beam"))
    sc.add(ns.Sphere(radius=2.0, material="N-BK7", comment="ball lens"))
    n = 1.5168
    efl = n * 2.0 / (2 * (n - 1))
    sc.add(ns.Detector(half_x=0.4, half_y=0.4, nx=101, ny=101, z=round(efl, 3), comment="paraxial focus"))
    save(placeholder("Ball lens (non-sequential)", n_notes), sc, "Ball Lens.lens.json")


# -- 4. dispersing prism at minimum deviation -----------------------------------------------------------------
def dispersing_prism():
    n_notes = ("A 60 degree N-SF11 prism at minimum deviation for 550 nm disperses a narrow white beam (five "
               "wavelengths, 450 to 650 nm). Open the Detector Viewer with Show = True color to see the "
               "spectrum, and the NS Layout coloured by wavelength. The prism lies with its apex up (Tilt X "
               "-90); the source and the detector are tilted along the incoming and the deviated beam.")
    sc = scene("Dispersing prism", n_notes)
    nd = float(lf.shared_library().resolve("N-SF11").index(0.55))
    i = math.degrees(math.asin(nd * math.sin(math.radians(30))))  # incidence angle at minimum deviation
    dev = 2 * i - 60
    base = 20.0
    h = base / 2 / math.tan(math.radians(30))
    ent = (-base / 4, h / 2)  # (z, y) mid-point of the entrance face
    ex = (base / 4, h / 2)
    L = 30.0
    a = math.radians(dev / 2)
    sc.add(ns.SourceEllipse(half_x=0.4, half_y=0.4, n_rays=2500, wavelengths=[0.45, 0.5, 0.55, 0.6, 0.65],
                            z=round(ent[0] - L * math.cos(a), 4), y=round(ent[1] - L * math.sin(a), 4),
                            tilt_x=round(-dev / 2, 4), comment="white beam"))
    sc.add(ns.Prism(base=base, apex_angle=60, half_x=6, material="N-SF11", tilt_x=-90, comment="60 deg prism"))
    D = 60.0
    sc.add(ns.Detector(half_x=3, half_y=6, nx=61, ny=241, z=round(ex[0] + D * math.cos(a), 4),
                       y=round(ex[1] - D * math.sin(a), 4), tilt_x=round(dev / 2, 4), comment="screen"))
    save(placeholder("Dispersing prism (non-sequential)", n_notes), sc, "Dispersing Prism.lens.json")


# -- 5. right-angle prism retroreflector (total internal reflection) ----------------------------------------------
def retro_prism():
    n_notes = ("A right-angle N-BK7 prism used as a retroreflector: the beam enters the hypotenuse face, is "
               "totally internally reflected by both 45 degree faces and leaves parallel to itself, shifted "
               "down, onto the detector beside the source. In the Ray Path Analysis the main path reads "
               "base T, left X, right X, base T (X = total internal reflection).")
    sc = scene("Right-angle prism retroreflector", n_notes, split=True, min_relative_intensity=1e-4)
    sc.add(ns.SourceEllipse(half_x=1, half_y=1, n_rays=1500, z=-15, y=4, comment="beam"))
    sc.add(ns.Prism(base=20, apex_angle=90, half_x=6, material="N-BK7", comment="right-angle prism"))
    sc.add(ns.Detector(half_x=3, half_y=3, nx=61, ny=61, z=-8, y=-4, comment="return beam"))
    save(placeholder("Retroreflecting prism (non-sequential)", n_notes), sc, "Retroreflecting Prism.lens.json")


# -- 6. LED in a parabolic reflector -----------------------------------------------------------------------------
def led_reflector():
    n_notes = ("A Lambertian LED (cosine exponent 1) at the focus of a parabolic mirror (radius 20, conic -1, "
               "focal length 10) faces the mirror; the reflected light leaves collimated. Light outside the "
               "mirror's rim escapes. The Detector Viewer in Angle space shows the collimated beam as a "
               "small spot around the axis.")
    sc = scene("LED reflector", n_notes)
    sc.add(ns.SourcePoint(cone_angle=85, cos_exponent=1, n_rays=4000, z=10, tilt_x=180, comment="LED"))
    sc.add(ns.StandardSurface(radius=20, conic=-1, semi_diameter=15, material="MIRROR", comment="parabolic reflector"))
    sc.add(ns.Detector(half_x=18, half_y=18, nx=81, ny=81, z=80, comment="target"))
    save(placeholder("LED reflector (non-sequential)", n_notes), sc, "LED Parabolic Reflector.lens.json")


# -- 7. light pipe homogeniser ----------------------------------------------------------------------------------
def light_pipe():
    n_notes = ("A wide-angle Lambertian source in front of a 4 x 4 x 50 mm N-BK7 rod. Light bounces along the "
               "rod by total internal reflection and leaves it as a nearly uniform square: compare the "
               "Detector Viewer's irradiance at the rod's exit with the source's hot spot. The rays are "
               "not split, so only TIR (always followed) bends them back.")
    sc = scene("Light pipe homogeniser", n_notes, max_segments=200)
    sc.add(ns.SourcePoint(cone_angle=70, cos_exponent=1, n_rays=5000, z=-0.5, comment="LED"))
    sc.add(ns.RectangularVolume(half_x=2, half_y=2, length=50, material="N-BK7", comment="light pipe"))
    sc.add(ns.Detector(half_x=2.5, half_y=2.5, nx=51, ny=51, z=50.2, comment="exit face"))
    save(placeholder("Light pipe (non-sequential)", n_notes), sc, "Light Pipe Homogenizer.lens.json")


# -- 8. periscope: fold mirrors placed with Ref Object, then a lens -------------------------------------------------
def periscope():
    n_notes = ("Two 45 degree fold mirrors lift a collimated beam by 30 mm, then a singlet focuses it. The "
               "second mirror is placed relative to the first (Ref = 1): change the first mirror's Z or Tilt "
               "X and the second one moves with it. The lens is placed on the second mirror's frame too "
               "(Ref = 2), so the whole periscope moves together.")
    sc = scene("Periscope", n_notes, split=True, min_relative_intensity=1e-4)
    sc.add(ns.SourceEllipse(half_x=4, half_y=4, n_rays=2000, z=0, comment="collimated beam"))
    c = math.sqrt(0.5)
    sc.add(ns.Rectangle(half_x=7, half_y=9, z=20, tilt_x=45, comment="fold mirror 1"))
    sc.add(ns.Rectangle(half_x=7, half_y=9, y=30 * c, z=-30 * c, ref=1, comment="fold mirror 2"))
    # in mirror 2's frame the outgoing beam (global +z) is local (0, c, c): put the lens 20 mm along it,
    # turned back by -45 deg about x so that its axis is the beam
    sc.add(ns.StandardLens(radius1=51.5, radius2=-51.5, thickness=4, semi_diameter=8, material="N-BK7",
                           y=20 * c, z=20 * c, tilt_x=-45, ref=2, comment="singlet f 50"))
    sc.add(ns.Detector(half_x=1, half_y=1, nx=101, ny=101, z=52.9, ref=3, comment="focus"))
    save(placeholder("Periscope (non-sequential)", n_notes), sc, "Periscope with Fold Mirrors.lens.json")


if __name__ == "__main__":
    for fn in (achromat_ghosts, cassegrain, ball_lens, dispersing_prism, retro_prism, led_reflector, light_pipe,
               periscope):
        fn()
