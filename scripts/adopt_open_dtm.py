"""Download reviewed open data and replace terrain in a new sibling catalog."""

import argparse
from pathlib import Path
from goosen.core import DataError, load_config, read_json, write_json
from goosen.open_dtm import fetch_open_dtm


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--catalog", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--config", default="configs/pilot.json")
    p.add_argument("--source", default="configs/open-dtm-pilot.json")
    a = p.parse_args()
    root = a.catalog.resolve().parent
    if a.output.exists() or a.output.resolve().parent != root:
        raise DataError("Choose a fresh sibling catalog")
    folder = root / "open-dtm"
    assets = fetch_open_dtm(load_config(a.config), a.source, folder)
    j = read_json(a.catalog)
    for role, items in assets.items():
        for item in items:
            item["path"] = (folder / item["path"]).relative_to(root).as_posix()
        j["assets"][role] = items
    write_json(a.output, j)
