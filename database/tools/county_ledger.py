#!/usr/bin/env python3
"""Import and validate the completed County Field Map classification ledger."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import sqlite3
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable

COUNTY_NAME = "Kane County, Illinois"
EXPECTED_SECTORS = tuple(
    f"N{north}-E{east:02d}"
    for north in range(11, 15)
    for east in range(6, 10)
)
SUPPORTED_FORMATS = {"kane-map-sector-state", "county-field-map-sector-state"}
SECTOR_RE = re.compile(r"^N(1[1-4])-E(0[6-9])$")
INSPECTION_RE = re.compile(r"^(N1[1-4]-E0[6-9]):r(0[1-9]|1[0-6])c(0[1-9]|1[0-6])$")
PRACTICAL_RE = re.compile(
    r"^(N1[1-4]-E0[6-9]):r(0[1-9]|1[0-6])c(0[1-9]|1[0-6]):"
    r"f(0[1-8])c(0[1-8])$"
)
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_MEMBER_BYTES = 16 * 1024 * 1024


@dataclass(frozen=True)
class SectorData:
    sector_id: str
    north: int
    east: int
    source_path: str
    source_sha256: str
    updated_at: str
    updated_datetime: dt.datetime
    source_format: str
    source_version: int
    discovered_count: int
    muted_count: int
    cells: tuple[tuple[object, ...], ...]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_timestamp(value: object, label: str) -> tuple[str, dt.datetime]:
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"{label} must be a non-empty timestamp string.")
    raw = value.strip()
    try:
        parsed = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RuntimeError(f"{label} is not a valid ISO-8601 timestamp: {raw}") from exc
    if parsed.tzinfo is None:
        raise RuntimeError(f"{label} must include a time-zone offset: {raw}")
    return raw, parsed.astimezone(dt.timezone.utc)


def checked_string_list(value: object, label: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise RuntimeError(f"{label} must be an array of strings.")
    if len(value) != len(set(value)):
        raise RuntimeError(f"{label} contains duplicate identifiers.")
    return value


def safe_archive_entries(archive: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    entries: dict[str, zipfile.ZipInfo] = {}
    total_size = 0
    for info in archive.infolist():
        if info.is_dir():
            continue
        path = PurePosixPath(info.filename)
        if path.is_absolute() or ".." in path.parts:
            raise RuntimeError(f"Unsafe archive member path: {info.filename}")
        if info.flag_bits & 0x1:
            raise RuntimeError(f"Encrypted archive members are not accepted: {info.filename}")
        if info.file_size > MAX_MEMBER_BYTES:
            raise RuntimeError(f"Archive member is too large: {info.filename}")
        total_size += info.file_size
        if total_size > MAX_ARCHIVE_BYTES:
            raise RuntimeError("Archive expands beyond the permitted size.")
        if path.suffix.lower() != ".json":
            raise RuntimeError(f"Unexpected non-JSON archive member: {info.filename}")
        sector_id = path.stem
        if sector_id in entries:
            raise RuntimeError(f"Duplicate sector filename in archive: {sector_id}")
        entries[sector_id] = info
    expected = set(EXPECTED_SECTORS)
    actual = set(entries)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        details = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if extra:
            details.append("unexpected " + ", ".join(extra))
        raise RuntimeError("Archive sector set is invalid: " + "; ".join(details))
    return entries


def parse_sector_document(source_path: str, raw: bytes) -> SectorData:
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Invalid JSON in {source_path}: {exc}") from exc
    if not isinstance(document, dict):
        raise RuntimeError(f"Sector document must be an object: {source_path}")

    source_format = document.get("format")
    source_version = document.get("version")
    county = document.get("county")
    sector_id = document.get("sector")
    if source_format not in SUPPORTED_FORMATS:
        raise RuntimeError(f"Unsupported sector format in {source_path}: {source_format}")
    if source_version != 1:
        raise RuntimeError(f"Unsupported sector version in {source_path}: {source_version}")
    if county != COUNTY_NAME:
        raise RuntimeError(f"Unexpected county identity in {source_path}: {county}")
    match = SECTOR_RE.fullmatch(str(sector_id or ""))
    if not match or sector_id != PurePosixPath(source_path).stem:
        raise RuntimeError(f"Sector identity does not match its filename: {source_path}")
    north, east = int(match.group(1)), int(match.group(2))
    updated_at, updated_datetime = parse_timestamp(document.get("updatedAt"), f"{source_path} updatedAt")

    state = document.get("state")
    if not isinstance(state, dict):
        raise RuntimeError(f"Missing state object in {source_path}.")
    inspection = state.get("inspection")
    practical = state.get("practical")
    if not isinstance(inspection, dict) or not isinstance(practical, dict):
        raise RuntimeError(f"Missing inspection or practical state in {source_path}.")

    inspection_active = set(checked_string_list(inspection.get("active"), f"{source_path} inspection.active"))
    inspection_muted = set(checked_string_list(inspection.get("muted"), f"{source_path} inspection.muted"))
    practical_active = set(checked_string_list(practical.get("active"), f"{source_path} practical.active"))
    practical_muted = set(checked_string_list(practical.get("muted"), f"{source_path} practical.muted"))
    if inspection_active & inspection_muted:
        raise RuntimeError(f"Inspection state overlaps in {source_path}.")
    if practical_active & practical_muted:
        raise RuntimeError(f"Practical state overlaps in {source_path}.")

    expected_inspection: set[str] = set()
    expected_practical: set[str] = set()
    cells: list[tuple[object, ...]] = []
    discovered_count = 0
    muted_count = 0
    for inspection_row in range(1, 17):
        for inspection_column in range(1, 17):
            inspection_id = f"{sector_id}:r{inspection_row:02d}c{inspection_column:02d}"
            expected_inspection.add(inspection_id)
            local_discovered = 0
            local_muted = 0
            for practical_row in range(1, 9):
                for practical_column in range(1, 9):
                    cell_id = f"{inspection_id}:f{practical_row:02d}c{practical_column:02d}"
                    expected_practical.add(cell_id)
                    if cell_id in practical_active:
                        classification = "discovered"
                        local_discovered += 1
                        discovered_count += 1
                    elif cell_id in practical_muted:
                        classification = "muted"
                        local_muted += 1
                        muted_count += 1
                    else:
                        raise RuntimeError(f"Completed ledger has an unclassified cell: {cell_id}")
                    global_row = (north - 11) * 128 + (inspection_row - 1) * 8 + practical_row
                    global_column = (east - 6) * 128 + (inspection_column - 1) * 8 + practical_column
                    cells.append((
                        cell_id, sector_id, north, east,
                        inspection_row, inspection_column,
                        practical_row, practical_column,
                        global_row, global_column, classification,
                    ))
            expected_state = "active" if local_discovered else "muted"
            actual_state = "active" if inspection_id in inspection_active else (
                "muted" if inspection_id in inspection_muted else "missing"
            )
            if local_discovered + local_muted != 64 or actual_state != expected_state:
                raise RuntimeError(
                    f"Inspection summary disagrees with practical cells: {inspection_id} "
                    f"expected {expected_state}, found {actual_state}."
                )

    if inspection_active | inspection_muted != expected_inspection:
        unknown = sorted((inspection_active | inspection_muted) - expected_inspection)
        raise RuntimeError(f"Inspection identifiers are incomplete or invalid in {source_path}: {unknown[:3]}")
    if practical_active | practical_muted != expected_practical:
        unknown = sorted((practical_active | practical_muted) - expected_practical)
        raise RuntimeError(f"Practical identifiers are incomplete or invalid in {source_path}: {unknown[:3]}")
    expected_sector_state = "active" if discovered_count else "muted"
    if state.get("sector") != expected_sector_state:
        raise RuntimeError(
            f"Sector summary disagrees with practical cells in {source_path}: "
            f"expected {expected_sector_state}, found {state.get('sector')}."
        )
    return SectorData(
        sector_id=sector_id,
        north=north,
        east=east,
        source_path=source_path,
        source_sha256=sha256_bytes(raw),
        updated_at=updated_at,
        updated_datetime=updated_datetime,
        source_format=source_format,
        source_version=source_version,
        discovered_count=discovered_count,
        muted_count=muted_count,
        cells=tuple(cells),
    )


def read_archive(path: Path) -> tuple[str, tuple[SectorData, ...]]:
    if not path.is_file():
        raise RuntimeError(f"Ledger archive does not exist: {path}")
    raw_archive = path.read_bytes()
    if len(raw_archive) > MAX_ARCHIVE_BYTES:
        raise RuntimeError("Ledger archive exceeds the permitted size.")
    archive_sha256 = sha256_bytes(raw_archive)
    try:
        with zipfile.ZipFile(path) as archive:
            entries = safe_archive_entries(archive)
            sectors = tuple(
                parse_sector_document(entries[sector_id].filename, archive.read(entries[sector_id]))
                for sector_id in EXPECTED_SECTORS
            )
    except zipfile.BadZipFile as exc:
        raise RuntimeError(f"Ledger archive is not a valid ZIP file: {path}") from exc
    formats = {sector.source_format for sector in sectors}
    versions = {sector.source_version for sector in sectors}
    if len(formats) != 1 or len(versions) != 1:
        raise RuntimeError("Sector files do not use one consistent format and version.")
    return archive_sha256, sectors


def import_ledger(database: Path, archive: Path, release_key: str | None = None) -> dict[str, object]:
    archive_sha256, sectors = read_archive(archive)
    release_key = release_key or f"kane-field-ledger-{archive_sha256[:12]}"
    source_created_at = max(sector.updated_datetime for sector in sectors)
    source_created = source_created_at.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    discovered_count = sum(sector.discovered_count for sector in sectors)
    muted_count = sum(sector.muted_count for sector in sectors)
    practical_count = discovered_count + muted_count
    if len(sectors) != 16 or practical_count != 262144:
        raise RuntimeError("Completed ledger totals are not 16 sectors and 262,144 practical cells.")

    connection = sqlite3.connect(database)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        with connection:
            county_row = connection.execute(
                "SELECT county_id FROM county WHERE fips_code = '17089'"
            ).fetchone()
            if not county_row:
                raise RuntimeError("Kane County identity row is missing from the database.")
            if connection.execute(
                "SELECT 1 FROM classification_release WHERE release_key = ? OR source_archive_sha256 = ?",
                (release_key, archive_sha256),
            ).fetchone():
                raise RuntimeError("This classification release or archive is already imported.")
            cursor = connection.execute(
                """
                INSERT INTO classification_release(
                    county_id, release_key, source_format, source_version,
                    source_archive_sha256, source_created_at, imported_at, status,
                    sector_count, inspection_cell_count, practical_cell_count,
                    discovered_count, muted_count, undiscovered_count, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'accepted', 16, 4096, 262144, ?, ?, 0, ?)
                """,
                (
                    county_row[0], release_key, sectors[0].source_format,
                    sectors[0].source_version, archive_sha256, source_created,
                    utc_now(), discovered_count, muted_count,
                    "Completed County Field Map classification baseline imported from immutable JSON archive.",
                ),
            )
            release_id = int(cursor.lastrowid)
            for sector in sectors:
                connection.execute(
                    """
                    INSERT INTO classification_sector(
                        classification_release_id, sector_id, source_relative_path,
                        source_sha256, source_updated_at, inspection_cell_count,
                        practical_cell_count, discovered_count, muted_count,
                        undiscovered_count
                    ) VALUES (?, ?, ?, ?, ?, 256, 16384, ?, ?, 0)
                    """,
                    (
                        release_id, sector.sector_id, sector.source_path,
                        sector.source_sha256, sector.updated_at,
                        sector.discovered_count, sector.muted_count,
                    ),
                )
                connection.executemany(
                    """
                    INSERT INTO classification_cell(
                        classification_release_id, cell_id, sector_id,
                        sector_north, sector_east, inspection_row,
                        inspection_column, practical_row, practical_column,
                        global_row, global_column, classification
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    ((release_id, *cell) for cell in sector.cells),
                )
            now = utc_now()
            settings = [
                ("tool_version", "batch-006.1", now),
                ("classification_release_key", release_key, now),
                ("classification_archive_sha256", archive_sha256, now),
            ]
            connection.executemany(
                """
                INSERT INTO project_setting(setting_key, setting_value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(setting_key) DO UPDATE SET
                    setting_value = excluded.setting_value,
                    updated_at = excluded.updated_at
                """,
                settings,
            )
            errors = classification_errors(connection, require_accepted=True)
            if errors:
                raise RuntimeError("Imported classification failed validation:\n- " + "\n- ".join(errors))
    finally:
        connection.close()
    return ledger_info(database)


