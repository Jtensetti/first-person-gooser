"""Admit local RGB imagery with an existing rights/hash receipt; no network calls."""

import argparse
from pathlib import Path
import rasterio
from goosen.core import DataError, horizontal, read_json, validate_asset, write_json


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--catalog", required=True, type=Path)
    p.add_argument("--image", required=True, type=Path)
    p.add_argument("--rgb-bands", required=True, nargs=3, type=int)
    p.add_argument("--year", required=True, type=int)
    p.add_argument("--output", required=True, type=Path)
    a = p.parse_args()
    if a.output.exists() or a.output.parent.resolve() != a.catalog.parent.resolve():
        raise DataError("Write a fresh catalog alongside the existing catalog")
    relative = a.image.resolve().relative_to(a.catalog.parent.resolve()).as_posix()
    record = read_json(str(a.image) + ".source.json")
    record["path"] = relative
    validate_asset(record, a.catalog.parent, "orthophoto")
    with rasterio.open(a.image) as src:
        if src.crs is None or not horizontal(src.crs).equals(horizontal(record["horizontal_crs"])):
            raise DataError("Image CRS disagrees with receipt")
        if len(set(a.rgb_bands)) != 3 or min(a.rgb_bands) < 1 or max(a.rgb_bands) > src.count:
            raise DataError("Invalid RGB band selection")
        if any(src.dtypes[b - 1] != "uint8" for b in a.rgb_bands):
            raise DataError("Normalize radiometry explicitly to display-ready uint8 sRGB first")
    record.update(rgb_bands=a.rgb_bands, color_space="sRGB", observation_year=a.year)
    catalog = read_json(a.catalog)
    catalog["assets"]["orthophoto"] = [record]
    write_json(a.output, catalog)


if __name__ == "__main__":
    main()
