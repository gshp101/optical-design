"""Non-sequential ray tracing and ray splitting."""

import math
import os

import numpy as np
import pytest

import lensforge as lf
from lensforge import nonseq as ns


def seq_rays(system, hy=0.0, n=4):
    gen = lf.RayGenerator(system)
    px, py = lf.pupil_grid("hexapolar", n)
    P, D, o = gen.rays(0.0, hy, px, py)
    return P, D, o


@pytest.mark.parametrize("name", ["achromat", "triplet"])
def test_matches_the_sequential_trace(name):
    s = lf.samples.achromat() if name == "achromat" else lf.load("examples/output/cooke_triplet.lens.json")
    scene = ns.from_sequential(s, fields=[0], stop_aperture=False)
    P, D, _ = seq_rays(s, 0.7)
    t = lf.trace(s, P, D, s.primary)
    r = scene.trace(rays=(P - 20 * D, D, 1.0, s.primary))
    d = r.detector(0)
    assert len(d.x) == t.valid.sum()
    assert np.sort(d.y) == pytest.approx(np.sort(t.y[t.valid]), abs=1e-9)
    assert np.sort(d.x) == pytest.approx(np.sort(t.x[t.valid]), abs=1e-9)


def test_cemented_group_becomes_touching_lenses():
    scene = ns.from_sequential(lf.samples.achromat())
    lenses = [o for o in scene.objects if o.kind == "STANDARD_LENS"]
    assert [o.material for o in lenses] == ["N-BAF10", "N-SF6"]
    assert lenses[1].z == pytest.approx(4.0)
    assert lenses[0].semi_diameter == lenses[1].semi_diameter
    assert len(scene.sources) == 3 and len(scene.detectors) == 1


def split_ghost_power(s, n=40):
    scene = ns.from_sequential(s, fields=[0], stop_aperture=False)
    scene.detectors[0].half_x = scene.detectors[0].half_y = 5000
    v = (np.arange(n) + 0.5) / n * 2 - 1
    PX, PY = np.meshgrid(v, v)
    m = PX**2 + PY**2 <= 1
    P, D, _ = lf.RayGenerator(s).rays(0, 0, PX[m], PY[m])
    r = scene.trace(rays=(P - 20 * D, D, 1.0 / m.sum(), s.primary), split=True, min_relative_intensity=1e-9)
    im = lf.ghost_image(s, 0, n_rays=n, half_width=5000)
    return r, im


def test_split_ghosts_agree_with_the_sequential_ghost_analysis():
    r, im = split_ghost_power(lf.samples.singlet())
    d = r.detector(0)
    assert d.total_power(2) == pytest.approx(im["ghost_power"], rel=1e-9)
    assert d.total_power("direct") == pytest.approx(im["nominal_power"], rel=1e-9)
    # energy is conserved: everything launched ends somewhere
    assert sum(r.power_by_event().values()) == pytest.approx(1.0, abs=1e-6)
    r, im = split_ghost_power(lf.samples.achromat())
    d = r.detector(0)
    assert d.total_power(2, tir=False) == pytest.approx(im["ghost_power"], rel=0.02)
    assert d.total_power("direct") == pytest.approx(im["nominal_power"], rel=1e-9)


def test_no_split_follows_transmission_only():
    s = lf.samples.singlet()
    scene = ns.from_sequential(s, fields=[0], n_rays=500)
    r = scene.trace()
    assert r.n_rays_total == r.n_launched
    d = r.detector(0)
    assert d.total_power("ghost") == 0
    n = s.material(1).index(s.primary)
    T = (1 - ((n - 1) / (n + 1)) ** 2) ** 2
    # inside the stop all light reaches the image, less two Fresnel losses (near normal incidence)
    inside = d.total_power() / (r.launched_power - r.power_by_event()["absorbed"])
    assert inside == pytest.approx(T, rel=2e-3)
    r = scene.trace(fresnel=False)
    assert r.detector(0).total_power() == pytest.approx(r.launched_power - r.power_by_event()["absorbed"])


