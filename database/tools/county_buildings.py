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

import county_building_refresh
import county_spatial

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
    harvested_at: str | None = None,
    source_version: str | None = None,
    manifest_file: Path | None = None,
) -> dict[str, Any]:
    raw, source_features = load_features(geojson)
    buildings = normalize_features(source_features, id_property)
    source_hash = sha256_bytes(raw)
    chosen_key = release_key or f"buildings-{source_hash[:12]}"
    now = utc_now()
    source_harvested_at = harvested_at or now
    manifest_raw = manifest_file.read_bytes() if manifest_file else None
    connection = sqlite3.connect(database)
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        with connection:
            dataset_id = ensure_dataset(connection, id_property, now)
            accepted = connection.execute(
                """
                SELECT release_id, release_key FROM source_release
                WHERE dataset_id = ? AND status = 'accepted'
                """,
                (dataset_id,),
            ).fetchone()
            previous_release_id = accepted[0] if accepted else None
            duplicate = connection.execute(
                "SELECT release_key FROM source_release WHERE dataset_id = ? AND (release_key = ? OR content_sha256 = ?)",
                (dataset_id, chosen_key, source_hash),
            ).fetchone()
            if duplicate:
                raise RuntimeError(f"Building source release already imported: {duplicate[0]}")
            run_cursor = connection.execute(
                """
                INSERT INTO harvest_run(
                    dataset_id, previous_release_id, started_at, status, tool_version
                ) VALUES (?, ?, ?, 'started', ?)
                """,
                (dataset_id, previous_release_id, now, "batch-012.0"),
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
                    source_version,
                    published_at,
                    source_harvested_at,
                    source_uri,
                    source_hash,
                    "Immutable building release import with refresh comparison when applicable.",
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
            if manifest_file is not None and manifest_raw is not None:
                connection.execute(
                    """
                    INSERT INTO source_file(
                        release_id, relative_path, media_type, byte_length, sha256, preserved_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        release_id,
                        manifest_file.name,
                        "application/json",
                        len(manifest_raw),
                        sha256_bytes(manifest_raw),
                        now,
                    ),
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
            extent = connection.execute(
                "SELECT MIN(min_x), MIN(min_y), MAX(max_x), MAX(max_y) FROM source_building"
            ).fetchone()
            connection.execute(
                """
                UPDATE gpkg_contents
                SET last_change = ?, min_x = ?, min_y = ?, max_x = ?, max_y = ?
                WHERE table_name = 'source_building'
                """,
                (now, *extent),
            )
            if previous_release_id is not None:
                county_building_refresh.compare_releases(
                    connection, run_id, previous_release_id, release_id, now
                )
                connection.execute(
                    """
                    UPDATE source_release
                    SET status = 'superseded', superseded_at = ?
                    WHERE release_id = ?
                    """,
                    (now, previous_release_id),
                )
            spatial_result = county_spatial.index_building_release(
                connection,
                release_id,
                county_spatial.review_source_ids_for_release(connection, release_id),
                now,
            )
            release_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(source_release)")
            }
            if "superseded_at" in release_columns:
                connection.execute(
                    """
                    UPDATE source_release
                    SET status = 'accepted', accepted_at = ?, superseded_at = NULL
                    WHERE release_id = ?
                    """,
                    (now, release_id),
                )
            else:
                connection.execute(
                    """
                    UPDATE source_release SET status = 'accepted', accepted_at = ?
                    WHERE release_id = ?
                    """,
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
        return {
            "release_key": chosen_key,
            "feature_count": len(buildings),
            "harvested_at": source_harvested_at,
            "source_version": source_version,
            "manifest_sha256": sha256_bytes(manifest_raw) if manifest_raw is not None else None,
            **spatial_result,
        }
    finally:
        connection.close()
