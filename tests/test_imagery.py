import numpy as np
import pytest
import rasterio
from PIL import Image
from rasterio.transform import from_origin
from goosen.core import DataError, sha256
from goosen.imagery import orthophoto_texture


def fixture(tmp_path, nodata=None):
    p = tmp_path / "rgb.tif"
    a = np.zeros((3, 4, 4), dtype="uint8")
    a[0, :2] = 255  # north red
    a[2, 2:] = 255  # south blue
    with rasterio.open(
        p,
        "w",
        driver="GTiff",
        width=4,
        height=4,
        count=3,
        dtype="uint8",
        crs="EPSG:3006",
        transform=from_origin(395500, 6133504, 1, 1),
        nodata=nodata,
    ) as ds:
        ds.write(a)
    record = {
        "rgb_bands": [1, 2, 3],
        "color_space": "sRGB",
        "observation_year": 2025,
        "horizontal_crs": "EPSG:3006",
        "sha256": sha256(p),
    }
    return p, record


def test_image_orientation_pixel_centres_and_seams(tmp_path):
    asset = fixture(tmp_path)
    bounds = [395500, 6133500, 395504, 6133504]
    info = orthophoto_texture([asset], bounds, tmp_path / "full.png", 1)
    rgb = np.asarray(Image.open(tmp_path / "full.png"))
    assert rgb[0, 0].tolist() == [255, 0, 0]
    assert rgb[-1, 0].tolist() == [0, 0, 255]
    assert info["pixel_m"] == [1, 1]
    orthophoto_texture([asset], [395500, 6133500, 395502, 6133504], tmp_path / "west.png", 1)
    orthophoto_texture([asset], [395502, 6133500, 395504, 6133504], tmp_path / "east.png", 1)
    assert np.array_equal(
        np.concatenate([np.asarray(Image.open(tmp_path / n)) for n in ["west.png", "east.png"]], axis=1), rgb
    )


def test_coverage_and_band_semantics_are_not_guessed(tmp_path):
    p, a = fixture(tmp_path)
    with pytest.raises(DataError, match="uncovered"):
        orthophoto_texture([(p, a)], [395500, 6133500, 395506, 6133504], tmp_path / "bad.png", 1)
    with pytest.raises(DataError, match="explicit RGB"):
        orthophoto_texture(
            [(p, {**a, "rgb_bands": [1, 1, 1]})], [395500, 6133500, 395504, 6133504], tmp_path / "bad.png", 1
        )
    with pytest.raises(DataError, match="CRS"):
        orthophoto_texture(
            [(p, {**a, "horizontal_crs": "EPSG:3008"})],
            [395500, 6133500, 395504, 6133504],
            tmp_path / "bad.png",
            1,
        )
