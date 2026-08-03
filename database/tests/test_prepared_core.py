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
import county_map_layers
import county_prepared

DATABASE_DIR = Path(__file__).resolve().parents[1]
LEDGER = DATABASE_DIR / "input" / "sectors.zip"
BUILDINGS = DATABASE_DIR / "fixtures" / "buildings-sample.geojson"
ROAD_PROFILE = DATABASE_DIR / "sources" / "kane-county-roads.json"
RIVER_PROFILE = DATABASE_DIR / "sources" / "kane-county-fox-river.json"
CREEK_PROFILE = DATABASE_DIR / "sources" / "kane-county-creeks.json"
CLI = TOOLS / "county_cli.py"
BOUNDARY_URL = "https://example.test/arcgis/rest/services/County_Boundary/FeatureServer/0"


def boundary_profile() -> dict[str, Any]:
    return {
        "profile_schema": 1,
        "profile_key": "kane-county-boundary",
        "agency_key": "kane-county-gis",
        "dataset_key": "county-boundary",
        "layer_url": BOUNDARY_URL,
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


def layer_metadata(profile: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "Feature Layer",
        "name": f"Fixture {profile['dataset_key']}",
        "geometryType": profile["expected_geometry_type"],
        "supportedQueryFormats": "JSON, geoJSON",
        "objectIdField": "OBJECTID",
        "maxRecordCount": 2000,
        "copyrightText": profile["copyright_text"],
        "fields": [{"name": "OBJECTID", "type": "esriFieldTypeOID"}],
        "editingInfo": {
            "lastEditDate": 1785758400000,
            "dataLastEditDate": 1785672000000,
            "schemaLastEditDate": 1785585600000,
        },
    }


def line_feature(object_id: int) -> dict[str, Any]:
    path = [[-88.60 + object_id / 1000, 41.80], [-88.50, 41.90]]
    return {
        "type": "Feature",
        "properties": {"OBJECTID": object_id, "route_type": "state"},
        "geometry": {
            "type": "MultiLineString" if object_id == 2 else "LineString",
            "coordinates": [path, list(reversed(path))] if object_id == 2 else path,
        },
    }


def polygon_feature(object_id: int) -> dict[str, Any]:
    west = -88.60 + object_id / 1000
    return {
        "type": "Feature",
        "properties": {"OBJECTID": object_id},
        "geometry": {
            "type": "Polygon",
            "coordinates": [[
                [west, 41.80], [west + 0.02, 41.80], [west + 0.02, 41.84],
                [west, 41.84], [west, 41.80],
            ]],
        },
    }


class BoundaryRequester:
    def __init__(self, profile: dict[str, Any]) -> None:
        self.profile = profile

    def __call__(self, url: str, params: dict[str, str], timeout: float) -> dict[str, Any]:
        if url == BOUNDARY_URL:
            metadata = layer_metadata(self.profile)
            metadata["name"] = "Fixture County Boundary"
            return metadata
        if params.get("returnIdsOnly") == "true":
            return {"objectIdFieldName": "OBJECTID", "objectIds": [7]}
        feature = polygon_feature(7)
        feature["geometry"]["coordinates"] = [[
            [-88.61, 41.71], [-88.22, 41.71], [-88.22, 42.16],
            [-88.61, 42.16], [-88.61, 41.71],
        ]]
        return {"type": "FeatureCollection", "features": [feature]}


class LayerRequester:
    def __init__(self, profile_path: Path) -> None:
        self.profile, _ = county_arcgis.load_profile(profile_path)
        factory = polygon_feature if self.profile["expected_geometry_type"] == "esriGeometryPolygon" else line_feature
        self.features = {value: factory(value) for value in (1, 2, 3)}
        if self.profile.get("missing_geometry_policy") == "exclude":
            self.features[2]["geometry"] = None

    def __call__(self, url: str, params: dict[str, str], timeout: float) -> dict[str, Any]:
        if url == self.profile["layer_url"]:
            return copy.deepcopy(layer_metadata(self.profile))
        if params.get("returnIdsOnly") == "true":
            return {"objectIdFieldName": "OBJECTID", "objectIds": [3, 1, 2]}
        ids = [int(value) for value in params["objectIds"].split(",")]
        return {
            "type": "FeatureCollection",
            "features": [copy.deepcopy(self.features[value]) for value in reversed(ids)],
        }


class PreparedCoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temporary.name)
        cls.profile = cls.root / "boundary-profile.json"
        profile = boundary_profile()
        cls.profile.write_bytes(county_arcgis.canonical_bytes(profile))
        cls.harvest = cls.root / "boundary.geojson"
        county_arcgis.harvest(
            cls.profile,
            cls.harvest,
            requester=BoundaryRequester(profile),
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
        cls.authoritative = cls.root / "authoritative.gpkg"
        shutil.copy2(base, cls.authoritative)
        county_boundary.accept_harvested_boundary(cls.authoritative, cls.profile, cls.harvest)
        sources: list[tuple[Path, Path, None]] = []
        for profile_path, name in (
            (ROAD_PROFILE, "roads.geojson"),
            (RIVER_PROFILE, "fox-river.geojson"),
            (CREEK_PROFILE, "creeks.geojson"),
        ):
            output = cls.root / name
            county_arcgis.harvest(
                profile_path,
                output,
                requester=LayerRequester(profile_path),
                harvested_at="2026-08-03T13:00:00.000Z",
            )
            sources.append((profile_path, output, None))
        cls.template = cls.root / "deployment-template.gpkg"
        shutil.copy2(cls.authoritative, cls.template)
        county_map_layers.accept_harvested_map_layers(cls.template, sources)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    def setUp(self) -> None:
        self.database = self.root / f"{self._testMethodName}.gpkg"
        self.output = self.root / f"{self._testMethodName}-prepared"
        shutil.copy2(self.template, self.database)

    def test_export_is_valid_and_complete(self) -> None:
        info = county_prepared.export_prepared_core(self.database, self.output)
        self.assertTrue(info["valid"])
        self.assertTrue(info["complete_browser_bundle"])
        self.assertEqual([], info["remaining_datasets"])
        self.assertEqual([], county_prepared.validate_core_export(self.output))
        self.assertEqual(
            {
                "buildings.json",
                "county_boundary.json",
                "roads.json",
                "water.json",
                "core-manifest.json",
            },
            {item.name for item in self.output.iterdir()},
        )

    def test_export_preserves_release_identity_and_feature_counts(self) -> None:
        info = county_prepared.export_prepared_core(self.database, self.output)
        boundary = json.loads((self.output / "county_boundary.json").read_text())
        buildings = json.loads((self.output / "buildings.json").read_text())
        self.assertEqual(1, len(boundary["features"]))
        self.assertEqual(3, len(buildings["features"]))
        self.assertEqual("7", boundary["features"][0]["id"])
        self.assertEqual(2, info["datasets"]["roads"]["feature_count"])
        self.assertEqual(6, info["datasets"]["water"]["feature_count"])
        self.assertEqual(
            "fixture-buildings-v1",
            info["datasets"]["buildings"]["releases"][0]["release_key"],
        )

    def test_export_decodes_linear_water_and_preserves_road_attributes(self) -> None:
        county_prepared.export_prepared_core(self.database, self.output)
        roads = json.loads((self.output / "roads.json").read_text())
        water = json.loads((self.output / "water.json").read_text())
        self.assertEqual({"LineString"}, {feature["geometry"]["type"] for feature in roads["features"]})
        self.assertEqual("state", roads["features"][0]["properties"]["route_type"])
        self.assertEqual(
            {"Polygon", "LineString", "MultiLineString"},
            {feature["geometry"]["type"] for feature in water["features"]},
        )
        self.assertEqual(
            {"water-fox-river", "water-creeks"},
            {feature["properties"]["dataset_key"] for feature in water["features"]},
        )

    def test_export_preserves_database_bytes(self) -> None:
        before = self.database.read_bytes()
        county_prepared.export_prepared_core(self.database, self.output)
        self.assertEqual(before, self.database.read_bytes())

    def test_export_refuses_database_without_map_layers(self) -> None:
        incomplete = self.root / f"{self._testMethodName}-incomplete.gpkg"
        shutil.copy2(self.authoritative, incomplete)
        with self.assertRaisesRegex(RuntimeError, "Deployment source database is invalid"):
            county_prepared.export_prepared_core(incomplete, self.output)
        self.assertFalse(self.output.exists())

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

    def test_tampered_water_file_is_detected(self) -> None:
        county_prepared.export_prepared_core(self.database, self.output)
        with (self.output / "water.json").open("ab") as stream:
            stream.write(b" ")
        errors = county_prepared.validate_core_export(self.output)
        self.assertTrue(any("hash mismatch: water.json" in error for error in errors))

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
        self.assertTrue(result["complete_browser_bundle"])
        self.assertEqual([], county_prepared.validate_core_export(self.output))


if __name__ == "__main__":
    unittest.main()
