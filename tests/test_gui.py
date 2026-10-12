import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))


class GuiValidationTests(unittest.TestCase):
    def _values(self, source, output):
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
            "search_literature": True,
            "use_origin": True,
            "origin_exe": "",
            "max_literature": 50,
        }

    def test_form_requires_existing_input_and_output_directory(self):
        from electrochem_harness.gui import validate_form

        values = self._values("missing.csv", "")
        errors = validate_form(values)

        self.assertTrue(any("输入文件" in error for error in errors))
        self.assertTrue(any("输出目录" in error for error in errors))

    def test_literature_search_requires_all_comparison_metadata(self):
        from electrochem_harness.gui import validate_form

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "curve.csv"
            source.write_text("placeholder", encoding="utf-8")
            values = self._values(source, Path(tmp) / "result")
            values["temperature"] = ""
            values["normalization_basis"] = "待填"

            errors = validate_form(values)

        self.assertTrue(any("测试温度" in error for error in errors))
        self.assertTrue(any("质量归一化口径" in error for error in errors))

    def test_report_only_command_is_argument_list_and_skips_origin(self):
        from electrochem_harness.gui import build_workflow_command

        values = self._values("D:/data/input.csv", "D:/data/result")
        values["use_origin"] = False
        values["search_literature"] = False
        command = build_workflow_command(PROJECT_ROOT, values)

        self.assertIsInstance(command, list)
        self.assertEqual(command[0].lower(), "powershell.exe")
        self.assertIn("-SkipOrigin", command)
        self.assertNotIn("-SearchLiterature", command)
        self.assertIn(str(PROJECT_ROOT / "run_sci_origin.ps1"), command)

    def test_full_command_contains_metadata_without_shell_quoting(self):
        from electrochem_harness.gui import build_workflow_command

        values = self._values("D:/data/input file.csv", "D:/data/result folder")
        values["origin_exe"] = "E:/Apps/Origin/Origin64.exe"
        command = build_workflow_command(PROJECT_ROOT, values)

        self.assertIn("-SearchLiterature", command)
        self.assertIn("-OriginExe", command)
        self.assertIn("D:/data/input file.csv", command)
        self.assertIn("锂硫电池", command)
        self.assertNotIn('"D:/data/input file.csv"', command)

    def test_tkinter_window_can_be_created_and_closed(self):
        from electrochem_harness.gui import smoke_test

        smoke_test(PROJECT_ROOT)


class GuiInteractionTests(unittest.TestCase):
    def _app(self):
        import tkinter as tk
        from electrochem_harness.gui import ElectrochemApp

        root = tk.Tk()
        root.withdraw()
        return root, ElectrochemApp(root, PROJECT_ROOT)

    def test_file_browsers_update_input_output_and_origin(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "cell.csv"
            source.write_text("data", encoding="utf-8")
            result = Path(tmp) / "chosen-result"
            origin = Path(tmp) / "Origin64.exe"
            origin.write_bytes(b"")
            root, app = self._app()
            try:
                with patch("electrochem_harness.gui.filedialog.askopenfilename", return_value=str(source)):
                    app._choose_input()
                self.assertEqual(app.variables["input_file"].get(), str(source))
                self.assertTrue(app.variables["output_dir"].get().endswith("cell_SCI"))
                with patch("electrochem_harness.gui.filedialog.askdirectory", return_value=str(result)):
                    app._choose_output()
                with patch("electrochem_harness.gui.filedialog.askopenfilename", return_value=str(origin)):
                    app._choose_origin()
                self.assertEqual(app.variables["output_dir"].get(), str(result))
                self.assertEqual(app.variables["origin_exe"].get(), str(origin))
            finally:
                root.destroy()

    def test_analysis_and_environment_buttons_dispatch_argument_lists(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "cell.csv"
            source.write_text("data", encoding="utf-8")
            root, app = self._app()
            try:
                values = {
                    "input_file": str(source),
                    "output_dir": str(Path(tmp) / "result"),
                    "battery_system": "锂硫电池",
                    "active_material": "S/C",
                    "cell_type": "半电池",
                    "counter_electrode": "Li",
                    "test_current": "0.1 C",
                    "temperature": "25 C",
                    "normalization_basis": "硫质量",
                }
                for name, value in values.items():
                    app.variables[name].set(value)
                with patch.object(app, "_start_command") as start:
                    app.run_analysis()
                    analysis_command, kind = start.call_args.args
                    self.assertEqual(kind, "analysis")
                    self.assertIn("-SearchLiterature", analysis_command)
                    app.check_environment()
                    self.assertEqual(start.call_args.args[1], "check")
                app.variables["temperature"].set("")
                with patch("electrochem_harness.gui.messagebox.showerror") as show_error, patch.object(app, "_start_command") as start:
                    app.run_analysis()
                    show_error.assert_called_once()
                    start.assert_not_called()
            finally:
                root.destroy()

    def test_worker_streams_output_and_reports_exit_code(self):
        root, app = self._app()
        fake_process = MagicMock()
        fake_process.stdout = ["first line\n", "second line\n"]
        fake_process.wait.return_value = 0
        try:
            with patch("electrochem_harness.gui.subprocess.Popen", return_value=fake_process):
                app._worker(["example-command"])
            events = [app.events.get_nowait(), app.events.get_nowait(), app.events.get_nowait()]
            self.assertEqual(events[-1], ("done", 0))
            self.assertIn(("line", "first line"), events)
        finally:
            root.destroy()

    def test_status_log_open_output_and_cancel_are_user_visible(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, app = self._app()
            try:
                app._append_log("hello")
                self.assertIn("hello", app.log.get("1.0", "end"))
                app.task_kind = "analysis"
                with patch("electrochem_harness.gui.messagebox.showinfo") as info:
                    app._finish(0)
                    info.assert_called_once()
                with patch("electrochem_harness.gui.messagebox.showerror") as error:
                    app._finish(2)
                    error.assert_called_once()
                app.variables["output_dir"].set(tmp)
                with patch("electrochem_harness.gui.os.startfile") as startfile:
                    app.open_output()
                    startfile.assert_called_once()
                fake_process = MagicMock()
                fake_process.pid = 1234
                fake_process.poll.return_value = None
                app.process = fake_process
                with patch("electrochem_harness.gui.subprocess.run") as run:
                    app._terminate_process()
                    run.assert_called_once()
                with patch("electrochem_harness.gui.messagebox.askyesno", return_value=False), patch.object(app, "_terminate_process") as terminate:
                    app.cancel_task()
                    terminate.assert_not_called()
            finally:
                root.destroy()


if __name__ == "__main__":
    unittest.main()
