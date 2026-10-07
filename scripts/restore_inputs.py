"""Restore a bundle into a fresh folder after separately supplied SHA-256 verification."""

import argparse
from pathlib import Path
from goosen.core import read_json
from goosen.handoff import restore_bundle, verify_bundle

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--bundle", required=True, type=Path)
    p.add_argument("--checksum", required=True, type=Path)
    p.add_argument("--output", type=Path, help="Omit to verify without extracting")
    p.add_argument("--max-gb", type=float, default=20)
    a = p.parse_args()
    digest = read_json(a.checksum)["sha256"]
    if a.output:
        m = restore_bundle(a.bundle, digest, a.output, int(a.max_gb * 1e9))
    else:
        m = verify_bundle(a.bundle, digest, int(a.max_gb * 1e9))
    print(f"Verified {len(m['files'])} files; public redistribution is not implied")
