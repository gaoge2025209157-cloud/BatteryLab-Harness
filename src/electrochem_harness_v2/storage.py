"""SQLite storage with idempotent migrations and append-only review events."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import uuid
from typing import Iterator

from .models import KnowledgeClaim, ReviewEvent, SourceSpan


class ResearchStore:
    SCHEMA_VERSION = 2

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.migrate()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def migrate(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS projects (
                    project_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    material_system TEXT NOT NULL,
                    keywords_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS source_documents (
                    source_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(project_id),
                    sha256 TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    UNIQUE(project_id, sha256)
                );
                CREATE TABLE IF NOT EXISTS source_spans (
                    span_id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL REFERENCES source_documents(source_id),
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS knowledge_claims (
                    claim_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(project_id),
                    source_id TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('candidate', 'approved', 'rejected')),
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS review_events (
                    event_id TEXT PRIMARY KEY,
                    claim_id TEXT NOT NULL REFERENCES knowledge_claims(claim_id),
                    previous_status TEXT NOT NULL,
                    new_status TEXT NOT NULL,
                    reviewer TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    reviewed_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS experiment_runs (
                    run_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(project_id),
                    raw_data_sha256 TEXT NOT NULL,
                    input_conditions_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS analysis_artifacts (
                    artifact_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES experiment_runs(run_id),
                    kind TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS search_knowledge_cache (
                    fingerprint TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
            row = connection.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()
            if row is None:
                connection.execute("INSERT INTO schema_meta(key, value) VALUES('schema_version', ?)", (str(self.SCHEMA_VERSION),))
            elif int(row["value"]) > self.SCHEMA_VERSION:
                raise RuntimeError("Unsupported newer schema version: {}".format(row["value"]))
            elif int(row["value"]) < self.SCHEMA_VERSION:
                connection.execute("UPDATE schema_meta SET value=? WHERE key='schema_version'", (str(self.SCHEMA_VERSION),))

    def create_project(self, name: str, material_system: str, keywords: list[str]) -> str:
        if not name.strip() or not material_system.strip():
            raise ValueError("Project name and material system are required.")
        project_id = "project-" + uuid.uuid4().hex
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO projects(project_id, name, material_system, keywords_json, created_at) VALUES(?,?,?,?,?)",
                (project_id, name.strip(), material_system.strip(), json.dumps(list(keywords), ensure_ascii=False), datetime.now(timezone.utc).isoformat()),
            )
        return project_id

    def update_project(self, project_id: str, name: str, material_system: str, keywords: list[str]) -> dict:
        if not project_id.strip() or not name.strip() or not material_system.strip():
            raise ValueError("Project ID, name, and material system are required.")
        clean_keywords = [str(value).strip() for value in keywords if str(value).strip()]
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE projects SET name=?, material_system=?, keywords_json=? WHERE project_id=?",
                (name.strip(), material_system.strip(), json.dumps(clean_keywords, ensure_ascii=False), project_id),
            )
            if cursor.rowcount != 1:
                raise KeyError("Project does not exist: {}".format(project_id))
        return next(item for item in self.list_projects() if item["project_id"] == project_id)

    def list_projects(self) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute("SELECT project_id, name, material_system, keywords_json, created_at FROM projects ORDER BY created_at DESC").fetchall()
        return [{"project_id": row["project_id"], "name": row["name"], "material_system": row["material_system"], "keywords": json.loads(row["keywords_json"]), "created_at": row["created_at"]} for row in rows]

    def find_source(self, project_id: str, sha256: str):
        from .models import SourceDocument
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM source_documents WHERE project_id=? AND sha256=?", (project_id, sha256)
            ).fetchone()
        if row is None:
            return None
        return SourceDocument(**json.loads(row["payload"]))

    def save_source(self, document, spans=()):
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT source_id FROM source_documents WHERE project_id=? AND sha256=?",
                (document.project_id, document.sha256),
            ).fetchone()
            if existing:
                return str(existing["source_id"])
            connection.execute(
                "INSERT INTO source_documents(source_id, project_id, sha256, payload) VALUES(?,?,?,?)",
                (document.source_id, document.project_id, document.sha256, json.dumps(document.to_dict(), ensure_ascii=False, sort_keys=True)),
            )
            for span in spans:
                connection.execute(
                    "INSERT INTO source_spans(span_id, source_id, payload) VALUES(?,?,?)",
                    (span.span_id, span.source_id, json.dumps(span.to_dict(), ensure_ascii=False, sort_keys=True)),
                )
        return document.source_id

    def save_claim(self, claim: KnowledgeClaim) -> KnowledgeClaim:
        if claim.status != "candidate":
            raise ValueError("Newly extracted claims must start as candidate.")
        with self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO knowledge_claims(claim_id, project_id, source_id, status, payload) VALUES(?,?,?,?,?)",
                (claim.claim_id, claim.project_id, claim.source_id, claim.status, json.dumps(claim.to_dict(), ensure_ascii=False, sort_keys=True)),
            )
        return claim

    def list_source_spans(self, source_id: str) -> list[SourceSpan]:
        with self._connect() as connection:
            rows = connection.execute("SELECT payload FROM source_spans WHERE source_id=? ORDER BY span_id", (source_id,)).fetchall()
        spans = []
        for row in rows:
            payload = json.loads(row["payload"])
            payload["bbox"] = tuple(payload["bbox"]) if payload.get("bbox") else None
            payload["figure_ids"] = tuple(payload.get("figure_ids") or ())
            spans.append(SourceSpan(**payload))
        return spans

    def get_claim(self, claim_id: str) -> KnowledgeClaim:
        with self._connect() as connection:
            row = connection.execute("SELECT payload FROM knowledge_claims WHERE claim_id=?", (claim_id,)).fetchone()
        if row is None:
            raise KeyError("Claim does not exist: {}".format(claim_id))
        payload = json.loads(row["payload"])
        payload["evidence_span_ids"] = tuple(payload.get("evidence_span_ids") or ())
        payload["limitations"] = tuple(payload.get("limitations") or ())
        return KnowledgeClaim(**payload)

    def review_claim(self, claim_id: str, status: str, reviewer: str, reason: str) -> KnowledgeClaim:
        if status not in {"approved", "rejected"}:
            raise ValueError("Review status must be approved or rejected.")
        if not reviewer.strip() or not reason.strip():
            raise ValueError("Reviewer and review reason are required.")
        current = self.get_claim(claim_id)
        updated = current.reviewed(status)
        event = ReviewEvent.new(claim_id, current.status, status, reviewer.strip(), reason.strip())
        with self._connect() as connection:
            connection.execute(
                "UPDATE knowledge_claims SET status=?, payload=? WHERE claim_id=?",
                (updated.status, json.dumps(updated.to_dict(), ensure_ascii=False, sort_keys=True), claim_id),
            )
            connection.execute(
                "INSERT INTO review_events(event_id, claim_id, previous_status, new_status, reviewer, reason, reviewed_at, payload) VALUES(?,?,?,?,?,?,?,?)",
                (event.event_id, event.claim_id, event.previous_status, event.new_status, event.reviewer, event.reason, event.reviewed_at, json.dumps(event.to_dict(), ensure_ascii=False, sort_keys=True)),
            )
        return updated

    def review_curated_claims(self, project_id: str, status: str, reviewer: str, reason: str) -> list[KnowledgeClaim]:
        """Review the compact Codex digest as one audited batch, never raw candidates."""
        if status not in {"approved", "rejected"}:
            raise ValueError("Review status must be approved or rejected.")
        if not reviewer.strip() or not reason.strip():
            raise ValueError("Reviewer and review reason are required.")
        current_items = self.list_review_queue(project_id)
        reviewed: list[KnowledgeClaim] = []
        with self._connect() as connection:
            for current in current_items:
                if current.status != "candidate":
                    continue
                updated = current.reviewed(status)
                event = ReviewEvent.new(current.claim_id, current.status, status, reviewer.strip(), reason.strip())
                connection.execute(
                    "UPDATE knowledge_claims SET status=?, payload=? WHERE claim_id=?",
                    (updated.status, json.dumps(updated.to_dict(), ensure_ascii=False, sort_keys=True), current.claim_id),
                )
                connection.execute(
                    "INSERT INTO review_events(event_id, claim_id, previous_status, new_status, reviewer, reason, reviewed_at, payload) VALUES(?,?,?,?,?,?,?,?)",
                    (event.event_id, event.claim_id, event.previous_status, event.new_status, event.reviewer, event.reason, event.reviewed_at, json.dumps(event.to_dict(), ensure_ascii=False, sort_keys=True)),
                )
                reviewed.append(updated)
        return reviewed

    def list_approved_claims(self, project_id: str) -> list[KnowledgeClaim]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM knowledge_claims WHERE project_id=? AND status='approved' ORDER BY claim_id", (project_id,)
            ).fetchall()
        return [self._claim_from_row(row) for row in rows]

    def list_review_events(self, claim_id: str) -> list[ReviewEvent]:
        with self._connect() as connection:
            rows = connection.execute("SELECT payload FROM review_events WHERE claim_id=? ORDER BY reviewed_at, event_id", (claim_id,)).fetchall()
        return [ReviewEvent(**json.loads(row["payload"])) for row in rows]

    def list_claims(self, project_id: str) -> list[KnowledgeClaim]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM knowledge_claims WHERE project_id=? ORDER BY claim_id", (project_id,)
            ).fetchall()
        return [self._claim_from_row(row) for row in rows]

    def list_review_queue(self, project_id: str) -> list[KnowledgeClaim]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM knowledge_claims WHERE project_id=? AND status='candidate' ORDER BY claim_id", (project_id,)
            ).fetchall()
        claims = [self._claim_from_row(row) for row in rows]
        return [claim for claim in claims if (claim.conditions or {}).get("review_stage") == "codex_curated"]

    def create_run(self, project_id: str, raw_data_sha256: str, input_conditions: dict, status: str) -> str:
        run_id = "run-" + uuid.uuid4().hex
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO experiment_runs(run_id, project_id, raw_data_sha256, input_conditions_json, status, created_at) VALUES(?,?,?,?,?,?)",
                (run_id, project_id, raw_data_sha256, json.dumps(input_conditions, ensure_ascii=False, sort_keys=True), status, datetime.now(timezone.utc).isoformat()),
            )
        return run_id

    def get_run(self, run_id: str) -> dict:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM experiment_runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise KeyError("Run does not exist: {}".format(run_id))
        return {
            "run_id": row["run_id"], "project_id": row["project_id"], "raw_data_sha256": row["raw_data_sha256"],
            "input_conditions": json.loads(row["input_conditions_json"]), "status": row["status"], "created_at": row["created_at"],
        }

    def save_analysis_artifact(self, run_id: str, kind: str, payload: dict) -> str:
        artifact_id = "artifact-" + uuid.uuid4().hex
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO analysis_artifacts(artifact_id, run_id, kind, payload) VALUES(?,?,?,?)",
                (artifact_id, run_id, kind, json.dumps(payload, ensure_ascii=False, sort_keys=True)),
            )
        return artifact_id

    def save_search_cache(self, fingerprint: str, payload: dict) -> None:
        if not fingerprint.strip():
            raise ValueError("Search cache fingerprint is required.")
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO search_knowledge_cache(fingerprint, payload, updated_at) VALUES(?,?,?) ON CONFLICT(fingerprint) DO UPDATE SET payload=excluded.payload, updated_at=excluded.updated_at",
                (fingerprint, json.dumps(payload, ensure_ascii=False, sort_keys=True), datetime.now(timezone.utc).isoformat()),
            )

    def get_search_cache(self, fingerprint: str):
        with self._connect() as connection:
            row = connection.execute("SELECT payload FROM search_knowledge_cache WHERE fingerprint=?", (fingerprint,)).fetchone()
        return json.loads(row["payload"]) if row else None

    @staticmethod
    def _claim_from_row(row: sqlite3.Row) -> KnowledgeClaim:
        payload = json.loads(row["payload"])
        payload["evidence_span_ids"] = tuple(payload.get("evidence_span_ids") or ())
        payload["limitations"] = tuple(payload.get("limitations") or ())
        return KnowledgeClaim(**payload)