def classification_errors(
    connection: sqlite3.Connection,
    require_accepted: bool,
) -> list[str]:
    errors: list[str] = []
    releases = connection.execute(
        """
        SELECT classification_release_id, status, sector_count,
               inspection_cell_count, practical_cell_count,
               discovered_count, muted_count, undiscovered_count,
               source_archive_sha256
        FROM classification_release
        ORDER BY classification_release_id
        """
    ).fetchall()
    accepted = [row for row in releases if row[1] == "accepted"]
    if require_accepted and len(accepted) != 1:
        errors.append(f"Accepted classification release count is {len(accepted)}; expected 1.")
    for release in releases:
        release_id = release[0]
        expected_counts = tuple(release[2:8])
        if release[1] == "accepted":
            grid_counts = (release[2], release[3], release[4], release[7])
            if grid_counts != (16, 4096, 262144, 0):
                errors.append(
                    f"Accepted release {release_id} does not describe one complete 512 x 512 grid: "
                    f"{grid_counts}."
                )
        if not re.fullmatch(r"[0-9a-f]{64}", str(release[8])):
            errors.append(f"Release {release_id} has an invalid archive SHA-256.")
        sector_rows = connection.execute(
            """
            SELECT COUNT(*), COALESCE(SUM(inspection_cell_count), 0),
                   COALESCE(SUM(practical_cell_count), 0),
                   COALESCE(SUM(discovered_count), 0),
                   COALESCE(SUM(muted_count), 0),
                   COALESCE(SUM(undiscovered_count), 0)
            FROM classification_sector WHERE classification_release_id = ?
            """,
            (release_id,),
        ).fetchone()
        cell_rows = connection.execute(
            """
            SELECT COUNT(*),
                   SUM(CASE WHEN classification = 'discovered' THEN 1 ELSE 0 END),
                   SUM(CASE WHEN classification = 'muted' THEN 1 ELSE 0 END),
                   SUM(CASE WHEN classification = 'undiscovered' THEN 1 ELSE 0 END),
                   MIN(global_row), MAX(global_row), MIN(global_column), MAX(global_column)
            FROM classification_cell WHERE classification_release_id = ?
            """,
            (release_id,),
        ).fetchone()
        if tuple(sector_rows) != expected_counts:
            errors.append(f"Release {release_id} sector totals disagree with its release row.")
        cell_counts = (cell_rows[0], cell_rows[1] or 0, cell_rows[2] or 0, cell_rows[3] or 0)
        if cell_counts != (release[4], release[5], release[6], release[7]):
            errors.append(f"Release {release_id} cell totals disagree with its release row.")
        if release[1] == "accepted" and tuple(cell_rows[4:]) != (1, 512, 1, 512):
            errors.append(f"Accepted release {release_id} does not span the full 512 x 512 grid.")
        invalid = connection.execute(
            """
            SELECT COUNT(*) FROM classification_cell
            WHERE classification_release_id = ? AND (
                cell_id != printf(
                    'N%d-E%02d:r%02dc%02d:f%02dc%02d',
                    sector_north, sector_east, inspection_row,
                    inspection_column, practical_row, practical_column
                ) OR
                global_row != (sector_north - 11) * 128 + (inspection_row - 1) * 8 + practical_row OR
                global_column != (sector_east - 6) * 128 + (inspection_column - 1) * 8 + practical_column
            )
            """,
            (release_id,),
        ).fetchone()[0]
        if invalid:
            errors.append(f"Release {release_id} contains {invalid} non-canonical cell identities.")
    return errors


def ledger_info(database: Path) -> dict[str, object]:
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    try:
        row = connection.execute(
            """
            SELECT release_key, source_format, source_version,
                   source_archive_sha256, source_created_at, imported_at,
                   status, sector_count, inspection_cell_count,
                   practical_cell_count, discovered_count, muted_count,
                   undiscovered_count
            FROM classification_release
            WHERE status = 'accepted'
            """
        ).fetchone()
        if not row:
            return {"accepted_classification": None}
        return {
            "accepted_classification": {
                "release_key": row[0],
                "source_format": row[1],
                "source_version": row[2],
                "source_archive_sha256": row[3],
                "source_created_at": row[4],
                "imported_at": row[5],
                "status": row[6],
                "sector_count": row[7],
                "inspection_cell_count": row[8],
                "practical_cell_count": row[9],
                "discovered_count": row[10],
                "muted_count": row[11],
                "undiscovered_count": row[12],
            }
        }
    finally:
        connection.close()
