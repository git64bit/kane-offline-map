from __future__ import annotations

import importlib.util
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "county_db.py"
INPUT_ARCHIVE = Path(__file__).resolve().parents[1] / "input" / "sectors.zip"
SPEC = importlib.util.spec_from_file_location("county_db", MODULE_PATH)
county_db = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(county_db)


class CountyDatabaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.database = Path(self.tempdir.name) / "test.gpkg"

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_initialize_and_validate(self) -> None:
        county_db.initialize_database(self.database, force=False)
        self.assertEqual([], county_db.validate_database(self.database))
        info = county_db.database_info(self.database)
        self.assertTrue(info["valid"])
        self.assertEqual("17089", info["county"]["fips_code"])
        self.assertEqual(6, len(info["migrations"]))
        self.assertIsNone(info["accepted_classification"])

    def test_refuses_overwrite(self) -> None:
        county_db.initialize_database(self.database, force=False)
        with self.assertRaises(RuntimeError):
            county_db.initialize_database(self.database, force=False)

    def test_detects_wrong_application_id(self) -> None:
        county_db.initialize_database(self.database, force=False)
        connection = sqlite3.connect(self.database)
        try:
            connection.execute("PRAGMA application_id = 0")
        finally:
            connection.close()
        errors = county_db.validate_database(self.database)
        self.assertTrue(any("application_id" in error for error in errors))

    def test_detects_migration_tampering(self) -> None:
        county_db.initialize_database(self.database, force=False)
        connection = sqlite3.connect(self.database)
        try:
            connection.execute(
                "UPDATE schema_migration SET sha256 = ? WHERE migration_id = 1",
                ("0" * 64,),
            )
            connection.commit()
        finally:
            connection.close()
        errors = county_db.validate_database(self.database)
        self.assertTrue(any("checksum mismatch" in error for error in errors))

    def test_detects_wrong_project_identity(self) -> None:
        county_db.initialize_database(self.database, force=False)
        connection = sqlite3.connect(self.database)
        try:
            connection.execute(
                "UPDATE project_setting SET setting_value = ? WHERE setting_key = 'project'",
                ("county-field-map",),
            )
            connection.commit()
        finally:
            connection.close()
        errors = county_db.validate_database(self.database)
        self.assertTrue(any("project identity" in error for error in errors))

    def test_empty_foundation_is_not_an_accepted_ledger(self) -> None:
        county_db.initialize_database(self.database, force=False)
        errors = county_db.validate_ledger_database(self.database)
        self.assertTrue(any("Accepted classification release count" in error for error in errors))

    def test_failed_build_preserves_existing_candidate(self) -> None:
        county_db.initialize_database(self.database, force=False)
        original = self.database.read_bytes()
        invalid_archive = Path(self.tempdir.name) / "invalid.zip"
        with zipfile.ZipFile(invalid_archive, "w") as archive:
            archive.writestr("not-a-sector.json", "{}")
        with self.assertRaises(RuntimeError):
            county_db.build_ledger_database(
                self.database, invalid_archive, force=True, release_key=None
            )
        self.assertEqual(original, self.database.read_bytes())


class CompletedLedgerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tempdir = tempfile.TemporaryDirectory()
        cls.database = Path(cls.tempdir.name) / "completed.gpkg"
        county_db.build_ledger_database(
            cls.database, INPUT_ARCHIVE, force=False, release_key=None
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tempdir.cleanup()

    def test_completed_ledger_counts_and_hash(self) -> None:
        self.assertEqual([], county_db.validate_ledger_database(self.database))
        info = county_db.database_info(self.database)
        ledger = info["accepted_classification"]
        self.assertEqual(
            "19506566f787b11a02036dce8bf800a33b0a64219046c5e0b89d474b862f09d2",
            ledger["source_archive_sha256"],
        )
        self.assertEqual(16, ledger["sector_count"])
        self.assertEqual(4096, ledger["inspection_cell_count"])
        self.assertEqual(262144, ledger["practical_cell_count"])
        self.assertEqual(72705, ledger["discovered_count"])
        self.assertEqual(189439, ledger["muted_count"])
        self.assertEqual(0, ledger["undiscovered_count"])

    def test_completed_ledger_grid_endpoints(self) -> None:
        connection = sqlite3.connect(self.database)
        try:
            first = connection.execute(
                """
                SELECT cell_id FROM classification_cell
                WHERE global_row = 1 AND global_column = 1
                """
            ).fetchone()[0]
            last = connection.execute(
                """
                SELECT cell_id FROM classification_cell
                WHERE global_row = 512 AND global_column = 512
                """
            ).fetchone()[0]
        finally:
            connection.close()
        self.assertEqual("N11-E06:r01c01:f01c01", first)
        self.assertEqual("N14-E09:r16c16:f08c08", last)

    def test_completed_ledger_is_immutable_by_identity(self) -> None:
        with self.assertRaises(RuntimeError):
            county_db.county_ledger.import_ledger(
                self.database, INPUT_ARCHIVE, release_key=None
            )


if __name__ == "__main__":
    unittest.main()
