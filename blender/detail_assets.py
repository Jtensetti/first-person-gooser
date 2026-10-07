"""Original deterministic botanical and facade meshes. No external image textures."""

import math
import random
import bpy
from mathutils import Vector


def tree_payload(seed=31):
    rng = random.Random(seed)
    vertices = []
    faces = []
    mats = []

    def branch(a, b, r0, r1):
        axis = Vector(b) - Vector(a)
        u = axis.cross(Vector((0, 1, 0))).normalized()
        v = axis.normalized().cross(u)
        start = len(vertices)
        for center, r in [(Vector(a), r0), (Vector(b), r1)]:
            for i in range(7):
                vertices.append(
                    tuple(center + r * (u * math.cos(i * math.tau / 7) + v * math.sin(i * math.tau / 7)))
                )
        for i in range(7):
            faces.append((start + i, start + (i + 1) % 7, start + (i + 1) % 7 + 7, start + i + 7))
            mats.append(0)

    branch((0, 0, 0), (0.012, 0, 0.72), 0.019, 0.006)
    clusters = []
    for i in range(18):
        a = i * 2.399
        z = 0.36 + i * 0.026
        r = 0.22 * (1 - 0.55 * (i / 18))
        end = (math.cos(a) * r, math.sin(a) * r, z + 0.13)
        branch((0, 0, z - 0.12), end, 0.007 * (1 - i / 25), 0.002)
        clusters.append((end[0], end[1], end[2], 0.12 if i < 12 else 0.09))
    clusters.append((0, 0, 0.90, 0.10))
    # Leaf sprays, irregularly oriented and layered: depth and porous silhouettes.
    for cx, cy, cz, r in clusters:
        for j in range(60):
            a = rng.uniform(0, math.tau)
            zz = rng.uniform(-1, 1)
            rr = r * rng.random() ** (1 / 3)
            loc = Vector(
                (
                    cx + rr * math.sqrt(1 - zz * zz) * math.cos(a),
                    cy + rr * math.sqrt(1 - zz * zz) * math.sin(a),
                    cz + rr * zz * 0.7,
                )
            )
            az = rng.uniform(0, math.tau)
            length = rng.uniform(0.018, 0.034)
            u = Vector((math.cos(az) * length, math.sin(az) * length, rng.uniform(-0.01, 0.01)))
            v = Vector((-math.sin(az) * length * 0.45, math.cos(az) * length * 0.45, 0.005))
            i = len(vertices)
            vertices.extend(
                [
                    tuple(loc - u),
                    tuple(loc + v),
                    tuple(loc + u),
                    tuple(loc - v),
                    tuple(loc + Vector((0, 0, 0.005))),
                ]
            )
            faces.extend([(i, i + 1, i + 4), (i + 1, i + 2, i + 4), (i + 2, i + 3, i + 4), (i + 3, i, i + 4)])
            m = 1 + rng.randrange(4)
            mats.extend([m] * 4)
    return {"vertices": vertices, "faces": faces}, mats


def facade_payload(payload, seed):
    """Generic window rhythm on existing wall quads; never surveyed facade detail."""
    rng = random.Random(seed)
    result = {k: {"vertices": [], "faces": []} for k in ["window_glass", "window_frame"]}

    def quad(kind, pts):
        m = result[kind]
        i = len(m["vertices"])
        m["vertices"].extend([tuple(p) for p in pts])
        m["faces"].append([i, i + 1, i + 2, i + 3])

    door_done = False
    for face in payload["faces"]:
        if len(face) != 4:
            continue
        a, b, c, d = [Vector(payload["vertices"][i]) for i in face]
        along = b - a
        length = along.length
        if length < 3 or length > 90:
            continue
        along.normalize()
        normal = Vector((along.y, -along.x, 0))
        wallheight = min(c.z, d.z) - max(a.z, b.z)
        floors = min(4, int((wallheight - 0.2) / 2.6))
        bays = max(1, int(length / 3.1))
        door_bay = bays // 2 if not door_done and wallheight > 2.4 and length > 4 else -1
        if door_bay >= 0:
            center = a + along * ((door_bay + 0.5) * length / bays) + normal * 0.04
            center.z = max(a.z, b.z) + 1.15
            u, v = along * 0.52, Vector((0, 0, 1.08))
            quad("window_frame", [center - u - v, center + u - v, center + u + v, center - u + v])
            center += normal * 0.012
            u, v = along * 0.45, Vector((0, 0, 1.01))
            quad("window_glass", [center - u - v, center + u - v, center + u + v, center - u + v])
            door_done = True
        for floor in range(floors):
            for bay in range(bays):
                if (floor == 0 and bay == door_bay) or rng.random() < 0.12:
                    continue
                center = a + along * ((bay + 0.5) * length / bays) + normal * 0.035
                center.z = max(a.z, b.z) + 1.9 + floor * 2.7
                if center.z + 0.65 > min(c.z, d.z) - 0.2:
                    continue
                u = along * 0.59
                v = Vector((0, 0, 0.65))
                quad("window_frame", [center - u - v, center + u - v, center + u + v, center - u + v])
                center += normal * 0.012
                u = along * 0.49
                v = Vector((0, 0, 0.55))
                quad("window_glass", [center - u - v, center + u - v, center + u + v, center - u + v])
                center += normal * 0.005
                u = along * 0.023
                quad("window_frame", [center - u - v, center + u - v, center + u + v, center - u + v])
    return result


