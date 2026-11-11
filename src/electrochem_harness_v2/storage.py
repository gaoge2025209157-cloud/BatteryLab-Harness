"""SQLite storage with idempotent migrations and append-only review events."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import sqlite3
import uuid
from typing import Any, Iterator

from .models import KnowledgeClaim, ReviewEvent, SourceSpan


class ResearchStore:
    SCHEMA_VERSION = 5
    RUN_STATUSES = frozenset({"PENDING", "RUNNING", "COMPLETED", "PARTIAL", "FAILED", "SKIPPED", "CANCELLED"})
    TERMINAL_STAGE_STATUSES = frozenset({"COMPLETED", "PARTIAL", "FAILED", "SKIPPED", "CANCELLED"})
    MAX_STAGE_ERROR_LENGTH = 2000
    _SECRET_RE = re.compile(
        r"(?i)(?:bearer\s+[A-Za-z0-9._~+/=-]+|(?:api[_-]?key|password|passwd|secret|token|credential)[\"']?\s*[:=]\s*[\"']?[^\s,;]+|sk-[A-Za-z0-9_-]{8,})"
    )
    _WINDOWS_PATH_RE = re.compile(r"(?i)(?<![\w])(?:[A-Z]:\\|\\\\)[^\r\n\t\"']+")
    _POSIX_PATH_RE = re.compile(r"(?<![\w.])/(?:Users|home|tmp|var|opt|etc|mnt|srv|root)/[^\r\n\t\"']+")
    _POINT_DATA_KEYS = frozenset({
        "raw_data", "raw_points", "data_points", "datapoints", "points", "samples",
        "measurements", "series", "pointwise_data", "raw_series", "rows", "raw_rows",
        "records", "curve", "curves", "trace", "traces", "values", "x_values", "y_values",
    })

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.migrate()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _existing_schema_version(self) -> tuple[int | None, bool]:
        """Return the declared version and whether an existing DB has user tables."""
        if not self.path.exists() or self.path.stat().st_size == 0:
            return None, False
        connection = sqlite3.connect(self.path)
        try:
            tables = {
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                ).fetchall()
            }
            if not tables:
                return None, False
            if "schema_meta" not in tables:
                return 0, True
            row = connection.execute(
                "SELECT value FROM schema_meta WHERE key='schema_version'"
            ).fetchone()
            return (int(row[0]) if row else 0), True
        finally:
            connection.close()

    def _backup_before_migration(self, old_version: int) -> Path:
        """Create one consistent SQLite backup for each source schema version."""
        backup_dir = self.path.parent / "backups"
        backup_path = backup_dir / f"{self.path.name}.v{old_version}.sqlite3"
        if backup_path.exists():
            return backup_path
        backup_dir.mkdir(parents=True, exist_ok=True)
        temporary = backup_dir / f".{backup_path.name}.{uuid.uuid4().hex}.tmp"
        source: sqlite3.Connection | None = None
        destination: sqlite3.Connection | None = None
        try:
            try:
                source = sqlite3.connect(self.path)
                destination = sqlite3.connect(temporary)
                source.backup(destination)
                destination.commit()
            finally:
                if destination is not None:
                    destination.close()
                if source is not None:
                    source.close()
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        try:
            os.replace(temporary, backup_path)
        except Exception:
            temporary.unlink(missing_ok=True)
            if not backup_path.exists():
                raise
        return backup_path

    @staticmethod
    def _table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
        return {str(row["name"]) for row in connection.execute(f"PRAGMA table_info({table})").fetchall()}

    def migrate(self) -> None:
        old_version, has_existing_tables = self._existing_schema_version()
        if old_version is not None and old_version > self.SCHEMA_VERSION:
            raise RuntimeError(f"Unsupported newer schema version: {old_version}")
        if has_existing_tables and old_version is not None and old_version < self.SCHEMA_VERSION:
            self._backup_before_migration(old_version)

        status_check = "('PENDING','RUNNING','COMPLETED','PARTIAL','FAILED','SKIPPED','CANCELLED')"
        table_statements = [
            "CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
            "CREATE TABLE IF NOT EXISTS projects (project_id TEXT PRIMARY KEY, name TEXT NOT NULL, material_system TEXT NOT NULL, keywords_json TEXT NOT NULL, created_at TEXT NOT NULL)",
            "CREATE TABLE IF NOT EXISTS source_documents (source_id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(project_id), sha256 TEXT NOT NULL, payload TEXT NOT NULL, UNIQUE(project_id, sha256))",
            "CREATE TABLE IF NOT EXISTS source_spans (span_id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES source_documents(source_id), payload TEXT NOT NULL)",
            "CREATE TABLE IF NOT EXISTS knowledge_claims (claim_id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(project_id), source_id TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('candidate','approved','rejected')), payload TEXT NOT NULL)",
            "CREATE TABLE IF NOT EXISTS review_events (event_id TEXT PRIMARY KEY, claim_id TEXT NOT NULL REFERENCES knowledge_claims(claim_id), previous_status TEXT NOT NULL, new_status TEXT NOT NULL, reviewer TEXT NOT NULL, reason TEXT NOT NULL, reviewed_at TEXT NOT NULL, payload TEXT NOT NULL)",
            f"CREATE TABLE IF NOT EXISTS experiment_runs (run_id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(project_id), raw_data_sha256 TEXT NOT NULL, input_conditions_json TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN {status_check}), legacy_status TEXT, created_at TEXT NOT NULL)",
            "CREATE TABLE IF NOT EXISTS analysis_artifacts (artifact_id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES experiment_runs(run_id), kind TEXT NOT NULL, payload TEXT NOT NULL)",
            "CREATE TABLE IF NOT EXISTS search_knowledge_cache (fingerprint TEXT PRIMARY KEY, payload TEXT NOT NULL, updated_at TEXT NOT NULL)",
            "CREATE TABLE IF NOT EXISTS research_states (project_id TEXT PRIMARY KEY REFERENCES projects(project_id), payload TEXT NOT NULL, updated_at TEXT NOT NULL)",
            "CREATE TABLE IF NOT EXISTS codex_invocations (invocation_id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(project_id), run_id TEXT REFERENCES experiment_runs(run_id), stage TEXT NOT NULL, context_hash TEXT NOT NULL, request_hash TEXT NOT NULL, response_hash TEXT, status TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL)",
            f"CREATE TABLE IF NOT EXISTS run_stages (run_id TEXT NOT NULL REFERENCES experiment_runs(run_id), stage TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN {status_check}), attempt INTEGER NOT NULL CHECK(attempt > 0), started_at TEXT, finished_at TEXT, error TEXT, artifact_paths_json TEXT NOT NULL DEFAULT '[]', recoverable_input_json TEXT NOT NULL DEFAULT '{{}}', updated_at TEXT NOT NULL, PRIMARY KEY(run_id, stage))",
            f"CREATE TABLE IF NOT EXISTS run_stage_events (event_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, stage TEXT NOT NULL, attempt INTEGER NOT NULL CHECK(attempt > 0), previous_status TEXT CHECK(previous_status IS NULL OR previous_status IN {status_check}), new_status TEXT NOT NULL CHECK(new_status IN {status_check}), error TEXT, artifact_paths_json TEXT NOT NULL DEFAULT '[]', recoverable_input_json TEXT NOT NULL DEFAULT '{{}}', created_at TEXT NOT NULL, FOREIGN KEY(run_id, stage) REFERENCES run_stages(run_id, stage))",
        ]
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            for statement in table_statements:
                connection.execute(statement)

            tables = {
                str(row["name"])
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            }
            legacy_context_tables: list[str] = []
            if "context_records" in tables and "record_id" not in self._table_columns(connection, "context_records"):
                # Never drop an audit table. Move the legacy table to a unique,
                # immutable archive even when an older archive already exists.
                suffix = 1
                archive_name = "context_records_v3_archive"
                while archive_name in tables:
                    suffix += 1
                    archive_name = "context_records_v3_archive_{}".format(suffix)
                connection.execute('ALTER TABLE context_records RENAME TO "{}"'.format(archive_name))
                tables.discard("context_records")
                tables.add(archive_name)
            legacy_context_tables = sorted(
                name for name in tables
                if name == "context_records_v3_archive" or name.startswith("context_records_v3_archive_")
            )
            if "context_records" not in tables:
                connection.execute(
                    "CREATE TABLE context_records (record_id TEXT PRIMARY KEY, context_id TEXT NOT NULL, project_id TEXT NOT NULL REFERENCES projects(project_id), run_id TEXT REFERENCES experiment_runs(run_id), stage TEXT NOT NULL, context_hash TEXT NOT NULL, input_tokens_estimated INTEGER NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL)"
                )
            for archive_name in legacy_context_tables:
                columns = self._table_columns(connection, archive_name)
                required = {"context_id", "project_id", "run_id", "stage", "context_hash", "input_tokens_estimated", "payload", "created_at"}
                if not required.issubset(columns):
                    continue
                rows = connection.execute(
                    'SELECT rowid AS legacy_rowid, context_id, project_id, run_id, stage, context_hash, input_tokens_estimated, payload, created_at FROM "{}" ORDER BY rowid'.format(archive_name)
                ).fetchall()
                for row in rows:
                    record_seed = "{}:{}:{}".format(archive_name, row["legacy_rowid"], row["context_id"])
                    record_id = "ctxrec-legacy-" + hashlib.sha256(record_seed.encode("utf-8")).hexdigest()
                    exists = connection.execute(
                        "SELECT 1 FROM context_records WHERE record_id=?", (record_id,)
                    ).fetchone()
                    if exists is not None:
                        continue
                    stored_payload = json.loads(row["payload"])
                    if isinstance(stored_payload, dict):
                        stored_payload = dict(stored_payload)
                        stored_payload["record_id"] = record_id
                        stored_payload.setdefault("context_id", row["context_id"])
                    connection.execute(
                        "INSERT INTO context_records(record_id, context_id, project_id, run_id, stage, context_hash, input_tokens_estimated, payload, created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                        (
                            record_id, row["context_id"], row["project_id"], row["run_id"], row["stage"],
                            row["context_hash"], row["input_tokens_estimated"],
                            json.dumps(stored_payload, ensure_ascii=False, sort_keys=True), row["created_at"],
                        ),
                    )
            if "legacy_status" not in self._table_columns(connection, "experiment_runs"):
                connection.execute("ALTER TABLE experiment_runs ADD COLUMN legacy_status TEXT")
            connection.execute(
                f"UPDATE experiment_runs SET legacy_status=status, status=CASE UPPER(status) "
                "WHEN 'NEEDS_REVIEW' THEN 'PENDING' WHEN 'DATA_ANALYZED' THEN 'COMPLETED' "
                f"WHEN 'PENDING' THEN 'PENDING' WHEN 'RUNNING' THEN 'RUNNING' WHEN 'COMPLETED' THEN 'COMPLETED' "
                "WHEN 'PARTIAL' THEN 'PARTIAL' WHEN 'FAILED' THEN 'FAILED' WHEN 'SKIPPED' THEN 'SKIPPED' "
                f"WHEN 'CANCELLED' THEN 'CANCELLED' ELSE 'FAILED' END WHERE status NOT IN {status_check}"
            )
            connection.execute("CREATE INDEX IF NOT EXISTS context_records_project_run ON context_records(project_id, run_id, created_at)")
            connection.execute("CREATE INDEX IF NOT EXISTS run_stages_run ON run_stages(run_id, updated_at)")
            connection.execute("CREATE INDEX IF NOT EXISTS run_stage_events_run_stage ON run_stage_events(run_id, stage, created_at, event_id)")
            connection.execute(
                "CREATE TRIGGER IF NOT EXISTS run_stage_events_no_update BEFORE UPDATE ON run_stage_events BEGIN SELECT RAISE(ABORT, 'run stage events are append-only'); END"
            )
            connection.execute(
                "CREATE TRIGGER IF NOT EXISTS run_stage_events_no_delete BEFORE DELETE ON run_stage_events BEGIN SELECT RAISE(ABORT, 'run stage events are append-only'); END"
            )
            # v3/v4 run tables had no CHECK constraint. Triggers enforce the v5
            # status domain for future writes without rebuilding or dropping rows.
            connection.execute(
                f"CREATE TRIGGER IF NOT EXISTS experiment_runs_status_insert BEFORE INSERT ON experiment_runs WHEN NEW.status NOT IN {status_check} BEGIN SELECT RAISE(ABORT, 'invalid run status'); END"
            )
            connection.execute(
                f"CREATE TRIGGER IF NOT EXISTS experiment_runs_status_update BEFORE UPDATE OF status ON experiment_runs WHEN NEW.status NOT IN {status_check} BEGIN SELECT RAISE(ABORT, 'invalid run status'); END"
            )
            row = connection.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()
            if row is None:
                connection.execute("INSERT INTO schema_meta(key, value) VALUES('schema_version', ?)", (str(self.SCHEMA_VERSION),))
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

    @classmethod
    def _validate_status(cls, status: str, *, terminal: bool = False) -> str:
        normalized = str(status or "").strip().upper()
        allowed = cls.TERMINAL_STAGE_STATUSES if terminal else cls.RUN_STATUSES
        if normalized not in allowed:
            raise ValueError("Status must be one of: {}".format(", ".join(sorted(allowed))))
        return normalized

    @classmethod
    def _sanitize_text(cls, value: str) -> str:
        clean = cls._SECRET_RE.sub("[REDACTED_SECRET]", str(value))
        clean = cls._WINDOWS_PATH_RE.sub("[REDACTED_PATH]", clean)
        clean = cls._POSIX_PATH_RE.sub("[REDACTED_PATH]", clean)
        return clean[: cls.MAX_STAGE_ERROR_LENGTH]

    @classmethod
    def _sanitize_recoverable_input(cls, value: dict | None) -> dict:
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise ValueError("Recoverable input must be a JSON object.")

        def clean(item: Any, key: str = "") -> Any:
            lowered = key.lower().replace("-", "_")
            if lowered in cls._POINT_DATA_KEYS:
                return "[OMITTED_POINT_DATA]"
            if any(marker in lowered for marker in ("password", "passwd", "secret", "token", "api_key", "apikey", "credential")):
                return "[REDACTED_SECRET]"
            if isinstance(item, dict):
                return {str(child_key): clean(child_value, str(child_key)) for child_key, child_value in item.items()}
            if isinstance(item, (list, tuple)):
                return [clean(child, key) for child in item]
            if isinstance(item, str):
                return cls._sanitize_text(item)
            if item is None or isinstance(item, (bool, int, float)):
                return item
            return str(item)

        sanitized = clean(value)
        # Validate serializability here so no transaction can be partially applied.
        json.dumps(sanitized, ensure_ascii=False, sort_keys=True)
        return sanitized

    @staticmethod
    def _normalize_artifact_paths(paths: list[str] | tuple[str, ...] | str | Path | None) -> list[str]:
        normalized: list[str] = []
        candidates = (paths,) if isinstance(paths, (str, Path)) else (paths or ())
        for raw in candidates:
            value = str(raw).strip().replace("\\", "/")
            windows_path = PureWindowsPath(str(raw))
            posix_path = PurePosixPath(value)
            if (
                not value
                or windows_path.is_absolute()
                or posix_path.is_absolute()
                or windows_path.drive
                or ".." in posix_path.parts
            ):
                raise ValueError("Artifact paths must be relative and remain inside the run directory.")
            normalized.append(posix_path.as_posix())
        return list(dict.fromkeys(normalized))

    @staticmethod
    def _run_from_row(row: sqlite3.Row) -> dict:
        return {
            "run_id": row["run_id"],
            "project_id": row["project_id"],
            "raw_data_sha256": row["raw_data_sha256"],
            "input_conditions": json.loads(row["input_conditions_json"]),
            "status": row["status"],
            "created_at": row["created_at"],
        }

    @staticmethod
    def _stage_from_row(row: sqlite3.Row) -> dict:
        return {
            "run_id": row["run_id"],
            "stage": row["stage"],
            "status": row["status"],
            "attempt": int(row["attempt"]),
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
            "error": row["error"],
            "artifact_paths": json.loads(row["artifact_paths_json"]),
            "recoverable_input": json.loads(row["recoverable_input_json"]),
            "updated_at": row["updated_at"],
        }

    def create_run(self, project_id: str, raw_data_sha256: str, input_conditions: dict, status: str) -> str:
        # Compatibility for the current workflow while persisted v5 states stay finite.
        normalized = {"DATA_ANALYZED": "COMPLETED", "NEEDS_REVIEW": "PENDING"}.get(
            str(status or "").strip().upper(), str(status or "").strip().upper()
        )
        normalized = self._validate_status(normalized)
        run_id = "run-" + uuid.uuid4().hex
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO experiment_runs(run_id, project_id, raw_data_sha256, input_conditions_json, status, created_at) VALUES(?,?,?,?,?,?)",
                (run_id, project_id, raw_data_sha256, json.dumps(input_conditions, ensure_ascii=False, sort_keys=True), normalized, datetime.now(timezone.utc).isoformat()),
            )
        return run_id

    def get_run(self, run_id: str) -> dict:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM experiment_runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise KeyError("Run does not exist: {}".format(run_id))
        return self._run_from_row(row)

    def list_runs(self, project_id: str | None = None, status: str | None = None) -> list[dict]:
        clauses: list[str] = []
        parameters: list[str] = []
        if project_id is not None:
            clauses.append("project_id=?")
            parameters.append(project_id)
        if status is not None:
            clauses.append("status=?")
            parameters.append(self._validate_status(status))
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM experiment_runs" + where + " ORDER BY created_at DESC, run_id DESC",
                parameters,
            ).fetchall()
        return [self._run_from_row(row) for row in rows]

    def update_run_status(self, run_id: str, status: str) -> dict:
        normalized = self._validate_status(status)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                "UPDATE experiment_runs SET status=? WHERE run_id=?", (normalized, run_id)
            )
            if cursor.rowcount != 1:
                raise KeyError("Run does not exist: {}".format(run_id))
            row = connection.execute("SELECT * FROM experiment_runs WHERE run_id=?", (run_id,)).fetchone()
        return self._run_from_row(row)

    def start_run_stage(self, run_id: str, stage: str, recoverable_input: dict | None = None) -> dict:
        stage_name = str(stage or "").strip()
        if not stage_name:
            raise ValueError("Stage name is required.")
        if len(stage_name) > 200:
            raise ValueError("Stage name must be at most 200 characters.")
        supplied_input = recoverable_input is not None
        clean_input = self._sanitize_recoverable_input(recoverable_input)
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if connection.execute("SELECT 1 FROM experiment_runs WHERE run_id=?", (run_id,)).fetchone() is None:
                raise KeyError("Run does not exist: {}".format(run_id))
            current = connection.execute(
                "SELECT * FROM run_stages WHERE run_id=? AND stage=?", (run_id, stage_name)
            ).fetchone()
            if current is not None and current["status"] == "RUNNING":
                raise RuntimeError("Stage is already running: {}".format(stage_name))
            attempt = int(current["attempt"]) + 1 if current is not None else 1
            previous_status = str(current["status"]) if current is not None else "PENDING"
            if not supplied_input and current is not None:
                clean_input = json.loads(current["recoverable_input_json"])
            input_json = json.dumps(clean_input, ensure_ascii=False, sort_keys=True)
            connection.execute(
                "INSERT INTO run_stages(run_id, stage, status, attempt, started_at, finished_at, error, artifact_paths_json, recoverable_input_json, updated_at) "
                "VALUES(?,?,?,?,?,?,?, ?,?,?) ON CONFLICT(run_id, stage) DO UPDATE SET status=excluded.status, attempt=excluded.attempt, started_at=excluded.started_at, finished_at=NULL, error=NULL, artifact_paths_json='[]', recoverable_input_json=excluded.recoverable_input_json, updated_at=excluded.updated_at",
                (run_id, stage_name, "RUNNING", attempt, now, None, None, "[]", input_json, now),
            )
            connection.execute(
                "INSERT INTO run_stage_events(event_id, run_id, stage, attempt, previous_status, new_status, error, artifact_paths_json, recoverable_input_json, created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                ("stageevt-" + uuid.uuid4().hex, run_id, stage_name, attempt, previous_status, "RUNNING", None, "[]", input_json, now),
            )
            row = connection.execute(
                "SELECT * FROM run_stages WHERE run_id=? AND stage=?", (run_id, stage_name)
            ).fetchone()
        return self._stage_from_row(row)

    def finish_run_stage(
        self,
        run_id: str,
        stage: str,
        status: str,
        error: str | None = None,
        artifact_paths: list[str] | tuple[str, ...] | str | Path | None = None,
        recoverable_input: dict | None = None,
    ) -> dict:
        stage_name = str(stage or "").strip()
        normalized = self._validate_status(status, terminal=True)
        clean_error = self._sanitize_text(error) if error else None
        supplied_artifacts = artifact_paths is not None
        clean_artifacts = self._normalize_artifact_paths(artifact_paths)
        supplied_input = recoverable_input is not None
        clean_input = self._sanitize_recoverable_input(recoverable_input)
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute(
                "SELECT * FROM run_stages WHERE run_id=? AND stage=?", (run_id, stage_name)
            ).fetchone()
            if current is None:
                raise KeyError("Run stage does not exist: {}".format(stage_name))
            if current["status"] != "RUNNING":
                raise RuntimeError("Only a running stage can be finished.")
            if not supplied_artifacts:
                clean_artifacts = json.loads(current["artifact_paths_json"])
            if not supplied_input:
                clean_input = json.loads(current["recoverable_input_json"])
            artifact_json = json.dumps(clean_artifacts, ensure_ascii=False, sort_keys=True)
            input_json = json.dumps(clean_input, ensure_ascii=False, sort_keys=True)
            connection.execute(
                "UPDATE run_stages SET status=?, finished_at=?, error=?, artifact_paths_json=?, recoverable_input_json=?, updated_at=? WHERE run_id=? AND stage=?",
                (normalized, now, clean_error, artifact_json, input_json, now, run_id, stage_name),
            )
            connection.execute(
                "INSERT INTO run_stage_events(event_id, run_id, stage, attempt, previous_status, new_status, error, artifact_paths_json, recoverable_input_json, created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                ("stageevt-" + uuid.uuid4().hex, run_id, stage_name, int(current["attempt"]), "RUNNING", normalized, clean_error, artifact_json, input_json, now),
            )
            row = connection.execute(
                "SELECT * FROM run_stages WHERE run_id=? AND stage=?", (run_id, stage_name)
            ).fetchone()
        return self._stage_from_row(row)

    def get_run_stage(self, run_id: str, stage: str) -> dict:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM run_stages WHERE run_id=? AND stage=?", (run_id, str(stage).strip())
            ).fetchone()
        if row is None:
            raise KeyError("Run stage does not exist: {}".format(stage))
        return self._stage_from_row(row)

    def list_run_stages(self, run_id: str) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM run_stages WHERE run_id=? ORDER BY updated_at, stage", (run_id,)
            ).fetchall()
        return [self._stage_from_row(row) for row in rows]

    def list_run_stage_events(self, run_id: str, stage: str | None = None) -> list[dict]:
        with self._connect() as connection:
            if stage is None:
                rows = connection.execute(
                    "SELECT * FROM run_stage_events WHERE run_id=? ORDER BY rowid", (run_id,)
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM run_stage_events WHERE run_id=? AND stage=? ORDER BY rowid",
                    (run_id, str(stage).strip()),
                ).fetchall()
        return [
            {
                "event_id": row["event_id"], "run_id": row["run_id"], "stage": row["stage"],
                "attempt": int(row["attempt"]), "previous_status": row["previous_status"],
                "new_status": row["new_status"], "error": row["error"],
                "artifact_paths": json.loads(row["artifact_paths_json"]),
                "recoverable_input": json.loads(row["recoverable_input_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

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
    def _empty_research_state(project_id: str) -> dict:
        return {
            "schema_version": "1.0",
            "project_id": project_id,
            "confirmed_decisions": [],
            "user_corrections": [],
            "recent_findings": [],
            "hypotheses": [],
            "rejected_hypotheses": [],
            "open_questions": [],
            "next_intent": "",
            "last_run_id": None,
            "row_version": 0,
        }

    def get_research_state(self, project_id: str) -> dict:
        with self._connect() as connection:
            project = connection.execute("SELECT 1 FROM projects WHERE project_id=?", (project_id,)).fetchone()
            if project is None:
                raise KeyError("Project does not exist: {}".format(project_id))
            row = connection.execute("SELECT payload FROM research_states WHERE project_id=?", (project_id,)).fetchone()
        if row is None:
            return self._empty_research_state(project_id)
        state = self._empty_research_state(project_id)
        state.update(json.loads(row["payload"]))
        return state

    def update_research_state(self, project_id: str, **fields) -> dict:
        """Update explicit research memory without silently inventing user decisions."""
        allowed = {
            "confirmed_decisions", "user_corrections", "recent_findings", "hypotheses",
            "rejected_hypotheses", "open_questions", "next_intent", "last_run_id",
        }
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError("Unsupported research-state fields: {}".format(", ".join(sorted(unknown))))
        state = self.get_research_state(project_id)
        for key, value in fields.items():
            if key in {"confirmed_decisions", "user_corrections", "recent_findings", "hypotheses", "rejected_hypotheses", "open_questions"}:
                state[key] = list(value or [])[-40:]
            elif key == "next_intent":
                state[key] = str(value or "").strip()[:2000]
            else:
                state[key] = value
        state["row_version"] = int(state.get("row_version", 0)) + 1
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO research_states(project_id, payload, updated_at) VALUES(?,?,?) "
                "ON CONFLICT(project_id) DO UPDATE SET payload=excluded.payload, updated_at=excluded.updated_at",
                (project_id, json.dumps(state, ensure_ascii=False, sort_keys=True), now),
            )
        return state

    def record_guidance_state(self, project_id: str, run_id: str, guidance: dict) -> dict:
        """Persist model output as candidate research memory, never as approved fact."""
        state = self.get_research_state(project_id)
        hypotheses = list(state.get("hypotheses") or [])
        for item in guidance.get("hypotheses") or []:
            if not isinstance(item, dict) or not str(item.get("claim") or "").strip():
                continue
            hypotheses.append({
                "run_id": run_id,
                "status": "candidate",
                "claim": str(item.get("claim") or "").strip(),
                "support": [str(value) for value in item.get("support") or []],
                "against": [str(value) for value in item.get("against") or []],
                "falsification_test": str(item.get("test") or "").strip(),
            })
        findings = list(state.get("recent_findings") or [])
        findings.extend(
            {
                "run_id": run_id,
                "status": "model_restatement_candidate",
                "text": str(value),
            }
            for value in guidance.get("data_facts") or []
        )
        open_questions = list(dict.fromkeys([
            *[str(value) for value in state.get("open_questions") or [] if str(value).strip()],
            *[str(value) for value in guidance.get("cannot_determine") or [] if str(value).strip()],
        ]))
        next_experiments = guidance.get("next_experiments") or []
        next_intent = ""
        if next_experiments:
            first = next_experiments[0]
            next_intent = str(first.get("action") if isinstance(first, dict) else first).strip()
        return self.update_research_state(
            project_id,
            recent_findings=findings[-40:],
            hypotheses=hypotheses[-40:],
            open_questions=open_questions[-40:],
            next_intent=next_intent,
            last_run_id=run_id,
        )

    def save_context_record(self, project_id: str, run_id: str | None, stage: str, manifest: dict) -> str:
        context_id = str(manifest.get("context_id") or "").strip()
        context_hash = str(manifest.get("context_hash") or "").strip()
        if not context_id or not context_hash:
            raise ValueError("Context manifest requires context_id and context_hash.")
        record_id = str(manifest.get("record_id") or "ctxrec-" + uuid.uuid4().hex).strip()
        stored = dict(manifest)
        stored["record_id"] = record_id
        payload = json.dumps(stored, ensure_ascii=False, sort_keys=True)
        created_at = str(stored.get("created_at") or datetime.now(timezone.utc).isoformat())
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO context_records(record_id, context_id, project_id, run_id, stage, context_hash, input_tokens_estimated, payload, created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (record_id, context_id, project_id, run_id, str(stage), context_hash, int(stored.get("input_tokens_estimated") or 0), payload, created_at),
            )
        return context_id

    def list_context_records(self, project_id: str, run_id: str | None = None) -> list[dict]:
        with self._connect() as connection:
            if run_id is None:
                rows = connection.execute(
                    "SELECT payload FROM context_records WHERE project_id=? ORDER BY created_at, record_id", (project_id,)
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT payload FROM context_records WHERE project_id=? AND run_id=? ORDER BY created_at, record_id", (project_id, run_id)
                ).fetchall()
        return [json.loads(row["payload"]) for row in rows]

    def save_codex_invocation(self, project_id: str, run_id: str | None, stage: str, record: dict) -> str:
        """Append one terminal Codex invocation record; existing IDs are immutable."""
        invocation_id = str(record.get("invocation_id") or "").strip()
        context_hash = str(record.get("context_hash") or "").strip()
        request_hash = str(record.get("request_hash") or "").strip()
        status = str(record.get("status") or "").strip()
        if not invocation_id or not context_hash or not request_hash or not status:
            raise ValueError("Codex invocation requires invocation_id, context_hash, request_hash, and status.")
        stored = dict(record)
        stored["project_id"] = project_id
        stored["run_id"] = run_id
        stored["stage"] = str(stage)
        created_at = str(stored.get("created_at") or datetime.now(timezone.utc).isoformat())
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO codex_invocations(invocation_id, project_id, run_id, stage, context_hash, request_hash, response_hash, status, payload, created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    invocation_id, project_id, run_id, str(stage), context_hash, request_hash,
                    stored.get("response_hash"), status,
                    json.dumps(stored, ensure_ascii=False, sort_keys=True), created_at,
                ),
            )
        return invocation_id

    def list_codex_invocations(self, project_id: str, run_id: str | None = None) -> list[dict]:
        with self._connect() as connection:
            if run_id is None:
                rows = connection.execute(
                    "SELECT payload FROM codex_invocations WHERE project_id=? ORDER BY created_at, invocation_id", (project_id,)
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT payload FROM codex_invocations WHERE project_id=? AND run_id=? ORDER BY created_at, invocation_id", (project_id, run_id)
                ).fetchall()
        return [json.loads(row["payload"]) for row in rows]

    @staticmethod
    def _claim_from_row(row: sqlite3.Row) -> KnowledgeClaim:
        payload = json.loads(row["payload"])
        payload["evidence_span_ids"] = tuple(payload.get("evidence_span_ids") or ())
        payload["limitations"] = tuple(payload.get("limitations") or ())
        return KnowledgeClaim(**payload)
