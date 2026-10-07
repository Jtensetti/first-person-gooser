import importlib.util
import json
import struct
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "cleanup", Path(__file__).parents[1] / "blender/gltf_cleanup.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_unused_tangent_cleanup_preserves_normal_maps_and_binary(tmp_path):
    doc = {
        "materials": [
            {},
            {"normalTexture": {"index": 0}},
            {"extensions": {"test": {"clearcoatNormalTexture": {"index": 1}}}},
        ],
        "meshes": [
            {"primitives": [{"material": i, "attributes": {"POSITION": 0, "TANGENT": 1}} for i in range(3)]}
        ],
    }
    data = json.dumps(doc).encode()
    data += b" " * ((-len(data)) % 4)
    tail = struct.pack("<I4s", 4, b"BIN\0") + b"1234"
    path = tmp_path / "test.glb"
    path.write_bytes(
        struct.pack("<4sII", b"glTF", 2, 20 + len(data) + len(tail))
        + struct.pack("<I4s", len(data), b"JSON")
        + data
        + tail
    )
    assert module.strip_unused_tangents(path) == 1
    raw = path.read_bytes()
    size = struct.unpack_from("<I", raw, 12)[0]
    out = json.loads(raw[20 : 20 + size])
    assert raw[20 + size :] == tail
    assert struct.unpack_from("<I", raw, 8)[0] == len(raw)
    primitives = out["meshes"][0]["primitives"]
    assert "TANGENT" not in primitives[0]["attributes"]
    assert all("TANGENT" in p["attributes"] for p in primitives[1:])
    assert module.strip_unused_tangents(path) == 0
