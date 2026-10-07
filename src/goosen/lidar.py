"""Bounded local LAZ/COPC processing. Raw points never enter the Blender scene."""

from __future__ import annotations


import laspy
import numpy as np
from shapely import contains_xy

from .core import DataError, horizontal


def load_points(path, bounds, max_points=5_000_000):
    w, s, e, n = bounds
    with laspy.open(path) as reader:
        crs = reader.header.parse_crs()
        if crs is None or horizontal(crs).to_epsg() != 3006:
            raise DataError("LiDAR must declare SWEREF99 TM; reproject explicitly before ingestion")
        chunks = []
        count = 0
        for p in reader.chunk_iterator(1_000_000):
            valid = (p.x >= w) & (p.x <= e) & (p.y >= s) & (p.y <= n)
            valid &= ~np.asarray(p.withheld, dtype=bool)
            valid &= ~np.isin(p.classification, [7, 18])
            count += np.count_nonzero(valid)
            if count > max_points:
                raise DataError("LiDAR pilot point budget exceeded")
            if np.any(valid):
                chunks.append(
                    np.column_stack(
                        [
                            np.asarray(p.x)[valid],
                            np.asarray(p.y)[valid],
                            np.asarray(p.z)[valid],
                            np.asarray(p.classification)[valid],
                        ]
                    )
                )
    return np.concatenate(chunks) if chunks else np.empty((0, 4))


def fit_gable(geometry, p):
    """Robust two-plane hypothesis, validated on held-out laser returns.

    Footprint constrains orientation only. Ridge offset, pitch and elevation
    come from returns. Complex roofs/trees must fail rather than become a gable.
    """
    from scipy.optimize import least_squares

    if geometry.geom_type != "Polygon" or geometry.interiors or len(p) < 30:
        return None
    rect = geometry.minimum_rotated_rectangle
    if geometry.area / rect.area < 0.78:
        return None
    corners = np.asarray(rect.exterior.coords)[:4]
    edges = np.roll(corners, -1, axis=0) - corners
    center = np.array([rect.centroid.x, rect.centroid.y])
    candidates = []
    for edge in edges[:2]:
        along = edge / np.linalg.norm(edge)
        across = np.array([-along[1], along[0]])
        uv = (p[:, :2] - center) @ np.column_stack([along, across])
        width = np.ptp((corners - center) @ across)
        if not 3 < width < 40:
            continue
        train = np.arange(len(p)) % 5 != 0
        z0 = np.median(p[:, 2])

        def design(params, values):
            a, b, c, pitch, shift = params
            return a * values[:, 0] + b * values[:, 1] + c - pitch * np.abs(values[:, 1] - shift)

        fit = least_squares(
            lambda q: design(q, uv[train]) - (p[train, 2] - z0),
            [0, 0, 1, 0.5, 0],
            loss="soft_l1",
            f_scale=0.15,
            bounds=([-0.12, -0.3, -15, 0.15, -width * 0.2], [0.12, 0.3, 15, 1.3, width * 0.2]),
            max_nfev=120,
        )
        a, b, c, pitch, shift = fit.x
        residual = np.abs(design(fit.x, uv) + z0 - p[:, 2])
        inliers = residual < 0.35
        sides = uv[:, 1] > shift
        rmse = float(np.sqrt(np.mean(residual[inliers] ** 2)))
        if (
            not fit.success
            or inliers.mean() < 0.85
            or (residual[~train] < 0.35).mean() < 0.8
            or rmse > 0.20
            or min(pitch - b, pitch + b) < 0.12
        ):
            continue
        if any(np.count_nonzero(inliers & (sides == side)) < 10 for side in [True, False]):
            continue
        # Both slopes must have evidence near ridge and toward the eaves.
        v = uv[inliers, 1]
        if np.ptp(v) < width * 0.65 or min(np.abs(v - shift)) > 0.8:
            continue
        planes = []
        for sign in [-1, 1]:
            gradient = a * along + (b + sign * pitch) * across
            planes.append([*gradient.tolist(), float(c + z0 - sign * pitch * shift), *center.tolist()])
        candidates.append(
            {
                "planes": planes,
                "ridge_point": (center + shift * across).tolist(),
                "ridge_direction": along.tolist(),
                "rule": "lidar_two_plane_gable",
                "evidence": "derived",
                "inlier_fraction": float(inliers.mean()),
                "heldout_fraction": float((residual[~train] < 0.35).mean()),
                "rmse_m": rmse,
                "points": len(p),
            }
        )
    return min(candidates, key=lambda q: q["rmse_m"]) if candidates else None


