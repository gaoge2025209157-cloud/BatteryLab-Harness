from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from electrochem_harness_v2.context_builder import (
    ContextBudgetExceeded,
    ContextBuilder,
    claim_compatibility,
)
from electrochem_harness_v2.models import KnowledgeClaim
from electrochem_harness_v2.storage import ResearchStore
from electrochem_harness_v2.workflow import ResearchWorkflow


def _task(identifier: str = "task-1") -> dict:
    return {
        "task_id": identifier,
        "stage": "codex_assessment",
        "goal": "判断容量下降的候选原因并设计下一轮判别实验",
        "success_criteria": ["区分事实与假设", "给出反证实验"],
        "current_question": "容量下降是否来自界面变化",
    }


def _project_context(**conditions) -> dict:
    return {
        "project_id": "project-1",
        "project_name": "P2O5研究",
        "material_system": "P2O5|LiTaCl6|Li-In",
        "keywords": ["P2O5", "容量衰减"],
        "experiment_conditions": {"temperature_C": 60, "cell_type": "half-cell", **conditions},
        "research_objective": "识别性能信号、证据边界和下一轮实验。",
        "deterministic_features": {
            "source_sha256": "abc123",
            "row_count": 200,
            "rows": [{"secret": "raw-row"}],
            "points": [{"time": 1}],
            "gcd_summary": {"latest_capacity_retention_percent": 82.0},
            "limitations": ["只有一颗电池"],
        },
    }


class ContextBuilderV2Tests(unittest.TestCase):
    def test_removes_raw_rows_secrets_and_absolute_paths(self):
        builder = ContextBuilder()
        context = _project_context()
        context["experiment_conditions"]["api_key"] = "do-not-send"
        context["experiment_conditions"]["data_path"] = "D:\\private\\sample.csv"
        result = builder.build(
            stage="codex_assessment",
            task=_task(),
            project_context=context,
            permissions={"network_access": False, "cookie": "private-cookie"},
        )
        rendered = json.dumps(result.bundle, ensure_ascii=False)
        self.assertNotIn("raw-row", rendered)
        self.assertNotIn("do-not-send", rendered)
        self.assertNotIn("private-cookie", rendered)
        self.assertNotIn("D:\\\\private", rendered)
        self.assertIn("sample.csv", rendered)
        self.assertFalse(result.manifest["point_level_input_sent"])
        self.assertFalse(result.manifest["row_level_input_sent"])

    def test_separates_approved_candidate_rejected_and_condition_conflicts(self):
        approved = KnowledgeClaim.new("project-1", "paper-a", "mechanism", "界面变化需要EIS验证").reviewed("approved")
        candidate = KnowledgeClaim.new("project-1", "paper-b", "method", "增加平行电池作为候选建议")
        rejected = KnowledgeClaim.new("project-1", "paper-c", "background", "已被拒绝的旧判断").reviewed("rejected")
        mismatch = KnowledgeClaim.new(
            "project-1", "paper-d", "performance", "另一体系的容量值",
            conditions={"material_system": "LiFePO4"},
        ).reviewed("approved")
        result = ContextBuilder().build(
            stage="codex_assessment",
            task=_task(),
            project_context=_project_context(),
            claims=[approved, candidate, rejected, mismatch],
        )
        self.assertEqual([row["claim_id"] for row in result.bundle["approved_knowledge"]], [approved.claim_id])
        self.assertEqual([row["claim_id"] for row in result.bundle["candidate_knowledge"]], [candidate.claim_id])
        reasons = {row["source_id"]: row["reason"] for row in result.manifest["excluded_sources"]}
        self.assertEqual(reasons[rejected.claim_id], "知识已被人工拒绝")
        self.assertIn("material_system不匹配", reasons[mismatch.claim_id])

    def test_missing_condition_is_labelled_insufficient_not_silently_comparable(self):
        status, reasons = claim_compatibility({"rate_C": 0.2}, {"temperature_C": 25})
        self.assertEqual(status, "insufficient_context")
        self.assertIn("rate_C", reasons[0])

    def test_context_hash_changes_with_experiment_or_knowledge_status(self):
        claim = KnowledgeClaim.new("project-1", "paper-a", "method", "使用EIS验证界面变化")
        builder = ContextBuilder()
        first = builder.build(stage="codex_assessment", task=_task(), project_context=_project_context(), claims=[claim])
        second = builder.build(stage="codex_assessment", task=_task(), project_context=_project_context(temperature_C=25), claims=[claim])
        third = builder.build(stage="codex_assessment", task=_task(), project_context=_project_context(), claims=[claim.reviewed("approved")])
        self.assertNotEqual(first.context_hash, second.context_hash)
        self.assertNotEqual(first.context_hash, third.context_hash)

    def test_online_sources_are_explicit_candidates(self):
        result = ContextBuilder().build(
            stage="codex_assessment",
            task=_task(),
            project_context=_project_context(),
            online_research={
                "sources": [{"title": "Paper", "url": "https://example.org/paper", "specific_claims": ["候选结论"]}],
                "knowledge_digest": [{"title": "摘要", "finding": "可能存在界面变化", "source_urls": ["https://example.org/paper"]}],
            },
        )
        packet = result.bundle["candidate_online_research"]
        self.assertEqual(packet["evidence_status"], "candidate_web_research")
        self.assertIn("候选证据必须", "；".join(result.bundle["active_constraints"]))

    def test_protected_context_over_budget_fails_instead_of_truncating(self):
        task = _task()
        task["goal"] = "容量" * 10000
        with self.assertRaises(ContextBudgetExceeded):
            ContextBuilder(max_input_tokens=1200).build(
                stage="codex_assessment",
                task=task,
                project_context=_project_context(),
            )


