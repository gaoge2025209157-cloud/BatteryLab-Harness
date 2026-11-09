from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from electrochem_harness_v2.report import write_report
from electrochem_harness_v2.origin_adapter import OriginAdapter
from electrochem_harness_v2.workflow import ResearchWorkflow


class CodexObservabilityTests(unittest.TestCase):
    def test_activity_log_appends_bounded_stage_records_and_manifest_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workflow = ResearchWorkflow(root / "research.sqlite3", root / "outputs")
            output_dir = root / "run"
            output_dir.mkdir()
            (output_dir / "manifest.json").write_text(json.dumps({"artifacts": []}), encoding="utf-8")
            workflow._record_codex_activity(output_dir, "CODEX_WEB_SEARCH", "COMPLETED", "联网检索完成", {"topics": ["capacity"], "source_count": 2})
            workflow._record_codex_activity(output_dir, "CODEX_ASSESSMENT", "FAILED", "课题评估失败", {"error": "timeout"})
            activity = json.loads((output_dir / "codex_activity.json").read_text(encoding="utf-8"))
            manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual([row["stage"] for row in activity], ["CODEX_WEB_SEARCH", "CODEX_ASSESSMENT"])
            self.assertEqual(activity[-1]["details"]["error"], "timeout")
            self.assertIn("codex_activity.json", manifest["artifacts"])

    def test_report_exposes_codex_search_and_failure_records(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.html"
            write_report(
                path,
                {"status": "REPORT_READY_WITH_NO_COMPARABLE_PAPERS"},
                [],
                [],
                benchmark={"codex_activity": [
                    {"stage": "CODEX_WEB_SEARCH", "status": "COMPLETED", "message": "联网检索完成", "details": {"topics": ["capacity"], "source_count": 2}},
                    {"stage": "CODEX_ASSESSMENT", "status": "FAILED", "message": "课题评估失败", "details": {"error": "timeout"}},
                ]},
            )
            html = path.read_text(encoding="utf-8")
        self.assertIn("四、Codex 联网文献学习明细", html)
        self.assertNotIn("Codex 工作记录", html)
        self.assertNotIn("timeout", html)
        self.assertNotIn("FAILED", html)
    def test_run_all_persists_failed_codex_stage_in_activity_and_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data_path = root / "data.csv"
            data_path.write_text("time,capacity,voltage\n0,0,3\n1,10,2\n2,0,3\n", encoding="utf-8")
            workflow = ResearchWorkflow(root / "research.sqlite3", root / "outputs")
            workflow.origin_adapter = OriginAdapter(root / "missing.ps1", runner=lambda *_: None)

            def fail_benchmark(*_args, **_kwargs):
                raise RuntimeError("simulated search failure")

            workflow.research_benchmarks = fail_benchmark
            project_id = workflow.create_project("Test", "P2O5|LiTaCl6", ["P2O5"])
            result = workflow.run_all(project_id, data_path, {"temperature_C": 60}, use_codex_candidates=False, use_codex_assessment=False, use_online_research=True)
            activity = json.loads((result["run"].output_dir / "codex_activity.json").read_text(encoding="utf-8"))
            manifest = json.loads((result["run"].output_dir / "manifest.json").read_text(encoding="utf-8"))
            self.assertTrue(any(row["stage"] == "CODEX_WEB_SEARCH" and row["status"] == "FAILED" for row in activity))
            self.assertIn("Benchmark research: simulated search failure", manifest["errors"])

