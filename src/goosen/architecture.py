"""Explicitly modeled architecture on real footprints. No invented measured roofs."""

import math
import numpy as np
from shapely.geometry import LineString
from shapely.geometry.polygon import orient
from shapely.ops import split

from .core import DataError
from .vectors import polygon_mesh


def modeled_gable(geom, terrain, ridge_height, origin):
    """Two roof planes on a mostly rectangular footprint; preserve exact outline.

    Only small simple footprints qualify. Complex/large buildings retain their
    unresolved volume. Orientation follows the long axis, pitch is a model.
    """
    if geom.geom_type != "Polygon" or geom.interiors or not 20 <= geom.area <= 600:
        return None
    rect = geom.minimum_rotated_rectangle
    if geom.area / rect.area < 0.82:
        return None
    corners = np.asarray(rect.exterior.coords)[:4]
    edges = np.roll(corners, -1, axis=0) - corners
    lengths = np.linalg.norm(edges, axis=1)
    direction = edges[np.argmax(lengths)] / max(lengths)
    normal = np.array([-direction[1], direction[0]])
    center = np.array([rect.centroid.x, rect.centroid.y])
    half_width = min(lengths) / 2
    if not 1.5 < half_width < 15:
        return None
    coords = list(geom.exterior.coords)
    z = terrain.sample([p[0] for p in coords], [p[1] for p in coords])
    if not np.isfinite(z).all():
        raise DataError("Modeled building has missing terrain")
    bottom = float(z.min()) - 0.25
    ridge = float(z.max()) + ridge_height
    rise = min(half_width * math.tan(math.radians(32)), 2.8, ridge_height * 0.45)

    def height(x, y):
        distance = abs(np.dot(np.array([x, y]) - center, normal))
        return ridge - rise * min(1.0, distance / half_width)

    line = LineString([center - direction * max(lengths) * 2, center + direction * max(lengths) * 2])
    pieces = split(geom, line)
    if len(pieces.geoms) != 2:
        return None
    roof = {"vertices": [], "faces": []}
    for piece in pieces.geoms:
        part = polygon_mesh(piece, height, origin)
        offset = len(roof["vertices"])
        roof["vertices"].extend(part["vertices"])
        roof["faces"].extend([[offset + i for i in face] for face in part["faces"]])
    walls = {"vertices": [], "faces": []}
    coords = list(orient(geom, sign=1).exterior.coords)
    for a, b in zip(coords, coords[1:]):
        a, b = np.asarray(a), np.asarray(b)
        da, db = np.dot(a - center, normal), np.dot(b - center, normal)
        ring = [a, b]
        if da * db < -1e-10:
            ring = [a, a + (b - a) * da / (da - db), b]
        for p, q in zip(ring, ring[1:]):
            index = len(walls["vertices"])
            walls["vertices"].extend(
                [
                    [p[0] - origin[0], p[1] - origin[1], bottom],
                    [q[0] - origin[0], q[1] - origin[1], bottom],
                    [q[0] - origin[0], q[1] - origin[1], height(*q)],
                    [p[0] - origin[0], p[1] - origin[1], height(*p)],
                ]
            )
            walls["faces"].append([index, index + 1, index + 2, index + 3])
    return {
        "walls": walls,
        "roof": roof,
        "rule": "generic_gable_32deg_capped",
        "ridge_height_m": ridge_height,
        "rise_m": rise,
        "evidence": "modeled",
    }
