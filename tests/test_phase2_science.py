import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from electrochem_harness.ground_truth import (
    GroundTruthSuite,
    evaluate_ground_truth,
    scientific_release_ready,
)
from electrochem_harness.replicates import (
    ReplicateCell,
    ReplicateGroup,
    analyze_replicates,
    write_replicate_outputs,
)
from electrochem_harness.scientific_standard import (
    SCIENTIFIC_STANDARD_VERSION,
    scientific_standard_hash,
    scientific_standard_manifest,
)


class ScientificStandardTests(unittest.TestCase):
    def test_manifest_freezes_all_core_metric_definitions(self):
        manifest = scientific_standard_manifest()

        self.assertEqual(SCIENTIFIC_STANDARD_VERSION, "1.0.0")
        self.assertEqual(manifest["version"], "1.0.0")
        self.assertEqual(len(scientific_standard_hash()), 64)
        required = {
            "charge_capacity_mAh",
            "discharge_capacity_mAh",
            "specific_capacity_mAh_g",
            "coulombic_efficiency",
            "capacity_retention",
            "average_voltage_V",
            "dominant_plateau_voltage_V",
        }
        self.assertTrue(required.issubset(manifest["metrics"]))
        self.assertEqual(manifest["conventions"]["charge_current_sign"], "positive")
        self.assertEqual(manifest["conventions"]["retention_reference"], "first_complete_discharge_cycle")
        self.assertEqual(manifest["metrics"]["dominant_plateau_voltage_V"]["bin_width_V"], 0.05)

    def test_manifest_hash_changes_if_scientific_rule_changes(self):
        manifest = scientific_standard_manifest()
        changed = json.loads(json.dumps(manifest))
        changed["conventions"]["charge_current_sign"] = "negative"

        self.assertNotEqual(scientific_standard_hash(manifest), scientific_standard_hash(changed))


class GroundTruthTests(unittest.TestCase):
    def _suite(self, reviewers=()):
        return GroundTruthSuite.from_dict(
            {
                "suite_id": "phase2-core-v1",
                "standard_version": SCIENTIFIC_STANDARD_VERSION,
                "standard_hash": scientific_standard_hash(),
                "review_status": "approved" if reviewers else "draft",
                "reviewers": list(reviewers),
                "cases": [
                    {
                        "case_id": "manual-case-1",
                        "description": "independently calculated reference values",
                        "expected": {
                            "cycle_1.charge_capacity_mAh": {
                                "value": 1.0,
                                "absolute_tolerance": 0.001,
                            },
                            "cycle_1.coulombic_efficiency": {
                                "value": 0.95,
                                "relative_tolerance": 0.01,
                            },
                        },
                    }
                ],
            }
        )

    def test_absolute_and_relative_tolerances_are_audited(self):
        result = evaluate_ground_truth(
            self._suite(),
            {
                "manual-case-1": {
                    "cycle_1": {
                        "charge_capacity_mAh": 1.0005,
                        "coulombic_efficiency": 0.955,
                    }
                }
            },
        )

        self.assertTrue(result.numeric_passed)
        self.assertEqual(result.total_checks, 2)
        self.assertEqual(result.passed_checks, 2)
        self.assertEqual(result.case_results[0].checks[0].tolerance_kind, "absolute")
        self.assertEqual(result.standard_hash, scientific_standard_hash())

    def test_out_of_tolerance_value_fails_with_delta(self):
        result = evaluate_ground_truth(
            self._suite(),
            {
                "manual-case-1": {
                    "cycle_1": {
                        "charge_capacity_mAh": 1.02,
                        "coulombic_efficiency": 0.95,
                    }
                }
            },
        )

        self.assertFalse(result.numeric_passed)
        failed = next(check for check in result.case_results[0].checks if not check.passed)
        self.assertAlmostEqual(failed.delta, 0.02)
        self.assertIn("charge_capacity_mAh", failed.metric_path)

    def test_scientific_release_gate_requires_numeric_pass_and_j_c_approval(self):
        values = {
            "manual-case-1": {
                "cycle_1": {
                    "charge_capacity_mAh": 1.0,
                    "coulombic_efficiency": 0.95,
                }
            }
        }
        draft = evaluate_ground_truth(self._suite(), values)
        approved = evaluate_ground_truth(self._suite(("J", "C")), values)

        self.assertFalse(scientific_release_ready(draft))
        self.assertTrue(scientific_release_ready(approved))

    def test_suite_rejects_wrong_or_tampered_standard_identity(self):
        payload = self._suite().to_dict()
        payload["standard_hash"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "standard hash"):
            GroundTruthSuite.from_dict(payload)


