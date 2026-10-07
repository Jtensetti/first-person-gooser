from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from rasterio.transform import from_origin
from rasterio.warp import reproject, Resampling

from .core import DataError, horizontal
from .inventory import open_raster


@dataclass
class Grid:
    values: np.ndarray
    west: float
    north: float
    step: float

    def sample(self, x, y):
        """Bilinear node-grid interpolation. Missing data stays missing."""
        a = np.asarray(x)
        b = np.asarray(y)
        col = (a - self.west) / self.step
        row = (self.north - b) / self.step
        inside = (
            (col >= 0) & (col <= self.values.shape[1] - 1) & (row >= 0) & (row <= self.values.shape[0] - 1)
        )
        j = np.clip(np.floor(col).astype(int), 0, self.values.shape[1] - 2)
        i = np.clip(np.floor(row).astype(int), 0, self.values.shape[0] - 2)
        fx = col - j
        fy = row - i
        result = np.zeros_like(col, dtype=float)
        missing = np.zeros_like(inside)
        for value, weight in (
            (self.values[i, j], (1 - fx) * (1 - fy)),
            (self.values[i, j + 1], fx * (1 - fy)),
            (self.values[i + 1, j], (1 - fx) * fy),
            (self.values[i + 1, j + 1], fx * fy),
        ):
            active = weight > 1e-12
            missing |= active & ~np.isfinite(value)
            result += np.where(active & np.isfinite(value), value, 0) * weight
        result = np.where(missing, np.nan, result)
        return np.where(inside, result, np.nan)

    def nearest(self, x, y):
        col = np.rint((np.asarray(x) - self.west) / self.step).astype(int)
        row = np.rint((self.north - np.asarray(y)) / self.step).astype(int)
        inside = (col >= 0) & (col < self.values.shape[1]) & (row >= 0) & (row < self.values.shape[0])
        return np.where(
            inside,
            self.values[np.clip(row, 0, self.values.shape[0] - 1), np.clip(col, 0, self.values.shape[1] - 1)],
            np.nan,
        )

    def sample_mesh(self, x, y):
        """Height on the actual TL–BR triangulated terrain, not a bilinear patch."""
        col = (np.asarray(x) - self.west) / self.step
        row = (self.north - np.asarray(y)) / self.step
        inside = (col >= 0) & (col <= self.values.shape[1] - 1)
        inside &= (row >= 0) & (row <= self.values.shape[0] - 1)
        j = np.clip(np.floor(col).astype(int), 0, self.values.shape[1] - 2)
        i = np.clip(np.floor(row).astype(int), 0, self.values.shape[0] - 2)
        u, v = col - j, row - i
        a, b = self.values[i, j], self.values[i, j + 1]
        c, d = self.values[i + 1, j], self.values[i + 1, j + 1]
        z = np.where(v >= u, a * (1 - v) + c * (v - u) + d * u, a * (1 - u) + b * (u - v) + d * v)
        return np.where(inside, z, np.nan)

    def tile(self, bounds, step):
        w, s, e, n = bounds
        if step % self.step:
            raise DataError("LOD step is not a multiple of the master grid")
        i = int(round((self.north - n) / self.step))
        j = int(round((w - self.west) / self.step))
        h = int(round((n - s) / self.step))
        width = int(round((e - w) / self.step))
        stride = int(step / self.step)
        return Grid(self.values[i : i + h + 1 : stride, j : j + width + 1 : stride], w, n, step)


def warp_nodes(paths, bounds, step, kind="continuous", halo=0, band=1):
    """One global node lattice, including shared borders and halo; no per-tile warps.

    Pixel centres in the temporary raster are exactly the eventual mesh vertices.
    The -half/+half transform prevents a half-pixel geography shift.
    """
    if kind not in ("continuous", "categorical"):
        raise DataError("Unknown raster kind")
    w, s, e, n = bounds
    halo = math.ceil(halo / step) * step
    w -= halo
    s -= halo
    e += halo
    n += halo
    width = int(round((e - w) / step)) + 1
    height = int(round((n - s) / step)) + 1
    if width * height > 5_000_000:
        raise DataError("Raster job exceeds bounded memory budget")
    dst_transform = from_origin(w - step / 2, n + step / 2, step, step)
    target = np.full((height, width), np.nan, dtype=np.float32)
    for path in paths:
        with open_raster(path) as src:
            if src.crs is None:
                raise DataError(f"Undeclared raster CRS: {path}")
            temp = np.full_like(target, np.nan)
            # Read only the source window covering this AOI plus interpolation margin.
            from rasterio.warp import transform_bounds
            from rasterio.windows import from_bounds, Window

            bb = transform_bounds(
                "EPSG:3006",
                horizontal(src.crs),
                w - step * 2,
                s - step * 2,
                e + step * 2,
                n + step * 2,
                densify_pts=21,
            )
            try:
                window = from_bounds(*bb, transform=src.transform).round_offsets().round_lengths()
                window = window.intersection(Window(0, 0, src.width, src.height))
            except Exception:
                continue
            data = src.read(band, window=window, masked=True).astype("float32").filled(np.nan)
            reproject(
                data,
                temp,
                src_transform=src.window_transform(window),
                src_crs=horizontal(src.crs),
                src_nodata=np.nan,
                dst_transform=dst_transform,
                dst_crs="EPSG:3006",
                dst_nodata=np.nan,
                resampling=Resampling.nearest if kind == "categorical" else Resampling.bilinear,
            )
            conflict = np.isfinite(temp) & np.isfinite(target)
            if kind == "categorical" and np.any(temp[conflict] != target[conflict]):
                raise DataError("Conflicting overlapping categorical rasters")
            target = np.where(np.isfinite(temp) & ~np.isfinite(target), temp, target)
    return Grid(target, w, n, step)


def mesh_payload(grid, origin, z_offset=0):
    """Holes remain holes; face normals point up in Blender ENU space."""
    a = grid.values
    h, w = a.shape
    xs = grid.west + np.arange(w) * grid.step - origin[0]
    ys = grid.north - np.arange(h) * grid.step - origin[1]
    x, y = np.meshgrid(xs, ys)
    valid = np.isfinite(a)
    vertices = np.column_stack((x.ravel(), y.ravel(), np.where(valid, a - z_offset, 0).ravel()))
    cell = valid[:-1, :-1] & valid[1:, :-1] & valid[:-1, 1:] & valid[1:, 1:]
    rows, cols = np.nonzero(cell)
    tl = rows * w + cols
    tr = tl + 1
    bl = tl + w
    br = bl + 1
    # Explicit shared diagonal makes overlays and exported terrain agree exactly.
    faces = np.concatenate((np.column_stack((tl, bl, br)), np.column_stack((tl, br, tr))))
    return {"vertices": vertices.astype(float).tolist(), "faces": faces.astype(int).tolist()}
