import json
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))


class OriginCompatibilityTests(unittest.TestCase):
    def test_matrix_covers_every_release_from_2021_through_2026b(self):
        matrix = json.loads((PROJECT_ROOT / "origin_compat.json").read_text(encoding="utf-8"))
        expected = [
            "2021", "2021b", "2022", "2022b", "2023", "2023b",
            "2024", "2024b", "2025", "2025b", "2026", "2026b",
        ]

        self.assertEqual(matrix["supported_releases"], expected)
        self.assertEqual(matrix["minimum_year"], 2021)
        self.assertEqual(matrix["maximum_year"], 2026)
        self.assertEqual(matrix["locally_validated"], ["2026b"])

    def test_launcher_reads_matrix_and_records_detected_release(self):
        launcher = (PROJECT_ROOT / "run_sci_origin.ps1").read_text(encoding="utf-8-sig")

        self.assertIn("origin_compat.json", launcher)
        self.assertIn("Get-OriginRelease", launcher)
        self.assertIn("ELECTROCHEM_ORIGIN_RELEASE", launcher)
        self.assertIn("Origin.ApplicationSI", launcher)
        self.assertNotIn("Origin.ApplicationCOMSI", launcher)
        self.assertIn("OriginRuntimeDir", launcher)
        self.assertIn("Copy-Item", launcher)
        self.assertIn("return [int]$code", launcher)
        self.assertIn("origin_release", launcher)

    def test_plotter_has_fallbacks_for_older_originpro_versions(self):
        plotter = (PROJECT_ROOT / "origin_plot.py").read_text(encoding="utf-8")

        self.assertIn("save_figure_compat", plotter)
        self.assertIn("set_plot_property_compat", plotter)
        self.assertIn("get_lt_str", plotter)
        self.assertIn("originpro_version", plotter)
        self.assertNotIn("Run inside Origin 2026b", plotter)

    def test_environment_check_reports_supported_release(self):
        checker = (PROJECT_ROOT / "check_environment.ps1").read_text(encoding="utf-8-sig")

        self.assertIn("origin_compat.json", checker)
        self.assertIn("supported release", checker)

    def test_release_builder_and_docs_include_compatibility_matrix(self):
        builder = (PROJECT_ROOT / "build_release.ps1").read_text(encoding="utf-8-sig")
        guide = (PROJECT_ROOT / "README_发布版.md").read_text(encoding="utf-8")

        self.assertIn("origin_compat.json", builder)
        self.assertIn("ORIGIN_COMPATIBILITY.md", builder)
        self.assertTrue((PROJECT_ROOT / "ORIGIN_COMPATIBILITY.md").is_file())
        self.assertIn("Origin 2021", guide)
        self.assertIn("2026b", guide)
        self.assertIn("仅2026b完成本机实测", guide)
        self.assertEqual((PROJECT_ROOT / "VERSION").read_text(encoding="utf-8").strip(), "0.5.0-rc1")


if __name__ == "__main__":
    unittest.main()
