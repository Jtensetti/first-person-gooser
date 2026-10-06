from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path

from pyproj import CRS, Transformer


class DataError(ValueError):
    """An input cannot safely be interpreted as the claimed geography."""


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf8"))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf8")
    os.replace(tmp, path)


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def stable_seed(*values):
    return int.from_bytes(hashlib.sha256(json.dumps(values).encode()).digest()[:8], "big")


def horizontal(crs):
    parsed = CRS.from_user_input(crs)
    return parsed.sub_crs_list[0] if parsed.is_compound else parsed


def transform_xy(src, dst):
    return Transformer.from_crs(horizontal(src), horizontal(dst), always_xy=True).transform


def load_config(path):
    c = read_json(path)
    if c.get("schema") != 1 or c.get("horizontal_crs") != "EPSG:3006":
        raise DataError("Configuration must use schema 1 and SWEREF99 TM EPSG:3006")
    if c.get("vertical_crs") != "EPSG:5613":
        raise DataError("Production vertical reference must be RH2000 (EPSG:5613)")
    b = c["bounds"]
    if len(b) != 4 or not all(math.isfinite(x) for x in b) or b[0] >= b[2] or b[1] >= b[3]:
        raise DataError("Invalid metric bounds")
    if not (250000 < b[0] < b[2] < 550000 and 6050000 < b[1] < b[3] < 6300000):
        raise DataError("Bounds outside expected southern Sweden range: check axis order/CRS")
    size = c["tile_size_m"]
    steps = c["lod_steps_m"]
    if size not in (250, 500, 1000) or not steps or steps != sorted(set(steps)):
        raise DataError("Use tile sizes 250/500/1000 and increasing LOD steps")
    for d in [b[2] - b[0], b[3] - b[1]]:
        if d % size:
            raise DataError("AOI must comprise whole metric tiles")
    if any(s <= 0 or size % s for s in steps) or c["terrain_step_m"] != steps[0]:
        raise DataError("LOD steps must divide tile size; first step is terrain_step_m")
    if (b[2] - b[0]) * (b[3] - b[1]) > 4_000_000:
        raise DataError("One job is limited to 4 km². Schedule multiple jobs when scaling")
    if c.get("crop_codebook"):
        c["crop_map"] = read_json(Path(path).parent / c["crop_codebook"])
    return c


def geographic_bounds(c, halo=0):
    w, s, e, n = c["bounds"]
    t = Transformer.from_crs(3006, 4326, always_xy=True)
    return list(t.transform_bounds(w - halo, s - halo, e + halo, n + halo, densify_pts=21))


def tiles(c):
    w, s, e, n = c["bounds"]
    size = c["tile_size_m"]
    for y in range(int((n - s) / size)):
        for x in range(int((e - w) / size)):
            left, bottom = w + x * size, s + y * size
            yield {
                "id": f"E{int(left)}_N{int(bottom)}_{size}",
                "bounds": [left, bottom, left + size, bottom + size],
            }


def validate_asset(asset, root, role):
    path = (Path(root) / asset["path"]).resolve()
    if not path.is_file() or sha256(path) != asset.get("sha256"):
        raise DataError(f"{role}: missing file or checksum mismatch: {path}")
    if not asset.get("source") or not asset.get("license") or not asset.get("license_evidence"):
        raise DataError(f"{role}: source, licence and evidence required")
    if asset.get("use_status") not in ("open", "authorized"):
        raise DataError(f"{role}: use is not cleared; verify source terms first")
    if asset.get("evidence") not in ("measured", "derived", "modeled"):
        raise DataError(f"{role}: explicit evidence class required")
    return path
