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
from shapely.geometry import Point, Polygon, box, shape
from shapely.ops import unary_union
from shapely import intersects_xy

from .core import DataError, read_json, sha256, stable_seed, tiles, validate_asset, write_json
from .rasters import warp_nodes, mesh_payload
from .vectors import read_features, polygon_mesh, drape_mesh, clip_terrain_water, polygons
from .lidar import load_points, derive_building, derive_canopy, canopy_peaks
from .imagery import orthophoto_texture
from .coast import load_coast, shoreline_height_check
from .architecture import modeled_gable, plane_building

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


def natural_texture(grid, path, sea=None):
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
    if sea is not None:
        gx, gy = np.meshgrid(
            grid.west + np.arange(a.shape[1]) * grid.step, grid.north - np.arange(a.shape[0]) * grid.step
        )
        wet = intersects_xy(sea, gx, gy)
        # Unknown former NMD sea pixels get a neutral modeled ground colour.
        # This changes only the preview palette, never the source NMD classes.
        rgb[(a == 62) & ~wet] = palette["bare"]
        rgb[wet] = palette["water"]
    Image.fromarray(rgb).save(path)


def water_from_nmd(grid, bounds, codes=(61, 62)):
    # Explicit low-resolution proxy. Native vector coast is required for acceptance.
    mask = np.isin(grid.values, codes).astype("uint8")
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
    vectors["context"] = [
        f for p, a in assets.get("context", []) for f in read_features(p, a["horizontal_crs"])
    ]
    crop_map = catalog.get("crop_map", {})
    if crop_map and (crop_map.get("year") != c["crop_year"] or not crop_map.get("source")):
        raise DataError("Crop codebook must have the same year as parcel data and a source")
    for f in vectors["fields"]:
        if f["properties"].get("arslager") != c["crop_year"]:
            raise DataError("Mixed parcel years")
    if not assets.get("orthophoto"):
        gaps.append(
            "No licensed orthophoto; "
            + (
                "10 m satellite RGB used for ground only"
                if assets.get("satellite_rgb")
                else "procedural base materials only"
            )
        )
    points = None
    if assets.get("lidar"):
        if vertical != "EPSG:5613" or any(a.get("vertical_crs") != "EPSG:5613" for _, a in assets["lidar"]):
            raise DataError("LiDAR and terrain must both be RH2000; no implicit Z transform")
        w, s, e, n = c["bounds"]
        h = c["halo_m"]
        points = np.concatenate([load_points(p, [w - h, s - h, e + h, n + h]) for p, a in assets["lidar"]])
    else:
        gaps.append("No LiDAR or approved municipal 3D model; building heights unresolved where absent")
    # Cells on the terrain lattice, not nodata treated as zero.
    core = terrain.tile(c["bounds"], c["terrain_step_m"])
    gx, gy = np.meshgrid(
        np.linspace(c["bounds"][0], c["bounds"][2], core.values.shape[1]),
        np.linspace(c["bounds"][3], c["bounds"][1], core.values.shape[0]),
    )
    land_codes = land.nearest(gx, gy)
    if not np.isfinite(land_codes).all():
        raise DataError("NMD does not cover the full job")
    sea, coast_report = load_coast(assets, c["bounds"])
    water = unary_union([f["geometry"] for f in vectors["water"]])
    if not water.is_empty:
        for f in vectors["water"]:
            if f["geometry"].geom_type not in ("Polygon", "MultiPolygon"):
                raise DataError("Water requires polygons, not an unclosed coast line")
    proxy = Polygon()
    if preview:
        proxy = water_from_nmd(land, c["bounds"], codes=(61,) if sea is not None else (61, 62))
        proxy = proxy.difference(water)
        if sea is not None:
            proxy = proxy.difference(sea)
        if proxy.area:
            gaps.append(
                "Water boundary includes a 10 m NMD " + ("inland proxy" if sea is not None else "proxy")
            )
        water = unary_union([water, proxy])
    if sea is not None:
        coarse_sea = water_from_nmd(land, c["bounds"], codes=(62,))
        coast_report["nmd_disagreement_m2"] = coarse_sea.symmetric_difference(
            sea.intersection(box(*c["bounds"]))
        ).area
        coast_report["terrain_seam"] = shoreline_height_check(sea, c["bounds"], terrain)
        water = unary_union([water, sea])
        gaps.append("OSM coastline topology verified; position still needs orthophoto/official comparison")
        gaps.append("Sea level uses a modeled preview zero, not an observed level in the terrain datum")
        if not preview:
            raise DataError("Coastal sea level requires evidence in the terrain vertical datum")
    invalid_land = int(np.count_nonzero(~np.isfinite(core.values) & ~intersects_xy(water, gx, gy)))
    if invalid_land:
        raise DataError(f"{invalid_land} land terrain nodes missing; supply covering data")
    water_surfaces = []
    for f in vectors["water"]:
        surface = f["geometry"].difference(sea) if sea is not None else f["geometry"]
        if surface.is_empty:
            continue
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
                surface,
                float(level),
                "derived" if f["properties"].get("water_level_m") is not None else "modeled",
            )
        )
    if preview and proxy.area:
        water_surfaces.append(("nmd-proxy", proxy, 0.0, "modeled"))
    if sea is not None:
        water_surfaces.append(("osm-sea", sea, 0.0, "modeled"))
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
            width = {
                "footway": 1.8,
                "steps": 1.5,
                "platform": 2,
                "pedestrian": 3,
                "path": 1.5,
                "cycleway": 2.5,
                "service": 3.5,
                "track": 3,
                "residential": 5,
                "tertiary": 6,
                "secondary": 7,
                "primary": 8,
            }.get(props.get("highway"), c["default_road_width_m"])
        if not 0 < float(width) < 100:
            raise DataError("Road width outside range")
        geom = f["geometry"]
        surface = (
            geom
            if geom.geom_type in ("Polygon", "MultiPolygon")
            else geom.buffer(float(width) / 2, cap_style=2, join_style=2)
        )
        roads.append(
            {
                **f,
                "centerline": geom if geom.geom_type == "LineString" else None,
                "geometry": surface,
                "modeled_width": props.get("width_m") is None,
            }
        )
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
    unresolved_roofs = sum(
        f["roof"] is None and not f.get("lidar_qa", {}).get("roof_model") for f in buildings
    )
    if unresolved_roofs:
        gaps.append(
            f"{unresolved_roofs} roofs lack measured geometry; any generated gables/materials are modeled"
        )
    canopy_sampler = None
    if points is not None:
        canopy = derive_canopy(
            points,
            terrain,
            land,
            exclusion=unary_union([f["geometry"] for f in buildings] + [f["geometry"] for f in roads]).buffer(
                0.5
            ),
        )
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
    if coast_report is not None:
        coast_report["building_overlap_m2"] = building_union.intersection(sea).area
        coast_report["road_overlap_m2"] = road_union.intersection(sea).area
        coast_report["overlap_note"] = (
            "Diagnostic only. Modeled road widths and coastal structures need review."
        )
    exclusion = unary_union([water, building_union.buffer(0.5), road_union])
    tree_candidates = (
        canopy_peaks(
            points,
            terrain,
            unary_union([exclusion.buffer(1), unary_union([f["geometry"] for f in vectors["fields"]])]),
            c["bounds"],
        )
        if points is not None
        else []
    )
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
        "coast_qa": coast_report,
        "tiles": [],
        "crop_exclusion_overlap_m2": round(overlaps, 2),
        "acceptance_passed": False,
        "note": "Build completion is not visual or geographic acceptance.",
    }
    if points is not None:
        ground_points = points[points[:, 3] == 2]
        residual = ground_points[:, 2] - terrain.sample(ground_points[:, 0], ground_points[:, 1])
        residual = residual[np.isfinite(residual)]
        manifest["lidar_qa"] = {
            "usable_points": len(points),
            "ground_comparison": {
                "samples": len(residual),
                "median_m": float(np.median(residual)) if len(residual) else None,
                "p95_absolute_m": float(np.percentile(np.abs(residual), 95)) if len(residual) else None,
                "note": "Consistency comparison against the DTM, not independent survey accuracy.",
            },
            "buildings": [{"id": f["id"], **f.get("lidar_qa", {})} for f in buildings],
            "derived_heights": sum(f.get("lidar_qa", {}).get("status") == "derived" for f in buildings),
            "fitted_single_planes": sum(f["roof"] is not None for f in buildings),
            "canopy_samples": len(canopy),
            "fitted_gables": sum(bool(f.get("lidar_qa", {}).get("roof_model")) for f in buildings),
            "canopy_candidates": len(tree_candidates),
            "note": "Unresolved roofs retain modeled preview geometry. Roof/tree confusion requires visual QA.",
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
            roof_model = f.get("lidar_qa", {}).get("roof_model")
            model = None
            if roof_model or f["roof"]:
                model = plane_building(
                    f["geometry"],
                    terrain,
                    origin,
                    roof_model["planes"] if roof_model else [f["roof"]],
                    roof_model,
                )
            if model is None and preview and c.get("modeled_architecture"):
                model = modeled_gable(f["geometry"], terrain, f["height"], origin)
            if model is None:
                # Preserve complex footprints, separate neutral walls from roof.
                coords = [xy for poly in polygons(f["geometry"]) for xy in poly.exterior.coords]
                top = (
                    float(np.max(terrain.sample([p[0] for p in coords], [p[1] for p in coords])))
                    + f["height"]
                )
                model = plane_building(f["geometry"], terrain, origin, [[0, 0, top, 0, 0]])
                model["evidence"] = "modeled"
                model["rule"] = "unresolved_flat_volume"
            palette = stable_seed(c["seed"], f["id"])
            # Art-directed subdued palette, not sampled pixels or per-house observations.
            roof_material = [
                "roof_slate",
                "roof_slate",
                "roof_charcoal",
                "roof_grey",
                "roof_clay",
                "roof_brown",
            ][palette % 6]
            for part in ("walls", "roof"):
                objects.append(
                    {
                        "id": "building-" + f["id"] + "-" + part,
                        "kind": "building",
                        "part": part,
                        "material": ["plaster_warm", "brick_ochre", "plaster_light", "brick_red"][palette % 4]
                        if part == "walls"
                        else roof_material,
                        "evidence": "derived",
                        "height_evidence": f["height_evidence"],
                        "roof_evidence": model["evidence"],
                        "material_evidence": "modeled",
                        "model_rule": model["rule"],
                        "mesh": model[part],
                    }
                )
        context_exclusion = unary_union([water, building_union.buffer(0.15), road_union])
        for f in vectors["context"]:
            props = f["properties"]
            if props.get("barrier") == "hedge":
                line = f["geometry"].intersection(region)
                if line.geom_type not in ("LineString", "MultiLineString"):
                    continue
                segments = [line] if line.geom_type == "LineString" else line.geoms
                for segment in segments:
                    for distance in np.arange(0, segment.length, 0.6):
                        point = segment.interpolate(distance)
                        if context_exclusion.covers(point):
                            continue
                        z = float(terrain.sample(point.x, point.y))
                        if np.isfinite(z):
                            instances.append(
                                {
                                    "asset": "broadleaf",
                                    "position": [point.x - w, point.y - s, z],
                                    "yaw": float(distance % 6.28),
                                    "height_m": 1.6,
                                    "position_evidence": "derived",
                                    "height_evidence": "modeled",
                                    "evidence": "modeled",
                                }
                            )
                continue
            if f["geometry"].geom_type not in ("Polygon", "MultiPolygon"):
                continue
            geom = f["geometry"].intersection(region).difference(context_exclusion)
            if geom.area < 1:
                continue
            kind = (
                "lawn"
                if (
                    props.get("landuse") == "grass"
                    or props.get("leisure") in ("park", "pitch")
                    or props.get("surface") == "grass"
                )
                else "shore"
                if props.get("natural") == "beach" or props.get("man_made") == "breakwater"
                else "gravel"
                if props.get("amenity") == "parking"
                else None
            )
            if props.get("surface") == "asphalt":
                kind = "asphalt"
            if kind:
                objects.append(
                    {
                        "id": "context-" + f["id"],
                        "kind": "surface",
                        "material": kind,
                        "evidence": "derived",
                        "material_evidence": "modeled",
                        "mesh": drape_mesh(geom, terrain, origin, offset=0.02, spacing=4),
                    }
                )
        if sea is not None:
            shore = sea.buffer(4).difference(sea).intersection(region).difference(context_exclusion)
            if shore.area:
                objects.append(
                    {
                        "id": "modeled-shore-band",
                        "kind": "surface",
                        "material": "shore",
                        "evidence": "modeled",
                        "model_rule": "4m_landward_coast_material_band",
                        "mesh": drape_mesh(shore, terrain, origin, offset=0.02, spacing=3),
                    }
                )
        for f in roads:
            geom = f["geometry"].intersection(region)
            if geom.area:
                objects.append(
                    {
                        "id": "road-" + f["id"],
                        "kind": "road",
                        "material": "lawn"
                        if f["properties"].get("surface") == "grass"
                        else "asphalt"
                        if f["properties"].get("surface") in ("asphalt", "paved", "paving_stones", "sett")
                        else "gravel"
                        if f["properties"].get("surface")
                        in ("gravel", "unpaved", "dirt", "ground", "fine_gravel", "pebblestone")
                        or f["properties"].get("highway") in ("path", "track", "footway")
                        else "asphalt",
                        "evidence": "modeled" if f["modeled_width"] else "derived",
                        "mesh": drape_mesh(geom, terrain, origin, spacing=8),
                    }
                )
            if (
                geom.area
                and f["properties"].get("highway") in ("primary", "secondary")
                and f["centerline"] is not None
            ):
                from shapely.ops import substring

                line = f["centerline"]
                dashes = []
                for distance in np.arange(0, line.length, 12):
                    segment = substring(line, float(distance), float(min(line.length, distance + 3)))
                    if segment.geom_type == "LineString":
                        dashes.append(
                            segment.buffer(0.06, cap_style=2).intersection(region).intersection(geom)
                        )
                stripe = unary_union(dashes)
                if stripe.area:
                    objects.append(
                        {
                            "id": "markings-" + f["id"],
                            "kind": "road_detail",
                            "material": "road_paint",
                            "evidence": "modeled",
                            "model_rule": "generic_dashed_centerline_not_surveyed",
                            "mesh": drape_mesh(stripe, terrain, origin, offset=0.042, spacing=3),
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
                        "level_evidence": proof,
                        "boundary_evidence": "derived" if water_id != "nmd-proxy" else "modeled",
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
                    # Distributed across actual parcels; no arbitrary circular preview patches.
                    near = geom.buffer(-2.5)
                    instances += scatter(
                        near,
                        terrain,
                        max(4.5, c["crop_spacing_m"]),
                        stable_seed(c["seed"], f["id"]),
                        origin,
                        f["crop_kind"],
                        CROP_HEIGHTS[f["crop_kind"]],
                        limit=c["max_instances_per_tile"] - len(instances),
                    )
        if tree_candidates:
            for tree in tree_candidates:
                x, y = tree["x"], tree["y"]
                if w <= x < e and s <= y < n:
                    instances.append(
                        {
                            "asset": "broadleaf",
                            "position": [x - w, y - s, float(terrain.sample(x, y))],
                            "yaw": (stable_seed(c["seed"], x, y) % 6283) / 1000,
                            "height_m": tree["height_m"],
                            "height_evidence": "derived",
                            "position_evidence": "derived_candidate",
                            "evidence": "modeled",
                        }
                    )
        else:
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
        elif assets.get("satellite_rgb"):
            texture_info = orthophoto_texture(
                assets["satellite_rgb"], tile["bounds"], output / texture, resolution=10, kind="satellite_rgb"
            )
        else:
            natural_texture(land.tile(tile["bounds"], 10), output / texture, sea)
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
