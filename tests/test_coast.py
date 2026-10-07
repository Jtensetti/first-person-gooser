import pytest
from shapely.geometry import LineString, Point, box

from goosen.coast import parse_coast, sea_from_lines
from goosen.core import DataError


def test_eastbound_south_coast_keeps_land_left_and_sea_right():
    sea, qa = sea_from_lines([LineString([(-1, 4), (3, 4), (3, 6), (11, 6)])], [0, 0, 10, 10])
    assert sea.covers(Point(5, 2))
    assert not sea.covers(Point(5, 8))
    assert sea.area == 54
    assert qa["topology_pass"]
    assert not qa["positional_accuracy_verified"]


def test_island_is_hole_in_sea_and_independent_of_way_partition():
    # Counterclockwise land island, including two joined ways.
    coords = [(2, 2), (4, 2), (4, 4), (2, 4), (2, 2)]
    a, _ = sea_from_lines([LineString(coords)], [0, 0, 10, 10])
    b, _ = sea_from_lines([LineString(coords[2:]), LineString(coords[:3])], [0, 0, 10, 10])
    assert a.equals(b)
    assert a.equals(box(0, 0, 10, 10).difference(box(2, 2, 4, 4)))


@pytest.mark.parametrize(
    "lines",
    [
        [[(-1, 4), (4, 4)], [(4.01, 4), (11, 4)]],  # gap, never snapped closed
        [[(-1, 4), (4, 4)], [(11, 4), (4, 4)]],  # reversed second way
        [[(-1, 4), (11, 4)], [(-1, 4), (11, 4)]],  # duplicate
        [[(-1, 4), (11, 4)], [(5, -1), (5, 11)]],  # crossing
        [[(-1, 4), (4, 4)], [(4, 4), (11, 4)], [(4, 4), (11, 8)]],  # branch
        [[(2, 2), (8, 8), (2, 8), (8, 2)]],  # self-intersection
        [[(0, 0), (10, 0)]],  # coincident job boundary
        [],
    ],
)
def test_broken_or_ambiguous_coast_is_rejected(lines):
    with pytest.raises(DataError):
        sea_from_lines([LineString(p) for p in lines], [0, 0, 10, 10])


def test_overpass_error_and_missing_node_are_not_valid_coasts():
    for raw in [
        b"<osm><remark>runtime error</remark></osm>",
        b'<osm><way id="1"><nd ref="9"/><tag k="natural" v="coastline"/></way></osm>',
    ]:
        with pytest.raises(DataError):
            parse_coast(raw, [0, 0, 10, 10])
