"""Retrieve a hash-pinned open Swedish DTM member, never its entire 397 GB archive."""

import hashlib
import os
import tarfile
import tempfile
from pathlib import Path

import rasterio
from pyproj import CRS
from shapely.geometry import box

from .acquire import receipt, session
from .core import DataError, read_json, write_json


def ranged_bytes(client, url, start, size, total):
    if start < 0 or not 0 < size <= 20_000_000 or start + size > total:
        raise DataError("Invalid or excessive archive range")
    end = start + size - 1
    with client.get(
        url,
        headers={"Range": f"bytes={start}-{end}", "Accept-Encoding": "identity"},
        stream=True,
        timeout=(10, 40),
    ) as response:
        if (
            response.status_code != 206
            or response.headers.get("Content-Range") != f"bytes {start}-{end}/{total}"
        ):
            # Check headers BEFORE reading; a 200 response may be 397 GB.
            raise DataError("Server did not honor the exact bounded range")
        chunks, count = [], 0
        for chunk in response.iter_content(65536):
            count += len(chunk)
            if count > size:
                raise DataError("Archive range exceeds declared size")
            chunks.append(chunk)
        if count != size:
            raise DataError("Archive range truncated")
        return b"".join(chunks)


def fetch_open_dtm(c, config_path, output):
    config = read_json(config_path)
    url = config["source"]
    if url != "https://download.mapterhorn.com/sources/se.tar" or config.get("license") != "CC0-1.0":
        raise DataError("Unreviewed open DTM archive")
    output = Path(output).resolve()
    if output.exists():
        raise DataError("DTM output exists; choose a fresh directory")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".open-dtm-", dir=output.parent) as tmp:
        stage = Path(tmp) / "dtm"
        stage.mkdir()
        with session() as client:
            for member in config["members"]:
                offset = member["header_offset"]
                header = ranged_bytes(client, url, offset, 512, config["archive_bytes"])
                info = tarfile.TarInfo.frombuf(header, "utf-8", "strict")
                if not info.isfile() or info.name != member["name"] or info.size != member["bytes"]:
                    raise DataError("Archive member moved or changed; review a fresh source manifest")
                data = ranged_bytes(client, url, offset + 512, info.size, config["archive_bytes"])
                if hashlib.sha256(data).hexdigest() != member["sha256"]:
                    raise DataError("Open DTM member checksum mismatch")
                (stage / Path(info.name).name).write_bytes(data)
        metadata = read_json(stage / "metadata.json")
        if metadata.get("license") != "CC0" or metadata.get("producer") != "Lantmäteriet":
            raise DataError("Archive provenance no longer matches reviewed source")
        files = list(stage.glob("*.tif"))
        if len(files) != 1:
            raise DataError("Pilot importer expects one covering DTM")
        path = files[0]
        with rasterio.open(path) as ds:
            if not CRS(ds.crs).equals(CRS(5845)) or ds.res != (1.0, 1.0) or ds.count != 1:
                raise DataError("Expected 1 m SWEREF99 TM + RH2000 DTM")
            w, s, e, n = c["bounds"]
            h = c["halo_m"]
            if not box(*ds.bounds).covers(box(w - h, s - h, e + h, n + h)):
                raise DataError("DTM does not cover job plus halo")
        common = dict(
            use_status="open",
            redistribution_status="CC0",
            evidence="derived",
            archive_source=config,
            source_access_year=metadata.get("access_year"),
        )
        record = receipt(
            path,
            url,
            "CC0-1.0",
            config["license_evidence"],
            horizontal_crs="EPSG:3006",
            vertical_crs="EPSG:5613",
            native_resolution_m=1,
            surface_kind="DTM",
            note="Lantmateriet via Mapterhorn source archive. Native 1 m grid; LERC conversion max Z error 0.001 m. Survey date unverified; access year is not observation year.",
            **common,
        )
        supporting = [
            receipt(stage / name, url, "CC0-1.0", config["license_evidence"], **common)
            for name in ("LICENSE.pdf", "metadata.json")
        ]
        assets = {"terrain": [record], "terrain_source": supporting}
        write_json(stage / "assets.json", assets)
        os.replace(stage, output)
    return assets
