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

OFFICIAL_PROFILE = Path(__file__).resolve().parents[1] / "sources" / "kane-county-boundary.json"
LAYER_URL = "https://example.test/arcgis/rest/services/County_Boundary/FeatureServer/0"


def profile_document() -> dict[str, Any]:
    return {
        "profile_schema": 1,
        "profile_key": "fixture-county-boundary",
        "agency_key": "fixture-gis",
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


def boundary_feature(object_id: int) -> dict[str, Any]:
    return {
        "type": "Feature",
        "properties": {"OBJECTID": object_id},
        "geometry": {
            "type": "Polygon",
            "coordinates": [[
                [-88.61, 41.71], [-88.22, 41.71], [-88.22, 42.16],
                [-88.61, 42.16], [-88.61, 41.71],
            ]],
        },
    }


class BoundaryRequester:
    def __init__(self, object_ids: list[int] | None = None) -> None:
        self.object_ids = object_ids or [7]
        self.calls: list[tuple[str, dict[str, str], float]] = []

    def __call__(self, url: str, params: dict[str, str], timeout: float) -> dict[str, Any]:
        self.calls.append((url, dict(params), timeout))
        if url == LAYER_URL:
            return copy.deepcopy(layer_metadata())
        if params.get("returnIdsOnly") == "true":
            return {"objectIdFieldName": "OBJECTID", "objectIds": list(self.object_ids)}
        ids = [int(value) for value in params["objectIds"].split(",")]
        return {
            "type": "FeatureCollection",
            "features": [boundary_feature(value) for value in reversed(ids)],
        }


class BoundaryProfileTests(unittest.TestCase):
    def test_official_boundary_profile_is_repository_specific(self) -> None:
        info = county_arcgis.profile_info(OFFICIAL_PROFILE)
        self.assertTrue(info["valid"])
        self.assertEqual("kane-county-boundary", info["profile_key"])
        self.assertEqual("OBJECTID", info["id_property"])
        self.assertEqual(1, info["expected_feature_count"])
        self.assertIn("County_Boundary", info["layer_url"])

    def test_expected_feature_count_must_be_positive(self) -> None:
        profile = profile_document()
        profile["expected_feature_count"] = 0
        self.assertIn(
            "expected_feature_count must be a positive integer when provided.",
            county_arcgis.profile_errors(profile),
        )

    def test_object_id_may_also_be_the_stable_id(self) -> None:
        self.assertEqual([], county_arcgis.profile_errors(profile_document()))


class BoundaryHarvestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.profile = self.root / "boundary-profile.json"
        self.profile.write_text(json.dumps(profile_document()), encoding="utf-8")
        self.output = self.root / "boundary.geojson"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_one_feature_harvest_validates_with_boundary_release_identity(self) -> None:
        info = county_arcgis.harvest(
            self.profile,
            self.output,
            requester=BoundaryRequester(),
            harvested_at="2026-07-31T17:00:00.000Z",
        )
        accepted = county_harvest.validate_harvest(self.profile, self.output)
        self.assertEqual(1, info["feature_count"])
        self.assertEqual(1, accepted["feature_count"])
        self.assertEqual("OBJECTID", accepted["id_property"])
        self.assertTrue(accepted["release_key"].startswith("kane-county-boundary-20260728-"))

    def test_wrong_live_feature_count_is_rejected_before_output(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "returned 2 features; expected 1"):
            county_arcgis.harvest(
                self.profile,
                self.output,
                requester=BoundaryRequester([7, 8]),
                harvested_at="2026-07-31T17:00:00.000Z",
            )
        self.assertFalse(self.output.exists())
        self.assertFalse(county_arcgis.manifest_path(self.output).exists())

    def test_boundary_manifest_records_exact_single_page_inventory(self) -> None:
        county_arcgis.harvest(
            self.profile,
            self.output,
            requester=BoundaryRequester(),
            harvested_at="2026-07-31T17:00:00.000Z",
        )
        manifest = json.loads(county_arcgis.manifest_path(self.output).read_text(encoding="utf-8"))
        self.assertEqual(1, manifest["request"]["object_id_count"])
        self.assertEqual(1, manifest["request"]["page_count"])
        self.assertEqual(1, manifest["output"]["feature_count"])


if __name__ == "__main__":
    unittest.main()
