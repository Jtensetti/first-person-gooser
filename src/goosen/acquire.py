"""Read-only, bounded geodata clients; explicit pagination and completeness checks."""

from __future__ import annotations

import json
import os
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .core import DataError, geographic_bounds, sha256, write_json

SJV = "https://epub.sjv.se/inspire/inspire/wfs"
MUNICIPAL = "https://geodata.trelleborg.se/arcgis/rest/services"
LM = "https://api.lantmateriet.se/stac-hojd/v1"


def session():
    s = requests.Session()
    s.headers["User-Agent"] = "Goosen-world/0.1 (bounded geodata preparation)"
    s.mount(
        "https://",
        HTTPAdapter(
            max_retries=Retry(
                total=3,
                backoff_factor=0.5,
                status_forcelist=[429, 502, 503, 504],
                allowed_methods=["GET", "HEAD"],
            )
        ),
    )
    return s


def get_json(s, url, params=None):
    response = s.get(url, params=params, timeout=(15, 90))
    response.raise_for_status()
    try:
        j = response.json()
    except ValueError as e:
        raise DataError(f"Non-JSON response from {urlparse(url).hostname}") from e
    if "error" in j:
        raise DataError(f"Service error: {j['error']}")
    return j


def receipt(path, source, license_name, evidence_url, evidence="measured", **extra):
    result = {
        "path": Path(path).name,
        "sha256": sha256(path),
        "source": source,
        "license": license_name,
        "license_evidence": evidence_url,
        "evidence": evidence,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        **extra,
    }
    write_json(str(path) + ".source.json", result)
    return result


def wfs_features(s, url, typename, cql, page_size=500, max_features=50000):
    base = {
        "service": "WFS",
        "version": "2.0.0",
        "request": "GetFeature",
        "typeNames": typename,
        "CQL_FILTER": cql,
        "srsName": "EPSG:3006",
        "outputFormat": "application/json",
    }
    hit = s.get(url, params={**base, "resultType": "hits"}, timeout=(15, 90))
    hit.raise_for_status()
    try:
        expected = int(ET.fromstring(hit.content).attrib["numberMatched"])
    except (ET.ParseError, KeyError, ValueError) as e:
        raise DataError("WFS did not provide a verifiable hit count") from e
    if expected > max_features:
        raise DataError("WFS request too large; reduce AOI")
    features = []
    seen = set()
    while len(features) < expected:
        page = get_json(
            s, url, {**base, "startIndex": len(features), "count": min(page_size, expected - len(features))}
        )
        if page.get("numberMatched") != expected:
            raise DataError("WFS count changed during download")
        batch = page.get("features", [])
        if not batch or page.get("numberReturned", len(batch)) != len(batch):
            raise DataError("WFS returned a truncated page")
        for f in batch:
            # GeoServer may not expose a stable feature id for database views.
            key = f.get("id") or json.dumps([f.get("properties"), f.get("geometry")], sort_keys=True)
            if key in seen:
                raise DataError("WFS repeated features; pagination is not complete")
            seen.add(key)
            features.append(f)
        if len(features) > expected:
            raise DataError("WFS returned more than the reported count")
    return {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": "EPSG:3006"}},
        "features": features,
        "numberMatched": expected,
        "numberReturned": len(features),
    }


def fetch_sjv(c, out, kind="skifte"):
    if kind not in ("skifte", "block"):
        raise DataError("Unknown SJV product")
    b = c["bounds"]
    h = c["halo_m"]
    cql = f"arslager={int(c['crop_year'])} AND BBOX(geom,{b[0] - h},{b[1] - h},{b[2] + h},{b[3] + h},'EPSG:3006')"
    with session() as s:
        data = wfs_features(s, SJV, f"inspire:arslager_{kind}", cql)
    if any(f["properties"].get("arslager") != c["crop_year"] for f in data["features"]):
        raise DataError("SJV returned a different crop year")
    write_json(out, data)
    return receipt(
        out,
        SJV,
        "SJV public WFS; Fees NONE / AccessConstraints NONE",
        SJV + "?service=WFS&request=GetCapabilities&version=2.0.0",
        evidence="derived",
        horizontal_crs="EPSG:3006",
        use_status="open",
        redistribution_status="review",
        observation_year=c["crop_year"],
        feature_count=len(data["features"]),
        query=cql,
        note="Public documented download service. Exact redistribution licence is unresolved; keep raw geometry out of public git.",
    )


