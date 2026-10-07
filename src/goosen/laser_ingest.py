"""Verify an authorized LM delivery and crop it locally without changing its datum."""

import copy
import os
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import laspy
import numpy as np
from pyproj import CRS

from .acquire import receipt
from .core import DataError, read_json, sha256, write_json


def crop_delivery(source, item, bounds, output, max_points=5_000_000):
    """Keep every point/flag inside the AOI. Filtering happens during analysis."""
    asset = item["assets"]["data"]
    digest = asset.get("file:checksum", "")
    if not digest.startswith("1220") or len(digest) != 68:
        raise DataError("LM delivery must have a STAC SHA-256 checksum")
    source, output = Path(source), Path(output)
    if source.stat().st_size != asset.get("file:size") or sha256(source) != digest[4:]:
        raise DataError("Downloaded laser file does not match STAC size/checksum")
    if output.exists():
        raise DataError("Choose a fresh laser crop path")
    w, s, e, n = bounds
    if not all(np.isfinite(bounds)) or w >= e or s >= n:
        raise DataError("Invalid laser crop bounds")
    counts, total = {}, 0
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".laser-", dir=output.parent) as tmp:
        stage = Path(tmp) / "pilot.laz"
        with laspy.open(source) as reader:
            crs = reader.header.parse_crs()
            if crs is None or not CRS(crs).equals(CRS(5845)):
                raise DataError("Laser source must declare SWEREF99 TM + RH2000 (EPSG:5845)")
            low, high = reader.header.mins, reader.header.maxs
            if low[0] > w or low[1] > s or high[0] < e or high[1] < n:
                raise DataError("Laser delivery extent does not cover pilot plus halo")
            header = copy.deepcopy(reader.header)
            # Output is sequential LAZ, not COPC; never retain an obsolete octree.
            header.vlrs = [v for v in header.vlrs if v.user_id.lower() != "copc"]
            header.evlrs = None
            with laspy.open(stage, mode="w", header=header, do_compress=True) as writer:
                for chunk in reader.chunk_iterator(1_000_000):
                    mask = (chunk.x >= w) & (chunk.x <= e) & (chunk.y >= s) & (chunk.y <= n)
                    part = chunk[mask]
                    total += len(part)
                    if total > max_points:
                        raise DataError("Laser pilot point budget exceeded")
                    if len(part):
                        writer.write_points(part)
                        keys, sizes = np.unique(part.classification, return_counts=True)
                        for key, size in zip(keys, sizes):
                            counts[str(int(key))] = counts.get(str(int(key)), 0) + int(size)
            if not total:
                raise DataError("No laser points in pilot")
        with laspy.open(stage) as reader:
            if reader.header.point_count != total or not CRS(reader.header.parse_crs()).equals(CRS(5845)):
                raise DataError("Laser crop failed round-trip verification")
        os.replace(stage, output)
    return {
        "source_sha256": digest[4:],
        "point_count": total,
        "class_counts": counts,
        "bounds": list(bounds),
        "horizontal_crs": "EPSG:3006",
        "vertical_crs": "EPSG:5613",
        "format": "LAZ (spatially cropped, all original point flags retained)",
        "coverage_note": "Extent coverage is checked; local point density/voids require further QA.",
    }


def adopt_laser(c, catalog, source, item_path, permission_path, output):
    catalog, output = Path(catalog).resolve(), Path(output).resolve()
    if output.exists() or output.parent != catalog.parent:
        raise DataError("Choose a fresh sibling catalog")
    item, permission = read_json(item_path), read_json(permission_path)
    url = item["assets"]["data"]["href"]
    if urlparse(url).scheme != "https" or urlparse(url).hostname != "dl1.lantmateriet.se":
        raise DataError("Unapproved laser source")
    if (
        permission.get("use_status") != "authorized"
        or not permission.get("license_evidence")
        or url not in permission.get("allowed_sources", [])
    ):
        raise DataError("Authorized product use and exact source permission must be recorded")
    folder = catalog.parent / "laser"
    if folder.exists():
        raise DataError("Laser import exists; use a fresh catalog folder")
    w, s, e, n = c["bounds"]
    h = c["halo_m"]
    with tempfile.TemporaryDirectory(prefix=".laser-adopt-", dir=catalog.parent) as tmp:
        stage = Path(tmp) / "laser"
        stage.mkdir()
        report = crop_delivery(source, item, [w - h, s - h, e + h, n + h], stage / "pilot.laz")
        write_json(stage / "item.json", item)
        write_json(stage / "crop-qa.json", report)
        props = item["properties"]
        common = dict(
            evidence="derived",
            use_status="authorized",
            redistribution_status=permission.get("redistribution_status", "review"),
        )
        record = receipt(
            stage / "pilot.laz",
            url,
            permission["license"],
            permission["license_evidence"],
            horizontal_crs="EPSG:3006",
            vertical_crs="EPSG:5613",
            observation_start=props.get("start_datetime"),
            observation_end=props.get("end_datetime"),
            source_sha256=report["source_sha256"],
            point_count=report["point_count"],
            **common,
        )
        support = [
            receipt(stage / name, url, permission["license"], permission["license_evidence"], **common)
            for name in ("item.json", "crop-qa.json")
        ]
        result = read_json(catalog)
        for role, records in {"lidar": [record], "lidar_source": support}.items():
            for rec in records:
                rec["path"] = "laser/" + rec["path"]
            result["assets"][role] = records
        os.replace(stage, folder)
    write_json(output, result)
    return report
