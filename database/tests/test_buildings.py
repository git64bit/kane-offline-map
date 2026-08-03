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
FIXTURE_V1 = Path(__file__).resolve().parents[1] / "fixtures" / "buildings-sample.geojson"
FIXTURE_V2 = Path(__file__).resolve().parents[1] / "fixtures" / "buildings-refresh-v2.geojson"
SPEC = importlib.util.spec_from_file_location("county_db_buildings_test", MODULE_PATH)
county_db = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(county_db)

TEMP_DIR: tempfile.TemporaryDirectory[str]
BASELINE: Path
REFRESHED: Path


def build_initial(path: Path) -> None:
    county_db.build_building_database(
        path,
        INPUT_ARCHIVE,
        FIXTURE_V1,
        force=False,
        ledger_release_key=None,
        building_release_key="fixture-buildings-v1",
        source_uri="fixture://buildings-sample.geojson",
        published_at="2026-07-29T00:00:00Z",
        id_property=None,
    )


def refresh(path: Path, source: Path = FIXTURE_V2, key: str = "fixture-buildings-v2") -> None:
    county_db.county_building_refresh.refresh_building_database(
        path,
        source,
        release_key=key,
        source_uri=f"fixture://{source.name}",
        published_at="2026-07-30T00:00:00Z",
        id_property=None,
    )


def setUpModule() -> None:
    global TEMP_DIR, BASELINE, REFRESHED
    TEMP_DIR = tempfile.TemporaryDirectory()
    BASELINE = Path(TEMP_DIR.name) / "baseline.gpkg"
    REFRESHED = Path(TEMP_DIR.name) / "refreshed.gpkg"
    build_initial(BASELINE)
    shutil.copy2(BASELINE, REFRESHED)
    refresh(REFRESHED)


def tearDownModule() -> None:
    TEMP_DIR.cleanup()


class BuildingReleaseTests(unittest.TestCase):
    def test_completed_building_release_validates(self) -> None:
        self.assertEqual([], county_db.validate_building_database(BASELINE))
        buildings = county_db.database_info(BASELINE)["accepted_buildings"]
        self.assertEqual("fixture-buildings-v1", buildings["release_key"])
        self.assertEqual(3, buildings["feature_count"])
        self.assertEqual(4326, buildings["srs_id"])
        self.assertEqual(1, buildings["release_history_count"])

    def test_geopackage_geometry_headers_and_types(self) -> None:
        connection = sqlite3.connect(BASELINE)
        try:
            rows = connection.execute(
                "SELECT geometry_type, geometry FROM source_building ORDER BY source_ordinal"
            ).fetchall()
        finally:
            connection.close()
        self.assertEqual(["Polygon", "Polygon", "MultiPolygon"], [row[0] for row in rows])
        self.assertTrue(all(row[1][:4] == b"GP\x00\x03" for row in rows))
        self.assertEqual([3, 3, 6], [int.from_bytes(row[1][41:45], "little") for row in rows])

    def test_source_table_is_registered_as_geopackage_features(self) -> None:
        connection = sqlite3.connect(BASELINE)
        try:
            contents = connection.execute(
                "SELECT data_type, srs_id FROM gpkg_contents WHERE table_name = 'source_building'"
            ).fetchone()
            geometry = connection.execute(
                """
                SELECT column_name, geometry_type_name, srs_id, z, m
                FROM gpkg_geometry_columns WHERE table_name = 'source_building'
                """
            ).fetchone()
        finally:
            connection.close()
        self.assertEqual(("features", 4326), contents)
        self.assertEqual(("geometry", "GEOMETRY", 4326, 0, 0), geometry)


