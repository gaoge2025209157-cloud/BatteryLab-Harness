from __future__ import annotations

import unittest

from electrochem_harness_v2.gcd_metrics import build_codex_feature_packet


class CodexFeatureBoundaryTests(unittest.TestCase):
    def test_codex_packet_contains_features_but_never_raw_rows_or_points(self):
        analysis = {
            "metadata": {"sha256": "abc", "source_name": "large.csv", "column_mapping": {"time": "time", "capacity": "capacity", "voltage": "voltage"}},
            "analysis": {
                "row_count": 100000,
                "voltage_range_V": [-0.2, 3.1],
                "negative_voltage_count": 4,
                "repeated_or_reversed_time_pairs": 9,
                "segments": [{"segment_id": "segment-1", "specific_capacity_mAh_g": 100, "direction_candidate": "discharge"}],
                "cycles": [{"cycle": 1, "discharge_specific_capacity_mAh_g": 90, "average_discharge_voltage_V": 1.2}],
                "gcd_summary": {"latest_capacity_retention_percent": 90},
                "points": [{"source_row": 2, "capacity": 99, "voltage": 1.0}],
                "rows": [["raw", "row"]],
            },
        }
        packet = build_codex_feature_packet(analysis)
        flattened = str(packet)
        self.assertIn("latest_capacity_retention_percent", flattened)
        self.assertIn("complete_cycles", packet)
        self.assertNotIn("points", packet)
        self.assertNotIn("rows", packet)
        self.assertNotIn("raw", flattened)
        self.assertNotIn("source_row", flattened)


if __name__ == "__main__":
    unittest.main()
