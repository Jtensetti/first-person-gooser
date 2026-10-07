from __future__ import annotations

import hashlib
import json
import math

import numpy as np
from shapely import constrained_delaunay_triangles
from shapely.geometry import MultiLineString, Polygon, shape
from shapely.ops import transform

from .core import DataError, transform_xy


def polygons(geometry):
    if geometry.is_empty:
        return []
    if geometry.geom_type == "Polygon":
        return [geometry]
    if hasattr(geometry, "geoms"):
        return [p for part in geometry.geoms for p in polygons(part)]
    return []


def esri_polygon(rings):
    """Even/odd nesting handles disjoint shells and holes regardless of winding."""
    result = Polygon()
    for ring in rings:
        if len(ring) < 4:
            raise DataError("Invalid ArcGIS ring")
        poly = Polygon([p[:2] for p in ring])
        if not poly.is_valid:
            raise DataError("Invalid ArcGIS polygon; do not silently repair source geometry")
        result = result.symmetric_difference(poly)
    return result


def read_features(path, declared_crs):
    data = json.loads(path.read_text(encoding="utf8"))
    features = []
    if data.get("geometryType") == "esriGeometryMultiPatch":
        raise DataError("Municipal multipatches are staged only; 3D conversion must preserve roof topology")
    # Explicit declaration wins only if it matches metadata.
    advertised = data.get("crs", {}).get("properties", {}).get("name") or data.get(
        "spatialReference", {}
    ).get("wkid")
    if advertised:
        from .core import horizontal

        if not horizontal(advertised).equals(horizontal(declared_crs)):
            raise DataError("Vector CRS metadata disagrees with catalog")
    convert = transform_xy(declared_crs, 3006)
    for f in data.get("features", []):
        raw = f.get("geometry")
        if raw is None:
            raise DataError("Null feature geometry")
        if "rings" in raw:
            geom = esri_polygon(raw["rings"])
        elif "paths" in raw:
            geom = MultiLineString([[(p[0], p[1]) for p in ring] for ring in raw["paths"]])
        elif "type" in raw:
            geom = shape(raw)
        else:
            raise DataError("Unsupported geometry. Multipatches require the dedicated 3D importer")
        if not geom.is_valid or geom.is_empty:
            raise DataError("Invalid/empty source geometry")

        # Deliberately 2D: do not accidentally treat an undocumented Z as RH2000.
        def xy(x, y, z=None):
            return convert(x, y)

        geom = transform(xy, geom)
        props = f.get("properties", f.get("attributes", {}))
        fid = str(
            f.get("id")
            or props.get("OBJECTID")
            or hashlib.sha256(json.dumps([raw, props], sort_keys=True).encode()).hexdigest()[:20]
        )
        features.append({"id": fid, "geometry": geom, "properties": props})
    if len({f["id"] for f in features}) != len(features):
        raise DataError("Duplicate vector feature ID")
    return features


def polygon_mesh(geom, height, origin, z_offset=0):
    """Constrained triangulation preserves concavities and inner courtyards."""
    verts = []
    faces = []
    lookup = {}
    for poly in polygons(geom):
        for tri in constrained_delaunay_triangles(poly).geoms:
            coords = list(tri.exterior.coords)[:-1]
            if len(coords) != 3:
                raise DataError("Expected triangle")
            if not tri.exterior.is_ccw:
                coords.reverse()
            face = []
            for x, y in coords:
                z = float(height(x, y))
                if not math.isfinite(z):
                    raise DataError("Surface has missing terrain")
                key = (float(x), float(y), z)
                if key not in lookup:
                    lookup[key] = len(verts)
                    verts.append([x - origin[0], y - origin[1], z - z_offset])
                face.append(lookup[key])
            faces.append(face)
    return {"vertices": verts, "faces": faces}


