import json

import pytest

from goosen.acquire import wfs_features, arcgis_features
from goosen.core import DataError, sha256, validate_asset
from goosen.osm import parse_osm, complete_relations


class Response:
    def __init__(self, data):
        self.data = data
        self.content = data if isinstance(data, bytes) else json.dumps(data).encode()

    def raise_for_status(self):
        pass

    def json(self):
        return self.data


class Session:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(kwargs.get("params", {}))
        return Response(next(self.responses))


def test_wfs_verifies_every_page_and_rejects_duplicates():
    hits = b'<FeatureCollection numberMatched="2"/>'
    a = {"id": "a", "geometry": {}, "properties": {}}
    b = {**a, "id": "b"}
    pages = [{"numberMatched": 2, "numberReturned": 1, "features": [f]} for f in (a, b)]
    s = Session([hits, *pages])
    assert len(wfs_features(s, "x", "layer", "year=2025", page_size=1)["features"]) == 2
    assert [c.get("startIndex") for c in s.calls[1:]] == [0, 1]
    with pytest.raises(DataError, match="repeated"):
        wfs_features(Session([hits, pages[0], pages[0]]), "x", "layer", "year=2025", page_size=1)


def test_wfs_rejects_truncation_and_changing_count():
    hits = b'<FeatureCollection numberMatched="2"/>'
    for p in [{"numberMatched": 2, "features": []}, {"numberMatched": 3, "features": []}]:
        with pytest.raises(DataError):
            wfs_features(Session([hits, p]), "x", "layer", "filter")


def test_arcgis_checks_exact_id_set_not_just_length():
    initial = {"objectIds": [4, 9], "objectIdFieldName": "OBJECTID"}
    bad = {"features": [{"attributes": {"OBJECTID": 4}}, {"attributes": {"OBJECTID": 7}}]}
    with pytest.raises(DataError, match="Incomplete"):
        arcgis_features(Session([initial, bad]), "url", [0, 0, 1, 1])


def test_asset_rejects_tampering_and_uncleared_license(tmp_path):
    p = tmp_path / "data.json"
    p.write_text("{}")
    a = {
        "path": p.name,
        "sha256": sha256(p),
        "source": "test",
        "license": "test fixture",
        "license_evidence": "synthetic",
        "use_status": "open",
        "evidence": "modeled",
    }
    assert validate_asset(a, tmp_path, "terrain") == p
    with pytest.raises(DataError, match="use is not cleared"):
        validate_asset({**a, "use_status": "review"}, tmp_path, "terrain")
    p.write_text("changed")
    with pytest.raises(DataError, match="checksum"):
        validate_asset(a, tmp_path, "terrain")


def test_osm_fetches_complete_relation_before_polygonizing():
    raw = b"""<osm><node id="1" lon="0" lat="0"/><node id="2" lon="1" lat="0"/><node id="3" lon="1" lat="1"/>
    <way id="10"><nd ref="1"/><nd ref="2"/><nd ref="3"/></way>
    <relation id="20"><member type="way" ref="10" role="outer"/><member type="way" ref="11" role="outer"/>
    <tag k="type" v="multipolygon"/><tag k="building" v="yes"/></relation></osm>"""
    full = (
        b'<osm><node id="4" lon="0" lat="1"/><way id="11"><nd ref="3"/><nd ref="4"/><nd ref="1"/></way></osm>'
    )
    with pytest.raises(DataError, match="extends"):
        parse_osm(raw)
    requests = []

    def fetch(rid):
        requests.append(rid)
        return full

    result = parse_osm(complete_relations(raw, fetch))
    assert requests == ["20"]
    assert len(result["buildings"]["features"]) == 1
