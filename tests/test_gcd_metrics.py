from __future__ import annotations

import unittest

from electrochem_harness_v2.gcd_metrics import analyze_gcd_metrics


class GcdMetricTests(unittest.TestCase):
    def test_calculates_capacity_weighted_voltage_polarization_reversibility_and_retention(self):
        segments = [
            {"segment_id": "segment-1", "direction_candidate": "charge", "specific_capacity_mAh_g": 100.0, "closed_by_capacity_reset": True, "start_source_row": 2, "end_source_row": 4},
            {"segment_id": "segment-2", "direction_candidate": "discharge", "specific_capacity_mAh_g": 90.0, "closed_by_capacity_reset": True, "start_source_row": 5, "end_source_row": 7},
            {"segment_id": "segment-3", "direction_candidate": "charge", "specific_capacity_mAh_g": 95.0, "closed_by_capacity_reset": True, "start_source_row": 8, "end_source_row": 10},
            {"segment_id": "segment-4", "direction_candidate": "discharge", "specific_capacity_mAh_g": 72.0, "closed_by_capacity_reset": True, "start_source_row": 11, "end_source_row": 13},
        ]
        points = (
            {"source_row": 2, "capacity": 0.0, "voltage": 2.0}, {"source_row": 3, "capacity": 50.0, "voltage": 3.0}, {"source_row": 4, "capacity": 100.0, "voltage": 4.0},
            {"source_row": 5, "capacity": 0.0, "voltage": 3.0}, {"source_row": 6, "capacity": 45.0, "voltage": 2.0}, {"source_row": 7, "capacity": 90.0, "voltage": 1.0},
            {"source_row": 8, "capacity": 0.0, "voltage": 2.0}, {"source_row": 9, "capacity": 47.5, "voltage": 3.0}, {"source_row": 10, "capacity": 95.0, "voltage": 4.0},
            {"source_row": 11, "capacity": 0.0, "voltage": 3.0}, {"source_row": 12, "capacity": 36.0, "voltage": 2.0}, {"source_row": 13, "capacity": 72.0, "voltage": 1.0},
        )
        result = analyze_gcd_metrics(points, segments)
        self.assertEqual(len(result["cycles"]), 2)
        self.assertAlmostEqual(result["cycles"][0]["average_charge_voltage_V"], 3.0)
        self.assertAlmostEqual(result["cycles"][0]["average_discharge_voltage_V"], 2.0)
        self.assertAlmostEqual(result["cycles"][0]["polarization_voltage_V"], 1.0)
        self.assertAlmostEqual(result["cycles"][0]["coulombic_efficiency_percent"], 90.0)
        self.assertAlmostEqual(result["cycles"][1]["capacity_retention_percent"], 80.0)
        self.assertEqual(result["summary"]["complete_cycle_count"], 2)
        self.assertEqual(result["summary"]["maximum_complete_discharge_capacity_mAh_g"], 90.0)
        self.assertEqual(result["summary"]["maximum_complete_discharge_cycle"], 1)


if __name__ == "__main__":
    unittest.main()
