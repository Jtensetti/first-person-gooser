"""Create a verified local handoff bundle. Does not upload or change permissions."""

import argparse
import json
import os
import zipfile
from pathlib import Path

from goosen.core import DataError, read_json, sha256, validate_asset, write_json


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--catalog", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    root = a.catalog.parent.resolve()
    files = {a.catalog.resolve()}
    catalog = read_json(a.catalog)
    statuses = set()
    for role, records in catalog["assets"].items():
        for record in records:
            source = validate_asset(record, root, role)
            if not source.is_relative_to(root):
                raise DataError("Bundle requires catalog-relative files within the catalog directory")
            files.add(source)
            sidecar = Path(str(source) + ".source.json")
            if sidecar.exists():
                files.add(sidecar)
            statuses.add(record.get("redistribution_status", "review"))
    # Include source migration references when bootstrap staged them.
    for rel in ("transfer-plan.json", "nbs/transfer-receipt.json"):
        if (root / rel).exists():
            files.add(root / rel)
    if (root / "nbs/upstream").exists():
        files.update(p for p in (root / "nbs/upstream").rglob("*") if p.is_file())
    if a.output.exists():
        raise DataError("Output exists; choose a fresh bundle name")
    a.output.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema": 1,
        "files": [
            {"path": f.relative_to(root).as_posix(), "sha256": sha256(f), "bytes": f.stat().st_size}
            for f in sorted(files)
        ],
        "redistribution_statuses": sorted(statuses),
        "notice": "Local handoff only. This bundle is not cleared for public redistribution; review each source and keep licensed data in approved storage.",
    }
    tmp = a.output.with_suffix(".part")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(files):
            z.write(f, f.relative_to(root).as_posix())
        z.writestr("handoff-manifest.json", json.dumps(manifest, indent=2))
    with zipfile.ZipFile(tmp) as z:
        if z.testzip():
            raise DataError("Bundle integrity check failed")
    os.replace(tmp, a.output)
    write_json(str(a.output) + ".sha256.json", {"sha256": sha256(a.output), "bytes": a.output.stat().st_size})
    print(f"Verified {len(files)} files in {a.output}; no upload performed")


if __name__ == "__main__":
    main()
