"""Directed OSM coast → bounded sea polygons, without invented closing coasts."""

from __future__ import annotations

import os
import tempfile
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

from shapely.geometry import LineString, Point, box, mapping
from shapely.ops import polygonize_full, unary_union

from .acquire import receipt, session
from .core import DataError, geographic_bounds, transform_xy, write_json


def sea_from_lines(lines, bounds):
    """Land is left, sea right. Only the AOI boundary may close open ways.

    Fail on gaps, branches, overlaps and inconsistent direction. Topological
    completeness is not a statement about surveyed positional accuracy.
    """
    region = box(*bounds)
    segments = []
    for line in lines:
        if not line.is_simple:
            raise DataError("Self-intersecting coastline")
        for a, b in zip(line.coords, list(line.coords)[1:]):
            segment = LineString([a, b]).intersection(region)
            if segment.is_empty or segment.length == 0:
                continue
            if segment.geom_type != "LineString" or segment.length < 1e-7:
                raise DataError("Degenerate coastline segment")
            if region.boundary.intersection(segment).length:
                raise DataError("Coastline coincides with AOI boundary; expand acquisition bounds")
            segments.append(segment)
    if not segments:
        raise DataError("No coastline crosses this job; sea/land cannot be inferred")
    if len(segments) > 100_000:
        raise DataError("Coastline segment budget exceeded")
    starts = Counter(tuple(s.coords[0]) for s in segments)
    ends = Counter(tuple(s.coords[-1]) for s in segments)
    for xy in starts.keys() | ends.keys():
        if region.boundary.distance(Point(xy)) > 1e-7 and (starts[xy] != 1 or ends[xy] != 1):
            raise DataError("Incomplete, branching or reversed coastline inside the job")
    coast = unary_union(segments)
    if abs(coast.length - sum(s.length for s in segments)) > 1e-6:
        raise DataError("Overlapping coastline segments")
    cells, cuts, dangles, invalid = polygonize_full(unary_union([coast, region.boundary]))
    if any(not g.is_empty for g in (cuts, dangles, invalid)):
        raise DataError("Coastline cannot form complete bounded polygons")
    cells = list(cells.geoms)
    if abs(sum(p.area for p in cells) - region.area) > 1e-5:
        raise DataError("Coastline partition does not cover the job")
    from shapely.strtree import STRtree

    tree = STRtree(cells)
    labels = [set() for _ in cells]
    for segment in segments:
        a, b = segment.coords
        dx, dy = b[0] - a[0], b[1] - a[1]
        midpoint = segment.interpolate(0.5, normalized=True)
        # Small offset is a side test, never a buffer or adjustment of geography.
        for distance in (min(0.01, segment.length / 100), 1e-5, 1e-7):
            left = Point(
                midpoint.x - dy / segment.length * distance, midpoint.y + dx / segment.length * distance
            )
            right = Point(
                midpoint.x + dy / segment.length * distance, midpoint.y - dx / segment.length * distance
            )
            li = tree.query(left, predicate="within")
            ri = tree.query(right, predicate="within")
            if len(li) == len(ri) == 1 and li[0] != ri[0]:
                labels[li[0]].add("land")
                labels[ri[0]].add("sea")
                break
        else:
            raise DataError("Ambiguous coast side; no heuristic sea fill allowed")
    if any(len(label) != 1 for label in labels):
        raise DataError("Inconsistent coastline direction or unclassified region")
    sea = unary_union([p for p, label in zip(cells, labels) if label == {"sea"}])
    return sea, {
        "segments": len(segments),
        "partition_cells": len(cells),
        "coast_length_m": coast.length,
        "sea_area_m2": sea.area,
        "land_area_m2": region.area - sea.area,
        "topology_pass": True,
        "positional_accuracy_verified": False,
    }


def parse_coast(raw, bounds):
    root = ET.fromstring(raw)
    if root.tag != "osm" or root.find("remark") is not None or root.find("error") is not None:
        raise DataError("Incomplete or erroneous coastline response")
    xy = transform_xy(4326, 3006)
    nodes = {n.attrib["id"]: xy(float(n.attrib["lon"]), float(n.attrib["lat"])) for n in root.findall("node")}
    lines, sources = [], []
    for way in root.findall("way"):
        tags = {t.attrib["k"]: t.attrib["v"] for t in way.findall("tag")}
        if tags.get("natural") != "coastline":
            continue
        try:
            coords = [nodes[n.attrib["ref"]] for n in way.findall("nd")]
        except KeyError as e:
            raise DataError("Coastline way missing a node") from e
        if len(coords) < 2:
            raise DataError("Coastline way has fewer than two nodes")
        lines.append(LineString(coords))
        sources.append({k: way.attrib.get(k) for k in ("id", "version", "timestamp")})
    sea, report = sea_from_lines(lines, bounds)
    report["ways"] = sources
    report["osm_base"] = root.find("meta").attrib.get("osm_base") if root.find("meta") is not None else None
    return sea, report


