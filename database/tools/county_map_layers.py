#!/usr/bin/env python3
"""Accept and validate authoritative Kane County road and water harvests."""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import sqlite3
import struct
import tempfile
from pathlib import Path
from typing import Any, Iterable

import county_arcgis
import county_building_refresh
import county_buildings
import county_harvest

SRS_ID = 4326
TOOL_VERSION = "batch-021.0"
DATASETS: dict[str, dict[str, Any]] = {
    "roads": {
        "profile_key": "kane-county-road-centerlines",
        "name": "Kane County Road Centerlines",
        "feature_class": "road-centerline",
        "description": "Authoritative county road centerlines preserved as immutable source releases.",
        "geometry_types": ("LineString", "MultiLineString"),
    },
    "water-fox-river": {
        "profile_key": "kane-county-fox-river",
        "name": "Kane County Fox River",
        "feature_class": "water-polygon",
        "description": "Authoritative Fox River polygons preserved as immutable source releases.",
        "geometry_types": ("Polygon", "MultiPolygon"),
    },
    "water-creeks": {
        "profile_key": "kane-county-creeks",
        "name": "Kane County Creeks",
        "feature_class": "water-centerline",
        "description": "Authoritative creek centerlines preserved as immutable source releases.",
        "geometry_types": ("LineString", "MultiLineString"),
    },
}
WKB_TYPES = {"LineString": 2, "Polygon": 3, "MultiLineString": 5, "MultiPolygon": 6}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def normalize_position(value: Any) -> tuple[float, float]:
    if not isinstance(value, list) or len(value) != 2:
        raise RuntimeError("Map-layer coordinates must contain exactly two ordinates.")
    try:
        x, y = float(value[0]), float(value[1])
    except (TypeError, ValueError) as exc:
        raise RuntimeError("Map-layer coordinates must be numeric.") from exc
    if not math.isfinite(x) or not math.isfinite(y):
        raise RuntimeError("Map-layer coordinates must be finite.")
    if not -180 <= x <= 180 or not -90 <= y <= 90:
        raise RuntimeError("Map-layer coordinates must use EPSG:4326 longitude/latitude.")
    return x, y


def normalize_line(value: Any) -> list[tuple[float, float]]:
    if not isinstance(value, list) or len(value) < 2:
        raise RuntimeError("LineString must contain at least two positions.")
    return [normalize_position(item) for item in value]


def normalize_geometry(geometry: Any) -> tuple[str, Any]:
    if not isinstance(geometry, dict):
        raise RuntimeError("Map-layer feature has no geometry object.")
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates")
    if geometry_type in ("Polygon", "MultiPolygon"):
        return county_buildings.normalize_geometry(geometry)
    if geometry_type == "LineString":
        return geometry_type, normalize_line(coordinates)
    if geometry_type == "MultiLineString":
        if not isinstance(coordinates, list) or not coordinates:
            raise RuntimeError("MultiLineString must contain at least one line.")
        return geometry_type, [normalize_line(line) for line in coordinates]
    raise RuntimeError(f"Unsupported map-layer geometry type: {geometry_type!r}.")


def iter_positions(geometry_type: str, coordinates: Any) -> Iterable[tuple[float, float]]:
    if geometry_type == "LineString":
        yield from coordinates
    elif geometry_type == "MultiLineString":
        for line in coordinates:
            yield from line
    else:
        yield from county_buildings.iter_positions(geometry_type, coordinates)


def line_wkb(line: list[tuple[float, float]]) -> bytes:
    parts = [struct.pack("<BI", 1, 2), struct.pack("<I", len(line))]
    parts.extend(struct.pack("<dd", x, y) for x, y in line)
    return b"".join(parts)


def geometry_wkb(geometry_type: str, coordinates: Any) -> bytes:
    if geometry_type == "LineString":
        return line_wkb(coordinates)
    if geometry_type == "MultiLineString":
        parts = [struct.pack("<BI", 1, 5), struct.pack("<I", len(coordinates))]
        parts.extend(line_wkb(line) for line in coordinates)
        return b"".join(parts)
    return county_buildings.geometry_wkb(geometry_type, coordinates)


