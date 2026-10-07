"""Read exact audited Git bytes without trusting checkout line-ending filters."""

import hashlib
import subprocess
from pathlib import Path, PurePosixPath

from .core import DataError


def locked_bytes(repo, relative, expected, commit):
    repo = Path(repo).resolve()
    rel = PurePosixPath(relative)
    if rel.is_absolute() or ".." in rel.parts or "\\" in relative or ":" in relative:
        raise DataError("Unsafe source path")
    path = (repo / relative).resolve()
    if not path.is_relative_to(repo):
        raise DataError("Source path escapes checkout")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() == expected:
        return data
    # Only a CRLF checkout of the exact pinned LF blob is accepted. Never mask
    # user modifications by quietly substituting repository data.
    result = subprocess.run(
        ["git", "-C", str(repo), "show", f"{commit}:{relative}"], capture_output=True, check=False
    )
    canonical = result.stdout
    if (
        result.returncode == 0
        and hashlib.sha256(canonical).hexdigest() == expected
        and b"\0" not in canonical
        and data.replace(b"\r\n", b"\n") == canonical
    ):
        return canonical
    raise DataError("Source file not verified against pinned inventory: " + relative)
