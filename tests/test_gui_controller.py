import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from electrochem_harness.gui_controller import (
    STEP_TITLES,
    SixStepWizard,
    WizardError,
    WizardStep,
)
from electrochem_harness.origin_adapter import OriginStatus
from electrochem_harness.workflow import ApprovalRequired


def write_capacity_curve(path):
    path.write_text(
        "测试时间/h,比容量/mAh/g,电压/V\n"
        "0,0,1.0\n"
        "1,10,2.0\n"
        "2,0,2.1\n"
        "3,9,1.0\n"
        "4,0,1.1\n"
        "5,5,2.0\n",
        encoding="utf-8",
    )


def form(source, output, *, network=False, origin=False):
    return {
        "input_file": str(source),
        "output_dir": str(output),
        "battery_system": "Li-S",
        "active_material": "S/C",
        "cell_type": "coin cell",
        "counter_electrode": "Li",
        "test_current": "0.2C",
        "temperature": "25 C",
        "normalization_basis": "硫质量",
        "search_literature": network,
        "use_origin": origin,
        "max_literature": 2,
    }


NETWORK_RESPONSE = {
    "verified_count": 0,
    "records": [],
    "limitations": ["mocked for deterministic test"],
}


class WizardStepOrderTests(unittest.TestCase):
    def test_every_step_has_a_user_facing_title(self):
        self.assertEqual(
            [step for step in WizardStep],
            [
                WizardStep.DATA,
                WizardStep.PREFLIGHT,
                WizardStep.PLAN,
                WizardStep.APPROVAL,
                WizardStep.EXECUTE,
                WizardStep.RESULTS,
            ],
        )
        for step in WizardStep:
            self.assertIn(step, STEP_TITLES)
            self.assertTrue(STEP_TITLES[step].strip())

    def test_plan_cannot_be_reviewed_before_preflight(self):
        with tempfile.TemporaryDirectory() as temp:
            wizard = SixStepWizard(PROJECT_ROOT)
            with self.assertRaises(WizardError):
                wizard.review_plan()

    def test_preflight_requires_a_form(self):
        wizard = SixStepWizard(PROJECT_ROOT)
        with self.assertRaises(WizardError):
            wizard.run_preflight()

    def test_blocking_preflight_stops_the_wizard_at_step_two(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "garbage.csv"
            source.write_text("这不是蓝电数据\n", encoding="utf-8")
            wizard = SixStepWizard(PROJECT_ROOT)
            wizard.edit_form(form(source, root / "result"))

            view = wizard.run_preflight()

            self.assertTrue(view.blocked)
            self.assertTrue(view.blocking)
            self.assertEqual(wizard.step, WizardStep.PREFLIGHT)
            with self.assertRaises(WizardError):
                wizard.review_plan()

    def test_happy_path_walks_all_six_steps(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "curve.csv"
            write_capacity_curve(source)
            wizard = SixStepWizard(PROJECT_ROOT)

            wizard.edit_form(form(source, root / "result"))
            self.assertEqual(wizard.step, WizardStep.DATA)

            view = wizard.run_preflight()
            self.assertFalse(view.blocked)
            self.assertEqual(view.summary["mode"], "specific_capacity_curve")
            self.assertEqual(wizard.step, WizardStep.PREFLIGHT)

            plan = wizard.review_plan()
            self.assertEqual(wizard.step, WizardStep.PLAN)
            self.assertIn("plan_hash", plan)
            self.assertIn("build_scientific_report", plan["tools"])

            approval = wizard.request_approval()
            self.assertEqual(wizard.step, WizardStep.APPROVAL)
            self.assertEqual(approval["required"], ["local_analysis", "formal_output"])
            self.assertFalse(wizard.can_start)

            wizard.approve(["local_analysis", "formal_output"])
            self.assertTrue(wizard.can_start)

            state = wizard.start()

            self.assertEqual(state, "completed")
            self.assertEqual(wizard.step, WizardStep.RESULTS)
            self.assertEqual(wizard.results.state, "completed")

    def test_results_group_report_and_audit_for_a_completed_run(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "curve.csv"
            write_capacity_curve(source)
            wizard = SixStepWizard(PROJECT_ROOT)
            wizard.edit_form(form(source, root / "result"))
            wizard.run_preflight()
            wizard.review_plan()
            wizard.request_approval()
            wizard.approve(["local_analysis", "formal_output"])
            wizard.start()

            results = wizard.results
            report_names = [item.name for item in results.report]
            self.assertIn("关键参数报告.md", report_names)
            self.assertIn("科学计算标准.json", report_names)
            self.assertTrue(all(item.available for item in results.report), results.to_dict())
            self.assertTrue(all(item.available for item in results.audit), results.to_dict())
            self.assertEqual(
                [item.name for item in results.audit],
                ["plan.json", "preflight.json", "approval.json", "events.jsonl", "run_record.json"],
            )

    def test_disabled_optional_groups_are_marked_not_required(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "curve.csv"
            write_capacity_curve(source)
            wizard = SixStepWizard(PROJECT_ROOT)
            wizard.edit_form(form(source, root / "result"))
            wizard.run_preflight()
            wizard.review_plan()
            wizard.request_approval()
            wizard.approve(["local_analysis", "formal_output"])
            wizard.start()

            results = wizard.results
            self.assertTrue(all(not item.required for item in results.evidence))
            self.assertTrue(all(not item.required for item in results.origin))


class WizardApprovalGateTests(unittest.TestCase):
    def test_execution_is_impossible_before_approval(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "curve.csv"
            write_capacity_curve(source)
            wizard = SixStepWizard(PROJECT_ROOT)
            wizard.edit_form(form(source, root / "result"))
            wizard.run_preflight()
            wizard.review_plan()

            with self.assertRaises(ApprovalRequired):
                wizard.start()

    def test_partial_approval_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "curve.csv"
            write_capacity_curve(source)
            wizard = SixStepWizard(PROJECT_ROOT)
            wizard.edit_form(form(source, root / "result"))
            wizard.run_preflight()
            wizard.review_plan()
            wizard.request_approval()

            with self.assertRaises(ApprovalRequired) as caught:
                wizard.approve(["local_analysis"])

            self.assertIn("formal_output", str(caught.exception))
            self.assertFalse(wizard.can_start)

    def test_network_plan_requires_the_network_scope(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "curve.csv"
            write_capacity_curve(source)
            wizard = SixStepWizard(PROJECT_ROOT)
            wizard.edit_form(form(source, root / "result", network=True))
            wizard.run_preflight()
            wizard.review_plan()
            approval = wizard.request_approval()

            self.assertIn("network_access", approval["required"])
            with self.assertRaises(ApprovalRequired):
                wizard.approve(["local_analysis", "formal_output"])

            with patch(
                "electrochem_harness.production_registry.search_crossref",
                return_value=NETWORK_RESPONSE,
            ):
                wizard.approve(["local_analysis", "formal_output", "network_access"])
                self.assertEqual(wizard.start(), "completed")

    def test_unknown_scope_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "curve.csv"
            write_capacity_curve(source)
            wizard = SixStepWizard(PROJECT_ROOT)
            wizard.edit_form(form(source, root / "result"))
            wizard.run_preflight()
            wizard.review_plan()
            wizard.request_approval()

            with self.assertRaises(WizardError):
                wizard.set_scopes(["local_analysis", "formal_output", "root_access"])

    def test_editing_the_form_after_approval_returns_to_step_one(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "curve.csv"
            write_capacity_curve(source)
            wizard = SixStepWizard(PROJECT_ROOT)
            wizard.edit_form(form(source, root / "result"))
            wizard.run_preflight()
            wizard.review_plan()
            wizard.request_approval()
            wizard.set_scopes(["local_analysis", "formal_output"])

            wizard.back_to_form()

            self.assertEqual(wizard.step, WizardStep.DATA)
            self.assertFalse(wizard.can_start)
            self.assertEqual(wizard.scopes, ())

    def test_cancel_is_recorded_as_cancelled_not_failed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "curve.csv"
            write_capacity_curve(source)
            wizard = SixStepWizard(PROJECT_ROOT)
            wizard.edit_form(form(source, root / "result"))
            wizard.run_preflight()
            wizard.review_plan()
            wizard.request_approval()
            wizard.approve(["local_analysis", "formal_output"])
            wizard.cancel("用户在第 5 步取消")

            self.assertEqual(wizard.start(), "cancelled")
            self.assertEqual(wizard.results.state, "cancelled")


class WizardOriginAndRetryTests(unittest.TestCase):
    def test_origin_failure_is_shown_as_a_degradation_not_a_lost_run(self):
        def failing_launcher(*args, **kwargs):
            raise RuntimeError("Origin 未安装")

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "curve.csv"
            write_capacity_curve(source)
            wizard = SixStepWizard(PROJECT_ROOT, origin_launcher=failing_launcher)
            wizard.edit_form(form(source, root / "result", origin=True))
            wizard.run_preflight()
            wizard.review_plan()
            wizard.request_approval()
            wizard.approve(["local_analysis", "formal_output"])

            state = wizard.start()

            self.assertEqual(state, "completed_with_warnings")
            self.assertEqual(len(wizard.results.degradations), 1)
            self.assertIn("build_origin_project", wizard.results.degradations[0])
            self.assertTrue(
                any(item.name == "关键参数报告.md" and item.available for item in wizard.results.report)
            )

    def test_origin_success_makes_the_origin_group_available(self):
        def fake_launcher(job_path, project_root, **kwargs):
            output = Path(job_path).parent
            for name in ("电化学分析.opju", "充放电曲线.png", "循环性能.png"):
                (output / name).write_bytes(b"origin-stub")
            (output / "origin_status.json").write_text(
                json.dumps({"ok": True, "origin_release": "2026b"}), encoding="utf-8"
            )
            return OriginStatus(ok=True, origin_release="2026b", originpro_version="1.2.3")

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "curve.csv"
            write_capacity_curve(source)
            wizard = SixStepWizard(PROJECT_ROOT, origin_launcher=fake_launcher)
            wizard.edit_form(form(source, root / "result", origin=True))
            wizard.run_preflight()
            wizard.review_plan()
            wizard.request_approval()
            wizard.approve(["local_analysis", "formal_output"])

            self.assertEqual(wizard.start(), "completed")
            self.assertTrue(all(item.available for item in wizard.results.origin))
            self.assertEqual(wizard.results.degradations, ())

    def test_retry_creates_a_new_audited_run_instead_of_reviving_the_failed_one(self):
        def failing_launcher(*args, **kwargs):
            raise RuntimeError("Origin 未安装")

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "curve.csv"
            write_capacity_curve(source)
            wizard = SixStepWizard(PROJECT_ROOT, origin_launcher=failing_launcher)
            wizard.edit_form(form(source, root / "result", origin=True))
            wizard.run_preflight()
            wizard.review_plan()
            wizard.request_approval()
            wizard.approve(["local_analysis", "formal_output"])
            wizard.start()
            first_run = wizard.controller.controlled_run.run_dir

            state = wizard.retry()
            second_run = wizard.controller.controlled_run.run_dir

            self.assertEqual(state, "completed_with_warnings")
            self.assertNotEqual(first_run, second_run)
            self.assertTrue(first_run.is_dir(), "the failed run must be preserved")
            self.assertTrue(
                (first_run / "events.jsonl").is_file(),
                "the failed run keeps its own event chain",
            )
            events = (second_run / "events.jsonl").read_text(encoding="utf-8")
            self.assertIn("retry_requested", events)
            self.assertIn(str(first_run), events)
            self.assertTrue(any("retried" in item for item in wizard.history))

    def test_retry_requires_a_previous_execution(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "curve.csv"
            write_capacity_curve(source)
            wizard = SixStepWizard(PROJECT_ROOT)
            wizard.edit_form(form(source, root / "result"))
            wizard.run_preflight()

            with self.assertRaises(WizardError):
                wizard.retry()

    def test_two_runs_of_the_same_input_share_a_plan_hash(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "curve.csv"
            write_capacity_curve(source)
            wizard = SixStepWizard(PROJECT_ROOT)
            wizard.edit_form(form(source, root / "result"))
            wizard.run_preflight()
            first_hash = wizard.prepared.plan.plan_hash
            wizard.run_preflight()
            second_hash = wizard.prepared.plan.plan_hash

            self.assertEqual(first_hash, second_hash)


if __name__ == "__main__":
    unittest.main()
