"""Build a coarse, data-derived surround. It is scenery, outside flight bounds."""

import argparse
import json
from pathlib import Path

import numpy as np

from goosen.core import sha256
from goosen.rasters import warp_nodes


def stage(terrain, landcover, output):
    bounds = [395000, 6132500, 397500, 6135000]
    dem = warp_nodes([terrain], bounds, 20)
    nmd = warp_nodes(landcover, bounds, 20, kind="categorical")
    vertices, colors, indices, water_indices = [], [], [], []
    h, w = dem.values.shape
    for row in range(h):
        for col in range(w):
            e, n = dem.west + col * 20, dem.north - row * 20
            code = nmd.values[row, col]
            z = dem.values[row, col]
            sea = code == 62
            vertices.extend(
                [e - 395500, 0 if sea else float(max(0, z)) if np.isfinite(z) else 0, -(n - 6133500)]
            )
            color = [0.065, 0.16, 0.17] if sea else [0.12, 0.16, 0.065]
            if 110 <= code < 130:
                color = [0.06, 0.10, 0.035]
            elif code in (51, 52, 53):
                color = [0.20, 0.19, 0.16]
            elif code in (3, 4):
                color = [0.15, 0.18, 0.075]
            colors.extend(color)
    for row in range(h - 1):
        for col in range(w - 1):
            e, n = dem.west + col * 20, dem.north - row * 20
            # Pilot boundaries align with this lattice: no duplicate surface.
            if 395500 <= e < 396500 and 6133500 < n <= 6134500:
                continue
            if not np.isfinite(nmd.values[row : row + 2, col : col + 2]).all():
                continue
            a = row * w + col
            target = water_indices if np.all(nmd.values[row : row + 2, col : col + 2] == 62) else indices
            target.extend([a, a + w, a + w + 1, a, a + w + 1, a + 1])
    mesh = {
        "positions": vertices,
        "colors": colors,
        "indices": indices,
        "water_indices": water_indices,
        "note": "20m distant LOD from native DTM and NMD; no buildings outside pilot",
        "bounds": bounds,
        "sources": {p.name: sha256(p) for p in [terrain, *landcover]},
    }
    path = output / "horizon.json"
    path.write_text(json.dumps(mesh, separators=(",", ":")), encoding="utf8")
    manifest_path = output / "world.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf8"))
    manifest["horizon"] = "horizon.json"
    manifest["files"]["horizon.json"] = sha256(path)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf8")
    print(f"Derived surround: {len(indices) // 3} triangles; flight bounds unchanged")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--terrain", type=Path, required=True)
    p.add_argument("--landcover", type=Path, nargs="+", required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    stage(a.terrain, a.landcover, a.output)
