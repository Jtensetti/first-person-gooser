import gzip
import json
from pathlib import Path

import numpy as np
import pytest
from shapely.geometry import box, mapping, Point

from goosen.core import DataError, write_json, sha256, load_config
from goosen.world import prepare
from goosen.qa import audit_world
from test_geography import raster
from rasterio.transform import from_origin


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
