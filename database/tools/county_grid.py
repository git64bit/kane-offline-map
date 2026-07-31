#!/usr/bin/env python3
"""Browser-compatible classification-grid calibration and coordinate math."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import sqlite3
from pathlib import Path
from typing import Any, Iterable

SRS_ID = 4326
WORLD = (0.0, 0.0, 1400.0, 900.0)
PADDING = 35.0
REFERENCE_COLUMNS = 6
VALID_COLUMN_START = 1
VALID_COLUMN_COUNT = 4
GRID_SIZE = 512

def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def iter_positions(value: Any) -> Iterable[tuple[float, float]]:
    if not isinstance(value, list):
        return
    if len(value) >= 2 and all(isinstance(item, (int, float)) for item in value[:2]):
        x, y = float(value[0]), float(value[1])
        if not math.isfinite(x) or not math.isfinite(y):
            raise RuntimeError("Boundary coordinates must be finite numbers.")
        if not -180.0 <= x <= 180.0 or not -90.0 <= y <= 90.0:
            raise RuntimeError("Boundary coordinates must be EPSG:4326 longitude/latitude values.")
        yield x, y
        return
    for item in value:
        yield from iter_positions(item)


def load_boundary(path: Path) -> tuple[bytes, tuple[float, float, float, float]]:
    if not path.is_file():
        raise RuntimeError(f"County boundary does not exist: {path}")
    raw = path.read_bytes()
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"County boundary is not valid UTF-8 GeoJSON: {exc}") from exc
    if isinstance(document, dict) and document.get("type") == "FeatureCollection":
        features = document.get("features")
    elif isinstance(document, list):
        features = document
    else:
        raise RuntimeError("County boundary must be a GeoJSON FeatureCollection or feature array.")
    if not isinstance(features, list) or not features:
        raise RuntimeError("County boundary contains no features.")
    positions: list[tuple[float, float]] = []
    for feature in features:
        if not isinstance(feature, dict) or feature.get("type") != "Feature":
            raise RuntimeError("County boundary contains a non-Feature item.")
        geometry = feature.get("geometry")
        if not isinstance(geometry, dict) or geometry.get("type") not in ("Polygon", "MultiPolygon"):
            raise RuntimeError("County boundary features must use Polygon or MultiPolygon geometry.")
        positions.extend(iter_positions(geometry.get("coordinates")))
    if not positions:
        raise RuntimeError("County boundary contains no usable coordinates.")
    xs = [point[0] for point in positions]
    ys = [point[1] for point in positions]
    bounds = min(xs), min(ys), max(xs), max(ys)
    if bounds[0] >= bounds[2] or bounds[1] >= bounds[3]:
        raise RuntimeError("County boundary extent has zero width or height.")
    return raw, bounds


def projection_for(bounds: tuple[float, float, float, float]) -> dict[str, float]:
    raw_min_x, raw_min_y, raw_max_x, raw_max_y = bounds
    world_min_x, world_min_y, world_max_x, world_max_y = WORLD
    raw_width = raw_max_x - raw_min_x
    raw_height = raw_max_y - raw_min_y
    target_width = world_max_x - world_min_x - PADDING * 2.0
    target_height = world_max_y - world_min_y - PADDING * 2.0
    scale = min(target_width / raw_width, target_height / raw_height)
    used_width = raw_width * scale
    used_height = raw_height * scale
    return {
        "raw_min_x": raw_min_x,
        "raw_min_y": raw_min_y,
        "raw_max_x": raw_max_x,
        "raw_max_y": raw_max_y,
        "world_min_x": world_min_x,
        "world_min_y": world_min_y,
        "world_max_x": world_max_x,
        "world_max_y": world_max_y,
        "padding": PADDING,
        "scale": scale,
        "offset_x": world_min_x + (world_max_x - world_min_x - used_width) / 2.0,
        "offset_y": world_min_y + (world_max_y - world_min_y - used_height) / 2.0,
    }




def table_exists(connection: sqlite3.Connection, name: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND name = ?",
        (name,),
    ).fetchone() is not None

def calibration_row(connection: sqlite3.Connection) -> tuple[Any, ...] | None:
    if not table_exists(connection, "classification_grid_calibration"):
        return None
    return connection.execute(
        """
        SELECT g.classification_release_id, g.raw_min_x, g.raw_min_y,
               g.raw_max_x, g.raw_max_y, g.world_min_x, g.world_min_y,
               g.world_max_x, g.world_max_y, g.scale, g.offset_x, g.offset_y
        FROM classification_grid_calibration g
        JOIN classification_release r
          ON r.classification_release_id = g.classification_release_id
        WHERE r.status = 'accepted'
        """
    ).fetchone()


def accepted_classification(connection: sqlite3.Connection) -> int:
    rows = connection.execute(
        "SELECT classification_release_id FROM classification_release WHERE status = 'accepted'"
    ).fetchall()
    if len(rows) != 1:
        raise RuntimeError(f"Accepted classification release count is {len(rows)}; expected 1.")
    return rows[0][0]


def calibrate_connection(connection: sqlite3.Connection, boundary: Path) -> dict[str, Any]:
    raw, bounds = load_boundary(boundary)
    source_hash = sha256_bytes(raw)
    release_id = accepted_classification(connection)
    existing = connection.execute(
        """
        SELECT boundary_sha256 FROM classification_grid_calibration
        WHERE classification_release_id = ?
        """,
        (release_id,),
    ).fetchone()
    if existing:
        if existing[0] != source_hash:
            raise RuntimeError("Accepted classification grid is already calibrated to a different boundary.")
        return {"boundary_sha256": source_hash, "already_calibrated": True}
    projection = projection_for(bounds)
    now = utc_now()
    connection.execute(
        """
        INSERT INTO classification_grid_calibration(
            classification_release_id, boundary_relative_path, boundary_sha256,
            boundary_byte_length, srs_id, raw_min_x, raw_min_y, raw_max_x,
            raw_max_y, world_min_x, world_min_y, world_max_x, world_max_y,
            padding, scale, offset_x, offset_y, calibrated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            release_id,
            boundary.name,
            source_hash,
            len(raw),
            SRS_ID,
            projection["raw_min_x"],
            projection["raw_min_y"],
            projection["raw_max_x"],
            projection["raw_max_y"],
            projection["world_min_x"],
            projection["world_min_y"],
            projection["world_max_x"],
            projection["world_max_y"],
            projection["padding"],
            projection["scale"],
            projection["offset_x"],
            projection["offset_y"],
            now,
        ),
    )
    return {
        "boundary_sha256": source_hash,
        "already_calibrated": False,
    }


