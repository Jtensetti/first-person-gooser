"""Prepare renderer-neutral, local-metre tile packages from a frozen input catalog."""

from __future__ import annotations

import gzip
import json
import math
import os
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image
from rasterio.features import shapes
from rasterio.transform import from_origin
from shapely.geometry import Point, box, shape
from shapely.ops import unary_union

from .core import DataError, read_json, sha256, stable_seed, tiles, validate_asset, write_json
from .rasters import warp_nodes, mesh_payload
from .vectors import read_features, polygon_mesh, building_mesh, drape_mesh, clip_terrain_water
from .lidar import load_points, derive_building, derive_canopy
from .imagery import orthophoto_texture

FOREST_CODES = [111, 112, 113, 114, 115, 116, 117, 121, 122, 123, 124, 125, 126, 127]
# Artistic seasonal defaults, never measurements or claimed farm observations.
CROP_HEIGHTS = {
    "wheat": 0.9,
    "barley": 0.8,
    "rapeseed": 1.25,
    "maize": 1.8,
    "grass": 0.35,
    "sugar_beet": 0.45,
    "potato": 0.6,
    "flower_mix": 0.6,
}


def archive_json(path, obj):
    data = json.dumps(obj, separators=(",", ":"), allow_nan=False).encode()
    with Path(path).open("wb") as f:
        with gzip.GzipFile(filename="", fileobj=f, mode="wb", mtime=0) as z:
            z.write(data)


def load_catalog(path):
    catalog = read_json(path)
    root = Path(path).parent
    if catalog.get("schema") != 1:
        raise DataError("Unknown catalog schema")
    assets = {}
    for role, items in catalog["assets"].items():
        if not isinstance(items, list):
            raise DataError("Catalog role must contain a list")
        assets[role] = [(validate_asset(a, root, role), a) for a in items]
    return catalog, assets


def category(code):
    if code in FOREST_CODES:
        return "forest"
    if code in (61, 62):
        return "water"
    if code == 3:
        return "field"
    if code in (51, 52, 53, 54):
        return "built"
    if code == 411:
        return "bare"
    return "grass"


def natural_texture(grid, path):
    # Natural base colours for technical preview only. No fake aerial imagery.
    palette = {
        "forest": (38, 65, 28),
        "water": (22, 52, 61),
        "field": (122, 128, 66),
        "built": (105, 101, 89),
        "bare": (159, 144, 109),
        "grass": (79, 108, 48),
    }
    a = grid.values
    rgb = np.full((*a.shape, 3), (100, 92, 78), dtype=np.uint8)
    for v in np.unique(a[np.isfinite(a)]):
        rgb[a == v] = palette[category(int(v))]
    Image.fromarray(rgb).save(path)


def water_from_nmd(grid, bounds):
    # Explicit low-resolution proxy. Native vector coast is required for acceptance.
    mask = np.isin(grid.values, [61, 62]).astype("uint8")
    transform = from_origin(grid.west - grid.step / 2, grid.north + grid.step / 2, grid.step, grid.step)
    geoms = [
        shape(g).intersection(box(*bounds))
        for g, v in shapes(mask, mask=mask == 1, transform=transform)
        if v == 1
    ]
    return unary_union(geoms)


