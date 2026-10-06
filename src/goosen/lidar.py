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
    return {
        "status": "derived",
        "points": len(p),
        "support": support,
        "height_m": float(np.percentile(p[:, 2] - terrain.sample(p[:, 0], p[:, 1]), 95)),
        "roof_plane": plane,
        "roof_evidence": "derived" if plane else "unresolved",
        "note": "Single-plane fit only; pitched/hipped roofs require multi-plane reconstruction. Vegetation intrusion remains a QA risk.",
    }


def derive_canopy(points, terrain, landcover, step=2):
    ground = terrain.sample(points[:, 0], points[:, 1])
    height = points[:, 2] - ground
    code = landcover.nearest(points[:, 0], points[:, 1])
    forest = np.isin(code, [111, 112, 113, 114, 115, 116, 117, 121, 122, 123, 124, 125, 126, 127])
    valid = forest & np.isfinite(height) & (height > 2) & (height < 60) & np.isin(points[:, 3], [1, 3, 4, 5])
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
