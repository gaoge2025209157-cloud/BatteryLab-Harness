import json
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from electrochem_harness.sci_report import create_scientific_bundle


class ScientificReportTests(unittest.TestCase):
    def test_current_review_status_keeps_unavailable_sources_as_placeholders(self):
        path = PROJECT_ROOT / "docs" / "scientific-validation" / "current-review-status.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        serialized = json.dumps(payload, ensure_ascii=False)

        self.assertEqual(payload["publication_gate"], "blocked")
        self.assertEqual(payload["source_materials"]["raw_export"]["status"], "pending")
        self.assertEqual(payload["voltage_window"]["status"], "pending")
        self.assertEqual(payload["cycle_mapping"]["calculation_convention"], "B")
        self.assertEqual(payload["final_segment"]["metric_handling"], "excluded")
        self.assertNotRegex(serialized, r"[A-Za-z]:\\\\")

    def test_bundle_records_blocked_release_gate(self):
        source = PROJECT_ROOT / "examples" / "sample_capacity_curve.csv"
        with tempfile.TemporaryDirectory() as tmp:
            paths = create_scientific_bundle(source, Path(tmp), search_literature=False)
            payload = json.loads(paths["json"].read_text(encoding="utf-8"))
            markdown = paths["report"].read_text(encoding="utf-8")

        self.assertEqual(payload["publication_gate"]["status"], "blocked")
        self.assertFalse(payload["publication_gate"]["can_publish"])
        self.assertIn("Scientific release gate", markdown)
        self.assertIn("private real-data", markdown)

    def test_boundary_fixture_is_synthetic_and_complete(self):
        fixture = PROJECT_ROOT / "tests" / "fixtures" / "scientific-boundary-cases.json"
        cases = json.loads(fixture.read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(cases), 18)
        self.assertTrue(all(case["id"].startswith("BC-") for case in cases))
        self.assertTrue(all(case["release_effect"] for case in cases))


if __name__ == "__main__":
    unittest.main()
