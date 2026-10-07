"""Create a verified local handoff bundle; never upload it."""

import argparse
from pathlib import Path
from goosen.handoff import bundle

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--catalog", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    result = bundle(a.catalog, a.output)
    print(f"Verified {len(result['files'])} files in {a.output}; no upload performed")
