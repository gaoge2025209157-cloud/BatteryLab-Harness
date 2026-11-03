import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))


def unified_values(source, output, fulltext):
    return {
        "input_file": str(source),
        "output_dir": str(output),
        "battery_system": "卤化物全固态锂电池",
        "active_material": "Li3ScCl6",
        "cell_type": "半电池",
        "counter_electrode": "Li-In",
        "test_current": "0.1",
        "temperature": "25",
        "search_literature": True,
        "unified_research": True,
        "max_literature": 5,
        "research_domain": "卤化物固态电解质正极界面",
        "research_background": "研究复合正极界面演化与容量衰减。",
        "research_question": "界面反应和接触损失是否导致容量衰减？",
        "local_fulltext_dir": str(fulltext),
        "literature_year_from": 2020,
        "use_origin": False,
        "origin_plot_mode": "both",
        "origin_exe": "",
    }


def reasoning():
    return {
        "summary": "当前容量变化可作为界面问题的筛选线索。",
        "recommended_search_terms": [],
        "article_core_findings": [],
        "research_background": [],
        "electrochemistry_foundations": [],
        "key_figures_tables": [],
        "learning_delta": [],
        "data_value_assessment": [{"finding": "容量下降", "value": "失效线索", "evidence": "确定性分析", "confidence": "medium", "limitations": "单电池"}],
        "missing_experiments": [{"question": "是否可重复", "experiment": "三个平行电池", "variables": "同批同条件", "expected_evidence": "均值和离散度", "priority": "high"}],
        "missing_characterization": [{"question": "界面是否变化", "characterization": "XPS", "sampling": "循环前后", "expected_evidence": "化学态变化", "priority": "high"}],
        "cannot_determine": ["不能只凭容量曲线确定界面机理"],
        "knowledge_candidates": [{"claim": "界面反应可能参与衰减", "source_ids": ["10.1000/a"], "conditions": "同类卤化物体系", "confidence": "medium", "verification_needed": "核对Figure 3"}],
    }


