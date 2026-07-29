#!/usr/bin/env python3
"""Import and validate immutable building GeoJSON releases."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import sqlite3
import struct
from pathlib import Path
from typing import Any, Iterable

SRS_ID = 4326
AGENCY_KEY = "kane-county-gis"
DATASET_KEY = "buildings"
COMMON_ID_PROPERTIES = (
    "id",
    "OBJECTID",
    "objectid",
    "ObjectID",
    "FID",
    "fid",
    "building_id",
    "BUILDING_ID",
)


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def feature_id(feature: dict[str, Any], id_property: str | None) -> str:
    properties = feature.get("properties") or {}
    candidates: list[Any] = []
    if id_property:
        candidates.append(properties.get(id_property))
    candidates.append(feature.get("id"))
    if not id_property:
        candidates.extend(properties.get(key) for key in COMMON_ID_PROPERTIES)
    for candidate in candidates:
        if candidate is None:
            continue
        value = str(candidate).strip()
        if value:
            return value
    detail = f" property {id_property!r}" if id_property else " feature.id or a recognized ID property"
    raise RuntimeError(f"Building feature is missing{detail}.")


def normalize_position(value: Any) -> tuple[float, float]:
    if not isinstance(value, list) or len(value) != 2:
        raise RuntimeError("Building coordinates must contain exactly two ordinates.")
    x = float(value[0])
    y = float(value[1])
    if not math.isfinite(x) or not math.isfinite(y):
        raise RuntimeError("Building coordinates must be finite numbers.")
    if not -180.0 <= x <= 180.0 or not -90.0 <= y <= 90.0:
        raise RuntimeError("Building coordinates must be EPSG:4326 longitude/latitude values.")
    return x, y


def normalize_ring(value: Any) -> list[tuple[float, float]]:
    if not isinstance(value, list):
        raise RuntimeError("Polygon ring is not an array.")
    ring = [normalize_position(position) for position in value]
    if len(ring) < 4:
        raise RuntimeError("Polygon ring must contain at least four positions.")
    if ring[0] != ring[-1]:
        raise RuntimeError("Polygon ring is not closed.")
    return ring


def normalize_polygon(value: Any) -> list[list[tuple[float, float]]]:
    if not isinstance(value, list) or not value:
        raise RuntimeError("Polygon must contain at least one ring.")
    return [normalize_ring(ring) for ring in value]


def normalize_geometry(geometry: Any) -> tuple[str, Any]:
    if not isinstance(geometry, dict):
        raise RuntimeError("Building feature has no geometry object.")
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates")
    if geometry_type == "Polygon":
        return geometry_type, normalize_polygon(coordinates)
    if geometry_type == "MultiPolygon":
        if not isinstance(coordinates, list) or not coordinates:
            raise RuntimeError("MultiPolygon must contain at least one polygon.")
        return geometry_type, [normalize_polygon(polygon) for polygon in coordinates]
    raise RuntimeError(f"Unsupported building geometry type: {geometry_type!r}.")


def iter_positions(geometry_type: str, coordinates: Any) -> Iterable[tuple[float, float]]:
    polygons = [coordinates] if geometry_type == "Polygon" else coordinates
    for polygon in polygons:
        for ring in polygon:
            yield from ring


def bounds_for_geometry(geometry_type: str, coordinates: Any) -> tuple[float, float, float, float]:
    positions = list(iter_positions(geometry_type, coordinates))
    xs = [position[0] for position in positions]
    ys = [position[1] for position in positions]
    return min(xs), min(ys), max(xs), max(ys)


def pack_ring(ring: list[tuple[float, float]]) -> bytes:
    body = [struct.pack("<I", len(ring))]
    body.extend(struct.pack("<dd", x, y) for x, y in ring)
    return b"".join(body)


def polygon_wkb(polygon: list[list[tuple[float, float]]]) -> bytes:
    body = [struct.pack("<BI", 1, 3), struct.pack("<I", len(polygon))]
    body.extend(pack_ring(ring) for ring in polygon)
    return b"".join(body)


def geometry_wkb(geometry_type: str, coordinates: Any) -> bytes:
    if geometry_type == "Polygon":
        return polygon_wkb(coordinates)
    body = [struct.pack("<BI", 1, 6), struct.pack("<I", len(coordinates))]
    body.extend(polygon_wkb(polygon) for polygon in coordinates)
    return b"".join(body)


def geopackage_geometry(geometry_type: str, coordinates: Any) -> tuple[bytes, bytes, tuple[float, float, float, float]]:
    bounds = bounds_for_geometry(geometry_type, coordinates)
    wkb = geometry_wkb(geometry_type, coordinates)
    flags = 0b00000011  # little endian, XY envelope, standard non-empty geometry
    header = b"GP" + bytes((0, flags)) + struct.pack("<i", SRS_ID)
    header += struct.pack("<dddd", bounds[0], bounds[2], bounds[1], bounds[3])
    return header + wkb, wkb, bounds


def load_features(path: Path) -> tuple[bytes, list[dict[str, Any]]]:
    raw = path.read_bytes()
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Building source is not valid UTF-8 GeoJSON: {exc}") from exc
    if isinstance(document, dict) and document.get("type") == "FeatureCollection":
        features = document.get("features")
    elif isinstance(document, list):
        features = document
    else:
        raise RuntimeError("Building source must be a GeoJSON FeatureCollection or feature array.")
    if not isinstance(features, list) or not features:
        raise RuntimeError("Building source contains no features.")
    normalized: list[dict[str, Any]] = []
    for ordinal, feature in enumerate(features, start=1):
        if not isinstance(feature, dict) or feature.get("type") != "Feature":
            raise RuntimeError(f"Building item {ordinal} is not a GeoJSON Feature.")
        normalized.append(feature)
    return raw, normalized


def normalize_features(features: list[dict[str, Any]], id_property: str | None) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for ordinal, feature in enumerate(features, start=1):
        source_id = feature_id(feature, id_property)
        if source_id in seen:
            raise RuntimeError(f"Duplicate building source feature id: {source_id}")
        seen.add(source_id)
        geometry_type, coordinates = normalize_geometry(feature.get("geometry"))
        gpkg_blob, wkb, bounds = geopackage_geometry(geometry_type, coordinates)
        properties = feature.get("properties")
        if properties is None:
            properties = {}
        if not isinstance(properties, dict):
            raise RuntimeError(f"Building {source_id} properties are not an object.")
        attributes_json = canonical_json(properties)
        geometry_hash = sha256_bytes(wkb)
        attributes_hash = sha256_bytes(attributes_json.encode("utf-8"))
        content_hash = sha256_bytes(
            canonical_json(
                {
                    "source_feature_id": source_id,
                    "geometry_sha256": geometry_hash,
                    "attributes_sha256": attributes_hash,
                }
            ).encode("utf-8")
        )
        output.append(
            {
                "source_feature_id": source_id,
                "source_ordinal": ordinal,
                "geometry": gpkg_blob,
                "geometry_type": geometry_type,
                "geometry_sha256": geometry_hash,
                "attributes_json": attributes_json,
                "attributes_sha256": attributes_hash,
                "content_sha256": content_hash,
                "bounds": bounds,
            }
        )
    return output


def ensure_dataset(connection: sqlite3.Connection, id_property: str | None, now: str) -> int:
    county_id = connection.execute(
        "SELECT county_id FROM county WHERE fips_code = '17089'"
    ).fetchone()[0]
    connection.execute(
        """
        INSERT INTO source_agency(agency_key, agency_name, jurisdiction, homepage_uri, created_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(agency_key) DO NOTHING
        """,
        (AGENCY_KEY, "Kane County GIS", "Kane County, Illinois", None, now),
    )
    agency_id = connection.execute(
        "SELECT agency_id FROM source_agency WHERE agency_key = ?", (AGENCY_KEY,)
    ).fetchone()[0]
    policy = f"GeoJSON property {id_property}" if id_property else "feature.id or recognized stable property"
    connection.execute(
        """
        INSERT INTO dataset(
            county_id, agency_id, dataset_key, dataset_name, feature_class,
            source_id_policy, description, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(county_id, dataset_key) DO NOTHING
        """,
        (
            county_id,
            agency_id,
            DATASET_KEY,
            "Kane County Buildings",
            "building",
            policy,
            "Countywide building polygons preserved as immutable source releases.",
            now,
        ),
    )
    return connection.execute(
        "SELECT dataset_id FROM dataset WHERE county_id = ? AND dataset_key = ?",
        (county_id, DATASET_KEY),
    ).fetchone()[0]


def import_buildings(
    database: Path,
    geojson: Path,
    release_key: str | None,
    source_uri: str | None,
    published_at: str | None,
    id_property: str | None,
) -> dict[str, Any]:
    raw, source_features = load_features(geojson)
    buildings = normalize_features(source_features, id_property)
    source_hash = sha256_bytes(raw)
    chosen_key = release_key or f"buildings-{source_hash[:12]}"
    now = utc_now()
    connection = sqlite3.connect(database)
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        with connection:
            dataset_id = ensure_dataset(connection, id_property, now)
            accepted = connection.execute(
                "SELECT release_key FROM source_release WHERE dataset_id = ? AND status = 'accepted'",
                (dataset_id,),
            ).fetchone()
            if accepted:
                raise RuntimeError(
                    f"An accepted building release already exists: {accepted[0]}. Refresh diff is not enabled yet."
                )
            duplicate = connection.execute(
                "SELECT release_key FROM source_release WHERE dataset_id = ? AND (release_key = ? OR content_sha256 = ?)",
                (dataset_id, chosen_key, source_hash),
            ).fetchone()
            if duplicate:
                raise RuntimeError(f"Building source release already imported: {duplicate[0]}")
            run_cursor = connection.execute(
                """
                INSERT INTO harvest_run(dataset_id, started_at, status, tool_version)
                VALUES (?, ?, 'started', ?)
                """,
                (dataset_id, now, "batch-008.0"),
            )
            run_id = run_cursor.lastrowid
            release_cursor = connection.execute(
                """
                INSERT INTO source_release(
                    dataset_id, release_key, source_version, source_published_at,
                    harvested_at, source_uri, content_sha256, status, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'candidate', ?)
                """,
                (
                    dataset_id,
                    chosen_key,
                    None,
                    published_at,
                    now,
                    source_uri,
                    source_hash,
                    "Initial immutable building release import.",
                ),
            )
            release_id = release_cursor.lastrowid
            connection.execute(
                "UPDATE harvest_run SET candidate_release_id = ? WHERE run_id = ?",
                (release_id, run_id),
            )
            connection.execute(
                """
                INSERT INTO source_file(
                    release_id, relative_path, media_type, byte_length, sha256, preserved_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (release_id, geojson.name, "application/geo+json", len(raw), source_hash, now),
            )
            connection.executemany(
                """
                INSERT INTO source_building(
                    release_id, source_feature_id, source_ordinal, geometry,
                    geometry_type, geometry_sha256, attributes_json,
                    attributes_sha256, content_sha256, min_x, min_y, max_x, max_y
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        release_id,
                        item["source_feature_id"],
                        item["source_ordinal"],
                        item["geometry"],
                        item["geometry_type"],
                        item["geometry_sha256"],
                        item["attributes_json"],
                        item["attributes_sha256"],
                        item["content_sha256"],
                        item["bounds"][0],
                        item["bounds"][1],
                        item["bounds"][2],
                        item["bounds"][3],
                    )
                    for item in buildings
                ],
            )
            min_x = min(item["bounds"][0] for item in buildings)
            min_y = min(item["bounds"][1] for item in buildings)
            max_x = max(item["bounds"][2] for item in buildings)
            max_y = max(item["bounds"][3] for item in buildings)
            connection.execute(
                """
                UPDATE gpkg_contents
                SET last_change = ?, min_x = ?, min_y = ?, max_x = ?, max_y = ?
                WHERE table_name = 'source_building'
                """,
                (now, min_x, min_y, max_x, max_y),
            )
            connection.execute(
                "UPDATE source_release SET status = 'accepted', accepted_at = ? WHERE release_id = ?",
                (now, release_id),
            )
            connection.execute(
                """
                UPDATE harvest_run
                SET completed_at = ?, status = 'accepted', candidate_release_id = ?
                WHERE run_id = ?
                """,
                (now, release_id, run_id),
            )
        return building_info(database)
    finally:
        connection.close()


def geometry_blob_error(blob: bytes) -> str | None:
    if len(blob) < 45:
        return "geometry BLOB is shorter than the GeoPackage header and WKB type"
    if blob[:2] != b"GP" or blob[2] != 0 or blob[3] != 3:
        return "geometry BLOB has an invalid GeoPackage header"
    if struct.unpack("<i", blob[4:8])[0] != SRS_ID:
        return "geometry BLOB uses an unexpected SRS"
    if blob[40] != 1:
        return "geometry WKB is not little endian"
    geometry_type = struct.unpack("<I", blob[41:45])[0]
    if geometry_type not in (3, 6):
        return "geometry WKB is not Polygon or MultiPolygon"
    return None


def building_errors(connection: sqlite3.Connection, require_accepted: bool) -> list[str]:
    errors: list[str] = []
    contents = connection.execute(
        "SELECT data_type, srs_id FROM gpkg_contents WHERE table_name = 'source_building'"
    ).fetchall()
    if contents != [("features", SRS_ID)]:
        errors.append("source_building is not correctly registered in gpkg_contents.")
    columns = connection.execute(
        """
        SELECT column_name, geometry_type_name, srs_id, z, m
        FROM gpkg_geometry_columns WHERE table_name = 'source_building'
        """
    ).fetchall()
    if columns != [("geometry", "GEOMETRY", SRS_ID, 0, 0)]:
        errors.append("source_building is not correctly registered in gpkg_geometry_columns.")
    accepted_rows = connection.execute(
        """
        SELECT r.release_id, r.release_key, r.content_sha256
        FROM source_release r JOIN dataset d ON d.dataset_id = r.dataset_id
        WHERE d.dataset_key = ? AND r.status = 'accepted'
        """,
        (DATASET_KEY,),
    ).fetchall()
    if require_accepted and len(accepted_rows) != 1:
        errors.append(f"Accepted building release count is {len(accepted_rows)}; expected 1.")
    for release_id, release_key, release_hash in accepted_rows:
        source_files = connection.execute(
            "SELECT sha256 FROM source_file WHERE release_id = ?", (release_id,)
        ).fetchall()
        if source_files != [(release_hash,)]:
            errors.append(f"Building release {release_key} source file hash is inconsistent.")
        count = connection.execute(
            "SELECT COUNT(*) FROM source_building WHERE release_id = ?", (release_id,)
        ).fetchone()[0]
        if count == 0:
            errors.append(f"Building release {release_key} contains no features.")
        for source_id, blob, geometry_hash, attributes_json, attributes_hash, content_hash in connection.execute(
            """
            SELECT source_feature_id, geometry, geometry_sha256, attributes_json,
                   attributes_sha256, content_sha256
            FROM source_building WHERE release_id = ? ORDER BY source_ordinal
            """,
            (release_id,),
        ):
            blob_error = geometry_blob_error(blob)
            if blob_error:
                errors.append(f"Building {source_id} {blob_error}.")
                continue
            wkb_hash = sha256_bytes(blob[40:])
            if geometry_hash != wkb_hash:
                errors.append(f"Building {source_id} geometry hash is inconsistent.")
            try:
                parsed_attributes = json.loads(attributes_json)
                expected_attributes = sha256_bytes(canonical_json(parsed_attributes).encode("utf-8"))
            except (json.JSONDecodeError, TypeError, ValueError):
                errors.append(f"Building {source_id} attributes JSON is invalid.")
                continue
            if attributes_hash != expected_attributes:
                errors.append(f"Building {source_id} attributes hash is inconsistent.")
            expected_content = sha256_bytes(
                canonical_json(
                    {
                        "source_feature_id": source_id,
                        "geometry_sha256": geometry_hash,
                        "attributes_sha256": attributes_hash,
                    }
                ).encode("utf-8")
            )
            if content_hash != expected_content:
                errors.append(f"Building {source_id} content hash is inconsistent.")
    return errors


def building_info(path: Path) -> dict[str, Any]:
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        row = connection.execute(
            """
            SELECT r.release_key, r.source_published_at, r.harvested_at, r.accepted_at,
                   r.source_uri, r.content_sha256, COUNT(b.source_building_id),
                   MIN(b.min_x), MIN(b.min_y), MAX(b.max_x), MAX(b.max_y)
            FROM source_release r
            JOIN dataset d ON d.dataset_id = r.dataset_id
            LEFT JOIN source_building b ON b.release_id = r.release_id
            WHERE d.dataset_key = ? AND r.status = 'accepted'
            GROUP BY r.release_id
            """,
            (DATASET_KEY,),
        ).fetchone()
        if row is None:
            return {}
        return {
            "accepted_buildings": {
                "release_key": row[0],
                "source_published_at": row[1],
                "harvested_at": row[2],
                "accepted_at": row[3],
                "source_uri": row[4],
                "content_sha256": row[5],
                "feature_count": row[6],
                "bounds": {"min_x": row[7], "min_y": row[8], "max_x": row[9], "max_y": row[10]},
                "srs_id": SRS_ID,
            }
        }
    finally:
        connection.close()
