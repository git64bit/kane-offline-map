#!/usr/bin/env python3
"""Accept one authoritative county-boundary harvest and calibrate the field grid."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import struct
import tempfile
from pathlib import Path
from typing import Any

import county_buildings
import county_grid
import county_harvest
import county_spatial

SRS_ID = 4326
AGENCY_KEY = "kane-county-gis"
DATASET_KEY = "county-boundary"
PROFILE_KEY = "kane-county-boundary"
TOOL_VERSION = "batch-014.0"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def normalize_boundary(geojson: Path, id_property: str) -> tuple[bytes, dict[str, Any]]:
    raw = geojson.read_bytes()
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"County boundary is not valid UTF-8 GeoJSON: {exc}") from exc
    features = document.get("features") if isinstance(document, dict) else None
    if not isinstance(document, dict) or document.get("type") != "FeatureCollection":
        raise RuntimeError("County boundary must be a GeoJSON FeatureCollection.")
    if not isinstance(features, list) or len(features) != 1:
        count = len(features) if isinstance(features, list) else 0
        raise RuntimeError(f"County boundary contains {count} features; expected 1.")
    feature = features[0]
    if not isinstance(feature, dict) or feature.get("type") != "Feature":
        raise RuntimeError("County boundary item is not a GeoJSON Feature.")
    source_id = county_buildings.feature_id(feature, id_property)
    geometry_type, coordinates = county_buildings.normalize_geometry(feature.get("geometry"))
    geometry, wkb, bounds = county_buildings.geopackage_geometry(geometry_type, coordinates)
    properties = feature.get("properties")
    if not isinstance(properties, dict):
        raise RuntimeError("County boundary properties are not an object.")
    attributes_json = canonical_json(properties)
    geometry_hash = sha256_bytes(wkb)
    attributes_hash = sha256_bytes(attributes_json.encode("utf-8"))
    content_hash = sha256_bytes(canonical_json({
        "source_feature_id": source_id,
        "geometry_sha256": geometry_hash,
        "attributes_sha256": attributes_hash,
    }).encode("utf-8"))
    return raw, {
        "source_feature_id": source_id,
        "geometry": geometry,
        "geometry_type": geometry_type,
        "geometry_sha256": geometry_hash,
        "attributes_json": attributes_json,
        "attributes_sha256": attributes_hash,
        "content_sha256": content_hash,
        "bounds": bounds,
    }


def ensure_dataset(connection: sqlite3.Connection, id_property: str, now: str) -> int:
    county_id = connection.execute(
        "SELECT county_id FROM county WHERE fips_code = '17089'"
    ).fetchone()[0]
    connection.execute(
        """
        INSERT INTO source_agency(agency_key, agency_name, jurisdiction, homepage_uri, created_at)
        VALUES (?, ?, ?, ?, ?) ON CONFLICT(agency_key) DO NOTHING
        """,
        (AGENCY_KEY, "Kane County GIS", "Kane County, Illinois", None, now),
    )
    agency_id = connection.execute(
        "SELECT agency_id FROM source_agency WHERE agency_key = ?", (AGENCY_KEY,)
    ).fetchone()[0]
    connection.execute(
        """
        INSERT INTO dataset(
            county_id, agency_id, dataset_key, dataset_name, feature_class,
            source_id_policy, description, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(county_id, dataset_key) DO NOTHING
        """,
        (
            county_id, agency_id, DATASET_KEY, "Kane County Boundary",
            "administrative-boundary", f"GeoJSON property {id_property}",
            "Authoritative county boundary preserved as an immutable source release.", now,
        ),
    )
    return connection.execute(
        "SELECT dataset_id FROM dataset WHERE county_id = ? AND dataset_key = ?",
        (county_id, DATASET_KEY),
    ).fetchone()[0]


def accepted_building_release(connection: sqlite3.Connection) -> int:
    row = connection.execute(
        """
        SELECT r.release_id FROM source_release r
        JOIN dataset d ON d.dataset_id = r.dataset_id
        WHERE d.dataset_key = 'buildings' AND r.status = 'accepted'
        """
    ).fetchone()
    if row is None:
        raise RuntimeError("Accepted building release is required before boundary acceptance.")
    return row[0]


def import_boundary(
    connection: sqlite3.Connection,
    geojson: Path,
    manifest_file: Path,
    harvest: dict[str, Any],
) -> dict[str, Any]:
    if harvest.get("profile_key") != PROFILE_KEY:
        raise RuntimeError("Harvest profile is not the Kane County boundary contract.")
    raw, boundary = normalize_boundary(geojson, harvest["id_property"])
    source_hash = sha256_bytes(raw)
    manifest_raw = manifest_file.read_bytes()
    if source_hash != harvest["geojson_sha256"]:
        raise RuntimeError("Boundary harvest hash changed after validation.")
    if sha256_bytes(manifest_raw) != harvest["manifest_sha256"]:
        raise RuntimeError("Boundary manifest hash changed after validation.")
    now = county_grid.utc_now()
    dataset_id = ensure_dataset(connection, harvest["id_property"], now)
    accepted = connection.execute(
        "SELECT release_key FROM source_release WHERE dataset_id = ? AND status = 'accepted'",
        (dataset_id,),
    ).fetchone()
    if accepted:
        raise RuntimeError(
            f"County boundary release is already accepted: {accepted[0]}. "
            "Boundary refresh is not implemented."
        )
    duplicate = connection.execute(
        """SELECT release_key FROM source_release
           WHERE dataset_id = ? AND (release_key = ? OR content_sha256 = ?)""",
        (dataset_id, harvest["release_key"], source_hash),
    ).fetchone()
    if duplicate:
        raise RuntimeError(f"County boundary source release already imported: {duplicate[0]}")
    run_id = connection.execute(
        """INSERT INTO harvest_run(dataset_id, started_at, status, tool_version)
           VALUES (?, ?, 'started', ?)""",
        (dataset_id, now, TOOL_VERSION),
    ).lastrowid
    release_id = connection.execute(
        """
        INSERT INTO source_release(
            dataset_id, release_key, source_version, source_published_at,
            harvested_at, source_uri, content_sha256, status, notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'candidate', ?)
        """,
        (
            dataset_id, harvest["release_key"], harvest["source_version"],
            harvest["published_at"], harvest["harvested_at"], harvest["source_uri"],
            source_hash, "Immutable authoritative county boundary and grid source.",
        ),
    ).lastrowid
    connection.execute(
        "UPDATE harvest_run SET candidate_release_id = ? WHERE run_id = ?",
        (release_id, run_id),
    )
    connection.executemany(
        """
        INSERT INTO source_file(
            release_id, relative_path, media_type, byte_length, sha256, preserved_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            (release_id, geojson.name, "application/geo+json", len(raw), source_hash, now),
            (
                release_id, manifest_file.name, "application/json", len(manifest_raw),
                sha256_bytes(manifest_raw), now,
            ),
        ],
    )
    bounds = boundary["bounds"]
    connection.execute(
        """
        INSERT INTO source_county_boundary(
            release_id, source_feature_id, source_ordinal, geometry,
            geometry_type, geometry_sha256, attributes_json,
            attributes_sha256, content_sha256, min_x, min_y, max_x, max_y
        ) VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            release_id, boundary["source_feature_id"], boundary["geometry"],
            boundary["geometry_type"], boundary["geometry_sha256"],
            boundary["attributes_json"], boundary["attributes_sha256"],
            boundary["content_sha256"], *bounds,
        ),
    )
    connection.execute(
        """UPDATE gpkg_contents SET last_change = ?, min_x = ?, min_y = ?,
           max_x = ?, max_y = ? WHERE table_name = 'source_county_boundary'""",
        (now, *bounds),
    )
    connection.execute(
        "UPDATE county SET canonical_srs_id = ? WHERE fips_code = '17089'", (SRS_ID,)
    )
    calibration = county_grid.calibrate_connection(connection, geojson, release_id)
    spatial = county_spatial.index_building_release(
        connection, accepted_building_release(connection), None, now
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
    return {
        "release_id": release_id,
        "release_key": harvest["release_key"],
        "boundary_sha256": source_hash,
        "boundary_feature_id": boundary["source_feature_id"],
        **calibration,
        **spatial,
    }


def accept_harvested_boundary(
    database: Path,
    profile: Path,
    geojson: Path,
    manifest_file: Path | None = None,
) -> dict[str, object]:
    import county_building_refresh
    import county_db

    harvest = county_harvest.validate_harvest(profile, geojson, manifest_file)
    manifest = Path(harvest["manifest"])
    if not database.is_file():
        raise RuntimeError(f"Accepted database does not exist: {database}")
    database.parent.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(
        prefix=f".{database.name}.", suffix=".boundary-candidate", dir=database.parent
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
                result = import_boundary(connection, geojson, manifest, harvest)
        finally:
            connection.close()
        errors = county_db.validate_authoritative_database(candidate)
        if errors:
            raise RuntimeError(
                "Authoritative boundary candidate failed validation:\n- " + "\n- ".join(errors)
            )
        os.replace(candidate, database)
        info = county_db.database_info(database)
        info["accepted_boundary_harvest"] = harvest
        info["boundary_acceptance_result"] = result
        return info
    finally:
        candidate.unlink(missing_ok=True)


def geometry_blob_error(blob: bytes) -> str | None:
    if len(blob) < 45:
        return "geometry BLOB is shorter than the GeoPackage header and WKB type"
    if blob[:2] != b"GP" or blob[2] != 0 or blob[3] != 3:
        return "geometry BLOB has an invalid GeoPackage header"
    if struct.unpack("<i", blob[4:8])[0] != SRS_ID:
        return "geometry BLOB uses an unexpected SRS"
    if blob[40] != 1 or struct.unpack("<I", blob[41:45])[0] not in (3, 6):
        return "geometry WKB is not little-endian Polygon or MultiPolygon"
    return None


def boundary_errors(connection: sqlite3.Connection, require_accepted: bool) -> list[str]:
    errors: list[str] = []
    contents = connection.execute(
        "SELECT data_type, srs_id FROM gpkg_contents WHERE table_name = 'source_county_boundary'"
    ).fetchall()
    if contents != [("features", SRS_ID)]:
        errors.append("source_county_boundary is not correctly registered in gpkg_contents.")
    columns = connection.execute(
        """SELECT column_name, geometry_type_name, srs_id, z, m
           FROM gpkg_geometry_columns WHERE table_name = 'source_county_boundary'"""
    ).fetchall()
    if columns != [("geometry", "GEOMETRY", SRS_ID, 0, 0)]:
        errors.append("source_county_boundary is not registered in gpkg_geometry_columns.")
    releases = connection.execute(
        """
        SELECT r.release_id, r.release_key, r.content_sha256, r.source_version
        FROM source_release r JOIN dataset d ON d.dataset_id = r.dataset_id
        WHERE d.dataset_key = ? AND r.status = 'accepted'
        """,
        (DATASET_KEY,),
    ).fetchall()
    if require_accepted and len(releases) != 1:
        errors.append(f"Accepted county-boundary release count is {len(releases)}; expected 1.")
    if not releases:
        count = connection.execute("SELECT COUNT(*) FROM source_county_boundary").fetchone()[0]
        if count:
            errors.append("County-boundary features exist without an accepted release.")
        return errors
    if len(releases) != 1:
        errors.append(f"Accepted county-boundary release count is {len(releases)}; expected 1.")
        return errors
    release_id, release_key, release_hash, source_version = releases[0]
    prefix = "arcgis-profile-sha256:"
    profile_hash = source_version[len(prefix):] if isinstance(source_version, str) and source_version.startswith(prefix) else ""
    if len(profile_hash) != 64 or any(char not in "0123456789abcdef" for char in profile_hash):
        errors.append(f"County-boundary release {release_key} ArcGIS profile hash is invalid.")
    rows = connection.execute(
        """
        SELECT source_feature_id, geometry, geometry_sha256, attributes_json,
               attributes_sha256, content_sha256, min_x, min_y, max_x, max_y
        FROM source_county_boundary WHERE release_id = ?
        """,
        (release_id,),
    ).fetchall()
    if len(rows) != 1:
        errors.append(
            f"County-boundary release {release_key} contains {len(rows)} features; expected 1."
        )
        return errors
    source_id, blob, geometry_hash, attributes_json, attributes_hash, content_hash, *bounds = rows[0]
    blob_error = geometry_blob_error(blob)
    if blob_error:
        errors.append(f"County-boundary release {release_key} {blob_error}.")
    else:
        if sha256_bytes(blob[40:]) != geometry_hash:
            errors.append(f"County-boundary release {release_key} geometry hash is invalid.")
        envelope = struct.unpack("<dddd", blob[8:40])
        if bounds != [envelope[0], envelope[2], envelope[1], envelope[3]]:
            errors.append(f"County-boundary release {release_key} bounds do not match geometry.")
    try:
        attributes = json.loads(attributes_json)
    except json.JSONDecodeError:
        attributes = None
    if not isinstance(attributes, dict):
        errors.append(f"County-boundary release {release_key} attributes are invalid JSON.")
    elif sha256_bytes(canonical_json(attributes).encode("utf-8")) != attributes_hash:
        errors.append(f"County-boundary release {release_key} attribute hash is invalid.")
    expected_content = sha256_bytes(canonical_json({
        "source_feature_id": source_id,
        "geometry_sha256": geometry_hash,
        "attributes_sha256": attributes_hash,
    }).encode("utf-8"))
    if content_hash != expected_content:
        errors.append(f"County-boundary release {release_key} content hash is invalid.")
    files = connection.execute(
        """SELECT relative_path, media_type, byte_length, sha256 FROM source_file
           WHERE release_id = ? ORDER BY source_file_id""",
        (release_id,),
    ).fetchall()
    geojson_files = [item for item in files if item[1] == "application/geo+json"]
    manifest_files = [item for item in files if item[1] == "application/json"]
    if len(files) != 2 or len(geojson_files) != 1 or len(manifest_files) != 1:
        errors.append(f"County-boundary release {release_key} source-file provenance is incomplete.")
        return errors
    geojson_file = geojson_files[0]
    if geojson_file[3] != release_hash:
        errors.append(f"County-boundary release {release_key} source-file hash is invalid.")
    calibration = connection.execute(
        """
        SELECT boundary_release_id, boundary_relative_path, boundary_sha256,
               boundary_byte_length, raw_min_x, raw_min_y, raw_max_x, raw_max_y
        FROM classification_grid_calibration
        """
    ).fetchall()
    expected = (release_id, geojson_file[0], release_hash, geojson_file[2], *bounds)
    if calibration != [expected]:
        errors.append(
            f"County-boundary release {release_key} is not the exact grid-calibration source."
        )
    canonical_srs = connection.execute(
        "SELECT canonical_srs_id FROM county WHERE fips_code = '17089'"
    ).fetchone()[0]
    if canonical_srs != SRS_ID:
        errors.append("Kane County canonical_srs_id is not EPSG:4326 after boundary acceptance.")
    return errors


def boundary_info(path: Path) -> dict[str, Any]:
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        row = connection.execute(
            """
            SELECT r.release_id, r.release_key, r.source_published_at, r.harvested_at,
                   r.accepted_at, r.source_uri, r.content_sha256,
                   b.source_feature_id, b.geometry_type,
                   b.min_x, b.min_y, b.max_x, b.max_y
            FROM source_release r JOIN dataset d ON d.dataset_id = r.dataset_id
            JOIN source_county_boundary b ON b.release_id = r.release_id
            WHERE d.dataset_key = ? AND r.status = 'accepted'
            """,
            (DATASET_KEY,),
        ).fetchone()
        if row is None:
            return {}
        files = connection.execute(
            """SELECT relative_path, media_type, byte_length, sha256
               FROM source_file WHERE release_id = ? ORDER BY source_file_id""",
            (row[0],),
        ).fetchall()
        return {"accepted_boundary": {
            "release_key": row[1],
            "source_published_at": row[2],
            "harvested_at": row[3],
            "accepted_at": row[4],
            "source_uri": row[5],
            "content_sha256": row[6],
            "source_feature_id": row[7],
            "geometry_type": row[8],
            "bounds": {"min_x": row[9], "min_y": row[10], "max_x": row[11], "max_y": row[12]},
            "srs_id": SRS_ID,
            "source_files": [
                {"relative_path": item[0], "media_type": item[1],
                 "byte_length": item[2], "sha256": item[3]}
                for item in files
            ],
        }}
    finally:
        connection.close()
