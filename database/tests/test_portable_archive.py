from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "deployment" / "tools"))

from portable_archive import ArchiveError, build_archive, validate_archive  # noqa: E402

SOURCE_COMMIT = "1" * 40


class PortableArchiveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.temp = Path(self.temporary.name)
        self.prepared = self.temp / "prepared"
        self.prepared.mkdir()
        fixtures = {
            "county_boundary.json": {"type": "FeatureCollection", "features": []},
            "roads.json": {"type": "FeatureCollection", "features": []},
            "water.json": {"type": "FeatureCollection", "features": []},
            "buildings.json": {"type": "FeatureCollection", "features": []},
        }
        datasets = {}
        keys = {
            "county_boundary.json": "county_boundary",
            "roads.json": "roads",
            "water.json": "water",
            "buildings.json": "buildings",
        }
        for name, value in fixtures.items():
            path = self.prepared / name
            path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
            content = path.read_bytes()
            datasets[keys[name]] = {
                "relative_path": name,
                "feature_count": 1,
                "byte_length": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
                "releases": [{
                    "dataset_key": keys[name],
                    "release_key": f"fixture-{keys[name]}",
                    "content_sha256": "0" * 64,
                }],
            }
        manifest = {
            "schema": "kane-offline-map-prepared-core",
            "schema_version": 2,
            "project": "kane-offline-map",
            "source_database": {"byte_length": 1, "sha256": "1" * 64},
            "datasets": datasets,
            "complete_browser_bundle": True,
            "remaining_datasets": [],
        }
        (self.prepared / "core-manifest.json").write_text(
            json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def build(self, name: str = "portable.zip", force: bool = False) -> tuple[Path, dict[str, object]]:
        output = self.temp / name
        return output, build_archive(ROOT, self.prepared, output, SOURCE_COMMIT, force=force)

    def test_archive_is_deterministic(self) -> None:
        first, first_result = self.build("first.zip")
        second, second_result = self.build("second.zip")
        self.assertEqual(first.read_bytes(), second.read_bytes())
        self.assertEqual(first_result["sha256"], second_result["sha256"])

    def test_archive_has_one_root_and_excludes_development_products(self) -> None:
        output, _ = self.build()
        with zipfile.ZipFile(output) as archive:
            names = archive.namelist()
        self.assertTrue(all(name.startswith("kane-offline-map/") for name in names))
        self.assertIn("kane-offline-map/index.html", names)
        self.assertIn("kane-offline-map/project-data/sectors/README.txt", names)
        self.assertNotIn("kane-offline-map/database/input/sectors.zip", names)
        self.assertFalse(any("/.git/" in name or name.endswith(".gpkg") for name in names))

    def test_manifest_verifies_every_payload_and_source_commit(self) -> None:
        output, _ = self.build()
        with zipfile.ZipFile(output) as archive:
            manifest = json.loads(archive.read("kane-offline-map/PORTABLE_MANIFEST.json"))
        self.assertEqual(SOURCE_COMMIT, manifest["source_commit"])
        self.assertFalse(manifest["review_bundle_included"])
        self.assertFalse(manifest["trivialhttp_runtime_included"])
        self.assertGreater(manifest["payload_file_count"], 10)
        self.assertEqual(manifest, validate_archive(output, manifest))

    def test_prepared_data_is_copied_exactly(self) -> None:
        output, result = self.build()
        with zipfile.ZipFile(output) as archive:
            for name in (
                "county_boundary.json", "roads.json", "water.json",
                "buildings.json", "core-manifest.json",
            ):
                expected = (self.prepared / name).read_bytes()
                actual = archive.read(f"kane-offline-map/data/kane-county/{name}")
                self.assertEqual(expected, actual)
                self.assertEqual(hashlib.sha256(expected).hexdigest(), result["prepared_data"][name]["sha256"])

    def test_missing_prepared_file_refuses_candidate(self) -> None:
        (self.prepared / "water.json").unlink()
        output = self.temp / "missing.zip"
        with self.assertRaises(ArchiveError):
            build_archive(ROOT, self.prepared, output, SOURCE_COMMIT)
        self.assertFalse(output.exists())

    def test_partial_prepared_manifest_is_rejected(self) -> None:
        manifest_path = self.prepared / "core-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["complete_browser_bundle"] = False
        manifest["remaining_datasets"] = ["water"]
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(ArchiveError, "not marked complete"):
            build_archive(ROOT, self.prepared, self.temp / "partial.zip", SOURCE_COMMIT)

    def test_prepared_manifest_hash_mismatch_is_rejected(self) -> None:
        with (self.prepared / "roads.json").open("ab") as stream:
            stream.write(b" ")
        with self.assertRaisesRegex(ArchiveError, "mismatch"):
            build_archive(ROOT, self.prepared, self.temp / "tampered.zip", SOURCE_COMMIT)

    def test_existing_output_is_preserved_without_force(self) -> None:
        output = self.temp / "existing.zip"
        output.write_bytes(b"accepted")
        with self.assertRaises(ArchiveError):
            build_archive(ROOT, self.prepared, output, SOURCE_COMMIT)
        self.assertEqual(b"accepted", output.read_bytes())

    def test_force_replaces_only_with_valid_archive(self) -> None:
        output = self.temp / "replace.zip"
        output.write_bytes(b"old")
        result = build_archive(ROOT, self.prepared, output, SOURCE_COMMIT, force=True)
        self.assertTrue(result["valid"])
        with zipfile.ZipFile(output) as archive:
            self.assertIn("kane-offline-map/PORTABLE_MANIFEST.json", archive.namelist())

    def test_shell_entrypoint_and_manual_addition_contract(self) -> None:
        script = (ROOT / "deployment" / "build-portable-archive.sh").read_text(encoding="utf-8")
        pipeline = (ROOT / "deployment" / "build-deployment-archive.sh").read_text(encoding="utf-8")
        readme = (ROOT / "deployment" / "USB_DEPLOYMENT_README.txt").read_text(encoding="utf-8")
        self.assertIn("portable_archive.py", script)
        self.assertIn("export-prepared-core", pipeline)
        self.assertIn("portable_archive.py", pipeline)
        self.assertIn("data/reviews/current", readme)
        self.assertIn("TrivialHTTP runtime files", readme)
        self.assertLessEqual(len((ROOT / "deployment" / "tools" / "portable_archive.py").read_text().splitlines()), 500)


if __name__ == "__main__":
    unittest.main()