def derive_building(geometry, points, terrain):
    # Classification 1 is not automatically building: enforce footprint interior,
    # normalized height and spatial support. No fit -> no purported roof geometry.
    interior = geometry.buffer(-0.6)
    use = contains_xy(interior, points[:, 0], points[:, 1]) & np.isin(points[:, 3], [1, 6])
    p = points[use]
    ground = terrain.sample(p[:, 0], p[:, 1])
    h = p[:, 2] - ground
    p = p[np.isfinite(h) & (h > 2) & (h < 80)]
    if len(p) < 12:
        return {"status": "insufficient_points", "points": len(p)}
    covered = len(set(zip(np.floor(p[:, 0] / 2).astype(int), np.floor(p[:, 1] / 2).astype(int)))) * 4
    support = min(1.0, covered / max(geometry.area, 1))
    if support < 0.4:
        return {"status": "insufficient_spatial_support", "points": len(p), "support": support}
    centre = p[:, :2].mean(axis=0)
    a = np.column_stack([p[:, 0] - centre[0], p[:, 1] - centre[1], np.ones(len(p))])
    fit = np.linalg.lstsq(a, p[:, 2], rcond=None)[0]
    residual = np.abs(a @ fit - p[:, 2])
    inliers = residual < 0.4
    plane = None
    if inliers.mean() > 0.8 and inliers.sum() >= 12:
        fit = np.linalg.lstsq(a[inliers], p[inliers, 2], rcond=None)[0]
        rmse = float(np.sqrt(np.mean((a[inliers] @ fit - p[inliers, 2]) ** 2)))
        if rmse < 0.25 and np.hypot(*fit[:2]) < 1.5:
            plane = [*fit.tolist(), *centre.tolist()]
    gable = fit_gable(geometry, p) if plane is None else None
    return {
        "status": "derived",
        "points": len(p),
        "support": support,
        "height_m": float(np.percentile(p[:, 2] - terrain.sample(p[:, 0], p[:, 1]), 95)),
        "roof_plane": plane,
        "roof_evidence": "derived" if plane or gable else "unresolved",
        "roof_model": gable,
        "note": "Single or validated two-plane fit; complex roofs remain unresolved. Vegetation intrusion remains a QA risk.",
    }


def derive_canopy(points, terrain, landcover, step=2, exclusion=None):
    ground = terrain.sample(points[:, 0], points[:, 1])
    height = points[:, 2] - ground
    code = landcover.nearest(points[:, 0], points[:, 1])
    forest = np.isin(code, [111, 112, 113, 114, 115, 116, 117, 121, 122, 123, 124, 125, 126, 127])
    valid = forest & np.isfinite(height) & (height > 2) & (height < 60) & np.isin(points[:, 3], [1, 3, 4, 5])
    if exclusion is not None and not exclusion.is_empty:
        valid &= ~contains_xy(exclusion, points[:, 0], points[:, 1])
    p = points[valid]
    h = height[valid]
    # Heights are estimates from returns, not surveyed tree identities.
    if not len(p):
        return []
    cells = {}
    for row, hh in zip(p, h):
        key = (int(row[0] // step), int(row[1] // step))
        if key not in cells or hh > cells[key][2]:
            cells[key] = (float(row[0]), float(row[1]), float(hh))
    return [{"x": v[0], "y": v[1], "height_m": v[2], "evidence": "derived"} for _, v in sorted(cells.items())]


def canopy_peaks(points, terrain, exclusion, bounds):
    """Canopy candidates beyond coarse NMD forest; no claimed individual tree census.

    Require vertical spread and neighbouring occupied cells, then suppress nearby
    peaks. Roofs, roads, water and cultivated field polygons are excluded by caller.
    """
    from scipy.spatial import cKDTree

    h = points[:, 2] - terrain.sample(points[:, 0], points[:, 1])
    valid = np.isfinite(h) & (h > 2.5) & (h < 35) & np.isin(points[:, 3], [1, 3, 4, 5])
    p, h = points[valid], h[valid]
    if not exclusion.is_empty:
        valid = ~contains_xy(exclusion, p[:, 0], p[:, 1])
        p, h = p[valid], h[valid]
    cells = {}
    for xy, height in zip(p[:, :2], h):
        key = tuple(np.floor(xy / 2).astype(int))
        cells.setdefault(key, []).append(float(height))
    candidates = []
    for (ix, iy), values in sorted(cells.items()):
        if len(values) >= 3 and max(values) - min(values) >= 0.7:
            x, y = ix * 2 + 1, iy * 2 + 1
            if bounds[0] <= x < bounds[2] and bounds[1] <= y < bounds[3]:
                candidates.append([x, y, float(np.percentile(values, 95))])
    if not candidates:
        return []
    a = np.asarray(candidates)
    tree = cKDTree(a[:, :2])
    removed = set()
    result = []
    for i in sorted(range(len(a)), key=lambda i: (-a[i, 2], a[i, 0], a[i, 1])):
        if i in removed or len(tree.query_ball_point(a[i, :2], 4.5)) < 3:
            continue
        x, y, height = a[i]
        result.append({"x": float(x), "y": float(y), "height_m": float(height)})
        removed.update(tree.query_ball_point(a[i, :2], max(3.5, height * 0.28)))
    return result
