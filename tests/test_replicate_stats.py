from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from electrochem_harness_v2.replicate_stats import analyze_replicates, summarize_replicates


class ReplicateStatsTests(unittest.TestCase):
    def test_calculates_descriptive_statistics_for_one_metric_and_unit(self):
        rows = [
            {"value": 1.0, "metric": "capacity", "unit": "mAh/g"},
            {"value": 2.0, "metric": "capacity", "unit": "mAh/g"},
            {"value": 3.0, "metric": "capacity", "unit": "mAh/g"},
        ]
        result = summarize_replicates(rows)
        self.assertEqual(result["schema_version"], "1.0")
        self.assertEqual(result["n"], 3)
        self.assertEqual(result["mean"], 2.0)
        self.assertEqual(result["sample_standard_deviation"], 1.0)
        self.assertEqual(result["coefficient_of_variation_percent"], 50.0)
        self.assertEqual(result["minimum"], 1.0)
        self.assertEqual(result["maximum"], 3.0)
        self.assertFalse(result["inferential_statistics_performed"])
        self.assertIsNone(result["significance_conclusion"])

    def test_marks_two_replicates_insufficient(self):
        result = analyze_replicates([{"value": 2.0}, {"value": 4.0}], metric="retention", unit="%")
        self.assertEqual(result["replicate_sufficiency"], "insufficient_n_lt_3")
        self.assertIn("insufficient_replicates_n_lt_3", result["quality_flags"])

    def test_accepts_csv_and_rejects_mixed_or_invalid_data(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "replicates.csv"
            path.write_text("value,metric,unit\n1.0,capacity,mAh/g\n2.0,capacity,mAh/g\n3.0,capacity,mAh/g\n", encoding="utf-8")
            self.assertEqual(summarize_replicates(path)["n"], 3)
        with self.assertRaises(ValueError):
            summarize_replicates([
                {"value": 1, "metric": "capacity", "unit": "mAh/g"},
                {"value": 2, "metric": "capacity", "unit": "Ah/kg"},
            ])
        with self.assertRaises(ValueError):
            summarize_replicates([
                {"value": 1, "metric": "capacity", "unit": "mAh/g"},
                {"value": 2, "metric": "voltage", "unit": "mAh/g"},
            ])
        with self.assertRaises(ValueError):
            summarize_replicates([{"value": 1}, {"value": float("inf")}], metric="capacity", unit="mAh/g")
        with self.assertRaises(ValueError):
            summarize_replicates([{"value": 1}], metric="capacity", unit="mAh/g")

    def test_zero_mean_has_no_coefficient_of_variation(self):
        result = summarize_replicates(
            [{"value": -1}, {"value": 0}, {"value": 1}], metric="offset", unit="V"
        )
        self.assertIsNone(result["coefficient_of_variation_percent"])
        self.assertIn("coefficient_of_variation_undefined_zero_mean", result["quality_flags"])


if __name__ == "__main__":
    unittest.main()
