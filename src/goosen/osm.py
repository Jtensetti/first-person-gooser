"""Optional fallback from one bounded OSM API extract, never a replacement by default."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
import requests

from shapely.geometry import Polygon, LineString, mapping
from shapely.ops import polygonize_full, unary_union

from .acquire import receipt, session
from .core import DataError, geographic_bounds, write_json


def metres(value):
    if value is None:
        return None
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(?:m)?\s*", str(value))
    return float(match[1]) if match and 0 < float(match[1]) < 500 else None


def parse_osm(raw):
    root = ET.fromstring(raw)
    if root.tag != "osm" or root.find("error") is not None or root.find("remark") is not None:
        raise DataError("OSM error response")
    nodes = {n.attrib["id"]: (float(n.attrib["lon"]), float(n.attrib["lat"])) for n in root.findall("node")}
    ways = {}
    tags = {}
    result = {k: [] for k in ("buildings", "roads", "water")}
    used = set()

    def properties(t):
        p = {
            k: t[k]
            for k in ("highway", "surface", "bridge", "tunnel", "building", "natural", "water")
            if k in t
        }
        p["height_m"] = metres(t.get("height"))
        p["width_m"] = metres(t.get("width"))
        p["dimensions_evidence"] = "derived"
        p["source"] = "OpenStreetMap"
        return p

    def add(fid, geom, t):
        if geom.is_empty or not geom.is_valid:
            raise DataError(f"Invalid OSM geometry: {fid}")
        role = (
            "buildings"
            if t.get("building") not in (None, "no")
            else "water"
            if t.get("natural") == "water"
            else "roads"
            if t.get("highway")
            else None
        )
        if role:
            result[role].append(
                {"type": "Feature", "id": fid, "geometry": mapping(geom), "properties": properties(t)}
            )

    for w in root.findall("way"):
        wid = w.attrib["id"]
        refs = [n.attrib["ref"] for n in w.findall("nd")]
        try:
            ways[wid] = [nodes[r] for r in refs]
        except KeyError as e:
            raise DataError("OSM way missing a node") from e
        tags[wid] = {t.attrib["k"]: t.attrib["v"] for t in w.findall("tag")}
    for relation in root.findall("relation"):
        t = {a.attrib["k"]: a.attrib["v"] for a in relation.findall("tag")}
        if t.get("type") != "multipolygon" or not (t.get("building") or t.get("natural") == "water"):
            continue
        outer = []
        inner = []
        members = [m for m in relation.findall("member") if m.attrib.get("type") == "way"]
        for m in members:
            wid = m.attrib["ref"]
            if wid not in ways:
                raise DataError("OSM relation extends beyond this extract; supply a complete extract")
            (inner if m.attrib.get("role") == "inner" else outer).append(LineString(ways[wid]))
            used.add(wid)

        def assemble(lines):
            if not lines:
                return Polygon()
            areas, cuts, dangles, invalid = polygonize_full(lines)
            if any(not g.is_empty for g in (cuts, dangles, invalid)):
                raise DataError("Incomplete OSM multipolygon rings")
            return unary_union(list(areas.geoms))

        shell = assemble(outer)
        holes = assemble(inner)
        if shell.is_empty:
            raise DataError("OSM outer relation could not be assembled")
        add("relation/" + relation.attrib["id"], shell.difference(holes), t)
    for wid, coords in ways.items():
        if wid in used or len(coords) < 2:
            continue
        t = tags[wid]
        if t.get("building") not in (None, "no") or t.get("natural") == "water":
            if len(coords) < 4 or coords[0] != coords[-1]:
                raise DataError("Unclosed OSM polygon")
            geom = Polygon(coords)
        else:
            geom = LineString(coords)
        add("way/" + wid, geom, t)
    return {k: {"type": "FeatureCollection", "features": v} for k, v in result.items()}


def complete_relations(raw, fetch):
    """Fetch missing members only for relevant multipolygons, with strict bounds."""
    root = ET.fromstring(raw)
    existing = {(e.tag, e.attrib.get("id")): e for e in root if "id" in e.attrib}
    pending = []
    for relation in root.findall("relation"):
        tags = {t.attrib["k"]: t.attrib["v"] for t in relation.findall("tag")}
        if tags.get("type") != "multipolygon" or not (
            tags.get("building") not in (None, "no") or tags.get("natural") == "water"
        ):
            continue
        if any(m.attrib["type"] != "way" for m in relation.findall("member")):
            raise DataError("Nested OSM polygon relation needs an offline complete extract")
        if any(("way", m.attrib["ref"]) not in existing for m in relation.findall("member")):
            pending.append(relation.attrib["id"])
    if len(pending) > 10:
        raise DataError("Too many incomplete OSM relations; use an offline PBF extract")
    for rid in pending:
        extra = fetch(rid)
        if len(extra) > 10_000_000:
            raise DataError("OSM relation response exceeds pilot budget")
        for element in ET.fromstring(extra):
            if "id" not in element.attrib:
                continue
            key = (element.tag, element.attrib["id"])
            if key in existing:
                if existing[key].attrib.get("version") != element.attrib.get("version"):
                    raise DataError("OSM changed during acquisition; fetch a fresh consistent extract")
                continue
            root.append(element)
            existing[key] = element
        if len(existing) > 200_000:
            raise DataError("OSM object budget exceeded")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def overpass_extract(s, bbox):
    """Bounded read-only fallback with complete way/relation member recursion."""
    w, south, e, n = bbox
    region = f"({south},{w},{n},{e})"
    query = (
        "[out:xml][timeout:60][maxsize:32000000];("
        f"way[building]{region};relation[building][type=multipolygon]{region};"
        f"way[highway]{region};way[natural=water]{region};"
        f"relation[natural=water][type=multipolygon]{region};);(._;>>;);out meta;"
    )
    url = "https://overpass-api.de/api/interpreter"
    response = s.get(url, params={"data": query}, timeout=(15, 90))
    response.raise_for_status()
    if len(response.content) > 32_000_000:
        raise DataError("OSM extract exceeds byte budget")
    root = ET.fromstring(response.content)
    if root.tag != "osm" or root.find("remark") is not None or root.find("error") is not None:
        raise DataError("Overpass returned an incomplete or erroneous extract")
    return response.content, url


def fetch_osm(c, out):
    from pathlib import Path

    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    bbox = geographic_bounds(c, c["halo_m"])
    if (bbox[2] - bbox[0]) * (bbox[3] - bbox[1]) > 0.005:
        raise DataError("OSM API only used for the small pilot; use PBF extract for scaling")
    url = "https://api.openstreetmap.org/api/0.6/map"
    with session() as s:
        try:
            r = s.get(url, params={"bbox": ",".join(map(str, bbox))}, timeout=(15, 90))
            r.raise_for_status()
            raw = r.content
        except requests.RequestException:
            raw, url = overpass_extract(s, bbox)
        if len(raw) > 32_000_000:
            raise DataError("OSM extract exceeds byte budget")

        def fetch_relation(rid):
            r = s.get("https://api.openstreetmap.org/api/0.6/relation/" + rid + "/full", timeout=(15, 90))
            r.raise_for_status()
            return r.content

        raw = complete_relations(raw, fetch_relation)
    (out / "extract.osm").write_bytes(raw)
    converted = parse_osm(raw)
    records = {}
    for role, data in converted.items():
        p = out / (role + ".geojson")
        write_json(p, data)
        records[role] = receipt(
            p,
            url,
            "ODbL-1.0",
            "https://www.openstreetmap.org/copyright",
            evidence="derived",
            use_status="open",
            redistribution_status="ODbL",
            horizontal_crs="EPSG:4326",
            note="Fallback inventory, completeness is not established. Coastlines are not auto-filled as water.",
        )
    return records
