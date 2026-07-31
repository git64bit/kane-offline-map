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
        for name, value in fixtures.items():
            (self.prepared / name).write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")

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
            for name in ("county_boundary.json", "roads.json", "water.json", "buildings.json"):
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
        readme = (ROOT / "deployment" / "USB_DEPLOYMENT_README.txt").read_text(encoding="utf-8")
        self.assertIn("portable_archive.py", script)
        self.assertIn("data/reviews/current", readme)
        self.assertIn("TrivialHTTP runtime files", readme)
        self.assertLessEqual(len((ROOT / "deployment" / "tools" / "portable_archive.py").read_text().splitlines()), 500)


if __name__ == "__main__":
    unittest.main()
