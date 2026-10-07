"""Portable local data bundles: explicit allowlist, checksums, atomic restore."""

import hashlib
import json
import os
import re
import shutil
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from .core import DataError, read_json, sha256, validate_asset, write_json


def safe_relative(value):
    p = PurePosixPath(value)
    if (
        not value
        or p.is_absolute()
        or ".." in p.parts
        or "\\" in value
        or ":" in value
        or p.as_posix() != value
        or any(x.endswith((".", " ")) for x in p.parts)
        or any(re.fullmatch(r"(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?", x) for x in p.parts)
    ):
        raise DataError("Unsafe bundle path: " + value)
    return p


def bundle(catalog_path, output):
    catalog_path, output = Path(catalog_path).resolve(), Path(output).resolve()
    root = catalog_path.parent
    if output.exists():
        raise DataError("Output exists; choose a fresh bundle name")
    files = {catalog_path}
    statuses = set()
    for role, records in read_json(catalog_path)["assets"].items():
        for record in records:
            files.add(validate_asset(record, root, role))
            sidecar = Path(str(root / record["path"]) + ".source.json")
            if sidecar.exists():
                files.add(sidecar.resolve())
            statuses.add(record.get("redistribution_status", "review"))
    for rel in ("transfer-plan.json", "nbs/transfer-receipt.json"):
        if (root / rel).exists():
            files.add(root / rel)
    receipt = root / "nbs/transfer-receipt.json"
    if receipt.exists():
        for item in read_json(receipt)["files"]:
            safe_relative(item["local_path"])
            path = (receipt.parent / item["local_path"]).resolve()
            if not path.is_relative_to(root) or sha256(path) != item["sha256"]:
                raise DataError("Changed upstream transfer file")
            files.add(path)
    entries = []
    for path in sorted(files):
        if not path.is_relative_to(root):
            raise DataError("Bundle file outside catalog directory")
        rel = path.relative_to(root).as_posix()
        safe_relative(rel)
        if rel == "handoff-manifest.json":
            raise DataError("Reserved bundle filename")
        entries.append({"path": rel, "sha256": sha256(path), "bytes": path.stat().st_size})
    manifest = {
        "schema": 1,
        "catalog": catalog_path.name,
        "files": entries,
        "redistribution_statuses": sorted(statuses),
        "notice": "Local handoff only; not approval for public redistribution.",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".handoff-", dir=output.parent) as tmp:
        packed = Path(tmp) / "bundle.zip"
        with zipfile.ZipFile(packed, "w", zipfile.ZIP_DEFLATED) as z:
            for item in entries:
                z.write(root / item["path"], item["path"])
            z.writestr("handoff-manifest.json", json.dumps(manifest, ensure_ascii=False))
        digest = sha256(packed)
        verify_bundle(packed, digest)
        os.replace(packed, output)
    write_json(str(output) + ".sha256.json", {"sha256": digest, "bytes": output.stat().st_size})
    return manifest


def verify_bundle(path, expected_sha256, max_bytes=20_000_000_000):
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256) or sha256(path) != expected_sha256:
        raise DataError("Bundle SHA-256 mismatch")
    with zipfile.ZipFile(path) as z:
        infos = z.infolist()
        names = [i.filename for i in infos]
        if len(names) > 100000 or len({n.casefold() for n in names}) != len(names):
            raise DataError("Duplicate or excessive bundle members")
        for info in infos:
            safe_relative(info.filename)
            if info.is_dir() or (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise DataError("Directory/symlink bundle members are forbidden")
        if sum(i.file_size for i in infos) > max_bytes:
            raise DataError("Bundle exceeds expanded-size budget")
        if "handoff-manifest.json" not in names or z.getinfo("handoff-manifest.json").file_size > 20_000_000:
            raise DataError("Missing or excessive handoff manifest")
        manifest = json.loads(z.read("handoff-manifest.json"))
        if manifest.get("schema") != 1:
            raise DataError("Unknown handoff schema")
        entries = manifest["files"]
        listed = [e["path"] for e in entries]
        if len(set(listed)) != len(listed) or set(names) != set(listed) | {"handoff-manifest.json"}:
            raise DataError("Manifest and archive members disagree")
        for item in entries:
            if z.getinfo(item["path"]).file_size != item["bytes"]:
                raise DataError("Bundle member size mismatch")
            with z.open(item["path"]) as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() != item["sha256"]:
                    raise DataError("Bundle member checksum mismatch")
        if manifest.get("catalog", "catalog.json") not in listed:
            raise DataError("Bundle catalog missing")
    return manifest


def restore_bundle(path, expected_sha256, output, max_bytes=20_000_000_000):
    output = Path(output).resolve()
    if output.exists():
        raise DataError("Restore output exists; refusing to overwrite")
    manifest = verify_bundle(path, expected_sha256, max_bytes)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".restore-", dir=output.parent) as tmp:
        stage = Path(tmp) / "data"
        stage.mkdir()
        with zipfile.ZipFile(path) as z:
            for item in manifest["files"]:
                target = stage / item["path"]
                target.parent.mkdir(parents=True, exist_ok=True)
                with z.open(item["path"]) as source, target.open("wb") as dest:
                    shutil.copyfileobj(source, dest, 1024 * 1024)
                if sha256(target) != item["sha256"]:
                    raise DataError("Restored checksum mismatch")
        catalog_path = stage / manifest.get("catalog", "catalog.json")
        for role, records in read_json(catalog_path)["assets"].items():
            for record in records:
                candidate = (catalog_path.parent / record["path"]).resolve()
                if not candidate.is_relative_to(stage):
                    raise DataError("Catalog asset escapes bundle")
                validate_asset(record, catalog_path.parent, role)
        write_json(stage / "handoff-manifest.json", manifest)
        os.replace(stage, output)
    return manifest
