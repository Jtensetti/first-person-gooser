"""Admit a frozen directed coastline into a fresh sibling catalog."""

import argparse
from pathlib import Path
from goosen.core import DataError, read_json, validate_asset, write_json


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--catalog", required=True, type=Path)
    p.add_argument("--coast", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    a = p.parse_args()
    root = a.catalog.resolve().parent
    if a.output.exists() or a.output.resolve().parent != root:
        raise DataError("Write a fresh catalog alongside the existing catalog")
    directory = a.coast.resolve()
    if not directory.is_relative_to(root):
        raise DataError("Acquire coast within the catalog directory for portable handoff")
    catalog = read_json(a.catalog)
    for role, records in read_json(directory / "assets.json").items():
        if role not in ("coastline", "coastline_source"):
            raise DataError("Unexpected coast asset role")
        for record in records:
            path = validate_asset(record, directory, role)
            record["path"] = path.relative_to(root).as_posix()
        catalog["assets"][role] = records
    write_json(a.output, catalog)


if __name__ == "__main__":
    main()
