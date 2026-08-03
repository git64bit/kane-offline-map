from __future__ import annotations

import copy
import json
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

TOOLS = Path(__file__).resolve().parents[1] / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import county_arcgis
import county_boundary
import county_db

DATABASE_DIR = Path(__file__).resolve().parents[1]
LEDGER = DATABASE_DIR / "input" / "sectors.zip"
BUILDINGS = DATABASE_DIR / "fixtures" / "buildings-sample.geojson"
LAYER_URL = "https://example.test/arcgis/rest/services/County_Boundary/FeatureServer/0"


def profile_document() -> dict[str, Any]:
    return {
        "profile_schema": 1,
        "profile_key": "kane-county-boundary",
        "agency_key": "kane-county-gis",
        "dataset_key": "county-boundary",
        "layer_url": LAYER_URL,
        "where": "1=1",
        "object_id_field": "OBJECTID",
        "id_property": "OBJECTID",
        "expected_geometry_type": "esriGeometryPolygon",
        "expected_feature_count": 1,
        "out_srs": 4326,
        "page_size": 2000,
        "out_fields": ["OBJECTID"],
        "copyright_text": "Fixture GIS",
    }


def layer_metadata(edit_millis: int) -> dict[str, Any]:
    return {
        "type": "Feature Layer",
        "name": "Fixture County Boundary",
        "geometryType": "esriGeometryPolygon",
        "supportedQueryFormats": "JSON, geoJSON",
        "objectIdField": "OBJECTID",
        "maxRecordCount": 2000,
        "copyrightText": "Fixture GIS",
        "fields": [{"name": "OBJECTID", "type": "esriFieldTypeOID"}],
        "editingInfo": {
            "lastEditDate": edit_millis,
            "dataLastEditDate": edit_millis,
            "schemaLastEditDate": edit_millis,
        },
    }


def boundary_feature(east: float = -88.22) -> dict[str, Any]:
    return {
        "type": "Feature",
        "properties": {"OBJECTID": 7},
        "geometry": {
            "type": "Polygon",
            "coordinates": [[
                [-88.61, 41.71], [east, 41.71], [east, 42.16],
                [-88.61, 42.16], [-88.61, 41.71],
            ]],
        },
    }


class BoundaryRequester:
    def __init__(self, edit_millis: int, east: float = -88.22) -> None:
        self.metadata = layer_metadata(edit_millis)
        self.feature = boundary_feature(east)

    def __call__(self, url: str, params: dict[str, str], timeout: float) -> dict[str, Any]:
        if url == LAYER_URL:
            return copy.deepcopy(self.metadata)
        if params.get("returnIdsOnly") == "true":
            return {"objectIdFieldName": "OBJECTID", "objectIds": [7]}
        return {"type": "FeatureCollection", "features": [copy.deepcopy(self.feature)]}


class BoundaryAcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temporary.name)
        cls.profile = cls.root / "boundary-profile.json"
        cls.profile.write_bytes(county_arcgis.canonical_bytes(profile_document()))
        cls.harvest = cls.root / "boundary-v1.geojson"
        county_arcgis.harvest(
            cls.profile,
            cls.harvest,
            requester=BoundaryRequester(1785240000000),
            harvested_at="2026-07-31T17:00:00.000Z",
        )
        base = cls.root / "base.gpkg"
        county_db.build_building_database(
            base, LEDGER, BUILDINGS, False, None, "fixture-buildings-v1",
            "https://example.test/buildings", "2026-07-30T00:00:00.000Z", None,
        )
        cls.template = cls.root / "accepted-template.gpkg"
        shutil.copy2(base, cls.template)
        county_boundary.accept_harvested_boundary(
            cls.template, cls.profile, cls.harvest
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    def setUp(self) -> None:
        self.database = self.root / f"{self._testMethodName}.gpkg"
        shutil.copy2(self.template, self.database)

    def test_acceptance_preserves_release_and_source_provenance(self) -> None:
        info = county_db.database_info(self.database)
        accepted = info["accepted_boundary"]
        self.assertEqual("7", accepted["source_feature_id"])
        self.assertEqual("Polygon", accepted["geometry_type"])
        self.assertEqual(2, len(accepted["source_files"]))
        self.assertTrue(accepted["release_key"].startswith("kane-county-boundary-"))

    def test_boundary_feature_table_and_calibration_are_linked(self) -> None:
        connection = sqlite3.connect(self.database)
        try:
            registration = connection.execute(
                "SELECT data_type, srs_id FROM gpkg_contents "
                "WHERE table_name = 'source_county_boundary'"
            ).fetchone()
            link = connection.execute(
                """SELECT b.release_id, g.boundary_release_id, r.content_sha256,
                          g.boundary_sha256
                   FROM source_county_boundary b
                   JOIN source_release r ON r.release_id = b.release_id
                   JOIN classification_grid_calibration g
                     ON g.boundary_release_id = b.release_id"""
            ).fetchone()
        finally:
            connection.close()
        self.assertEqual(("features", 4326), registration)
        self.assertEqual(link[0], link[1])
        self.assertEqual(link[2], link[3])

    def test_authoritative_database_validation_passes(self) -> None:
        self.assertEqual([], county_db.validate_authoritative_database(self.database))

    def test_invalid_manifest_preserves_accepted_database(self) -> None:
        before = self.database.read_bytes()
        bad_manifest = self.root / f"{self._testMethodName}.manifest.json"
        manifest = json.loads(county_arcgis.manifest_path(self.harvest).read_text())
        manifest["output"]["sha256"] = "0" * 64
        bad_manifest.write_bytes(county_arcgis.canonical_bytes(manifest))
        with self.assertRaisesRegex(RuntimeError, "output hash"):
            county_boundary.accept_harvested_boundary(
                self.database, self.profile, self.harvest, bad_manifest
            )
        self.assertEqual(before, self.database.read_bytes())

    def test_second_boundary_release_is_refused_and_preserves_database(self) -> None:
        second = self.root / f"{self._testMethodName}.geojson"
        county_arcgis.harvest(
            self.profile,
            second,
            requester=BoundaryRequester(1785326400000, -88.21),
            harvested_at="2026-08-01T17:00:00.000Z",
        )
        before = self.database.read_bytes()
        with self.assertRaisesRegex(RuntimeError, "Boundary refresh is not implemented"):
            county_boundary.accept_harvested_boundary(
                self.database, self.profile, second
            )
        self.assertEqual(before, self.database.read_bytes())

    def test_calibration_release_tampering_is_detected(self) -> None:
        connection = sqlite3.connect(self.database)
        try:
            connection.execute(
                "UPDATE classification_grid_calibration SET boundary_release_id = NULL"
            )
            connection.commit()
        finally:
            connection.close()
        errors = county_db.validate_authoritative_database(self.database)
        self.assertTrue(any("exact grid-calibration source" in error for error in errors))

    def test_schema_version_and_canonical_srs_are_authoritative(self) -> None:
        connection = sqlite3.connect(self.database)
        try:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            srs = connection.execute(
                "SELECT canonical_srs_id FROM county WHERE fips_code = '17089'"
            ).fetchone()[0]
            migrations = connection.execute("SELECT COUNT(*) FROM schema_migration").fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(10800, version)
        self.assertEqual(4326, srs)
        self.assertEqual(9, migrations)


if __name__ == "__main__":
    unittest.main()
