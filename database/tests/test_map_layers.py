from __future__ import annotations

import copy
import json
import shutil
import sqlite3
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

DATABASE = Path(__file__).resolve().parents[1]
LEDGER = DATABASE / "input" / "sectors.zip"
BUILDINGS = DATABASE / "fixtures" / "buildings-sample.geojson"
ROAD_PROFILE = DATABASE / "sources" / "kane-county-roads.json"
RIVER_PROFILE = DATABASE / "sources" / "kane-county-fox-river.json"
CREEK_PROFILE = DATABASE / "sources" / "kane-county-creeks.json"


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
        "properties": {"OBJECTID": object_id},
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


class LayerRequester:
    def __init__(self, profile_path: Path) -> None:
        self.profile, _ = county_arcgis.load_profile(profile_path)
        factory = polygon_feature if self.profile["expected_geometry_type"] == "esriGeometryPolygon" else line_feature
        self.features = {value: factory(value) for value in (1, 2, 3)}

    def __call__(self, url: str, params: dict[str, str], timeout: float) -> dict[str, Any]:
        if url == self.profile["layer_url"]:
            return copy.deepcopy(layer_metadata(self.profile))
        if params.get("returnIdsOnly") == "true":
            return {"objectIdFieldName": "OBJECTID", "objectIds": [3, 1, 2]}
        ids = [int(value) for value in params["objectIds"].split(",")]
        return {"type": "FeatureCollection", "features": [copy.deepcopy(self.features[i]) for i in reversed(ids)]}


