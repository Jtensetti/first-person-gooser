"""Replace coarse terrain with the downloaded, evidenced 1 m LM DTM.

Creates a new catalog. Never renames EGM96 heights to RH2000 or alters an old build.
"""

import argparse
from pathlib import Path

import rasterio

from goosen.core import DataError, horizontal, read_json, sha256, write_json


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--catalog", type=Path, required=True)
    p.add_argument("--dtm", type=Path, required=True)
    p.add_argument("--lidar", type=Path)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    if a.output.exists() or a.output.parent.resolve() != a.catalog.parent.resolve():
        raise DataError("Write a new catalog alongside the existing one; relative paths must stay valid")
    j = read_json(a.catalog)
    for role, path in [("terrain", a.dtm), ("lidar", a.lidar)]:
        if path is None:
            continue
        rec = read_json(str(path) + ".source.json")
        if (
            rec.get("use_status") != "authorized"
            or rec.get("vertical_crs") != "EPSG:5613"
            or sha256(path) != rec.get("sha256")
        ):
            raise DataError("Expected verified authorized LM download receipt in RH2000")
        if role == "terrain":
            with rasterio.open(path) as r:
                if horizontal(r.crs).to_epsg() != 3006 or max(r.res) > 2:
                    raise DataError(
                        "DTM must be metric SWEREF99 TM, <=2 m; resampling does not increase native quality"
                    )
                rec.update(native_resolution_m=max(r.res), surface_kind="DTM")
        rec["path"] = path.resolve().relative_to(a.output.parent.resolve()).as_posix()
        j["assets"][role] = [rec]
    j["purpose"] = "LM height data adopted; remaining geometric and visual quality gates still apply"
    write_json(a.output, j)


if __name__ == "__main__":
    main()
