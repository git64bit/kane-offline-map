#!/usr/bin/env python3
"""Export open review cells as one deterministic bundle split by county sector."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

import county_grid
import county_review_export

INDEX_SCHEMA = "kane-offline-map-open-review-bundle"
SECTOR_SCHEMA = "kane-offline-map-open-review-sector"
SCHEMA_VERSION = 1
SECTOR_CODES = tuple(
    f"N{north}-E{east:02d}"
    for north in range(11, 15)
    for east in range(6, 10)
)
INDEX_NAME = "index.json"
SECTOR_DIRECTORY = "sectors"


def canonical_bytes(value: Any) -> bytes:
    return county_review_export.canonical_bytes(value)


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path: Path) -> str:
    return county_review_export.sha256_file(path)


def sector_document(
    source: dict[str, Any], sector_id: str, features: list[dict[str, Any]]
) -> dict[str, Any]:
    review_count = sum(feature["properties"]["review_count"] for feature in features)
    return {
        "type": "FeatureCollection",
        "name": f"Kane Offline Map open review cells — {sector_id}",
        "schema": SECTOR_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "sector_id": sector_id,
        "generated_at": source["generated_at"],
        "source_database": source["source_database"],
        "accepted_releases": source["accepted_releases"],
        "calibration": source["calibration"],
        "summary": {
            "open_review_count": review_count,
            "review_cell_count": len(features),
        },
        "features": features,
    }


def validate_feature(feature: Any, sector_id: str, cell_ids: set[str]) -> list[str]:
    errors: list[str] = []
    if not isinstance(feature, dict) or feature.get("type") != "Feature":
        return [f"Sector {sector_id} contains an invalid feature."]
    properties = feature.get("properties")
    geometry = feature.get("geometry")
    if not isinstance(properties, dict) or not isinstance(geometry, dict):
        return [f"Sector {sector_id} feature properties or geometry are missing."]
    cell_id = properties.get("cell_id")
    if not isinstance(cell_id, str) or cell_id in cell_ids:
        errors.append(f"Sector {sector_id} contains a missing or duplicate cell identity.")
    else:
        cell_ids.add(cell_id)
    if properties.get("sector_id") != sector_id:
        errors.append(f"Sector file {sector_id} contains a feature from another sector.")
    count = properties.get("review_count")
    review_ids = properties.get("review_ids")
    building_ids = properties.get("building_ids")
    if not isinstance(count, int) or count <= 0:
        errors.append(f"Sector {sector_id} cell {cell_id} has an invalid review count.")
    else:
        if not isinstance(review_ids, list) or len(review_ids) != count:
            errors.append(f"Sector {sector_id} cell {cell_id} review identifiers are inconsistent.")
        if not isinstance(building_ids, list) or len(building_ids) != count:
            errors.append(f"Sector {sector_id} cell {cell_id} building identifiers are inconsistent.")
    if geometry.get("type") != "Polygon" or not isinstance(geometry.get("coordinates"), list):
        errors.append(f"Sector {sector_id} cell {cell_id} geometry is invalid.")
    return errors


def validate_sector_document(
    document: Any,
    expected_sector: str,
    expected_context: dict[str, Any],
    cell_ids: set[str],
) -> tuple[list[str], int, int]:
    errors: list[str] = []
    if not isinstance(document, dict):
        return [f"Sector {expected_sector} root is not an object."], 0, 0
    if document.get("type") != "FeatureCollection":
        errors.append(f"Sector {expected_sector} is not a GeoJSON FeatureCollection.")
    if document.get("schema") != SECTOR_SCHEMA or document.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"Sector {expected_sector} schema identity is invalid.")
    if document.get("sector_id") != expected_sector:
        errors.append(f"Sector file identity does not match {expected_sector}.")
    for key in ("generated_at", "source_database", "accepted_releases", "calibration"):
        if document.get(key) != expected_context.get(key):
            errors.append(f"Sector {expected_sector} {key} does not match the bundle index.")
    features = document.get("features")
    summary = document.get("summary")
    if not isinstance(features, list) or not isinstance(summary, dict):
        return errors + [f"Sector {expected_sector} features or summary are missing."], 0, 0
    review_count = 0
    for feature in features:
        errors.extend(validate_feature(feature, expected_sector, cell_ids))
        if isinstance(feature, dict) and isinstance(feature.get("properties"), dict):
            count = feature["properties"].get("review_count")
            if isinstance(count, int) and count > 0:
                review_count += count
    if summary.get("review_cell_count") != len(features):
        errors.append(f"Sector {expected_sector} cell summary count is inconsistent.")
    if summary.get("open_review_count") != review_count:
        errors.append(f"Sector {expected_sector} review summary count is inconsistent.")
    return errors, len(features), review_count


def read_canonical_json(path: Path, label: str) -> tuple[Any | None, list[str], bytes]:
    try:
        raw = path.read_bytes()
        document = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, [f"Cannot read {label}: {exc}"], b""
    errors = [] if canonical_bytes(document) == raw else [f"{label} is not canonical JSON."]
    return document, errors, raw


def validate_bundle(path: Path) -> list[str]:
    errors: list[str] = []
    if not path.is_dir():
        return [f"Review bundle directory does not exist: {path}"]
    index_path = path / INDEX_NAME
    index, index_errors, _ = read_canonical_json(index_path, "Review bundle index")
    errors.extend(index_errors)
    if not isinstance(index, dict):
        return errors + ["Review bundle index root is not an object."]
    if index.get("schema") != INDEX_SCHEMA or index.get("schema_version") != SCHEMA_VERSION:
        errors.append("Review bundle index schema identity is invalid.")
    sectors = index.get("sectors")
    summary = index.get("summary")
    if not isinstance(sectors, list) or not isinstance(summary, dict):
        return errors + ["Review bundle index sectors or summary are missing."]
    listed_codes = [item.get("sector_id") for item in sectors if isinstance(item, dict)]
    if listed_codes != list(SECTOR_CODES):
        errors.append("Review bundle sector registry is incomplete or out of order.")
    expected_context = {
        key: index.get(key)
        for key in ("generated_at", "source_database", "accepted_releases", "calibration")
    }
    total_cells = 0
    total_reviews = 0
    nonempty = 0
    sector_cell_counts: dict[str, int] = {}
    cell_ids: set[str] = set()
    for item in sectors:
        if not isinstance(item, dict):
            errors.append("Review bundle contains an invalid sector registry item.")
            continue
        sector_id = item.get("sector_id")
        if sector_id not in SECTOR_CODES:
            errors.append(f"Review bundle contains an invalid sector identity: {sector_id}")
            continue
        expected_relative = f"{SECTOR_DIRECTORY}/{sector_id}.geojson"
        if item.get("relative_path") != expected_relative:
            errors.append(f"Sector {sector_id} relative path is invalid.")
        sector_path = path / expected_relative
        document, file_errors, raw = read_canonical_json(sector_path, f"Sector {sector_id}")
        errors.extend(file_errors)
        if not raw:
            continue
        if item.get("byte_length") != len(raw):
            errors.append(f"Sector {sector_id} byte length does not match the index.")
        if item.get("sha256") != sha256_bytes(raw):
            errors.append(f"Sector {sector_id} hash does not match the index.")
        sector_errors, cell_count, review_count = validate_sector_document(
            document, sector_id, expected_context, cell_ids
        )
        errors.extend(sector_errors)
        if item.get("review_cell_count") != cell_count:
            errors.append(f"Sector {sector_id} cell count does not match the index.")
        if item.get("open_review_count") != review_count:
            errors.append(f"Sector {sector_id} review count does not match the index.")
        total_cells += cell_count
        total_reviews += review_count
        sector_cell_counts[sector_id] = cell_count
        if cell_count:
            nonempty += 1
    expected_summary = {
        "open_review_count": total_reviews,
        "review_cell_count": total_cells,
        "sector_file_count": len(SECTOR_CODES),
        "nonempty_sector_count": nonempty,
    }
    for key, value in expected_summary.items():
        if summary.get(key) != value:
            errors.append(f"Review bundle summary field {key} is inconsistent.")
    if summary.get("sector_cell_counts") != sector_cell_counts:
        errors.append("Review bundle sector cell counts are inconsistent.")
    return errors


def write_candidate(database: Path, candidate: Path, generated_at: str) -> dict[str, Any]:
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    try:
        source = county_review_export.build_document(database, connection, generated_at)
    finally:
        connection.close()
    by_sector = {sector: [] for sector in SECTOR_CODES}
    for feature in source["features"]:
        sector_id = feature["properties"]["sector_id"]
        if sector_id not in by_sector:
            raise RuntimeError(f"Open review uses unexpected sector identity: {sector_id}")
        by_sector[sector_id].append(feature)
    sector_root = candidate / SECTOR_DIRECTORY
    sector_root.mkdir(parents=True)
    registry: list[dict[str, Any]] = []
    sector_cell_counts: dict[str, int] = {}
    total_bytes = 0
    nonempty = 0
    for sector_id in SECTOR_CODES:
        document = sector_document(source, sector_id, by_sector[sector_id])
        raw = canonical_bytes(document)
        relative_path = f"{SECTOR_DIRECTORY}/{sector_id}.geojson"
        (candidate / relative_path).write_bytes(raw)
        cell_count = document["summary"]["review_cell_count"]
        sector_cell_counts[sector_id] = cell_count
        if cell_count:
            nonempty += 1
        total_bytes += len(raw)
        registry.append({
            "sector_id": sector_id,
            "relative_path": relative_path,
            "open_review_count": document["summary"]["open_review_count"],
            "review_cell_count": cell_count,
            "byte_length": len(raw),
            "sha256": sha256_bytes(raw),
        })
    index = {
        "schema": INDEX_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "generated_at": source["generated_at"],
        "source_database": source["source_database"],
        "accepted_releases": source["accepted_releases"],
        "calibration": source["calibration"],
        "summary": {
            "open_review_count": source["summary"]["open_review_count"],
            "review_cell_count": source["summary"]["review_cell_count"],
            "sector_file_count": len(SECTOR_CODES),
            "nonempty_sector_count": nonempty,
            "sector_cell_counts": sector_cell_counts,
        },
        "sectors": registry,
    }
    index_raw = canonical_bytes(index)
    (candidate / INDEX_NAME).write_bytes(index_raw)
    total_bytes += len(index_raw)
    return {
        "document": index,
        "index_raw": index_raw,
        "bundle_byte_length": total_bytes,
    }


def promote_directory(candidate: Path, output: Path, force: bool) -> None:
    backup_root: Path | None = None
    backup: Path | None = None
    if output.exists():
        if not force:
            raise RuntimeError(f"Review bundle already exists: {output}")
        backup_root = Path(tempfile.mkdtemp(prefix=f".{output.name}.backup.", dir=output.parent))
        backup = backup_root / "accepted"
        os.replace(output, backup)
    try:
        os.replace(candidate, output)
    except Exception:
        if backup is not None and backup.exists() and not output.exists():
            os.replace(backup, output)
        raise
    finally:
        if backup_root is not None:
            shutil.rmtree(backup_root, ignore_errors=True)


def export_open_review_bundle(
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
        raise RuntimeError(f"Review bundle already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    generated_at = generated_at or county_grid.utc_now()
    candidate = Path(tempfile.mkdtemp(
        prefix=f".{output.name}.", suffix=".candidate", dir=output.parent
    ))
    try:
        result = write_candidate(database, candidate, generated_at)
        candidate_errors = validate_bundle(candidate)
        if candidate_errors:
            raise RuntimeError(
                "Open-review bundle candidate failed validation:\n- "
                + "\n- ".join(candidate_errors)
            )
        promote_directory(candidate, output, force)
    finally:
        if candidate.exists():
            shutil.rmtree(candidate, ignore_errors=True)
    index = result["document"]
    summary = index["summary"]
    return {
        "valid": True,
        "output": str(output),
        "index": str(output / INDEX_NAME),
        "index_byte_length": len(result["index_raw"]),
        "index_sha256": sha256_bytes(result["index_raw"]),
        "bundle_byte_length": result["bundle_byte_length"],
        **summary,
        "accepted_releases": index["accepted_releases"],
    }