def test_ball_lens_focus_and_tir_light_pipe():
    n_glass = lf.shared_library().resolve("N-BK7").index(0.5875618)
    D_ball = 10.0
    efl = n_glass * D_ball / (4 * (n_glass - 1))
    bfl = efl - D_ball / 2
    scene = ns.NonSequentialSystem("ball")
    scene.add(ns.Sphere(radius=5.0, material="N-BK7"))
    det = scene.add(ns.Detector(half_x=1, half_y=1, nx=11, ny=11, z=5.0 + bfl))
    P = np.array([[0.0, y, -20.0] for y in (0.01, 0.02, -0.015)])
    D = np.tile([0.0, 0.0, 1.0], (3, 1))
    r = scene.trace(rays=(P, D, 1.0, 0.5875618))
    assert np.abs(r.detector(det).y).max() < 2e-5  # paraxial rays cross at the paraxial focus

    rod = ns.NonSequentialSystem("light pipe")
    rod.add(ns.CylinderVolume(radius=1.0, length=100.0, material="N-BK7"))
    out = rod.add(ns.Detector(half_x=3, half_y=3, nx=5, ny=5, z=100.5))
    rod.add(ns.SourcePoint(cone_angle=25, n_rays=400, z=-0.01, sampling="grid"))
    r = rod.trace(fresnel=False)
    d = r.detector(out)
    assert d.total_power() == pytest.approx(1.0)  # every ray guided to the far end by TIR
    assert d.n_tir.max() > 10 and (d.n_tir[np.hypot(d.x, d.y) > 2] > 0).all()


def test_fold_mirror_and_absorber():
    scene = ns.NonSequentialSystem("fold")
    scene.add(ns.SourceEllipse(half_x=1, half_y=1, n_rays=200, z=-10, sampling="grid"))
    scene.add(ns.Rectangle(half_x=5, half_y=5, tilt_x=45.0, material="MIRROR"))
    det = scene.add(ns.Detector(half_x=3, half_y=3, nx=3, ny=3, y=20, tilt_x=-90.0))
    r = scene.trace()
    d = r.detector(det)
    assert d.total_power() == pytest.approx(1.0)
    assert np.abs(d.direction[:, 2]).max() == pytest.approx(1.0)  # arrives along the detector normal
    scene.objects[0].material = "ABSORB"
    assert scene.trace().power_by_event()["absorbed"] == pytest.approx(1.0)


def test_box_and_coating_split():
    scene = ns.NonSequentialSystem("plate")
    scene.add(ns.SourceRectangle(half_x=1, half_y=1, n_rays=100, z=-5, sampling="grid"))
    plate = scene.add(ns.RectangularVolume(half_x=5, half_y=5, length=2, material="N-BK7", coating=0.01))
    det = scene.add(ns.Detector(half_x=3, half_y=3, nx=3, ny=3, z=10))
    r = scene.trace(split=True, min_relative_intensity=1e-12)
    d = r.detector(det)
    assert d.total_power(0) == pytest.approx(0.99**2)
    assert d.total_power(2) == pytest.approx(0.99**2 * 0.01**2)
    back = r.power_by_event()["escaped"]
    assert back == pytest.approx(1 - sum(d.total_power(k) for k in range(0, 20, 2)), rel=1e-6)
    assert plate.coating == 0.01


def test_cassegrain_primary_gets_a_hole():
    scene = ns.from_sequential(lf.samples.cassegrain(), fields=[0], n_rays=800)
    prim = scene.objects[0]
    assert prim.inner_radius > 0
    d = scene.trace().detector(0)
    assert d.total_power() > 0.8
    assert d.rms_radius() < 1e-6


def test_json_roundtrip(tmp_path):
    scene = ns.from_sequential(lf.load("examples/output/cooke_triplet.lens.json"), n_rays=50)
    scene.add(ns.Sphere(radius=2, material="N-SF6", x=1, tilt_y=10, comment="ball"))
    p = tmp_path / "scene.ns.json"
    ns.save(scene, str(p))
    back = ns.load(str(p))
    assert back.to_dict() == scene.to_dict()
    r1, r2 = scene.trace(), back.trace()
    assert r1.detector(0).total_power() == pytest.approx(r2.detector(0).total_power())
    with pytest.raises(ValueError):
        lf.save(lf.samples.singlet(), str(tmp_path / "lens.json"))
        ns.load(str(tmp_path / "lens.json"))


def test_pose_angles_roundtrip():
    from lensforge.surfaces import rotation_matrix
    for a in [(10, 20, 30), (-45, 5, 0), (0, -80, 12)]:
        assert ns.angles_from_matrix(rotation_matrix(*a)) == pytest.approx(a)
    d = np.array([0.3, -0.2, 0.9])
    tx, ty = ns.direction_angles(d)
    assert rotation_matrix(tx, ty, 0)[:, 2] == pytest.approx(d / np.linalg.norm(d))


# ---------------------------------------------------------------------------
# Ref objects, prisms, Lambertian sources, ray paths, scenes kept with the lens
# ---------------------------------------------------------------------------

