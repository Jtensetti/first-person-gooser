import gzip
import json
from pathlib import Path

import numpy as np
import pytest
import laspy
from pyproj import CRS
from shapely.geometry import box, mapping, Point

from goosen.core import DataError, write_json, sha256, load_config
from goosen.world import prepare
from goosen.qa import audit_world
from test_geography import raster
from rasterio.transform import from_origin


def test_laser_world_retains_halo_and_reports_height_evidence(inputs, tmp_path):
    c, catalog = inputs
    w, s, _, _ = c["bounds"]
    h = laspy.LasHeader(point_format=6, version="1.4")
    h.add_crs(CRS(5845))
    p = laspy.LasData(h)
    x, y = np.meshgrid(np.arange(101, 110), np.arange(101, 110))
    p.x = np.r_[w + x.ravel(), w - 2]
    p.y = np.r_[s + y.ravel(), s - 2]
    p.z = np.r_[15 + 0.1 * (x.ravel() - 101), 8]
    p.classification = np.r_[np.ones(x.size, dtype=np.uint8), 2]
    path = tmp_path / "pilot.laz"
    p.write(path)
    data = json.loads(catalog.read_text())
    data["assets"]["lidar"] = [
        {
            "path": path.name,
            "sha256": sha256(path),
            "source": "synthetic fixture",
            "license": "test",
            "license_evidence": "test",
            "use_status": "open",
            "evidence": "modeled",
            "horizontal_crs": "EPSG:3006",
            "vertical_crs": "EPSG:5613",
        }
    ]
    write_json(catalog, data)
    result = prepare(c, catalog, tmp_path / "laser-world", True)
    qa = result["lidar_qa"]
    assert qa["usable_points"] == 82
    assert qa["ground_comparison"]["samples"] == 1
    assert qa["ground_comparison"]["median_m"] == pytest.approx(0)
    assert qa["derived_heights"] == 1
    assert qa["fitted_single_planes"] == 1
    assert result["acceptance_passed"] is False


@pytest.fixture
def inputs(tmp_path):
    c = load_config(Path(__file__).parents[1] / "configs/pilot.json")
    c.update(bounds=[395500, 6133500, 395750, 6133750], tile_size_m=250, lod_steps_m=[2, 10])
    w, s, e, n = c["bounds"]
    assets = {}
    for role, code in [("terrain", 8), ("landcover", 3)]:
        p = raster(
            tmp_path / (role + ".tif"),
            np.full((157, 157), code, dtype="float32"),
            from_origin(w - 31, n + 31, 2, 2),
        )
        assets[role] = [
            {
                "path": p.name,
                "sha256": sha256(p),
                "source": "synthetic fixture",
                "license": "test",
                "license_evidence": "test fixture",
                "use_status": "open",
                "evidence": "modeled",
                "vertical_crs": "EPSG:5613",
                "horizontal_crs": "EPSG:3006",
                "native_resolution_m": 2,
                "surface_kind": "DTM",
            }
        ]
    for role, geom, props in [
        ("buildings", box(w + 100, s + 100, w + 110, s + 110), {"height_m": 7}),
        ("fields", box(w + 30, s + 30, w + 210, s + 210), {"arslager": 2025, "grdkod_mar": 50}),
        ("roads", box(w + 60, s, w + 65, n), {"width_m": 5}),
        ("water", box(w + 160, s + 160, w + 175, s + 175), {"water_level_m": 8, "vertical_crs": "EPSG:5613"}),
    ]:
        p = tmp_path / (role + ".json")
        write_json(
            p,
            {
                "type": "FeatureCollection",
                "features": [{"type": "Feature", "id": role, "geometry": mapping(geom), "properties": props}],
            },
        )
        assets[role] = [
            {
                "path": p.name,
                "sha256": sha256(p),
                "source": "synthetic fixture",
                "license": "test",
                "license_evidence": "test fixture",
                "use_status": "open",
                "evidence": "modeled",
                "horizontal_crs": "EPSG:3006",
            }
        ]
    catalog = tmp_path / "catalog.json"
    write_json(catalog, {"schema": 1, "assets": assets, "crop_map": c["crop_map"]})
    return c, catalog