def scatter(
    geom, grid, spacing, seed, origin, kind, height, exclusion=None, limit=15000, height_sampler=None
):
    if geom.is_empty or limit <= 0:
        return []
    w, s, e, n = geom.bounds
    if ((e - w) / spacing + 1) * ((n - s) / spacing + 1) > 2_000_000:
        raise DataError("Instance candidate budget exceeded")
    # Global lattice + per-cell hash: neighbouring tiles and different clipping
    # order produce identical positions, not doubled/reseeded seams.
    result = []
    for iy in range(math.floor(s / spacing), math.ceil(n / spacing)):
        for ix in range(math.floor(w / spacing), math.ceil(e / spacing)):
            rng = np.random.default_rng(stable_seed(seed, kind, ix, iy))
            x = (ix + 0.2 + 0.6 * rng.random()) * spacing
            y = (iy + 0.2 + 0.6 * rng.random()) * spacing
            if not geom.contains(Point(x, y)) or exclusion is not None and exclusion.covers(Point(x, y)):
                continue
            z = float(grid.sample(x, y))
            if not math.isfinite(z):
                continue
            estimated_height = height_sampler(x, y) if height_sampler else None
            result.append(
                {
                    "asset": kind,
                    "position": [x - origin[0], y - origin[1], z],
                    "yaw": float(rng.uniform(0, 2 * math.pi)),
                    "height_m": float(
                        estimated_height
                        if estimated_height is not None
                        else height * (0.85 + 0.3 * rng.random())
                    ),
                    "height_evidence": "derived" if estimated_height is not None else "modeled",
                    "position_evidence": "modeled",
                    "evidence": "modeled",
                }
            )
            if len(result) >= limit:
                return result
    return result