class UnifiedResearchWorkflowTests(unittest.TestCase):
    def test_search_is_derived_from_experiment_and_project_context(self):
        from electrochem_harness.research_workflow import build_learning_request

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            request = build_learning_request(unified_values(root / "data.csv", root / "out", root), root / "analysis.json")

        self.assertEqual(request.search.max_results, 5)
        self.assertEqual(request.max_documents, 5)
        self.assertEqual(request.model_document_limit, 1)
        self.assertEqual(request.max_evidence_chars, 26000)
        self.assertIn("课题背景", request.search.research_question)
        self.assertTrue(request.auto_fetch_publisher_html)
        self.assertFalse(request.open_guided_pages)
        self.assertIn("tju_library", request.search.databases)
        self.assertIn("web_of_science", request.search.databases)
        self.assertIn("wiley", request.search.databases)
        self.assertTrue(any("halide solid electrolyte" in group for group in request.search.concept_groups))

    def test_final_guidance_requires_every_candidate_to_be_reviewed(self):
        from electrochem_harness.knowledge_assistant import knowledge_candidate_key
        from electrochem_harness.research_workflow import finalize_research_guidance

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            deterministic = root / "关键结论.txt"
            deterministic.write_text("关键指标\n容量保持率：80%。\n", encoding="utf-8")
            item = reasoning()["knowledge_candidates"][0]
            with self.assertRaises(ValueError):
                finalize_research_guidance(
                    deterministic_conclusion=deterministic,
                    reasoning=reasoning(),
                    status_by_id={},
                    values=unified_values(root / "data.csv", root / "out", root),
                    target=root / "研究结论与指导.txt",
                )
            automatic = finalize_research_guidance(
                deterministic_conclusion=deterministic,
                reasoning=reasoning(),
                status_by_id={},
                values=unified_values(root / "data.csv", root / "out", root),
                target=root / "自动研究结论与指导.txt",
                require_review=False,
            )
            self.assertIn("原文已学习，待人工复核", automatic.read_text(encoding="utf-8"))
            target = finalize_research_guidance(
                deterministic_conclusion=deterministic,
                reasoning=reasoning(),
                status_by_id={knowledge_candidate_key(item): "approved"},
                values=unified_values(root / "data.csv", root / "out", root),
                target=root / "研究结论与指导.txt",
            )
            text = target.read_text(encoding="utf-8")

        self.assertIn("已学习知识及复核状态", text)
        self.assertIn("原文学习记录（供人工核对，不自动进入正式结论）", text)
        self.assertIn("候选解释与证据缺口", text)
        self.assertIn("判别实验", text)
        self.assertIn("支持结果", text)
        self.assertIn("反证结果", text)
        self.assertIn("10.1000/a", text)
        self.assertNotIn("*", text)

    def test_dialogue_uses_guidance_and_returns_structured_advice(self):
        from electrochem_harness.llm_provider import LLMResult
        from electrochem_harness.research_workflow import ask_research_question

        class Provider:
            def generate_json(self, system, payload):
                self.payload = payload
                return LLMResult({"answer": "先确认重复性。", "basis": ["当前只有单电池"], "uncertainties": ["批次差异"], "next_actions": ["制作三个平行电池"], "questions_for_user": ["载量是多少？"]}, "qwen", 10, 20, 30)

        from electrochem_harness.knowledge_assistant import knowledge_candidate_key
        provider = Provider()
        candidate = reasoning()["knowledge_candidates"][0]
        response = ask_research_question(
            provider=provider,
            values={"research_domain": "卤化物", "research_background": "界面研究", "research_question": "为何衰减"},
            guidance_text="当前单电池容量下降",
            reasoning=reasoning(),
            history=[],
            user_message="我的整体课题下一步怎么安排？",
            status_by_id={knowledge_candidate_key(candidate): "approved"},
        )
        self.assertEqual(response["model"], "qwen")
        self.assertTrue(any("三个平行电池" in item for item in response["next_actions"]))
        self.assertEqual(len(provider.payload["literature_learning"]["approved_knowledge"]), 1)
        self.assertTrue(provider.payload["literature_learning"]["rejected_content_omitted"])
        self.assertEqual(provider.payload["literature_learning"]["learned_pending_review"], [])
        self.assertNotIn("article_core_findings", provider.payload["literature_learning"])

    def test_controlled_network_stage_writes_learning_and_audit_artifacts(self):
        from electrochem_harness.gui_phase1 import Phase1GuiController
        from electrochem_harness.workflow import WorkflowState

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "curve.csv"
            source.write_text("测试时间/h,比容量/mAh/g,电压/V\n0,0,1.0\n0.1,10,0.5\n0.1,0,0.6\n0.2,12,2.5\n0.2,0,2.4\n0.3,9,0.5\n", encoding="utf-8")
            values = unified_values(source, root / "out", root)
            fake = SimpleNamespace(
                reasoning=reasoning(), run_id="learn-1", run_dir=root / "knowledge-run",
                knowledge_entry_key="k" * 64, knowledge_path=root / "knowledge.md",
                plan_hash="p" * 64, evidence_hash="e" * 64, context_hash="c" * 64,
                context_tokens_estimated=1000, model="qwen", total_tokens=500,
                cache_hit=False, metadata_count=2, document_count=2,
            )
            progress_events = []
            controller = Phase1GuiController(
                root,
                progress_callback=lambda stage, message, details: progress_events.append((stage, message, details)),
            )
            prepared = controller.prepare(values)
            controller.approve(("local_analysis", "network_access", "formal_output"))
            def fake_learning(*args, **kwargs):
                kwargs["progress_callback"]("search", "论文筛选完成", {"selected_count": 2})
                return fake
            with patch("electrochem_harness.production_registry.run_integrated_learning", side_effect=fake_learning):
                result = controller.execute()
            artifacts = result.run_dir / "artifacts"
            learning_exists = (artifacts / "文献学习结果.json").is_file()
            audit_exists = (artifacts / "文献学习审计.json").is_file()
            guidance_exists = (artifacts / "研究结论与指导.txt").is_file()
            html_report_exists = (artifacts / "研究分析报告.html").is_file()
            audit = json.loads((artifacts / "文献学习审计.json").read_text(encoding="utf-8"))
            root_text = str(root)

        self.assertEqual(result.state, WorkflowState.COMPLETED)
        self.assertEqual(progress_events[0][0], "search")
        self.assertEqual(progress_events[0][2]["selected_count"], 2)
        self.assertTrue(learning_exists)
        self.assertTrue(audit_exists)
        self.assertTrue(guidance_exists)
        self.assertTrue(html_report_exists)
        self.assertEqual(audit["document_count"], 2)
        self.assertNotIn(root_text, json.dumps(audit, ensure_ascii=False))


    def test_search_only_fallback_keeps_five_papers_without_failing_run(self):
        from electrochem_harness.gui_phase1 import Phase1GuiController
        from electrochem_harness.knowledge_assistant import NoReadableFulltextError
        from electrochem_harness.workflow import WorkflowState

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "curve.csv"
            source.write_text("测试时间/h,比容量/mAh/g,电压/V\n0,0,1.0\n0.1,10,0.5\n0.1,0,0.6\n0.2,12,2.5\n0.2,0,2.4\n0.3,9,0.5\n", encoding="utf-8")
            values = unified_values(source, root / "out", root)
            papers = [
                {"doi": "10.1000/{}".format(index), "title": "Paper {}".format(index), "journal": "Nature Communications", "year": 2026, "status": "需浏览器下载", "learned": False}
                for index in range(5)
            ]
            controller = Phase1GuiController(root)
            controller.prepare(values)
            controller.approve(("local_analysis", "network_access", "formal_output"))
            with patch(
                "electrochem_harness.production_registry.run_integrated_learning",
                side_effect=NoReadableFulltextError("search only", papers),
            ):
                result = controller.execute()
            artifacts = result.run_dir / "artifacts"
            audit = json.loads((artifacts / "文献学习审计.json").read_text(encoding="utf-8"))
            manifest = json.loads((artifacts / "文献清单.json").read_text(encoding="utf-8"))
            automatic_report_exists = (artifacts / "研究分析报告.html").is_file()

        self.assertEqual(result.state, WorkflowState.COMPLETED)
        self.assertEqual(audit["status"], "search_only")
        self.assertFalse(audit["model_called"])
        self.assertEqual(manifest["selected_count"], 5)
        self.assertTrue(automatic_report_exists)


    def test_unreviewed_fulltext_learning_is_reused_with_lower_trust(self):
        from electrochem_harness.knowledge_assistant import ResearchKnowledgeStore
        from electrochem_harness.academic_search import AcademicSearchRequest
        from electrochem_harness.knowledge_assistant import KnowledgeAssistantRequest

        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "knowledge.md"
            request = KnowledgeAssistantRequest(
                search=AcademicSearchRequest(
                    domain="卤化物",
                    research_question="界面为何衰减",
                    concept_groups=(("halide",), ("interface",)),
                    max_results=1,
                ),
                max_documents=1,
            )
            store = ResearchKnowledgeStore(path)
            store.update_candidate(
                request,
                reasoning(),
                evidence_hash="a" * 64,
                run_id="run-1",
                source_ids=("10.1000/a",),
            )
            reusable = store.reusable_evidence("卤化物")

        self.assertEqual(len(reusable), 1)
        self.assertEqual(reusable[0]["status"], "candidate")
        self.assertEqual(reusable[0]["trust"], "fulltext_learned_pending_review")


if __name__ == "__main__":
    unittest.main()