def geopackage_geometry(
    geometry_type: str, coordinates: Any
) -> tuple[bytes, bytes, tuple[float, float, float, float]]:
    points = list(iter_positions(geometry_type, coordinates))
    xs, ys = [item[0] for item in points], [item[1] for item in points]
    bounds = (min(xs), min(ys), max(xs), max(ys))
    wkb = geometry_wkb(geometry_type, coordinates)
    header = b"GP" + bytes((0, 3)) + struct.pack("<i", SRS_ID)
    header += struct.pack("<dddd", bounds[0], bounds[2], bounds[1], bounds[3])
    return header + wkb, wkb, bounds


def normalize_features(
    geojson: Path, id_property: str, allowed_types: tuple[str, ...]
) -> tuple[bytes, list[dict[str, Any]]]:
    raw = geojson.read_bytes()
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Map-layer source is not valid UTF-8 GeoJSON: {exc}") from exc
    features = document.get("features") if isinstance(document, dict) else None
    if not isinstance(document, dict) or document.get("type") != "FeatureCollection":
        raise RuntimeError("Map-layer source must be a GeoJSON FeatureCollection.")
    if not isinstance(features, list) or not features:
        raise RuntimeError("Map-layer source contains no features.")
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for ordinal, feature in enumerate(features, start=1):
        if not isinstance(feature, dict) or feature.get("type") != "Feature":
            raise RuntimeError(f"Map-layer item {ordinal} is not a GeoJSON Feature.")
        source_id = county_buildings.feature_id(feature, id_property)
        if source_id in seen:
            raise RuntimeError(f"Duplicate map-layer source feature id: {source_id}")
        seen.add(source_id)
        geometry_type, coordinates = normalize_geometry(feature.get("geometry"))
        if geometry_type not in allowed_types:
            raise RuntimeError(
                f"Map-layer feature {source_id} geometry is {geometry_type}; "
                f"expected {' or '.join(allowed_types)}."
            )
        blob, wkb, bounds = geopackage_geometry(geometry_type, coordinates)
        attributes = feature.get("properties")
        if not isinstance(attributes, dict):
            raise RuntimeError(f"Map-layer feature {source_id} properties are not an object.")
        attributes_json = canonical_json(attributes)
        geometry_hash = sha256_bytes(wkb)
        attributes_hash = sha256_bytes(attributes_json.encode("utf-8"))
        content_hash = sha256_bytes(canonical_json({
            "source_feature_id": source_id,
            "geometry_sha256": geometry_hash,
            "attributes_sha256": attributes_hash,
        }).encode("utf-8"))
        output.append({
            "source_feature_id": source_id,
            "source_ordinal": ordinal,
            "geometry": blob,
            "geometry_type": geometry_type,
            "geometry_sha256": geometry_hash,
            "attributes_json": attributes_json,
            "attributes_sha256": attributes_hash,
            "content_sha256": content_hash,
            "bounds": bounds,
        })
    return raw, output


def ensure_dataset(
    connection: sqlite3.Connection, dataset_key: str, id_property: str, now: str
) -> int:
    contract = DATASETS[dataset_key]
    county_id = connection.execute(
        "SELECT county_id FROM county WHERE fips_code = '17089'"
    ).fetchone()[0]
    connection.execute(
        """INSERT INTO source_agency(
               agency_key, agency_name, jurisdiction, homepage_uri, created_at
           ) VALUES ('kane-county-gis', 'Kane County GIS', 'Kane County, Illinois', NULL, ?)
           ON CONFLICT(agency_key) DO NOTHING""",
        (now,),
    )
    agency_id = connection.execute(
        "SELECT agency_id FROM source_agency WHERE agency_key = 'kane-county-gis'"
    ).fetchone()[0]
    connection.execute(
        """INSERT INTO dataset(
               county_id, agency_id, dataset_key, dataset_name, feature_class,
               source_id_policy, description, created_at
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(county_id, dataset_key) DO NOTHING""",
        (
            county_id, agency_id, dataset_key, contract["name"], contract["feature_class"],
            f"GeoJSON property {id_property}", contract["description"], now,
        ),
    )
    row = connection.execute(
        """SELECT dataset_id, dataset_name, feature_class FROM dataset
           WHERE county_id = ? AND dataset_key = ?""",
        (county_id, dataset_key),
    ).fetchone()
    if row[1:] != (contract["name"], contract["feature_class"]):
        raise RuntimeError(f"Existing dataset contract is incompatible: {dataset_key}.")
    return int(row[0])


