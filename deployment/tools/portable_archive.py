#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable

ARCHIVE_ROOT = "kane-offline-map"
SCHEMA = "kane-offline-map-portable-archive"
SCHEMA_VERSION = 1
FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
PREPARED_MANIFEST = "core-manifest.json"
REQUIRED_PREPARED = (
    "county_boundary.json",
    "roads.json",
    "water.json",
    "buildings.json",
    PREPARED_MANIFEST,
)
PREPARED_DATASETS = {
    "county_boundary": "county_boundary.json",
    "roads": "roads.json",
    "water": "water.json",
    "buildings": "buildings.json",
}
TRACKED_RUNTIME = (
    "index.html",
    "portable_config.js",
    "LICENSE",
    "src/app.js",
    "src/constants.js",
    "src/dataLoader.js",
    "src/grid.js",
    "src/reviewBundleLoader.js",
    "src/reviewOverlay.js",
    "src/renderer.js",
    "src/stateStore.js",
    "styles/app.css",
    "data/reviews/README.txt",
)
GENERATED_FILES = {
    "README-USB.txt": "deployment/USB_DEPLOYMENT_README.txt",
    "START-URL.txt": "deployment/START-URL.txt",
    "trivialhttp-runtime/README.txt": "deployment/TRIVIALHTTP_RUNTIME_README.txt",
    "project-data/sectors/README.txt": "deployment/SECTOR_STORAGE_README.txt",
}


class ArchiveError(RuntimeError):
    pass


@dataclass(frozen=True)
class Payload:
    path: str
    source: Path | None = None
    content: bytes | None = None

    def read_bytes(self) -> bytes:
        if self.content is not None:
            return self.content
        if self.source is None:
            raise ArchiveError(f"Payload {self.path} has no source.")
        return self.source.read_bytes()


@dataclass(frozen=True)
class PayloadRecord:
    path: str
    byte_length: int
    sha256: str

    def as_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "byte_length": self.byte_length,
            "sha256": self.sha256,
        }


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def validate_regular_file(path: Path, label: str) -> None:
    if path.is_symlink():
        raise ArchiveError(f"{label} must not be a symbolic link: {path}")
    if not path.is_file():
        raise ArchiveError(f"{label} is missing: {path}")
    if path.stat().st_size <= 0:
        raise ArchiveError(f"{label} is empty: {path}")


def validate_prepared_data(directory: Path) -> dict[str, dict[str, object]]:
    if not directory.is_dir() or directory.is_symlink():
        raise ArchiveError(f"Prepared data directory is unavailable: {directory}")
    for name in REQUIRED_PREPARED:
        validate_regular_file(directory / name, "Prepared data file")
    manifest_path = directory / PREPARED_MANIFEST
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ArchiveError("Prepared browser manifest is invalid.") from error
    if manifest.get("schema") != "kane-offline-map-prepared-core":
        raise ArchiveError("Prepared browser manifest schema is invalid.")
    if manifest.get("schema_version") != 2:
        raise ArchiveError("Prepared browser manifest version is invalid.")
    if manifest.get("complete_browser_bundle") is not True:
        raise ArchiveError("Prepared browser bundle is not marked complete.")
    if manifest.get("remaining_datasets") != []:
        raise ArchiveError("Prepared browser bundle still lists remaining datasets.")
    datasets = manifest.get("datasets")
    if not isinstance(datasets, dict) or set(datasets) != set(PREPARED_DATASETS):
        raise ArchiveError("Prepared browser dataset registry is invalid.")
    records: dict[str, dict[str, object]] = {}
    for key, name in PREPARED_DATASETS.items():
        path = directory / name
        with path.open("rb") as stream:
            prefix = stream.read(4096).lstrip()
        if not prefix.startswith(b"{"):
            raise ArchiveError(f"Prepared data file is not JSON: {path}")
        record = datasets[key]
        if not isinstance(record, dict) or record.get("relative_path") != name:
            raise ArchiveError(f"Prepared manifest record is invalid: {name}")
        byte_length = path.stat().st_size
        sha256 = sha256_path(path)
        if record.get("byte_length") != byte_length:
            raise ArchiveError(f"Prepared data byte length mismatch: {name}")
        if record.get("sha256") != sha256:
            raise ArchiveError(f"Prepared data hash mismatch: {name}")
        if not isinstance(record.get("feature_count"), int) or record["feature_count"] <= 0:
            raise ArchiveError(f"Prepared data feature count is invalid: {name}")
        records[name] = {"byte_length": byte_length, "sha256": sha256}
    records[PREPARED_MANIFEST] = {
        "byte_length": manifest_path.stat().st_size,
        "sha256": sha256_path(manifest_path),
    }
    return records

