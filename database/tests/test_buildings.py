from __future__ import annotations

import importlib.util
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools"
MODULE_PATH = TOOLS / "county_db.py"
INPUT_ARCHIVE = Path(__file__).resolve().parents[1] / "input" / "sectors.zip"
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "buildings-sample.geojson"
SPEC = importlib.util.spec_from_file_location("county_db_buildings_test", MODULE_PATH)
county_db = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(county_db)


class BuildingReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tempdir = tempfile.TemporaryDirectory()
        cls.database = Path(cls.tempdir.name) / "buildings.gpkg"
        county_db.build_building_database(
            cls.database,
            INPUT_ARCHIVE,
            FIXTURE,
            force=False,
            ledger_release_key=None,
            building_release_key="fixture-buildings-v1",
            source_uri="fixture://buildings-sample.geojson",
            published_at="2026-07-29T00:00:00Z",
            id_property=None,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tempdir.cleanup()

    def test_completed_building_release_validates(self) -> None:
        self.assertEqual([], county_db.validate_building_database(self.database))
        info = county_db.database_info(self.database)
        buildings = info["accepted_buildings"]
        self.assertEqual("fixture-buildings-v1", buildings["release_key"])
        self.assertEqual(3, buildings["feature_count"])
        self.assertEqual(4326, buildings["srs_id"])

    def test_geopackage_geometry_headers_and_types(self) -> None:
        connection = sqlite3.connect(self.database)
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
        connection = sqlite3.connect(self.database)
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

    def test_second_accepted_building_release_is_refused(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "accepted building release already exists"):
            county_db.county_buildings.import_buildings(
                self.database,
                FIXTURE,
                release_key="fixture-buildings-v2",
                source_uri=None,
                published_at=None,
                id_property=None,
            )


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
            county_db.county_buildings.import_buildings(
                self.database, path, None, None, None, None
            )

    def test_non_polygon_geometry_is_rejected(self) -> None:
        path = self.write_geojson([self.feature("point", geometry_type="Point")])
        with self.assertRaisesRegex(RuntimeError, "Unsupported building geometry type"):
            county_db.county_buildings.import_buildings(
                self.database, path, None, None, None, None
            )


if __name__ == "__main__":
    unittest.main()
