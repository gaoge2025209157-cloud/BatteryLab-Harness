from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from electrochem_harness_v2.cv_analysis import analyze_cv


class CvAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.points = [
            {"potential_V": 0.0, "current_A": 0.0},
            {"potential_V": 1.0, "current_A": 1.0},
            {"potential_V": 2.0, "current_A": 3.0},
            {"potential_V": 3.0, "current_A": 1.0},
            {"potential_V": 2.0, "current_A": -1.0},
            {"potential_V": 1.0, "current_A": -2.0},
            {"potential_V": 0.0, "current_A": -0.5},
        ]

    def test_detects_directions_peaks_separation_and_cycle(self):
        result = analyze_cv(self.points)
        self.assertEqual(result["schema_version"], "1.0")
        self.assertEqual([row["direction"] for row in result["sweeps"]], ["increasing", "decreasing"])
        self.assertEqual(result["cycle_count"], 1)
        self.assertEqual(result["complete_cycle_count"], 1)
        self.assertEqual(result["cycles"][0]["oxidation_peak"]["potential_V"], 2.0)
        self.assertEqual(result["cycles"][0]["reduction_peak"]["potential_V"], 1.0)
        self.assertEqual(result["cycles"][0]["peak_separation_V"], 1.0)
        self.assertIsNone(result["sweeps"][0]["integrated_charge_C"])
        self.assertTrue(any("I·dV" in item for item in result["limitations"]))

    def test_integrates_charge_only_with_scan_rate(self):
        result = analyze_cv(self.points, scan_rate=2.0)
        self.assertAlmostEqual(result["sweeps"][0]["integrated_charge_C"], 2.25)
        self.assertAlmostEqual(result["sweeps"][1]["integrated_charge_C"], -1.375)

    def test_accepts_csv_and_rejects_bad_values_units_and_small_input(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cv.csv"
            path.write_text("potential_V,current_A\n" + "\n".join(
                "{},{}".format(point["potential_V"], point["current_A"]) for point in self.points
            ), encoding="utf-8")
            self.assertEqual(analyze_cv(path)["point_count"], 7)
        with self.assertRaises(ValueError):
            analyze_cv(self.points[:-1] + [{"potential_V": float("nan"), "current_A": 0.0}])
        with self.assertRaises(ValueError):
            analyze_cv(self.points, units={"potential_V": "mV", "current_A": "A"})
        mixed_row_units = [dict(point) for point in self.points]
        mixed_row_units[2]["potential_unit"] = "mV"
        with self.assertRaises(ValueError):
            analyze_cv(mixed_row_units)
        with self.assertRaises(ValueError):
            analyze_cv(self.points[:4])
        with self.assertRaises(ValueError):
            analyze_cv(self.points, scan_rate=1.0, scan_rate_unit="mV/s")


if __name__ == "__main__":
    unittest.main()
