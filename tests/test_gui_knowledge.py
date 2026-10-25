import sys
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))


class KnowledgeAssistantDialogTests(unittest.TestCase):
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

    def make_dialog(self):
        from electrochem_harness.gui_knowledge import KnowledgeAssistantDialog

        dialog = KnowledgeAssistantDialog(self.root, PROJECT_ROOT)
        dialog.withdraw()
        self.addCleanup(self._close, dialog)
        dialog.question_text.insert("1.0", "界面稳定性如何影响循环性能？")
        return dialog

    @staticmethod
    def _close(dialog):
        try:
            dialog.busy = False
            dialog._on_close()
        except tk.TclError:
            pass

    def test_generates_advanced_search_plan_without_network(self):
        dialog = self.make_dialog()
        with patch("electrochem_harness.gui_knowledge.messagebox"):
            plan = dialog.generate_search_plan()
        self.assertIsNotNone(plan)
        text = dialog.output_text.get("1.0", "end")
        self.assertIn("web_of_science", text)
        self.assertIn("TS=(", text)
        self.assertIn("scopus", text)
        self.assertIn("TITLE-ABS-KEY(", text)
        self.assertIn("校园IP", text)

    def test_missing_llm_configuration_is_rejected_before_network(self):
        dialog = self.make_dialog()
        dialog.variables["llm_base_url"].set("")
        dialog.variables["llm_model"].set("")
        with patch("electrochem_harness.gui_knowledge.messagebox") as box:
            dialog.run_assistant()
        self.assertFalse(dialog.busy)
        box.showerror.assert_called_once()

    def test_main_gui_exposes_knowledge_assistant_button(self):
        from electrochem_harness.gui import ElectrochemApp

        app = ElectrochemApp(self.root, PROJECT_ROOT)
        try:
            self.assertEqual("文献知识助手", app.knowledge_assistant_button.cget("text"))
            self.assertTrue(callable(app.open_knowledge_assistant))
        finally:
            app._cancel_polling()
            for widget in self.root.winfo_children():
                if widget is not self.root:
                    try:
                        widget.destroy()
                    except tk.TclError:
                        pass


if __name__ == "__main__":
    unittest.main()