def micro_material(mat, name):
    """Metric object coordinates keep water/soil detail continuous across tiles."""
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    bsdf = nodes.get("Principled BSDF")
    tex = nodes.new("ShaderNodeTexNoise")
    tex.inputs["Scale"].default_value = 1.8 if name == "water" else 5
    tex.inputs["Detail"].default_value = 3
    geom = nodes.new("ShaderNodeNewGeometry")
    links.new(geom.outputs["Position"], tex.inputs["Vector"])
    bump = nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.22
    bump.inputs["Distance"].default_value = 0.09 if name == "water" else 0.035
    links.new(tex.outputs["Fac"], bump.inputs["Height"])
    links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    if name.startswith("ground-"):
        # Fine tonal modulation preserves the actual satellite RGB underneath.
        image = next((n for n in nodes if n.type == "TEX_IMAGE"), None)
        if image:
            ramp = nodes.new("ShaderNodeValToRGB")
            ramp.color_ramp.elements[0].color = (0.48, 0.48, 0.48, 1)
            ramp.color_ramp.elements[1].color = (1, 1, 1, 1)
            links.new(tex.outputs["Fac"], ramp.inputs["Fac"])
            mix = nodes.new("ShaderNodeMixRGB")
            mix.blend_type = "MULTIPLY"
            mix.inputs[0].default_value = 0.35
            links.new(image.outputs["Color"], mix.inputs[1])
            links.new(ramp.outputs["Color"], mix.inputs[2])
            links.new(mix.outputs["Color"], bsdf.inputs["Base Color"])


def architectural_uv(obj):
    uv = obj.data.uv_layers.new(name="UVMap")
    for poly in obj.data.polygons:
        normal = poly.normal
        if abs(normal.z) < 0.1:
            u = Vector((-normal.y, normal.x, 0)).normalized()
            v = Vector((0, 0, 1))
        else:
            u = Vector((normal.y, -normal.x, 0))
            if u.length < 0.01:
                u = Vector((1, 0, 0))
            u.normalize()
            v = normal.cross(u).normalized()
        for i in poly.loop_indices:
            co = obj.data.vertices[obj.data.loops[i].vertex_index].co
            uv.data[i].uv = (co.dot(u) / 2, co.dot(v) / 2)


def surface_textures(mat, name, folder):
    """Original repeatable 2 m PBR tiles, packed and exportable with glTF."""
    import numpy as np
    import hashlib

    size = 512
    rng = np.random.default_rng(int(hashlib.sha256(name.encode()).hexdigest()[:8], 16))
    y, x = np.mgrid[0:size, 0:size] / size
    base = np.array(mat.diffuse_color[:3])
    noise = rng.normal(0, 0.025, (size, size))
    height = noise * 0.008
    tint = 1 + noise
    if name.startswith("roof_"):
        row = np.floor(y * 6).astype(int)
        fx = (x * 8 + (row % 2) * 0.5) % 1
        fy = (y * 6) % 1
        grout = (fx < 0.03) | (fy < 0.045)
        tilevar = rng.uniform(0.82, 1.12, (6, 8))
        tint = tilevar[row % 6, np.floor(x * 8 + (row % 2) * 0.5).astype(int) % 8] + noise
        tint = np.where(grout, tint * 0.65, tint)
        height = 0.012 * np.sin(fx * np.pi) + 0.006 * fy
        height[grout] = 0
    elif name.startswith("brick_"):
        row = np.floor(y * 32).astype(int)
        fx = (x * 8 + (row % 2) * 0.5) % 1
        fy = (y * 32) % 1
        grout = (fx < 0.035) | (fy < 0.10)
        tilevar = rng.uniform(0.8, 1.15, (32, 8))
        tint = tilevar[row % 32, np.floor(x * 8 + (row % 2) * 0.5).astype(int) % 8] + noise
        height = np.where(grout, 0, 0.004) + noise * 0.004
    else:
        grout = None
    rgb = np.clip(base[None, None, :] * tint[:, :, None], 0, 1)
    if name.startswith("brick_"):
        rgb[grout] = [0.20, 0.19, 0.16]
    # Image pixel buffer is stored as sRGB for colour; normals are non-colour.
    rgb = np.where(rgb <= 0.0031308, rgb * 12.92, 1.055 * np.maximum(rgb, 0) ** (1 / 2.4) - 0.055)
    dx = (np.roll(height, -1, 1) - np.roll(height, 1, 1)) / (4 / size)
    dy = (np.roll(height, -1, 0) - np.roll(height, 1, 0)) / (4 / size)
    normal = np.dstack([-dx, -dy, np.ones_like(dx)])
    normal /= np.linalg.norm(normal, axis=2)[:, :, None]
    normal = normal * 0.5 + 0.5
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    bsdf = nodes.get("Principled BSDF")
    for kind, data in [("color", rgb), ("normal", normal)]:
        pixels = np.dstack([data, np.ones((size, size))]).astype("float32")
        img = bpy.data.images.new("Goosen-" + name + "-" + kind, width=size, height=size)
        img.colorspace_settings.name = "sRGB" if kind == "color" else "Non-Color"
        img.pixels.foreach_set(pixels.ravel())
        img.filepath_raw = str(folder / (name + "-" + kind + ".png"))
        img.file_format = "PNG"
        img.save()
        img.pack()
        tex = nodes.new("ShaderNodeTexImage")
        tex.image = img
        if kind == "color":
            links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
        else:
            n = nodes.new("ShaderNodeNormalMap")
            links.new(tex.outputs["Color"], n.inputs["Color"])
            links.new(n.outputs["Normal"], bsdf.inputs["Normal"])
