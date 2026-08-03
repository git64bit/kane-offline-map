from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

TOOLS = Path(__file__).resolve().parents[1] / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import county_arcgis
import county_harvest

DATABASE = Path(__file__).resolve().parents[1]
ROAD_PROFILE = DATABASE / "sources" / "kane-county-roads.json"
RIVER_PROFILE = DATABASE / "sources" / "kane-county-fox-river.json"
CREEK_PROFILE = DATABASE / "sources" / "kane-county-creeks.json"
LAYER_URL = "https://example.test/arcgis/rest/services/roads/FeatureServer/0"


def profile_document(geometry: str = "esriGeometryPolyline") -> dict[str, Any]:
    return {
        "profile_schema": 1,
        "profile_key": "fixture-roads",
        "agency_key": "fixture-gis",
        "dataset_key": "roads",
        "layer_url": LAYER_URL,
        "where": "1=1",
        "object_id_field": "OBJECTID",
        "id_property": "OBJECTID",
        "expected_geometry_type": geometry,
        "out_srs": 4326,
        "page_size": 2,
        "out_fields": ["OBJECTID"],
        "copyright_text": "Fixture GIS",
    }


def metadata(geometry: str = "esriGeometryPolyline") -> dict[str, Any]:
    return {
        "type": "Feature Layer",
        "name": "Fixture roads",
        "geometryType": geometry,
        "supportedQueryFormats": "JSON, geoJSON, PBF",
        "objectIdField": "OBJECTID",
        "maxRecordCount": 2000,
        "copyrightText": "Fixture GIS",
        "fields": [{"name": "OBJECTID", "type": "esriFieldTypeOID"}],
        "editingInfo": {
            "lastEditDate": 1785326400000,
            "dataLastEditDate": 1785240000000,
            "schemaLastEditDate": 1785153600000,
        },
    }


def line_feature(object_id: int, multi: bool = False) -> dict[str, Any]:
    path = [[-88.6 + object_id / 1000, 41.8], [-88.5, 41.9]]
    geometry = {
        "type": "MultiLineString" if multi else "LineString",
        "coordinates": [path, list(reversed(path))] if multi else path,
    }
    return {
        "type": "Feature",
        "properties": {"OBJECTID": object_id},
        "geometry": geometry,
    }


def polygon_feature(object_id: int) -> dict[str, Any]:
    return {
        "type": "Feature",
        "properties": {"OBJECTID": object_id},
        "geometry": {
            "type": "Polygon",
            "coordinates": [[
                [-88.6, 41.8], [-88.5, 41.8], [-88.5, 41.9],
                [-88.6, 41.9], [-88.6, 41.8],
            ]],
        },
    }


class LinearRequester:
    def __init__(self) -> None:
        self.features = {
            1: line_feature(1),
            2: line_feature(2, multi=True),
            3: line_feature(3),
        }
        self.calls: list[tuple[str, dict[str, str], float]] = []

    def __call__(self, url: str, params: dict[str, str], timeout: float) -> dict[str, Any]:
        self.calls.append((url, dict(params), timeout))
        if url == LAYER_URL:
            return copy.deepcopy(metadata())
        if params.get("returnIdsOnly") == "true":
            return {"objectIdFieldName": "OBJECTID", "objectIds": [3, 1, 2]}
        ids = [int(value) for value in params["objectIds"].split(",")]
        return {
            "type": "FeatureCollection",
            "features": [copy.deepcopy(self.features[value]) for value in reversed(ids)],
        }


class OfficialLinearProfileTests(unittest.TestCase):
    def test_official_profiles_are_repository_specific(self) -> None:
        records = [
            (ROAD_PROFILE, "roads", "esriGeometryPolyline", "KaneCo_IL_Centerlines_ROW"),
            (RIVER_PROFILE, "water-fox-river", "esriGeometryPolygon", "KaneCo_IL_FoxRiver"),
            (CREEK_PROFILE, "water-creeks", "esriGeometryPolyline", "KaneCo_IL_Creeks"),
        ]
        for path, dataset, geometry, service in records:
            profile, _ = county_arcgis.load_profile(path)
            self.assertEqual(dataset, profile["dataset_key"])
            self.assertEqual(geometry, profile["expected_geometry_type"])
            self.assertIn(service, profile["layer_url"])
            self.assertTrue(profile["layer_url"].endswith("/FeatureServer/1"))
        road_profile, _ = county_arcgis.load_profile(ROAD_PROFILE)
        self.assertEqual("exclude", road_profile["missing_geometry_policy"])

    def test_profile_info_reports_geometry_contract(self) -> None:
        info = county_arcgis.profile_info(ROAD_PROFILE)
        self.assertEqual("esriGeometryPolyline", info["expected_geometry_type"])

    def test_unsupported_geometry_contract_is_rejected(self) -> None:
        profile = profile_document("esriGeometryPoint")
        errors = county_arcgis.profile_errors(profile)
        self.assertTrue(any("Unsupported ArcGIS geometry contract" in item for item in errors))

    def test_missing_geometry_exclusion_requires_object_id_identity(self) -> None:
        profile = profile_document()
        profile["missing_geometry_policy"] = "exclude"
        profile["id_property"] = "ROAD_ID"
        profile["out_fields"].append("ROAD_ID")
        errors = county_arcgis.profile_errors(profile)
        self.assertIn(
            "missing_geometry_policy 'exclude' requires id_property to equal object_id_field.",
            errors,
        )

    def test_unknown_missing_geometry_policy_is_rejected(self) -> None:
        profile = profile_document()
        profile["missing_geometry_policy"] = "ignore"
        self.assertIn(
            "missing_geometry_policy must be 'reject' or 'exclude'.",
            county_arcgis.profile_errors(profile),
        )


class LinearHarvestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.profile = self.root / "roads-profile.json"
        self.profile.write_text(json.dumps(profile_document()), encoding="utf-8")
        self.output = self.root / "roads.geojson"
        self.requester = LinearRequester()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def harvest(self) -> dict[str, Any]:
        return county_arcgis.harvest(
            self.profile,
            self.output,
            requester=self.requester,
            harvested_at="2026-08-03T12:00:00.000Z",
        )

    def test_polyline_harvest_accepts_line_and_multiline_geometry(self) -> None:
        info = self.harvest()
        document = json.loads(self.output.read_text(encoding="utf-8"))
        self.assertEqual(3, info["feature_count"])
        self.assertEqual(["1", "2", "3"], [item["id"] for item in document["features"]])
        self.assertEqual("MultiLineString", document["features"][1]["geometry"]["type"])

    def test_polyline_harvest_pair_validates_offline(self) -> None:
        self.harvest()
        info = county_harvest.validate_harvest(self.profile, self.output)
        self.assertTrue(info["valid"])
        self.assertTrue(info["release_key"].startswith("kane-roads-20260728-"))

    def test_polygon_geometry_is_rejected_by_polyline_profile(self) -> None:
        self.requester.features[2] = polygon_feature(2)
        with self.assertRaisesRegex(RuntimeError, "expected LineString or MultiLineString"):
            self.harvest()
        self.assertFalse(self.output.exists())

    def test_polyline_geometry_is_rejected_by_polygon_profile(self) -> None:
        profile = profile_document("esriGeometryPolygon")
        with self.assertRaisesRegex(RuntimeError, "expected Polygon or MultiPolygon"):
            county_arcgis.normalize_page(
                {"type": "FeatureCollection", "features": [line_feature(1)]},
                [1], "OBJECTID", "OBJECTID", profile["expected_geometry_type"], set(),
            )

    def test_degenerate_line_is_rejected(self) -> None:
        self.requester.features[1]["geometry"]["coordinates"] = [[-88.6, 41.8]]
        with self.assertRaisesRegex(RuntimeError, "at least 2 coordinate pairs"):
            self.harvest()

    def test_missing_geometry_is_rejected_by_default(self) -> None:
        self.requester.features[2]["geometry"] = None
        with self.assertRaisesRegex(RuntimeError, "geometry is missing or invalid"):
            self.harvest()

    def test_profile_can_exclude_and_record_missing_geometry(self) -> None:
        profile = profile_document()
        profile["missing_geometry_policy"] = "exclude"
        self.profile.write_text(json.dumps(profile), encoding="utf-8")
        self.requester.features[2]["geometry"] = None
        info = self.harvest()
        document = json.loads(self.output.read_text(encoding="utf-8"))
        manifest = json.loads(county_arcgis.manifest_path(self.output).read_text(encoding="utf-8"))
        accepted = county_harvest.validate_harvest(self.profile, self.output)
        self.assertEqual(["1", "3"], [item["id"] for item in document["features"]])
        self.assertEqual([2], document["exclusions"]["object_ids"])
        self.assertEqual(document["exclusions"], manifest["exclusions"])
        self.assertEqual(2, info["feature_count"])
        self.assertEqual(3, info["source_record_count"])
        self.assertEqual(1, info["excluded_feature_count"])
        self.assertEqual(2, accepted["feature_count"])
        self.assertEqual(3, accepted["object_id_count"])
        self.assertEqual(1, accepted["excluded_feature_count"])

    def test_exclusion_policy_does_not_accept_malformed_geometry(self) -> None:
        profile = profile_document()
        profile["missing_geometry_policy"] = "exclude"
        self.profile.write_text(json.dumps(profile), encoding="utf-8")
        self.requester.features[2]["geometry"] = {}
        with self.assertRaisesRegex(RuntimeError, "expected LineString or MultiLineString"):
            self.harvest()

    def test_exclusion_inventory_hash_is_validated(self) -> None:
        profile = profile_document()
        profile["missing_geometry_policy"] = "exclude"
        self.profile.write_text(json.dumps(profile), encoding="utf-8")
        self.requester.features[2]["geometry"] = None
        self.harvest()
        document = json.loads(self.output.read_text(encoding="utf-8"))
        manifest = json.loads(county_arcgis.manifest_path(self.output).read_text(encoding="utf-8"))
        document["exclusions"]["object_ids_sha256"] = "0" * 64
        manifest["exclusions"] = copy.deepcopy(document["exclusions"])
        with self.assertRaisesRegex(RuntimeError, "exclusion object-ID hash"):
            county_harvest.validate_exclusions(document, manifest, profile)


if __name__ == "__main__":
    unittest.main()
