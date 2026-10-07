"""Omit unused tangent streams; preserve tangents for normal-mapped materials.

Blender can emit zero tangents on tiny coastal terrain triangles. Those terrain
materials have no normal map, so these streams serve no shading purpose.
"""

import json
import struct
from pathlib import Path


def strip_unused_tangents(path):
    path = Path(path)
    raw = path.read_bytes()
    magic, version, length = struct.unpack_from("<4sII", raw)
    size, kind = struct.unpack_from("<I4s", raw, 12)
    if magic != b"glTF" or version != 2 or length != len(raw) or kind != b"JSON":
        raise ValueError("Unexpected GLB container")
    document = json.loads(raw[20 : 20 + size])

    def requires_tangents(value):
        if isinstance(value, dict):
            return any(k.lower().endswith("normaltexture") or requires_tangents(v) for k, v in value.items())
        if isinstance(value, list):
            return any(requires_tangents(v) for v in value)
        return False

    removed = 0
    materials = document.get("materials", [])
    for mesh in document.get("meshes", []):
        for primitive in mesh.get("primitives", []):
            material = materials[primitive["material"]] if "material" in primitive else {}
            if not requires_tangents(material) and "TANGENT" in primitive.get("attributes", {}):
                del primitive["attributes"]["TANGENT"]
                removed += 1
    if removed:
        payload = json.dumps(document, separators=(",", ":"), ensure_ascii=True).encode()
        payload += b" " * ((-len(payload)) % 4)
        tail = raw[20 + size :]
        path.write_bytes(
            struct.pack("<4sII", b"glTF", 2, 20 + len(payload) + len(tail))
            + struct.pack("<I4s", len(payload), b"JSON")
            + payload
            + tail
        )
    return removed
