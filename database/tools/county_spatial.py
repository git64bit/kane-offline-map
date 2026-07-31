#!/usr/bin/env python3
"""Calibrate the field grid and relate building polygons to practical cells."""

from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

import county_geometry
import county_grid

decode_geometry = county_geometry.decode_geometry
geometry_intersects_rect = county_geometry.geometry_intersects_rect
polygon_intersects_rect = county_geometry.polygon_intersects_rect


def calibrate_database(database: Path, boundary: Path) -> dict[str, object]:
    import county_building_refresh
    import county_db

    if not database.is_file():
        raise RuntimeError(f"Accepted database does not exist: {database}")
    database.parent.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(
        prefix=f".{database.name}.", suffix=".spatial-candidate", dir=database.parent
    )
    os.close(handle)
    candidate = Path(name)
    try:
        shutil.copy2(database, candidate)
        county_building_refresh.upgrade_candidate(candidate)
        connection = sqlite3.connect(candidate)
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            with connection:
                result = county_grid.calibrate_connection(connection, boundary)
                accepted_building = connection.execute(
                    """
                    SELECT r.release_id FROM source_release r
                    JOIN dataset d ON d.dataset_id = r.dataset_id
                    WHERE d.dataset_key = 'buildings' AND r.status = 'accepted'
                    """
                ).fetchone()
                if accepted_building:
                    result.update(index_building_release(
                        connection, accepted_building[0], None, county_grid.utc_now()
                    ))
        finally:
            connection.close()
        errors = county_db.validate_spatial_database(candidate)
        if errors:
            raise RuntimeError("Spatial candidate failed validation:\n- " + "\n- ".join(errors))
        os.replace(candidate, database)
        return {**county_db.database_info(database), "calibration_result": result}
    finally:
        candidate.unlink(missing_ok=True)


