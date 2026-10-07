from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .core import DataError, load_config, read_json


def main(argv=None):
    p = argparse.ArgumentParser(prog="goosen", description="GÅSEN geodata → reproducible Blender tiles")
    sub = p.add_subparsers(dest="command", required=True)
    for name in [
        "inventory",
        "transfer-plan",
        "transfer",
        "discover",
        "fetch-sjv",
        "fetch-osm",
        "fetch-coast",
        "fetch-municipal",
        "fetch-lm",
        "bootstrap-preview",
        "prepare",
        "qa",
        "benchmark",
    ]:
        q = sub.add_parser(name)
        if name not in ("inventory", "transfer", "fetch-lm", "qa"):
            q.add_argument("--config", default="configs/pilot.json")
        if name in ("inventory", "transfer-plan", "transfer", "bootstrap-preview"):
            q.add_argument("--repo", required=True, type=Path)
        if name not in ("qa",):
            q.add_argument("--output", required=True, type=Path)
        if name == "inventory":
            q.add_argument("--commit", default="8263aa2f583170fc3a6a6bf6f3f174a7c8ac4322")
        if name == "transfer":
            q.add_argument("--plan", required=True, type=Path)
            q.add_argument("--include-preview", action="store_true")
        if name == "fetch-sjv":
            q.add_argument("--kind", choices=["block", "skifte"], default="skifte")
        if name == "fetch-municipal":
            q.add_argument("--permission", required=True, type=Path)
            q.add_argument(
                "--layer",
                choices=["buildings", "buildings3d", "road-lines", "water-lines", "rail-lines"],
                default="buildings",
            )
        if name == "fetch-lm":
            q.add_argument("--asset", required=True, type=Path)
            q.add_argument("--permission", required=True, type=Path)
        if name == "bootstrap-preview":
            q.add_argument("--osm", action="store_true")
        if name in ("prepare", "benchmark"):
            q.add_argument("--catalog", required=True, type=Path)
            q.add_argument("--preview", action="store_true")
        if name == "qa":
            q.add_argument("--world", required=True, type=Path)
    a = p.parse_args(argv)
    try:
        c = load_config(a.config) if hasattr(a, "config") else None
        if a.command == "inventory":
            from .inventory import audit_repo

            r = audit_repo(a.repo, a.output, a.commit)
            print(json.dumps({k: r[k] for k in ["file_count", "raster_files", "errors"]}))
        elif a.command == "transfer-plan":
            from .migration import make_transfer_plan

            r = make_transfer_plan(a.repo, c, a.output)
            print(f"Locked {len(r['files'])} candidate files")
        elif a.command == "transfer":
            from .migration import transfer

            print(f"Transferred {len(transfer(a.repo, a.plan, a.output, a.include_preview))} verified files")
        elif a.command == "discover":
            from .acquire import discover

            r = discover(c, a.output)
            print(f"Discovered {len(r.get('lm_items', []))} LM items; metadata only")
        elif a.command == "fetch-sjv":
            from .acquire import fetch_sjv

            print(json.dumps(fetch_sjv(c, a.output, a.kind)))
        elif a.command == "fetch-osm":
            from .osm import fetch_osm

            r = fetch_osm(c, a.output)
            print("Fetched OSM fallback: " + ", ".join(r))
        elif a.command == "fetch-coast":
            from .coast import fetch_coast

            r = fetch_coast(c, a.output)
            print(json.dumps(r["coastline"][0]["topology"], indent=2))
        elif a.command == "fetch-municipal":
            from .acquire import fetch_municipal

            print(json.dumps(fetch_municipal(c, a.output, a.permission, a.layer)))
        elif a.command == "fetch-lm":
            from .acquire import download_lm

            download_lm(read_json(a.asset), a.output, a.permission)
            print("Verified asset download complete")
        elif a.command == "bootstrap-preview":
            from .bootstrap import bootstrap

            bootstrap(c, a.repo, a.output, a.osm)
            print("Preview inputs staged; these do not meet geographic acceptance")
        elif a.command == "prepare":
            from .world import prepare

            r = prepare(c, a.catalog, a.output, a.preview)
            print(f"Built {len(r['tiles'])} tiles; gaps: {len(r['gaps'])}; acceptance_passed=false")
        elif a.command == "qa":
            from .qa import audit_world

            r = audit_world(a.world)
            print(json.dumps(r, indent=2))
            return 0 if r["structural_pass"] else 1
        elif a.command == "benchmark":
            from .qa import benchmark

            print(json.dumps(benchmark(c, a.catalog, a.output, a.preview), indent=2))
    except (DataError, FileNotFoundError) as e:
        print("GÅSEN: " + str(e), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
