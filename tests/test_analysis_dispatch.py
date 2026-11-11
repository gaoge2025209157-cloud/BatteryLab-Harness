from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from electrochem_harness_v2.analysis_dispatch import (
    analyze_experiment,
    extract_replicate_metric,
    summarize_analysis_replicates,
)
from electrochem_harness_v2.csv_importer import GcdCsvImporter
from electrochem_harness_v2.report import write_report


CV_POINTS = [
    {"potential_V": 0.0, "current_A": 0.0},
    {"potential_V": 1.0, "current_A": 1.0},
    {"potential_V": 2.0, "current_A": 3.0},
    {"potential_V": 3.0, "current_A": 1.0},
    {"potential_V": 2.0, "current_A": -1.0},
    {"potential_V": 1.0, "current_A": -2.0},
    {"potential_V": 0.0, "current_A": -0.5},
]

EIS_POINTS = [
    {"frequency_Hz": 10000.0, "z_real_ohm": 5.0, "z_imag_ohm": 0.2},
    {"frequency_Hz": 1000.0, "z_real_ohm": 6.0, "z_imag_ohm": -2.0},
    {"frequency_Hz": 100.0, "z_real_ohm": 8.0, "z_imag_ohm": -5.0},
    {"frequency_Hz": 10.0, "z_real_ohm": 12.0, "z_imag_ohm": -4.0},
    {"frequency_Hz": 1.0, "z_real_ohm": 16.0, "z_imag_ohm": -4.0},
    {"frequency_Hz": 0.1, "z_real_ohm": 20.0, "z_imag_ohm": -4.0},
]

GITT_POINTS = [
    {"time_s": 0.0, "current_A": 0.0, "voltage_V": 3.00},
    {"time_s": 1.0, "current_A": 0.0, "voltage_V": 3.00},
    {"time_s": 2.0, "current_A": 0.1, "voltage_V": 3.10},
    {"time_s": 3.0, "current_A": 0.1, "voltage_V": 3.20},
    {"time_s": 4.0, "current_A": 0.0, "voltage_V": 3.18},
    {"time_s": 5.0, "current_A": 0.0, "voltage_V": 3.16},
]


class AnalysisDispatchTests(unittest.TestCase):
    def test_routes_cv_eis_and_gitt_with_explicit_conditions(self):
        cases = [
            ("cv", CV_POINTS, {"scan_rate": 0.5}, "scan_rate_V_s", 0.5),
            ("eis", EIS_POINTS, {"tail_fraction": 0.5}, "point_count", 6),
            ("gitt", GITT_POINTS, {"current_threshold_A": 0.01}, "current_threshold_A", 0.01),
        ]
        for method, source, conditions, result_key, expected in cases:
            with self.subTest(method=method):
                result = analyze_experiment(method, source, conditions)
                self.assertEqual(
                    set(result),
                    {"schema_version", "analysis_type", "metadata", "analysis", "limitations", "quality_flags"},
                )
                self.assertEqual(result["analysis_type"], method)
                self.assertEqual(result["analysis"][result_key], expected)
                self.assertEqual(result["metadata"]["conditions"], conditions)

    def test_rejects_unknown_method_and_requires_only_gitt_threshold(self):
        with self.assertRaisesRegex(ValueError, "Unknown analysis method"):
            analyze_experiment("raman", object())

        cv = analyze_experiment("cv", CV_POINTS, {})
        self.assertIsNone(cv["analysis"]["scan_rate_V_s"])
        self.assertTrue(
            all(row["integrated_charge_C"] is None for row in cv["analysis"]["sweeps"])
        )
        eis = analyze_experiment("eis", EIS_POINTS, {})
        self.assertEqual(eis["analysis"]["point_count"], len(EIS_POINTS))
        with self.assertRaisesRegex(ValueError, "requires"):
            analyze_experiment("gitt", GITT_POINTS, {})

    def test_gcd_dispatch_uses_existing_importer_without_changing_legacy_api(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "gcd.csv"
            path.write_text(
                "time/s,voltage/V,specific capacity/mAh/g,current/A,cycle,direction\n"
                "0,3.0,0,0.1,1,charge\n"
                "1,3.5,10,0.1,1,charge\n"
                "2,3.4,0,-0.1,1,discharge\n"
                "3,3.0,9,-0.1,1,discharge\n",
                encoding="utf-8",
            )
            legacy = GcdCsvImporter().read(path, conditions={"active_material_mass_mg": 1.0})
            dispatched = analyze_experiment("GCD", path, {"active_material_mass_mg": 1.0})
        self.assertIn("gcd_summary", legacy.analysis)
        self.assertEqual(dispatched["analysis_type"], "gcd")
        self.assertEqual(dispatched["analysis"]["gcd_summary"], legacy.analysis["gcd_summary"])
        self.assertEqual(dispatched["metadata"]["sha256"], legacy.metadata.sha256)

    def test_extracts_and_summarizes_only_same_name_same_unit_metrics(self):
        results = [
            {"analysis": {"latest_average_discharge_voltage_V": value}}
            for value in (3.0, 3.2, 3.4)
        ]
        row = extract_replicate_metric(results[0], "latest_average_discharge_voltage_V")
        self.assertEqual(row, {
            "value": 3.0,
            "metric": "latest_average_discharge_voltage_V",
            "unit": "V",
        })
        summary = summarize_analysis_replicates(results, "latest_average_discharge_voltage_V")
        self.assertEqual(summary["n"], 3)
        self.assertAlmostEqual(summary["mean"], 3.2)
        self.assertEqual(summary["unit"], "V")

        mixed = [
            {"analysis": {"result": {"value": 1.0, "unit": "V"}}},
            {"analysis": {"result": {"value": 2.0, "unit": "mV"}}},
        ]
        with self.assertRaisesRegex(ValueError, "mix different units"):
            summarize_analysis_replicates(mixed, "result")

    def test_report_renders_each_non_gcd_analysis_without_gcd_capacity_conclusion(self):
        analyses = [
            ("cv", analyze_experiment("cv", CV_POINTS, {"scan_rate": 0.5}), "CV 扫描段确定性摘要"),
            ("eis", analyze_experiment("eis", EIS_POINTS, {"tail_fraction": 0.5}), "EIS 描述量确定性摘要"),
            ("gitt", analyze_experiment("gitt", GITT_POINTS, {"current_threshold_A": 0.01}), "GITT 脉冲确定性摘要"),
            ("replicates", {
                "schema_version": "1.0",
                "analysis_type": "replicates",
                "metadata": {},
                "analysis": summarize_analysis_replicates(
                    [{"analysis": {"peak_separation_V": value}} for value in (0.8, 0.9, 1.0)],
                    "peak_separation_V",
                ),
                "limitations": [],
                "quality_flags": [],
            }, "同名同单位指标的重复统计摘要"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            for method, analysis, marker in analyses:
                with self.subTest(method=method):
                    path = Path(directory) / (method + ".html")
                    write_report(path, {"material_system": "generic"}, [], [], analysis=analysis)
                    html = path.read_text(encoding="utf-8")
                    self.assertIn(marker, html)
                    self.assertIn("不能自动推断反应、等效电路或扩散系数", html)
                    self.assertIn("不把 GCD 容量声明套用于", html)
                    self.assertNotIn("表征当前循环的电荷收支", html)


if __name__ == "__main__":
    unittest.main()