def arcgis_features(
    s, layer, bounds, in_sr=3006, out_sr=3006, fields="OBJECTID", where="1=1", multipatch=False
):
    query = layer.rstrip("/") + "/query"
    data = get_json(
        s,
        query,
        {
            "f": "json",
            "where": where,
            "geometry": ",".join(map(str, bounds)),
            "geometryType": "esriGeometryEnvelope",
            "inSR": in_sr,
            "spatialRel": "esriSpatialRelIntersects",
            "returnIdsOnly": "true",
        },
    )
    if "objectIds" not in data:
        raise DataError("ArcGIS omitted objectIds")
    ids = data["objectIds"] or []
    if len(ids) != len(set(ids)) or len(ids) > 100000:
        raise DataError("Invalid ArcGIS ID enumeration")
    oid = data.get("objectIdFieldName", "OBJECTID")
    features = []
    geometry_type = None
    if oid not in fields.split(","):
        fields = oid + "," + fields
    for offset in range(0, len(ids), 150):
        batch = sorted(ids)[offset : offset + 150]
        page = get_json(
            s,
            query,
            {
                "f": "json",
                "objectIds": ",".join(map(str, batch)),
                "outFields": fields,
                "outSR": out_sr,
                "returnGeometry": "true",
                "returnZ": "true",
                "returnM": "false",
                **({"multipatchOption": "stripMaterials"} if multipatch else {}),
            },
        )
        found = [f["attributes"][oid] for f in page.get("features", [])]
        if page.get("exceededTransferLimit") or len(found) != len(batch) or set(found) != set(batch):
            raise DataError("Incomplete ArcGIS ID batch")
        geometry_type = page.get("geometryType")
        features.extend(page["features"])
    return {
        "geometryType": geometry_type,
        "spatialReference": {"wkid": out_sr},
        "features": features,
        "count": len(ids),
    }


def fetch_municipal(c, out, permission_path, layer_id="buildings"):
    permission = json.loads(Path(permission_path).read_text())
    if permission.get("use_status") != "authorized" or not permission.get("license_evidence"):
        raise DataError("Municipal reuse permission and evidence are required")
    products = {
        "buildings": (
            "tomtkarta/Tomtkarta/MapServer/31",
            "OBJECTID,STATUS",
            "STATUS NOT IN (1,4) OR STATUS IS NULL",
        ),
        "buildings3d": ("TreD/Byggnader_3D_250407/FeatureServer/0", "OBJECTID,LOD,B_PART", "1=1"),
        "road-lines": ("tomtkarta/Tomtkarta/MapServer/28", "OBJECTID", "1=1"),
        "water-lines": ("tomtkarta/Tomtkarta/MapServer/25", "OBJECTID", "1=1"),
        "rail-lines": ("tomtkarta/Tomtkarta/MapServer/29", "OBJECTID", "1=1"),
    }
    path, fields, where = products[layer_id]
    url = MUNICIPAL + "/" + path
    if url not in permission.get("allowed_sources", []):
        raise DataError("Permission does not cover this source")
    b = c["bounds"]
    h = c["halo_m"]
    bounds = [b[0] - h, b[1] - h, b[2] + h, b[3] + h]
    with session() as s:
        data = arcgis_features(
            s, url, bounds, fields=fields, where=where, multipatch=layer_id == "buildings3d"
        )
    write_json(out, data)
    return receipt(
        out,
        url,
        permission["license"],
        permission["license_evidence"],
        evidence="derived",
        horizontal_crs="EPSG:3006",
        vertical_crs=permission.get("vertical_crs"),
        use_status="authorized",
        redistribution_status=permission.get("redistribution_status", "review"),
    )


