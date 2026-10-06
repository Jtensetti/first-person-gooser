from __future__ import annotations

import json
import shutil
import subprocess
import csv
from pathlib import Path

from .core import DataError, geographic_bounds, sha256, write_json

NBS_COMMIT = "8263aa2f583170fc3a6a6bf6f3f174a7c8ac4322"


def intersects(a, b):
    return a[0] < b[2] and a[2] > b[0] and a[1] < b[3] and a[3] > b[1]


def make_transfer_plan(repo, c, output):
    repo = Path(repo)
    if (repo / ".git").exists():
        head = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
        ).stdout.strip()
        if head != NBS_COMMIT:
            raise DataError(
                "Source checkout differs from the inventoried commit; check out the pinned commit"
            )
    audit_file = Path(__file__).resolve().parents[2] / "docs/evidence/inventory/repository-files.csv"
    expected = {}
    if audit_file.exists():
        with audit_file.open() as stream:
            expected = {r["path"]: r["sha256"] for r in csv.DictReader(stream)}

    def locked(rel):
        p = repo / rel
        digest = sha256(p)
        if not expected or expected.get(rel) != digest:
            raise DataError("Source file not verified against the pinned inventory: " + rel)
        return {"path": rel, "sha256": digest, "bytes": p.stat().st_size}

    bbox = geographic_bounds(c, c["halo_m"])
    entries = []
    decisions = {
        "nmd2023_landcover": "admit",
        "elevation": "preview_only",
        "canopy_height": "review",
        "pca_3band": "quarantine",
        "ndvi": "quarantine",
        "biomass": "review",
        "water_freq": "review",
        "hand": "exclude",
        "lst": "exclude",
        "soc": "exclude",
        "nightlights": "exclude",
        "population": "exclude",
        "precipitation": "quarantine",
        "builtup": "exclude",
        "landcover": "exclude",
        "slope": "exclude",
        "municipal_slope": "exclude",
    }
    for index in sorted((repo / "public/data").glob("*_index.json")):
        prefix = index.name.removesuffix("_index.json")
        for e in json.loads(index.read_text()):
            if intersects(e["bbox"], bbox):
                p = index.parent / e["name"]
                entries.append(
                    {
                        **locked(p.relative_to(repo).as_posix()),
                        "role": prefix,
                        "decision": decisions.get(prefix, "review"),
                        "bbox": e["bbox"],
                    }
                )
    plan = {
        "schema": 1,
        "source_repo": "Jtensetti/nbs-sandbox-trelleborg",
        "source_commit": NBS_COMMIT,
        "aoi_wgs84": bbox,
        "files": entries,
        "code_reuse": [
            "scripts/prepare-municipal-rasters.py",
            "scripts/prepare-municipal-boundary.py",
            "bake/bake_ee.py",
        ],
        "boundary": "src/lib/geo/municipality-boundary.json",
        "support_files": [
            locked(rel)
            for rel in [
                "src/lib/geo/municipality-boundary.json",
                "public/data/municipal_sources.json",
                "scripts/prepare-municipal-rasters.py",
                "scripts/prepare-municipal-boundary.py",
                "bake/bake_ee.py",
                "bake/README.md",
                "bake/requirements.txt",
            ]
        ],
        "note": "Do not copy .env, cloud settings or the unrelated web app. Bulk raw data stays outside git.",
    }
    write_json(output, plan)
    return plan


def transfer(repo, plan_path, dest, include_preview=False):
    repo, dest = Path(repo), Path(dest)
    plan = json.loads(Path(plan_path).read_text())
    dest.mkdir(parents=True, exist_ok=True)
    copied = []
    for e in plan["files"]:
        if e["decision"] != "admit" and not (include_preview and e["decision"] == "preview_only"):
            continue
        source = (repo / e["path"]).resolve()
        if not source.is_relative_to(repo.resolve()) or sha256(source) != e["sha256"]:
            raise DataError(f"Transfer input differs from lock: {e['path']}")
        out = dest / Path(e["path"]).name
        shutil.copyfile(source, out)
        if sha256(out) != e["sha256"]:
            raise DataError("Transfer checksum mismatch")
        copied.append({**e, "local_path": out.name})
    for item in plan["support_files"]:
        rel = item["path"]
        source = (repo / rel).resolve()
        if not source.is_relative_to(repo.resolve()) or sha256(source) != item["sha256"]:
            raise DataError("Support file differs from source lock: " + rel)
        out = dest / "upstream" / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, out)
        copied.append({**item, "role": "upstream_reference", "local_path": out.relative_to(dest).as_posix()})
    write_json(dest / "transfer-receipt.json", {"source_commit": plan["source_commit"], "files": copied})
    return copied
