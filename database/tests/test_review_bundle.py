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
import county_review_bundle

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


class ReviewBundleTests(unittest.TestCase):
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
        self.output = self.root / f"{self._testMethodName}-bundle"
        shutil.copy2(self.template, self.database)

    def test_bundle_is_valid_and_sectorized(self) -> None:
        info = county_review_bundle.export_open_review_bundle(
            self.database,
            self.output,
            generated_at="2026-07-31T18:00:00.000Z",
        )
        self.assertTrue(info["valid"])
        self.assertEqual([], county_review_bundle.validate_bundle(self.output))
        index = json.loads((self.output / "index.json").read_text())
        self.assertEqual(16, info["sector_file_count"])
        self.assertEqual(16, len(index["sectors"]))
        self.assertEqual(info["review_cell_count"], sum(
            item["review_cell_count"] for item in index["sectors"]
        ))
        self.assertEqual(
            {item["sector_id"]: item["review_cell_count"] for item in index["sectors"]},
            index["summary"]["sector_cell_counts"],
        )
        self.assertGreater(info["open_review_count"], 0)

    def test_cli_dispatch_exports_bundle(self) -> None:
        command = [
            sys.executable,
            str(TOOLS / "county_cli.py"),
            "export-open-review-bundle",
            str(self.database),
            "--output",
            str(self.output),
        ]
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        info = json.loads(completed.stdout)
        self.assertTrue(info["valid"])
        self.assertEqual(str(self.output), info["output"])
        self.assertEqual([], county_review_bundle.validate_bundle(self.output))

    def test_bundle_preserves_database_bytes(self) -> None:
        before = self.database.read_bytes()
        county_review_bundle.export_open_review_bundle(self.database, self.output)
        self.assertEqual(before, self.database.read_bytes())

    def test_bundle_refuses_overwrite(self) -> None:
        self.output.mkdir()
        marker = self.output / "preserve.txt"
        marker.write_text("preserve", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "already exists"):
            county_review_bundle.export_open_review_bundle(self.database, self.output)
        self.assertEqual("preserve", marker.read_text(encoding="utf-8"))

    def test_force_replaces_existing_bundle(self) -> None:
        self.output.mkdir()
        (self.output / "replace.txt").write_text("replace", encoding="utf-8")
        county_review_bundle.export_open_review_bundle(
            self.database, self.output, force=True
        )
        self.assertFalse((self.output / "replace.txt").exists())
        self.assertEqual([], county_review_bundle.validate_bundle(self.output))

    def test_tampered_sector_hash_is_detected(self) -> None:
        county_review_bundle.export_open_review_bundle(self.database, self.output)
        sector = self.output / "sectors" / "N11-E06.geojson"
        sector.write_bytes(sector.read_bytes() + b" ")
        errors = county_review_bundle.validate_bundle(self.output)
        self.assertTrue(any("hash" in error or "canonical" in error for error in errors))

    def test_missing_sector_file_is_detected(self) -> None:
        county_review_bundle.export_open_review_bundle(self.database, self.output)
        (self.output / "sectors" / "N14-E09.geojson").unlink()
        errors = county_review_bundle.validate_bundle(self.output)
        self.assertTrue(any("Cannot read Sector N14-E09" in error for error in errors))

    def test_noncanonical_index_is_detected(self) -> None:
        county_review_bundle.export_open_review_bundle(self.database, self.output)
        index_path = self.output / "index.json"
        document = json.loads(index_path.read_text())
        index_path.write_text(json.dumps(document, indent=2), encoding="utf-8")
        errors = county_review_bundle.validate_bundle(self.output)
        self.assertTrue(any("index is not canonical" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
