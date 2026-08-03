#!/usr/bin/env python3
"""Validate ArcGIS harvest pairs before SQL acceptance."""

from __future__ import annotations

import datetime as dt
import json
import math
from pathlib import Path
from typing import Any

import county_arcgis
import county_geojson


def parse_timestamp(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"Harvest manifest {label} must be a non-empty timestamp.")
    text = value.strip()
    try:
        dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RuntimeError(f"Harvest manifest {label} is not an ISO-8601 timestamp.") from exc
    return text


def load_json_object(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    raw = path.read_bytes()
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"{label} is not valid UTF-8 JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise RuntimeError(f"{label} is not a JSON object.")
    return document, raw


def require_equal(actual: Any, expected: Any, label: str) -> None:
    if actual != expected:
        raise RuntimeError(f"Harvest manifest {label} does not match the accepted source contract.")


def source_contract(profile: dict[str, Any]) -> dict[str, Any]:
    return {
        "profile_key": profile["profile_key"],
        "agency_key": profile["agency_key"],
        "dataset_key": profile["dataset_key"],
        "layer_url": profile["layer_url"],
        "object_id_field": profile["object_id_field"],
        "stable_id_property": profile["id_property"],
        "out_srs": profile["out_srs"],
    }


def chosen_published_at(manifest: dict[str, Any]) -> str:
    source = manifest["source"]
    value = source.get("layer_data_last_edit_at") or source.get("layer_last_edit_at")
    return parse_timestamp(value or manifest["harvested_at"], "published timestamp")


def release_key(dataset_key: str, published_at: str, output_sha256: str) -> str:
    moment = dt.datetime.fromisoformat(published_at.replace("Z", "+00:00"))
    date_key = moment.astimezone(dt.timezone.utc).strftime("%Y%m%d")
    return f"kane-{dataset_key}-{date_key}-{output_sha256[:12]}"


def validate_features(
    document: dict[str, Any], profile: dict[str, Any], manifest: dict[str, Any]
) -> tuple[list[int], list[str]]:
    if document.get("type") != "FeatureCollection":
        raise RuntimeError("Harvest output is not a GeoJSON FeatureCollection.")
    require_equal(document.get("name"), profile["profile_key"], "GeoJSON name")
    require_equal(document.get("source"), manifest["source"], "GeoJSON source summary")
    features = document.get("features")
    if not isinstance(features, list) or not features:
        raise RuntimeError("Harvest output contains no features.")

    object_ids: list[int] = []
    stable_ids: list[str] = []
    seen_objects: set[int] = set()
    seen_stable: set[str] = set()
    for ordinal, feature in enumerate(features, start=1):
        if not isinstance(feature, dict) or feature.get("type") != "Feature":
            raise RuntimeError(f"Harvest output item {ordinal} is not a GeoJSON Feature.")
        properties = feature.get("properties")
        if not isinstance(properties, dict):
            raise RuntimeError(f"Harvest output feature {ordinal} has invalid properties.")
        current_object = county_arcgis.object_id(
            properties.get(profile["object_id_field"]), profile["object_id_field"]
        )
        current_stable = county_arcgis.stable_text(
            properties.get(profile["id_property"]), profile["id_property"]
        )
        if current_object in seen_objects:
            raise RuntimeError(f"Harvest output contains duplicate object ID {current_object}.")
        if current_stable in seen_stable:
            raise RuntimeError(f"Harvest output contains duplicate stable ID {current_stable}.")
        if str(feature.get("id")) != current_stable:
            raise RuntimeError(
                f"Harvest output feature {current_object} does not use {profile['id_property']} as feature.id."
            )
        county_geojson.validate_geometry(
            feature.get("geometry"),
            profile["expected_geometry_type"],
            f"feature {current_stable}",
        )
        seen_objects.add(current_object)
        seen_stable.add(current_stable)
        object_ids.append(current_object)
        stable_ids.append(current_stable)
    if object_ids != sorted(object_ids):
        raise RuntimeError("Harvest output features are not ordered by object ID.")
    return object_ids, stable_ids


def validate_harvest(
    profile_path: Path, geojson_path: Path, manifest_file: Path | None = None
) -> dict[str, Any]:
    profile, profile_raw = county_arcgis.load_profile(profile_path)
    manifest_file = manifest_file or county_arcgis.manifest_path(geojson_path)
    document, output_raw = load_json_object(geojson_path, "Harvest output")
    manifest, manifest_raw = load_json_object(manifest_file, "Harvest manifest")

    if output_raw != county_arcgis.canonical_bytes(document):
        raise RuntimeError("Harvest output is not in canonical ArcGIS-harvester form.")
    if manifest_raw != county_arcgis.canonical_bytes(manifest):
        raise RuntimeError("Harvest manifest is not in canonical ArcGIS-harvester form.")
    require_equal(manifest.get("manifest_schema"), county_arcgis.MANIFEST_SCHEMA, "schema")

    profile_record = manifest.get("profile")
    if not isinstance(profile_record, dict):
        raise RuntimeError("Harvest manifest profile record is missing or invalid.")
    require_equal(profile_record.get("profile_key"), profile["profile_key"], "profile key")
    require_equal(profile_record.get("sha256"), county_arcgis.sha256_bytes(profile_raw), "profile hash")
    require_equal(profile_record.get("path"), profile_path.name, "profile filename")

    source = manifest.get("source")
    if not isinstance(source, dict):
        raise RuntimeError("Harvest manifest source record is missing or invalid.")
    for key, expected in source_contract(profile).items():
        require_equal(source.get(key), expected, f"source {key}")

    metadata = manifest.get("layer_metadata")
    if not isinstance(metadata, dict):
        raise RuntimeError("Harvest manifest layer metadata is missing or invalid.")
    county_arcgis.validate_layer_metadata(profile, metadata)
    require_equal(
        manifest.get("layer_metadata_sha256"),
        county_arcgis.sha256_bytes(county_arcgis.canonical_bytes(metadata)),
        "layer metadata hash",
    )
    require_equal(source, county_arcgis.source_summary(profile, metadata), "source summary")

    output_record = manifest.get("output")
    if not isinstance(output_record, dict):
        raise RuntimeError("Harvest manifest output record is missing or invalid.")
    output_hash = county_arcgis.sha256_bytes(output_raw)
    require_equal(output_record.get("path"), geojson_path.name, "output filename")
    require_equal(output_record.get("byte_length"), len(output_raw), "output byte length")
    require_equal(output_record.get("sha256"), output_hash, "output hash")

    object_ids, stable_ids = validate_features(document, profile, manifest)
    require_equal(output_record.get("feature_count"), len(object_ids), "feature count")
    expected_count = profile.get("expected_feature_count")
    if expected_count is not None and len(object_ids) != expected_count:
        raise RuntimeError(
            f"Harvest output contains {len(object_ids)} features; expected {expected_count}."
        )

    request = manifest.get("request")
    if not isinstance(request, dict):
        raise RuntimeError("Harvest manifest request record is missing or invalid.")
    require_equal(request.get("where"), profile["where"], "request filter")
    require_equal(request.get("out_fields"), profile["out_fields"], "request fields")
    page_size = request.get("page_size")
    if not isinstance(page_size, int) or isinstance(page_size, bool) or page_size < 1:
        raise RuntimeError("Harvest manifest page size is invalid.")
    require_equal(request.get("object_id_count"), len(object_ids), "object ID count")
    require_equal(
        request.get("object_ids_sha256"),
        county_arcgis.sha256_bytes(county_arcgis.canonical_bytes(object_ids)),
        "object ID inventory hash",
    )
    require_equal(request.get("page_count"), math.ceil(len(object_ids) / page_size), "page count")

    harvested_at = parse_timestamp(manifest.get("harvested_at"), "harvested_at")
    published_at = chosen_published_at(manifest)
    manifest_hash = county_arcgis.sha256_bytes(manifest_raw)
    return {
        "valid": True,
        "profile_key": profile["profile_key"],
        "release_key": release_key(profile["dataset_key"], published_at, output_hash),
        "source_uri": profile["layer_url"],
        "source_version": f"arcgis-profile-sha256:{profile_record['sha256']}",
        "profile_sha256": profile_record["sha256"],
        "published_at": published_at,
        "harvested_at": harvested_at,
        "id_property": profile["id_property"],
        "geojson": str(geojson_path),
        "manifest": str(manifest_file),
        "geojson_sha256": output_hash,
        "manifest_sha256": manifest_hash,
        "feature_count": len(object_ids),
        "object_id_count": len(object_ids),
        "stable_id_count": len(stable_ids),
    }