def cell_metrics(calibration: tuple[Any, ...]) -> dict[str, float]:
    (
        _, raw_min_x, raw_min_y, raw_max_x, raw_max_y,
        world_min_x, world_min_y, world_max_x, world_max_y,
        scale, offset_x, offset_y,
    ) = calibration
    world_width = world_max_x - world_min_x
    world_height = world_max_y - world_min_y
    valid_min_x = world_min_x + world_width * VALID_COLUMN_START / REFERENCE_COLUMNS
    valid_max_x = valid_min_x + world_width * VALID_COLUMN_COUNT / REFERENCE_COLUMNS
    return {
        "raw_min_x": raw_min_x,
        "raw_min_y": raw_min_y,
        "raw_max_x": raw_max_x,
        "raw_max_y": raw_max_y,
        "valid_min_x": valid_min_x,
        "valid_max_x": valid_max_x,
        "world_min_y": world_min_y,
        "world_max_y": world_max_y,
        "cell_world_width": (valid_max_x - valid_min_x) / GRID_SIZE,
        "cell_world_height": world_height / GRID_SIZE,
        "scale": scale,
        "offset_x": offset_x,
        "offset_y": offset_y,
    }


def world_point(metrics: dict[str, float], point: tuple[float, float]) -> tuple[float, float]:
    return (
        metrics["offset_x"] + (point[0] - metrics["raw_min_x"]) * metrics["scale"],
        metrics["offset_y"] + (metrics["raw_max_y"] - point[1]) * metrics["scale"],
    )


