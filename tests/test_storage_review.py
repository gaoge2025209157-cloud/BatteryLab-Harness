from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from electrochem_harness_v2.models import KnowledgeClaim
from electrochem_harness_v2.storage import ResearchStore


class ResearchStoreReviewTests(unittest.TestCase):
    def test_candidate_requires_review_before_becoming_approved(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ResearchStore(Path(directory) / "research.sqlite3")
            project_id = store.create_project("P2O5 test", "P2O5|LiTaCl6|Li-In", ["P2O5"])
            claim = KnowledgeClaim.new(
                project_id=project_id,
                source_id="source-1",
                claim_type="performance",
                text="A reported capacity",
                metric_id="discharge_specific_capacity_mAh_g",
                value=152.2,
                unit="mAh/g",
                conditions={"temperature_C": 60},
                evidence_span_ids=["span-1"],
            )
            store.save_claim(claim)
            self.assertEqual(store.list_approved_claims(project_id), [])

            reviewed = store.review_claim(claim.claim_id, "approved", "researcher", "Verified against PDF")
            self.assertEqual(reviewed.status, "approved")
            self.assertEqual([item.claim_id for item in store.list_approved_claims(project_id)], [claim.claim_id])
            self.assertEqual(len(store.list_review_events(claim.claim_id)), 1)

    def test_review_history_is_append_only(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ResearchStore(Path(directory) / "research.sqlite3")
            project_id = store.create_project("P2O5 test", "P2O5|LiTaCl6|Li-In", ["P2O5"])
            claim = KnowledgeClaim.new(project_id, "source-1", "background", "A background fact")
            store.save_claim(claim)
            store.review_claim(claim.claim_id, "approved", "researcher", "first review")
            store.review_claim(claim.claim_id, "rejected", "researcher", "later rejected")
            self.assertEqual(len(store.list_review_events(claim.claim_id)), 2)
            self.assertEqual(store.get_claim(claim.claim_id).status, "rejected")

    def test_context_and_invocation_records_are_append_only(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ResearchStore(Path(directory) / "research.sqlite3")
            project_id = store.create_project("Test", "P2O5", [])
            base = {
                "context_id": "ctx-same-stage",
                "context_hash": "a" * 64,
                "input_tokens_estimated": 10,
                "created_at": "2026-01-01T00:00:00+00:00",
            }
            store.save_context_record(project_id, None, "stage", {**base, "record_id": "ctxrec-1"})
            store.save_context_record(project_id, None, "stage", {**base, "record_id": "ctxrec-2"})
            self.assertEqual(len(store.list_context_records(project_id)), 2)

            invocation = {
                "invocation_id": "codexinv-1",
                "context_hash": "b" * 64,
                "request_hash": "c" * 64,
                "response_hash": None,
                "status": "FAILED",
                "created_at": "2026-01-01T00:00:00+00:00",
            }
            store.save_codex_invocation(project_id, None, "stage", invocation)
            with self.assertRaises(sqlite3.IntegrityError):
                store.save_codex_invocation(project_id, None, "stage", {**invocation, "status": "COMPLETED"})
            self.assertEqual(store.list_codex_invocations(project_id)[0]["status"], "FAILED")

    def test_v3_context_table_migrates_without_deleting_existing_record(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "research.sqlite3"
            connection = sqlite3.connect(path)
            connection.executescript(
                "CREATE TABLE schema_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);"
                "INSERT INTO schema_meta VALUES('schema_version', '3');"
                "CREATE TABLE projects(project_id TEXT PRIMARY KEY, name TEXT NOT NULL, material_system TEXT NOT NULL, keywords_json TEXT NOT NULL, created_at TEXT NOT NULL);"
                "INSERT INTO projects VALUES('project-1', 'Test', 'P2O5', '[]', '2026-01-01');"
                "CREATE TABLE experiment_runs(run_id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(project_id), raw_data_sha256 TEXT NOT NULL, input_conditions_json TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL);"
                "CREATE TABLE context_records(context_id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(project_id), run_id TEXT REFERENCES experiment_runs(run_id), stage TEXT NOT NULL, context_hash TEXT NOT NULL, input_tokens_estimated INTEGER NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL);"
            )
            payload = json.dumps({"context_id": "ctx-old", "context_hash": "old"})
            connection.execute(
                "INSERT INTO context_records VALUES(?,?,?,?,?,?,?,?)",
                ("ctx-old", "project-1", None, "stage", "old", 1, payload, "2026-01-01"),
            )
            connection.commit()
            connection.close()

            store = ResearchStore(path)
            self.assertEqual(store.list_context_records("project-1")[0]["context_id"], "ctx-old")
            store.save_context_record("project-1", None, "stage", {
                "record_id": "ctxrec-new", "context_id": "ctx-old", "context_hash": "new",
                "input_tokens_estimated": 2, "created_at": "2026-01-02",
            })
            self.assertEqual(len(store.list_context_records("project-1")), 2)

    def test_scientifically_distinct_claim_values_have_distinct_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ResearchStore(Path(directory) / "research.sqlite3")
            project_id = store.create_project("Test", "Generic", [])
            first = KnowledgeClaim.new(
                project_id, "source-1", "performance", "Reported capacity",
                metric_id="capacity", value=100.0, unit="mAh/g",
                conditions={"temperature_C": 25},
            )
            second = KnowledgeClaim.new(
                project_id, "source-1", "performance", "Reported capacity",
                metric_id="capacity", value=120.0, unit="mAh/g",
                conditions={"temperature_C": 25},
            )
            store.save_claim(first)
            store.save_claim(second)

            self.assertNotEqual(first.claim_id, second.claim_id)
            self.assertEqual(len(store.list_claims(project_id)), 2)

    def test_updates_project_name_type_and_keywords_without_losing_unicode(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ResearchStore(Path(directory) / "research.sqlite3")
            project_id = store.create_project("初始课题", "卤化物电解质", ["LPSC"])
            updated = store.update_project(project_id, "P₂O₅-LPSC 固态电池", "P₂O₅｜LPSC｜Li-In", ["P₂O₅", "LPSC", "固态电池"])
        self.assertEqual(updated["name"], "P₂O₅-LPSC 固态电池")
        self.assertEqual(updated["material_system"], "P₂O₅｜LPSC｜Li-In")
        self.assertEqual(updated["keywords"], ["P₂O₅", "LPSC", "固态电池"])
