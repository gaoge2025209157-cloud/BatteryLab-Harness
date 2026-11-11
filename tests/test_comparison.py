from __future__ import annotations

import unittest

from electrochem_harness_v2.comparison import compare_metric
from electrochem_harness_v2.models import KnowledgeClaim


class ComparisonTests(unittest.TestCase):
    def _claim(self, status="approved"):
        return KnowledgeClaim.new(
            project_id="project-1",
            source_id="source-1",
            claim_type="performance",
            text="Reference capacity",
            metric_id="discharge_specific_capacity_mAh_g",
            value=100.0,
            unit="mAh/g",
            conditions={
                "cathode": "NCM88",
                "electrolyte": "LiCl",
                "temperature_C": 60,
                "normalization_basis": "cathode active mass",
            },
            evidence_span_ids=["span-1"],
            status=status,
        )

    def test_candidate_cannot_produce_a_formal_comparison(self):
        outcome = compare_metric(
            observed_value=110.0,
            observed_unit="mAh/g",
            observed_conditions={},
            claim=self._claim("candidate"),
        )
        self.assertEqual(outcome.comparability, "not_approved")
        self.assertIsNone(outcome.decision)

    def test_missing_required_condition_blocks_comparison(self):
        outcome = compare_metric(
            observed_value=110.0,
            observed_unit="mAh/g",
            observed_conditions={"cathode": "NCM88", "electrolyte": "LiCl", "temperature_C": 60},
            claim=self._claim(),
        )
        self.assertEqual(outcome.comparability, "insufficient_context")
        self.assertIsNone(outcome.decision)

    def test_unit_mismatch_blocks_comparison(self):
        outcome = compare_metric(
            observed_value=110.0,
            observed_unit="Wh/kg",
            observed_conditions={
                "cathode": "NCM88",
                "electrolyte": "LiCl",
                "temperature_C": 60,
                "normalization_basis": "cathode active mass",
            },
            claim=self._claim(),
        )
        self.assertEqual(outcome.comparability, "not_comparable")
        self.assertIsNone(outcome.decision)

    def test_matching_conditions_produce_numeric_difference(self):
        outcome = compare_metric(
            observed_value=110.0,
            observed_unit="mAh/g",
            observed_conditions={
                "cathode": "NCM88",
                "electrolyte": "LiCl",
                "temperature_C": 60,
                "normalization_basis": "cathode active mass",
            },
            claim=self._claim(),
        )
        self.assertEqual(outcome.comparability, "comparable")
        self.assertEqual(outcome.decision, "above_reference")
        self.assertEqual(outcome.absolute_difference, 10.0)


if __name__ == "__main__":
    unittest.main()
