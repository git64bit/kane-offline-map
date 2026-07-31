#!/usr/bin/env python3
"""Harvest deterministic GeoJSON releases from an ArcGIS FeatureServer layer."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Iterable

PROFILE_SCHEMA = 1
MANIFEST_SCHEMA = 1
DEFAULT_TIMEOUT = 120.0
Requester = Callable[[str, dict[str, str], float], dict[str, Any]]


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


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


def manifest_path(output: Path) -> Path:
    return Path(str(output) + ".manifest.json")


def arcgis_error(document: Any) -> RuntimeError | None:
    if not isinstance(document, dict) or "error" not in document:
        return None
    error = document.get("error") or {}
    code = error.get("code", "unknown")
    message = error.get("message", "ArcGIS request failed")
    details = error.get("details") or []
    detail = "; ".join(str(item) for item in details if item)
    suffix = f" ({detail})" if detail else ""
    return RuntimeError(f"ArcGIS error {code}: {message}{suffix}")


def http_request_json(url: str, params: dict[str, str], timeout: float) -> dict[str, Any]:
    encoded = urllib.parse.urlencode(params).encode("utf-8")
    is_query = url.rstrip("/").endswith("/query")
    request_url = url if is_query else url + ("&" if "?" in url else "?") + encoded.decode("ascii")
    request = urllib.request.Request(
        request_url,
        data=encoded if is_query else None,
        headers={
            "Accept": "application/json, application/geo+json",
            "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
            "User-Agent": "Kane-Offline-Map/1 ArcGIS-Harvester",
        },
        method="POST" if is_query else "GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"ArcGIS HTTP error {exc.code}: {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"ArcGIS connection error: {exc.reason}") from exc
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"ArcGIS response is not valid UTF-8 JSON: {exc}") from exc
    error = arcgis_error(document)
    if error:
        raise error
    if not isinstance(document, dict):
        raise RuntimeError("ArcGIS response is not a JSON object.")
    return document


def profile_errors(profile: Any) -> list[str]:
    if not isinstance(profile, dict):
        return ["Source profile is not a JSON object."]
    errors: list[str] = []
    required_strings = (
        "profile_key",
        "agency_key",
        "dataset_key",
        "layer_url",
        "where",
        "object_id_field",
        "id_property",
        "expected_geometry_type",
        "copyright_text",
    )
    if profile.get("profile_schema") != PROFILE_SCHEMA:
        errors.append(f"profile_schema must be {PROFILE_SCHEMA}.")
    for key in required_strings:
        if not isinstance(profile.get(key), str) or not profile[key].strip():
            errors.append(f"{key} must be a non-empty string.")
    layer_url = profile.get("layer_url")
    if isinstance(layer_url, str):
        parsed = urllib.parse.urlparse(layer_url)
        if parsed.scheme != "https" or not parsed.netloc:
            errors.append("layer_url must be an absolute HTTPS URL.")
        if "/FeatureServer/" not in parsed.path:
            errors.append("layer_url must identify an ArcGIS FeatureServer layer.")
    if profile.get("out_srs") != 4326:
        errors.append("out_srs must be EPSG:4326.")
    page_size = profile.get("page_size")
    if not isinstance(page_size, int) or isinstance(page_size, bool) or not 1 <= page_size <= 5000:
        errors.append("page_size must be an integer from 1 through 5000.")
    out_fields = profile.get("out_fields")
    if not isinstance(out_fields, list) or not out_fields:
        errors.append("out_fields must be a non-empty array.")
    elif any(not isinstance(item, str) or not item.strip() for item in out_fields):
        errors.append("out_fields entries must be non-empty strings.")
    elif len(set(out_fields)) != len(out_fields):
        errors.append("out_fields contains duplicate names.")
    else:
        for key in ("object_id_field", "id_property"):
            value = profile.get(key)
            if isinstance(value, str) and value not in out_fields:
                errors.append(f"out_fields must include {value!r} from {key}.")
    return errors


def load_profile(path: Path) -> tuple[dict[str, Any], bytes]:
    raw = path.read_bytes()
    try:
        profile = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Source profile is not valid UTF-8 JSON: {exc}") from exc
    errors = profile_errors(profile)
    if errors:
        raise RuntimeError("Invalid ArcGIS source profile:\n- " + "\n- ".join(errors))
    return profile, raw


def profile_info(path: Path) -> dict[str, Any]:
    profile, raw = load_profile(path)
    return {
        "valid": True,
        "path": str(path),
        "profile_key": profile["profile_key"],
        "layer_url": profile["layer_url"],
        "id_property": profile["id_property"],
        "object_id_field": profile["object_id_field"],
        "out_srs": profile["out_srs"],
        "page_size": profile["page_size"],
        "profile_sha256": sha256_bytes(raw),
    }


def format_supported(value: Any) -> set[str]:
    if isinstance(value, str):
        return {item.strip().lower() for item in value.split(",") if item.strip()}
    if isinstance(value, list):
        return {str(item).strip().lower() for item in value if str(item).strip()}
    return set()


def validate_layer_metadata(profile: dict[str, Any], metadata: dict[str, Any]) -> None:
    errors: list[str] = []
    if metadata.get("type") != "Feature Layer":
        errors.append("ArcGIS resource is not a Feature Layer.")
    if metadata.get("geometryType") != profile["expected_geometry_type"]:
        errors.append(
            f"Geometry type is {metadata.get('geometryType')!r}; "
            f"expected {profile['expected_geometry_type']!r}."
        )
    if "geojson" not in format_supported(metadata.get("supportedQueryFormats")):
        errors.append("Layer does not advertise GeoJSON query support.")
    object_field = metadata.get("objectIdField") or metadata.get("objectIdFieldName")
    if object_field != profile["object_id_field"]:
        errors.append(
            f"Object ID field is {object_field!r}; expected {profile['object_id_field']!r}."
        )
    fields = {
        field.get("name") for field in metadata.get("fields", []) if isinstance(field, dict)
    }
    missing_fields = [field for field in profile["out_fields"] if field not in fields]
    if missing_fields:
        errors.append("Layer metadata is missing requested fields: " + ", ".join(missing_fields) + ".")
    max_records = metadata.get("maxRecordCount")
    if not isinstance(max_records, int) or max_records < 1:
        errors.append("Layer maxRecordCount is missing or invalid.")
    if errors:
        raise RuntimeError("ArcGIS layer metadata mismatch:\n- " + "\n- ".join(errors))


def chunks(values: list[int], size: int) -> Iterable[list[int]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


def stable_text(value: Any, label: str) -> str:
    if value is None or isinstance(value, bool):
        raise RuntimeError(f"Building feature is missing stable {label}.")
    text = str(value).strip()
    if not text:
        raise RuntimeError(f"Building feature is missing stable {label}.")
    return text


def object_id(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise RuntimeError(f"ArcGIS feature has invalid {field}.")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"ArcGIS feature has invalid {field}: {value!r}.") from exc
    if result < 0:
        raise RuntimeError(f"ArcGIS feature has invalid {field}: {value!r}.")
    return result


def normalize_page(
    document: dict[str, Any],
    expected_ids: list[int],
    object_field: str,
    stable_field: str,
    seen_stable: set[str],
) -> list[dict[str, Any]]:
    if document.get("type") != "FeatureCollection" or not isinstance(document.get("features"), list):
        raise RuntimeError("ArcGIS feature query did not return a GeoJSON FeatureCollection.")
    by_object: dict[int, dict[str, Any]] = {}
    for feature in document["features"]:
        if not isinstance(feature, dict) or feature.get("type") != "Feature":
            raise RuntimeError("ArcGIS GeoJSON contains a non-Feature item.")
        properties = feature.get("properties")
        if not isinstance(properties, dict):
            raise RuntimeError("ArcGIS feature properties are missing or invalid.")
        current_object_id = object_id(properties.get(object_field), object_field)
        if current_object_id in by_object:
            raise RuntimeError(f"ArcGIS page contains duplicate object ID {current_object_id}.")
        stable_id = stable_text(properties.get(stable_field), stable_field)
        if stable_id in seen_stable:
            raise RuntimeError(f"ArcGIS harvest contains duplicate stable ID {stable_id}.")
        geometry = feature.get("geometry")
        if not isinstance(geometry, dict) or geometry.get("type") not in ("Polygon", "MultiPolygon"):
            raise RuntimeError(f"ArcGIS feature {stable_id} has unsupported geometry.")
        feature = dict(feature)
        feature["id"] = stable_id
        by_object[current_object_id] = feature
        seen_stable.add(stable_id)
    expected = set(expected_ids)
    actual = set(by_object)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise RuntimeError(f"ArcGIS page object ID mismatch; missing={missing}, extra={extra}.")
    return [by_object[current] for current in expected_ids]


def epoch_millis_iso(value: Any) -> str | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    moment = dt.datetime.fromtimestamp(float(value) / 1000.0, tz=dt.timezone.utc)
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def source_summary(profile: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    editing = metadata.get("editingInfo") if isinstance(metadata.get("editingInfo"), dict) else {}
    def edit_value(name: str) -> Any:
        return editing.get(name) if editing.get(name) is not None else metadata.get(name)
    return {
        "profile_key": profile["profile_key"],
        "agency_key": profile["agency_key"],
        "dataset_key": profile["dataset_key"],
        "layer_url": profile["layer_url"],
        "layer_name": metadata.get("name"),
        "copyright_text": metadata.get("copyrightText") or profile["copyright_text"],
        "object_id_field": profile["object_id_field"],
        "stable_id_property": profile["id_property"],
        "out_srs": profile["out_srs"],
        "layer_last_edit_at": epoch_millis_iso(edit_value("lastEditDate")),
        "layer_data_last_edit_at": epoch_millis_iso(edit_value("dataLastEditDate")),
        "layer_schema_last_edit_at": epoch_millis_iso(edit_value("schemaLastEditDate")),
    }


def write_temporary(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".candidate", dir=path.parent)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        Path(temporary_name).unlink(missing_ok=True)
        raise
    return Path(temporary_name)


def promote_pair(output: Path, output_data: bytes, manifest_data: bytes, force: bool) -> None:
    sidecar = manifest_path(output)
    if not force and (output.exists() or sidecar.exists()):
        raise RuntimeError(f"Harvest output already exists: {output}")
    output_candidate = write_temporary(output, output_data)
    try:
        manifest_candidate = write_temporary(sidecar, manifest_data)
    except Exception:
        output_candidate.unlink(missing_ok=True)
        raise
    output_backup = output.with_name(f".{output.name}.backup")
    manifest_backup = sidecar.with_name(f".{sidecar.name}.backup")
    for backup in (output_backup, manifest_backup):
        backup.unlink(missing_ok=True)
    moved_output = False
    moved_manifest = False
    promoted_output = False
    promoted_manifest = False
    try:
        if output.exists():
            os.replace(output, output_backup)
            moved_output = True
        if sidecar.exists():
            os.replace(sidecar, manifest_backup)
            moved_manifest = True
        os.replace(output_candidate, output)
        promoted_output = True
        os.replace(manifest_candidate, sidecar)
        promoted_manifest = True
    except Exception:
        if promoted_output:
            output.unlink(missing_ok=True)
        if promoted_manifest:
            sidecar.unlink(missing_ok=True)
        if moved_output:
            os.replace(output_backup, output)
        if moved_manifest:
            os.replace(manifest_backup, sidecar)
        raise
    finally:
        output_candidate.unlink(missing_ok=True)
        manifest_candidate.unlink(missing_ok=True)
        output_backup.unlink(missing_ok=True)
        manifest_backup.unlink(missing_ok=True)


def harvest(
    profile_path: Path,
    output: Path,
    force: bool = False,
    timeout: float = DEFAULT_TIMEOUT,
    requester: Requester = http_request_json,
    harvested_at: str | None = None,
) -> dict[str, Any]:
    profile, profile_raw = load_profile(profile_path)
    sidecar = manifest_path(output)
    if not force and (output.exists() or sidecar.exists()):
        raise RuntimeError(f"Harvest output already exists: {output}")
    harvested_at = harvested_at or utc_now()
    metadata = requester(profile["layer_url"], {"f": "pjson"}, timeout)
    validate_layer_metadata(profile, metadata)
    query_url = profile["layer_url"].rstrip("/") + "/query"
    identifiers = requester(
        query_url,
        {"where": profile["where"], "returnIdsOnly": "true", "f": "json"},
        timeout,
    )
    field_name = identifiers.get("objectIdFieldName")
    if field_name and field_name != profile["object_id_field"]:
        raise RuntimeError(
            f"ArcGIS ID response field is {field_name!r}; expected {profile['object_id_field']!r}."
        )
    raw_ids = identifiers.get("objectIds")
    if not isinstance(raw_ids, list) or not raw_ids:
        raise RuntimeError("ArcGIS layer query returned no object IDs.")
    object_ids = sorted(object_id(value, profile["object_id_field"]) for value in raw_ids)
    if len(set(object_ids)) != len(object_ids):
        raise RuntimeError("ArcGIS ID response contains duplicate object IDs.")
    max_records = int(metadata["maxRecordCount"])
    page_size = min(profile["page_size"], max_records)
    features: list[dict[str, Any]] = []
    seen_stable: set[str] = set()
    page_count = 0
    for page_ids in chunks(object_ids, page_size):
        page_count += 1
        page = requester(
            query_url,
            {
                "objectIds": ",".join(str(value) for value in page_ids),
                "outFields": ",".join(profile["out_fields"]),
                "returnGeometry": "true",
                "returnZ": "false",
                "returnM": "false",
                "outSR": str(profile["out_srs"]),
                "f": "geojson",
            },
            timeout,
        )
        features.extend(
            normalize_page(
                page,
                page_ids,
                profile["object_id_field"],
                profile["id_property"],
                seen_stable,
            )
        )
    source = source_summary(profile, metadata)
    collection = {
        "type": "FeatureCollection",
        "name": profile["profile_key"],
        "source": source,
        "features": features,
    }
    output_data = canonical_bytes(collection)
    metadata_data = canonical_bytes(metadata)
    ids_data = canonical_bytes(object_ids)
    manifest = {
        "manifest_schema": MANIFEST_SCHEMA,
        "harvested_at": harvested_at,
        "profile": {
            "path": profile_path.name,
            "profile_key": profile["profile_key"],
            "sha256": sha256_bytes(profile_raw),
        },
        "source": source,
        "request": {
            "where": profile["where"],
            "out_fields": profile["out_fields"],
            "page_size": page_size,
            "page_count": page_count,
            "object_id_count": len(object_ids),
            "object_ids_sha256": sha256_bytes(ids_data),
        },
        "layer_metadata": metadata,
        "layer_metadata_sha256": sha256_bytes(metadata_data),
        "output": {
            "path": output.name,
            "byte_length": len(output_data),
            "sha256": sha256_bytes(output_data),
            "feature_count": len(features),
        },
    }
    manifest_data = canonical_bytes(manifest)
    promote_pair(output, output_data, manifest_data, force)
    return {
        "valid": True,
        "profile_key": profile["profile_key"],
        "output": str(output),
        "manifest": str(manifest_path(output)),
        "feature_count": len(features),
        "page_count": page_count,
        "sha256": sha256_bytes(output_data),
        "source": source,
    }
