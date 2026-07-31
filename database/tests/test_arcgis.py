from __future__ import annotations

import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

TOOLS = Path(__file__).resolve().parents[1] / "tools"
MODULE_PATH = TOOLS / "county_arcgis.py"
OFFICIAL_PROFILE = Path(__file__).resolve().parents[1] / "sources" / "kane-county-buildings.json"
SPEC = importlib.util.spec_from_file_location("county_arcgis_test", MODULE_PATH)
county_arcgis = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(county_arcgis)

LAYER_URL = "https://example.test/arcgis/rest/services/Buildings/FeatureServer/0"


def profile_document() -> dict[str, Any]:
    return {
        "profile_schema": 1,
        "profile_key": "fixture-buildings",
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


def layer_metadata() -> dict[str, Any]:
    return {
        "type": "Feature Layer",
        "name": "Fixture Buildings",
        "geometryType": "esriGeometryPolygon",
        "supportedQueryFormats": "JSON, geoJSON, PBF",
        "objectIdField": "OBJECTID",
        "maxRecordCount": 2,
        "copyrightText": "Fixture GIS",
        "fields": [
            {"name": "OBJECTID", "type": "esriFieldTypeOID"},
            {"name": "FPId", "type": "esriFieldTypeInteger"},
            {"name": "Name", "type": "esriFieldTypeString"},
        ],
        "editingInfo": {
            "lastEditDate": 1785326400000,
            "dataLastEditDate": 1785240000000,
            "schemaLastEditDate": 1785153600000,
        },
    }


def polygon(index: int) -> dict[str, Any]:
    x = -88.5 + index * 0.01
    y = 41.8 + index * 0.01
    return {
        "type": "Polygon",
        "coordinates": [[
            [x, y], [x + 0.002, y], [x + 0.002, y + 0.002],
            [x, y + 0.002], [x, y],
        ]],
    }


def feature(object_id: int, stable_id: Any | None = None) -> dict[str, Any]:
    stable_id = object_id * 10 if stable_id is None else stable_id
    return {
        "type": "Feature",
        "properties": {
            "OBJECTID": object_id,
            "FPId": stable_id,
            "Name": f"Building {object_id}",
        },
        "geometry": polygon(object_id),
    }


class FakeRequester:
    def __init__(self) -> None:
        self.metadata = layer_metadata()
        self.object_ids = [3, 1, 2]
        self.features = {value: feature(value) for value in self.object_ids}
        self.calls: list[tuple[str, dict[str, str], float]] = []

    def __call__(self, url: str, params: dict[str, str], timeout: float) -> dict[str, Any]:
        self.calls.append((url, dict(params), timeout))
        if url == LAYER_URL:
            return copy.deepcopy(self.metadata)
        if params.get("returnIdsOnly") == "true":
            return {"objectIdFieldName": "OBJECTID", "objectIds": list(self.object_ids)}
        ids = [int(value) for value in params["objectIds"].split(",")]
        return {
            "type": "FeatureCollection",
            "features": [copy.deepcopy(self.features[value]) for value in reversed(ids)],
        }


class ArcGISProfileTests(unittest.TestCase):
    def test_official_kane_profile_is_valid_and_repository_specific(self) -> None:
        info = county_arcgis.profile_info(OFFICIAL_PROFILE)
        self.assertTrue(info["valid"])
        self.assertEqual("kane-county-building-footprints", info["profile_key"])
        self.assertEqual("FPId", info["id_property"])
        self.assertEqual(4326, info["out_srs"])
        self.assertIn("KaneCo_IL_BuildingFootprints", info["layer_url"])

    def test_profile_requires_stable_and_object_ids_in_output_fields(self) -> None:
        profile = profile_document()
        profile["out_fields"] = ["Name"]
        errors = county_arcgis.profile_errors(profile)
        self.assertIn("out_fields must include 'OBJECTID' from object_id_field.", errors)
        self.assertIn("out_fields must include 'FPId' from id_property.", errors)

    def test_layer_metadata_contract_rejects_schema_drift(self) -> None:
        metadata = layer_metadata()
        metadata["geometryType"] = "esriGeometryPoint"
        with self.assertRaisesRegex(RuntimeError, "metadata mismatch"):
            county_arcgis.validate_layer_metadata(profile_document(), metadata)


class ArcGISHarvestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.profile = self.root / "profile.json"
        self.profile.write_text(json.dumps(profile_document()), encoding="utf-8")
        self.output = self.root / "release.geojson"
        self.requester = FakeRequester()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def harvest(self, force: bool = False) -> dict[str, Any]:
        return county_arcgis.harvest(
            self.profile,
            self.output,
            force=force,
            timeout=19.0,
            requester=self.requester,
            harvested_at="2026-07-31T15:00:00.000Z",
        )

    def test_harvest_uses_object_id_chunks_and_writes_deterministic_release(self) -> None:
        info = self.harvest()
        document = json.loads(self.output.read_text(encoding="utf-8"))
        manifest = json.loads(county_arcgis.manifest_path(self.output).read_text(encoding="utf-8"))
        self.assertEqual(["10", "20", "30"], [item["id"] for item in document["features"]])
        self.assertEqual([1, 2, 3], [item["properties"]["OBJECTID"] for item in document["features"]])
        page_calls = [call for call in self.requester.calls if "objectIds" in call[1]]
        self.assertEqual(["1,2", "3"], [call[1]["objectIds"] for call in page_calls])
        self.assertEqual(3, info["feature_count"])
        self.assertEqual(2, info["page_count"])
        self.assertEqual(3, manifest["output"]["feature_count"])
        self.assertEqual(info["sha256"], manifest["output"]["sha256"])
        self.assertEqual("FPId", manifest["source"]["stable_id_property"])
        self.assertEqual("2026-07-29T12:00:00.000Z", manifest["source"]["layer_last_edit_at"])
        self.assertNotIn(str(self.root), self.output.read_text(encoding="utf-8"))

    def test_missing_stable_id_rejects_candidate_and_preserves_existing_pair(self) -> None:
        self.output.write_text("accepted output", encoding="utf-8")
        sidecar = county_arcgis.manifest_path(self.output)
        sidecar.write_text("accepted manifest", encoding="utf-8")
        self.requester.features[2]["properties"]["FPId"] = None
        with self.assertRaisesRegex(RuntimeError, "missing stable FPId"):
            self.harvest(force=True)
        self.assertEqual("accepted output", self.output.read_text(encoding="utf-8"))
        self.assertEqual("accepted manifest", sidecar.read_text(encoding="utf-8"))

    def test_duplicate_stable_id_rejects_candidate(self) -> None:
        self.requester.features[2]["properties"]["FPId"] = 10
        with self.assertRaisesRegex(RuntimeError, "duplicate stable ID 10"):
            self.harvest()
        self.assertFalse(self.output.exists())
        self.assertFalse(county_arcgis.manifest_path(self.output).exists())

    def test_page_object_id_mismatch_rejects_candidate(self) -> None:
        self.requester.features[2]["properties"]["OBJECTID"] = 99
        with self.assertRaisesRegex(RuntimeError, "object ID mismatch"):
            self.harvest()
        self.assertFalse(self.output.exists())

    def test_force_replaces_output_and_removes_temporary_files(self) -> None:
        self.output.write_text("old", encoding="utf-8")
        county_arcgis.manifest_path(self.output).write_text("old manifest", encoding="utf-8")
        self.harvest(force=True)
        self.assertTrue(self.output.read_text(encoding="utf-8").startswith('{"features"'))
        leftovers = [path.name for path in self.root.iterdir() if "candidate" in path.name or "backup" in path.name]
        self.assertEqual([], leftovers)

    def test_existing_output_is_refused_without_force_before_network(self) -> None:
        self.output.write_text("old", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "already exists"):
            self.harvest()
        self.assertEqual("old", self.output.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