def index_building_release(
    connection: sqlite3.Connection,
    release_id: int,
    review_source_ids: set[str] | None,
    indexed_at: str | None = None,
) -> dict[str, int]:
    calibration = county_grid.calibration_row(connection)
    if calibration is None:
        return {"relation_count": 0, "review_count": 0}
    indexed_at = indexed_at or county_grid.utc_now()
    classification_release_id = calibration[0]
    metrics = county_grid.cell_metrics(calibration)
    states = county_grid.classification_states(connection, classification_release_id)
    release = connection.execute(
        """
        SELECT r.dataset_id, d.dataset_key FROM source_release r
        JOIN dataset d ON d.dataset_id = r.dataset_id WHERE r.release_id = ?
        """,
        (release_id,),
    ).fetchone()
    if release is None or release[1] != "buildings":
        raise RuntimeError("Spatial indexing target is not a building release.")
    dataset_id = release[0]
    relation_rows: list[tuple[Any, ...]] = []
    review_rows: list[tuple[Any, ...]] = []
    relation_count = 0
    review_count = 0

    def flush_rows() -> None:
        nonlocal relation_count, review_count
        if relation_rows:
            before = connection.total_changes
            connection.executemany(
                """
                INSERT OR IGNORE INTO building_cell_relation(
                    source_building_id, classification_release_id, global_row,
                    global_column, relation_type, indexed_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                relation_rows,
            )
            relation_count += connection.total_changes - before
            relation_rows.clear()
        if review_rows:
            before = connection.total_changes
            connection.executemany(
                """
                INSERT OR IGNORE INTO classification_review(
                    classification_release_id, cell_id, trigger_dataset_id,
                    trigger_source_feature_id, previous_classification,
                    recommended_classification, detected_in_release_id, detected_at,
                    review_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                review_rows,
            )
            review_count += connection.total_changes - before
            review_rows.clear()

    buildings = connection.execute(
        """
        SELECT source_building_id, source_feature_id, geometry,
               min_x, min_y, max_x, max_y
        FROM source_building WHERE release_id = ? ORDER BY source_ordinal
        """,
        (release_id,),
    )
    for building_id, source_id, blob, min_x, min_y, max_x, max_y in buildings:
        polygons = county_geometry.decode_geometry(blob)
        candidates = county_grid.candidate_range(metrics, (min_x, min_y, max_x, max_y))
        if candidates is None:
            continue
        rows, columns = candidates
        for row in rows:
            for column in columns:
                if not county_geometry.geometry_intersects_rect(polygons, county_grid.cell_bounds(metrics, row, column)):
                    continue
                relation_rows.append(
                    (
                        building_id,
                        classification_release_id,
                        row,
                        column,
                        "intersects",
                        indexed_at,
                    )
                )
                should_review = review_source_ids is None or source_id in review_source_ids
                state_code = states[(row - 1) * county_grid.GRID_SIZE + column - 1]
                if should_review and state_code in (1, 2):
                    previous = "muted" if state_code == 1 else "undiscovered"
                    review_rows.append(
                        (
                            classification_release_id,
                            county_grid.cell_id_from_global(row, column),
                            dataset_id,
                            source_id,
                            previous,
                            "discovered",
                            release_id,
                            indexed_at,
                            "open",
                        )
                    )
                if len(relation_rows) >= 10000:
                    flush_rows()
    flush_rows()
    return {"relation_count": relation_count, "review_count": review_count}


def review_source_ids_for_release(connection: sqlite3.Connection, release_id: int) -> set[str] | None:
    if not county_grid.table_exists(connection, "building_release_comparison"):
        return None
    comparison = connection.execute(
        "SELECT comparison_id FROM building_release_comparison WHERE candidate_release_id = ?",
        (release_id,),
    ).fetchone()
    if comparison is None:
        return None
    return {
        row[0]
        for row in connection.execute(
            """
            SELECT source_feature_id FROM building_feature_change
            WHERE comparison_id = ? AND change_type IN ('added', 'geometry_changed', 'modified')
            """,
            (comparison[0],),
        )
    }


def spatial_errors(connection: sqlite3.Connection, require_calibrated: bool) -> list[str]:
    errors: list[str] = []
    calibrations = connection.execute(
        """
        SELECT classification_release_id, boundary_sha256, boundary_byte_length,
               raw_min_x, raw_min_y, raw_max_x, raw_max_y, scale
        FROM classification_grid_calibration
        """
    ).fetchall()
    if require_calibrated and len(calibrations) != 1:
        errors.append(f"Classification grid calibration count is {len(calibrations)}; expected 1.")
        return errors
    if not calibrations:
        relation_count = connection.execute("SELECT COUNT(*) FROM building_cell_relation").fetchone()[0]
        if relation_count:
            errors.append("Building-cell relations exist without a grid calibration.")
        return errors
    for release_id, boundary_hash, byte_length, min_x, min_y, max_x, max_y, scale in calibrations:
        if len(boundary_hash) != 64 or byte_length <= 0 or min_x >= max_x or min_y >= max_y or scale <= 0:
            errors.append(f"Classification calibration {release_id} metadata is invalid.")
    if not require_calibrated:
        return errors
    for release_id, *_ in calibrations:
        count = connection.execute(
            "SELECT COUNT(*) FROM classification_cell_spatial WHERE classification_release_id = ?",
            (release_id,),
        ).fetchone()[0]
        if count != county_grid.GRID_SIZE * county_grid.GRID_SIZE:
            errors.append(f"Spatial classification view contains {count} cells; expected {county_grid.GRID_SIZE * county_grid.GRID_SIZE}.")
        endpoint_rows = connection.execute(
            """
            SELECT global_row, global_column, min_x, min_y, max_x, max_y
            FROM classification_cell_spatial
            WHERE classification_release_id = ? AND (
                (global_row = 1 AND global_column = 1) OR
                (global_row = 512 AND global_column = 512)
            ) ORDER BY global_row, global_column
            """,
            (release_id,),
        ).fetchall()
        if len(endpoint_rows) != 2 or any(row[2] >= row[4] or row[3] >= row[5] for row in endpoint_rows):
            errors.append(f"Spatial classification view endpoints are invalid for release {release_id}.")
    invalid_relations = connection.execute(
        """
        SELECT COUNT(*) FROM building_cell_relation r
        LEFT JOIN source_building b ON b.source_building_id = r.source_building_id
        LEFT JOIN classification_cell c
          ON c.classification_release_id = r.classification_release_id
         AND c.global_row = r.global_row AND c.global_column = r.global_column
        WHERE b.source_building_id IS NULL OR c.cell_id IS NULL
        """
    ).fetchone()[0]
    if invalid_relations:
        errors.append(f"Building-cell relation foreign coverage is invalid for {invalid_relations} rows.")
    accepted = connection.execute(
        """
        SELECT r.release_id FROM source_release r JOIN dataset d ON d.dataset_id = r.dataset_id
        WHERE d.dataset_key = 'buildings' AND r.status = 'accepted'
        """
    ).fetchone()
    if require_calibrated and accepted:
        calibration = county_grid.calibration_row(connection)
        if calibration is not None:
            metrics = county_grid.cell_metrics(calibration)
            first = county_grid.cell_bounds(metrics, 1, 1)
            last = county_grid.cell_bounds(metrics, 512, 512)
            grid_rect = (first[0], last[1], last[2], first[3])
            expected_indexed = {
                building_id
                for building_id, blob in connection.execute(
                    "SELECT source_building_id, geometry FROM source_building WHERE release_id = ?",
                    (accepted[0],),
                )
                if county_geometry.geometry_intersects_rect(
                    county_geometry.decode_geometry(blob), grid_rect
                )
            }
            actual_indexed = {
                row[0] for row in connection.execute(
                    """
                    SELECT DISTINCT b.source_building_id
                    FROM source_building b JOIN building_cell_relation r
                      ON r.source_building_id = b.source_building_id
                    WHERE b.release_id = ?
                    """,
                    (accepted[0],),
                )
            }
            if actual_indexed != expected_indexed:
                errors.append(
                    "Accepted building spatial coverage is incomplete or includes outside geometry."
                )
    orphan_reviews = connection.execute(
        """
        SELECT COUNT(*) FROM classification_review r
        JOIN source_building b
          ON b.release_id = r.detected_in_release_id
         AND b.source_feature_id = r.trigger_source_feature_id
        JOIN classification_cell c
          ON c.classification_release_id = r.classification_release_id
         AND c.cell_id = r.cell_id
        LEFT JOIN building_cell_relation rel
          ON rel.source_building_id = b.source_building_id
         AND rel.classification_release_id = r.classification_release_id
         AND rel.global_row = c.global_row
         AND rel.global_column = c.global_column
        WHERE r.trigger_dataset_id IS NOT NULL
          AND rel.source_building_id IS NULL
        """
    ).fetchone()[0]
    if orphan_reviews:
        errors.append(f"Spatial review triggers lack {orphan_reviews} building-cell relations.")
    review_errors = connection.execute(
        """
        SELECT COUNT(*) FROM classification_review r
        JOIN classification_cell c
          ON c.classification_release_id = r.classification_release_id
         AND c.cell_id = r.cell_id
        WHERE r.trigger_dataset_id IS NOT NULL
          AND r.recommended_classification = 'discovered'
          AND c.classification NOT IN ('muted', 'undiscovered')
        """
    ).fetchone()[0]
    if review_errors:
        errors.append(f"Spatial review triggers point to {review_errors} already-discovered cells.")
    return errors


def spatial_info(path: Path) -> dict[str, Any]:
    probe = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        if not county_grid.table_exists(probe, "classification_grid_calibration"):
            return {}
    finally:
        probe.close()
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        calibration = connection.execute(
            """
            SELECT boundary_relative_path, boundary_sha256, calibrated_at,
                   raw_min_x, raw_min_y, raw_max_x, raw_max_y
            FROM classification_grid_calibration
            """
        ).fetchone()
        if calibration is None:
            return {}
        accepted = connection.execute(
            """
            SELECT r.release_id FROM source_release r JOIN dataset d ON d.dataset_id = r.dataset_id
            WHERE d.dataset_key = 'buildings' AND r.status = 'accepted'
            """
        ).fetchone()
        relation_count = 0
        feature_count = 0
        if accepted:
            relation_count = connection.execute(
                """
                SELECT COUNT(*) FROM building_cell_relation rel
                JOIN source_building b ON b.source_building_id = rel.source_building_id
                WHERE b.release_id = ?
                """,
                (accepted[0],),
            ).fetchone()[0]
            feature_count = connection.execute(
                """
                SELECT COUNT(DISTINCT b.source_building_id)
                FROM building_cell_relation rel
                JOIN source_building b ON b.source_building_id = rel.source_building_id
                WHERE b.release_id = ?
                """,
                (accepted[0],),
            ).fetchone()[0]
        reviews = connection.execute(
            "SELECT COUNT(*) FROM classification_review WHERE trigger_dataset_id IS NOT NULL"
        ).fetchone()[0]
        open_reviews = connection.execute(
            """
            SELECT COUNT(*) FROM classification_review
            WHERE trigger_dataset_id IS NOT NULL AND review_status = 'open'
            """
        ).fetchone()[0]
        return {
            "spatial_grid": {
                "boundary_relative_path": calibration[0],
                "boundary_sha256": calibration[1],
                "calibrated_at": calibration[2],
                "bounds": {
                    "min_x": calibration[3],
                    "min_y": calibration[4],
                    "max_x": calibration[5],
                    "max_y": calibration[6],
                },
                "srs_id": county_grid.SRS_ID,
                "accepted_building_relation_count": relation_count,
                "accepted_building_indexed_feature_count": feature_count,
                "review_count": reviews,
                "open_review_count": open_reviews,
            }
        }
    finally:
        connection.close()