def import_harvest(
    connection: sqlite3.Connection,
    profile_path: Path,
    geojson: Path,
    harvest: dict[str, Any],
) -> dict[str, Any]:
    profile, _ = county_arcgis.load_profile(profile_path)
    dataset_key = profile["dataset_key"]
    contract = DATASETS.get(dataset_key)
    if contract is None or profile["profile_key"] != contract["profile_key"]:
        raise RuntimeError(f"Harvest profile is not an accepted map-layer contract: {profile['profile_key']}.")
    manifest = Path(harvest["manifest"])
    raw, features = normalize_features(geojson, harvest["id_property"], contract["geometry_types"])
    manifest_raw = manifest.read_bytes()
    if sha256_bytes(raw) != harvest["geojson_sha256"]:
        raise RuntimeError(f"{dataset_key} harvest hash changed after validation.")
    if sha256_bytes(manifest_raw) != harvest["manifest_sha256"]:
        raise RuntimeError(f"{dataset_key} manifest hash changed after validation.")
    now = county_buildings.utc_now()
    dataset_id = ensure_dataset(connection, dataset_key, harvest["id_property"], now)
    accepted = connection.execute(
        "SELECT release_key FROM source_release WHERE dataset_id = ? AND status = 'accepted'",
        (dataset_id,),
    ).fetchone()
    if accepted:
        raise RuntimeError(
            f"{dataset_key} release is already accepted: {accepted[0]}. Refresh is not implemented."
        )
    run_id = connection.execute(
        """INSERT INTO harvest_run(dataset_id, started_at, status, tool_version)
           VALUES (?, ?, 'started', ?)""",
        (dataset_id, now, TOOL_VERSION),
    ).lastrowid
    release_id = connection.execute(
        """INSERT INTO source_release(
               dataset_id, release_key, source_version, source_published_at,
               harvested_at, source_uri, content_sha256, status, notes
           ) VALUES (?, ?, ?, ?, ?, ?, ?, 'candidate', ?)""",
        (
            dataset_id, harvest["release_key"], harvest["source_version"],
            harvest["published_at"], harvest["harvested_at"], harvest["source_uri"],
            harvest["geojson_sha256"], f"Immutable authoritative {dataset_key} release.",
        ),
    ).lastrowid
    connection.execute(
        "UPDATE harvest_run SET candidate_release_id = ? WHERE run_id = ?", (release_id, run_id)
    )
    connection.executemany(
        """INSERT INTO source_file(
               release_id, relative_path, media_type, byte_length, sha256, preserved_at
           ) VALUES (?, ?, ?, ?, ?, ?)""",
        [
            (release_id, geojson.name, "application/geo+json", len(raw), sha256_bytes(raw), now),
            (release_id, manifest.name, "application/json", len(manifest_raw),
             sha256_bytes(manifest_raw), now),
        ],
    )
    connection.executemany(
        """INSERT INTO source_map_feature(
               release_id, source_feature_id, source_ordinal, geometry, geometry_type,
               geometry_sha256, attributes_json, attributes_sha256, content_sha256,
               min_x, min_y, max_x, max_y
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [(
            release_id, item["source_feature_id"], item["source_ordinal"], item["geometry"],
            item["geometry_type"], item["geometry_sha256"], item["attributes_json"],
            item["attributes_sha256"], item["content_sha256"], *item["bounds"],
        ) for item in features],
    )
    connection.execute(
        "UPDATE source_release SET status = 'accepted', accepted_at = ? WHERE release_id = ?",
        (now, release_id),
    )
    connection.execute(
        """UPDATE harvest_run SET completed_at = ?, status = 'accepted',
           candidate_release_id = ? WHERE run_id = ?""",
        (now, release_id, run_id),
    )
    return {"dataset_key": dataset_key, "release_id": release_id,
            "release_key": harvest["release_key"], "feature_count": len(features)}


def update_extent(connection: sqlite3.Connection, now: str) -> None:
    extent = connection.execute(
        "SELECT MIN(min_x), MIN(min_y), MAX(max_x), MAX(max_y) FROM source_map_feature"
    ).fetchone()
    connection.execute(
        """UPDATE gpkg_contents SET last_change = ?, min_x = ?, min_y = ?, max_x = ?, max_y = ?
           WHERE table_name = 'source_map_feature'""",
        (now, *extent),
    )


def accept_harvested_map_layers(
    database: Path, sources: list[tuple[Path, Path, Path | None]]
) -> dict[str, object]:
    import county_db

    harvests = [county_harvest.validate_harvest(*source) for source in sources]
    keys = [county_arcgis.load_profile(source[0])[0]["dataset_key"] for source in sources]
    if set(keys) != set(DATASETS) or len(keys) != len(DATASETS):
        raise RuntimeError("Road and water acceptance requires exactly roads, Fox River, and creeks.")
    if not database.is_file():
        raise RuntimeError(f"Accepted database does not exist: {database}")
    handle, name = tempfile.mkstemp(
        prefix=f".{database.name}.", suffix=".map-layers-candidate", dir=database.parent
    )
    os.close(handle)
    candidate = Path(name)
    try:
        shutil.copy2(database, candidate)
        county_building_refresh.upgrade_candidate(candidate)
        connection = sqlite3.connect(candidate)
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            with connection:
                results = [
                    import_harvest(connection, source[0], source[1], harvest)
                    for source, harvest in zip(sources, harvests)
                ]
                update_extent(connection, county_buildings.utc_now())
        finally:
            connection.close()
        errors = county_db.validate_deployment_database(candidate)
        if errors:
            raise RuntimeError("Map-layer candidate failed validation:\n- " + "\n- ".join(errors))
        os.replace(candidate, database)
        info = county_db.database_info(database)
        info["accepted_map_layer_harvests"] = harvests
        info["map_layer_acceptance_results"] = results
        return info
    finally:
        candidate.unlink(missing_ok=True)


def geometry_blob_error(blob: bytes, geometry_type: str) -> str | None:
    if len(blob) < 45 or blob[:2] != b"GP" or blob[2] != 0 or blob[3] != 3:
        return "geometry BLOB has an invalid GeoPackage header"
    if struct.unpack("<i", blob[4:8])[0] != SRS_ID:
        return "geometry BLOB uses an unexpected SRS"
    expected = WKB_TYPES.get(geometry_type)
    if blob[40] != 1 or struct.unpack("<I", blob[41:45])[0] != expected:
        return "geometry WKB type does not match geometry_type"
    return None


def map_layer_errors(connection: sqlite3.Connection, require_accepted: bool) -> list[str]:
    errors: list[str] = []
    contents = connection.execute(
        "SELECT data_type, srs_id FROM gpkg_contents WHERE table_name = 'source_map_feature'"
    ).fetchall()
    if contents != [("features", SRS_ID)]:
        errors.append("source_map_feature is not correctly registered in gpkg_contents.")
    columns = connection.execute(
        """SELECT column_name, geometry_type_name, srs_id, z, m FROM gpkg_geometry_columns
           WHERE table_name = 'source_map_feature'"""
    ).fetchall()
    if columns != [("geometry", "GEOMETRY", SRS_ID, 0, 0)]:
        errors.append("source_map_feature is not registered in gpkg_geometry_columns.")
    accepted_keys: set[str] = set()
    for dataset_key, contract in DATASETS.items():
        releases = connection.execute(
            """SELECT r.release_id, r.release_key, r.content_sha256, r.source_version
               FROM source_release r JOIN dataset d ON d.dataset_id = r.dataset_id
               WHERE d.dataset_key = ? AND r.status = 'accepted'""",
            (dataset_key,),
        ).fetchall()
        if require_accepted and len(releases) != 1:
            errors.append(f"Accepted {dataset_key} release count is {len(releases)}; expected 1.")
        if not releases:
            continue
        accepted_keys.add(dataset_key)
        if len(releases) != 1:
            errors.append(f"Accepted {dataset_key} release count is {len(releases)}; expected 1.")
            continue
        release_id, release_key, release_hash, source_version = releases[0]
        prefix = "arcgis-profile-sha256:"
        profile_hash = source_version[len(prefix):] if isinstance(source_version, str) and source_version.startswith(prefix) else ""
        if len(profile_hash) != 64 or any(char not in "0123456789abcdef" for char in profile_hash):
            errors.append(f"{dataset_key} release {release_key} ArcGIS profile hash is invalid.")
        files = connection.execute(
            """SELECT media_type, byte_length, sha256 FROM source_file
               WHERE release_id = ? ORDER BY source_file_id""",
            (release_id,),
        ).fetchall()
        geojson = [item for item in files if item[0] == "application/geo+json"]
        manifests = [item for item in files if item[0] == "application/json"]
        if len(files) != 2 or len(geojson) != 1 or len(manifests) != 1:
            errors.append(f"{dataset_key} release {release_key} source-file provenance is incomplete.")
        elif geojson[0][2] != release_hash:
            errors.append(f"{dataset_key} release {release_key} source-file hash is invalid.")
        rows = connection.execute(
            """SELECT source_ordinal, source_feature_id, geometry, geometry_type,
                      geometry_sha256, attributes_json, attributes_sha256, content_sha256,
                      min_x, min_y, max_x, max_y
               FROM source_map_feature WHERE release_id = ? ORDER BY source_ordinal""",
            (release_id,),
        ).fetchall()
        if not rows:
            errors.append(f"{dataset_key} release {release_key} contains no features.")
        if [row[0] for row in rows] != list(range(1, len(rows) + 1)):
            errors.append(f"{dataset_key} release {release_key} ordinals are not contiguous.")
        for row in rows:
            (_, source_id, blob, geometry_type, geometry_hash, attributes_json,
             attributes_hash, content_hash, min_x, min_y, max_x, max_y) = row
            if geometry_type not in contract["geometry_types"]:
                errors.append(f"{dataset_key} feature {source_id} has an invalid geometry type.")
                continue
            blob_error = geometry_blob_error(blob, geometry_type)
            if blob_error:
                errors.append(f"{dataset_key} feature {source_id} {blob_error}.")
                continue
            if sha256_bytes(blob[40:]) != geometry_hash:
                errors.append(f"{dataset_key} feature {source_id} geometry hash is invalid.")
            envelope = struct.unpack("<dddd", blob[8:40])
            if (min_x, min_y, max_x, max_y) != (envelope[0], envelope[2], envelope[1], envelope[3]):
                errors.append(f"{dataset_key} feature {source_id} bounds do not match geometry.")
            try:
                attributes = json.loads(attributes_json)
            except json.JSONDecodeError:
                attributes = None
            if not isinstance(attributes, dict):
                errors.append(f"{dataset_key} feature {source_id} attributes are invalid JSON.")
                continue
            expected_attributes = sha256_bytes(canonical_json(attributes).encode("utf-8"))
            if attributes_hash != expected_attributes:
                errors.append(f"{dataset_key} feature {source_id} attribute hash is invalid.")
            expected_content = sha256_bytes(canonical_json({
                "source_feature_id": source_id,
                "geometry_sha256": geometry_hash,
                "attributes_sha256": attributes_hash,
            }).encode("utf-8"))
            if content_hash != expected_content:
                errors.append(f"{dataset_key} feature {source_id} content hash is invalid.")
    if not accepted_keys:
        count = connection.execute("SELECT COUNT(*) FROM source_map_feature").fetchone()[0]
        if count:
            errors.append("Map-layer features exist without accepted releases.")
    return errors


def map_layer_info(path: Path) -> dict[str, Any]:
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        output: dict[str, Any] = {}
        for dataset_key in DATASETS:
            row = connection.execute(
                """SELECT r.release_id, r.release_key, r.source_published_at, r.harvested_at,
                          r.accepted_at, r.source_uri, r.content_sha256, COUNT(f.source_map_feature_id),
                          MIN(f.min_x), MIN(f.min_y), MAX(f.max_x), MAX(f.max_y)
                   FROM source_release r JOIN dataset d ON d.dataset_id = r.dataset_id
                   LEFT JOIN source_map_feature f ON f.release_id = r.release_id
                   WHERE d.dataset_key = ? AND r.status = 'accepted' GROUP BY r.release_id""",
                (dataset_key,),
            ).fetchone()
            if row:
                output[dataset_key] = {
                    "release_key": row[1], "source_published_at": row[2],
                    "harvested_at": row[3], "accepted_at": row[4], "source_uri": row[5],
                    "content_sha256": row[6], "feature_count": row[7],
                    "bounds": {"min_x": row[8], "min_y": row[9], "max_x": row[10], "max_y": row[11]},
                    "srs_id": SRS_ID,
                }
        return {"accepted_map_layers": output} if output else {}
    finally:
        connection.close()