def git_source_commit(root: Path) -> str:
    try:
        commit = subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        dirty = subprocess.check_output(
            ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=no"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError) as error:
        raise ArchiveError("A Git checkout is required unless --source-commit is supplied.") from error
    if dirty:
        raise ArchiveError("Tracked repository files are modified; refusing to package an uncommitted tree.")
    if len(commit) != 40 or any(character not in "0123456789abcdef" for character in commit.lower()):
        raise ArchiveError(f"Invalid Git commit identity: {commit}")
    return commit.lower()


def build_payloads(root: Path, prepared: Path) -> list[Payload]:
    payloads: list[Payload] = []
    for relative in TRACKED_RUNTIME:
        source = root / relative
        validate_regular_file(source, "Runtime source file")
        payloads.append(Payload(path=relative, source=source))
    for target, source_relative in GENERATED_FILES.items():
        source = root / source_relative
        validate_regular_file(source, "Deployment template")
        payloads.append(Payload(path=target, content=source.read_bytes()))
    for name in REQUIRED_PREPARED:
        payloads.append(Payload(path=f"data/kane-county/{name}", source=prepared / name))
    return sorted(payloads, key=lambda item: item.path)


def payload_records(payloads: Iterable[Payload]) -> list[PayloadRecord]:
    records: list[PayloadRecord] = []
    for payload in payloads:
        content = payload.read_bytes()
        records.append(PayloadRecord(payload.path, len(content), sha256_bytes(content)))
    return records


def archive_manifest(source_commit: str, records: list[PayloadRecord], prepared_records: dict[str, dict[str, object]]) -> dict[str, object]:
    return {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "project": "kane-offline-map",
        "archive_root": ARCHIVE_ROOT,
        "source_commit": source_commit,
        "payload_file_count": len(records),
        "payload": [record.as_dict() for record in records],
        "prepared_data": prepared_records,
        "manual_additions": [
            "data/reviews/current/",
            "TrivialHTTP runtime files",
        ],
        "review_bundle_included": False,
        "trivialhttp_runtime_included": False,
    }


def zip_info(name: str, directory: bool = False) -> zipfile.ZipInfo:
    normalized = name.rstrip("/") + ("/" if directory else "")
    info = zipfile.ZipInfo(normalized, FIXED_ZIP_TIME)
    info.create_system = 3
    mode = 0o755 if directory else 0o644
    file_type = stat.S_IFDIR if directory else stat.S_IFREG
    info.external_attr = (file_type | mode) << 16
    info.compress_type = zipfile.ZIP_STORED if directory else zipfile.ZIP_DEFLATED
    return info


def parent_directories(paths: Iterable[str]) -> list[str]:
    directories = {ARCHIVE_ROOT}
    for relative in paths:
        parent = PurePosixPath(ARCHIVE_ROOT, relative).parent
        while str(parent) not in (".", ""):
            directories.add(str(parent))
            if str(parent) == ARCHIVE_ROOT:
                break
            parent = parent.parent
    return sorted(directories)


def write_candidate(candidate: Path, payloads: list[Payload], manifest: dict[str, object]) -> None:
    manifest_content = canonical_json(manifest)
    archive_paths = [payload.path for payload in payloads] + ["PORTABLE_MANIFEST.json"]
    with zipfile.ZipFile(candidate, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for directory in parent_directories(archive_paths):
            archive.writestr(zip_info(directory, directory=True), b"")
        for payload in payloads:
            archive.writestr(zip_info(f"{ARCHIVE_ROOT}/{payload.path}"), payload.read_bytes())
        archive.writestr(zip_info(f"{ARCHIVE_ROOT}/PORTABLE_MANIFEST.json"), manifest_content)


def validate_archive(path: Path, expected_manifest: dict[str, object]) -> dict[str, object]:
    validate_regular_file(path, "Portable archive candidate")
    with zipfile.ZipFile(path, "r") as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ArchiveError("Portable archive contains duplicate paths.")
        manifest_name = f"{ARCHIVE_ROOT}/PORTABLE_MANIFEST.json"
        try:
            manifest = json.loads(archive.read(manifest_name).decode("utf-8"))
        except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ArchiveError("Portable archive manifest is unavailable or invalid.") from error
        if manifest != expected_manifest:
            raise ArchiveError("Portable archive manifest does not match the candidate payload.")
        expected_files = {manifest_name}
        for record in manifest["payload"]:
            relative = str(record["path"])
            full_name = f"{ARCHIVE_ROOT}/{relative}"
            expected_files.add(full_name)
            try:
                content = archive.read(full_name)
            except KeyError as error:
                raise ArchiveError(f"Portable archive payload is missing: {relative}") from error
            if len(content) != int(record["byte_length"]):
                raise ArchiveError(f"Portable archive byte length mismatch: {relative}")
            if sha256_bytes(content) != str(record["sha256"]):
                raise ArchiveError(f"Portable archive hash mismatch: {relative}")
        actual_files = {name for name in names if not name.endswith("/")}
        if actual_files != expected_files:
            raise ArchiveError("Portable archive contains unexpected or missing files.")
        if any(name.startswith(f"{ARCHIVE_ROOT}/data/reviews/current/") for name in actual_files):
            raise ArchiveError("Portable archive must not embed the external review bundle.")
    return manifest


def build_archive(root: Path, prepared: Path, output: Path, source_commit: str, force: bool = False) -> dict[str, object]:
    root = root.resolve()
    prepared = prepared.resolve()
    output = output.resolve()
    if output.exists() and not force:
        raise ArchiveError(f"Output already exists; use --force to replace it: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    prepared_records = validate_prepared_data(prepared)
    payloads = build_payloads(root, prepared)
    records = payload_records(payloads)
    manifest = archive_manifest(source_commit, records, prepared_records)
    candidate = output.with_name(f".{output.name}.candidate-{os.getpid()}")
    try:
        candidate.unlink(missing_ok=True)
        write_candidate(candidate, payloads, manifest)
        validate_archive(candidate, manifest)
        os.replace(candidate, output)
    finally:
        candidate.unlink(missing_ok=True)
    return {
        "valid": True,
        "output": str(output),
        "byte_length": output.stat().st_size,
        "sha256": sha256_path(output),
        "source_commit": source_commit,
        "payload_file_count": len(records),
        "prepared_data": prepared_records,
        "review_bundle_included": False,
        "trivialhttp_runtime_included": False,
    }


def parse_arguments(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the Kane Offline Map portable application ZIP.")
    parser.add_argument("prepared_data", type=Path, help="Folder containing the complete prepared browser bundle.")
    parser.add_argument("output", type=Path, help="Destination ZIP path.")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--source-commit", help="Explicit 40-character source commit identity.")
    parser.add_argument("--force", action="store_true", help="Replace an existing output only after candidate validation.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    arguments = parse_arguments(list(sys.argv[1:] if argv is None else argv))
    try:
        source_commit = arguments.source_commit or git_source_commit(arguments.root)
        if len(source_commit) != 40 or any(character not in "0123456789abcdef" for character in source_commit.lower()):
            raise ArchiveError("--source-commit must be a 40-character hexadecimal Git identity.")
        result = build_archive(
            arguments.root,
            arguments.prepared_data,
            arguments.output,
            source_commit.lower(),
            force=arguments.force,
        )
    except ArchiveError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
