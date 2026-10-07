import laspy
import numpy as np
import pytest
from pyproj import CRS

from goosen.core import DataError, sha256, write_json, read_json, validate_asset
from goosen.laser_ingest import crop_delivery, adopt_laser
from goosen.lidar import load_points


def delivery(tmp_path, epsg=5845):
    header = laspy.LasHeader(point_format=6, version="1.4")
    header.scales = np.array([0.01, 0.01, 0.01])
    header.offsets = np.array([395500, 6133500, 0], dtype=float)
    header.add_crs(CRS(epsg))
    las = laspy.LasData(header)
    las.x = np.array([395490, 395501, 395502, 395503, 395504, 395520])
    las.y = np.array([6133490, 6133501, 6133502, 6133503, 6133504, 6133520])
    las.z = np.array([2, 3, 4, 5, 6, 7])
    las.classification = [2, 2, 6, 18, 5, 2]
    las.withheld = [0, 0, 0, 0, 1, 0]
    path = tmp_path / "source.laz"
    las.write(path)
    item = {
        "properties": {"start_datetime": "2025-02-14T00:00:00Z", "end_datetime": "2025-02-19T00:00:00Z"},
        "assets": {
            "data": {
                "href": "https://dl1.lantmateriet.se/test.laz",
                "file:size": path.stat().st_size,
                "file:checksum": "1220" + sha256(path),
            }
        },
    }
    return path, item


def test_crop_preserves_datum_flags_and_verified_provenance(tmp_path):
    source, item = delivery(tmp_path)
    bounds = [395500, 6133500, 395510, 6133510]
    output = tmp_path / "crop.laz"
    report = crop_delivery(source, item, bounds, output)
    assert report["point_count"] == 4
    assert report["class_counts"] == {"2": 1, "5": 1, "6": 1, "18": 1}
    with laspy.open(output) as r:
        assert CRS(r.header.parse_crs()).equals(CRS(5845))
        p = r.read()
        assert list(p.classification) == [2, 6, 18, 5]
        assert list(p.withheld) == [0, 0, 0, 1]
        assert np.allclose(p.z, [3, 4, 5, 6])
    clean = load_points(output, bounds)
    assert len(clean) == 2  # noise and withheld points excluded only at analysis time
    assert list(clean[:, 3]) == [2, 6]


def test_crop_rejects_corrupt_source_budget_and_wrong_vertical_datum(tmp_path):
    source, item = delivery(tmp_path)
    bounds = [395500, 6133500, 395510, 6133510]
    output = tmp_path / "crop.laz"
    with pytest.raises(DataError, match="budget"):
        crop_delivery(source, item, bounds, output, max_points=2)
    assert not output.exists()
    item["assets"]["data"]["file:checksum"] = "1220" + "0" * 64
    with pytest.raises(DataError, match="checksum"):
        crop_delivery(source, item, bounds, output)
    source, item = delivery(tmp_path, epsg=3006)
    with pytest.raises(DataError, match="RH2000"):
        crop_delivery(source, item, bounds, output)
    assert not output.exists()


def test_adopt_catalog_is_portable_and_does_not_overwrite(tmp_path):
    source, item = delivery(tmp_path)
    write_json(tmp_path / "item.json", item)
    write_json(tmp_path / "catalog.json", {"schema": 1, "assets": {}})
    write_json(
        tmp_path / "permission.json",
        {
            "use_status": "authorized",
            "license": "synthetic test",
            "license_evidence": "test",
            "allowed_sources": [item["assets"]["data"]["href"]],
        },
    )
    c = {"bounds": [395500, 6133500, 395510, 6133510], "halo_m": 1}
    args = (
        c,
        tmp_path / "catalog.json",
        source,
        tmp_path / "item.json",
        tmp_path / "permission.json",
        tmp_path / "catalog-laser.json",
    )
    report = adopt_laser(*args)
    assert report["point_count"] == 4
    out = read_json(args[-1])
    for role, records in out["assets"].items():
        for record in records:
            assert validate_asset(record, tmp_path, role).is_file()
            assert record["source"] == item["assets"]["data"]["href"]
    with pytest.raises(DataError, match="fresh"):
        adopt_laser(*args)