def test_ref_object_places_items_in_another_objects_frame():
    from lensforge.surfaces import rotation_matrix
    sc = ns.NonSequentialSystem("ref")
    sc.add(ns.Rectangle(half_x=5, half_y=5, z=20, tilt_x=45))
    c = math.sqrt(0.5)
    sc.add(ns.Rectangle(half_x=5, half_y=5, y=30 * c, z=-30 * c, ref=1))
    R, O = sc.global_pose(sc.objects[1])
    assert O == pytest.approx([0, 30, 20])
    assert R == pytest.approx(rotation_matrix(45, 0, 0))
    res = sc.resolved()
    assert res is not sc and res.objects[1].ref == 0 and res.objects[1].y == pytest.approx(30)
    assert sc.objects[1].ref == 1  # the scene itself is unchanged
    flat = ns.NonSequentialSystem("flat")
    assert flat.resolved() is flat
    # the periscope sends the beam up by 30 and along +z again
    sc.add(ns.SourceEllipse(half_x=1, half_y=1, n_rays=50, sampling="grid"))
    det = sc.add(ns.Detector(half_x=3, half_y=3, z=60, y=30))
    r = sc.trace()
    assert r.detector(det).total_power() == pytest.approx(1.0)
    assert r.system.objects[1].ref == 0  # the result holds the resolved scene
    # moving the reference moves what is placed on it
    sc.objects[0].z = 25
    assert sc.global_pose(sc.objects[1])[1] == pytest.approx([0, 30, 25])
    sc.objects[0].ref = 2
    with pytest.raises(ValueError, match="loop"):
        sc.resolved()
    sc.objects[0].ref = 9
    with pytest.raises(ValueError, match="does not exist"):
        sc.trace()


def test_right_angle_prism_retroreflects_by_tir():
    sc = ns.NonSequentialSystem("retro")
    sc.add(ns.SourceEllipse(half_x=1, half_y=1, n_rays=200, z=-15, y=4))
    sc.add(ns.Prism(base=20, apex_angle=90, half_x=6, material="N-BK7"))
    det = sc.add(ns.Detector(half_x=3, half_y=3, z=-8, y=-4))
    r = sc.trace(fresnel=False)
    d = r.detector(det)
    assert d.total_power() == pytest.approx(1.0)
    assert np.all(d.n_tir == 2)
    assert d.direction[:, 2] == pytest.approx(-1.0)  # straight back
    p = r.paths(det)
    assert len(p) == 1 and [c for _, _, c in p[0]["steps"]] == ["T", "X", "X", "T", "D"]
    assert [f for _, f, _ in p[0]["steps"]][:4] == ["base", "right", "left", "base"]


def test_prism_faces_and_minimum_deviation():
    pr = ns.Prism(base=20, apex_angle=60, half_x=5, material="N-SF11")
    assert pr.height == pytest.approx(10 / math.tan(math.radians(30)))
    names = [f.name for f in pr.faces()]
    assert names == ["base", "left", "right", "+x", "-x"]
    with pytest.raises(ValueError):
        ns.Prism(apex_angle=180).faces()
    # a ray through the prism at minimum deviation leaves at the textbook angle
    sc = ns.NonSequentialSystem("prism")
    lib = lf.shared_library()
    n = float(lib.resolve("N-SF11").index(0.55))
    i = math.degrees(math.asin(n * 0.5))
    dev = 2 * i - 60
    sc.add(ns.Prism(base=20, apex_angle=60, half_x=5, material="N-SF11", tilt_x=-90))
    h = 10 / math.tan(math.radians(30))
    P = [[0, h / 2 - 30 * math.sin(math.radians(dev / 2)), -5 - 30 * math.cos(math.radians(dev / 2))]]
    D = [[0, math.sin(math.radians(dev / 2)), math.cos(math.radians(dev / 2))]]
    r = ns.trace(sc, rays=(P, D, 1.0, 0.55), fresnel=False)
    out = r.segments["end"][-1] - r.segments["start"][-1]
    ang = math.degrees(math.atan2(out[1], out[2]))
    assert ang == pytest.approx(-dev / 2, abs=1e-6)


def test_lambertian_source():
    rng = np.random.default_rng(1)
    s = ns.SourcePoint(cone_angle=90, cos_exponent=1, n_rays=200000)
    _, D = s.local_rays(s.n_rays, rng)
    assert D[:, 2].mean() == pytest.approx(2 / 3, abs=3e-3)  # <cos> of a Lambertian emitter
    s0 = ns.SourcePoint(cone_angle=90, n_rays=200000)
    assert s0.local_rays(s0.n_rays, rng)[1][:, 2].mean() == pytest.approx(0.5, abs=3e-3)
    s2 = ns.SourceEllipse(half_x=1, half_y=1, cone_angle=30, cos_exponent=4, n_rays=1000)
    assert np.all(s2.local_rays(1000, rng)[1][:, 2] >= math.cos(math.radians(30)) - 1e-12)
    assert ns.source_from_dict(s2.to_dict()).cos_exponent == 4