def stac_search(s, c, collections=None, limit=100):
    params = {"bbox": ",".join(map(str, geographic_bounds(c, c["halo_m"]))), "limit": limit}
    if collections:
        params["collections"] = ",".join(collections)
    url = LM + "/search"
    result = []
    seen = set()
    for _ in range(30):
        data = get_json(s, url, params)
        for f in data.get("features", []):
            key = (f.get("collection"), f["id"])
            if key in seen:
                raise DataError("STAC repeated an item")
            seen.add(key)
            result.append(f)
        links = [v for v in data.get("links", []) if v["rel"] == "next"]
        if not links:
            return {"type": "FeatureCollection", "features": result}
        link = links[0]
        if link.get("method", "GET") != "GET" or urlparse(link["href"]).hostname != "api.lantmateriet.se":
            raise DataError("Unsupported STAC pagination")
        url, params = link["href"], None
    raise DataError("STAC pagination limit reached")


def discover(c, out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    report = {"date": datetime.now(timezone.utc).isoformat(), "services": []}
    with session() as s:
        try:
            data = stac_search(s, c)
            write_json(out / "lm-stac-items.json", data)
            report["lm_items"] = [
                {
                    "id": f["id"],
                    "collection": f.get("collection"),
                    "date": f["properties"].get("datetime"),
                    "assets": {
                        k: {p: v.get(p) for p in ("href", "type", "file:size", "file:checksum")}
                        for k, v in f.get("assets", {}).items()
                    },
                }
                for f in data["features"]
            ]
        except (requests.RequestException, DataError) as e:
            report["lm_error"] = str(e)
        # Only public catalogue metadata; never probe sign-in or edit operations.
        for path in ["", "TreD", "tomtkarta/Tomtkarta/MapServer", "Ortofoto", "Stadsmiljo"]:
            try:
                j = get_json(s, MUNICIPAL + ("/" + path if path else ""), {"f": "json"})
                report["services"].append(
                    {
                        "path": path,
                        "status": "metadata_available",
                        "services": j.get("services", []),
                        "layers": j.get("layers", []),
                        "copyright": j.get("copyrightText", ""),
                    }
                )
            except (requests.RequestException, DataError) as e:
                report["services"].append({"path": path, "status": "blocked", "reason": str(e)})
    write_json(out / "discovery.json", report)
    return report


def download_lm(asset, out, permission_path):
    permission = json.loads(Path(permission_path).read_text())
    if permission.get("use_status") != "authorized" or not permission.get("license_evidence"):
        raise DataError("Accept the product terms in Geotorget and record permission first")
    url = asset["href"]
    if urlparse(url).scheme != "https" or urlparse(url).hostname != "dl1.lantmateriet.se":
        raise DataError("Unapproved Lantmäteriet asset host")
    if not os.environ.get("LM_USER") or not os.environ.get("LM_PASSWORD"):
        raise DataError("LM_USER and LM_PASSWORD are required; keep them out of git")
    if url not in permission.get("allowed_sources", []):
        raise DataError("Permission record does not cover this exact LM asset URL")
    expected = asset.get("file:checksum", "")
    expected = expected[4:] if expected.startswith("1220") else None
    size = asset.get("file:size")
    if Path(out).exists() and expected and sha256(out) == expected:
        return
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(str(out) + ".part")
    with session() as s:
        # Scope credentials to this single approved request. No credential-bearing URLs.
        with s.get(
            url,
            auth=(os.environ["LM_USER"], os.environ["LM_PASSWORD"]),
            stream=True,
            allow_redirects=False,
            timeout=(15, 120),
        ) as r:
            if 300 <= r.status_code < 400:
                raise DataError("Unexpected asset redirect; inspect before using credentials")
            r.raise_for_status()
            with tmp.open("wb") as f:
                for chunk in r.iter_content(1024 * 1024):
                    f.write(chunk)
    if size and tmp.stat().st_size != size:
        raise DataError("Asset size mismatch")
    if expected and sha256(tmp) != expected:
        raise DataError("Asset checksum mismatch")
    tmp.replace(out)
    return receipt(
        out,
        url,
        permission["license"],
        permission["license_evidence"],
        evidence="derived",
        use_status="authorized",
        vertical_crs="EPSG:5613",
        horizontal_crs="EPSG:3006",
        redistribution_status=permission.get("redistribution_status", "review"),
        observation_start=asset.get("observation_start"),
        observation_end=asset.get("observation_end"),
    )
