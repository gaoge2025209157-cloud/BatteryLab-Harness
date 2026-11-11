from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from electrochem_harness_v2.csv_importer import GcdCsvImporter
from electrochem_harness_v2.origin_data import (
    _origin_candidate_segments,
    _reconstruct_cycles,
    prepare_origin_tables,
)


class OriginDataTests(unittest.TestCase):
    def test_prepares_tables_without_rewriting_source_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.csv"
            source.write_text("time,capacity,voltage\n0,0,2\n1,10,3\n2,0,3\n3,8,2\n4,0,2\n", encoding="utf-8")
            imported = GcdCsvImporter().read(source)
            outputs = prepare_origin_tables(imported, root / "origin")
            self.assertTrue(outputs["curves"].is_file())
            self.assertTrue(outputs["summary"].is_file())
            curves = outputs["curves"].read_text(encoding="utf-8-sig")
            summary = outputs["summary"].read_text(encoding="utf-8-sig")
            self.assertIn("cycle,direction,specific_capacity_mAh_g,voltage_V", curves)
            self.assertIn("1,charge,10.0,3.0", curves)
            self.assertIn("1,discharge,8.0,2.0", curves)
            self.assertIn("cycle,charge_specific_capacity_mAh_g,discharge_specific_capacity_mAh_g,coulombic_efficiency_percent,complete", summary)
            self.assertIn("1,10.0,8.0,80.0,true", summary)
            self.assertEqual(source.read_text(encoding="utf-8").splitlines()[0], "time,capacity,voltage")

    def test_origin_complete_cycle_accepts_all_gcd_closure_rules(self):
        segments = [
            {
                "segment_id": "segment-1",
                "start_source_row": 2,
                "end_source_row": 3,
                "direction_candidate": "charge",
                "specific_capacity_mAh_g": 10.0,
                "confidence": "high",
                "origin_eligible": True,
                "closed_by_capacity_reset": False,
                "closed_by_explicit_boundary": True,
                "closed_by_current_sign": False,
            },
            {
                "segment_id": "segment-2",
                "start_source_row": 4,
                "end_source_row": 5,
                "direction_candidate": "discharge",
                "specific_capacity_mAh_g": 8.0,
                "confidence": "medium",
                "origin_eligible": True,
                "closed_by_capacity_reset": False,
                "closed_by_explicit_boundary": False,
                "closed_by_current_sign": True,
            },
        ]
        cycles, _ = _reconstruct_cycles(_origin_candidate_segments(segments))
        self.assertEqual(len(cycles), 1)
        self.assertTrue(cycles[0]["complete"])
        self.assertEqual(cycles[0]["coulombic_efficiency_percent"], 80.0)

    def test_filtered_unknown_or_rejected_segment_prevents_cross_gap_pairing(self):
        for omitted in (
            {
                "segment_id": "segment-2",
                "start_source_row": 4,
                "end_source_row": 5,
                "direction_candidate": "unknown",
                "specific_capacity_mAh_g": 1.0,
                "confidence": "low",
                "origin_eligible": False,
            },
            {
                "segment_id": "segment-2",
                "start_source_row": 4,
                "end_source_row": 5,
                "direction_candidate": "charge",
                "specific_capacity_mAh_g": 1.0,
                "confidence": "high",
                "origin_eligible": True,
                "review_status": "rejected",
            },
        ):
            with self.subTest(omitted=omitted["direction_candidate"], rejected=omitted.get("review_status")):
                segments = [
                    {
                        "segment_id": "segment-1",
                        "start_source_row": 2,
                        "end_source_row": 3,
                        "direction_candidate": "charge",
                        "specific_capacity_mAh_g": 10.0,
                        "confidence": "high",
                        "origin_eligible": True,
                        "closed_by_capacity_reset": True,
                    },
                    omitted,
                    {
                        "segment_id": "segment-3",
                        "start_source_row": 6,
                        "end_source_row": 7,
                        "direction_candidate": "discharge",
                        "specific_capacity_mAh_g": 8.0,
                        "confidence": "high",
                        "origin_eligible": True,
                        "closed_by_capacity_reset": True,
                    },
                ]
                cycles, labels = _reconstruct_cycles(_origin_candidate_segments(segments))
                self.assertEqual(len(cycles), 1)
                self.assertFalse(cycles[0]["complete"])
                self.assertNotEqual(labels[0][0], labels[1][0])

    def test_conflicting_explicit_current_segment_is_excluded_from_origin(self):
        segments = [
            {
                "direction_candidate": "charge",
                "confidence": "medium",
                "origin_eligible": False,
                "explicit_current_conflict": True,
            }
        ]
        self.assertEqual(_origin_candidate_segments(segments), [])


if __name__ == "__main__":
    unittest.main()
