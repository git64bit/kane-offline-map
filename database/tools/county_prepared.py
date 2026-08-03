#!/usr/bin/env python3
"""Export the complete accepted browser-data bundle as deterministic GeoJSON."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
from pathlib import Path
from typing import Any, Iterable, Iterator

import county_geometry

SCHEMA = "kane-offline-map-prepared-core"
SCHEMA_VERSION = 2
MANIFEST_NAME = "core-manifest.json"
BOUNDARY_NAME = "county_boundary.json"
ROADS_NAME = "roads.json"
WATER_NAME = "water.json"
BUILDINGS_NAME = "buildings.json"
DATASET_FILES = (BOUNDARY_NAME, ROADS_NAME, WATER_NAME, BUILDINGS_NAME)
DATASET_REGISTRY = {
    "county_boundary": BOUNDARY_NAME,
    "roads": ROADS_NAME,
    "water": WATER_NAME,
    "buildings": BUILDINGS_NAME,
}
PreparedRow = tuple[str, str, bytes, str | None, dict[str, Any] | None]


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


def source_document(release: dict[str, Any], dataset_key: str) -> dict[str, Any]:
    output = {key: value for key, value in release.items() if key != "release_id"}
    output["dataset_key"] = dataset_key
    return output


def json_coordinates(value: Any) -> Any:
    if isinstance(value, tuple):
        return [float(item) for item in value]
    if isinstance(value, list):
        return [json_coordinates(item) for item in value]
    raise RuntimeError("Decoded prepared geometry has an invalid coordinate structure.")


def feature_document(
    feature_id: str,
    geometry_type: str,
    geometry_blob: bytes,
    attributes_json: str | None,
    extra_properties: dict[str, Any] | None,
) -> dict[str, Any]:
    decoded_type, coordinates = county_geometry.decode_geojson_geometry(geometry_blob)
    if decoded_type != geometry_type:
        raise RuntimeError(
            f"Prepared geometry type mismatch for feature {feature_id}: "
            f"{geometry_type} != {decoded_type}."
        )
    properties: dict[str, Any] = {}
    if attributes_json is not None:
        parsed = json.loads(attributes_json)
        if not isinstance(parsed, dict):
            raise RuntimeError(f"Prepared attributes are not an object: {feature_id}.")
        properties.update(parsed)
    if extra_properties:
        properties.update(extra_properties)
    properties["source_feature_id"] = str(feature_id)
    return {
        "type": "Feature",
        "id": str(feature_id),
        "properties": properties,
        "geometry": {
            "type": geometry_type,
            "coordinates": json_coordinates(coordinates),
        },
    }


def write_feature_collection(
    path: Path,
    name: str,
    source: Any,
    rows: Iterable[PreparedRow],
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
        for row in rows:
            if not first:
                stream.write(b",")
                digest.update(b",")
            raw = canonical_bytes(feature_document(*row)).rstrip(b"\n")
            stream.write(raw)
            digest.update(raw)
            first = False
            count += 1
        stream.write(suffix)
        digest.update(suffix)
    return count, digest.hexdigest(), path.stat().st_size


def boundary_rows(connection: sqlite3.Connection, release_id: int) -> Iterator[PreparedRow]:
    rows = connection.execute(
        """SELECT source_feature_id, geometry_type, geometry
           FROM source_county_boundary WHERE release_id = ? ORDER BY source_ordinal""",
        (release_id,),
    )
    for source_id, geometry_type, geometry in rows:
        yield str(source_id), geometry_type, geometry, None, None


def building_rows(connection: sqlite3.Connection, release_id: int) -> Iterator[PreparedRow]:
    rows = connection.execute(
        """SELECT source_feature_id, geometry_type, geometry
           FROM source_building WHERE release_id = ? ORDER BY source_ordinal""",
        (release_id,),
    )
    for source_id, geometry_type, geometry in rows:
        yield str(source_id), geometry_type, geometry, None, None


def map_rows(
    connection: sqlite3.Connection,
    release_id: int,
    dataset_key: str,
) -> Iterator[PreparedRow]:
    rows = connection.execute(
        """SELECT source_feature_id, geometry_type, geometry, attributes_json
           FROM source_map_feature WHERE release_id = ? ORDER BY source_ordinal""",
        (release_id,),
    )
    for source_id, geometry_type, geometry, attributes_json in rows:
        yield (
            f"{dataset_key}:{source_id}",
            geometry_type,
            geometry,
            attributes_json,
            {"dataset_key": dataset_key, "source_dataset_feature_id": str(source_id)},
        )


def dataset_record(
    relative_path: str,
    feature_count: int,
    sha256: str,
    byte_length: int,
    releases: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "relative_path": relative_path,
        "feature_count": feature_count,
        "byte_length": byte_length,
        "sha256": sha256,
        "releases": [
            {
                "dataset_key": release["dataset_key"],
                "release_key": release["release_key"],
                "content_sha256": release["content_sha256"],
            }
            for release in releases
        ],
    }


def export_candidate(database: Path, candidate: Path) -> dict[str, Any]:
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    try:
        releases = {
            key: accepted_release(connection, key)
            for key in (
                "county-boundary",
                "buildings",
                "roads",
                "water-fox-river",
                "water-creeks",
            )
        }
        boundary_source = source_document(releases["county-boundary"], "county-boundary")
        boundary = write_feature_collection(
            candidate / BOUNDARY_NAME,
            "Kane County boundary",
            boundary_source,
            boundary_rows(connection, releases["county-boundary"]["release_id"]),
        )
        building_source = source_document(releases["buildings"], "buildings")
        buildings = write_feature_collection(
            candidate / BUILDINGS_NAME,
            "Kane County building footprints",
            building_source,
            building_rows(connection, releases["buildings"]["release_id"]),
        )
        road_source = source_document(releases["roads"], "roads")
        roads = write_feature_collection(
            candidate / ROADS_NAME,
            "Kane County road centerlines",
            road_source,
            map_rows(connection, releases["roads"]["release_id"], "roads"),
        )
        water_sources = [
            source_document(releases[key], key)
            for key in ("water-fox-river", "water-creeks")
        ]
        water_rows = (
            row
            for key in ("water-fox-river", "water-creeks")
            for row in map_rows(connection, releases[key]["release_id"], key)
        )
        water = write_feature_collection(
            candidate / WATER_NAME,
            "Kane County Fox River and creeks",
            water_sources,
            water_rows,
        )
    finally:
        connection.close()
    if boundary[0] != 1:
        raise RuntimeError(f"Prepared boundary feature count is {boundary[0]}; expected 1.")
    for label, result in (("buildings", buildings), ("roads", roads), ("water", water)):
        if result[0] <= 0:
            raise RuntimeError(f"Prepared {label} export contains no features.")
    release_docs = {
        key: source_document(value, key)
        for key, value in releases.items()
    }
    manifest = {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "project": "kane-offline-map",
        "source_database": {
            "byte_length": database.stat().st_size,
            "sha256": sha256_file(database),
        },
        "datasets": {
            "county_boundary": dataset_record(BOUNDARY_NAME, *boundary, [release_docs["county-boundary"]]),
            "roads": dataset_record(ROADS_NAME, *roads, [release_docs["roads"]]),
            "water": dataset_record(
                WATER_NAME,
                *water,
                [release_docs["water-fox-river"], release_docs["water-creeks"]],
            ),
            "buildings": dataset_record(BUILDINGS_NAME, *buildings, [release_docs["buildings"]]),
        },
        "complete_browser_bundle": True,
        "remaining_datasets": [],
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
        return [f"Prepared browser directory is unavailable: {path}"]
    expected = {MANIFEST_NAME, *DATASET_FILES}
    actual = {item.name for item in path.iterdir() if item.is_file()}
    if actual != expected:
        errors.append("Prepared browser directory contains unexpected or missing files.")
    try:
        raw = (path / MANIFEST_NAME).read_bytes()
        manifest = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return errors + [f"Prepared browser manifest is invalid: {exc}"]
    if canonical_bytes(manifest) != raw:
        errors.append("Prepared browser manifest is not canonical JSON.")
    if manifest.get("schema") != SCHEMA or manifest.get("schema_version") != SCHEMA_VERSION:
        errors.append("Prepared browser manifest schema identity is invalid.")
    if manifest.get("complete_browser_bundle") is not True:
        errors.append("Prepared browser bundle is not marked complete.")
    if manifest.get("remaining_datasets") != []:
        errors.append("Prepared browser remaining-dataset registry is not empty.")
    datasets = manifest.get("datasets")
    if not isinstance(datasets, dict) or set(datasets) != set(DATASET_REGISTRY):
        return errors + ["Prepared browser manifest dataset registry is invalid."]
    for key, name in DATASET_REGISTRY.items():
        record = datasets.get(key)
        file_path = path / name
        if not isinstance(record, dict):
            errors.append(f"Prepared browser dataset record is missing: {key}")
            continue
        if record.get("relative_path") != name:
            errors.append(f"Prepared browser relative path is invalid: {key}")
        if not file_path.is_file() or file_path.is_symlink():
            errors.append(f"Prepared browser data file is unavailable: {name}")
            continue
        if record.get("byte_length") != file_path.stat().st_size:
            errors.append(f"Prepared browser byte length mismatch: {name}")
        if record.get("sha256") != sha256_file(file_path):
            errors.append(f"Prepared browser hash mismatch: {name}")
        count = record.get("feature_count")
        if not isinstance(count, int) or count <= 0:
            errors.append(f"Prepared browser feature count is invalid: {name}")
        releases = record.get("releases")
        if not isinstance(releases, list) or not releases:
            errors.append(f"Prepared browser release provenance is missing: {name}")
        errors.extend(validate_collection_envelope(file_path))
    return errors


def promote_directory(candidate: Path, output: Path, force: bool) -> None:
    backup_root: Path | None = None
    backup: Path | None = None
    if output.exists():
        if not force:
            raise RuntimeError(f"Prepared browser export already exists: {output}")
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
    errors = county_db.validate_deployment_database(database)
    if errors:
        raise RuntimeError("Deployment source database is invalid:\n- " + "\n- ".join(errors))
    if output.exists() and not force:
        raise RuntimeError(f"Prepared browser export already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    candidate = Path(tempfile.mkdtemp(
        prefix=f".{output.name}.", suffix=".candidate", dir=output.parent
    ))
    try:
        result = export_candidate(database, candidate)
        candidate_errors = validate_core_export(candidate)
        if candidate_errors:
            raise RuntimeError(
                "Prepared browser candidate failed validation:\n- "
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
        "complete_browser_bundle": True,
        "remaining_datasets": [],
        "datasets": manifest["datasets"],
        "source_database": manifest["source_database"],
    }
