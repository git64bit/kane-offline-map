from __future__ import annotations

import re
import unittest
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class InterfaceParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: set[str] = set()
        self.scripts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if values.get("id"):
            self.ids.add(str(values["id"]))
        if tag == "script" and values.get("src"):
            self.scripts.append(str(values["src"]))


class BrowserReviewContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.index = (ROOT / "index.html").read_text(encoding="utf-8")
        cls.app = (ROOT / "src" / "app.js").read_text(encoding="utf-8")
        cls.loader = (ROOT / "src" / "reviewBundleLoader.js").read_text(encoding="utf-8")
        cls.overlay = (ROOT / "src" / "reviewOverlay.js").read_text(encoding="utf-8")
        cls.renderer = (ROOT / "src" / "renderer.js").read_text(encoding="utf-8")
        cls.data_loader = (ROOT / "src" / "dataLoader.js").read_text(encoding="utf-8")
        cls.config = (ROOT / "portable_config.js").read_text(encoding="utf-8")

    def test_review_scripts_load_before_renderer_and_application(self) -> None:
        parser = InterfaceParser()
        parser.feed(self.index)
        positions = {source: parser.scripts.index(source) for source in parser.scripts}
        self.assertLess(positions["src/reviewBundleLoader.js"], positions["src/app.js"])
        self.assertLess(positions["src/reviewOverlay.js"], positions["src/renderer.js"])
        self.assertLess(positions["src/renderer.js"], positions["src/app.js"])

    def test_review_status_interface_is_required(self) -> None:
        parser = InterfaceParser()
        parser.feed(self.index)
        self.assertTrue({"reviewStatus", "reviewDetail"}.issubset(parser.ids))
        self.assertIn('document.getElementById("reviewStatus")', self.app)
        self.assertIn('document.getElementById("reviewDetail")', self.app)
        self.assertIn("Review required", self.index)

    def test_default_bundle_path_is_external_and_ignored(self) -> None:
        ignored = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn('reviewBundlePath: "data/reviews/current"', self.config)
        self.assertIn("data/reviews/current", ignored.splitlines())
        self.assertTrue((ROOT / "data" / "reviews" / "README.txt").is_file())

    def test_loader_verifies_identity_hash_and_active_sector_only(self) -> None:
        required = [
            "kane-offline-map-open-review-bundle",
            "kane-offline-map-open-review-sector",
            "CLASSIFICATION_ARCHIVE_SHA256",
            'cache: "no-store"',
            'digest("SHA-256"',
            "G.parsePracticalCode",
            "releaseSector",
        ]
        for value in required:
            self.assertIn(value, self.loader)
        self.assertNotIn("Promise.all", self.loader)

    def test_renderer_places_reviews_at_all_three_grid_levels(self) -> None:
        self.assertIn("CFM.createReviewOverlay", self.renderer)
        self.assertIn("reviewOverlay.drawCounty(context)", self.renderer)
        self.assertIn("reviewOverlay.drawSector(context, selectedSector)", self.renderer)
        self.assertIn("reviewOverlay.drawPractical(ctx, selectedSector, selectedInspection)", self.renderer)
        self.assertIn("G.sectorBounds", self.overlay)
        self.assertIn("G.inspectionBounds", self.overlay)
        self.assertIn("G.practicalBounds", self.overlay)

    def test_review_failure_is_nonfatal_and_read_only(self) -> None:
        self.assertIn("console.warn(\"Kane Offline Map review bundle unavailable\"", self.app)
        self.assertIn('setReviewState("unavailable"', self.app)
        self.assertNotIn("classification_review", self.app)
        self.assertNotIn("fetch(\"/__", self.loader)
        self.assertIn("Orange outlines are read-only", self.app)

    def test_linear_water_is_loaded_and_drawn_separately(self) -> None:
        self.assertIn("waterLines: convertLines", self.data_loader)
        self.assertIn("sectorData.waterLines", self.renderer)
        self.assertIn("drawPaths(ctx, sectorData.waterLines", self.renderer)
        self.assertIn("COLORS.water", self.renderer)

    def test_script_line_count_contract(self) -> None:
        scripts = sorted((ROOT / "src").glob("*.js"))
        offenders = {path.name: len(path.read_text(encoding="utf-8").splitlines())
                     for path in scripts
                     if len(path.read_text(encoding="utf-8").splitlines()) > 500}
        self.assertEqual({}, offenders)
        self.assertRegex(self.loader, re.compile(r"currentSector:\s*\(\)\s*=>\s*loadedSector"))


if __name__ == "__main__":
    unittest.main()
