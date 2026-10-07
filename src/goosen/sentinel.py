"""Small public Sentinel-2 true-colour extract; 10 m satellite, never aerial ortho."""

import math
import os
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import numpy as np
import rasterio
from rasterio.warp import transform_bounds
from rasterio.windows import Window, from_bounds

from .acquire import get_json, receipt, session
from .core import DataError, write_json

LICENSE = "https://registry.opendata.aws/sentinel-2-l2a-cogs/"
ITEM_BASE = "https://earth-search.aws.element84.com/v1/collections/sentinel-2-l2a/items/"


def read_crop(href, bounds):
    if (
        urlparse(href).scheme != "https"
        or urlparse(href).hostname != "sentinel-cogs.s3.us-west-2.amazonaws.com"
    ):
        raise DataError("Unreviewed Sentinel COG host")
    with rasterio.Env(
        GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
        CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif",
        GDAL_HTTP_TIMEOUT=30,
    ):
        with rasterio.open(href) as src:
            bb = transform_bounds(3006, src.crs, *bounds, densify_pts=21)
            window = from_bounds(*bb, transform=src.transform)
            window = Window(
                math.floor(window.col_off) - 3,
                math.floor(window.row_off) - 3,
                math.ceil(window.width) + 6,
                math.ceil(window.height) + 6,
            )
            if window.width * window.height > 1_000_000 or window.col_off < 0 or window.row_off < 0:
                raise DataError("Sentinel extract outside bounded pixel budget")
            if window.col_off + window.width > src.width or window.row_off + window.height > src.height:
                raise DataError("Sentinel scene does not cover pilot")
            data = src.read(window=window, masked=True)
            if np.ma.getmaskarray(data).any():
                raise DataError("Sentinel pilot has no-data pixels")
            profile = dict(
                driver="GTiff",
                width=int(window.width),
                height=int(window.height),
                count=src.count,
                dtype=src.dtypes[0],
                crs=src.crs,
                transform=src.window_transform(window),
                compress="deflate",
            )
            return data.data, profile


def cloud_check(scl):
    # Reject missing, saturated, shadow, medium/high cloud, cirrus and snow.
    if not np.isin(scl, [2, 4, 5, 6, 7]).all():
        raise DataError("Sentinel extract includes cloud/shadow/snow/invalid pixels; choose another scene")
    return {str(int(k)): int(v) for k, v in zip(*np.unique(scl, return_counts=True))}


def fetch_sentinel(c, item_id, output):
    if not item_id.replace("_", "").isalnum():
        raise DataError("Invalid STAC item id")
    url = ITEM_BASE + item_id
    output = Path(output).resolve()
    if output.exists():
        raise DataError("Sentinel output exists; choose a fresh directory")
    with session() as client:
        item = get_json(client, url)
    if item.get("id") != item_id:
        raise DataError("Unexpected STAC item")
    w, s, e, n = c["bounds"]
    h = c["halo_m"]
    bounds = [w - h, s - h, e + h, n + h]
    scl, scl_profile = read_crop(item["assets"]["scl"]["href"], bounds)
    quality = cloud_check(scl)
    rgb, profile = read_crop(item["assets"]["visual"]["href"], bounds)
    if rgb.shape[0] != 3 or rgb.dtype != np.uint8 or abs(profile["transform"].a) != 10:
        raise DataError("Expected native 10 m display-ready Sentinel RGB")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".sentinel-", dir=output.parent) as tmp:
        stage = Path(tmp) / "sentinel"
        stage.mkdir()
        for name, data, spec in [("rgb.tif", rgb, profile), ("scl.tif", scl, scl_profile)]:
            with rasterio.open(stage / name, "w", **spec) as dst:
                dst.write(data)
        write_json(stage / "item.json", item)
        common = dict(
            use_status="open",
            redistribution_status="Copernicus Sentinel terms",
            evidence="derived",
            attribution=f"Contains modified Copernicus Sentinel data ({item['properties']['datetime'][:4]}), processed by ESA/Element 84.",
            observation_year=int(item["properties"]["datetime"][:4]),
            observation_datetime=item["properties"]["datetime"],
        )
        rgb_record = receipt(
            stage / "rgb.tif",
            item["assets"]["visual"]["href"],
            "Copernicus Sentinel open data",
            LICENSE,
            horizontal_crs=profile["crs"].to_string(),
            native_resolution_m=10,
            color_space="sRGB",
            rgb_bands=[1, 2, 3],
            imagery_kind="satellite_rgb",
            local_scl_counts=quality,
            note="TCI 10 m, not high-resolution aerial imagery. SCL is 20 m; class 7 is unclassified.",
            **common,
        )
        sources = [
            receipt(stage / "item.json", url, "Copernicus Sentinel open data", LICENSE, **common),
            receipt(
                stage / "scl.tif",
                item["assets"]["scl"]["href"],
                "Copernicus Sentinel open data",
                LICENSE,
                horizontal_crs=scl_profile["crs"].to_string(),
                native_resolution_m=20,
                **common,
            ),
        ]
        assets = {"satellite_rgb": [rgb_record], "satellite_source": sources}
        write_json(stage / "assets.json", assets)
        os.replace(stage, output)
    return assets