class BuildingRefreshTests(unittest.TestCase):
    def copy_database(self, source: Path, name: str) -> Path:
        path = Path(TEMP_DIR.name) / name
        shutil.copy2(source, path)
        return path

    def test_refresh_accepts_candidate_and_supersedes_previous(self) -> None:
        connection = sqlite3.connect(REFRESHED)
        try:
            rows = connection.execute(
                "SELECT release_key, status, superseded_at FROM source_release ORDER BY release_id"
            ).fetchall()
        finally:
            connection.close()
        self.assertEqual("fixture-buildings-v1", rows[0][0])
        self.assertEqual("superseded", rows[0][1])
        self.assertIsNotNone(rows[0][2])
        self.assertEqual(("fixture-buildings-v2", "accepted", None), rows[1])
        self.assertEqual([], county_db.validate_building_database(REFRESHED))

    def test_refresh_comparison_reports_added_removed_unchanged_and_modified(self) -> None:
        info = county_db.database_info(REFRESHED)["accepted_buildings"]
        self.assertEqual(2, info["release_history_count"])
        self.assertEqual(
            {
                "previous_release_key": "fixture-buildings-v1",
                "added": 1,
                "removed": 1,
                "unchanged": 1,
                "geometry_changed": 0,
                "attributes_changed": 0,
                "modified": 1,
            },
            info["comparison"],
        )
        connection = sqlite3.connect(REFRESHED)
        try:
            rows = connection.execute(
                "SELECT source_feature_id, change_type FROM building_feature_change ORDER BY source_feature_id"
            ).fetchall()
        finally:
            connection.close()
        self.assertEqual(
            [
                ("fixture-building-001", "unchanged"),
                ("fixture-building-002", "modified"),
                ("fixture-building-003", "removed"),
                ("fixture-building-004", "added"),
            ],
            rows,
        )

    def test_previous_release_features_remain_immutable(self) -> None:
        connection = sqlite3.connect(BASELINE)
        try:
            before = connection.execute(
                "SELECT source_feature_id, content_sha256 FROM source_building ORDER BY source_feature_id"
            ).fetchall()
        finally:
            connection.close()
        connection = sqlite3.connect(REFRESHED)
        try:
            after = connection.execute(
                """
                SELECT b.source_feature_id, b.content_sha256
                FROM source_building b JOIN source_release r ON r.release_id = b.release_id
                WHERE r.release_key = 'fixture-buildings-v1' ORDER BY b.source_feature_id
                """
            ).fetchall()
        finally:
            connection.close()
        self.assertEqual(before, after)

    def test_duplicate_refresh_preserves_accepted_database(self) -> None:
        database = self.copy_database(REFRESHED, "duplicate.gpkg")
        before = database.read_bytes()
        with self.assertRaisesRegex(RuntimeError, "already imported"):
            refresh(database, key="fixture-buildings-v2-duplicate-key")
        self.assertEqual(before, database.read_bytes())

    def test_invalid_refresh_preserves_accepted_database(self) -> None:
        database = self.copy_database(BASELINE, "invalid.gpkg")
        invalid = Path(TEMP_DIR.name) / "invalid.geojson"
        invalid.write_text('{"type":"FeatureCollection","features":[]}', encoding="utf-8")
        before = database.read_bytes()
        with self.assertRaisesRegex(RuntimeError, "contains no features"):
            refresh(database, source=invalid, key="invalid-release")
        self.assertEqual(before, database.read_bytes())

    def test_refresh_upgrades_batch008_database_before_comparison(self) -> None:
        database = Path(TEMP_DIR.name) / "legacy-batch008.gpkg"
        county_db.initialize_database(database, force=False, migration_limit=5, user_version=10400)
        county_db.county_ledger.import_ledger(database, INPUT_ARCHIVE, None)
        county_db.county_buildings.import_buildings(
            database,
            FIXTURE_V1,
            "fixture-buildings-v1",
            "fixture://buildings-sample.geojson",
            "2026-07-29T00:00:00Z",
            None,
        )
        connection = sqlite3.connect(database)
        try:
            self.assertEqual(5, connection.execute("SELECT COUNT(*) FROM schema_migration").fetchone()[0])
            self.assertEqual(10400, connection.execute("PRAGMA user_version").fetchone()[0])
        finally:
            connection.close()
        refresh(database)
        connection = sqlite3.connect(database)
        try:
            self.assertEqual(9, connection.execute("SELECT COUNT(*) FROM schema_migration").fetchone()[0])
            self.assertEqual(10800, connection.execute("PRAGMA user_version").fetchone()[0])
        finally:
            connection.close()
        self.assertEqual([], county_db.validate_building_database(database))

    def test_third_release_distinguishes_geometry_and_attribute_changes(self) -> None:
        database = self.copy_database(REFRESHED, "change-kinds.gpkg")
        document = json.loads(FIXTURE_V2.read_text(encoding="utf-8"))
        document["features"][0]["properties"]["name"] = "Fixture Building One Renamed"
        document["features"][1]["geometry"]["coordinates"][0][1][0] = -88.3967
        third = Path(TEMP_DIR.name) / "buildings-refresh-v3.geojson"
        third.write_text(json.dumps(document), encoding="utf-8")
        county_db.county_buildings.import_buildings(
            database,
            third,
            "fixture-buildings-v3",
            "fixture://buildings-refresh-v3.geojson",
            "2026-07-31T00:00:00Z",
            None,
        )
        info = county_db.database_info(database)["accepted_buildings"]["comparison"]
        self.assertEqual(1, info["unchanged"])
        self.assertEqual(1, info["geometry_changed"])
        self.assertEqual(1, info["attributes_changed"])
        self.assertEqual(0, info["modified"])
        self.assertEqual([], county_db.validate_building_database(database))


class BuildingInputValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.database = Path(self.tempdir.name) / "foundation.gpkg"
        county_db.initialize_database(self.database, force=False)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def write_geojson(self, features: list[dict]) -> Path:
        path = Path(self.tempdir.name) / "input.geojson"
        path.write_text(json.dumps({"type": "FeatureCollection", "features": features}))
        return path

    def feature(self, feature_id: str, geometry_type: str = "Polygon") -> dict:
        coordinates: object = [[[0, 0], [1, 0], [1, 1], [0, 0]]]
        if geometry_type == "Point":
            coordinates = [0, 0]
        return {
            "type": "Feature",
            "id": feature_id,
            "properties": {},
            "geometry": {"type": geometry_type, "coordinates": coordinates},
        }

    def test_duplicate_source_ids_are_rejected(self) -> None:
        path = self.write_geojson([self.feature("same"), self.feature("same")])
        with self.assertRaisesRegex(RuntimeError, "Duplicate building source feature id"):
            county_db.county_buildings.import_buildings(self.database, path, None, None, None, None)

    def test_non_polygon_geometry_is_rejected(self) -> None:
        path = self.write_geojson([self.feature("point", geometry_type="Point")])
        with self.assertRaisesRegex(RuntimeError, "Unsupported building geometry type"):
            county_db.county_buildings.import_buildings(self.database, path, None, None, None, None)


if __name__ == "__main__":
    unittest.main()
