import sys
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))


class ResearchWorkbenchTests(unittest.TestCase):
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

    def test_main_window_exposes_one_controlled_entry_and_future_test_entries(self):
        from electrochem_harness.gui import ElectrochemApp

        app = ElectrochemApp(self.root, PROJECT_ROOT)
        try:
            self.assertTrue(app.conclusion_preview.winfo_exists())
            self.assertEqual(
                set(app.test_entry_buttons),
                {"charge_discharge", "performance_plots", "eis", "cv_lsv", "gitt_pitt", "ccd", "characterization"},
            )
            self.assertEqual(str(app.test_entry_buttons["charge_discharge"].cget("state")), "normal")
            self.assertFalse(hasattr(app, "phase1_button"))
            self.assertFalse(hasattr(app, "run_button"))
            labels = []

            def collect(widget):
                try:
                    text = str(widget.cget("text"))
                except tk.TclError:
                    text = ""
                if text:
                    labels.append(text)
                for child in widget.winfo_children():
                    collect(child)

            collect(app.root)
            self.assertEqual(labels.count("文献知识助手"), 1)
        finally:
            app._cancel_polling()
            for widget in self.root.winfo_children():
                try:
                    widget.destroy()
                except tk.TclError:
                    pass

    def test_plain_conclusion_summary_is_loaded_without_markdown_symbols(self):
        from electrochem_harness.gui import ElectrochemApp

        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            (output / "关键参数报告.md").write_text("# 详细报告\n**不要直接展示**\n", encoding="utf-8")
            (output / "关键结论.txt").write_text(
                "关键指标\n容量保持率：90.0%\n\n简要结论与依据\n存在轻微衰减。依据：首末圈容量比较。\n",
                encoding="utf-8",
            )
            app = ElectrochemApp(self.root, PROJECT_ROOT)
            try:
                app.variables["output_dir"].set(str(output))
                self.assertTrue(app._load_analysis_preview())
                displayed = app.conclusion_preview.get("1.0", "end")
                self.assertIn("容量保持率", displayed)
                self.assertNotIn("**", displayed)
                self.assertNotIn("# 详细报告", displayed)
            finally:
                app._cancel_polling()
                for widget in self.root.winfo_children():
                    try:
                        widget.destroy()
                    except tk.TclError:
                        pass

    def test_knowledge_dialog_has_live_progress_conclusions_and_review_queue(self):
        from electrochem_harness.gui_knowledge import KnowledgeAssistantDialog

        dialog = KnowledgeAssistantDialog(self.root, PROJECT_ROOT)
        dialog.withdraw()
        try:
            self.assertTrue(dialog.progress_tree.winfo_exists())
            self.assertTrue(dialog.conclusion_notebook.winfo_exists())
            self.assertTrue(dialog.knowledge_tree.winfo_exists())
            self.assertTrue(callable(dialog.approve_selected_candidate))
            self.assertTrue(callable(dialog.reject_selected_candidate))
        finally:
            dialog.busy = False
            dialog._on_close()


class KnowledgeReviewTests(unittest.TestCase):
    def _request(self):
        from electrochem_harness.academic_search import AcademicSearchRequest
        from electrochem_harness.knowledge_assistant import KnowledgeAssistantRequest

        return KnowledgeAssistantRequest(
            search=AcademicSearchRequest(
                domain="卤化物固态电解质",
                research_question="界面阻抗是否增长？",
                concept_groups=(("halide electrolyte",), ("interface",)),
                databases=("crossref",),
                max_results=3,
            ),
            max_documents=2,
            max_evidence_chars=10000,
        )

    def _reasoning(self):
        return {
            "summary": "现有证据只支持提出界面演化假设。",
            "recommended_search_terms": [],
            "research_background": [],
            "key_figures_tables": [],
            "data_value_assessment": [{"finding": "容量下降", "value": "筛选线索", "evidence": "数据摘要", "confidence": "low", "limitations": "单电池"}],
            "missing_experiments": [{"question": "阻抗是否增长", "experiment": "分阶段EIS", "variables": "温度和压力", "expected_evidence": "阻抗分量变化", "priority": "high"}],
            "missing_characterization": [{"question": "界面产物是什么", "characterization": "XPS", "sampling": "循环前后", "expected_evidence": "化学态变化", "priority": "high"}],
            "cannot_determine": ["不能确定阻抗来源"],
            "knowledge_candidates": [
                {"claim": "需要分阶段EIS验证界面阻抗增长。", "source_ids": ["10.1000/a"], "conditions": "同体系", "confidence": "medium", "verification_needed": "核对正文"},
                {"claim": "循环后XPS可检验界面产物。", "source_ids": ["10.1000/b"], "conditions": "同体系", "confidence": "low", "verification_needed": "补全文"},
            ],
        }

    def test_individual_candidate_can_be_approved_without_approving_siblings(self):
        from electrochem_harness.knowledge_assistant import ResearchKnowledgeStore, knowledge_candidate_key

        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "research_knowledge.md"
            store = ResearchKnowledgeStore(path)
            reasoning = self._reasoning()
            entry_key = store.update_candidate(
                self._request(), reasoning, evidence_hash="a" * 64, run_id="run-1", source_ids=("10.1000/a", "10.1000/b")
            )
            first = knowledge_candidate_key(reasoning["knowledge_candidates"][0])
            second = knowledge_candidate_key(reasoning["knowledge_candidates"][1])
            store.set_candidate_status(entry_key, first, "approved", "已核对正文方法。")
            text = path.read_text(encoding="utf-8")

        self.assertIn("候选ID：{}".format(first), text)
        self.assertIn("状态：approved", text)
        self.assertIn("已核对正文方法", text)
        second_block = text.split("候选ID：{}".format(second), 1)[1]
        self.assertIn("状态：candidate", second_block)

    def test_progress_callback_reports_all_major_stages(self):
        from electrochem_harness.knowledge_assistant import run_knowledge_assistant
        from electrochem_harness.llm_provider import LLMResult

        reasoning = self._reasoning()

        class Provider:
            config = None

            def generate_json(self, system_prompt, payload):
                return LLMResult(payload=reasoning, model="fake", total_tokens=10)

        events = []
        with tempfile.TemporaryDirectory() as temp:
            run_knowledge_assistant(
                self._request(),
                Provider(),
                run_root=Path(temp) / "runs",
                knowledge_path=Path(temp) / "knowledge.md",
                metadata_searcher=lambda request: [],
                document_collector=lambda request, metadata: [],
                progress_callback=lambda stage, message, details: events.append(stage),
            )

        for stage in ("plan", "search", "fulltext", "evidence", "llm", "knowledge", "done"):
            self.assertIn(stage, events)


if __name__ == "__main__":
    unittest.main()
