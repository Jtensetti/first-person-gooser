"""Package a previously built local flight viewer; never uploads its data."""

import argparse
import json
import shutil
from pathlib import Path

from goosen.core import sha256


def package(runtime, output):
    dist = runtime / "dist"
    world = dist / "world"
    manifest = json.loads((world / "world.json").read_text(encoding="utf8"))
    for name, checksum in manifest["files"].items():
        if Path(name).name != name or sha256(world / name) != checksum:
            raise ValueError(f"Invalid world file: {name}")
    if output.exists() and any(output.iterdir()):
        raise ValueError("Choose an empty output directory")
    shutil.copytree(dist, output, dirs_exist_ok=True)
    shutil.copyfile(runtime / "serve.py", output / "start.py")
    shutil.copyfile(runtime / "STARTA_GASEN.cmd", output / "STARTA_GASEN.cmd")
    shutil.copyfile(runtime / "node_modules" / "three" / "LICENSE", output / "THREE-LICENSE.txt")
    shutil.copyfile(runtime.parent / "THIRD_PARTY_NOTICES.md", output / "DATA-NOTICES.md")
    shutil.copyfile(runtime.parent / "docs" / "FLIGHT-2026-10-07.md", output / "LAS_MIG.md")
    hashes = {p.relative_to(output).as_posix(): sha256(p) for p in sorted(output.rglob("*")) if p.is_file()}
    (output / "delivery-manifest.json").write_text(
        json.dumps({"schema": 1, "local_preview_only": True, "files": hashes}, indent=2), encoding="utf8"
    )
    print(f"Packaged and hashed {len(hashes)} files in {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", type=Path, default=Path("runtime"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    package(args.runtime, args.output)