def raw_point(metrics: dict[str, float], point: tuple[float, float]) -> tuple[float, float]:
    return (
        metrics["raw_min_x"] + (point[0] - metrics["offset_x"]) / metrics["scale"],
        metrics["raw_max_y"] - (point[1] - metrics["offset_y"]) / metrics["scale"],
    )


def cell_bounds(metrics: dict[str, float], row: int, column: int) -> tuple[float, float, float, float]:
    x0 = metrics["valid_min_x"] + (column - 1) * metrics["cell_world_width"]
    x1 = x0 + metrics["cell_world_width"]
    y0 = metrics["world_min_y"] + (row - 1) * metrics["cell_world_height"]
    y1 = y0 + metrics["cell_world_height"]
    top_left = raw_point(metrics, (x0, y0))
    bottom_right = raw_point(metrics, (x1, y1))
    return top_left[0], bottom_right[1], bottom_right[0], top_left[1]


def candidate_range(
    metrics: dict[str, float], bounds: tuple[float, float, float, float]
) -> tuple[range, range] | None:
    min_world = world_point(metrics, (bounds[0], bounds[3]))
    max_world = world_point(metrics, (bounds[2], bounds[1]))
    if (
        max_world[0] < metrics["valid_min_x"]
        or min_world[0] > metrics["valid_max_x"]
        or max_world[1] < metrics["world_min_y"]
        or min_world[1] > metrics["world_max_y"]
    ):
        return None
    first_column = math.floor((min_world[0] - metrics["valid_min_x"]) / metrics["cell_world_width"]) + 1
    last_column = math.floor((max_world[0] - metrics["valid_min_x"]) / metrics["cell_world_width"]) + 1
    first_row = math.floor((min_world[1] - metrics["world_min_y"]) / metrics["cell_world_height"]) + 1
    last_row = math.floor((max_world[1] - metrics["world_min_y"]) / metrics["cell_world_height"]) + 1
    first_column = max(1, first_column - 1)
    last_column = min(GRID_SIZE, last_column + 1)
    first_row = max(1, first_row - 1)
    last_row = min(GRID_SIZE, last_row + 1)
    if first_column > last_column or first_row > last_row:
        return None
    return range(first_row, last_row + 1), range(first_column, last_column + 1)


def cell_id_from_global(row: int, column: int) -> str:
    sector_north = 11 + (row - 1) // 128
    sector_east = 6 + (column - 1) // 128
    local_row = (row - 1) % 128
    local_column = (column - 1) % 128
    inspection_row = local_row // 8 + 1
    inspection_column = local_column // 8 + 1
    practical_row = local_row % 8 + 1
    practical_column = local_column % 8 + 1
    return (
        f"N{sector_north}-E{sector_east:02d}:r{inspection_row:02d}c{inspection_column:02d}:"
        f"f{practical_row:02d}c{practical_column:02d}"
    )


def classification_states(connection: sqlite3.Connection, release_id: int) -> bytearray:
    values = bytearray(GRID_SIZE * GRID_SIZE)
    rows = connection.execute(
        """
        SELECT global_row, global_column, classification
        FROM classification_cell WHERE classification_release_id = ?
        ORDER BY global_row, global_column
        """,
        (release_id,),
    )
    count = 0
    codes = {"discovered": 0, "muted": 1, "undiscovered": 2}
    for row, column, state in rows:
        values[(row - 1) * GRID_SIZE + column - 1] = codes[state]
        count += 1
    if count != GRID_SIZE * GRID_SIZE:
        raise RuntimeError(f"Classification grid contains {count} cells; expected {GRID_SIZE * GRID_SIZE}.")
    return values
