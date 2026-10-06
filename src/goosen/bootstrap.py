"""An explicit engineering preview using inspected legacy data, not an acceptance shortcut."""

from pathlib import Path

from .acquire import fetch_sjv, receipt
from .core import write_json
from .migration import make_transfer_plan, transfer
from .osm import fetch_osm


def bootstrap(c, repo, output, osm=False):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    plan = output / "transfer-plan.json"
    make_transfer_plan(repo, c, plan)
    files = transfer(repo, plan, output / "nbs", include_preview=True)
    assets = {"terrain": [], "landcover": []}
    for f in files:
        if f["role"] == "upstream_reference":
            continue
        p = output / "nbs" / f["local_path"]
        terrain = f["role"] == "elevation"
        record = receipt(
            p,
            "USGS/SRTMGL1_003 via pinned NBS commit"
            if terrain
            else "Naturvårdsverket NMD2023 v2.1 via pinned NBS commit",
            "NASA/USGS public data" if terrain else "CC0-1.0",
            "https://developers.google.com/earth-engine/datasets/catalog/USGS_SRTMGL1_003"
            if terrain
            else "https://geodata.naturvardsverket.se/nedladdning/marktacke/NMD2023/Basskikt_v2_x/NMD2023_Produktbeskrivning_Basskikt_NMD2023_v2_x.pdf",
            evidence="derived",
            use_status="open",
            redistribution_status="open",
            horizontal_crs="EPSG:4326",
            vertical_crs="EPSG:5773" if terrain else None,
            native_resolution_m=30 if terrain else 10,
            surface_kind="DSM" if terrain else "classification",
            observation_year=2000 if terrain else 2023,
        )
        record["path"] = p.relative_to(output).as_posix()
        assets["terrain" if terrain else "landcover"].append(record)
    # Cataloguing public SJV geometry is permitted by its published open-data policy;
    # metadata does not specify a CC variant, so public redistribution stays on hold.
    record = fetch_sjv(c, output / f"fields-{c['crop_year']}.geojson")
    assets["fields"] = [record]
    if osm:
        for role, record in fetch_osm(c, output / "osm").items():
            record["path"] = "osm/" + record["path"]
            assets[role] = [record]
    catalog = {
        "schema": 1,
        "assets": assets,
        "crop_map": c.get("crop_map", {}),
        "purpose": "Engineering preview only; replace SRTM and verify crop codebook before acceptance",
    }
    write_json(output / "catalog.json", catalog)
    return catalog