def _prepare(c, catalog_path, output, preview):
    catalog, assets = load_catalog(catalog_path)
    if not assets.get("terrain"):
        raise DataError("A terrain raster is required; use explicit preview bootstrap or supply LM DTM")
    if not assets.get("landcover"):
        raise DataError("NMD landcover is required")
    gaps = []
    vertical = {a.get("vertical_crs") for _, a in assets["terrain"]}
    if len(vertical) != 1 or None in vertical:
        raise DataError("Terrain vertical datum is ambiguous")
    vertical = next(iter(vertical))
    if vertical != "EPSG:5613":
        if not preview:
            raise DataError(
                "Production requires RH2000. Horizontal reprojection cannot convert vertical datums"
            )
        gaps.append("Terrain is a preview surface in " + vertical + "; not an RH2000 bare-earth DTM")
    if any(
        a.get("native_resolution_m", 999) > 2 or a.get("surface_kind") != "DTM" for _, a in assets["terrain"]
    ):
        if not preview:
            raise DataError("Production requires a declared bare-earth DTM at <=2 m native resolution")
        gaps.append("Coarse surface model: no claims about ditches, embankments or surveyed terrain")
    terrain = warp_nodes(
        [p for p, a in assets["terrain"]], c["bounds"], c["terrain_step_m"], halo=c["halo_m"]
    )
    land = warp_nodes([p for p, a in assets["landcover"]], c["bounds"], 10, "categorical", halo=c["halo_m"])
    vectors = {}
    for role in ("buildings", "fields", "roads", "water"):
        vectors[role] = [f for p, a in assets.get(role, []) for f in read_features(p, a["horizontal_crs"])]
        if not vectors[role]:
            gaps.append("Missing " + role)
    # One authoritative source per role prevents silent double counting.
    for role in ("buildings", "fields", "roads", "water"):
        if len(assets.get(role, [])) > 1:
            raise DataError(f"{role}: merge and deduplicate sources explicitly before building")
    crop_map = catalog.get("crop_map", {})
    if crop_map and (crop_map.get("year") != c["crop_year"] or not crop_map.get("source")):
        raise DataError("Crop codebook must have the same year as parcel data and a source")
    for f in vectors["fields"]:
        if f["properties"].get("arslager") != c["crop_year"]:
            raise DataError("Mixed parcel years")
    if not assets.get("orthophoto"):
        gaps.append("No licensed orthophoto; procedural base materials only")
    points = None
    if assets.get("lidar"):
        if vertical != "EPSG:5613" or any(a.get("vertical_crs") != "EPSG:5613" for _, a in assets["lidar"]):
            raise DataError("LiDAR and terrain must both be RH2000; no implicit Z transform")
        points = np.concatenate([load_points(p, c["bounds"]) for p, a in assets["lidar"]])
    else:
        gaps.append("No LiDAR or approved municipal 3D model; building heights unresolved where absent")
    # Cells on the terrain lattice, not nodata treated as zero.
    core = terrain.tile(c["bounds"], c["terrain_step_m"])
    gx, gy = np.meshgrid(
        np.linspace(c["bounds"][0], c["bounds"][2], core.values.shape[1]),
        np.linspace(c["bounds"][3], c["bounds"][1], core.values.shape[0]),
    )
    land_codes = land.nearest(gx, gy)
    invalid_land = int(np.count_nonzero(~np.isfinite(core.values) & ~np.isin(land_codes, [61, 62])))
    if invalid_land:
        raise DataError(f"{invalid_land} land terrain nodes missing; supply covering data")
    if not np.isfinite(land_codes).all():
        raise DataError("NMD does not cover the full job")
    water = unary_union([f["geometry"] for f in vectors["water"]])
    if not water.is_empty:
        for f in vectors["water"]:
            if f["geometry"].geom_type not in ("Polygon", "MultiPolygon"):
                raise DataError("Water requires polygons, not an unclosed coast line")
    if water.is_empty or preview:
        # Supplement inland OSM polygons with explicitly coarse NMD sea in preview.
        if preview:
            water = unary_union([water, water_from_nmd(land, c["bounds"])])
            gaps.append("Water boundary includes a 10 m NMD proxy")
    water_surfaces = []
    for f in vectors["water"]:
        level = f["properties"].get("water_level_m")
        if level is not None:
            if f["properties"].get("vertical_crs") != vertical:
                raise DataError("Water and terrain vertical references disagree")
        elif not preview:
            raise DataError("Water polygon requires an evidenced water_level_m in the terrain datum")
        else:
            boundary = f["geometry"].boundary
            samples = [boundary.interpolate(i / 20, normalized=True) for i in range(21)]
            z = terrain.sample([p.x for p in samples], [p.y for p in samples])
            if not np.isfinite(z).any():
                raise DataError("Cannot model inland water level without terrain samples")
            level = float(np.nanpercentile(z, 10))
        water_surfaces.append(
            (
                f["id"],
                f["geometry"],
                float(level),
                "derived" if f["properties"].get("water_level_m") is not None else "modeled",
            )
        )
    if preview:
        proxy = water_from_nmd(land, c["bounds"]).difference(
            unary_union([f["geometry"] for f in vectors["water"]])
        )
        water_surfaces.append(("nmd-proxy", proxy, 0.0, "modeled"))
    roads = []
    skipped_roads = 0
    for f in vectors["roads"]:
        props = f["properties"]
        if props.get("bridge") not in (None, "no", False) or props.get("tunnel") not in (None, "no", False):
            skipped_roads += 1
            continue
        width = props.get("width_m")
        if width is None:
            if not preview:
                raise DataError("Road width missing; supply width evidence or explicit reviewed model")
            width = c["default_road_width_m"]
        if not 0 < float(width) < 100:
            raise DataError("Road width outside range")
        geom = f["geometry"]
        surface = (
            geom
            if geom.geom_type in ("Polygon", "MultiPolygon")
            else geom.buffer(float(width) / 2, cap_style=2, join_style=2)
        )
        roads.append({**f, "geometry": surface, "modeled_width": props.get("width_m") is None})
    if skipped_roads:
        gaps.append(f"{skipped_roads} bridge/tunnel features skipped; deck/underground heights required")
    buildings = []
    for f in vectors["buildings"]:
        height = f["properties"].get("height_m")
        roof = None
        proof = "derived" if height else "modeled"
        if points is not None:
            stats = derive_building(f["geometry"], points, terrain)
            if stats["status"] == "derived":
                height = stats["height_m"]
                roof = stats["roof_plane"]
                proof = "derived"
            f["lidar_qa"] = stats
        if height is None:
            if not preview:
                raise DataError("Building heights missing; supply LiDAR or the municipal 3D model")
            height = c["default_building_height_m"]
        if not 1 < float(height) < 150:
            raise DataError("Building height outside supported range")
        buildings.append({**f, "height": float(height), "roof": roof, "height_evidence": proof})
    unresolved_roofs = sum(f["roof"] is None for f in buildings)
    if unresolved_roofs:
        gaps.append(f"{unresolved_roofs} roofs use a modeled flat volume; roof structure unresolved")
    canopy_sampler = None
    if points is not None:
        canopy = derive_canopy(points, terrain, land)
        if canopy:
            from scipy.spatial import cKDTree

            canopy_tree = cKDTree([(p["x"], p["y"]) for p in canopy])

            def canopy_sampler(x, y):
                distance, index = canopy_tree.query([x, y], distance_upper_bound=12)
                return canopy[index]["height_m"] if np.isfinite(distance) else None

    if canopy_sampler is None:
        gaps.append("Tree heights and density use modeled prototypes; no accepted local canopy estimates")
    gaps.append("Vegetation assets, phenology and facade materials still require visual acceptance")
    building_union = unary_union([f["geometry"] for f in buildings])
    road_union = unary_union([f["geometry"] for f in roads])
    exclusion = unary_union([water, building_union.buffer(0.5), road_union])
    fields = []
    unknown_codes = set()
    overlaps = 0
    for f in vectors["fields"]:
        geom = f["geometry"]
        overlaps += geom.intersection(exclusion).area
        # Crop instances cannot enter houses, roads or water even if years disagree.
        # Original source polygon is retained separately for QA; the clipped crop
        # surface is a derived mask, never an edited source boundary.
        code = str(f["properties"].get("grdkod_mar", "unknown"))
        kind = crop_map.get("codes", {}).get(code, {}).get("category", "unknown")
        if kind not in CROP_HEIGHTS:
            unknown_codes.add(code)
            kind = "unknown"
        fields.append({**f, "geometry": geom.difference(exclusion), "crop_kind": kind, "crop_code": code})
    if unknown_codes:
        gaps.append(
            "Unmapped crop codes for " + str(c["crop_year"]) + ": " + ", ".join(sorted(unknown_codes))
        )
    if not preview and gaps:
        raise DataError("Acceptance build blocked: " + "; ".join(gaps))
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema": 1,
        "world": c["id"],
        "horizontal_crs": "EPSG:3006",
        "vertical_crs": vertical,
        "units": "metres",
        "axes": "X east, Y north, Z up",
        "preview_only": preview,
        "reference_origin": [c["bounds"][0], c["bounds"][1], 0],
        "bounds": c["bounds"],
        "input_catalog_sha256": sha256(catalog_path),
        "config": c,
        "sources": catalog["assets"],
        "gaps": gaps,
        "tiles": [],
        "crop_exclusion_overlap_m2": round(overlaps, 2),
        "acceptance_passed": False,
        "note": "Build completion is not visual or geographic acceptance.",
    }
    forest_mask = np.isin(land.values, FOREST_CODES).astype("uint8")
    transform = from_origin(land.west - 5, land.north + 5, 10, 10)
    forest = unary_union(
        [shape(g) for g, v in shapes(forest_mask, mask=forest_mask == 1, transform=transform) if v == 1]
    ).difference(exclusion)
    for tile in tiles(c):
        w, s, e, n = tile["bounds"]
        region = box(w, s, e, n)
        origin = [w, s, 0]
        objects = []
        instances = []
        for lod, step in enumerate(c["lod_steps_m"]):
            grid = terrain.tile(tile["bounds"], step)
            payload = clip_terrain_water(mesh_payload(grid, origin), grid, water.intersection(region), origin)
            if sum(len(f) - 2 for f in payload["faces"]) > c["max_terrain_triangles_per_tile"]:
                raise DataError("Terrain triangle budget exceeded")
            objects.append(
                {"id": "terrain", "kind": "terrain", "lod": lod, "material": "ground", "mesh": payload}
            )
        for f in buildings:
            # Own each complete building once, including footprints that cross
            # the pilot boundary. Do not create a false facade by clipping it.
            inside = f["geometry"].intersection(box(*c["bounds"]))
            if inside.is_empty or inside.area == 0:
                continue
            anchor = inside.representative_point()
            if not (w <= anchor.x < e and s <= anchor.y < n):
                continue
            objects.append(
                {
                    "id": "building-" + f["id"],
                    "kind": "building",
                    "material": "building",
                    "evidence": "derived",
                    "height_evidence": f["height_evidence"],
                    "roof_evidence": "derived" if f["roof"] else "modeled",
                    "mesh": building_mesh(f["geometry"], terrain, f["height"], origin, f["roof"]),
                }
            )
        for f in roads:
            geom = f["geometry"].intersection(region)
            if geom.area:
                objects.append(
                    {
                        "id": "road-" + f["id"],
                        "kind": "road",
                        "material": "gravel"
                        if f["properties"].get("surface") in ("gravel", "unpaved", "dirt")
                        else "asphalt",
                        "evidence": "modeled" if f["modeled_width"] else "derived",
                        "mesh": drape_mesh(geom, terrain, origin, spacing=8),
                    }
                )
        for water_id, water_geometry, level, proof in water_surfaces:
            wet = water_geometry.intersection(region)
            if wet.area:
                objects.append(
                    {
                        "id": "water-" + water_id,
                        "kind": "water",
                        "material": "water",
                        "evidence": proof,
                        "mesh": polygon_mesh(wet, lambda x, y: level, origin),
                    }
                )
        for f in fields:
            geom = f["geometry"].intersection(region)
            if geom.area:
                objects.append(
                    {
                        "id": "field-" + f["id"],
                        "kind": "field",
                        "material": f["crop_kind"] if f["crop_kind"] != "unknown" else "field",
                        "crop_code": f["crop_code"],
                        "crop_year": c["crop_year"],
                        "evidence": "derived",
                        "mesh": drape_mesh(geom, terrain, origin, offset=0.015, spacing=20),
                    }
                )
                if f["crop_kind"] != "unknown":
                    # Sparse clusters for authoring preview. Final micro-density is
                    # generated around the camera in a separate asset/LOD pass.
                    near = geom.intersection(Point((w + e) / 2, (s + n) / 2).buffer(c["crop_near_radius_m"]))
                    instances += scatter(
                        near,
                        terrain,
                        c["crop_spacing_m"],
                        stable_seed(c["seed"], f["id"]),
                        origin,
                        f["crop_kind"],
                        CROP_HEIGHTS[f["crop_kind"]],
                        limit=c["max_instances_per_tile"] - len(instances),
                    )
        instances += scatter(
            forest.intersection(region),
            terrain,
            c["tree_spacing_m"],
            c["seed"],
            origin,
            "broadleaf",
            12,
            limit=max(0, c["max_instances_per_tile"] - len(instances)),
            height_sampler=canopy_sampler,
        )
        texture = tile["id"] + "-ground.png"
        if assets.get("orthophoto"):
            texture_info = orthophoto_texture(
                assets["orthophoto"],
                tile["bounds"],
                output / texture,
                c.get("orthophoto_pixel_m", 0.5),
            )
        else:
            natural_texture(land.tile(tile["bounds"], 10), output / texture)
            texture_info = {"kind": "modeled_nmd_palette", "sha256": sha256(output / texture)}
        package = {
            "schema": 1,
            "tile": tile,
            "origin": origin,
            "objects": objects,
            "instances": instances,
            "ground_texture": texture,
            "ground_texture_info": texture_info,
            "preview_only": preview,
            "vegetation_note": "Procedural prototype instances; modeled positions, species and height unless replaced with approved evidence.",
        }
        name = tile["id"] + ".tile.json.gz"
        archive_json(output / name, package)
        manifest["tiles"].append(
            {
                **tile,
                "origin": origin,
                "file": name,
                "sha256": sha256(output / name),
                "bytes": (output / name).stat().st_size,
                "objects": len(objects),
                "instances": len(instances),
                "triangles_lod0": sum(
                    sum(len(face) - 2 for face in o["mesh"]["faces"]) for o in objects if o.get("lod", 0) == 0
                ),
            }
        )
    write_json(output / "manifest.json", manifest)
    return manifest


def prepare(c, catalog_path, output, preview=False):
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise DataError("Output already exists; choose a fresh build directory to preserve the last build")
    with tempfile.TemporaryDirectory(prefix=".goosen-", dir=output.parent) as tmp:
        result = _prepare(c, catalog_path, Path(tmp) / "world", preview)
        os.replace(Path(tmp) / "world", output)
    return result
