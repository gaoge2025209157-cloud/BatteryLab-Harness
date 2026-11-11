from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from electrochem_harness_v2.analysis_dispatch import build_analysis_feature_packet
from electrochem_harness_v2.benchmarks import build_benchmark_topics
from electrochem_harness_v2.origin_adapter import OriginPlotResult
from electrochem_harness_v2.storage import ResearchStore
from electrochem_harness_v2.workflow import ResearchWorkflow


CV_POINTS = [
    {"potential_V": 0.0, "current_A": 0.0},
    {"potential_V": 1.0, "current_A": 1.0},
    {"potential_V": 2.0, "current_A": 3.0},
    {"potential_V": 3.0, "current_A": 1.0},
    {"potential_V": 2.0, "current_A": -1.0},
    {"potential_V": 1.0, "current_A": -2.0},
    {"potential_V": 0.0, "current_A": -0.5},
]
EIS_POINTS = [
    {"frequency_Hz": 10000.0, "z_real_ohm": 5.0, "z_imag_ohm": 0.2},
    {"frequency_Hz": 1000.0, "z_real_ohm": 6.0, "z_imag_ohm": -2.0},
    {"frequency_Hz": 100.0, "z_real_ohm": 8.0, "z_imag_ohm": -5.0},
    {"frequency_Hz": 10.0, "z_real_ohm": 12.0, "z_imag_ohm": -4.0},
    {"frequency_Hz": 1.0, "z_real_ohm": 16.0, "z_imag_ohm": -4.0},
    {"frequency_Hz": 0.1, "z_real_ohm": 20.0, "z_imag_ohm": -4.0},
]
GITT_POINTS = [
    {"time_s": 0.0, "current_A": 0.0, "voltage_V": 3.00},
    {"time_s": 1.0, "current_A": 0.0, "voltage_V": 3.00},
    {"time_s": 2.0, "current_A": 0.1, "voltage_V": 3.10},
    {"time_s": 3.0, "current_A": 0.1, "voltage_V": 3.20},
    {"time_s": 4.0, "current_A": 0.0, "voltage_V": 3.18},
    {"time_s": 5.0, "current_A": 0.0, "voltage_V": 3.16},
]


class FakeOrigin:
    def __init__(self):
        self.calls = 0

    def plot(self, run_dir, curves_csv, summary_csv, run_id, raw_data_sha256, initial_curves_csv=None):
        self.calls += 1
        base = Path(run_dir)
        origin = base / "origin"
        figures = base / "figures"
        origin.mkdir(parents=True, exist_ok=True)
        figures.mkdir(parents=True, exist_ok=True)
        project = origin / "electrochemistry.opju"
        project.write_bytes(b"opju")
        images = []
        for name in ("charge_discharge.png", "cycling.png"):
            path = figures / name
            path.write_bytes(b"png")
            images.append(path)
        manifest = origin / "origin_manifest.json"
        manifest.write_text(json.dumps({
            "run_id": run_id,
            "raw_data_sha256": raw_data_sha256,
            "status": "ORIGIN_PLOTTED",
            "reason": None,
            "figures": [path.name for path in images],
        }), encoding="utf-8")
        return OriginPlotResult("ORIGIN_PLOTTED", manifest, project, tuple(images), None)


