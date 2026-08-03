from __future__ import annotations

import copy
import json
import shutil
import subprocess
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
import county_prepared

DATABASE_DIR = Path(__file__).resolve().parents[1]
LEDGER = DATABASE_DIR / "input" / "sectors.zip"
BUILDINGS = DATABASE_DIR / "fixtures" / "buildings-sample.geojson"
CLI = TOOLS / "county_cli.py"
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


def layer_metadata() -> dict[str, Any]:
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
            "lastEditDate": 1785240000000,
            "dataLastEditDate": 1785240000000,
            "schemaLastEditDate": 1785240000000,
        },
    }


def boundary_feature() -> dict[str, Any]:
    return {
        "type": "Feature",
        "properties": {"OBJECTID": 7},
        "geometry": {
            "type": "Polygon",
            "coordinates": [[
                [-88.61, 41.71], [-88.22, 41.71], [-88.22, 42.16],
                [-88.61, 42.16], [-88.61, 41.71],
            ]],
        },
    }


class BoundaryRequester:
    def __call__(self, url: str, params: dict[str, str], timeout: float) -> dict[str, Any]:
        if url == LAYER_URL:
            return copy.deepcopy(layer_metadata())
        if params.get("returnIdsOnly") == "true":
            return {"objectIdFieldName": "OBJECTID", "objectIds": [7]}
        return {"type": "FeatureCollection", "features": [copy.deepcopy(boundary_feature())]}


class PreparedCoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temporary.name)
        cls.profile = cls.root / "boundary-profile.json"
        cls.profile.write_bytes(county_arcgis.canonical_bytes(profile_document()))
        cls.harvest = cls.root / "boundary.geojson"
        county_arcgis.harvest(
            cls.profile,
            cls.harvest,
            requester=BoundaryRequester(),
            harvested_at="2026-07-31T17:00:00.000Z",
        )
        base = cls.root / "base.gpkg"
        county_db.build_building_database(
            base,
            LEDGER,
            BUILDINGS,
            False,
            None,
            "fixture-buildings-v1",
            "https://example.test/buildings",
            "2026-07-30T00:00:00.000Z",
            None,
        )
        cls.template = cls.root / "authoritative-template.gpkg"
        shutil.copy2(base, cls.template)
        county_boundary.accept_harvested_boundary(
            cls.template, cls.profile, cls.harvest
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    def setUp(self) -> None:
        self.database = self.root / f"{self._testMethodName}.gpkg"
        self.output = self.root / f"{self._testMethodName}-prepared"
        shutil.copy2(self.template, self.database)

    def test_export_is_valid_and_explicitly_incomplete(self) -> None:
        info = county_prepared.export_prepared_core(self.database, self.output)
        self.assertTrue(info["valid"])
        self.assertFalse(info["complete_browser_bundle"])
        self.assertEqual(["roads", "water"], info["remaining_datasets"])
        self.assertEqual([], county_prepared.validate_core_export(self.output))
        self.assertEqual(
            {"buildings.json", "county_boundary.json", "core-manifest.json"},
            {item.name for item in self.output.iterdir()},
        )

    def test_export_preserves_release_identity_and_feature_counts(self) -> None:
        info = county_prepared.export_prepared_core(self.database, self.output)
        boundary = json.loads((self.output / "county_boundary.json").read_text())
        buildings = json.loads((self.output / "buildings.json").read_text())
        self.assertEqual(1, len(boundary["features"]))
        self.assertEqual(3, len(buildings["features"]))
        self.assertEqual("7", boundary["features"][0]["id"])
        self.assertEqual(3, info["datasets"]["buildings"]["feature_count"])
        self.assertEqual(
            "fixture-buildings-v1", info["datasets"]["buildings"]["release_key"]
        )

    def test_export_preserves_database_bytes(self) -> None:
        before = self.database.read_bytes()
        county_prepared.export_prepared_core(self.database, self.output)
        self.assertEqual(before, self.database.read_bytes())

    def test_export_refuses_existing_directory(self) -> None:
        self.output.mkdir()
        marker = self.output / "preserve.txt"
        marker.write_text("preserve", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "already exists"):
            county_prepared.export_prepared_core(self.database, self.output)
        self.assertEqual("preserve", marker.read_text(encoding="utf-8"))

    def test_force_replaces_existing_directory(self) -> None:
        self.output.mkdir()
        (self.output / "replace.txt").write_text("replace", encoding="utf-8")
        county_prepared.export_prepared_core(self.database, self.output, force=True)
        self.assertEqual([], county_prepared.validate_core_export(self.output))
        self.assertFalse((self.output / "replace.txt").exists())

    def test_tampered_building_file_is_detected(self) -> None:
        county_prepared.export_prepared_core(self.database, self.output)
        with (self.output / "buildings.json").open("ab") as stream:
            stream.write(b" ")
        errors = county_prepared.validate_core_export(self.output)
        self.assertTrue(any("hash mismatch" in error for error in errors))

    def test_public_cli_dispatches_export(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                str(CLI),
                "export-prepared-core",
                str(self.database),
                "--output",
                str(self.output),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        result = json.loads(completed.stdout)
        self.assertTrue(result["valid"])
        self.assertEqual([], county_prepared.validate_core_export(self.output))


if __name__ == "__main__":
    unittest.main()
