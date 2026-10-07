from __future__ import annotations

import copy
import gzip
import json
import time
from pathlib import Path

import numpy as np

from .core import read_json, sha256, write_json


def audit_world(world):
    world = Path(world)
    m = read_json(world / "manifest.json")
    errors = []
    edges = {}
    counts = {}
    for tile in m["tiles"]:
        path = world / tile["file"]
        if sha256(path) != tile["sha256"]:
            errors.append("Checksum: " + tile["id"])
            continue
        package = json.loads(gzip.decompress(path.read_bytes()))
        texture = world / package["ground_texture"]
        if not texture.is_file() or (
            package.get("ground_texture_info") and sha256(texture) != package["ground_texture_info"]["sha256"]
        ):
            errors.append("Ground texture checksum: " + tile["id"])
        counts[tile["id"]] = {"instances": len(package["instances"]), "objects": len(package["objects"])}
        for obj in package["objects"]:
            vertices = np.asarray(obj["mesh"]["vertices"], dtype=float)
            faces = obj["mesh"]["faces"]
            if not np.isfinite(vertices).all():
                errors.append("Nonfinite vertex: " + obj["id"])
            if any(min(f) < 0 or max(f) >= len(vertices) or len(set(f)) < 3 for f in faces):
                errors.append("Invalid face: " + obj["id"])
            if obj["kind"] == "terrain" and obj.get("lod") == 0:
                w, s, e, n = tile["bounds"]
                v = vertices + np.asarray(package["origin"])
                boundary = (
                    np.isclose(v[:, 0], w, rtol=0, atol=1e-6)
                    | np.isclose(v[:, 0], e, rtol=0, atol=1e-6)
                    | np.isclose(v[:, 1], s, rtol=0, atol=1e-6)
                    | np.isclose(v[:, 1], n, rtol=0, atol=1e-6)
                )
                for x, y, z in v[boundary]:
                    k = (round(x, 6), round(y, 6))
                    if k in edges and abs(edges[k] - z) > 1e-5:
                        errors.append("Terrain seam mismatch")
                    edges[k] = z
        if len(package["instances"]) > m["config"]["max_instances_per_tile"]:
            errors.append("Instance budget")
    r = {
        "schema": 1,
        "world": m["world"],
        "structural_pass": not errors,
        "errors": errors,
        "tile_counts": counts,
        "preview_only": m["preview_only"],
        "acceptance_passed": False,
        "gaps": m["gaps"],
        "scope": "Checksums, finite geometry, face indices, shared LOD0 heights, instance budget. Not ortho/LiDAR/visual validation.",
    }
    write_json(world / "qa.json", r)
    return r


def benchmark(c, catalog, out, preview):
    from .world import prepare

    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for size in (250, 500, 1000):
        cfg = copy.deepcopy(c)
        cfg["tile_size_m"] = size
        # 250 is not divisible by 4: compare common 2/10 m geometry grids.
        cfg["lod_steps_m"] = [2, 10]
        cfg["max_terrain_triangles_per_tile"] = 600000
        start = time.perf_counter()
        m = prepare(cfg, catalog, out / str(size), preview)
        rows.append(
            {
                "tile_size_m": size,
                "tile_count": len(m["tiles"]),
                "prepare_seconds": round(time.perf_counter() - start, 3),
                "compressed_bytes": sum(t["bytes"] for t in m["tiles"]),
                "max_triangles_lod0": max(t["triangles_lod0"] for t in m["tiles"]),
                "scope": "Python preprocessing only; not browser GPU/frame rate",
            }
        )
    write_json(out / "benchmark.json", rows)
    return rows
