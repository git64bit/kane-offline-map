from __future__ import annotations

import copy
import hashlib
import json
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
import county_building_refresh
import county_db
import county_harvest

LEDGER = Path(__file__).resolve().parents[1] / "input" / "sectors.zip"
LAYER_URL = "https://example.test/arcgis/rest/services/Buildings/FeatureServer/0"


def profile_document() -> dict[str, Any]:
    return {
        "profile_schema": 1,
        "profile_key": "fixture-building-harvest",
        "agency_key": "fixture-gis",
        "dataset_key": "buildings",
        "layer_url": LAYER_URL,
        "where": "1=1",
        "object_id_field": "OBJECTID",
        "id_property": "FPId",
        "expected_geometry_type": "esriGeometryPolygon",
        "out_srs": 4326,
        "page_size": 2,
        "out_fields": ["OBJECTID", "FPId", "Name"],
        "copyright_text": "Fixture GIS",
    }


def layer_metadata(edit_millis: int = 1785240000000) -> dict[str, Any]:
    return {
        "type": "Feature Layer",
        "name": "Fixture Buildings",
        "geometryType": "esriGeometryPolygon",
        "supportedQueryFormats": "JSON, geoJSON",
        "objectIdField": "OBJECTID",
        "maxRecordCount": 2,
        "copyrightText": "Fixture GIS",
        "fields": [
            {"name": "OBJECTID", "type": "esriFieldTypeOID"},
            {"name": "FPId", "type": "esriFieldTypeInteger"},
            {"name": "Name", "type": "esriFieldTypeString"},
        ],
        "editingInfo": {
            "lastEditDate": edit_millis + 86400000,
            "dataLastEditDate": edit_millis,
            "schemaLastEditDate": edit_millis - 86400000,
        },
    }


def polygon(index: int, offset: float = 0.0) -> dict[str, Any]:
    x = -88.5 + index * 0.01 + offset
    y = 41.8 + index * 0.01
    return {
        "type": "Polygon",
        "coordinates": [[
            [x, y], [x + 0.002, y], [x + 0.002, y + 0.002],
            [x, y + 0.002], [x, y],
        ]],
    }


def feature(object_id: int, name: str | None = None, offset: float = 0.0) -> dict[str, Any]:
    return {
        "type": "Feature",
        "properties": {
            "OBJECTID": object_id,
            "FPId": object_id * 10,
            "Name": name or f"Building {object_id}",
        },
        "geometry": polygon(object_id, offset),
    }


class FakeRequester:
    def __init__(self, version: int = 1) -> None:
        self.metadata = layer_metadata(1785240000000 + (version - 1) * 86400000)
        if version == 1:
            self.object_ids = [3, 1, 2]
            self.features = {value: feature(value) for value in self.object_ids}
        else:
            self.object_ids = [4, 2, 1]
            self.features = {
                1: feature(1),
                2: feature(2, name="Building 2 Renamed", offset=0.0002),
                4: feature(4),
            }

    def __call__(self, url: str, params: dict[str, str], timeout: float) -> dict[str, Any]:
        if url == LAYER_URL:
            return copy.deepcopy(self.metadata)
        if params.get("returnIdsOnly") == "true":
            return {"objectIdFieldName": "OBJECTID", "objectIds": list(self.object_ids)}
        ids = [int(value) for value in params["objectIds"].split(",")]
        return {
            "type": "FeatureCollection",
            "features": [copy.deepcopy(self.features[value]) for value in reversed(ids)],
        }


class HarvestAcceptanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.profile = self.root / "profile.json"
        self.profile.write_bytes(county_arcgis.canonical_bytes(profile_document()))
        self.first = self.root / "first.geojson"
        county_arcgis.harvest(
            self.profile,
            self.first,
            requester=FakeRequester(1),
            harvested_at="2026-07-31T15:00:00.000Z",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def validate(self, path: Path | None = None) -> dict[str, Any]:
        return county_harvest.validate_harvest(self.profile, path or self.first)

    def rewrite_output(self, document: dict[str, Any]) -> None:
        output_data = county_arcgis.canonical_bytes(document)
        self.first.write_bytes(output_data)
        manifest_path = county_arcgis.manifest_path(self.first)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["output"]["byte_length"] = len(output_data)
        manifest["output"]["sha256"] = hashlib.sha256(output_data).hexdigest()
        manifest["output"]["feature_count"] = len(document["features"])
        manifest_path.write_bytes(county_arcgis.canonical_bytes(manifest))

    def build_database(self, harvest_path: Path | None = None) -> Path:
        path = harvest_path or self.first
        accepted = county_harvest.validate_harvest(self.profile, path)
        database = self.root / "accepted.gpkg"
        county_db.build_building_database(
            database,
            LEDGER,
            path,
            False,
            None,
            accepted["release_key"],
            accepted["source_uri"],
            accepted["published_at"],
            accepted["id_property"],
            accepted["harvested_at"],
            accepted["source_version"],
            Path(accepted["manifest"]),
        )
        return database

    def test_valid_pair_derives_deterministic_acceptance_metadata(self) -> None:
        info = self.validate()
        self.assertTrue(info["valid"])
        self.assertEqual(3, info["feature_count"])
        self.assertEqual("FPId", info["id_property"])
        self.assertTrue(info["release_key"].startswith("kane-buildings-20260728-"))
        self.assertEqual(LAYER_URL, info["source_uri"])
        self.assertEqual(
            f"arcgis-profile-sha256:{info['profile_sha256']}", info["source_version"]
        )

    def test_noncanonical_output_is_rejected(self) -> None:
        self.first.write_bytes(self.first.read_bytes() + b" ")
        with self.assertRaisesRegex(RuntimeError, "canonical"):
            self.validate()

    def test_profile_hash_tampering_is_rejected(self) -> None:
        path = county_arcgis.manifest_path(self.first)
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["profile"]["sha256"] = "0" * 64
        path.write_bytes(county_arcgis.canonical_bytes(manifest))
        with self.assertRaisesRegex(RuntimeError, "profile hash"):
            self.validate()

    def test_feature_id_must_equal_stable_source_id(self) -> None:
        document = json.loads(self.first.read_text(encoding="utf-8"))
        document["features"][0]["id"] = "not-the-stable-id"
        self.rewrite_output(document)
        with self.assertRaisesRegex(RuntimeError, "does not use FPId"):
            self.validate()

    def test_feature_order_must_follow_complete_object_id_inventory(self) -> None:
        document = json.loads(self.first.read_text(encoding="utf-8"))
        document["features"][0], document["features"][1] = (
            document["features"][1], document["features"][0]
        )
        self.rewrite_output(document)
        with self.assertRaisesRegex(RuntimeError, "ordered by object ID"):
            self.validate()

    def test_database_preserves_harvest_and_manifest_provenance(self) -> None:
        database = self.build_database()
        accepted = self.validate()
        connection = sqlite3.connect(database)
        try:
            release = connection.execute(
                """
                SELECT release_key, source_version, source_published_at, harvested_at, source_uri
                FROM source_release WHERE status = 'accepted' AND release_key = ?
                """,
                (accepted["release_key"],),
            ).fetchone()
            files = connection.execute(
                "SELECT media_type, sha256 FROM source_file ORDER BY source_file_id"
            ).fetchall()
        finally:
            connection.close()
        self.assertEqual(
            (
                accepted["release_key"], accepted["source_version"],
                accepted["published_at"], accepted["harvested_at"], accepted["source_uri"],
            ),
            release,
        )
        self.assertEqual(
            [
                ("application/geo+json", accepted["geojson_sha256"]),
                ("application/json", accepted["manifest_sha256"]),
            ],
            files,
        )
        self.assertEqual([], county_db.validate_building_database(database))

    def test_second_validated_harvest_refreshes_release_history(self) -> None:
        database = self.build_database()
        second = self.root / "second.geojson"
        county_arcgis.harvest(
            self.profile,
            second,
            requester=FakeRequester(2),
            harvested_at="2026-08-01T15:00:00.000Z",
        )
        accepted = county_harvest.validate_harvest(self.profile, second)
        county_building_refresh.refresh_building_database(
            database,
            second,
            accepted["release_key"],
            accepted["source_uri"],
            accepted["published_at"],
            accepted["id_property"],
            accepted["harvested_at"],
            accepted["source_version"],
            Path(accepted["manifest"]),
        )
        info = county_db.database_info(database)["accepted_buildings"]
        self.assertEqual(2, info["release_history_count"])
        self.assertEqual(1, info["comparison"]["added"])
        self.assertEqual(1, info["comparison"]["removed"])
        self.assertEqual(1, info["comparison"]["unchanged"])
        self.assertEqual(1, info["comparison"]["modified"])
        connection = sqlite3.connect(database)
        try:
            self.assertEqual(4, connection.execute("SELECT COUNT(*) FROM source_file").fetchone()[0])
        finally:
            connection.close()

    def test_invalid_pair_is_rejected_before_accepted_database_changes(self) -> None:
        database = self.build_database()
        before = hashlib.sha256(database.read_bytes()).hexdigest()
        manifest_path = county_arcgis.manifest_path(self.first)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["output"]["sha256"] = "f" * 64
        manifest_path.write_bytes(county_arcgis.canonical_bytes(manifest))
        with self.assertRaisesRegex(RuntimeError, "output hash"):
            self.validate()
        self.assertEqual(before, hashlib.sha256(database.read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()