def load_coast(assets, job_bounds):
    """Reprove the derived geometry from the hashed raw source on every build."""
    from .vectors import read_features

    if not assets.get("coastline"):
        return None, None
    if len(assets["coastline"]) != 1 or len(assets.get("coastline_source", [])) != 1:
        raise DataError("Coast requires one derived polygon asset and one frozen raw extract")
    path, record = assets["coastline"][0]
    raw_path, raw_record = assets["coastline_source"][0]
    bounds = record.get("coverage_bounds", [])
    if (
        len(bounds) != 4
        or not box(*bounds).covers(box(*job_bounds))
        or record.get("coverage_kind") != "directed_coast_partition"
        or record.get("raw_sha256") != raw_record["sha256"]
        or record.get("horizontal_crs") != "EPSG:3006"
    ):
        raise DataError("Coast coverage/source contract is incomplete")
    if raw_path.stat().st_size > 16_000_000:
        raise DataError("Coastline response exceeds byte budget")
    sea, report = parse_coast(raw_path.read_bytes(), bounds)
    features = read_features(path, record["horizontal_crs"])
    if any(f["geometry"].geom_type not in ("Polygon", "MultiPolygon") for f in features):
        raise DataError("Coast sea asset must contain polygons")
    stored = unary_union([f["geometry"] for f in features])
    if stored.symmetric_difference(sea).area > 1e-6:
        raise DataError("Sea polygon differs from its frozen coastline")
    return sea, report


def shoreline_height_check(sea, bounds, terrain, level=0.0, spacing=5.0):
    """Quantify the terrain/sea seam without warping terrain to fit an assumed sea.

    Ignore the acquisition rectangle: it is a clipping edge, not a shoreline.
    Residuals against a modeled sea are diagnostics, never measured accuracy.
    """
    import numpy as np

    shoreline = sea.boundary.intersection(box(*bounds).buffer(-0.01))
    parts = list(shoreline.geoms) if hasattr(shoreline, "geoms") else [shoreline]
    samples = [
        part.interpolate(float(d))
        for part in parts
        if part.length
        for d in np.linspace(0, part.length, max(2, int(np.ceil(part.length / spacing)) + 1))
    ]
    z = terrain.sample([p.x for p in samples], [p.y for p in samples]) if samples else np.array([])
    finite = z[np.isfinite(z)] - level
    return {
        "sample_count": len(samples),
        "valid_samples": len(finite),
        "sampling_m": spacing,
        "sea_level_evidence": "modeled",
        "residual_p05_m": float(np.percentile(finite, 5)) if len(finite) else None,
        "residual_median_m": float(np.median(finite)) if len(finite) else None,
        "residual_p95_m": float(np.percentile(finite, 95)) if len(finite) else None,
        "max_abs_residual_m": float(np.max(np.abs(finite))) if len(finite) else None,
        "note": "Includes piers/quays. Difference from modeled sea, not surveyed vertical error.",
    }


def fetch_coast(c, output):
    """One small public read; atomic output and retained raw source receipt."""
    output = Path(output).resolve()
    if output.exists():
        raise DataError("Coast output exists; choose a fresh directory")
    w, s, e, n = c["bounds"]
    h = c["halo_m"]
    bounds = [w - h, s - h, e + h, n + h]
    west, south, east, north = geographic_bounds(c, h + 100)
    if (east - west) * (north - south) > 0.005:
        raise DataError("Coast API acquisition is limited to the pilot")
    query = (
        "[out:xml][timeout:60][maxsize:16000000];"
        f"way[natural=coastline]({south},{west},{north},{east});(._;>;);out meta;"
    )
    url = "https://overpass-api.de/api/interpreter"
    with session() as client:
        with client.get(url, params={"data": query}, timeout=(15, 90), stream=True) as response:
            response.raise_for_status()
            chunks, size = [], 0
            for chunk in response.iter_content(65536):
                size += len(chunk)
                if size > 16_000_000:
                    raise DataError("Coastline response exceeds byte budget")
                chunks.append(chunk)
            raw = b"".join(chunks)
    sea, report = parse_coast(raw, bounds)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".coast-", dir=output.parent) as tmp:
        stage = Path(tmp) / "coast"
        stage.mkdir()
        source = stage / "coastline.osm"
        source.write_bytes(raw)
        common = dict(use_status="open", redistribution_status="ODbL", evidence="derived")
        raw_record = receipt(
            source,
            url,
            "ODbL-1.0",
            "https://www.openstreetmap.org/copyright",
            horizontal_crs="EPSG:4326",
            query=query,
            **common,
        )
        path = stage / "sea.geojson"
        write_json(
            path,
            {
                "type": "FeatureCollection",
                "crs": {"type": "name", "properties": {"name": "EPSG:3006"}},
                "features": [
                    {
                        "type": "Feature",
                        "id": "osm-sea",
                        "geometry": mapping(sea),
                        "properties": {"water": "sea", "boundary_evidence": "derived"},
                    }
                ],
            },
        )
        record = receipt(
            path,
            url,
            "ODbL-1.0",
            "https://www.openstreetmap.org/copyright",
            horizontal_crs="EPSG:3006",
            coverage_bounds=bounds,
            coverage_kind="directed_coast_partition",
            topology=report,
            raw_sha256=raw_record["sha256"],
            note="OSM fallback shoreline, not surveyed accuracy or an observed sea level.",
            **common,
        )
        records = {"coastline": [record], "coastline_source": [raw_record]}
        write_json(stage / "assets.json", records)
        os.replace(stage, output)
    return records
