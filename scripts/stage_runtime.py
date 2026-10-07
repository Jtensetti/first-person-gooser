"""Stage the existing local pilot for the flight viewer, without publishing data."""

import argparse
import gzip
import json
import shutil
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from goosen.core import sha256


def stage(world, scene, output):
    if output.exists() and any(output.iterdir()):
        raise ValueError("Use an empty staging directory")
    output.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((world / "manifest.json").read_text(encoding="utf8"))
    bounds = manifest["bounds"]
    if bounds != [395500, 6133500, 396500, 6134500] or len(manifest["tiles"]) != 4:
        raise ValueError("This runtime stages the four 500m Smygehuk pilot tiles only")
    step = manifest["config"]["terrain_step_m"]
    size = round((bounds[2] - bounds[0]) / step) + 1
    ground = np.zeros((size, size), dtype="<f4")
    obstacles = ground.copy()
    overview = Image.new("RGB", (1000, 1000), "#24444b")
    draw = ImageDraw.Draw(overview)
    entries = []
    roofs = []
    trees = []
    for entry in manifest["tiles"]:
        src = world / entry["file"]
        if sha256(src) != entry["sha256"]:
            raise ValueError("Source tile checksum mismatch")
        tile = json.loads(gzip.decompress(src.read_bytes()))
        ox, oy = tile["origin"][0] - bounds[0], tile["origin"][1] - bounds[1]
        name = entry["id"]
        for suffix in ["-lod0.glb", "-instances.json"]:
            shutil.copyfile(scene / (name + suffix), output / (name + suffix))
        entries.append(
            {
                "id": name,
                "east": ox,
                "north": oy,
                "glb": name + "-lod0.glb",
                "instances": name + "-instances.json",
            }
        )
        texture = Image.open(world / tile["ground_texture"]).convert("RGB").resize((500, 500))
        overview.paste(texture, (round(ox), round(1000 - oy - 500)))
        for obj in tile["objects"]:
            mesh = obj["mesh"]
            vertices = np.asarray(mesh["vertices"])
            if not len(vertices):
                continue
            x = vertices[:, 0] + ox
            y = vertices[:, 1] + oy
            if obj["kind"] == "terrain" and obj["lod"] == 0:
                # Initial lattice vertices precede coast clipping additions.
                count = (round(500 / step) + 1) ** 2
                ix, iy = np.rint(x[:count] / step).astype(int), np.rint(y[:count] / step).astype(int)
                ground[iy, ix] = np.maximum(0, vertices[:count, 2])
            if obj["kind"] == "building" and obj.get("part") == "roof":
                roofs.append((np.column_stack((x, y, vertices[:, 2])), mesh["faces"]))
            if obj["kind"] in ("road", "water", "building"):
                color = {"road": "#c8c1a5", "water": "#24444b", "building": "#7c8277"}[obj["kind"]]
                for face in mesh["faces"]:
                    draw.polygon([(float(x[i]), 1000 - float(y[i])) for i in face], fill=color)
        for inst in tile["instances"]:
            if inst["asset"] == "broadleaf":
                p = inst["position"]
                trees.append((p[0] + ox, p[1] + oy, p[2], inst["height_m"]))
    obstacles[:] = ground
    # Conservative roof envelope: bounding cells prevent tunnelling at narrow eaves.
    for vertices, faces in roofs:
        for face in faces:
            v = vertices[face]
            lo = np.maximum(0, np.floor(v[:, :2].min(axis=0) / step).astype(int) - 1)
            hi = np.minimum(size - 1, np.ceil(v[:, :2].max(axis=0) / step).astype(int) + 1)
            obstacles[lo[1] : hi[1] + 1, lo[0] : hi[0] + 1] = np.maximum(
                obstacles[lo[1] : hi[1] + 1, lo[0] : hi[0] + 1], v[:, 2].max()
            )
    for x, y, z, h in trees:
        r = max(1, h * 0.25)
        lo = np.maximum(0, np.floor((np.array([x, y]) - r) / step).astype(int))
        hi = np.minimum(size - 1, np.ceil((np.array([x, y]) + r) / step).astype(int))
        obstacles[lo[1] : hi[1] + 1, lo[0] : hi[0] + 1] = np.maximum(
            obstacles[lo[1] : hi[1] + 1, lo[0] : hi[0] + 1], z + h
        )
    ground.tofile(output / "ground.f32")
    obstacles.tofile(output / "clearance.f32")
    overview.save(output / "map.jpg", quality=90)
    shutil.copyfile(scene / "prototype-assets.glb", output / "prototype-assets.glb")
    result = {
        "schema": 1,
        "name": "Smygehuk",
        "size_m": 1000,
        "step": step,
        "grid_size": size,
        "tiles": entries,
        "origin_sweref99": bounds[:2],
        "height_datum": "RH2000",
        "preview_only": True,
        "source_manifest_sha256": sha256(world / "manifest.json"),
        "attribution": "© OpenStreetMap contributors · Copernicus Sentinel · Lantmäteriet via Mapterhorn · Jordbruksverket",
        "files": {p.name: sha256(p) for p in sorted(output.iterdir()) if p.is_file()},
    }
    (output / "world.json").write_text(json.dumps(result, indent=2), encoding="utf8")
    print(f"Staged {len(entries)} tiles, {size}² height/clearance grids; no upload")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--world", type=Path, required=True)
    p.add_argument("--scene", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    stage(a.world, a.scene, a.output)