class ResearchStateTests(unittest.TestCase):
    def test_research_state_persists_user_decisions_and_candidate_guidance(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ResearchStore(Path(directory) / "research.sqlite3")
            project_id = store.create_project("Test", "P2O5", ["P2O5"])
            state = store.update_research_state(
                project_id,
                confirmed_decisions=["先复测平行电池"],
                user_corrections=["测试温度为60摄氏度"],
                rejected_hypotheses=[{"claim": "时间倒退", "reason": "原始时间单调"}],
            )
            self.assertEqual(state["row_version"], 1)
            updated = store.record_guidance_state(project_id, "run-1", {
                "data_facts": ["容量保持率为82%"],
                "hypotheses": [{"claim": "界面阻抗增加", "support": ["极化上升"], "against": [], "test": "进行EIS"}],
                "cannot_determine": ["缺少平行电池"],
                "next_experiments": [{"action": "复测平行电池"}],
            })
            self.assertEqual(updated["confirmed_decisions"], ["先复测平行电池"])
            self.assertEqual(updated["hypotheses"][-1]["status"], "candidate")
            self.assertEqual(updated["next_intent"], "复测平行电池")
            self.assertEqual(store.get_research_state(project_id)["last_run_id"], "run-1")


class _FakeAssessmentClient:
    last_context = None

    def __init__(self, *_args, **_kwargs):
        pass

    def evaluate_project(self, project_context, *_args, **_kwargs):
        _FakeAssessmentClient.last_context = dict(project_context)
        return "thread-test", {
            "assessment": "当前证据只支持候选解释。",
            "data_facts": ["程序已完成确定性分析"],
            "hypotheses": [{"claim": "界面变化", "support": ["极化变化"], "against": ["缺少EIS"], "test": "补充EIS"}],
            "cannot_determine": ["无法确定唯一原因"],
            "benchmark_comparisons": [],
            "theoretical_energy_assessment": {"status": "limited", "conclusion": "仅为活性物质口径"},
            "next_experiments": [{"action": "增加一组EIS测试", "variable": "循环状态", "expected_evidence": "阻抗变化"}],
        }


class WorkflowContextIntegrationTests(unittest.TestCase):
    def test_assessment_uses_managed_context_and_persists_cross_run_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workflow = ResearchWorkflow(root / "research.sqlite3", root / "outputs")
            project_id = workflow.create_project("Test", "P2O5|LiTaCl6", ["P2O5", "界面"])
            workflow.store.update_research_state(project_id, confirmed_decisions=["先检查数据完整性"])
            data_path = root / "data.csv"
            data_path.write_text("time,capacity,voltage\n0,0,3\n1,10,2\n2,0,3\n", encoding="utf-8")
            run = workflow.analyze_data(project_id, data_path, {"temperature_C": 60, "cell_type": "half-cell"})
            origin_dir = run.output_dir / "origin"
            origin_dir.mkdir(parents=True)
            (origin_dir / "origin_manifest.json").write_text(json.dumps({"status": "PLOT_BLOCKED", "reason": "test"}), encoding="utf-8")
            with patch("electrochem_harness_v2.workflow.CodexResearchClient", _FakeAssessmentClient):
                workflow.evaluate_with_codex(project_id, run.run_id)

            self.assertEqual(_FakeAssessmentClient.last_context["schema_version"], "2.0")
            self.assertEqual(_FakeAssessmentClient.last_context["research_memory"]["confirmed_decisions"], ["先检查数据完整性"])
            rendered = json.dumps(_FakeAssessmentClient.last_context, ensure_ascii=False)
            self.assertNotIn('"rows"', rendered)
            context_dir = run.output_dir / "contexts"
            self.assertTrue((context_dir / "codex_assessment.bundle.json").is_file())
            self.assertTrue((context_dir / "codex_assessment.manifest.json").is_file())
            guidance = json.loads((run.output_dir / "guidance.json").read_text(encoding="utf-8"))
            self.assertEqual(guidance["basis"]["managed_context"], "contexts/codex_assessment.bundle.json")
            self.assertEqual(workflow.store.get_research_state(project_id)["last_run_id"], run.run_id)
            report = workflow.build_report(project_id, run.run_id)
            self.assertIn("本轮Codex上下文与依据", report.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
