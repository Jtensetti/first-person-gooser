"""Run with Blender 4.5+: blender -b --factory-startup -P blender/build_world.py -- ...

No GIS wheels are installed inside Blender. Inputs are renderer-neutral JSON/gzip.
Only the GOOSEN collection is replaced when running interactively.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import random
import sys
import time
from pathlib import Path

import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
from detail_assets import tree_payload, facade_payload, micro_material, architectural_uv, surface_textures

from gltf_cleanup import strip_unused_tangents

MATERIAL_CACHE = {}

COLORS = {
    "road_paint": (0.60, 0.59, 0.52, 1),
    "ground": (0.2, 0.27, 0.1, 1),
    "building": (0.55, 0.49, 0.40, 1),
    "asphalt": (0.065, 0.07, 0.074, 1),
    "gravel": (0.27, 0.23, 0.18, 1),
    "shore": (0.14, 0.13, 0.11, 1),
    "lawn": (0.048, 0.10, 0.028, 1),
    "field": (0.27, 0.30, 0.12, 1),
    "water": (0.008, 0.032, 0.04, 1),
    "wheat": (0.45, 0.36, 0.13, 1),
    "barley": (0.40, 0.34, 0.14, 1),
    "rapeseed": (0.50, 0.49, 0.07, 1),
    "maize": (0.14, 0.28, 0.045, 1),
    "grass": (0.12, 0.25, 0.065, 1),
    "sugar_beet": (0.10, 0.24, 0.065, 1),
    "broadleaf": (0.06, 0.15, 0.025, 1),
    "potato": (0.10, 0.23, 0.045, 1),
    "flower_mix": (0.24, 0.28, 0.09, 1),
    "bark": (0.12, 0.08, 0.047, 1),
    "roof_clay": (0.23, 0.10, 0.058, 1),
    "roof_charcoal": (0.038, 0.043, 0.048, 1),
    "roof_grey": (0.14, 0.145, 0.14, 1),
    "roof_brown": (0.12, 0.085, 0.058, 1),
    "brick_red": (0.28, 0.13, 0.083, 1),
    "window_glass": (0.045, 0.075, 0.09, 1),
    "window_frame": (0.49, 0.47, 0.41, 1),
    "leaf0": (0.045, 0.11, 0.018, 1),
    "leaf1": (0.08, 0.17, 0.03, 1),
    "leaf2": (0.12, 0.20, 0.045, 1),
    "leaf3": (0.055, 0.13, 0.025, 1),
    "roof_slate": (0.065, 0.073, 0.08, 1),
    "plaster_warm": (0.52, 0.43, 0.30, 1),
    "brick_ochre": (0.33, 0.20, 0.10, 1),
    "plaster_light": (0.66, 0.63, 0.53, 1),
}


def material(name, texture=None):
    existing = MATERIAL_CACHE.get(name)
    if existing:
        return existing
    mat = bpy.data.materials.new("Goosen-" + name)
    MATERIAL_CACHE[name] = mat
    mat.diffuse_color = COLORS.get(name, COLORS["grass"])
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = mat.diffuse_color
    bsdf.inputs["Roughness"].default_value = 0.87
    if name.startswith(("roof_", "plaster_", "brick_")):
        noise = mat.node_tree.nodes.new("ShaderNodeTexNoise")
        coord = mat.node_tree.nodes.new("ShaderNodeTexCoord")
        noise.inputs["Scale"].default_value = 3 if name.startswith("roof_") else 6
        bump = mat.node_tree.nodes.new("ShaderNodeBump")
        bump.inputs["Strength"].default_value = 0.18
        bump.inputs["Distance"].default_value = 0.015
        mat.node_tree.links.new(coord.outputs["Object"], noise.inputs["Vector"])
        mat.node_tree.links.new(noise.outputs["Fac"], bump.inputs["Height"])
        mat.node_tree.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    if name == "water":
        bsdf.inputs["Roughness"].default_value = 0.17
        bsdf.inputs["Metallic"].default_value = 0.1
        bsdf.inputs["IOR"].default_value = 1.333
        noise = mat.node_tree.nodes.new("ShaderNodeTexNoise")
        noise.inputs["Scale"].default_value = 13
        bump = mat.node_tree.nodes.new("ShaderNodeBump")
        bump.inputs["Strength"].default_value = 0.1
        bump.inputs["Distance"].default_value = 0.08
        mat.node_tree.links.new(noise.outputs["Fac"], bump.inputs["Height"])
        mat.node_tree.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    if texture:
        tex = mat.node_tree.nodes.new("ShaderNodeTexImage")
        tex.image = bpy.data.images.load(str(texture), check_existing=True)
        tex.image.pack()
        mat.node_tree.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    if name == "window_glass":
        bsdf.inputs["Roughness"].default_value = 0.23
        bsdf.inputs["Metallic"].default_value = 0.35
    if name.startswith("leaf"):
        bsdf.inputs["Roughness"].default_value = 0.7
    if name == "water" or name.startswith("ground-") or name in ("asphalt", "gravel", "shore", "lawn"):
        micro_material(mat, name)
    if name.startswith(("roof_", "brick_", "plaster_")):
        surface_textures(mat, name, TEXTURE_DIR)
    return mat


def mesh_object(name, payload, collection, mat=None):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(payload["vertices"], [], payload["faces"])
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    if mat:
        mesh.materials.append(mat)
    return obj


def uv_ground(obj, size):
    uv = obj.data.uv_layers.new(name="UVMap")
    for poly in obj.data.polygons:
        for loop_id in poly.loop_indices:
            v = obj.data.vertices[obj.data.loops[loop_id].vertex_index].co
            uv.data[loop_id].uv = (v.x / size, v.y / size)


def prototype(kind, collection):
    """Original procedural engineering assets, not photorealistic substitutes.

    Height is normalized to one metre. Artist assets can replace these later
    without changing geodata, instances or the pipeline.
    """
    verts = []
    faces = []

    def frustum(z0, z1, r0, r1, n=6, cx=0, cy=0):
        start = len(verts)
        for z, r in [(z0, r0), (z1, r1)]:
            verts.extend(
                [
                    (cx + r * math.cos(2 * math.pi * i / n), cy + r * math.sin(2 * math.pi * i / n), z)
                    for i in range(n)
                ]
            )
        faces.extend(
            [(start + i, start + (i + 1) % n, start + n + (i + 1) % n, start + n + i) for i in range(n)]
        )
        faces.append(tuple(start + n + i for i in range(n)))

    if kind == "broadleaf":
        payload, indices = tree_payload()
        obj = mesh_object("asset-" + kind, payload, collection, material("bark"))
        for k in range(4):
            obj.data.materials.append(material("leaf" + str(k)))
        for poly, index in zip(obj.data.polygons, indices):
            poly.material_index = index
            poly.use_smooth = index == 0
        obj["goosen_asset"] = kind
        obj["evidence"] = "modeled"
        obj.hide_render = True
        obj.hide_set(True)
        return obj
    else:
        frustum(0, 0.92, 0.008, 0.004, 4)
        if kind in ("wheat", "barley"):
            frustum(0.78, 1, 0.035, 0.01, 5)
        elif kind == "rapeseed":
            for i in range(6):
                a = i * math.pi / 3
                frustum(
                    0.72 + 0.025 * i, 0.95 + 0.01 * i, 0.04, 0.01, 4, 0.045 * math.cos(a), 0.045 * math.sin(a)
                )
        for i in range(5):
            a = i * 2.4
            z = 0.15 + i * 0.13
            r = 0.15 if kind in ("maize", "sugar_beet", "potato", "flower_mix") else 0.07
            start = len(verts)
            verts.extend(
                [
                    (0, 0, z),
                    (r * math.cos(a), r * math.sin(a), z + 0.15),
                    (r * 0.6 * math.cos(a + 0.35), r * 0.6 * math.sin(a + 0.35), z + 0.22),
                ]
            )
            faces.append((start, start + 1, start + 2))
    base_v, base_f = list(verts), list(faces)
    rng = random.Random(218)
    nominal = {
        "wheat": 0.9,
        "barley": 0.8,
        "rapeseed": 1.25,
        "maize": 1.8,
        "grass": 0.35,
        "sugar_beet": 0.45,
        "potato": 0.6,
        "flower_mix": 0.6,
    }[kind]
    for i in range(63):
        dx, dy = rng.uniform(-1.9, 1.9) / nominal, rng.uniform(-1.9, 1.9) / nominal
        scale = rng.uniform(0.78, 1.02)
        start = len(verts)
        verts.extend([(x + dx, y + dy, z * scale) for x, y, z in base_v])
        faces.extend([tuple(start + j for j in f) for f in base_f])
    obj = mesh_object("asset-" + kind, {"vertices": verts, "faces": faces}, collection, material(kind))
    obj["goosen_asset"] = kind
    obj["evidence"] = "modeled"
    obj.hide_render = True
    obj.hide_set(True)
    return obj


def instance_group(name, points, asset, collection):
    mesh = bpy.data.meshes.new(name + "-points")
    mesh.from_pydata([p["position"] for p in points], [], [])
    mesh.update()
    for attr, key in [("height", "height_m"), ("yaw", "yaw")]:
        a = mesh.attributes.new(attr, "FLOAT", "POINT")
        a.data.foreach_set("value", [p[key] for p in points])
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    tree = bpy.data.node_groups.new(name + "-instances", "GeometryNodeTree")
    tree.interface.new_socket(name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    tree.interface.new_socket(name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    nodes = tree.nodes
    links = tree.links
    inp = nodes.new("NodeGroupInput")
    out = nodes.new("NodeGroupOutput")
    inst = nodes.new("GeometryNodeInstanceOnPoints")
    info = nodes.new("GeometryNodeObjectInfo")
    info.transform_space = "ORIGINAL"
    info.inputs["Object"].default_value = asset
    info.inputs["As Instance"].default_value = True
    links.new(inp.outputs["Geometry"], inst.inputs["Points"])
    links.new(info.outputs["Geometry"], inst.inputs["Instance"])
    height = nodes.new("GeometryNodeInputNamedAttribute")
    height.data_type = "FLOAT"
    height.inputs["Name"].default_value = "height"
    scale = nodes.new("ShaderNodeCombineXYZ")
    links.new(height.outputs["Attribute"], scale.inputs["Z"])
    for axis in "XY":
        links.new(height.outputs["Attribute"], scale.inputs[axis])
    links.new(scale.outputs["Vector"], inst.inputs["Scale"])
    yaw = nodes.new("GeometryNodeInputNamedAttribute")
    yaw.data_type = "FLOAT"
    yaw.inputs["Name"].default_value = "yaw"
    rotation = nodes.new("ShaderNodeCombineXYZ")
    links.new(yaw.outputs["Attribute"], rotation.inputs["Z"])
    links.new(rotation.outputs["Vector"], inst.inputs["Rotation"])
    links.new(inst.outputs["Instances"], out.inputs["Geometry"])
    mod = obj.modifiers.new("Instances - do not realize", "NODES")
    mod.node_group = tree
    obj["goosen_instances"] = True
    return obj


def clean_collection():
    old = bpy.data.collections.get("GOOSEN")
    if old:
        for obj in list(old.all_objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.collections.remove(old)
    collection = bpy.data.collections.new("GOOSEN")
    bpy.context.scene.collection.children.link(collection)
    return collection


def lighting(collection, centre):
    world = bpy.data.worlds.new("Goosen daylight")
    world.use_nodes = True
    sky = world.node_tree.nodes.new("ShaderNodeTexSky")
    sky.sky_type = (
        "MULTIPLE_SCATTERING"
        if "MULTIPLE_SCATTERING" in sky.bl_rna.properties["sky_type"].enum_items.keys()
        else "NISHITA"
    )
    sky.sun_elevation = math.radians(30)
    sky.sun_rotation = math.radians(210)
    sky.sun_disc = False
    world.node_tree.links.new(sky.outputs["Color"], world.node_tree.nodes.get("Background").inputs[0])
    world.node_tree.nodes.get("Background").inputs[1].default_value = 0.14
    bpy.context.scene.world = world
    light = bpy.data.lights.new("Goosen sun - artistic preset", "SUN")
    light.energy = 3
    light.color = (1, 0.91, 0.78)
    light.angle = math.radians(2)
    sun = bpy.data.objects.new(light.name, light)
    collection.objects.link(sun)
    sun.rotation_euler = (0.6, -0.4, -0.6)
    camdata = bpy.data.cameras.new("Pilot inspection camera")
    cam = bpy.data.objects.new(camdata.name, camdata)
    collection.objects.link(cam)
    cam.location = (centre[0], centre[1] - 1050, 950)
    target = Vector((centre[0], centre[1], 5))
    cam.rotation_euler = (target - cam.location).to_track_quat("-Z", "Y").to_euler()
    camdata.lens = 28
    camdata.clip_end = 20000
    bpy.context.scene.camera = cam
    return cam


def export_selected(path, objects):
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        obj.hide_set(False)
        obj.select_set(True)
    if objects:
        bpy.context.view_layer.objects.active = objects[0]
    restore = []
    for mat in bpy.data.materials:
        if not mat.use_nodes or not mat.name.startswith("Goosen-ground-"):
            continue
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        tex = next((n for n in mat.node_tree.nodes if n.type == "TEX_IMAGE"), None)
        socket = bsdf.inputs["Base Color"]
        if tex and socket.links:
            restore.append((mat, socket.links[0].from_socket, socket))
            mat.node_tree.links.new(tex.outputs["Color"], socket)
    bpy.ops.export_scene.gltf(
        filepath=str(path),
        export_format="GLB",
        use_selection=True,
        export_yup=True,
        export_extras=True,
        export_apply=True,
        export_tangents=True,
    )
    strip_unused_tangents(path)
    for mat, source, target in restore:
        mat.node_tree.links.new(source, target)


def build(args):
    if bpy.app.version < (4, 5, 0):
        raise RuntimeError("Blender 4.5 or newer is required")
    world = Path(args.world).resolve()
    manifest = json.loads((world / "manifest.json").read_text(encoding="utf8"))
    if manifest["preview_only"] and not args.allow_preview:
        raise RuntimeError("Engineering preview: pass --allow-preview explicitly")
    out = Path(args.output).resolve()
    if out.exists() and any(out.iterdir()):
        raise RuntimeError("Blender output is not empty; choose a fresh directory")
    out.mkdir(parents=True, exist_ok=True)
    global TEXTURE_DIR
    TEXTURE_DIR = out / "materials"
    TEXTURE_DIR.mkdir(exist_ok=True)
    MATERIAL_CACHE.clear()
    main = clean_collection()
    if args.isolate_scene:
        for existing in bpy.context.scene.objects:
            if existing.name not in main.all_objects:
                existing.hide_render = True
                existing.hide_set(True)
    assets = bpy.data.collections.new("Goosen prototype assets")
    main.children.link(assets)
    prototypes = {
        k: prototype(k, assets)
        for k in [
            "broadleaf",
            "wheat",
            "barley",
            "rapeseed",
            "maize",
            "grass",
            "sugar_beet",
            "potato",
            "flower_mix",
        ]
    }
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1
    origin = manifest["reference_origin"]
    stats = []
    start = time.perf_counter()
    for entry in manifest["tiles"]:
        if args.tile and args.tile != entry["id"]:
            continue
        payload_path = world / entry["file"]
        if hashlib.sha256(payload_path.read_bytes()).hexdigest() != entry["sha256"]:
            raise RuntimeError("Tile checksum mismatch")
        tile = json.loads(gzip.decompress(payload_path.read_bytes()))
        texture_path = world / tile["ground_texture"]
        if (
            tile.get("ground_texture_info")
            and hashlib.sha256(texture_path.read_bytes()).hexdigest() != tile["ground_texture_info"]["sha256"]
        ):
            raise RuntimeError("Ground texture checksum mismatch")
        collection = bpy.data.collections.new(entry["id"])
        main.children.link(collection)
        offset = Vector(tile["origin"]) - Vector(origin)
        export_objects = []
        ground = material("ground-" + entry["id"], world / tile["ground_texture"])
        for record in tile["objects"]:
            if record["kind"] == "terrain" and record.get("lod") != args.lod:
                continue
            obj = mesh_object(
                entry["id"] + "/" + record["id"],
                record["mesh"],
                collection,
                ground
                if record["kind"] == "terrain"
                or (
                    record["kind"] == "field"
                    and tile.get("ground_texture_info", {}).get("kind") in ("orthophoto", "satellite_rgb")
                )
                else material(record["material"]),
            )
            if record["kind"] in ("terrain", "field"):
                uv_ground(obj, entry["bounds"][2] - entry["bounds"][0])
            if record["kind"] == "building":
                architectural_uv(obj)
            obj.location = offset
            obj["evidence"] = record.get("evidence", "derived")
            for key in (
                "height_evidence",
                "roof_evidence",
                "boundary_evidence",
                "level_evidence",
                "material_evidence",
                "model_rule",
                "crop_code",
                "crop_year",
            ):
                if key in record:
                    obj[key] = record[key]
            obj["goosen_kind"] = record["kind"]
            if record.get("part") == "roof":
                mod = obj.modifiers.new("Modeled roof thickness 0.10 m", "SOLIDIFY")
                mod.thickness = 0.10
                mod.offset = -1
                obj["thickness_evidence"] = "modeled"
            export_objects.append(obj)
            if record.get("part") == "walls":
                details = facade_payload(
                    record["mesh"], int(hashlib.sha256(record["id"].encode()).hexdigest()[:8], 16)
                )
                for kind, payload in details.items():
                    if payload["faces"]:
                        detail = mesh_object(obj.name + "/" + kind, payload, collection, material(kind))
                        detail.location = offset
                        detail["evidence"] = "modeled"
                        detail["goosen_kind"] = "facade_detail"
                        export_objects.append(detail)
        for kind in sorted({p["asset"] for p in tile["instances"]}):
            points = [p for p in tile["instances"] if p["asset"] == kind]
            obj = instance_group(entry["id"] + "/" + kind, points, prototypes[kind], collection)
            obj.location = offset
        if args.export_glb:
            # Keep each GLB tile-local. Runtime applies floating-origin placement.
            for obj in export_objects:
                obj.location = (0, 0, 0)
            export_selected(out / (entry["id"] + f"-lod{args.lod}.glb"), export_objects)
            for obj in export_objects:
                obj.location = offset
            # Instances remain compact and separate; never realize millions of plants.
            (out / (entry["id"] + "-instances.json")).write_text(
                json.dumps(tile["instances"], separators=(",", ":"))
            )
        stats.append(
            {
                "tile": entry["id"],
                "mesh_objects": len(export_objects),
                "instances": len(tile["instances"]),
                "triangles": sum(sum(len(p.vertices) - 2 for p in o.data.polygons) for o in export_objects),
            }
        )
    centre = ((manifest["bounds"][2] - origin[0]) / 2, (manifest["bounds"][3] - origin[1]) / 2)
    lighting(main, centre)
    scene["goosen_horizontal_crs"] = "EPSG:3006"
    scene["goosen_vertical_crs"] = manifest["vertical_crs"]
    scene["goosen_preview_only"] = manifest["preview_only"]
    scene["goosen_origin"] = origin
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 32
    scene.cycles.use_denoising = True
    scene.cycles.device = "CPU"
    scene.render.resolution_x = 1600
    scene.render.resolution_y = 1000
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.view_settings.view_transform = "AgX"
    if args.export_glb:
        objects = list(prototypes.values())
        for obj in objects:
            obj.hide_render = False
        export_selected(out / "prototype-assets.glb", objects)
        for obj in objects:
            obj.hide_render = True
            obj.hide_set(True)
    # Persist a useful first view when the user opens a background-built scene.
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type == "VIEW_3D":
                space = area.spaces.active
                space.clip_end = 20000
                space.overlay.show_overlays = False
                space.shading.type = "MATERIAL"
                space.region_3d.view_perspective = "CAMERA"
                space.region_3d.view_camera_zoom = 10
    bpy.ops.wm.save_as_mainfile(filepath=str(out / "goosen-pilot.blend"))
    if args.render:
        scene.render.filepath = str(out / "inspection.png")
        bpy.ops.render.render(write_still=True)
    report = {
        "blender": bpy.app.version_string,
        "elapsed_seconds": round(time.perf_counter() - start, 2),
        "tiles": stats,
        "preview_only": manifest["preview_only"],
        "accepted_photorealism": False,
        "export_axes": "glTF X east, Y up, Z south; translation (E-E0, H, -(N-N0))",
        "limitations": [
            "Procedural prototype vegetation",
            "Generic facades",
            "No browser benchmark",
            "No goose or flight mechanic yet",
        ],
    }
    (out / "blender-report.json").write_text(json.dumps(report, indent=2))
    print("GOOSEN_REPORT " + json.dumps(report))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--world", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--tile")
    p.add_argument("--lod", type=int, choices=[0, 1, 2], default=0)
    p.add_argument("--allow-preview", action="store_true")
    p.add_argument("--export-glb", action="store_true")
    p.add_argument("--render", action="store_true")
    p.add_argument(
        "--isolate-scene",
        action="store_true",
        help="Hide pre-existing objects outside GOOSEN; preserve their data",
    )
    build(p.parse_args(sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []))
