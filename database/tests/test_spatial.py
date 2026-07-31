from __future__ import annotations

import importlib.util
import json
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools"
MODULE_PATH = TOOLS / "county_db.py"
INPUT_ARCHIVE = Path(__file__).resolve().parents[1] / "input" / "sectors.zip"
BOUNDARY = Path(__file__).resolve().parents[1] / "fixtures" / "county-boundary-sample.geojson"
BUILDINGS_V1 = Path(__file__).resolve().parents[1] / "fixtures" / "buildings-sample.geojson"
BUILDINGS_V2 = Path(__file__).resolve().parents[1] / "fixtures" / "buildings-refresh-v2.geojson"
SPEC = importlib.util.spec_from_file_location("county_db_spatial_test", MODULE_PATH)
county_db = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(county_db)

TEMP_DIR: tempfile.TemporaryDirectory[str]
CALIBRATED: Path
REFRESHED: Path


def build(path: Path) -> None:
    county_db.build_building_database(
        path,
        INPUT_ARCHIVE,
        BUILDINGS_V1,
        force=False,
        ledger_release_key=None,
        building_release_key="fixture-buildings-v1",
        source_uri="fixture://buildings-sample.geojson",
        published_at="2026-07-29T00:00:00Z",
        id_property=None,
    )


def setUpModule() -> None:
    global TEMP_DIR, CALIBRATED, REFRESHED
    TEMP_DIR = tempfile.TemporaryDirectory()
    CALIBRATED = Path(TEMP_DIR.name) / "calibrated.gpkg"
    REFRESHED = Path(TEMP_DIR.name) / "refreshed.gpkg"
    build(CALIBRATED)
    county_db.county_spatial.calibrate_database(CALIBRATED, BOUNDARY)
    shutil.copy2(CALIBRATED, REFRESHED)
    county_db.county_building_refresh.refresh_building_database(
        REFRESHED,
        BUILDINGS_V2,
        release_key="fixture-buildings-v2",
        source_uri="fixture://buildings-refresh-v2.geojson",
        published_at="2026-07-30T00:00:00Z",
        id_property=None,
    )


def tearDownModule() -> None:
    TEMP_DIR.cleanup()


