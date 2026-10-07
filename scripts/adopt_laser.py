"""Admit an authenticated, locally downloaded Lantmateriet laser delivery."""

import argparse
from pathlib import Path
from goosen.core import load_config
from goosen.laser_ingest import adopt_laser

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--catalog", type=Path, required=True)
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--item", type=Path, required=True)
    p.add_argument("--permission", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--config", default="configs/pilot-open.json")
    a = p.parse_args()
    r = adopt_laser(load_config(a.config), a.catalog, a.source, a.item, a.permission, a.output)
    print(f"Verified and cropped {r['point_count']} points; original observations preserved")
