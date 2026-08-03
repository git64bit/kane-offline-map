#!/usr/bin/env python3
"""Export accepted boundary and building releases as deterministic browser GeoJSON."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
from pathlib import Path
from typing import Any, Iterable

import county_geometry

SCHEMA = "kane-offline-map-prepared-core"
SCHEMA_VERSION = 1
MANIFEST_NAME = "core-manifest.json"
BOUNDARY_NAME = "county_boundary.json"
BUILDINGS_NAME = "buildings.json"
DATASET_FILES = (BOUNDARY_NAME, BUILDINGS_NAME)


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


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def database_sha256(path: Path) -> str:
    return sha256_file(path)


def json_coordinates(polygons: list[list[list[tuple[float, float]]]], geometry_type: str) -> list[Any]:
    converted = [
        [[[float(x), float(y)] for x, y in ring] for ring in polygon]
        for polygon in polygons
    ]
    if geometry_type == "Polygon":
        if len(converted) != 1:
            raise RuntimeError("Polygon geometry decoded to an unexpected polygon count.")
        return converted[0]
    if geometry_type == "MultiPolygon":
        return converted
    raise RuntimeError(f"Unsupported prepared geometry type: {geometry_type}")


def accepted_release(connection: sqlite3.Connection, dataset_key: str) -> dict[str, Any]:
    row = connection.execute(
        """
        SELECT r.release_id, r.release_key, r.source_published_at, r.harvested_at,
               r.accepted_at, r.source_uri, r.content_sha256
        FROM source_release r
        JOIN dataset d ON d.dataset_id = r.dataset_id
        WHERE d.dataset_key = ? AND r.status = 'accepted'
        """,
        (dataset_key,),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"Accepted {dataset_key} release is unavailable.")
    keys = (
        "release_id",
        "release_key",
        "source_published_at",
        "harvested_at",
        "accepted_at",
        "source_uri",
        "content_sha256",
    )
    return dict(zip(keys, row))


def feature_document(
    feature_id: str,
    geometry_type: str,
    geometry_blob: bytes,
) -> dict[str, Any]:
    polygons = county_geometry.decode_geometry(geometry_blob)
    return {
        "type": "Feature",
        "id": str(feature_id),
        "properties": {"source_feature_id": str(feature_id)},
        "geometry": {
            "type": geometry_type,
            "coordinates": json_coordinates(polygons, geometry_type),
        },
    }


def write_feature_collection(
    path: Path,
    name: str,
    source: dict[str, Any],
    rows: Iterable[tuple[str, str, bytes]],
) -> tuple[int, str, int]:
    count = 0
    digest = hashlib.sha256()
    prefix = b'{"features":['
    suffix = (
        b'],"name":'
        + canonical_bytes(name).rstrip(b"\n")
        + b',"source":'
        + canonical_bytes(source).rstrip(b"\n")
        + b',"type":"FeatureCollection"}\n'
    )
    with path.open("wb") as stream:
        stream.write(prefix)
        digest.update(prefix)
        first = True
        for source_id, geometry_type, geometry_blob in rows:
            if not first:
                stream.write(b",")
                digest.update(b",")
            raw = canonical_bytes(
                feature_document(source_id, geometry_type, geometry_blob)
            ).rstrip(b"\n")
            stream.write(raw)
            digest.update(raw)
            first = False
            count += 1
        stream.write(suffix)
        digest.update(suffix)
    return count, digest.hexdigest(), path.stat().st_size


def export_candidate(database: Path, candidate: Path) -> dict[str, Any]:
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    try:
        boundary_release = accepted_release(connection, "county-boundary")
        building_release = accepted_release(connection, "buildings")
        boundary_rows = connection.execute(
            """
            SELECT source_feature_id, geometry_type, geometry
            FROM source_county_boundary
            WHERE release_id = ?
            ORDER BY source_ordinal
            """,
            (boundary_release["release_id"],),
        )
        boundary_count, boundary_hash, boundary_bytes = write_feature_collection(
            candidate / BOUNDARY_NAME,
            "Kane County boundary",
            {key: value for key, value in boundary_release.items() if key != "release_id"},
            boundary_rows,
        )
        building_rows = connection.execute(
            """
            SELECT source_feature_id, geometry_type, geometry
            FROM source_building
            WHERE release_id = ?
            ORDER BY source_ordinal
            """,
            (building_release["release_id"],),
        )
        building_count, building_hash, building_bytes = write_feature_collection(
            candidate / BUILDINGS_NAME,
            "Kane County building footprints",
            {key: value for key, value in building_release.items() if key != "release_id"},
            building_rows,
        )
    finally:
        connection.close()
    if boundary_count != 1:
        raise RuntimeError(f"Prepared boundary feature count is {boundary_count}; expected 1.")
    if building_count <= 0:
        raise RuntimeError("Prepared building export contains no features.")
    manifest = {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "project": "kane-offline-map",
        "source_database": {
            "byte_length": database.stat().st_size,
            "sha256": database_sha256(database),
        },
        "datasets": {
            "county_boundary": {
                "relative_path": BOUNDARY_NAME,
                "feature_count": boundary_count,
                "byte_length": boundary_bytes,
                "sha256": boundary_hash,
                "release_key": boundary_release["release_key"],
                "content_sha256": boundary_release["content_sha256"],
            },
            "buildings": {
                "relative_path": BUILDINGS_NAME,
                "feature_count": building_count,
                "byte_length": building_bytes,
                "sha256": building_hash,
                "release_key": building_release["release_key"],
                "content_sha256": building_release["content_sha256"],
            },
        },
        "complete_browser_bundle": False,
        "remaining_datasets": ["roads", "water"],
    }
    manifest_raw = canonical_bytes(manifest)
    (candidate / MANIFEST_NAME).write_bytes(manifest_raw)
    return {
        "manifest": manifest,
        "manifest_sha256": hashlib.sha256(manifest_raw).hexdigest(),
        "manifest_byte_length": len(manifest_raw),
    }


def validate_collection_envelope(path: Path) -> list[str]:
    errors: list[str] = []
    try:
        size = path.stat().st_size
        with path.open("rb") as stream:
            prefix = stream.read(32)
            stream.seek(max(0, size - 64))
            suffix = stream.read()
    except OSError as exc:
        return [f"Cannot read prepared GeoJSON {path.name}: {exc}"]
    if not prefix.startswith(b'{"features":['):
        errors.append(f"Prepared GeoJSON {path.name} has an invalid canonical prefix.")
    if not suffix.endswith(b',"type":"FeatureCollection"}\n'):
        errors.append(f"Prepared GeoJSON {path.name} has an invalid canonical suffix.")
    return errors


def validate_core_export(path: Path) -> list[str]:
    errors: list[str] = []
    if not path.is_dir() or path.is_symlink():
        return [f"Prepared core directory is unavailable: {path}"]
    expected = {MANIFEST_NAME, *DATASET_FILES}
    actual = {item.name for item in path.iterdir() if item.is_file()}
    if actual != expected:
        errors.append("Prepared core directory contains unexpected or missing files.")
    try:
        raw = (path / MANIFEST_NAME).read_bytes()
        manifest = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return errors + [f"Prepared core manifest is invalid: {exc}"]
    if canonical_bytes(manifest) != raw:
        errors.append("Prepared core manifest is not canonical JSON.")
    if manifest.get("schema") != SCHEMA or manifest.get("schema_version") != SCHEMA_VERSION:
        errors.append("Prepared core manifest schema identity is invalid.")
    if manifest.get("complete_browser_bundle") is not False:
        errors.append("Prepared core export must remain explicitly incomplete.")
    if manifest.get("remaining_datasets") != ["roads", "water"]:
        errors.append("Prepared core export remaining-dataset registry is invalid.")
    datasets = manifest.get("datasets")
    if not isinstance(datasets, dict):
        return errors + ["Prepared core manifest datasets are missing."]
    for key, name in (("county_boundary", BOUNDARY_NAME), ("buildings", BUILDINGS_NAME)):
        record = datasets.get(key)
        file_path = path / name
        if not isinstance(record, dict):
            errors.append(f"Prepared core dataset record is missing: {key}")
            continue
        if record.get("relative_path") != name:
            errors.append(f"Prepared core relative path is invalid: {key}")
        if not file_path.is_file() or file_path.is_symlink():
            errors.append(f"Prepared core data file is unavailable: {name}")
            continue
        if record.get("byte_length") != file_path.stat().st_size:
            errors.append(f"Prepared core byte length mismatch: {name}")
        if record.get("sha256") != sha256_file(file_path):
            errors.append(f"Prepared core hash mismatch: {name}")
        count = record.get("feature_count")
        if not isinstance(count, int) or count <= 0:
            errors.append(f"Prepared core feature count is invalid: {name}")
        errors.extend(validate_collection_envelope(file_path))
    return errors


def promote_directory(candidate: Path, output: Path, force: bool) -> None:
    backup_root: Path | None = None
    backup: Path | None = None
    if output.exists():
        if not force:
            raise RuntimeError(f"Prepared core export already exists: {output}")
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


def export_prepared_core(database: Path, output: Path, force: bool = False) -> dict[str, Any]:
    import county_db

    database = database.resolve()
    output = output.resolve()
    errors = county_db.validate_authoritative_database(database)
    if errors:
        raise RuntimeError("Authoritative database is invalid:\n- " + "\n- ".join(errors))
    if output.exists() and not force:
        raise RuntimeError(f"Prepared core export already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    candidate = Path(tempfile.mkdtemp(
        prefix=f".{output.name}.", suffix=".candidate", dir=output.parent
    ))
    try:
        result = export_candidate(database, candidate)
        candidate_errors = validate_core_export(candidate)
        if candidate_errors:
            raise RuntimeError(
                "Prepared core candidate failed validation:\n- "
                + "\n- ".join(candidate_errors)
            )
        promote_directory(candidate, output, force)
    finally:
        if candidate.exists():
            shutil.rmtree(candidate, ignore_errors=True)
    manifest = result["manifest"]
    return {
        "valid": True,
        "output": str(output),
        "manifest": str(output / MANIFEST_NAME),
        "manifest_byte_length": result["manifest_byte_length"],
        "manifest_sha256": result["manifest_sha256"],
        "complete_browser_bundle": False,
        "remaining_datasets": manifest["remaining_datasets"],
        "datasets": manifest["datasets"],
        "source_database": manifest["source_database"],
    }
