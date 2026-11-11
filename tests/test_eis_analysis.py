from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from electrochem_harness_v2.eis_analysis import analyze_eis


class EisAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.points = [
            {"frequency_Hz": 0.1, "z_real_ohm": 20.0, "z_imag_ohm": -4.0},
            {"frequency_Hz": 1.0, "z_real_ohm": 16.0, "z_imag_ohm": -4.0},
            {"frequency_Hz": 10.0, "z_real_ohm": 12.0, "z_imag_ohm": -4.0},
            {"frequency_Hz": 100.0, "z_real_ohm": 8.0, "z_imag_ohm": -5.0},
            {"frequency_Hz": 1000.0, "z_real_ohm": 6.0, "z_imag_ohm": -2.0},
            {"frequency_Hz": 10000.0, "z_real_ohm": 5.0, "z_imag_ohm": 0.2},
        ]

    def test_normalizes_frequency_and_extracts_descriptors(self):
        result = analyze_eis(self.points, tail_fraction=0.5)
        self.assertEqual(result["schema_version"], "1.0")
        self.assertEqual(result["frequency_range_Hz"], {"minimum": 0.1, "maximum": 10000.0})
        self.assertEqual(result["normalized_points"][0]["frequency_Hz"], 10000.0)
        self.assertIn("frequency_order_normalized", result["quality_flags"])
        self.assertEqual(result["high_frequency_real_axis_intercept_candidate"]["z_real_ohm"], 5.0)
        self.assertEqual(result["minus_z_imag_peak"]["frequency_Hz"], 100.0)
        self.assertEqual(result["minus_z_imag_peak"]["minus_z_imag_ohm"], 5.0)
        self.assertAlmostEqual(result["low_frequency_tail"]["slope_d_minus_z_imag_d_z_real"], 0.0)
        self.assertTrue(any("No equivalent-circuit" in item for item in result["limitations"]))

    def test_accepts_symbolic_csv_headers(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "eis.csv"
            path.write_text("frequency/Hz,Z'/ohm,Z''/ohm\n" + "\n".join(
                "{frequency_Hz},{z_real_ohm},{z_imag_ohm}".format(**point) for point in self.points
            ), encoding="utf-8")
            result = analyze_eis(path)
        self.assertEqual(result["normalized_points"][0]["z_real_ohm"], 5.0)
        self.assertEqual(result["normalized_points"][0]["z_imag_ohm"], 0.2)

    def test_rejects_nonpositive_frequency_nonfinite_units_and_few_points(self):
        bad_frequency = [dict(point) for point in self.points]
        bad_frequency[0]["frequency_Hz"] = 0.0
        with self.assertRaises(ValueError):
            analyze_eis(bad_frequency)
        nonfinite = [dict(point) for point in self.points]
        nonfinite[0]["z_real_ohm"] = float("inf")
        with self.assertRaises(ValueError):
            analyze_eis(nonfinite)
        with self.assertRaises(ValueError):
            analyze_eis(self.points, units={"frequency_Hz": "kHz", "z_real_ohm": "ohm", "z_imag_ohm": "ohm"})
        with self.assertRaises(ValueError):
            analyze_eis(self.points[:4])

    def test_rejects_degenerate_low_frequency_tail(self):
        points = [dict(point) for point in self.points]
        for point in points[:3]:
            point["z_real_ohm"] = 10.0
        with self.assertRaises(ValueError):
            analyze_eis(points, tail_fraction=0.5)


if __name__ == "__main__":
    unittest.main()
