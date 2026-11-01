"""Non-sequential ray tracing and ray splitting."""

import math

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
