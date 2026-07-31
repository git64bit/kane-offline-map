#!/usr/bin/env python3
"""Export open spatial review cells from an authoritative GeoPackage."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

import county_grid

SCHEMA = "kane-offline-map-open-review-cells"
SCHEMA_VERSION = 1


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def accepted_release(
    connection: sqlite3.Connection, dataset_key: str
) -> tuple[str, str]:
    row = connection.execute(
        """
        SELECT r.release_key, r.content_sha256
        FROM source_release r
        JOIN dataset d ON d.dataset_id = r.dataset_id
        WHERE d.dataset_key = ? AND r.status = 'accepted'
        """,
        (dataset_key,),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"Accepted {dataset_key} release is missing.")
    return row[0], row[1]


def accepted_classification(connection: sqlite3.Connection) -> tuple[str, str]:
    row = connection.execute(
        """
        SELECT release_key, source_archive_sha256
        FROM classification_release WHERE status = 'accepted'
        """
    ).fetchone()
    if row is None:
        raise RuntimeError("Accepted classification release is missing.")
    return row[0], row[1]


def review_rows(connection: sqlite3.Connection) -> list[tuple[Any, ...]]:
    return connection.execute(
        """
        SELECT c.cell_id, c.sector_id, c.global_row, c.global_column,
               c.classification, s.min_x, s.min_y, s.max_x, s.max_y,
               r.review_id, r.trigger_source_feature_id, r.detected_at,
               r.detected_in_release_id
        FROM classification_review r
        JOIN dataset d ON d.dataset_id = r.trigger_dataset_id
        JOIN classification_cell c
          ON c.classification_release_id = r.classification_release_id
         AND c.cell_id = r.cell_id
        JOIN classification_cell_spatial s
          ON s.classification_release_id = c.classification_release_id
         AND s.cell_id = c.cell_id
        WHERE d.dataset_key = 'buildings' AND r.review_status = 'open'
        ORDER BY c.global_row, c.global_column,
                 r.trigger_source_feature_id, r.review_id
        """
    ).fetchall()


def rectangle(min_x: float, min_y: float, max_x: float, max_y: float) -> dict[str, Any]:
    return {
        "type": "Polygon",
        "coordinates": [[
            [min_x, min_y],
            [max_x, min_y],
            [max_x, max_y],
            [min_x, max_y],
            [min_x, min_y],
        ]],
    }


def build_document(
    database: Path,
    connection: sqlite3.Connection,
    generated_at: str,
) -> dict[str, Any]:
    rows = review_rows(connection)
    grouped: list[dict[str, Any]] = []
    current_key: tuple[int, int] | None = None
    current: dict[str, Any] | None = None
    sector_counts: Counter[str] = Counter()

    for row in rows:
        (
            cell_id, sector_id, global_row, global_column, classification,
            min_x, min_y, max_x, max_y, review_id, source_id, detected_at,
            detected_release_id,
        ) = row
        key = (global_row, global_column)
        if key != current_key:
            current = {
                "type": "Feature",
                "id": cell_id,
                "geometry": rectangle(min_x, min_y, max_x, max_y),
                "properties": {
                    "cell_id": cell_id,
                    "sector_id": sector_id,
                    "global_row": global_row,
                    "global_column": global_column,
                    "classification": classification,
                    "review_count": 0,
                    "review_ids": [],
                    "building_ids": [],
                    "first_detected_at": detected_at,
                    "detected_in_release_ids": [],
                },
            }
            grouped.append(current)
            current_key = key
            sector_counts[sector_id] += 1
        assert current is not None
        properties = current["properties"]
        properties["review_count"] += 1
        properties["review_ids"].append(review_id)
        properties["building_ids"].append(source_id)
        if detected_at < properties["first_detected_at"]:
            properties["first_detected_at"] = detected_at
        if detected_release_id not in properties["detected_in_release_ids"]:
            properties["detected_in_release_ids"].append(detected_release_id)

    classification_key, classification_hash = accepted_classification(connection)
    building_key, building_hash = accepted_release(connection, "buildings")
    boundary_key, boundary_hash = accepted_release(connection, "county-boundary")
    calibration = connection.execute(
        """
        SELECT boundary_sha256, raw_min_x, raw_min_y, raw_max_x, raw_max_y,
               calibrated_at
        FROM classification_grid_calibration
        """
    ).fetchone()
    if calibration is None:
        raise RuntimeError("Accepted classification grid calibration is missing.")

    return {
        "type": "FeatureCollection",
        "name": "Kane Offline Map open review cells",
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "source_database": {
            "path": str(database),
            "byte_length": database.stat().st_size,
            "sha256": sha256_file(database),
        },
        "accepted_releases": {
            "classification": {
                "release_key": classification_key,
                "source_archive_sha256": classification_hash,
            },
            "buildings": {
                "release_key": building_key,
                "content_sha256": building_hash,
            },
            "county_boundary": {
                "release_key": boundary_key,
                "content_sha256": boundary_hash,
            },
        },
        "calibration": {
            "boundary_sha256": calibration[0],
            "bounds": {
                "min_x": calibration[1],
                "min_y": calibration[2],
                "max_x": calibration[3],
                "max_y": calibration[4],
            },
            "calibrated_at": calibration[5],
            "srs_id": county_grid.SRS_ID,
        },
        "summary": {
            "open_review_count": len(rows),
            "review_cell_count": len(grouped),
            "sector_cell_counts": dict(sorted(sector_counts.items())),
        },
        "features": grouped,
    }


def validate_document(document: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if document.get("type") != "FeatureCollection":
        errors.append("Review export is not a GeoJSON FeatureCollection.")
    if document.get("schema") != SCHEMA or document.get("schema_version") != SCHEMA_VERSION:
        errors.append("Review export schema identity is invalid.")
    features = document.get("features")
    summary = document.get("summary")
    if not isinstance(features, list) or not isinstance(summary, dict):
        return errors + ["Review export features or summary are missing."]
    cell_ids: set[str] = set()
    review_total = 0
    for feature in features:
        if not isinstance(feature, dict) or feature.get("type") != "Feature":
            errors.append("Review export contains an invalid feature.")
            continue
        properties = feature.get("properties")
        geometry = feature.get("geometry")
        if not isinstance(properties, dict) or not isinstance(geometry, dict):
            errors.append("Review export feature properties or geometry are missing.")
            continue
        cell_id = properties.get("cell_id")
        if not isinstance(cell_id, str) or cell_id in cell_ids:
            errors.append("Review export cell identities are missing or duplicated.")
        else:
            cell_ids.add(cell_id)
        count = properties.get("review_count")
        review_ids = properties.get("review_ids")
        building_ids = properties.get("building_ids")
        if not isinstance(count, int) or count <= 0:
            errors.append(f"Review export cell {cell_id} has an invalid review count.")
            continue
        if not isinstance(review_ids, list) or len(review_ids) != count:
            errors.append(f"Review export cell {cell_id} review identifiers are inconsistent.")
        if not isinstance(building_ids, list) or len(building_ids) != count:
            errors.append(f"Review export cell {cell_id} building identifiers are inconsistent.")
        review_total += count
        coordinates = geometry.get("coordinates")
        if geometry.get("type") != "Polygon" or not isinstance(coordinates, list):
            errors.append(f"Review export cell {cell_id} geometry is invalid.")
    if summary.get("review_cell_count") != len(features):
        errors.append("Review export cell summary count is inconsistent.")
    if summary.get("open_review_count") != review_total:
        errors.append("Review export review summary count is inconsistent.")
    return errors


def validate_export(path: Path) -> list[str]:
    try:
        raw = path.read_bytes()
        document = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return [f"Cannot read review export: {exc}"]
    if not isinstance(document, dict):
        return ["Review export root is not an object."]
    errors = validate_document(document)
    if canonical_bytes(document) != raw:
        errors.append("Review export is not canonical JSON.")
    return errors


def export_open_reviews(
    database: Path,
    output: Path,
    force: bool = False,
    generated_at: str | None = None,
) -> dict[str, Any]:
    import county_db

    errors = county_db.validate_authoritative_database(database)
    if errors:
        raise RuntimeError("Authoritative database is invalid:\n- " + "\n- ".join(errors))
    if output.exists() and not force:
        raise RuntimeError(f"Review export already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    generated_at = generated_at or county_grid.utc_now()
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    try:
        document = build_document(database, connection, generated_at)
    finally:
        connection.close()
    raw = canonical_bytes(document)
    handle, name = tempfile.mkstemp(
        prefix=f".{output.name}.", suffix=".candidate", dir=output.parent
    )
    candidate = Path(name)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        candidate_errors = validate_export(candidate)
        if candidate_errors:
            raise RuntimeError(
                "Open-review export candidate failed validation:\n- "
                + "\n- ".join(candidate_errors)
            )
        os.replace(candidate, output)
    finally:
        candidate.unlink(missing_ok=True)
    summary = document["summary"]
    return {
        "valid": True,
        "output": str(output),
        "byte_length": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        **summary,
        "accepted_releases": document["accepted_releases"],
    }
