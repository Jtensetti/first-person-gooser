import hashlib
import json
import subprocess
import zipfile
import pytest
from goosen.core import DataError, sha256, write_json
from goosen.handoff import bundle, restore_bundle, verify_bundle, safe_relative
from goosen.source_lock import locked_bytes


def catalog(tmp_path):
    source = tmp_path / "åker.json"
    source.write_text('{"crop":"råg"}', encoding="utf8")
    path = tmp_path / "catalog.json"
    write_json(
        path,
        {
            "schema": 1,
            "assets": {
                "fields": [
                    {
                        "path": source.name,
                        "sha256": sha256(source),
                        "source": "synthetic",
                        "license": "fixture",
                        "license_evidence": "fixture",
                        "use_status": "open",
                        "evidence": "modeled",
                        "redistribution_status": "review",
                    }
                ]
            },
        },
    )
    return path


def test_round_trip_and_modified_bundle_rejected(tmp_path):
    path = catalog(tmp_path)
    (tmp_path / ".env").write_text("not a bundle input")
    archive = tmp_path / "inputs.zip"
    m = bundle(path, archive)
    assert {i["path"] for i in m["files"]} == {"catalog.json", "åker.json"}
    output = tmp_path / "restored"
    restore_bundle(archive, sha256(archive), output)
    assert (output / "åker.json").read_bytes() == (tmp_path / "åker.json").read_bytes()
    with pytest.raises(DataError, match="exists"):
        restore_bundle(archive, sha256(archive), output)
    with pytest.raises(DataError, match="SHA-256"):
        verify_bundle(archive, "0" * 64)
    with pytest.raises(DataError, match="budget"):
        verify_bundle(archive, sha256(archive), max_bytes=10)


@pytest.mark.parametrize("member", ["../escape", "C:/escape", "a\\escape", "CON.txt", "folder./x"])
def test_restore_rejects_unsafe_paths_atomically(tmp_path, member):
    with pytest.raises(DataError, match="Unsafe"):
        safe_relative(member)
    p = tmp_path / "bad.zip"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr(member, b"bad")
        z.writestr("handoff-manifest.json", json.dumps({"schema": 1, "files": []}))
    with pytest.raises(DataError):
        restore_bundle(p, sha256(p), tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_member_hash_is_checked_even_with_correct_outer_hash(tmp_path):
    p = tmp_path / "bad.zip"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("catalog.json", b"{}")
        z.writestr(
            "handoff-manifest.json",
            json.dumps({"schema": 1, "files": [{"path": "catalog.json", "bytes": 2, "sha256": "0" * 64}]}),
        )
    with pytest.raises(DataError, match="member checksum"):
        verify_bundle(p, sha256(p))


def test_crlf_checkout_uses_exact_blob_but_never_masks_edits(tmp_path):
    def git(*args):
        return subprocess.check_output(["git", "-C", str(tmp_path), *args])

    git("init")
    git("config", "core.autocrlf", "false")
    original = b"one\ntwo\n"
    p = tmp_path / "data.json"
    p.write_bytes(original)
    git("add", "data.json")
    git("-c", "user.email=test@example.invalid", "-c", "user.name=Test", "commit", "-m", "fixture")
    commit = git("rev-parse", "HEAD").decode().strip()
    digest = hashlib.sha256(original).hexdigest()
    p.write_bytes(original.replace(b"\n", b"\r\n"))
    assert locked_bytes(tmp_path, p.name, digest, commit) == original
    p.write_bytes(b"changed\r\n")
    with pytest.raises(DataError, match="not verified"):
        locked_bytes(tmp_path, p.name, digest, commit)
