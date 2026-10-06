"""Optional authenticated Earth Engine exports; semantic inputs, never terrain height.

Adapted to metric pilot tiles from the existing NBS bake pattern. No 30 m upsampling
of AlphaEarth; no per-pixel embeddings or PCA exposed to the flight experience.
"""

import argparse
import os
from pathlib import Path

import rasterio

from goosen.acquire import receipt, session
from goosen.core import DataError, load_config, tiles, write_json

AE = "GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL"
S2 = "COPERNICUS/S2_SR_HARMONIZED"


def main():
    import ee

    p = argparse.ArgumentParser()
    p.add_argument("--config", default="configs/pilot.json")
    p.add_argument("--product", choices=["alphaearth", "ndvi", "sentinel-rgb"], required=True)
    p.add_argument("--year", type=int, required=True)
    p.add_argument("--project", default=os.environ.get("EE_PROJECT"))
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    if not a.project:
        raise DataError("Set EE_PROJECT to your authorized project and authenticate Earth Engine first")
    if a.output.exists():
        raise DataError("Choose a fresh output directory to freeze each acquisition")
    c = load_config(a.config)
    ee.Initialize(project=a.project)
    region = ee.Geometry.Rectangle(c["bounds"], proj="EPSG:3006", geodesic=False)
    if a.product == "alphaearth":
        collection = (
            ee.ImageCollection(AE).filterDate(f"{a.year}-01-01", f"{a.year + 1}-01-01").filterBounds(region)
        )
        if collection.size().getInfo() == 0:
            raise DataError("No AlphaEarth coverage for this year and AOI; no year substitution")
        image = collection.mosaic().select([f"A{i:02d}" for i in range(64)])
        count, source, license_name = 64, AE, "CC-BY-4.0"
        evidence_url = (
            "https://developers.google.com/earth-engine/datasets/catalog/GOOGLE_SATELLITE_EMBEDDING_V1_ANNUAL"
        )
    else:
        collection = (
            ee.ImageCollection(S2)
            .filterDate(f"{a.year}-06-01", f"{a.year}-08-01")
            .filterBounds(region)
            .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 60))
        )
        if collection.size().getInfo() == 0:
            raise DataError("No Sentinel-2 acquisitions in selected season")

        def clear(img):
            scl = img.select("SCL")
            mask = scl.remap([4, 5, 6], [1, 1, 1], 0).eq(1)
            return img.updateMask(mask).select(["B2", "B3", "B4", "B8"]).multiply(0.0001)

        image = collection.map(clear).median()
        image = (
            image.normalizedDifference(["B8", "B4"]).rename("NDVI")
            if a.product == "ndvi"
            else image.select(["B4", "B3", "B2"])
        )
        count, source, license_name = (
            (1 if a.product == "ndvi" else 3),
            S2,
            "Copernicus Sentinel open-data terms",
        )
        evidence_url = (
            "https://dataspace.copernicus.eu/data-collections/copernicus-sentinel-missions/sentinel-2"
        )
    a.output.mkdir(parents=True)
    records = []
    with session() as s:
        for tile in tiles(c):
            geom = ee.Geometry.Rectangle(tile["bounds"], proj="EPSG:3006", geodesic=False)
            url = (
                image.toFloat()
                .unmask(-32768)
                .clip(geom)
                .getDownloadURL(
                    {
                        "region": geom,
                        "scale": 10,
                        "crs": "EPSG:3006",
                        "format": "GEO_TIFF",
                        "filePerBand": False,
                    }
                )
            )
            response = s.get(url, timeout=(15, 120))
            response.raise_for_status()
            if len(response.content) > 32 * 1024 * 1024:
                raise DataError("Earth Engine export exceeds pilot budget")
            path = a.output / (tile["id"] + ".tif")
            path.write_bytes(response.content)
            with rasterio.open(path, "r+") as raster:
                if raster.count != count or raster.crs.to_epsg() != 3006:
                    raise DataError("Unexpected Earth Engine band count or CRS")
                raster.nodata = -32768
            records.append(
                receipt(
                    path,
                    source,
                    license_name,
                    evidence_url,
                    evidence="derived",
                    use_status="open",
                    horizontal_crs="EPSG:3006",
                    observation_year=a.year,
                    resolution_m=10,
                    units="embedding axes"
                    if count == 64
                    else "NDVI"
                    if count == 1
                    else "surface reflectance",
                    note="Semantic/seasonal input only; never an object-height source. Satellite RGB is not orthophotography.",
                )
            )
    write_json(
        a.output / "catalog.json",
        {
            "schema": 1,
            "product": a.product,
            "assets": records,
            "alphaearth_attribution": "The AlphaEarth Foundations Satellite Embedding dataset is produced by Google and Google DeepMind."
            if count == 64
            else None,
        },
    )


if __name__ == "__main__":
    main()
