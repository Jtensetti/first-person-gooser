import json
import zipfile

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import Polygon, box

from goosen.core import DataError, transform_xy
from goosen.rasters import Grid, warp_nodes, mesh_payload
from goosen.vectors import esri_polygon, polygon_mesh, read_features
from goosen.world import scatter
from goosen.lidar import derive_building, derive_canopy


def raster(path, values, transform, crs=3006):
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=values.shape[0],
        width=values.shape[1],
        count=1,
        dtype=values.dtype,
        crs=crs,
        transform=transform,
        nodata=-9999,
    ) as dst:
        dst.write(values, 1)
    return path


def test_smygehuk_coordinate_roundtrip_and_axis_order():
    lon, lat = transform_xy(3006, 4326)(395500, 6133500)
    assert lon == pytest.approx(13.3524784364, abs=1e-8)
    assert lat == pytest.approx(55.3367358842, abs=1e-8)
    assert transform_xy(4326, 3006)(lon, lat) == pytest.approx((395500, 6133500), abs=1e-5)
    assert transform_xy(5845, 3006)(395500, 6133500) == pytest.approx((395500, 6133500))


def test_raster_centres_are_mesh_nodes_and_shared_edges_match(tmp_path):
    # Analytic plane z=x+2y makes a half-pixel shift observable.
    x, y = np.meshgrid(np.arange(5), np.arange(4, -1, -1))
    p = raster(tmp_path / "plane.tif", (x + 2 * y).astype("float32"), from_origin(-0.5, 4.5, 1, 1))
    g = warp_nodes([p], [0, 0, 4, 4], 1)
    np.testing.assert_allclose(g.values, x + 2 * y)
    a, b = g.tile([0, 0, 2, 4], 1), g.tile([2, 0, 4, 4], 1)
    np.testing.assert_array_equal(a.values[:, -1], b.values[:, 0])
    vertices = np.array(mesh_payload(g, [0, 0, 0])["vertices"])
    assert vertices[0].tolist() == [0, 4, 8]
    face = mesh_payload(g, [0, 0, 0])["faces"][0]
    assert np.cross(vertices[face[1]] - vertices[face[0]], vertices[face[2]] - vertices[face[0]])[2] > 0


def test_zip_disguised_as_tiff_supported(tmp_path):
    p = raster(tmp_path / "source.tif", np.ones((3, 3), dtype="float32"), from_origin(-0.5, 2.5, 1, 1))
    z = tmp_path / "legacy.tif"
    with zipfile.ZipFile(z, "w") as bundle:
        bundle.write(p, "elevation.tif")
    np.testing.assert_allclose(warp_nodes([z], [0, 0, 2, 2], 1).values, 1)


def test_nodata_never_becomes_land_or_poison_zero_weight_neighbor():
    g = Grid(np.array([[1.0, np.nan], [3.0, 4.0]]), 0, 1, 1)
    assert float(g.sample(0, 1)) == 1
    assert np.isnan(g.sample(0.5, 0.5))
    assert np.isnan(g.sample(-1, 0))
    assert mesh_payload(g, [0, 0, 0])["faces"] == []


def test_categorical_resampling_keeps_classes_and_detects_conflict(tmp_path):
    a = np.array([[3, 62, 62], [3, 3, 62], [51, 51, 62]], dtype="int16")
    p = raster(tmp_path / "nmd.tif", a, from_origin(-0.5, 2.5, 1, 1))
    g = warp_nodes([p], [0, 0, 2, 2], 0.5, "categorical")
    assert set(np.unique(g.values)) <= {3, 51, 62}
    q = raster(tmp_path / "other.tif", np.full((3, 3), 111, dtype="int16"), from_origin(-0.5, 2.5, 1, 1))
    with pytest.raises(DataError, match="Conflicting"):
        warp_nodes([p, q], [0, 0, 2, 2], 1, "categorical")


def test_polygon_roof_preserves_courtyard_concavity_and_winding():
    poly = Polygon([(0, 0), (10, 0), (10, 10), (6, 10), (6, 6), (0, 6)], [[(1, 1), (1, 3), (3, 3), (3, 1)]])
    mesh = polygon_mesh(poly, lambda x, y: 7, [0, 0, 0])
    total = 0
    for f in mesh["faces"]:
        triangle = Polygon([mesh["vertices"][i][:2] for i in f])
        assert poly.covers(triangle)
        assert triangle.exterior.is_ccw
        total += triangle.area
    assert total == pytest.approx(poly.area)
    restored = esri_polygon([list(poly.exterior.coords), list(poly.interiors[0].coords)])
    assert restored.equals(poly)


def test_multipatch_cannot_silently_turn_into_2d_footprint(tmp_path):
    p = tmp_path / "3d.json"
    p.write_text(json.dumps({"geometryType": "esriGeometryMultiPatch", "features": []}))
    with pytest.raises(DataError, match="multipatches"):
        read_features(p, "EPSG:3006")


def test_scatter_deterministic_seams_and_exclusions():
    g = Grid(np.ones((21, 21)), 0, 20, 1)
    exclusion = box(4, 4, 7, 8)
    common = dict(grid=g, spacing=1, seed=17, origin=[0, 0, 0], kind="grass", height=0.5, exclusion=exclusion)
    whole = scatter(box(0, 0, 20, 20), **common)
    pieces = scatter(box(0, 0, 10, 20), **common) + scatter(box(10, 0, 20, 20), **common)

    def key(p):
        return tuple(p["position"])

    assert sorted(whole, key=key) == sorted(pieces, key=key)
    assert len({key(p) for p in whole}) == len(whole)
    from shapely.geometry import Point

    assert all(not exclusion.covers(Point(p["position"][:2])) for p in whole)
    assert scatter(box(0, 0, 20, 20), limit=0, **common) == []


def test_lidar_roof_fit_requires_spatial_support_and_normalizes_ground():
    terrain = Grid(np.full((31, 31), 10.0), 0, 30, 1)
    x, y = np.meshgrid(np.arange(2, 19, 2), np.arange(2, 19, 2))
    x, y = x.ravel(), y.ravel()
    points = np.column_stack([x, y, 16 + 0.1 * x, np.ones_like(x)])
    r = derive_building(box(0, 0, 20, 20), points, terrain)
    assert r["status"] == "derived"
    assert r["roof_plane"][0] == pytest.approx(0.1)
    assert r["height_m"] == pytest.approx(7.8)
    assert derive_building(box(0, 0, 20, 20), points[:4], terrain)["status"] == "insufficient_points"
    canopy = derive_canopy(points, terrain, Grid(np.full((31, 31), 115.0), 0, 30, 1))
    assert len(canopy) > 0
    assert max(p["height_m"] for p in canopy) == pytest.approx(7.8)


def test_terrain_is_cut_at_real_water_edge_without_double_surface():
    from goosen.vectors import clip_terrain_water

    g = Grid(np.zeros((6, 6)), 0, 5, 1)
    water = box(2.3, 0, 5, 5)
    mesh = clip_terrain_water(mesh_payload(g, [0, 0, 0]), g, water, [0, 0, 0])
    area = 0
    for face in mesh["faces"]:
        poly = Polygon([mesh["vertices"][i][:2] for i in face])
        assert poly.intersection(water).area < 1e-9
        area += poly.area
    assert area == pytest.approx(2.3 * 5)
