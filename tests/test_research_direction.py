from __future__ import annotations

import unittest

from electrochem_harness_v2.research_direction import build_research_direction


class ResearchDirectionTests(unittest.TestCase):
    def test_prioritizes_data_integrity_stability_and_polarization_for_realistic_feature_summary(self):
        direction = build_research_direction({
            "negative_voltage_count": 377,
            "repeated_or_reversed_time_pairs": 287024,
            "gcd_summary": {
                "complete_cycle_count": 21,
                "first_complete_discharge_capacity_mAh_g": 3627.9,
                "latest_complete_discharge_capacity_mAh_g": 1770.5,
                "latest_capacity_retention_percent": 48.8,
                "latest_polarization_voltage_V": 0.572,
                "latest_coulombic_efficiency_percent": 96.71,
            },
        })
        self.assertIn("仪器步骤", direction["headline"])
        self.assertTrue(any("48.80%" in item for item in direction["observations"]))
        self.assertTrue(any("极化" in item for item in direction["risks"]))
        self.assertEqual(direction["actions"][0]["priority"], "P0｜核对仪器步骤与分段")
        self.assertIn("XPS", direction["actions"][3]["decision_evidence"])

    def test_uses_entered_active_material_mass_without_default_mass_warning(self):
        direction = build_research_direction({
            "gcd_summary": {"first_complete_discharge_capacity_mAh_g": 1100.0},
        }, {"active_material_mass_mg": 3.5})
        self.assertTrue(any("3.500 mg" in item for item in direction["observations"]))
        self.assertNotIn("容量口径", direction["headline"])

        direction = build_research_direction({"gcd_summary": {}})
        self.assertIn("不构成反应机理证明", direction["scope"])
        self.assertNotIn("mAh", direction["headline"])
        self.assertEqual(len(direction["actions"]), 4)


if __name__ == "__main__":
    unittest.main()
