from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from electrochem_harness_v2.csv_importer import GcdCsvImporter


class AdvancedGcdDataTests(unittest.TestCase):
    def _read(self, content: str, **kwargs):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "curve.csv"
            path.write_text(content, encoding="utf-8")
            return GcdCsvImporter().read(path, **kwargs)

    def test_normalizes_units_and_keeps_physical_source_rows_after_preamble(self):
        result = self._read(
            "Instrument export\n\n"
            "Time/min;Voltage/mV;Current/uA;Specific Capacity/Ah/g\n"
            "0;3000;1000;0\n"
            "1;3500;1000;0.01\n"
        )
        self.assertEqual(result.metadata.delimiter, ";")
        self.assertEqual(result.points[0]["source_row"], 4)
        self.assertEqual(result.points[1]["time"], 60.0)
        self.assertEqual(result.points[0]["voltage"], 3.0)
        self.assertEqual(result.points[0]["current"], 0.001)
        self.assertEqual(result.points[1]["capacity"], 10.0)
        self.assertTrue(result.analysis["unit_normalization"]["time"]["explicit"])

    def test_integrates_current_per_segment_without_overwriting_exported_capacity(self):
        result = self._read(
            "Time/s,Voltage/V,Current/mA,Specific Capacity/mAh/g,Cycle,Step,Status\n"
            "0,3.0,1,0,1,1,Charge\n"
            "1800,3.5,1,40,1,1,Charge\n"
            "3600,4.0,1,80,1,1,Charge\n"
            "3601,4.0,-1,0,1,2,Discharge\n"
            "5401,3.5,-1,45,1,2,Discharge\n"
            "7201,3.0,-1,90,1,2,Discharge\n",
            active_material_mass_mg=10,
        )
        charge, discharge = result.analysis["segments"]
        self.assertEqual(charge["specific_capacity_mAh_g"], 80.0)
        self.assertAlmostEqual(charge["integrated_specific_capacity_mAh_g"], 100.0)
        self.assertAlmostEqual(charge["integration_difference_mAh_g"], 20.0)
        self.assertEqual(discharge["specific_capacity_mAh_g"], 90.0)
        self.assertAlmostEqual(discharge["integrated_specific_capacity_mAh_g"], 100.0)
        self.assertEqual(result.analysis["gcd_summary"]["integrated_segment_count"], 2)

    def test_explicit_cycle_step_and_direction_take_segmentation_precedence(self):
        result = self._read(
            "Time/s,Voltage/V,Current/mA,Specific Capacity/mAh/g,Cycle,Step,Direction\n"
            "0,3.0,1,0,7,1,charge\n"
            "1,3.1,1,1,7,1,charge\n"
            "2,3.1,-1,1,7,2,discharge\n"
            "3,3.0,-1,2,7,2,discharge\n"
        )
        self.assertEqual(result.analysis["segmentation_method"], "explicit_cycle_step_direction")
        self.assertEqual([item["direction_candidate"] for item in result.analysis["segments"]], ["charge", "discharge"])
        self.assertEqual([item["cycle_candidate"] for item in result.analysis["segments"]], ["7", "7"])
        self.assertTrue(all(item["confidence"] == "high" for item in result.analysis["segments"]))

    def test_capacity_reset_then_voltage_direction_is_the_conservative_fallback(self):
        reset = self._read(
            "time,capacity,voltage\n"
            "0,0,2\n1,10,3\n2,0,3\n3,8,2\n4,0,2\n"
        )
        self.assertEqual(reset.analysis["segmentation_method"], "capacity_reset")
        self.assertEqual(reset.analysis["segmentation_confidence"], "medium")

        voltage = self._read(
            "time,capacity,voltage\n"
            "0,0,2\n1,1,3\n2,2,4\n3,3,3\n4,4,2\n"
        )
        self.assertEqual(voltage.analysis["segmentation_method"], "voltage_direction")
        self.assertEqual(voltage.analysis["segmentation_confidence"], "low")
        self.assertTrue(any("low confidence" in item for item in voltage.analysis["warnings"]))

    def test_missing_mass_leaves_exported_capacity_and_marks_integration(self):
        result = self._read(
            "Time/s,Specific Capacity/mAh/g,Voltage/V,Current/mA\n"
            "0,0,3,1\n3600,75,4,1\n"
        )
        segment = result.analysis["segments"][0]
        self.assertEqual(segment["specific_capacity_mAh_g"], 75.0)
        self.assertIsNone(segment["integrated_specific_capacity_mAh_g"])
        self.assertEqual(segment["integration_status"], "missing_active_material_mass")
        self.assertTrue(any("mass is missing" in item for item in result.analysis["warnings"]))

    def test_reversed_time_disables_only_affected_integration(self):
        result = self._read(
            "Time/s,Specific Capacity/mAh/g,Voltage/V,Current/mA\n"
            "0,0,3,1\n2,1,3.5,1\n1,2,4,1\n",
            conditions={"active_material_mass_mg": 10},
        )
        self.assertEqual(result.analysis["repeated_or_reversed_time_pairs"], 1)
        self.assertEqual(result.analysis["segments"][0]["integration_status"], "non_increasing_time")
        self.assertIsNone(result.analysis["segments"][0]["integrated_specific_capacity_mAh_g"])

    def test_legacy_bare_headers_remain_readable_but_units_are_unverified(self):
        result = self._read("time,capacity,voltage\n0,0,3\n1,2,4\n")
        self.assertEqual(result.points[1]["time"], 1.0)
        self.assertEqual(result.points[1]["capacity"], 2.0)
        self.assertEqual(result.points[1]["voltage"], 4.0)
        self.assertFalse(result.analysis["unit_normalization"]["time"]["explicit"])
        self.assertTrue(any("unit-unverified" in item for item in result.analysis["warnings"]))

    def test_cycle_column_does_not_raise_current_inferred_segment_confidence(self):
        result = self._read(
            "Time/s,Voltage/V,Current/mA,Specific Capacity/mAh/g,Cycle\n"
            "0,3.0,1,0,1\n"
            "1,4.0,1,10,1\n"
            "2,4.0,-1,0,1\n"
            "3,3.0,-1,9,1\n"
        )
        self.assertEqual(result.analysis["segmentation_confidence"], "high")
        self.assertEqual(
            [segment["confidence"] for segment in result.analysis["segments"]],
            ["medium", "medium"],
        )
        self.assertTrue(
            all(segment["direction_inference_method"] == "current_sign" for segment in result.analysis["segments"])
        )
        self.assertTrue(
            all(
                segment["current_sign_convention"] == "candidate_positive_charge_negative_discharge"
                for segment in result.analysis["segments"]
            )
        )
        self.assertTrue(any("candidate convention" in warning for warning in result.analysis["warnings"]))

    def test_explicit_direction_current_conflict_is_warned_and_not_origin_eligible(self):
        result = self._read(
            "Time/s,Voltage/V,Current/mA,Specific Capacity/mAh/g,Direction\n"
            "0,3.0,-1,0,charge\n"
            "1,4.0,-1,10,charge\n"
        )
        segment = result.analysis["segments"][0]
        self.assertEqual(segment["direction_candidate"], "charge")
        self.assertEqual(segment["confidence"], "medium")
        self.assertTrue(segment["explicit_current_conflict"])
        self.assertFalse(segment["origin_eligible"])
        self.assertTrue(any("conflicts" in warning for warning in segment["warnings"]))

    def test_integration_summary_distinguishes_total_attempted_and_eligible_segments(self):
        result = self._read(
            "Time/s,Voltage/V,Current/mA,Specific Capacity/mAh/g,Direction\n"
            "0,3.0,1,0,charge\n"
            "1,4.0,1,10,charge\n"
            "2,4.0,-1,0,discharge\n"
            "1,3.0,-1,9,discharge\n",
            active_material_mass_mg=10,
        )
        summary = result.analysis["gcd_summary"]
        self.assertEqual(summary["total_segment_count"], 2)
        self.assertEqual(summary["integration_attempted_segment_count"], 2)
        self.assertEqual(summary["integration_eligible_segment_count"], 1)
        self.assertEqual(summary["integrated_segment_count"], 1)

    def test_file_import_streams_without_path_read_bytes(self):
        with patch.object(Path, "read_bytes", side_effect=AssertionError("full byte read")):
            result = self._read(
                "Time/s,Specific Capacity/mAh/g,Voltage/V\n"
                "0,0,3\n1,1,4\n"
            )
        self.assertEqual(result.analysis["row_count"], 2)

    def test_rejects_nonfinite_current_and_mass(self):
        with self.assertRaises(ValueError):
            self._read(
                "Time/s,Specific Capacity/mAh/g,Voltage/V,Current/mA\n"
                "0,0,3,Inf\n1,1,4,1\n"
            )
        with self.assertRaises(ValueError):
            self._read(
                "Time/s,Specific Capacity/mAh/g,Voltage/V,Current/mA\n"
                "0,0,3,1\n1,1,4,1\n",
                active_material_mass_mg=float("nan"),
            )


if __name__ == "__main__":
    unittest.main()
