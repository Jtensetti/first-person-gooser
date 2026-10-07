"""Metric RGB orthophoto tiles. Never infer RGB from arbitrary satellite bands."""

import math
import numpy as np
from PIL import Image
from rasterio.transform import from_bounds
from rasterio.warp import Resampling, reproject, transform_bounds
from rasterio.windows import Window, from_bounds as window_from_bounds
from rasterio.errors import WindowError
from .core import DataError, horizontal, sha256
from .inventory import open_raster


def orthophoto_texture(assets, bounds, path, resolution=0.5, kind="orthophoto"):
    if kind not in ("orthophoto", "satellite_rgb"):
        raise DataError("Unknown RGB imagery kind")
    if kind == "satellite_rgb" and any(
        resolution < a.get("native_resolution_m", float("inf")) for _, a in assets
    ):
        raise DataError("Satellite imagery must not be presented at a finer pixel size than its source")
    w, s, e, n = bounds
    if not math.isfinite(resolution) or resolution <= 0:
        raise DataError("Orthophoto resolution must be positive")
    width, height = math.ceil((e - w) / resolution), math.ceil((n - s) / resolution)
    if width * height > 16_777_216:
        raise DataError("Orthophoto tile exceeds texture budget")
    dest_transform = from_bounds(w, s, e, n, width, height)
    target = np.full((3, height, width), np.nan, dtype=np.float32)
    for source, record in assets:
        bands = record.get("rgb_bands")
        if (
            not isinstance(bands, list)
            or len(bands) != 3
            or len(set(bands)) != 3
            or any(not isinstance(b, int) or b < 1 for b in bands)
            or record.get("color_space") != "sRGB"
            or not record.get("observation_year")
        ):
            raise DataError("Orthophoto requires three explicit RGB bands, sRGB and observation_year")
        with open_raster(source) as src:
            if src.crs is None or not horizontal(src.crs).equals(horizontal(record["horizontal_crs"])):
                raise DataError("Orthophoto CRS disagrees with catalog")
            if max(bands) > src.count or any(src.dtypes[b - 1] != "uint8" for b in bands):
                raise DataError(
                    "Orthophoto requires display-ready uint8 RGB; normalize other radiometry explicitly"
                )
            bb = transform_bounds(3006, horizontal(src.crs), w, s, e, n, densify_pts=21)
            window = window_from_bounds(*bb, transform=src.transform)
            # Include neighbouring source pixels needed by bilinear interpolation.
            window = Window(
                math.floor(window.col_off) - 2,
                math.floor(window.row_off) - 2,
                math.ceil(window.width) + 4,
                math.ceil(window.height) + 4,
            )
            try:
                window = window.intersection(Window(0, 0, src.width, src.height))
            except WindowError:
                continue
            data = src.read(bands, window=window, masked=True).astype("float32").filled(np.nan)
            temp = np.full_like(target, np.nan)
            for band in range(3):
                reproject(
                    data[band],
                    temp[band],
                    src_transform=src.window_transform(window),
                    src_crs=horizontal(src.crs),
                    src_nodata=np.nan,
                    dst_transform=dest_transform,
                    dst_crs="EPSG:3006",
                    dst_nodata=np.nan,
                    resampling=Resampling.bilinear,
                )
            valid = np.isfinite(temp).all(axis=0) & ~np.isfinite(target).all(axis=0)
            target[:, valid] = temp[:, valid]
    missing = int((~np.isfinite(target).all(axis=0)).sum())
    if missing:
        raise DataError(f"Orthophoto has {missing} uncovered pixels; supply covering licensed imagery")
    Image.fromarray(np.rint(target).clip(0, 255).astype("uint8").transpose(1, 2, 0)).save(path)
    return {
        "kind": kind,
        "sha256": sha256(path),
        "width": width,
        "height": height,
        "pixel_m": [(e - w) / width, (n - s) / height],
        "bounds": bounds,
        "uv": "u=(E-west)/width_m; v=(N-south)/height_m; image row 0 north",
        "source_hashes": [a["sha256"] for _, a in assets],
        "observation_years": sorted({a["observation_year"] for _, a in assets}),
    }
