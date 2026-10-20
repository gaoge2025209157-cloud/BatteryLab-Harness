import json
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from electrochem_harness.evaluation import (
    EVALUATION_VERSION,
    build_fixtures,
    run_suite,
)


class EvaluationSuiteTests(unittest.TestCase):
    """整个套件只能跑一次：setUpClass 里跑完，其余用例只读结果。"""

    @classmethod
    def setUpClass(cls):
        cls._temp = tempfile.TemporaryDirectory()
        root = Path(cls._temp.name)
        cls.fixtures_dir = root / "fixtures"
        cls.report = run_suite(
            PROJECT_ROOT, work_dir=root / "work", fixtures_dir=cls.fixtures_dir
        )

    @classmethod
    def tearDownClass(cls):
        cls._temp.cleanup()

    def test_all_twelve_cases_pass(self):
        failures = [
            "{} {}：{}".format(case.case_id, case.title, case.detail)
            for case in self.report.cases
            if not case.passed
        ]
        self.assertEqual(failures, [], "\n".join(failures))
        self.assertEqual(len(self.report.cases), 12)

    def test_metrics_meet_the_release_targets(self):
        metrics = self.report.metrics

        self.assertEqual(metrics["blocking_detection_rate"], 1.0)
        self.assertEqual(metrics["unauthorized_execution_rate"], 0.0)
        self.assertEqual(metrics["issue_recognition_rate"], 1.0)
        self.assertEqual(metrics["false_positive_rate"], 0.0)
        self.assertEqual(metrics["artifact_completeness"], 1.0)
        self.assertEqual(metrics["repeat_hash_consistency"], 1.0)
        self.assertTrue(metrics["core_metric_consistent"])
        self.assertEqual(metrics["manual_fix_count"], 0)

    def test_unapproved_run_never_executes(self):
        case = next(item for item in self.report.cases if item.case_id == "E-10")

        self.assertEqual(case.observation.outcome, "unauthorized")
        self.assertIsNone(case.observation.state)

    def test_repeat_runs_share_one_core_hash(self):
        case = next(item for item in self.report.cases if item.case_id == "E-12")

        self.assertTrue(case.passed)
        self.assertEqual(len(case.observation.core_hash), 64)

    def test_report_is_json_serialisable(self):
        payload = self.report.to_dict()
        restored = json.loads(json.dumps(payload, ensure_ascii=False))

        self.assertEqual(restored["evaluation_version"], EVALUATION_VERSION)
        self.assertEqual(restored["summary"]["cases"], 12)
        self.assertEqual(len(restored["cases"]), 12)

    def test_markdown_lists_every_case_and_metric(self):
        text = self.report.to_markdown()

        for case in self.report.cases:
            self.assertIn(case.case_id, text)
        for label in ("阻断类案例拦截率", "未批准执行率", "重复运行哈希一致率"):
            self.assertIn(label, text)

    def test_fixtures_are_synthetic_and_stable(self):
        first = build_fixtures(self.fixtures_dir)
        second = build_fixtures(self.fixtures_dir)

        self.assertEqual(first, second)
        self.assertIn("raw_4col", first)
        self.assertTrue((self.fixtures_dir / "README.md").is_file())
        for path in first.values():
            self.assertTrue(path.is_file())
            self.assertNotIn("真实", path.read_text(encoding="utf-8")[:50])


class FixtureContentTests(unittest.TestCase):
    def test_unit_variant_uses_microamp_millivolt_minute(self):
        with tempfile.TemporaryDirectory() as temp:
            fixtures = build_fixtures(Path(temp))
            header = fixtures["raw_4col_units"].read_text(encoding="utf-8").splitlines()[0]

            self.assertIn("uA", header)
            self.assertIn("mV", header)
            self.assertIn("min", header)

    def test_time_regression_fixture_really_goes_backwards(self):
        with tempfile.TemporaryDirectory() as temp:
            fixtures = build_fixtures(Path(temp))
            rows = fixtures["raw_4col_time_regression"].read_text(encoding="utf-8").splitlines()[1:]
            times = [float(row.split(",")[1]) for row in rows]

            self.assertNotEqual(times, sorted(times))


if __name__ == "__main__":
    unittest.main()