def boundary_profile(url: str) -> dict[str, Any]:
    return {
        "profile_schema": 1,
        "profile_key": "kane-county-boundary",
        "agency_key": "kane-county-gis",
        "dataset_key": "county-boundary",
        "layer_url": url,
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


class BoundaryRequester:
    def __init__(self, profile: dict[str, Any]) -> None:
        self.profile = profile

    def __call__(self, url: str, params: dict[str, str], timeout: float) -> dict[str, Any]:
        if url == self.profile["layer_url"]:
            metadata = layer_metadata(self.profile)
            metadata["name"] = "Fixture boundary"
            return metadata
        if params.get("returnIdsOnly") == "true":
            return {"objectIdFieldName": "OBJECTID", "objectIds": [1]}
        feature = polygon_feature(1)
        feature["geometry"]["coordinates"] = [[
            [-88.61, 41.71], [-88.22, 41.71], [-88.22, 42.16],
            [-88.61, 42.16], [-88.61, 41.71],
        ]]
        return {"type": "FeatureCollection", "features": [feature]}


class MapLayerAcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temporary.name)
        base = cls.root / "base.gpkg"
        county_db.build_building_database(
            base, LEDGER, BUILDINGS, False, None, "fixture-buildings-v1",
            "https://example.test/buildings", "2026-07-30T00:00:00.000Z", None,
        )
        boundary_url = "https://example.test/County_Boundary/FeatureServer/0"
        cls.boundary_profile = cls.root / "boundary-profile.json"
        boundary_record = boundary_profile(boundary_url)
        cls.boundary_profile.write_bytes(county_arcgis.canonical_bytes(boundary_record))
        cls.boundary = cls.root / "boundary.geojson"
        county_arcgis.harvest(
            cls.boundary_profile, cls.boundary, requester=BoundaryRequester(boundary_record),
            harvested_at="2026-08-03T12:00:00.000Z",
        )
        cls.authoritative = cls.root / "authoritative.gpkg"
        shutil.copy2(base, cls.authoritative)
        county_boundary.accept_harvested_boundary(
            cls.authoritative, cls.boundary_profile, cls.boundary
        )
        cls.sources: list[tuple[Path, Path, None]] = []
        for profile_path, name in (
            (ROAD_PROFILE, "roads.geojson"),
            (RIVER_PROFILE, "fox-river.geojson"),
            (CREEK_PROFILE, "creeks.geojson"),
        ):
            output = cls.root / name
            county_arcgis.harvest(
                profile_path, output, requester=LayerRequester(profile_path),
                harvested_at="2026-08-03T13:00:00.000Z",
            )
            cls.sources.append((profile_path, output, None))
        cls.deployment = cls.root / "deployment.gpkg"
        shutil.copy2(cls.authoritative, cls.deployment)
        county_map_layers.accept_harvested_map_layers(cls.deployment, cls.sources)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    def copy_database(self, source: Path) -> Path:
        target = self.root / f"{self._testMethodName}.gpkg"
        shutil.copy2(source, target)
        return target

    def test_atomic_acceptance_promotes_all_three_releases(self) -> None:
        database = self.copy_database(self.authoritative)
        command = [
            sys.executable, str(TOOLS / "county_db.py"), "accept-harvested-map-layers",
            str(database),
            "--road-profile", str(self.sources[0][0]), "--roads", str(self.sources[0][1]),
            "--river-profile", str(self.sources[1][0]), "--fox-river", str(self.sources[1][1]),
            "--creek-profile", str(self.sources[2][0]), "--creeks", str(self.sources[2][1]),
        ]
        result = subprocess.run(command, text=True, capture_output=True, check=False)
        self.assertEqual(0, result.returncode, result.stderr)
        info = json.loads(result.stdout)
        self.assertEqual(set(county_map_layers.DATASETS), set(info["accepted_map_layers"]))
        self.assertEqual([], county_db.validate_deployment_database(database))

    def test_feature_table_registration_and_geometry_types(self) -> None:
        database = self.copy_database(self.deployment)
        connection = sqlite3.connect(database)
        try:
            registration = connection.execute(
                "SELECT data_type, srs_id FROM gpkg_contents WHERE table_name = 'source_map_feature'"
            ).fetchone()
            types = dict(connection.execute(
                """SELECT d.dataset_key, group_concat(DISTINCT f.geometry_type)
                   FROM source_map_feature f JOIN source_release r ON r.release_id = f.release_id
                   JOIN dataset d ON d.dataset_id = r.dataset_id GROUP BY d.dataset_key"""
            ))
        finally:
            connection.close()
        self.assertEqual(("features", 4326), registration)
        self.assertIn("LineString", types["roads"])
        self.assertEqual("Polygon", types["water-fox-river"])

    def test_release_provenance_and_counts_are_reported(self) -> None:
        info = county_db.database_info(self.deployment)["accepted_map_layers"]
        for dataset_key in county_map_layers.DATASETS:
            self.assertEqual(3, info[dataset_key]["feature_count"])
            self.assertEqual(64, len(info[dataset_key]["content_sha256"]))
            self.assertEqual(4326, info[dataset_key]["srs_id"])

    def test_invalid_third_manifest_preserves_database(self) -> None:
        database = self.copy_database(self.authoritative)
        bad_manifest = self.root / f"{self._testMethodName}.manifest.json"
        creek_manifest = county_arcgis.manifest_path(self.sources[2][1])
        document = json.loads(creek_manifest.read_text(encoding="utf-8"))
        document["output"]["sha256"] = "0" * 64
        bad_manifest.write_bytes(county_arcgis.canonical_bytes(document))
        sources = [*self.sources[:2], (self.sources[2][0], self.sources[2][1], bad_manifest)]
        before = database.read_bytes()
        with self.assertRaisesRegex(RuntimeError, "output hash"):
            county_map_layers.accept_harvested_map_layers(database, sources)
        self.assertEqual(before, database.read_bytes())

    def test_second_acceptance_is_refused_and_preserves_database(self) -> None:
        database = self.copy_database(self.deployment)
        before = database.read_bytes()
        with self.assertRaisesRegex(RuntimeError, "Refresh is not implemented"):
            county_map_layers.accept_harvested_map_layers(database, self.sources)
        self.assertEqual(before, database.read_bytes())

    def test_geometry_hash_tampering_is_detected(self) -> None:
        database = self.copy_database(self.deployment)
        connection = sqlite3.connect(database)
        try:
            connection.execute(
                "UPDATE source_map_feature SET geometry_sha256 = ? WHERE source_map_feature_id = 1",
                ("0" * 64,),
            )
            connection.commit()
        finally:
            connection.close()
        errors = county_db.validate_deployment_database(database)
        self.assertTrue(any("geometry hash is invalid" in item for item in errors))

    def test_public_validation_command_passes(self) -> None:
        result = subprocess.run(
            [sys.executable, str(TOOLS / "county_db.py"), "validate-deployment", str(self.deployment)],
            text=True, capture_output=True, check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("VALID deployment source database", result.stdout)

    def test_schema_version_and_migration_count_include_map_layers(self) -> None:
        connection = sqlite3.connect(self.deployment)
        try:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            migrations = connection.execute("SELECT COUNT(*) FROM schema_migration").fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(10800, version)
        self.assertEqual(9, migrations)


if __name__ == "__main__":
    unittest.main()