def drape_mesh(geom, grid, origin, offset=0.03):
    """Clip to every terrain triangle so overlay faces cannot cut through slopes."""
    import shapely

    vertices, faces = [], []
    for poly in polygons(geom):
        w, s, e, n = poly.bounds
        col0 = max(0, math.floor((w - grid.west) / grid.step))
        col1 = min(grid.values.shape[1] - 1, math.ceil((e - grid.west) / grid.step))
        row0 = max(0, math.floor((grid.north - n) / grid.step))
        row1 = min(grid.values.shape[0] - 1, math.ceil((grid.north - s) / grid.step))
        if (col1 - col0) * (row1 - row0) > 250000:
            raise DataError("Surface mesh exceeds budget")
        col, row = np.meshgrid(np.arange(col0, col1), np.arange(row0, row1))
        tl = np.column_stack((grid.west + col.ravel() * grid.step, grid.north - row.ravel() * grid.step))
        if not len(tl):
            continue
        bl, br, tr = tl + [0, -grid.step], tl + [grid.step, -grid.step], tl + [grid.step, 0]
        triangles = shapely.polygons(
            np.concatenate((np.stack((tl, bl, br), axis=1), np.stack((tl, br, tr), axis=1)))
        )
        patches = shapely.intersection(triangles[shapely.intersects(triangles, poly)], poly)
        for patch in patches:
            if patch.area <= 1e-10:
                continue
            part = polygon_mesh(patch, lambda x, y: float(grid.sample_mesh(x, y)) + offset, origin)
            start = len(vertices)
            vertices.extend(part["vertices"])
            faces.extend([[v + start for v in f] for f in part["faces"]])
    return {"vertices": vertices, "faces": faces}


def building_mesh(geom, grid, height, origin, roof=None):
    # Use a level foundation at the lowest footprint sample; terrain hides the skirt.
    points = [xy for poly in polygons(geom) for xy in poly.exterior.coords]
    z = np.asarray(grid.sample([p[0] for p in points], [p[1] for p in points]))
    if not np.isfinite(z).all():
        raise DataError("Building footprint has missing terrain")
    bottom = float(z.min()) - 0.25
    top = float(z.max()) + height
    if roof:

        def top_fn(x, y):
            return roof[0] * (x - roof[3]) + roof[1] * (y - roof[4]) + roof[2]
    else:

        def top_fn(x, y):
            return top

    payload = polygon_mesh(geom, top_fn, origin)
    for poly in polygons(geom):
        from shapely.geometry.polygon import orient

        poly = orient(poly, sign=1)
        for ring in [poly.exterior, *poly.interiors]:
            coords = list(ring.coords)
            for a, b in zip(coords, coords[1:]):
                v = len(payload["vertices"])
                payload["vertices"].extend(
                    [
                        [a[0] - origin[0], a[1] - origin[1], bottom],
                        [b[0] - origin[0], b[1] - origin[1], bottom],
                        [b[0] - origin[0], b[1] - origin[1], top_fn(*b)],
                        [a[0] - origin[0], a[1] - origin[1], top_fn(*a)],
                    ]
                )
                payload["faces"].append([v, v + 1, v + 2, v + 3])
    return payload


def clip_terrain_water(payload, grid, water, origin):
    """Cut water footprints out of terrain; no coplanar sea or invented bathymetry."""
    if water.is_empty or not payload["faces"]:
        return payload
    import shapely

    vertices = np.asarray(payload["vertices"])
    faces = np.asarray(payload["faces"], dtype=int)
    xy = vertices[faces, :2] + np.asarray(origin[:2])
    cells = shapely.polygons(xy)
    shapely.prepare(water)
    wet = shapely.intersects(water, cells)
    submerged = shapely.covers(water, cells)
    kept = faces[~wet].tolist()
    result = {"vertices": payload["vertices"], "faces": kept}
    for index in np.flatnonzero(wet & ~submerged):
        dry = cells[index].difference(water)
        patch = polygon_mesh(dry, lambda x, y: float(grid.sample_mesh(x, y)), origin)
        start = len(result["vertices"])
        result["vertices"].extend(patch["vertices"])
        result["faces"].extend([[start + i for i in f] for f in patch["faces"]])
    return result
