import numpy as np
import pytest
from shapely.geometry import Polygon, box
from shapely.affinity import rotate

from goosen.architecture import modeled_gable
from goosen.core import DataError
from goosen.open_dtm import ranged_bytes
from goosen.rasters import Grid
from goosen.sentinel import cloud_check


class Response:
    def __init__(self, status, content_range, content):
        self.status_code = status
        self.headers = {"Content-Range": content_range}
        self.content = content
        self.read = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def iter_content(self, size):
        self.read = True
        yield self.content


class Client:
    def __init__(self, response):
        self.response = response

    def get(self, *args, **kwargs):
        return self.response


def test_range_rejects_full_archive_before_reading():
    response = Response(200, "", b"never read this")
    with pytest.raises(DataError, match="honor"):
        ranged_bytes(Client(response), "https://example.org", 100, 10, 500)
    assert not response.read
    with pytest.raises(DataError, match="truncated"):
        ranged_bytes(Client(Response(206, "bytes 100-109/500", b"short")), "url", 100, 10, 500)
    assert (
        ranged_bytes(Client(Response(206, "bytes 100-109/500", b"0123456789")), "url", 100, 10, 500)
        == b"0123456789"
    )


def test_cloud_mask_rejects_cloud_shadow_and_nodata():
    assert cloud_check(np.array([4, 5, 6, 7])) == {"4": 1, "5": 1, "6": 1, "7": 1}
    for code in [0, 1, 3, 8, 9, 10, 11]:
        with pytest.raises(DataError):
            cloud_check(np.array([4, code]))


def test_modeled_roof_preserves_rotated_footprint_ridge_and_labels():
    terrain = Grid(np.full((101, 101), 2.0), 0, 100, 1)
    footprint = rotate(box(30, 30, 46, 40), 27)
    model = modeled_gable(footprint, terrain, 6, [0, 0, 0])
    assert model["evidence"] == "modeled"
    mesh = model["roof"]
    areas = []
    for f in mesh["faces"]:
        p = Polygon([mesh["vertices"][i][:2] for i in f])
        assert p.difference(footprint).area < 1e-8
        areas.append(p.area)
    assert sum(areas) == pytest.approx(footprint.area)
    heights = [p[2] for p in mesh["vertices"]]
    assert max(heights) == pytest.approx(8)
    assert max(heights) - min(heights) > 2
    assert modeled_gable(box(10, 10, 60, 60), terrain, 6, [0, 0, 0]) is None
    courtyard = Polygon([(20, 20), (40, 20), (40, 40), (20, 40)], [[(25, 25), (30, 25), (30, 30), (25, 30)]])
    assert modeled_gable(courtyard, terrain, 6, [0, 0, 0]) is None