def test_end_to_end_reproducible_meshes_and_no_plants_on_buildings_roads_water(inputs, tmp_path):
    c, catalog = inputs
    a = prepare(c, catalog, tmp_path / "a", True)
    b = prepare(c, catalog, tmp_path / "b", True)
    assert [t["sha256"] for t in a["tiles"]] == [t["sha256"] for t in b["tiles"]]
    assert audit_world(tmp_path / "a")["structural_pass"]
    tile = json.loads(gzip.decompress((tmp_path / "a" / a["tiles"][0]["file"]).read_bytes()))
    exclude = box(100, 100, 110, 110).buffer(0.5).union(box(60, 0, 65, 250)).union(box(160, 160, 175, 175))
    assert tile["instances"]
    assert all(not exclude.covers(Point(p["position"][:2])) for p in tile["instances"])
    with pytest.raises(DataError, match="already exists"):
        prepare(c, catalog, tmp_path / "a", True)


def test_preview_does_not_bypass_license_and_production_rejects_coarse_datum(inputs, tmp_path):
    c, catalog = inputs
    j = json.loads(catalog.read_text())
    j["assets"]["terrain"][0]["vertical_crs"] = "EPSG:5773"
    write_json(catalog, j)
    with pytest.raises(DataError, match="RH2000"):
        prepare(c, catalog, tmp_path / "reject", False)
    assert not (tmp_path / "reject").exists()
    j["assets"]["terrain"][0]["use_status"] = "review"
    write_json(catalog, j)
    with pytest.raises(DataError, match="use is not cleared"):
        prepare(c, catalog, tmp_path / "reject-preview", True)


def test_wrong_crop_year_is_not_silently_reinterpreted(inputs, tmp_path):
    c, catalog = inputs
    j = json.loads(catalog.read_text())
    j["crop_map"]["year"] = 2026
    write_json(catalog, j)
    with pytest.raises(DataError, match="same year"):
        prepare(c, catalog, tmp_path / "reject", True)


def test_duplicate_authoritative_sources_are_not_double_built(inputs, tmp_path):
    c, catalog = inputs
    j = json.loads(catalog.read_text())
    j["assets"]["buildings"] *= 2
    write_json(catalog, j)
    with pytest.raises(DataError, match="deduplicate"):
        prepare(c, catalog, tmp_path / "reject", True)


def test_orthophoto_is_consumed_and_texture_tampering_fails_qa(inputs, tmp_path):
    import rasterio

    c, catalog = inputs
    w, s, e, n = c["bounds"]
    p = tmp_path / "ortho.tif"
    with rasterio.open(
        p,
        "w",
        driver="GTiff",
        width=250,
        height=250,
        count=3,
        dtype="uint8",
        crs="EPSG:3006",
        transform=from_origin(w, n, 1, 1),
    ) as ds:
        ds.write(np.full((3, 250, 250), 120, dtype="uint8"))
    j = json.loads(catalog.read_text())
    j["assets"]["orthophoto"] = [
        {
            **j["assets"]["landcover"][0],
            "path": p.name,
            "sha256": sha256(p),
            "rgb_bands": [1, 2, 3],
            "color_space": "sRGB",
            "observation_year": 2025,
        }
    ]
    write_json(catalog, j)
    output = tmp_path / "with-ortho"
    m = prepare(c, catalog, output, True)
    tile = json.loads(gzip.decompress((output / m["tiles"][0]["file"]).read_bytes()))
    assert tile["ground_texture_info"]["kind"] == "orthophoto"
    assert not any("No licensed orthophoto" in g for g in m["gaps"])
    assert audit_world(output)["structural_pass"]
    (output / tile["ground_texture"]).write_bytes(b"tampered")
    assert not audit_world(output)["structural_pass"]