class ReplicateStatisticsTests(unittest.TestCase):
    @staticmethod
    def _cell(cell_id, values, condition="same-condition", excluded=False, reason=""):
        cycles = []
        for cycle, capacity in enumerate(values, start=1):
            cycles.append(
                {
                    "cycle": cycle,
                    "discharge_specific_capacity_mAh_g": capacity,
                    "charge_specific_capacity_mAh_g": capacity / 0.98,
                    "coulombic_efficiency": 0.98,
                    "capacity_retention": capacity / values[0],
                    "complete": True,
                }
            )
        return ReplicateCell(
            cell_id=cell_id,
            condition_fingerprint=condition,
            cycles=tuple(cycles),
            excluded=excluded,
            exclusion_reason=reason,
        )

    def test_three_cells_produce_mean_sample_sd_sem_ci_and_raw_points(self):
        group = ReplicateGroup(
            group_id="batch-a",
            condition_fingerprint="same-condition",
            cells=(
                self._cell("A", [100.0, 90.0]),
                self._cell("B", [102.0, 92.0]),
                self._cell("C", [98.0, 88.0]),
            ),
        )

        result = analyze_replicates(group)
        cycle_1 = result.metric("discharge_specific_capacity_mAh_g", 1)

        self.assertEqual(result.interpretation, "replicated")
        self.assertEqual(cycle_1.n, 3)
        self.assertAlmostEqual(cycle_1.mean, 100.0)
        self.assertAlmostEqual(cycle_1.sample_sd, 2.0)
        self.assertAlmostEqual(cycle_1.sem, 2.0 / math.sqrt(3))
        self.assertGreater(cycle_1.ci95_high, cycle_1.mean)
        self.assertEqual([point.cell_id for point in cycle_1.raw_points], ["A", "B", "C"])

    def test_single_cell_is_explicitly_exploratory(self):
        result = analyze_replicates(
            ReplicateGroup("single", "same-condition", (self._cell("A", [100.0]),))
        )

        self.assertEqual(result.interpretation, "exploratory")
        self.assertTrue(any("不能证明重复性" in warning for warning in result.warnings))
        metric = result.metric("discharge_specific_capacity_mAh_g", 1)
        self.assertIsNone(metric.sample_sd)
        self.assertIsNone(metric.ci95_low)

    def test_robust_outlier_is_flagged_but_not_automatically_excluded(self):
        cells = tuple(
            self._cell(name, [value])
            for name, value in zip(("A", "B", "C", "D", "E"), (99.0, 100.0, 100.5, 101.0, 180.0))
        )
        result = analyze_replicates(ReplicateGroup("outlier", "same-condition", cells))
        metric = result.metric("discharge_specific_capacity_mAh_g", 1)

        self.assertEqual(metric.n, 5)
        flagged = [point for point in metric.raw_points if point.outlier_flag]
        self.assertEqual([point.cell_id for point in flagged], ["E"])
        self.assertIn("E", metric.included_cell_ids)

    def test_manual_exclusion_requires_reason_and_preserves_audit_point(self):
        with self.assertRaisesRegex(ValueError, "exclusion reason"):
            self._cell("B", [100.0], excluded=True)

        group = ReplicateGroup(
            "excluded",
            "same-condition",
            (
                self._cell("A", [100.0]),
                self._cell("B", [200.0], excluded=True, reason="事前规则：装配后开路电压不合格"),
                self._cell("C", [102.0]),
            ),
        )
        result = analyze_replicates(group)
        metric = result.metric("discharge_specific_capacity_mAh_g", 1)

        self.assertEqual(metric.n, 2)
        excluded = next(point for point in metric.raw_points if point.cell_id == "B")
        self.assertFalse(excluded.included)
        self.assertEqual(excluded.exclusion_reason, "事前规则：装配后开路电压不合格")

    def test_condition_mismatch_is_rejected_before_statistics(self):
        group = ReplicateGroup(
            "mixed",
            "same-condition",
            (self._cell("A", [100.0]), self._cell("B", [100.0], condition="other")),
        )
        with self.assertRaisesRegex(ValueError, "condition fingerprint"):
            analyze_replicates(group)

    def test_outputs_include_json_csv_and_markdown(self):
        group = ReplicateGroup(
            "batch-a",
            "same-condition",
            (self._cell("A", [100.0]), self._cell("B", [102.0]), self._cell("C", [98.0])),
        )
        with tempfile.TemporaryDirectory() as tmp:
            paths = write_replicate_outputs(analyze_replicates(group), Path(tmp))
            payload = json.loads(paths["json"].read_text(encoding="utf-8"))
            markdown = paths["report"].read_text(encoding="utf-8")
            svg = paths["plot"].read_text(encoding="utf-8")

        self.assertEqual(set(paths), {"json", "csv", "report", "plot"})
        self.assertEqual(payload["standard_version"], SCIENTIFIC_STANDARD_VERSION)
        self.assertIn("原始散点", markdown)
        self.assertIn("样本标准差", markdown)
        self.assertIn("<circle", svg)
        self.assertIn('data-role="sd-error-bar"', svg)


