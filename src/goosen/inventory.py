"""Audit actual committed bytes, including ZIP payloads misnamed as .tif."""

from __future__ import annotations

import csv
import json
import zipfile
from collections import Counter, defaultdict
from contextlib import contextmanager
from pathlib import Path

import numpy as np
import rasterio
from rasterio.io import MemoryFile
from pyproj import Geod

from .core import DataError, sha256, write_json


@contextmanager
def open_raster(path, band_index=0):
    path = Path(path)
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            names = sorted(n for n in z.namelist() if n.lower().endswith((".tif", ".tiff")))
            if not names or band_index >= len(names):
                raise DataError(f"Missing TIFF member: {path}")
            with MemoryFile(z.read(names[band_index])) as mem, mem.open() as ds:
                yield ds
    else:
        with rasterio.open(path) as ds:
            yield ds


def audit_repo(repo, output, commit):
    repo, output = Path(repo), Path(output)
    output.mkdir(parents=True, exist_ok=True)
    files = []
    # Tracked-file snapshot is preferred; never recurse through node_modules or .git.
    import subprocess

    p = subprocess.run(["git", "-C", str(repo), "ls-files", "-z"], capture_output=True)
    paths = (
        [repo / x for x in p.stdout.decode().split("\0") if x]
        if p.returncode == 0
        else [
            p
            for p in repo.rglob("*")
            if p.is_file() and not any(v in p.parts for v in (".git", "node_modules", ".venv"))
        ]
    )
    for path in sorted(paths):
        files.append(
            {"path": path.relative_to(repo).as_posix(), "bytes": path.stat().st_size, "sha256": sha256(path)}
        )
    with (output / "repository-files.csv").open("w", newline="", encoding="utf8") as f:
        writer = csv.DictWriter(f, fieldnames=["path", "bytes", "sha256"], lineterminator="\n")
        writer.writeheader()
        writer.writerows(files)
    groups = defaultdict(list)
    errors = []
    geod = Geod(ellps="GRS80")
    for index in sorted((repo / "public/data").glob("*_index.json")):
        prefix = index.name.removesuffix("_index.json")
        for entry in json.loads(index.read_text()):
            path = index.parent / entry["name"]
            record = {
                "file": entry["name"],
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
                "zip": zipfile.is_zipfile(path),
            }
            try:
                if record["zip"]:
                    with zipfile.ZipFile(path) as z:
                        record["members"] = sorted(z.namelist())
                with open_raster(path) as ds:
                    a = ds.read(1, masked=True)
                    valid = np.asarray(a.compressed())
                    valid = valid[np.isfinite(valid)]
                    b = list(ds.bounds)
                    cx = (b[0] + b[2]) / 2
                    cy = (b[1] + b[3]) / 2
                    if ds.crs.is_geographic:
                        dx = geod.inv(cx, cy, cx + abs(ds.transform.a), cy)[2]
                        dy = geod.inv(cx, cy, cx, cy + abs(ds.transform.e))[2]
                    else:
                        dx, dy = map(abs, ds.res)
                    record.update(
                        crs=str(ds.crs),
                        bounds=b,
                        shape=[ds.height, ds.width],
                        bands=ds.count,
                        pixel_m=[round(dx, 3), round(dy, 3)],
                        valid_cells=len(valid),
                        total_cells=a.size,
                        minimum=float(valid.min()) if len(valid) else None,
                        maximum=float(valid.max()) if len(valid) else None,
                        index_matches=bool(np.allclose(b, entry["bbox"], atol=1e-7, rtol=0)),
                    )
                    if not record["index_matches"]:
                        errors.append(f"Index mismatch: {path.name}")
            except Exception as e:
                errors.append(f"{path.name}: {e}")
            groups[prefix].append(record)
    summary = []
    for prefix, entries in groups.items():
        summary.append(
            {
                "prefix": prefix,
                "files": len(entries),
                "bytes": sum(e["bytes"] for e in entries),
                "encodings": dict(Counter("ZIP" if e["zip"] else "GeoTIFF" for e in entries)),
                "pixel_m": sorted({tuple(e.get("pixel_m", [])) for e in entries}),
                "valid_cells": sum(e.get("valid_cells", 0) for e in entries),
                "minimum": min((e["minimum"] for e in entries if e.get("minimum") is not None), default=None),
                "maximum": max((e["maximum"] for e in entries if e.get("maximum") is not None), default=None),
            }
        )
    report = {
        "source": "Jtensetti/nbs-sandbox-trelleborg",
        "commit": commit,
        "file_count": len(files),
        "raster_files": sum(map(len, groups.values())),
        "layers": summary,
        "errors": errors,
        "scope": "All repository file names and checksums, all indexed raster headers and band-1 cells; semantic review in INVENTORY.md",
    }
    write_json(output / "repository-audit.json", report)
    write_json(output / "raster-files.json", groups)
    return report