class SpatialCalibrationTests(unittest.TestCase):
    def test_calibration_validates_and_reports(self) -> None:
        self.assertEqual([], county_db.validate_spatial_database(CALIBRATED))
        info = county_db.database_info(CALIBRATED)["spatial_grid"]
        self.assertEqual(4326, info["srs_id"])
        self.assertEqual("county-boundary-sample.geojson", info["boundary_relative_path"])
        self.assertEqual(3, info["accepted_building_indexed_feature_count"])
        self.assertEqual(19, info["accepted_building_relation_count"])
        self.assertEqual(11, info["open_review_count"])

    def test_spatial_view_has_complete_grid_and_ordered_bounds(self) -> None:
        connection = sqlite3.connect(CALIBRATED)
        try:
            count = connection.execute("SELECT COUNT(*) FROM classification_cell_spatial").fetchone()[0]
            endpoints = connection.execute(
                """
                SELECT cell_id, min_x, min_y, max_x, max_y
                FROM classification_cell_spatial
                WHERE (global_row = 1 AND global_column = 1)
                   OR (global_row = 512 AND global_column = 512)
                ORDER BY global_row, global_column
                """
            ).fetchall()
        finally:
            connection.close()
        self.assertEqual(262144, count)
        self.assertEqual("N11-E06:r01c01:f01c01", endpoints[0][0])
        self.assertEqual("N14-E09:r16c16:f08c08", endpoints[1][0])
        self.assertTrue(all(row[1] < row[3] and row[2] < row[4] for row in endpoints))
        self.assertGreater(endpoints[0][2], endpoints[1][2])
        connection = sqlite3.connect(CALIBRATED)
        try:
            calibration = county_db.county_spatial.county_grid.calibration_row(connection)
            sql_bounds = connection.execute(
                """
                SELECT min_x, min_y, max_x, max_y FROM classification_cell_spatial
                WHERE global_row = 256 AND global_column = 256
                """
            ).fetchone()
        finally:
            connection.close()
        expected = county_db.county_spatial.county_grid.cell_bounds(
            county_db.county_spatial.county_grid.cell_metrics(calibration), 256, 256
        )
        for actual, wanted in zip(sql_bounds, expected):
            self.assertAlmostEqual(wanted, actual, places=12)

    def test_building_relations_are_exact_geometry_intersections(self) -> None:
        connection = sqlite3.connect(CALIBRATED)
        try:
            rows = connection.execute(
                """
                SELECT b.geometry, s.min_x, s.min_y, s.max_x, s.max_y
                FROM building_cell_relation r
                JOIN source_building b ON b.source_building_id = r.source_building_id
                JOIN classification_cell_spatial s
                  ON s.classification_release_id = r.classification_release_id
                 AND s.global_row = r.global_row AND s.global_column = r.global_column
                """
            ).fetchall()
        finally:
            connection.close()
        self.assertGreater(len(rows), 0)
        for blob, min_x, min_y, max_x, max_y in rows:
            polygons = county_db.county_spatial.decode_geometry(blob)
            self.assertTrue(
                county_db.county_spatial.geometry_intersects_rect(
                    polygons, (min_x, min_y, max_x, max_y)
                )
            )

    def test_reviews_reference_only_muted_cells(self) -> None:
        connection = sqlite3.connect(CALIBRATED)
        try:
            rows = connection.execute(
                """
                SELECT c.classification, r.recommended_classification, r.review_status
                FROM classification_review r
                JOIN classification_cell c
                  ON c.classification_release_id = r.classification_release_id
                 AND c.cell_id = r.cell_id
                WHERE r.trigger_dataset_id IS NOT NULL
                """
            ).fetchall()
        finally:
            connection.close()
        self.assertGreater(len(rows), 0)
        self.assertEqual({"muted"}, {row[0] for row in rows})
        self.assertEqual({"discovered"}, {row[1] for row in rows})
        self.assertEqual({"open"}, {row[2] for row in rows})

    def test_recalibration_to_different_boundary_preserves_database(self) -> None:
        database = Path(TEMP_DIR.name) / "recalibration.gpkg"
        shutil.copy2(CALIBRATED, database)
        document = json.loads(BOUNDARY.read_text(encoding="utf-8"))
        document["features"][0]["geometry"]["coordinates"][0][1][0] = -88.0000
        different = Path(TEMP_DIR.name) / "different-boundary.geojson"
        different.write_text(json.dumps(document), encoding="utf-8")
        before = database.read_bytes()
        with self.assertRaisesRegex(RuntimeError, "different boundary"):
            county_db.county_spatial.calibrate_database(database, different)
        self.assertEqual(before, database.read_bytes())


class SpatialRefreshTests(unittest.TestCase):
    def test_refresh_indexes_new_release_and_only_spatial_changes_trigger_review(self) -> None:
        self.assertEqual([], county_db.validate_spatial_database(REFRESHED))
        connection = sqlite3.connect(REFRESHED)
        try:
            accepted_id = connection.execute(
                "SELECT release_id FROM source_release WHERE release_key = 'fixture-buildings-v2'"
            ).fetchone()[0]
            indexed = connection.execute(
                """
                SELECT COUNT(DISTINCT b.source_feature_id)
                FROM source_building b JOIN building_cell_relation r
                  ON r.source_building_id = b.source_building_id
                WHERE b.release_id = ?
                """,
                (accepted_id,),
            ).fetchone()[0]
            review_ids = {
                row[0] for row in connection.execute(
                    """
                    SELECT DISTINCT trigger_source_feature_id FROM classification_review
                    WHERE detected_in_release_id = ?
                    """,
                    (accepted_id,),
                )
            }
        finally:
            connection.close()
        self.assertEqual(3, indexed)
        self.assertNotIn("fixture-building-001", review_ids)
        self.assertEqual({"fixture-building-002", "fixture-building-004"}, review_ids)

    def test_polygon_hole_does_not_create_false_interior_intersection(self) -> None:
        polygon = [[
            (0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0), (0.0, 0.0)
        ], [
            (3.0, 3.0), (7.0, 3.0), (7.0, 7.0), (3.0, 7.0), (3.0, 3.0)
        ]]
        self.assertFalse(county_db.county_spatial.polygon_intersects_rect(polygon, (4.0, 4.0, 6.0, 6.0)))
        self.assertTrue(county_db.county_spatial.polygon_intersects_rect(polygon, (2.0, 4.0, 4.0, 6.0)))


if __name__ == "__main__":
    unittest.main()