def test_frozen_coast_replaces_nmd_sea_retains_lake_and_rejects_changed_polygon(inputs, tmp_path):
    from goosen.coast import parse_coast
    from goosen.core import transform_xy
    from shapely.geometry import Polygon

    c, catalog = inputs
    w, s, e, n = c["bounds"]
    xy = transform_xy(3006, 4326)
    coords = [xy(w - 30, s + 80), xy(e + 30, s + 80)]
    raw = (
        "<osm>"
        + "".join(f'<node id="{i}" lon="{x}" lat="{y}"/>' for i, (x, y) in enumerate(coords))
        + '<way id="1"><nd ref="0"/><nd ref="1"/>'
        '<tag k="natural" v="coastline"/></way></osm>'
    ).encode()
    raw_path = tmp_path / "coast.osm"
    raw_path.write_bytes(raw)
    sea, _ = parse_coast(raw, c["bounds"])
    path = tmp_path / "coast.json"
    data = {
        "type": "FeatureCollection",
        "features": [
            {"id": "sea", "type": "Feature", "geometry": mapping(sea), "properties": {"water": "sea"}}
        ],
    }
    write_json(path, data)
    j = json.loads(catalog.read_text())
    template = j["assets"]["water"][0]
    j["assets"]["coastline_source"] = [{**template, "path": raw_path.name, "sha256": sha256(raw_path)}]
    j["assets"]["coastline"] = [
        {
            **template,
            "path": path.name,
            "sha256": sha256(path),
            "coverage_kind": "directed_coast_partition",
            "coverage_bounds": c["bounds"],
            "raw_sha256": sha256(raw_path),
        }
    ]
    # Deliberately wrong coarse sea mask: authoritative vector must restore land.
    land = tmp_path / "landcover.tif"
    raster(land, np.full((157, 157), 62, dtype="float32"), from_origin(w - 31, n + 31, 2, 2))
    j["assets"]["landcover"][0]["sha256"] = sha256(land)
    write_json(catalog, j)
    output = tmp_path / "with-coast"
    m = prepare(c, catalog, output, True)
    tile = json.loads(gzip.decompress((output / m["tiles"][0]["file"]).read_bytes()))
    water = [o for o in tile["objects"] if o["kind"] == "water"]
    assert {o["id"] for o in water} == {"water-osm-sea", "water-water"}
    assert all(o["level_evidence"] == "modeled" for o in water if o["id"] == "water-osm-sea")

    def area(obj):
        v = obj["mesh"]["vertices"]
        return sum(Polygon([v[i][:2] for i in f]).area for f in obj["mesh"]["faces"])

    assert sum(area(o) for o in water) == pytest.approx(20000 + 225, abs=0.01)
    terrain = next(o for o in tile["objects"] if o["kind"] == "terrain" and o["lod"] == 0)
    assert area(terrain) == pytest.approx(62500 - 20000 - 225, abs=0.01)
    assert all(p["position"][1] >= 80 - 1e-6 for p in tile["instances"])
    assert audit_world(output)["structural_pass"]
    assert m["coast_qa"]["terrain_seam"]["residual_median_m"] == pytest.approx(8)
    data["features"][0]["geometry"] = mapping(box(w, s, e, n))
    write_json(path, data)
    j["assets"]["coastline"][0]["sha256"] = sha256(path)
    write_json(catalog, j)
    with pytest.raises(DataError, match="differs from its frozen coastline"):
        prepare(c, catalog, tmp_path / "bad-coast", True)


def test_context_surfaces_clip_buildings_and_water(inputs, tmp_path):
    from shapely.geometry import Polygon

    c, catalog = inputs
    w, s, e, n = c["bounds"]
    j = json.loads(catalog.read_text())
    path = tmp_path / "context.json"
    write_json(
        path,
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "id": "parking",
                    "geometry": mapping(box(w + 90, s + 90, w + 180, s + 180)),
                    "properties": {"amenity": "parking", "surface": "asphalt"},
                }
            ],
        },
    )
    j["assets"]["context"] = [{**j["assets"]["buildings"][0], "path": path.name, "sha256": sha256(path)}]
    write_json(catalog, j)
    out = tmp_path / "context-world"
    m = prepare(c, catalog, out, True)
    tile = json.loads(gzip.decompress((out / m["tiles"][0]["file"]).read_bytes()))
    surface = next(o for o in tile["objects"] if o["id"] == "context-parking")
    forbidden = box(100, 100, 110, 110).union(box(160, 160, 175, 175))
    for face in surface["mesh"]["faces"]:
        poly = Polygon([surface["mesh"]["vertices"][i][:2] for i in face])
        assert poly.intersection(forbidden).area < 1e-7
    assert surface["material"] == "asphalt"
    assert surface["material_evidence"] == "modeled"


def test_missing_path_width_uses_narrow_model(inputs, tmp_path):
    from shapely.geometry import LineString, Polygon

    c, catalog = inputs
    w, s, e, n = c["bounds"]
    j = json.loads(catalog.read_text())
    path = tmp_path / j["assets"]["roads"][0]["path"]
    write_json(
        path,
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "id": "path",
                    "geometry": mapping(LineString([(w + 10, s + 10), (w + 10, s + 110)])),
                    "properties": {"highway": "path"},
                }
            ],
        },
    )
    j["assets"]["roads"][0]["sha256"] = sha256(path)
    write_json(catalog, j)
    out = tmp_path / "path-world"
    m = prepare(c, catalog, out, True)
    tile = json.loads(gzip.decompress((out / m["tiles"][0]["file"]).read_bytes()))
    road = next(o for o in tile["objects"] if o["id"] == "road-path")
    area = sum(Polygon([road["mesh"]["vertices"][i][:2] for i in f]).area for f in road["mesh"]["faces"])
    assert area == pytest.approx(150)
    assert road["material"] == "gravel"
    assert road["evidence"] == "modeled"
