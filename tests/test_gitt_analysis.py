from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from electrochem_harness_v2.gitt_analysis import analyze_gitt


class GittAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.points = [
            {"time_s": 0.0, "current_A": 0.0, "voltage_V": 3.00},
            {"time_s": 1.0, "current_A": 0.0, "voltage_V": 3.00},
            {"time_s": 2.0, "current_A": 0.1, "voltage_V": 3.10},
            {"time_s": 3.0, "current_A": 0.1, "voltage_V": 3.20},
            {"time_s": 4.0, "current_A": 0.1, "voltage_V": 3.25},
            {"time_s": 5.0, "current_A": 0.0, "voltage_V": 3.22},
            {"time_s": 6.0, "current_A": 0.0, "voltage_V": 3.20},
            {"time_s": 7.0, "current_A": -0.1, "voltage_V": 3.10},
            {"time_s": 8.0, "current_A": -0.1, "voltage_V": 3.00},
            {"time_s": 9.0, "current_A": 0.0, "voltage_V": 3.02},
            {"time_s": 10.0, "current_A": 0.0, "voltage_V": 3.05},
        ]

    def test_segments_steps_and_reports_voltage_changes_without_diffusion(self):
        result = analyze_gitt(self.points, current_threshold_A=0.01)
        self.assertEqual(result["schema_version"], "1.0")
        self.assertEqual(result["step_count"], 5)
        self.assertEqual(result["pulse_count"], 2)
        self.assertEqual([step["kind"] for step in result["steps"]], ["rest", "pulse", "rest", "pulse", "rest"])
        first = result["pulses"][0]
        self.assertAlmostEqual(first["duration_s"], 2.0)
        self.assertAlmostEqual(first["instantaneous_voltage_change_V"], 0.1)
        self.assertAlmostEqual(first["pulse_end_voltage_change_V"], 0.25)
        self.assertAlmostEqual(first["steady_state_voltage_change_V"], 0.2)
        self.assertAlmostEqual(first["relaxation_voltage_change_V"], -0.05)
        self.assertIsNone(first["diffusion_coefficient_m2_s"])
        self.assertIsNone(result["diffusion_coefficient_m2_s"])

    def test_accepts_csv(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "gitt.csv"
            path.write_text("time_s,current_A,voltage_V\n" + "\n".join(
                "{time_s},{current_A},{voltage_V}".format(**point) for point in self.points
            ), encoding="utf-8")
            result = analyze_gitt(path, current_threshold_A=0.01)
        self.assertEqual(result["pulse_count"], 2)

    def test_rejects_invalid_time_threshold_values_units_and_small_input(self):
        reversed_time = [dict(point) for point in self.points]
        reversed_time[4]["time_s"] = reversed_time[3]["time_s"]
        with self.assertRaises(ValueError):
            analyze_gitt(reversed_time, current_threshold_A=0.01)
        with self.assertRaises(ValueError):
            analyze_gitt(self.points, current_threshold_A=0.0)
        nonfinite = [dict(point) for point in self.points]
        nonfinite[0]["voltage_V"] = float("nan")
        with self.assertRaises(ValueError):
            analyze_gitt(nonfinite, current_threshold_A=0.01)
        with self.assertRaises(ValueError):
            analyze_gitt(self.points, current_threshold_A=0.01, units={"time_s": "h", "current_A": "A", "voltage_V": "V"})
        with self.assertRaises(ValueError):
            analyze_gitt(self.points[:5], current_threshold_A=0.01)


if __name__ == "__main__":
    unittest.main()