class WorkflowCoreIntegrationTests(unittest.TestCase):
    def _workflow(self, root: Path) -> tuple[ResearchWorkflow, str]:
        workflow = ResearchWorkflow(root / "research.sqlite3", root / "outputs")
        workflow.origin_adapter = FakeOrigin()
        project_id = workflow.create_project("Test", "generic electrochemistry", ["test"])
        return workflow, project_id

    @staticmethod
    def _gcd_csv(root: Path, name: str = "gcd.csv", scale: float = 1.0) -> Path:
        path = root / name
        path.write_text(
            "time/s,specific capacity/mAh/g,voltage/V,current/A,cycle,direction\n"
            "0,0,3.0,0.001,1,charge\n"
            "3600,{charge},3.5,0.001,1,charge\n"
            "3601,0,3.4,-0.001,1,discharge\n"
            "7201,{discharge},3.0,-0.001,1,discharge\n"
            "7202,0,3.0,0.001,2,charge\n".format(charge=10 * scale, discharge=9 * scale),
            encoding="utf-8",
        )
        return path

    def test_gcd_conditions_reach_current_integration_and_all_methods_route(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workflow, project_id = self._workflow(root)
            gcd = workflow.analyze_data(project_id, self._gcd_csv(root), {"active_material_mass_mg": 10.0})
            payload = json.loads((gcd.output_dir / "analysis.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["analysis_type"], "gcd")
            self.assertGreater(payload["analysis"]["gcd_summary"]["integrated_segment_count"], 0)
            cases = [
                ("cv", CV_POINTS, {"scan_rate": 0.5}),
                ("eis", EIS_POINTS, {"tail_fraction": 0.5}),
                ("gitt", GITT_POINTS, {"current_threshold_A": 0.01}),
            ]
            for method, source, conditions in cases:
                run = workflow.analyze_data(project_id, source, conditions, method)
                envelope = json.loads((run.output_dir / "analysis.json").read_text(encoding="utf-8"))
                self.assertEqual(envelope["analysis_type"], method)

    def test_non_gcd_feature_packet_and_topics_respect_method_boundaries(self):
        packet = build_analysis_feature_packet({
            "analysis_type": "cv",
            "metadata": {"sha256": "a" * 64},
            "analysis": {"peak_separation_V": 0.4, "normalized_points": [1], "nested": {"rows": [2], "series": [3]}},
        })
        serialized = json.dumps(packet)
        self.assertNotIn("normalized_points", serialized)
        self.assertNotIn('"rows"', serialized)
        self.assertNotIn('"series"', serialized)
        cv_topics = " ".join(build_benchmark_topics("material", {"peak_separation_V": 0.4}, "cv")).lower()
        eis_topics = " ".join(build_benchmark_topics("material", {"charge_transfer_resistance_ohm": 4}, "eis")).lower()
        gitt_topics = " ".join(build_benchmark_topics("material", {"pulse_count": 2}, "gitt")).lower()
        self.assertNotIn("specific capacity", cv_topics)
        self.assertNotIn("theoretical specific energy", eis_topics)
        self.assertNotIn("diffusion coefficient", gitt_topics)

    def test_run_all_records_truthful_statuses_and_completed_list(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workflow, project_id = self._workflow(root)
            result = workflow.run_all(
                project_id, self._gcd_csv(root), {"active_material_mass_mg": 10},
                use_online_research=False, use_codex_candidates=False, use_codex_assessment=False,
            )
            run = workflow.store.get_run(result["run"].run_id)
            self.assertEqual(run["status"], "COMPLETED")
            manifest = json.loads((result["run"].output_dir / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["stage_statuses"]["DATA"], "COMPLETED")
            self.assertEqual(manifest["stage_statuses"]["SEARCH"], "SKIPPED")
            self.assertNotIn("SEARCH", manifest["completed_stages"])
            self.assertEqual(set(manifest["stage_statuses"]), {
                "SEARCH", "PDF", "CODEX_PDF", "DATA", "BENCHMARK_RESEARCH",
                "CODEX_KNOWLEDGE", "ORIGIN", "CODEX_ASSESSMENT", "REPORT",
            })

    def test_cancellation_preserves_analysis_and_resume_validates_hash_and_attempts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workflow, project_id = self._workflow(root)
            source = self._gcd_csv(root)
            checks = {"count": 0}

            def cancel_after_data():
                checks["count"] += 1
                return checks["count"] >= 5

            cancelled = workflow.run_all(
                project_id, source, {"active_material_mass_mg": 10},
                use_online_research=False, use_codex_candidates=False, use_codex_assessment=False,
                cancel_requested=cancel_after_data,
            )
            run_id = cancelled["run"].run_id
            self.assertEqual(workflow.store.get_run(run_id)["status"], "CANCELLED")
            self.assertTrue((cancelled["run"].output_dir / "analysis.json").is_file())
            data_attempt = workflow.store.get_run_stage(run_id, "DATA")["attempt"]
            resumed = workflow.resume_run(
                project_id, run_id, source,
                use_online_research=False, use_codex_candidates=False, use_codex_assessment=False,
            )
            self.assertEqual(workflow.store.get_run(run_id)["status"], "COMPLETED")
            self.assertEqual(workflow.store.get_run_stage(run_id, "DATA")["attempt"], data_attempt)
            self.assertGreaterEqual(workflow.store.get_run_stage(run_id, "ORIGIN")["attempt"], 2)
            changed = self._gcd_csv(root, "changed.csv", 2.0)
            with self.assertRaisesRegex(ValueError, "raw-data hash"):
                workflow.resume_run(project_id, run_id, changed)
            with self.assertRaisesRegex(ValueError, "original experiment conditions"):
                workflow.resume_run(project_id, run_id, source, {"active_material_mass_mg": 20})
            with self.assertRaisesRegex(ValueError, "original analysis_type"):
                workflow.resume_run(project_id, run_id, source, analysis_type="cv")
            self.assertTrue(resumed["report"].is_file())

    def test_non_gcd_origin_is_audited_skip_without_origin_engine(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workflow, project_id = self._workflow(root)
            fake_origin = workflow.origin_adapter
            result = workflow.run_all(
                project_id, CV_POINTS, {"scan_rate": 0.5}, analysis_type="cv",
                use_online_research=False, use_codex_candidates=False, use_codex_assessment=False,
            )
            self.assertEqual(fake_origin.calls, 0)
            stage = workflow.store.get_run_stage(result["run"].run_id, "ORIGIN")
            self.assertEqual(stage["status"], "SKIPPED")
            manifest = json.loads((result["run"].output_dir / "origin" / "origin_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], "PLOT_NOT_AVAILABLE_FOR_METHOD")

    def test_segment_review_is_audited_recomputed_and_used_by_origin(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workflow, project_id = self._workflow(root)
            source = self._gcd_csv(root)
            run = workflow.analyze_data(project_id, source, {"active_material_mass_mg": 10})
            reviewed = workflow.review_gcd_segments(project_id, run.run_id, source, [
                {"segment_id": "segment-1", "status": "approved", "direction": "charge", "reviewer": "chemist", "reason": "instrument step"},
                {"segment_id": "segment-2", "status": "approved", "direction": "discharge", "reviewer": "chemist", "reason": "instrument step"},
            ])
            self.assertTrue(all(row["review_status"] == "reviewed" for row in reviewed["analysis"]["segments"][:2]))
            self.assertEqual(reviewed["analysis"]["gcd_summary"]["complete_cycle_count"], 1)
            workflow.prepare_origin(project_id, run.run_id, source)
            self.assertEqual(workflow.origin_adapter.calls, 1)
            audit = json.loads((run.output_dir / "segment_review.json").read_text(encoding="utf-8"))
            self.assertEqual(len(audit["events"]), 2)

    def test_segment_review_invalidates_and_resume_rebuilds_downstream_stages(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workflow, project_id = self._workflow(root)
            source = self._gcd_csv(root)
            initial = workflow.run_all(
                project_id,
                source,
                {"active_material_mass_mg": 10},
                use_online_research=False,
                use_codex_candidates=False,
                use_codex_assessment=False,
            )
            run_id = initial["run"].run_id
            origin_attempt = workflow.store.get_run_stage(run_id, "ORIGIN")["attempt"]

            workflow.review_gcd_segments(project_id, run_id, source, [
                {"segment_id": "segment-1", "status": "approved", "direction": "charge", "reviewer": "chemist", "reason": "instrument step"},
                {"segment_id": "segment-2", "status": "approved", "direction": "discharge", "reviewer": "chemist", "reason": "instrument step"},
            ])

            self.assertEqual(workflow.store.get_run(run_id)["status"], "PARTIAL")
            self.assertEqual(workflow.store.get_run_stage(run_id, "ORIGIN")["status"], "PARTIAL")
            resumed = workflow.resume_run(
                project_id,
                run_id,
                source,
                use_online_research=False,
                use_codex_candidates=False,
                use_codex_assessment=False,
            )
            self.assertEqual(workflow.store.get_run(run_id)["status"], "COMPLETED")
            self.assertGreater(workflow.store.get_run_stage(run_id, "ORIGIN")["attempt"], origin_attempt)
            self.assertTrue(resumed["report"].is_file())

    def test_summarize_runs_persists_hashed_report_envelope_without_significance(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workflow, project_id = self._workflow(root)
            runs = [
                workflow.analyze_data(project_id, self._gcd_csv(root, "a.csv", 1.0), {"active_material_mass_mg": 10}),
                workflow.analyze_data(project_id, self._gcd_csv(root, "b.csv", 1.1), {"active_material_mass_mg": 10}),
            ]
            envelope = workflow.summarize_runs(
                project_id, [run.run_id for run in runs],
                "gcd_summary.latest_complete_discharge_capacity_mAh_g",
            )
            self.assertEqual(envelope["analysis_type"], "replicates")
            self.assertEqual(envelope["analysis"]["n"], 2)
            self.assertIsNone(envelope["analysis"]["significance_conclusion"])
            digest = envelope["metadata"]["replicate_hash"]
            replicate_root = root / "outputs" / project_id / "replicates"
            self.assertTrue((replicate_root / ("replicate-" + digest + ".json")).is_file())
            self.assertTrue((replicate_root / ("replicate-" + digest + ".html")).is_file())
            cv_run = workflow.analyze_data(project_id, CV_POINTS, {}, "cv")
            with self.assertRaisesRegex(ValueError, "same analysis_type"):
                workflow.summarize_runs(
                    project_id,
                    [runs[0].run_id, cv_run.run_id],
                    "gcd_summary.latest_complete_discharge_capacity_mAh_g",
                )

    def test_core_data_failure_sets_failed_run_and_skips_downstream_stages(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workflow, project_id = self._workflow(root)
            invalid = root / "invalid.csv"
            invalid.write_text("not,a,supported,experiment\n1,2,3,4\n", encoding="utf-8")
            result = workflow.run_all(
                project_id, invalid, {},
                use_online_research=False, use_codex_candidates=False, use_codex_assessment=False,
            )
            run_id = result["run"].run_id
            self.assertEqual(workflow.store.get_run(run_id)["status"], "FAILED")
            statuses = {row["stage"]: row["status"] for row in workflow.store.list_run_stages(run_id)}
            self.assertEqual(statuses["DATA"], "FAILED")
            self.assertTrue(all(statuses[stage] == "SKIPPED" for stage in (
                "BENCHMARK_RESEARCH", "CODEX_KNOWLEDGE", "ORIGIN", "CODEX_ASSESSMENT", "REPORT",
            )))

    def test_research_cache_envelope_distinguishes_fresh_stale_and_incompatible(self):
        class FakeSearch:
            calls = 0

            def search(self, keywords, rows=5):
                type(self).calls += 1
                return type("Result", (), {"query": " ".join(keywords), "searched_at": "now", "status": "LITERATURE_SEARCHED", "error": None, "records": []})()

        class FakeCodex:
            calls = 0

            def __init__(self, *args, **kwargs):
                pass

            def research_online(self, context, topics, records):
                type(self).calls += 1
                return {
                    "sources": [], "priority_sources": [], "knowledge_digest": [],
                    "research_synthesis": {}, "commercial_batteries": [],
                    "mainstream_systems": [], "standards": [], "literature_studies": [],
                }

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workflow, project_id = self._workflow(root)
            run = workflow.analyze_data(project_id, self._gcd_csv(root), {"active_material_mass_mg": 10})
            with patch("electrochem_harness_v2.search.LiteratureSearchAdapter", FakeSearch), patch("electrochem_harness_v2.workflow.CodexResearchClient", FakeCodex):
                first = workflow.research_benchmarks(project_id, run.run_id, ["test"])
                second = workflow.research_benchmarks(project_id, run.run_id, ["test"])
                self.assertEqual(second["cache_status"], "fresh")
                self.assertTrue(second["cache_reused"])
                workflow.store.update_research_state(
                    project_id, confirmed_decisions=["new researcher decision"]
                )
                changed_context = workflow.research_benchmarks(project_id, run.run_id, ["test"])
                self.assertEqual(changed_context["cache_status"], "incompatible")
                key = first["fingerprint"]
                entry = workflow.store.get_search_cache(key)
                entry["expires_at"] = "2000-01-01T00:00:00+00:00"
                workflow.store.save_search_cache(key, entry)
                stale = workflow.research_benchmarks(project_id, run.run_id, ["test"])
                self.assertEqual(stale["cache_status"], "stale")
                workflow.store.save_search_cache(key, {"legacy": "bare-cache"})
                incompatible = workflow.research_benchmarks(project_id, run.run_id, ["test"])
                self.assertEqual(incompatible["cache_status"], "incompatible")
                self.assertEqual(FakeCodex.calls, 4)
            activity = json.loads((run.output_dir / "codex_activity.json").read_text(encoding="utf-8"))
            classifications = [row["details"].get("cache_status") for row in activity if row["stage"] == "CODEX_WEB_SEARCH" and row["status"] == "STARTED"]
            self.assertEqual(classifications, ["incompatible", "fresh", "incompatible", "stale", "incompatible"])


class NonDestructiveMigrationTests(unittest.TestCase):
    def test_coexisting_legacy_context_tables_are_uniquely_archived_and_all_copied(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "research.sqlite3"
            with closing(sqlite3.connect(path)) as connection:
                connection.executescript(
                    "CREATE TABLE schema_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);"
                    "INSERT INTO schema_meta VALUES('schema_version', '3');"
                    "CREATE TABLE projects(project_id TEXT PRIMARY KEY, name TEXT NOT NULL, material_system TEXT NOT NULL, keywords_json TEXT NOT NULL, created_at TEXT NOT NULL);"
                    "INSERT INTO projects VALUES('project-1', 'Test', 'P2O5', '[]', '2026-01-01');"
                    "CREATE TABLE experiment_runs(run_id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(project_id), raw_data_sha256 TEXT NOT NULL, input_conditions_json TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL);"
                    "CREATE TABLE context_records(context_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, run_id TEXT, stage TEXT NOT NULL, context_hash TEXT NOT NULL, input_tokens_estimated INTEGER NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL);"
                    "CREATE TABLE context_records_v3_archive(context_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, run_id TEXT, stage TEXT NOT NULL, context_hash TEXT NOT NULL, input_tokens_estimated INTEGER NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL);"
                )
                for table, digest, created in (("context_records", "newer", "2026-01-02"), ("context_records_v3_archive", "older", "2026-01-01")):
                    payload = json.dumps({"context_id": "ctx-same", "context_hash": digest, "history": digest})
                    connection.execute(
                        "INSERT INTO {} VALUES(?,?,?,?,?,?,?,?)".format(table),
                        ("ctx-same", "project-1", None, "stage", digest, 1, payload, created),
                    )
                connection.commit()
            store = ResearchStore(path)
            records = store.list_context_records("project-1")
            self.assertEqual({row["history"] for row in records}, {"older", "newer"})
            self.assertEqual(len({row["record_id"] for row in records}), 2)
            with closing(sqlite3.connect(path)) as connection:
                tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertIn("context_records_v3_archive", tables)
            self.assertIn("context_records_v3_archive_2", tables)


if __name__ == "__main__":
    unittest.main()
