"""Portable entry point: Python 3.11+, installed goosen, optional Blender 4.5+."""

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

from goosen.core import DataError
from goosen.migration import NBS_COMMIT


def run(*args, cwd=None):
    subprocess.run([str(a) for a in args], cwd=cwd, check=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--source", type=Path, default=Path("../nbs-sandbox-trelleborg"))
    p.add_argument("--blender", help="Optional full path to Blender executable")
    p.add_argument("--job", default="pilot")
    p.add_argument("--catalog", type=Path, help="Replay frozen/restored inputs without network acquisition")
    p.add_argument("--osm", action="store_true", help="Explicitly admit ODbL fallback buildings/roads")
    a = p.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", a.job):
        raise DataError("Job name must contain only letters, digits, hyphens and underscores")
    root = Path(__file__).resolve().parents[1]
    source = a.source.resolve()
    if a.catalog:
        if a.osm:
            raise DataError("--catalog replays frozen inputs; do not combine with --osm")
    elif not source.exists():
        # Existing signed-in Git/gh credential helper supplies private repo access.
        # No credentials, login or third-party source contents are copied into code.
        run(
            "git", "clone", "--no-checkout", "https://github.com/Jtensetti/nbs-sandbox-trelleborg.git", source
        )
        run("git", "-C", source, "checkout", "--detach", NBS_COMMIT)
    else:
        # Do not modify an existing user's checkout. Worktree pinning is explicit in docs.
        if not (source / ".git").exists():
            raise DataError("Source must be a git checkout or worktree; see docs/TOMORROW.md")
        head = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
        if head != NBS_COMMIT:
            raise DataError(
                "Source is not pinned. Create a detached worktree as documented; existing work was left intact"
            )
    output = root / "build" / a.job
    if output.exists():
        raise DataError("Build already exists: choose a new --job name")
    common = [sys.executable, "-m", "goosen.cli"]
    catalog = a.catalog.resolve() if a.catalog else root / "data" / a.job / "catalog.json"
    if not a.catalog:
        if catalog.exists():
            raise DataError("Catalog exists; replay it with --catalog or choose a new job")
        run(
            *common,
            "bootstrap-preview",
            "--repo",
            source,
            "--output",
            catalog.parent,
            *(["--osm"] if a.osm else []),
            cwd=root,
        )
    run(
        *common,
        "prepare",
        "--catalog",
        catalog,
        "--output",
        output,
        "--preview",
        cwd=root,
    )
    run(*common, "qa", "--world", output, cwd=root)
    blender = a.blender or shutil.which("blender")
    if blender:
        run(
            blender,
            "-b",
            "--factory-startup",
            "--python-exit-code",
            "1",
            "-P",
            root / "blender/build_world.py",
            "--",
            "--world",
            output,
            "--output",
            root / "build" / (a.job + "-blender"),
            "--allow-preview",
            "--export-glb",
            "--render",
            cwd=root,
        )
    else:
        print("Prepared world package. Run Blender later using docs/TOMORROW.md.")


if __name__ == "__main__":
    main()
