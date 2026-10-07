"""Render repeatable actual-scene review views, without changing geodata."""

import bpy
import sys
from pathlib import Path
from mathutils import Vector

out = Path(sys.argv[sys.argv.index("--") + 1]).resolve()
scene = bpy.context.scene
scene.cycles.samples = 48
scene.cycles.use_denoising = True
scene.render.resolution_x = 1600
scene.render.resolution_y = 1000
views = [
    ("hamnen", (740, -150, 220), (450, 220, 5), 38),
    ("bostader", (980, 540, 130), (770, 800, 7), 48),
    ("takdetalj", (800, 770, 45), (760, 850, 7), 55),
]
original = scene.camera
for name, position, target, lens in views:
    data = bpy.data.cameras.new(name)
    cam = bpy.data.objects.new(name, data)
    bpy.data.collections["GOOSEN"].objects.link(cam)
    cam.location = position
    cam.rotation_euler = (Vector(target) - cam.location).to_track_quat("-Z", "Y").to_euler()
    data.lens = lens
    data.clip_end = 10000
    scene.camera = cam
    scene.render.filepath = str(out / (name + ".png"))
    bpy.ops.render.render(write_still=True)
scene.camera = original
bpy.ops.wm.save_as_mainfile(filepath=str(out / "goosen-pilot.blend"))
