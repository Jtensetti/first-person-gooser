"""Background Blender regression check: wall height must not invent storeys."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from detail_assets import facade_payload

for wall_height in [2.65, 3.25, 7.5, 15]:
    wall = {
        "vertices": [[0, 0, 0], [15, 0, 0], [15, 0, wall_height], [0, 0, wall_height]],
        "faces": [[0, 1, 2, 3]],
    }
    result = facade_payload(wall, 41)
    assert result["window_glass"]["faces"], "Low-rise house lost all windows"
    assert max(v[2] for part in result.values() for v in part["vertices"]) <= 2.31
    assert result == facade_payload(wall, 41)

print("FACADE_QA: low and tall walls retain one modeled window row; deterministic")