if __name__ == "__main__":
    unittest.main()



class Phase2RepositoryIntegrationTests(unittest.TestCase):
    def test_repository_ground_truth_suite_passes_numeric_gate_but_awaits_review(self):
        from electrochem_harness.ground_truth import run_ground_truth_suite

        result = run_ground_truth_suite(PROJECT_ROOT / "standards" / "ground_truth_v1.json")

        self.assertTrue(result.numeric_passed)
        self.assertFalse(scientific_release_ready(result))
        self.assertEqual(result.review_status, "draft")
        self.assertGreaterEqual(result.total_checks, 12)

    def test_replicate_manifest_loads_real_curve_files_and_writes_outputs(self):
        from electrochem_harness.replicates import run_replicate_manifest

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cells = []
            for cell_id, capacity in (("A", 100), ("B", 102), ("C", 98)):
                path = root / (cell_id + ".csv")
                path.write_text(
                    "测试时间/h,比容量/mAh/g,电压/V\n"
                    "0,0,1\n1,{0},2\n2,0,2\n3,{0},1\n4,0,1\n".format(capacity),
                    encoding="utf-8",
                )
                cells.append({"cell_id": cell_id, "input_file": path.name})
            manifest = root / "replicates.json"
            manifest.write_text(
                json.dumps(
                    {
                        "group_id": "batch-a",
                        "experiment_metadata": {"system": "test", "rate": "1C"},
                        "cells": cells,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result, paths = run_replicate_manifest(manifest, root / "out")

        self.assertEqual(result.interpretation, "replicated")
        self.assertAlmostEqual(
            result.metric("discharge_specific_capacity_mAh_g", 1).mean, 100.0
        )
        self.assertEqual(set(paths), {"json", "csv", "report", "plot"})

    def test_scientific_bundle_records_frozen_standard_and_single_cell_boundary(self):
        from electrochem_harness.sci_report import create_scientific_bundle

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "curve.csv"
            source.write_text(
                "测试时间/h,比容量/mAh/g,电压/V\n"
                "0,0,1\n1,100,2\n2,0,2\n3,98,1\n4,0,1\n",
                encoding="utf-8",
            )
            paths = create_scientific_bundle(source, root / "out")
            payload = json.loads(paths["json"].read_text(encoding="utf-8"))
            report = paths["report"].read_text(encoding="utf-8")
            standard = json.loads(paths["standard"].read_text(encoding="utf-8"))

        self.assertEqual(payload["scientific_standard"]["version"], SCIENTIFIC_STANDARD_VERSION)
        self.assertEqual(standard["identity"]["sha256"], scientific_standard_hash())
        self.assertIn("单个电池", report)
        self.assertIn("探索性", report)
