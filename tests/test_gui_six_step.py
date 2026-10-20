import sys
import tempfile
import time
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from electrochem_harness.gui_controller import WizardStep
from electrochem_harness.gui_six_step import SixStepDialog
from electrochem_harness.origin_adapter import OriginPlotFailed

SAMPLE = PROJECT_ROOT / "examples" / "sample_capacity_curve.csv"


def values(source, output, *, origin=False, network=False):
    return {
        "input_file": str(source),
        "output_dir": str(output),
        "origin_exe": "",
        "search_literature": network,
        "use_origin": origin,
        "max_literature": 2,
        "battery_system": "Li-S",
        "active_material": "S/C",
        "cell_type": "coin cell",
        "counter_electrode": "Li",
        "test_current": "0.2C",
        "temperature": "25 C",
        "normalization_basis": "硫质量",
    }


def pump(root, dialog, timeout=30.0):
    """Drive the Tk event loop until the worker thread reports back."""

    deadline = time.time() + timeout
    while dialog.busy and time.time() < deadline:
        root.update()
        time.sleep(0.02)
    for _ in range(30):
        root.update()
        time.sleep(0.005)


class DialogTestCase(unittest.TestCase):
    """Share one Tk root per class.

    Creating and destroying a fresh ``Tk`` per test leaves orphaned timers in
    previously created interpreters, which Tcl reports as
    ``invalid command name ..._poll_events``.
    """

    @classmethod
    def setUpClass(cls):
        cls.root = tk.Tk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        try:
            cls.root.destroy()
        except tk.TclError:
            pass

    def setUp(self):
        # 任何意外的错误弹窗都会阻塞事件循环，测试里一律拦截。
        patcher = patch("electrochem_harness.gui_six_step.messagebox")
        self.messagebox = patcher.start()
        self.addCleanup(patcher.stop)

    def make(self, form_values, launcher=None):
        with patch("electrochem_harness.gui_six_step.messagebox"):
            dialog = SixStepDialog(
                self.root, PROJECT_ROOT, form_values, origin_launcher=launcher
            )
        dialog.withdraw()
        self.addCleanup(self._close_dialog, dialog)
        return self.root, dialog

    @staticmethod
    def _close_dialog(dialog):
        try:
            dialog.destroy()
        except tk.TclError:
            pass

    @staticmethod
    def _safe_destroy(widget):
        try:
            widget.destroy()
        except tk.TclError:
            pass

    def tree_state(self, dialog, name):
        for group in dialog.results_tree.get_children():
            for item in dialog.results_tree.get_children(group):
                if dialog.results_tree.item(item, "text").strip() == name:
                    return dialog.results_tree.item(item, "values")[0]
        return None


class SixStepNavigationTests(DialogTestCase):
    def test_dialog_opens_on_step_one_and_does_nothing_else(self):
        with tempfile.TemporaryDirectory() as temp:
            root, dialog = self.make(values(SAMPLE, Path(temp) / "out"))

            self.assertEqual(dialog.wizard.step, WizardStep.DATA)
            self.assertEqual(dialog.step_label.cget("text"), "第 1 / 6 步")
            self.assertEqual(dialog.next_button.cget("text"), "下一步：预检查")
            self.assertEqual(str(dialog.back_button.cget("state")), "disabled")
            self.assertFalse((Path(temp) / "out" / "runs").exists())

    def test_blank_form_is_rejected_without_leaving_step_one(self):
        with tempfile.TemporaryDirectory() as temp:
            root, dialog = self.make(values("", Path(temp) / "out"))
            with patch("electrochem_harness.gui_six_step.messagebox") as box:
                dialog.go_next()

            self.assertEqual(dialog.wizard.step, WizardStep.DATA)
            self.assertTrue(box.showerror.called)

    def test_blocking_preflight_keeps_next_disabled(self):
        with tempfile.TemporaryDirectory() as temp:
            root_dir = Path(temp)
            source = root_dir / "garbage.csv"
            source.write_text("这不是蓝电数据\n", encoding="utf-8")
            root, dialog = self.make(values(source, root_dir / "out"))

            dialog.go_next()

            self.assertEqual(dialog.wizard.step, WizardStep.PREFLIGHT)
            self.assertEqual(str(dialog.next_button.cget("state")), "disabled")
            body = dialog.preflight_text.get("1.0", "end")
            self.assertIn("[阻断]", body)

    def test_valid_input_reaches_plan_with_a_hash(self):
        with tempfile.TemporaryDirectory() as temp:
            root, dialog = self.make(values(SAMPLE, Path(temp) / "out"))

            dialog.go_next()
            self.assertEqual(dialog.wizard.step, WizardStep.PREFLIGHT)
            self.assertIn("预检查通过", dialog.preflight_headline.cget("text"))

            dialog.go_next()
            self.assertEqual(dialog.wizard.step, WizardStep.PLAN)
            body = dialog.plan_text.get("1.0", "end")
            self.assertIn("计划哈希", body)
            self.assertIn("build_scientific_report", body)

    def test_going_back_rebuilds_the_plan(self):
        with tempfile.TemporaryDirectory() as temp:
            root, dialog = self.make(values(SAMPLE, Path(temp) / "out"))
            dialog.go_next()
            dialog.go_next()
            first_hash = dialog.wizard.prepared.plan.plan_hash

            dialog.go_back()
            self.assertEqual(dialog.wizard.step, WizardStep.PREFLIGHT)

            dialog.go_next()

            self.assertEqual(dialog.wizard.step, WizardStep.PLAN)
            self.assertEqual(dialog.wizard.prepared.plan.plan_hash, first_hash)


