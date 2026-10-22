import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from electrochem_harness.workflow import ApprovalRequired, WorkflowState


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


def values(source, output, *, network=False, origin=False):
    return {
        "input_file": str(source),
        "output_dir": str(output),
        "battery_system": "锂硫电池",
        "active_material": "S/C",
        "cell_type": "半电池",
        "counter_electrode": "Li",
        "test_current": "0.1 C",
        "temperature": "25 C",
        "normalization_basis": "硫质量",
        "search_literature": network,
        "use_origin": origin,
        "max_literature": 2,
    }


class Phase1GuiControllerTests(unittest.TestCase):
    def test_prepare_creates_reviewable_plan_but_cannot_execute_without_approval(self):
        from electrochem_harness.gui_phase1 import Phase1GuiController

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "curve.csv"
            write_capacity_curve(source)
            controller = Phase1GuiController(PROJECT_ROOT)

            prepared = controller.prepare(values(source, root / "result"))

            self.assertFalse(prepared.blocked)
            self.assertEqual(prepared.state, WorkflowState.AWAITING_APPROVAL)
            self.assertEqual(len(prepared.plan.plan_hash), 64)
            self.assertTrue((prepared.run_dir / "plan.json").is_file())
            self.assertTrue((prepared.run_dir / "preflight.json").is_file())
            with self.assertRaises(ApprovalRequired):
                controller.execute()

    def test_approved_local_run_generates_valid_artifacts_and_audit_record(self):
        from electrochem_harness.gui_phase1 import Phase1GuiController

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "curve.csv"
            write_capacity_curve(source)
            controller = Phase1GuiController(PROJECT_ROOT)
            controller.prepare(values(source, root / "result"))
            approval = controller.approve()

            result = controller.execute()

            self.assertEqual(result.state, WorkflowState.COMPLETED)
            self.assertIn("local_analysis", approval.scopes)
            self.assertIn("formal_output", approval.scopes)
            self.assertTrue((result.run_dir / "approval.json").is_file())
            self.assertTrue((result.run_dir / "events.jsonl").is_file())
            self.assertTrue((result.run_dir / "run_record.json").is_file())
            self.assertTrue((result.run_dir / "artifacts" / "关键参数报告.md").is_file())
            self.assertTrue(result.validation.valid)

    def test_changed_form_invalidates_approval_and_requires_new_plan(self):
        from electrochem_harness.gui_phase1 import Phase1GuiController

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "curve.csv"
            write_capacity_curve(source)
            original = values(source, root / "result")
            controller = Phase1GuiController(PROJECT_ROOT)
            controller.prepare(original)
            controller.approve()
            changed = dict(original)
            changed["temperature"] = "60 C"

            self.assertTrue(controller.invalidate_if_changed(changed))
            self.assertTrue(controller.approval_invalidated)
            with self.assertRaises(ApprovalRequired):
                controller.execute()

    def test_unreadable_land_format_is_blocked_before_plan_or_approval(self):
        from electrochem_harness.gui_phase1 import Phase1GuiController

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "bad.csv"
            source.write_text("not,a,land,file\n1,2,3,4\n", encoding="utf-8")
            controller = Phase1GuiController(PROJECT_ROOT)

            prepared = controller.prepare(values(source, root / "result"))

            self.assertTrue(prepared.blocked)
            self.assertEqual(prepared.state, WorkflowState.BLOCKED)
            self.assertIsNone(prepared.plan)
            self.assertTrue(any(issue["blocking"] for issue in prepared.issues))
            with self.assertRaises(ApprovalRequired):
                controller.approve()

    def test_origin_failure_is_an_explicit_degradation_not_lost_local_work(self):
        from electrochem_harness.gui_phase1 import Phase1GuiController
        from electrochem_harness.origin_adapter import OriginPlotFailed

        def failing_launcher(*args, **kwargs):
            raise OriginPlotFailed("Origin is not installed on this machine")

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "curve.csv"
            write_capacity_curve(source)
            controller = Phase1GuiController(
                PROJECT_ROOT, origin_launcher=failing_launcher
            )
            controller.prepare(values(source, root / "result", origin=True))
            controller.approve()

            result = controller.execute()

            self.assertEqual(result.state, WorkflowState.COMPLETED_WITH_WARNINGS)
            self.assertTrue((result.run_dir / "artifacts" / "关键参数报告.md").is_file())
            self.assertEqual(result.degradations[0].tool_id, "build_origin_project")
            self.assertIn("Origin is not installed", result.degradations[0].reason)

    def test_origin_success_records_project_figures_and_compatibility_warnings(self):
        import json as json_module

        from electrochem_harness.gui_phase1 import Phase1GuiController
        from electrochem_harness.origin_adapter import OriginStatus

        def fake_launcher(job_path, project_root, **kwargs):
            output = Path(job_path).parent
            for name in ("电化学分析.opju", "充放电曲线.png", "循环性能.png"):
                (output / name).write_bytes(b"origin-stub")
            (output / "origin_status.json").write_text(
                json_module.dumps(
                    {
                        "ok": True,
                        "project": str(output / "电化学分析.opju"),
                        "origin_release": "2026b",
                        "originpro_version": "1.2.3",
                        "compatibility_warnings": ["save_fig(width=...) is unavailable"],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            return OriginStatus(
                ok=True,
                project=str(output / "电化学分析.opju"),
                origin_release="2026b",
                originpro_version="1.2.3",
                warnings=("save_fig(width=...) is unavailable",),
            )

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "curve.csv"
            write_capacity_curve(source)
            controller = Phase1GuiController(
                PROJECT_ROOT, origin_launcher=fake_launcher
            )
            controller.prepare(values(source, root / "result", origin=True))
            controller.approve()

            result = controller.execute()

            self.assertEqual(result.state, WorkflowState.COMPLETED)
            artifacts = result.run_dir / "artifacts"
            for name in ("电化学分析.opju", "充放电曲线.png", "循环性能.png", "origin_status.json"):
                self.assertTrue((artifacts / name).is_file(), name)
            self.assertEqual(
                result.outputs["build_origin_project"]["origin_release"], "2026b"
            )
            record = json_module.loads(
                (result.run_dir / "run_record.json").read_text(encoding="utf-8")
            )
            self.assertTrue(
                any("save_fig" in warning for warning in record["warnings"]), record["warnings"]
            )
            self.assertEqual(record["degradations"], [])

    def test_raw_four_column_mode_generates_controlled_local_report(self):
        from electrochem_harness.gui_phase1 import Phase1GuiController

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "raw.csv"
            source.write_text(
                "循环号,测试时间(s),电流(mA),电压(V)\n"
                "1,0,1,2.0\n1,10,1,2.2\n1,20,-1,2.1\n1,30,-1,1.8\n",
                encoding="utf-8",
            )
            controller = Phase1GuiController(PROJECT_ROOT)
            prepared = controller.prepare(values(source, root / "result"))
            controller.approve()

            result = controller.execute()

            self.assertEqual(prepared.summary["mode"], "raw_current_curve")
            self.assertEqual(result.state, WorkflowState.COMPLETED)
            self.assertTrue((result.run_dir / "artifacts" / "完整分析.json").is_file())

    def test_network_scope_is_required_and_mocked_search_is_audited(self):
        from unittest.mock import patch
        from electrochem_harness.approval import ApprovalScopeError
        from electrochem_harness.gui_phase1 import Phase1GuiController

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "curve.csv"
            write_capacity_curve(source)
            controller = Phase1GuiController(PROJECT_ROOT)
            controller.prepare(values(source, root / "result", network=True))
            with self.assertRaises(ApprovalScopeError):
                controller.approve(("local_analysis", "formal_output"))
            controller.approve(("local_analysis", "network_access", "formal_output"))
            response = {
                "verified_count": 0,
                "records": [],
                "limitations": ["mocked for deterministic test"],
            }
            with patch(
                "electrochem_harness.production_registry.search_crossref",
                return_value=response,
            ):
                result = controller.execute()

            self.assertEqual(result.state, WorkflowState.COMPLETED)
            self.assertTrue((result.run_dir / "artifacts" / "文献证据.json").is_file())
            report = (result.run_dir / "artifacts" / "关键参数报告.md").read_text(encoding="utf-8")
            self.assertIn("Phase 1文献执行记录", report)

    def test_cancel_before_execution_is_recorded_as_cancelled(self):
        from electrochem_harness.gui_phase1 import Phase1GuiController

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "curve.csv"
            write_capacity_curve(source)
            controller = Phase1GuiController(PROJECT_ROOT)
            controller.prepare(values(source, root / "result"))
            controller.approve()
            controller.cancel("演示用户取消")

            result = controller.execute()

            self.assertEqual(result.state, WorkflowState.CANCELLED)
            self.assertTrue((result.run_dir / "run_record.json").is_file())

    def test_plan_formatter_shows_tools_hash_and_blocking_reason(self):
        from electrochem_harness.gui_phase1 import Phase1GuiController, format_plan

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            good = root / "good.csv"
            write_capacity_curve(good)
            controller = Phase1GuiController(PROJECT_ROOT)
            prepared = controller.prepare(values(good, root / "good-result"))
            text = format_plan(prepared)
            self.assertIn("计划哈希", text)
            self.assertIn("parse_land_text", text)

            bad = root / "bad.csv"
            bad.write_text("invalid\n", encoding="utf-8")
            blocked = controller.prepare(values(bad, root / "bad-result"))
            blocked_text = format_plan(blocked)
            self.assertIn("阻断问题", blocked_text)
            self.assertIn("unrecognized_land_format", blocked_text)


class Phase1GuiIntegrationTests(unittest.TestCase):
    def test_main_window_exposes_phase1_controlled_demo(self):
        import tkinter as tk
        from unittest.mock import patch
        from electrochem_harness.gui import ElectrochemApp

        root = tk.Tk()
        root.withdraw()
        app = ElectrochemApp(root, PROJECT_ROOT)
        try:
            app.variables["battery_system"].set("锂硫电池")
            with patch("electrochem_harness.gui.Phase1Dialog") as dialog:
                app.open_phase1_demo()
            self.assertEqual(app.phase1_button.cget("text"), "Phase 1受控演示")
            passed_values = dialog.call_args.args[2]
            self.assertEqual(passed_values["battery_system"], "锂硫电池")
        finally:
            root.destroy()



if __name__ == "__main__":
    unittest.main()
