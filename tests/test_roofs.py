import numpy as np
from shapely.geometry import box
from shapely.affinity import rotate, translate
from goosen.lidar import fit_gable
from goosen.architecture import plane_building
from goosen.architecture import modeled_gable, lowrise_eave


class Ground:
    def sample(self, x, y):
        return np.zeros_like(np.asarray(x), dtype=float) + 3


def test_lowrise_fallback_ignores_contaminated_laser_maximum():
    profile = {"eave_m": 3.0, "outbuilding_eave_m": 2.4}
    geom = box(0, 0, 6, 5)
    eave = lowrise_eave(geom, {"building": "bungalow"}, profile)
    a = modeled_gable(geom, Ground(), 10.2, [0, 0, 0], eave_height=eave)
    b = modeled_gable(geom, Ground(), 24, [0, 0, 0], eave_height=eave)
    assert a == b
    assert a["evidence"] == "modeled"
    assert a["rule"] == "modeled_lowrise_gable"
    assert min(v[2] for v in a["roof"]["vertices"]) == 5.4
    assert max(v[2] for v in a["roof"]["vertices"]) < 7.1


def test_lowrise_complex_footprint_preserved_and_special_buildings_excluded():
    profile = {"eave_m": 3.0, "outbuilding_eave_m": 2.4}
    geom = box(0, 0, 14, 10).difference(box(7, 5, 14, 10))
    m = modeled_gable(geom, Ground(), 12, [0, 0, 0], eave_height=3)
    assert m and m["rule"] == "modeled_lowrise_hip"
    assert max(v[2] for v in m["walls"]["vertices"]) == 6
    area = sum(
        abs(
            np.cross(
                np.subtract(m["roof"]["vertices"][f[1]], m["roof"]["vertices"][f[0]]),
                np.subtract(m["roof"]["vertices"][f[2]], m["roof"]["vertices"][f[0]]),
            )[2]
        )
        / 2
        for f in m["roof"]["faces"]
    )
    assert abs(area - geom.area) < 1e-8
    assert max(v[2] for v in m["roof"]["vertices"]) <= 8.8
    assert lowrise_eave(box(0, 0, 5, 5), {"building": "lighthouse"}, profile) is None
    assert lowrise_eave(box(0, 0, 40, 30), {"building": "yes"}, profile) is None


def fixture(angle=0):
    rng = np.random.default_rng(41)
    xy = rng.uniform([-9, -4], [9, 4], (600, 2))
    z = 11 - 0.65 * np.abs(xy[:, 1] - 0.3) + rng.normal(0, 0.06, 600)
    a = np.radians(angle)
    matrix = np.array([[np.cos(a), -np.sin(a)], [np.sin(a), np.cos(a)]])
    xy = xy @ matrix.T + [395600, 6133600]
    geom = translate(rotate(box(-10, -5, 10, 5), angle, origin=(0, 0)), 395600, 6133600)
    return geom, np.column_stack([xy, z])


def test_gable_rotation_offset_and_noise():
    for angle in [0, 33, 89]:
        geom, p = fixture(angle)
        q = fit_gable(geom, p)
        assert q is not None
        assert q["heldout_fraction"] > 0.95
        mesh = plane_building(geom, Ground(), [395500, 6133500, 0], q["planes"], q)
        assert mesh and mesh["evidence"] == "derived"
        for x, y, z in mesh["roof"]["vertices"]:
            expected = min(
                a * (x + 395500 - cx) + b * (y + 6133500 - cy) + c for a, b, c, cx, cy in q["planes"]
            )
            assert abs(z - expected) < 1e-7
        assert len(mesh["roof"]["faces"]) >= 4


def test_gable_rejects_vegetation_flat_and_sparse():
    geom, p = fixture()
    assert fit_gable(geom, p[:15]) is None
    p[:, 2] = 8
    assert fit_gable(geom, p) is None
    p[:, 2] = np.random.default_rng(22).uniform(7, 15, len(p))
    assert fit_gable(geom, p) is None


def test_plane_geometry_preserves_hole_and_area():
    geom = box(0, 0, 20, 20).difference(box(5, 5, 15, 15))
    m = plane_building(geom, Ground(), [0, 0, 0], [[0, 0, 9, 0, 0]])
    area = 0
    for f in m["roof"]["faces"]:
        a, b, c = np.asarray([m["roof"]["vertices"][i] for i in f])
        area += abs(np.cross(b - a, c - a)[2]) / 2
    assert abs(area - geom.area) < 1e-8
    assert len(m["walls"]["faces"]) == 8


def test_canopy_candidates_exclude_roofs_and_require_spread():
    from goosen.lidar import canopy_peaks
    from shapely.geometry import Point

    points = []
    for x in range(1, 20, 2):
        for y in range(1, 20, 2):
            for height in [4, 5, 6, 7]:
                points.append([x, y, height + 3, 1])
    points = np.asarray(points)
    roof = box(0, 0, 9, 20)
    result = canopy_peaks(points, Ground(), roof, [0, 0, 20, 20])
    assert result
    assert all(not roof.contains(Point(t["x"], t["y"])) for t in result)
    assert result == canopy_peaks(points, Ground(), roof, [0, 0, 20, 20])
    points[:, 2] = 9
    assert not canopy_peaks(points, Ground(), roof, [0, 0, 20, 20])
