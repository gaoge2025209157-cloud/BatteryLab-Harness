import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from electrochem_harness.analysis import analyze_cycles, load_cycling_csv
from electrochem_harness.guidance import run_harness
from electrochem_harness.knowledge import ExperienceStore, KnowledgeBase
from electrochem_harness.models import ExperimentContext


HEADERS = ["cycle", "time_s", "current_mA", "voltage_V"]


def write_csv(path, rows, headers=HEADERS):
    with Path(path).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerows(rows)


class AnalysisTests(unittest.TestCase):
    def test_analyzes_two_cycles_and_normalizes_by_mass(self):
        rows = [
            [1, 0, 1.0, 3.0],
            [1, 3600, 1.0, 4.0],
            [1, 3601, 0.0, 4.0],
            [1, 3602, -1.0, 4.0],
            [1, 7202, -1.0, 2.8],
            [2, 7203, 1.0, 3.0],
            [2, 10803, 1.0, 4.0],
            [2, 10804, 0.0, 4.0],
            [2, 10805, -0.9, 4.0],
            [2, 14405, -0.9, 2.8],
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cycling.csv"
            write_csv(path, rows)
            points = load_cycling_csv(path)
            metrics = analyze_cycles(points, active_mass_mg=10.0)

        self.assertEqual([item.cycle for item in metrics], [1, 2])
        self.assertAlmostEqual(metrics[0].charge_capacity_mAh, 1.0, delta=0.001)
        self.assertAlmostEqual(metrics[0].discharge_capacity_mAh, 1.0, delta=0.001)
        self.assertAlmostEqual(metrics[0].specific_discharge_capacity_mAh_g, 100.0, delta=0.1)
        self.assertAlmostEqual(metrics[0].coulombic_efficiency, 1.0, delta=0.002)
        self.assertAlmostEqual(metrics[1].capacity_retention, 0.9, delta=0.002)
        self.assertGreater(metrics[0].average_charge_voltage_V, metrics[0].average_discharge_voltage_V)

    def test_missing_required_column_names_the_column(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.csv"
            write_csv(path, [[1, 0, 1.0]], headers=["cycle", "time_s", "current_mA"])
            with self.assertRaisesRegex(ValueError, "voltage_V"):
                load_cycling_csv(path)

    def test_missing_mass_keeps_raw_capacity_and_omits_specific_capacity(self):
        rows = [[1, 0, 1.0, 3.0], [1, 3600, 1.0, 4.0]]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cycling.csv"
            write_csv(path, rows)
            metrics = analyze_cycles(load_cycling_csv(path))

        self.assertGreater(metrics[0].charge_capacity_mAh, 0)
        self.assertIsNone(metrics[0].specific_discharge_capacity_mAh_g)

    def test_constant_voltage_current_is_integrated(self):
        from electrochem_harness.models import CyclingPoint

        points = [
            CyclingPoint(1, 0.0, 2.0, 4.0, 2),
            CyclingPoint(1, 1800.0, 2.0, 4.0, 3),
        ]
        metric = analyze_cycles(points)[0]

        self.assertAlmostEqual(metric.charge_capacity_mAh, 1.0)
        self.assertAlmostEqual(metric.charge_energy_mWh, 4.0)

    def test_negative_voltage_energy_is_retained_instead_of_clamped(self):
        from electrochem_harness.models import CyclingPoint

        points = [
            CyclingPoint(1, 0.0, -1.0, -0.2, 2),
            CyclingPoint(1, 3600.0, -1.0, -0.2, 3),
        ]
        metric = analyze_cycles(points)[0]

        self.assertAlmostEqual(metric.discharge_capacity_mAh, 1.0)
        self.assertAlmostEqual(metric.discharge_energy_mWh, -0.2)
        self.assertAlmostEqual(metric.average_discharge_voltage_V, -0.2)

    def test_nonfinite_value_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nonfinite.csv"
            write_csv(path, [[1, 0, "nan", 3.0]])
            with self.assertRaisesRegex(ValueError, "Non-finite"):
                load_cycling_csv(path)


class KnowledgeAndGuidanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.rules_path = self.root / "rules.json"
        self.experiences_path = self.root / "experiences.jsonl"
        self.rules_path.write_text(
            json.dumps(
                [
                    {
                        "id": "rule-low-ce",
                        "metric": "coulombic_efficiency",
                        "operator": "<",
                        "threshold": 0.95,
                        "conditions": {"experiment_type": "galvanostatic_cycling"},
                        "claim": "库仑效率偏低。",
                        "action": "复核电流符号、截止条件与装配一致性。",
                        "source": "test-rule",
                        "confidence": 0.65,
                    }
                ],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _low_ce_csv(self):
        path = self.root / "low_ce.csv"
        write_csv(
            path,
            [
                [1, 0, 1.0, 3.0],
                [1, 3600, 1.0, 4.0],
                [1, 3601, 0.0, 4.0],
                [1, 3602, -0.8, 4.0],
                [1, 7202, -0.8, 3.0],
            ],
        )
        return path

    def test_rule_recommendation_contains_evidence_and_source(self):
        context = ExperimentContext(
            system_type="half_cell",
            electrolyte="待填",
            anode="Li",
            atmosphere="Ar",
            active_mass_mg=10.0,
        )
        report = run_harness(
            self._low_ce_csv(),
            context,
            KnowledgeBase(self.rules_path, self.experiences_path),
        )

        recommendation = next(item for item in report.recommendations if item.source_id == "rule-low-ce")
        self.assertIn("coulombic_efficiency", recommendation.evidence)
        self.assertEqual(recommendation.source, "test-rule")
        self.assertTrue(recommendation.requires_confirmation)

    def test_non_monotonic_time_is_blocked_before_analysis(self):
        path = self.root / "bad_time.csv"
        write_csv(path, [[1, 0, 1.0, 3.0], [1, 10, 1.0, 3.1], [1, 5, -1.0, 3.0]])
        report = run_harness(
            path,
            ExperimentContext(system_type="half_cell"),
            KnowledgeBase(self.rules_path, self.experiences_path),
        )

        self.assertEqual(report.metrics, [])
        self.assertTrue(any(issue.code == "non_monotonic_time" and issue.blocking for issue in report.quality_issues))

    def test_negative_voltage_incomplete_cycle_and_cycle_jump_are_reported(self):
        path = self.root / "quality_cases.csv"
        write_csv(
            path,
            [
                [1, 0, 1.0, 0.1],
                [1, 10, 1.0, -0.1],
                [3, 20, 1.0, 0.2],
                [3, 30, -1.0, 0.1],
            ],
        )
        report = run_harness(
            path,
            ExperimentContext(system_type="half_cell"),
            KnowledgeBase(self.rules_path, self.experiences_path),
        )
        codes = [issue.code for issue in report.quality_issues]

        self.assertIn("negative_voltage", codes)
        self.assertIn("cycle_number_jump", codes)
        self.assertIn("incomplete_cycle", codes)

    def test_validated_experience_is_project_scoped_and_feedback_changes_confidence(self):
        store = ExperienceStore(self.experiences_path)
        experience = store.record(
            experiment_type="galvanostatic_cycling",
            system_type="half_cell",
            observation="首圈库仑效率偏低",
            action="复核装配压力一致性",
            outcome="重复性改善",
            evidence="batch-A vs batch-B",
            validated=True,
        )

        matches = store.find(experiment_type="galvanostatic_cycling", system_type="half_cell", min_confidence=0.5)
        self.assertEqual(len(matches), 1)
        self.assertEqual(store.find("galvanostatic_cycling", "full_cell", 0.0), [])
        updated = store.apply_feedback(experience.id, effective=False, evidence="batch-C 未复现")
        self.assertLess(updated.confidence, experience.confidence)
        self.assertIn("batch-C 未复现", updated.feedback_evidence)

    def test_end_to_end_report_is_json_serializable_and_lists_missing_context(self):
        report = run_harness(
            self._low_ce_csv(),
            ExperimentContext(system_type="half_cell", active_mass_mg=10.0),
            KnowledgeBase(self.rules_path, self.experiences_path),
        )
        payload = report.to_dict()

        json.dumps(payload, ensure_ascii=False)
        self.assertEqual(payload["status"], "warning")
        self.assertIn("electrolyte", payload["missing_context"])
        self.assertGreater(len(payload["conclusions"]), 0)


if __name__ == "__main__":
    unittest.main()



class LandExportAdapterTests(unittest.TestCase):
    def test_loads_land_csv_with_chinese_headers_and_ampere_current(self):
        from electrochem_harness.land import LandImportConfig, load_land_export

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "land_export.csv"
            path.write_text(
                "循环号,测试时间,电流(A),电压(V)\n"
                "1,00:00:00,0.001,3.0\n"
                "1,01:00:00,0.001,4.0\n"
                "1,01:00:01,0,4.0\n"
                "1,01:00:02,-0.001,4.0\n"
                "1,02:00:02,-0.001,3.0\n",
                encoding="utf-8-sig",
            )

            result = load_land_export(path, LandImportConfig())

        self.assertEqual(len(result.points), 5)
        self.assertEqual(result.points[0].cycle, 1)
        self.assertEqual(result.points[1].time_s, 3600.0)
        self.assertAlmostEqual(result.points[0].current_mA, 1.0)
        self.assertEqual(result.detected_columns["cycle"], "循环号")
        self.assertEqual(result.detected_units["current"], "A")

    def test_loads_tab_delimited_land_text_and_reverses_current_direction(self):
        from electrochem_harness.land import LandImportConfig, load_land_export

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "land_export.txt"
            path.write_text(
                "Cycle ID\tTotal Time(Sec)\tCurrent(mA)\tVoltage(V)\n"
                "1\t0\t-1\t3.0\n"
                "1\t3600\t-1\t4.0\n"
                "1\t3601\t1\t3.9\n",
                encoding="utf-8",
            )

            result = load_land_export(
                path, LandImportConfig(charge_current_sign="negative")
            )

        self.assertEqual(result.points[0].current_mA, 1.0)
        self.assertEqual(result.points[2].current_mA, -1.0)
        self.assertEqual(result.delimiter, "\t")
        self.assertTrue(result.metadata()["current_sign_reversed"])
        self.assertEqual(result.metadata()["charge_current_sign"], "negative")

    def test_converts_microamp_and_millivolt_units(self):
        from electrochem_harness.land import LandImportConfig, load_land_export

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "small_units.csv"
            path.write_text(
                "循环号,时间(s),电流(uA),电压(mV)\n"
                "1,0,1000,3000\n1,1,-500,2500\n",
                encoding="utf-8",
            )
            result = load_land_export(path, LandImportConfig())

        self.assertEqual(result.detected_units["current"], "uA")
        self.assertEqual(result.detected_units["voltage"], "mV")
        self.assertAlmostEqual(result.points[0].current_mA, 1.0)
        self.assertAlmostEqual(result.points[1].current_mA, -0.5)
        self.assertAlmostEqual(result.points[0].voltage_V, 3.0)

    def test_skips_land_metadata_rows_before_header(self):
        from electrochem_harness.land import LandImportConfig, load_land_export

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "land_export.csv"
            path.write_text(
                "设备,LAND CT2001A\n"
                "导出时间,2026-10-12\n"
                "循环序号,总时间(s),电流(mA),电压(V)\n"
                "1,0,1,3.0\n"
                "1,1,1,3.1\n",
                encoding="gb18030",
            )

            result = load_land_export(path, LandImportConfig())

        self.assertEqual(result.header_row, 3)
        self.assertEqual(len(result.points), 2)

    def test_rejects_excel_and_reports_conversion_instead_of_guessing(self):
        from electrochem_harness.land import LandImportConfig, load_land_export

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "land_export.xlsx"
            path.write_bytes(b"not-an-xlsx")
            with self.assertRaisesRegex(ValueError, "CSV.*TXT"):
                load_land_export(path, LandImportConfig())

    def test_land_cli_writes_report_and_import_metadata(self):
        from electrochem_harness.land_cli import main as land_main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "land.csv"
            output = root / "report.json"
            rules = root / "rules.json"
            experiences = root / "experiences.jsonl"
            source.write_text(
                "循环号,测试时间,电流(mA),电压(V)\n"
                "1,0,1,3.0\n"
                "1,3600,1,4.0\n"
                "1,3601,-1,3.9\n"
                "1,7201,-1,3.0\n",
                encoding="utf-8",
            )
            rules.write_text("[]", encoding="utf-8")

            exit_code = land_main(
                [
                    str(source),
                    "--output", str(output),
                    "--rules", str(rules),
                    "--experiences", str(experiences),
                    "--system-type", "half_cell",
                    "--electrolyte", "Li3ScCl6",
                    "--anode", "Li",
                    "--atmosphere", "Ar",
                    "--active-mass-mg", "10",
                ]
            )
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["import_metadata"]["detected_columns"]["cycle"], "循环号")
        self.assertEqual(payload["report"]["status"], "ok")
        self.assertEqual(len(payload["report"]["metrics"]), 1)



class LandSpecificCapacityCurveTests(unittest.TestCase):
    def test_reconstructs_complete_and_partial_cycles_from_capacity_resets(self):
        from electrochem_harness.land_curve import analyze_land_capacity_curve

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "curve.csv"
            path.write_text(
                "测试时间/h,比容量/mAh/g,电压/V\n"
                "0.00,0,1.2\n0.01,100,0.5\n0.01,0,0.6\n"
                "0.02,120,2.5\n0.02,0,2.4\n"
                "0.03,110,0.5\n0.03,0,0.6\n"
                "0.04,100,2.4\n0.04,0,2.3\n"
                "0.05,20,1.8\n",
                encoding="gb18030",
            )

            result = analyze_land_capacity_curve(path)

        self.assertEqual(result["import_metadata"]["mode"], "specific_capacity_curve")
        self.assertEqual(
            result["import_metadata"]["cycle_mapping_convention"],
            "initial_discharge_unpaired_then_charge_discharge_pairs",
        )
        self.assertEqual(
            result["import_metadata"]["normalization_basis"],
            "source_exported_specific_capacity_denominator_unverified",
        )
        self.assertEqual(result["report"]["initial_discharge_capacity_mAh_g"], 100.0)
        self.assertEqual(len(result["report"]["cycles"]), 2)
        self.assertTrue(result["report"]["cycles"][0]["complete"])
        self.assertAlmostEqual(result["report"]["cycles"][0]["coulombic_efficiency"], 110 / 120)
        self.assertFalse(result["report"]["cycles"][1]["complete"])
        self.assertIsNone(result["report"]["cycles"][1]["coulombic_efficiency"])

    def test_curve_mode_reports_negative_voltage_and_repeated_times(self):
        from electrochem_harness.land_curve import analyze_land_capacity_curve

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "curve.csv"
            path.write_text(
                "测试时间/h,比容量/mAh/g,电压/V\n"
                "0.00,0,1.0\n0.00,10,-0.1\n",
                encoding="utf-8",
            )
            result = analyze_land_capacity_curve(path)

        codes = {item["code"] for item in result["report"]["quality_issues"]}
        self.assertIn("negative_voltage", codes)
        self.assertIn("repeated_rounded_time", codes)



class ScientificReportTests(unittest.TestCase):
    def test_capacity_weighted_voltage_and_dominant_plateau(self):
        from electrochem_harness.land_curve import _voltage_metrics

        metrics = _voltage_metrics(
            [(0.0, 0.0, 1.00), (0.1, 50.0, 1.00), (0.2, 100.0, 1.02), (0.3, 120.0, 2.00)],
            bin_width_V=0.05,
        )

        self.assertAlmostEqual(metrics["average_voltage_V"], 1.085, delta=0.01)
        self.assertAlmostEqual(metrics["dominant_plateau_voltage_V"], 1.005, delta=0.03)
        self.assertGreater(metrics["dominant_plateau_capacity_fraction"], 0.8)

    def test_concise_report_contains_key_table_and_defers_unscoped_literature_claim(self):
        from electrochem_harness.sci_report import render_concise_markdown

        payload = {
            "report": {
                "status": "warning",
                "initial_discharge_capacity_mAh_g": 90.0,
                "cycles": [{
                    "cycle": 1,
                    "charge_specific_capacity_mAh_g": 100.0,
                    "discharge_specific_capacity_mAh_g": 95.0,
                    "coulombic_efficiency": 0.95,
                    "capacity_retention": 1.0,
                    "average_charge_voltage_V": 2.1,
                    "average_discharge_voltage_V": 1.8,
                    "charge_plateau_voltage_V": 2.0,
                    "discharge_plateau_voltage_V": 1.7,
                    "complete": True,
                }],
                "quality_issues": [],
            }
        }
        text = render_concise_markdown(payload, material=None, cell_configuration=None, rate=None, temperature=None)

        self.assertIn("充电比容量", text)
        self.assertIn("95.00%", text)
        self.assertIn("文献对比暂缓", text)
        self.assertNotIn("国际领先", text)