def test_ray_paths_account_for_every_detected_ray():
    scene = ns.from_sequential(lf.samples.achromat(), fields=[0], n_rays=400)
    r = scene.trace(split=True, min_relative_intensity=1e-7)
    d = r.detector(0)
    paths = r.paths(0)
    assert sum(p["power"] for p in paths) == pytest.approx(d.total_power())
    assert sum(p["rays"] for p in paths) == len(d.x)
    assert paths[0]["n_reflections"] == 0 and paths[0]["fraction"] > 0.99
    ghosts = r.paths(0, rays="ghost")
    assert sum(p["power"] for p in ghosts) == pytest.approx(d.total_power("ghost"))
    assert all(p["n_reflections"] >= 2 and p["label"].endswith("4 D") for p in ghosts)
    # the segments of a ghost path start at the source and end on the detector
    g = ghosts[0]["segments"]
    assert r.segments["object"][g].max() == 3
    assert {"step", "face"} <= set(r.segments)
    with pytest.raises(ValueError):
        r.paths(0, rays="bogus")


def test_scene_is_saved_with_the_lens_and_copied_with_it(tmp_path):
    lens = lf.samples.achromat()
    lens.nonseq = ns.from_sequential(lens, n_rays=100)
    lens.nonseq.trace_settings["split"] = True
    lens.nonseq.objects[0].ref = 0
    lens.nonseq.add(ns.Prism(comment="p", ref=1, z=50))
    p = str(tmp_path / "with_scene.lens.json")
    lf.save(lens, p)
    with open(p) as f:
        text = f.read()
    assert "Infinity" not in text  # plain JSON for the browser
    back = lf.load(p)
    assert back.nonseq.to_dict() == lens.nonseq.to_dict()
    assert back.nonseq.trace_settings["split"] is True
    c = lens.copy()
    assert c.nonseq is not lens.nonseq and c.nonseq.library is lens.library
    assert c.to_dict() == lens.to_dict()
    assert lf.samples.singlet().nonseq is None and "nonseq" not in lf.samples.singlet().to_dict()


def test_scene_trace_uses_its_settings():
    sc = ns.from_sequential(lf.samples.singlet(), fields=[0], n_rays=100)
    assert sc.trace().n_rays_total == sc.trace().n_launched  # defaults: no splitting
    sc.trace_settings["split"] = True
    assert sc.trace().n_rays_total > sc.trace().n_launched
    r = sc.trace(split=False)
    assert r.n_rays_total == r.n_launched  # keywords override the settings


NS_EXAMPLES = os.path.join(os.path.dirname(__file__), "..", "examples", "non-sequential")


@pytest.mark.parametrize("name", sorted(f for f in os.listdir(NS_EXAMPLES) if f.endswith(".lens.json")))
def test_non_sequential_examples_trace(name):
    lens = lf.load(os.path.join(NS_EXAMPLES, name))
    sc = lens.nonseq
    assert sc is not None and sc.objects and sc.sources and sc.notes
    r = sc.trace()
    assert r.detectors and r.detector(0).total_power() > 0.5, name


def test_layout_plots_draw_paths_planes_and_3d():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import lensforge.plot as P
    scene = ns.from_sequential(lf.samples.achromat(), fields=[0], n_rays=200)
    r = scene.trace(split=True)
    fig = plt.figure()
    ax = P.ns_layout(r, fig.add_subplot(2, 2, 1), plane="x", color_by="wavelength", rays="ghost")
    assert ax.get_xlabel() == "z" and ax.get_ylabel() == "x"
    P.ns_layout(r, fig.add_subplot(2, 2, 2), path=r.paths(0)[1])
    P.ns_layout_3d(r, fig.add_subplot(2, 2, 3, projection="3d"), elevation=10, azimuth=30)
    for show in ("irradiance", "color", "cross_x", "cross_y", "angle"):
        P.ns_detector(r, 0, fig.add_subplot(2, 2, 4), show=show, log=True)
        fig.axes[-1].remove()
    P.ns_paths(r.paths(0), fig.add_subplot(2, 2, 4))
    plt.close(fig)
    for o in scene.objects + [ns.Prism(), ns.Sphere(), ns.CylinderVolume(), ns.RectangularVolume(), ns.Rectangle(),
                              ns.StandardSurface(inner_radius=2)]:
        for plane in ("x", "y"):
            assert all(np.all(np.isfinite(p)) for p in o.outline(plane=plane))
        assert len(o.wireframe()) >= 2