class SixStepApprovalTests(DialogTestCase):
    def _to_approval(self, dialog):
        dialog.go_next()
        dialog.go_next()
        dialog.go_next()
        self.assertEqual(dialog.wizard.step, WizardStep.APPROVAL)

    def test_unchecking_a_mandatory_scope_disables_approval(self):
        with tempfile.TemporaryDirectory() as temp:
            root, dialog = self.make(values(SAMPLE, Path(temp) / "out"))
            self._to_approval(dialog)
            self.assertEqual(str(dialog.approve_button.cget("state")), "normal")

            dialog.scope_vars["formal_output"].set(False)
            dialog._refresh_approve_button()

            self.assertEqual(str(dialog.approve_button.cget("state")), "disabled")
            self.assertIn("formal_output", dialog.status.get())

    def test_network_scope_appears_only_when_requested(self):
        with tempfile.TemporaryDirectory() as temp:
            root, dialog = self.make(values(SAMPLE, Path(temp) / "out"))
            self._to_approval(dialog)
            self.assertNotIn("network_access", dialog.scope_vars)

            root2, dialog2 = self.make(values(SAMPLE, Path(temp) / "out2", network=True))
            self._to_approval(dialog2)
            self.assertIn("network_access", dialog2.scope_vars)
            self.assertIn("Crossref", dialog2.network_note.cget("text"))


class SixStepExecutionTests(DialogTestCase):
    def _run(self, dialog, root):
        dialog.go_next()
        dialog.go_next()
        dialog.go_next()
        self.assertEqual(
            dialog.wizard.step, WizardStep.APPROVAL, "未能进入第 4 步，请检查表单与预检查"
        )
        dialog.approve_and_run()
        pump(root, dialog)
        self.assertIsNotNone(dialog.wizard.results, "执行没有产生结果，请检查 worker 异常")

    def test_full_run_reaches_results_with_artifacts(self):
        with tempfile.TemporaryDirectory() as temp:
            root, dialog = self.make(values(SAMPLE, Path(temp) / "out"))
            self._run(dialog, root)

            self.assertEqual(dialog.wizard.step, WizardStep.RESULTS)
            self.assertIn("第 6 步", dialog.results_headline.cget("text"))
            self.assertEqual(self.tree_state(dialog, "关键参数报告.md"), "已生成")
            self.assertEqual(self.tree_state(dialog, "科学计算标准.json"), "已生成")
            self.assertEqual(self.tree_state(dialog, "events.jsonl"), "已生成")
            self.assertEqual(self.tree_state(dialog, "origin_job.json"), "已生成")

    def test_origin_failure_is_shown_as_degradation(self):
        def failing_launcher(*args, **kwargs):
            raise OriginPlotFailed("Origin 未安装")

        with tempfile.TemporaryDirectory() as temp:
            root, dialog = self.make(values(SAMPLE, Path(temp) / "out", origin=True), failing_launcher)
            self._run(dialog, root)

            self.assertIn("降级记录", dialog.degradation_label.cget("text"))
            self.assertIn("build_origin_project", dialog.degradation_label.cget("text"))
            self.assertEqual(self.tree_state(dialog, "关键参数报告.md"), "已生成")
            self.assertEqual(self.tree_state(dialog, "充放电曲线.png"), "缺失")

    def test_retry_creates_a_second_run_and_keeps_the_first(self):
        with tempfile.TemporaryDirectory() as temp:
            root, dialog = self.make(values(SAMPLE, Path(temp) / "out"))
            self._run(dialog, root)
            first = dialog._run_dir()

            with patch("electrochem_harness.gui_six_step.messagebox"):
                dialog.retry_run()
            pump(root, dialog)
            second = dialog._run_dir()

            self.assertNotEqual(first, second)
            self.assertTrue((first / "events.jsonl").is_file())
            self.assertTrue((second / "events.jsonl").is_file())
            self.assertIn("retry_requested", (second / "events.jsonl").read_text(encoding="utf-8"))

    def test_back_to_form_returns_to_step_one(self):
        with tempfile.TemporaryDirectory() as temp:
            root, dialog = self.make(values(SAMPLE, Path(temp) / "out"))
            self._run(dialog, root)

            dialog.back_to_form()

            self.assertEqual(dialog.wizard.step, WizardStep.DATA)
            self.assertEqual(dialog.step_label.cget("text"), "第 1 / 6 步")


class MainWindowEntryTests(unittest.TestCase):
    def test_main_window_exposes_the_six_step_entry(self):
        from electrochem_harness.gui import ElectrochemApp

        root = tk.Tk()
        root.withdraw()
        try:
            app = ElectrochemApp(root, PROJECT_ROOT)
            self.assertEqual(app.six_step_button.cget("text"), "六步受控分析")
            self.assertTrue(callable(app.open_six_step))
        finally:
            app._cancel_polling()
            root.destroy()

    def test_open_six_step_passes_current_form_values(self):
        from electrochem_harness.gui import ElectrochemApp

        root = tk.Tk()
        root.withdraw()
        captured = {}

        class FakeDialog:
            def __init__(self, parent, project_root, form_values):
                captured["values"] = form_values
                captured["root"] = project_root

            def winfo_exists(self):
                return 1

        try:
            app = ElectrochemApp(root, PROJECT_ROOT)
            app.variables["input_file"].set("D:/data/cell.csv")
            app.variables["battery_system"].set("Li-S")
            with patch("electrochem_harness.gui_six_step.SixStepDialog", FakeDialog):
                app.open_six_step()

            self.assertEqual(captured["values"]["input_file"], "D:/data/cell.csv")
            self.assertEqual(captured["values"]["battery_system"], "Li-S")
            self.assertEqual(Path(captured["root"]), PROJECT_ROOT)
        finally:
            app._cancel_polling()
            root.destroy()


if __name__ == "__main__":
    unittest.main()
