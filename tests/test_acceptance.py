import sys
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))


class AcceptanceStoreTests(unittest.TestCase):
    def test_checklist_covers_learned_knowledge_and_data_flow_only(self):
        from electrochem_harness.acceptance import ACCEPTANCE_ITEMS

        ids = {item.item_id for item in ACCEPTANCE_ITEMS}
        self.assertEqual(len(ACCEPTANCE_ITEMS), 10)
        self.assertEqual(ids, {"KN-01", "KN-02", "KN-03", "KN-04", "KN-05", "DF-01", "DF-02", "DF-03", "DF-04", "DF-05"})
        combined = " ".join(
            "{} {} {} {} {}".format(item.group, item.title, item.review_object, item.operation, item.expected)
            for item in ACCEPTANCE_ITEMS
        )
        self.assertNotIn("J/C", combined)
        self.assertNotIn("发布门", combined)
        self.assertNotIn("必须", combined)
        self.assertTrue(all(item.operation and item.expected and item.review_object for item in ACCEPTANCE_ITEMS))

    def test_status_notes_persist_and_report_is_exported(self):
        from electrochem_harness.acceptance import AcceptanceStore

        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp) / "acceptance_state.json"
            store = AcceptanceStore(state)
            store.mark("DF-02", "passed", "run-001，平均电压与比能量抽查一致。")
            restored = AcceptanceStore(state)
            report = restored.export_markdown()

            self.assertEqual(restored.record("DF-02")["status"], "passed")
            self.assertIn("run-001", restored.record("DF-02")["note"])
            self.assertEqual(restored.summary()["passed"], 1)
            text = report.read_text(encoding="utf-8")
            self.assertIn("DF-02", text)
            self.assertIn("平均电压与比能量", text)
            self.assertIn("关键指标计算结果", text)


class AcceptanceDialogTests(unittest.TestCase):
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

    def test_dialog_marks_one_item_without_changing_siblings(self):
        from electrochem_harness.gui_acceptance import AcceptanceDialog

        with tempfile.TemporaryDirectory() as temp:
            dialog = AcceptanceDialog(self.root, Path(temp), action_handlers={})
            dialog.withdraw()
            try:
                dialog.tree.selection_set("KN-01")
                dialog._show_item("KN-01")
                dialog.note_text.insert("1.0", "人工核对完成")
                dialog._set_status("passed")
                self.assertEqual(dialog.store.record("KN-01")["status"], "passed")
                self.assertEqual(dialog.store.record("KN-02")["status"], "pending")
                self.assertIn("已确认1", dialog.summary_var.get())
                self.assertEqual(dialog.tree.set("KN-01", "status"), "已确认")
            finally:
                dialog.destroy()

    def test_export_button_writes_report(self):
        from electrochem_harness.gui_acceptance import AcceptanceDialog

        with tempfile.TemporaryDirectory() as temp:
            dialog = AcceptanceDialog(self.root, Path(temp), action_handlers={})
            dialog.withdraw()
            try:
                with patch("electrochem_harness.gui_acceptance.messagebox"), patch(
                    "electrochem_harness.gui_acceptance.os.startfile", create=True
                ):
                    dialog._export_report()
                self.assertTrue(
                    (Path(temp) / "outputs" / "manual_acceptance" / "知识点与数据流程验收报告.md").is_file()
                )
            finally:
                dialog.destroy()


if __name__ == "__main__":
    unittest.main()
