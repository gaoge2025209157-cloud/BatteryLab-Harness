from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from electrochem_harness_v2.report import write_report
from electrochem_harness_v2.origin_adapter import OriginAdapter
from electrochem_harness_v2.models import KnowledgeClaim
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

    def test_invocation_recorder_creates_unique_file_and_database_row(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workflow = ResearchWorkflow(root / "research.sqlite3", root / "outputs")
            project_id = workflow.create_project("Test", "P2O5", [])
            recorder = workflow._invocation_recorder(project_id, "codex_assessment")
            recorder({
                "invocation_id": "codexinv-test",
                "created_at": "2026-01-01T00:00:00+00:00",
                "stage": "codex_assessment",
                "context_hash": "a" * 64,
                "request_hash": "b" * 64,
                "response_hash": None,
                "status": "FAILED",
            })
            path = root / "outputs" / project_id / "codex_invocations" / "codexinv-test.json"
            self.assertTrue(path.is_file())
            self.assertEqual(workflow.store.list_codex_invocations(project_id)[0]["status"], "FAILED")
            with self.assertRaises(Exception):
                recorder({
                    "invocation_id": "codexinv-test",
                    "created_at": "2026-01-01T00:00:01+00:00",
                    "stage": "codex_assessment",
                    "context_hash": "c" * 64,
                    "request_hash": "d" * 64,
                    "status": "COMPLETED",
                })

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
        self.assertIn("四、文献与知识依据", html)
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


    def test_offline_run_skips_metadata_search_and_every_codex_route(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data_path = root / "data.csv"
            data_path.write_text(
                "time,capacity,voltage\n0,0,3\n1,10,2\n2,0,3\n",
                encoding="utf-8",
            )
            workflow = ResearchWorkflow(root / "research.sqlite3", root / "outputs")
            workflow.origin_adapter = OriginAdapter(root / "missing.ps1", runner=lambda *_: None)
            workflow.search_literature = lambda *_args, **_kwargs: self.fail(
                "offline mode must not call metadata search"
            )
            project_id = workflow.create_project("Test", "Generic", ["private-topic"])

            result = workflow.run_all(
                project_id,
                data_path,
                {},
                keywords=["private-topic"],
                use_codex_candidates=False,
                use_online_research=False,
                use_codex_assessment=False,
            )

            self.assertEqual(result["search_status"], "SKIPPED")
            self.assertEqual(workflow.store.list_codex_invocations(project_id), [])

    def test_literature_fallback_uses_only_approved_stored_fields(self):
        claim = KnowledgeClaim.new(
            "project-1",
            "source-1",
            "method",
            "Approved method",
            conditions={
                "title": "Stored title",
                "tests": ["Stored test"],
                "question": "Stored question",
                "finding": "Stored finding",
                "how_to_borrow": "Stored action",
                "source_urls": ["https://example.org/paper"],
            },
            status="approved",
        )

        studies = ResearchWorkflow._derive_literature_studies([claim])

        self.assertEqual(studies[0]["tests"], ["Stored test"])
        self.assertEqual(studies[0]["how_to_borrow"], "Stored action")
        self.assertNotIn("P2O5", json.dumps(studies, ensure_ascii=False))
        self.assertNotIn("LiTaCl", json.dumps(studies, ensure_ascii=False))
