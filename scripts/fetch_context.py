"""Acquire a bounded OSM surface/hedge supplement, with frozen provenance."""

import argparse
import json
from pathlib import Path
from shapely.geometry import Polygon, LineString, mapping
from goosen.core import load_config, geographic_bounds, sha256, write_json, DataError
from goosen.acquire import session, receipt

p = argparse.ArgumentParser()
p.add_argument("--config", required=True)
p.add_argument("--catalog", required=True)
p.add_argument("--output", required=True)
p.add_argument("--reuse-response", action="store_true")
a = p.parse_args()
c = load_config(a.config)
w, s, e, n = geographic_bounds(c, 30)
bbox = f"({s},{w},{n},{e})"
query = (
    "[out:json][timeout:40][maxsize:33554432];("
    + "".join(
        "way" + f + bbox + ";"
        for f in [
            "[amenity=parking]",
            '[leisure~"^(pitch|park)$"]',
            "[landuse=grass]",
            '[natural~"^(beach|scrub)$"]',
            "[barrier=hedge]",
            '[man_made~"^(pier|breakwater)$"]',
        ]
    )
    + ");out geom;"
)
out = Path(a.output).resolve()
cat = Path(a.catalog).resolve()
if out.exists() or out.parent != cat.parent:
    raise DataError("Use a new sibling catalog")
folder = out.parent / "context"
folder.mkdir(exist_ok=True)
raw = folder / "response.json"
if a.reuse_response:
    data = json.loads(raw.read_text())
else:
    if raw.exists():
        raise DataError("Existing response; use --reuse-response to resume")
    response = session().post("https://overpass-api.de/api/interpreter", data={"data": query}, timeout=55)
    response.raise_for_status()
    if len(response.content) > 10000000:
        raise DataError("Context response budget exceeded")
    data = response.json()
    raw.write_bytes(response.content)
if data.get("remark") or len(data.get("elements", [])) > 5000:
    raise DataError("Incomplete or oversized Overpass response")
features = []
skipped = []
for obj in data["elements"]:
    coords = [(v["lon"], v["lat"]) for v in obj.get("geometry", [])]
    tags = obj.get("tags", {})
    if len(coords) < 2:
        skipped.append(obj["id"])
        continue
    closed = coords[0] == coords[-1] and len(coords) >= 4
    if tags.get("barrier") == "hedge":
        geom = LineString(coords)
    elif closed:
        geom = Polygon(coords)
    else:
        skipped.append(obj["id"])
        continue
    if not geom.is_valid:
        skipped.append(obj["id"])
        continue
    props = {
        k: v
        for k, v in tags.items()
        if k in ["amenity", "leisure", "landuse", "natural", "surface", "barrier", "man_made", "sport"]
    }
    features.append(
        {"type": "Feature", "id": "way/" + str(obj["id"]), "geometry": mapping(geom), "properties": props}
    )
path = folder / "features.geojson"
write_json(path, {"type": "FeatureCollection", "features": features})
asset = {
    "path": "context/features.geojson",
    "sha256": sha256(path),
    "source": "https://overpass-api.de/api/interpreter",
    "license": "ODbL-1.0",
    "license_evidence": "https://www.openstreetmap.org/copyright",
    "use_status": "open",
    "redistribution_status": "ODbL",
    "horizontal_crs": "EPSG:4326",
    "evidence": "derived",
    "query": query,
    "osm_base": data.get("osm3s", {}).get("timestamp_osm_base"),
    "feature_count": len(features),
    "note": "Optional OSM fallback surfaces. Open non-hedge ways skipped, not guessed closed.",
    "skipped": skipped,
}
receipt(raw, asset["source"], asset["license"], asset["license_evidence"], evidence="derived", query=query)
write_json(str(path) + ".source.json", asset)
catalog = json.loads(cat.read_text())
catalog["assets"]["context"] = [asset]
write_json(out, catalog)
print(json.dumps({"features": len(features), "skipped": len(skipped), "catalog": str(out)}))
