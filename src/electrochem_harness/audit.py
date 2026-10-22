"""Append-only event log and atomically updated run record."""

import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

from .approval import ApprovalStore
from .models import AnalysisPlan, ApprovalRecord


_ZERO_HASH = "0" * 64


class AuditStore:
    """Own the durable, resumable record for one controlled run directory."""

    def __init__(
        self,
        run_dir: Path,
        *,
        run_id: Optional[str] = None,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ):
        self.run_dir = Path(run_dir)
        self.run_id = run_id or "run-{}".format(uuid.uuid4().hex)
        self.clock = clock
        self.events_path = self.run_dir / "events.jsonl"
        self.run_record_path = self.run_dir / "run_record.json"
        self.plan_path = self.run_dir / "plan.json"
        self.approval_path = self.run_dir / "approval.json"
        self.preflight_path = self.run_dir / "preflight.json"
        self._record = None
        self._sequence = 0
        self._last_event_hash = _ZERO_HASH

    def initialize(self, plan: AnalysisPlan) -> None:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        _atomic_json(self.plan_path, plan.to_dict())
        _atomic_json(self.preflight_path, {"issues": list(plan.preflight_issues)})
        timestamp = self._timestamp()
        software_version = _read_version()
        rules_version_sha256 = _rules_hash()
        self._record = {
            "schema_version": 1,
            "run_id": self.run_id,
            "software_version": software_version,
            "rules_version_sha256": rules_version_sha256,
            "created_at": timestamp,
            "updated_at": timestamp,
            "state": "created",
            "plan_id": plan.plan_id,
            "plan_hash": plan.plan_hash,
            "input_identity": dict(plan.input_identity),
            "preflight_issues": list(plan.preflight_issues),
            "approval": None,
            "state_history": [],
            "tool_manifest": [],
            "tools": [],
            "warnings": [],
            "degradations": [],
            "validation": None,
            "artifacts": [],
            "core_results_hash": None,
            "error": None,
        }
        self._save_record()

    def set_tool_manifest(self, manifest) -> None:
        self._require_initialized()
        self._record["tool_manifest"] = list(manifest)
        self._touch()

    def append_event(self, event_type: str, state: str, details=None) -> Mapping[str, Any]:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self._sequence += 1
        payload = {
            "sequence": self._sequence,
            "timestamp": self._timestamp(),
            "event_type": str(event_type),
            "state": str(state),
            "details": _json_safe(details or {}),
            "previous_hash": self._last_event_hash,
        }
        payload["event_hash"] = _event_hash(payload)
        with self.events_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        self._last_event_hash = payload["event_hash"]
        return payload

    def record_transition(self, transition) -> None:
        self._require_initialized()
        item = transition.to_dict()
        item["timestamp"] = self._timestamp()
        self._record["state"] = item["to_state"]
        self._record["state_history"].append(item)
        self.append_event("state_transition", item["to_state"], item)
        self._touch()

    def save_approval(self, record: ApprovalRecord) -> None:
        self._require_initialized()
        ApprovalStore(self.approval_path).save(record)
        self._record["approval"] = record.to_dict()
        self.append_event(
            "approval_decision",
            self._record["state"],
            {
                "approval_id": record.approval_id,
                "approved": record.approved,
                "scopes": list(record.scopes),
                "source": record.source,
                "record_hash": record.record_hash,
            },
        )
        self._touch()

    def record_tool(
        self,
        tool_id: str,
        status: str,
        attempts: int,
        *,
        arguments=None,
        duration_seconds=None,
        output=None,
        error=None,
    ) -> None:
        self._require_initialized()
        item = {
            "tool_id": str(tool_id),
            "status": str(status),
            "attempts": int(attempts),
            "timestamp": self._timestamp(),
            "arguments": _summary(arguments or {}),
            "duration_seconds": (
                None if duration_seconds is None else float(duration_seconds)
            ),
            "output": _summary(output),
            "error": None if error is None else str(error),
        }
        self._record["tools"].append(item)
        self.append_event("tool_execution", self._record["state"], item)
        self._touch()

    def add_warning(self, message: str) -> None:
        self._require_initialized()
        self._record["warnings"].append(str(message))
        self._touch()

    def add_degradation(self, tool_id: str, reason: str) -> None:
        self._require_initialized()
        item = {"tool_id": str(tool_id), "reason": str(reason), "timestamp": self._timestamp()}
        self._record["degradations"].append(item)
        self.append_event("degradation", self._record["state"], item)
        self._touch()

    def save_validation(self, validation) -> None:
        self._require_initialized()
        payload = validation.to_dict()
        self._record["validation"] = payload
        self._record["artifacts"] = payload["artifacts"]
        self._record["core_results_hash"] = payload["core_results_hash"]
        self.append_event("validation", self._record["state"], payload)
        self._touch()

    def set_error(self, error: Exception, *, stage: str) -> None:
        self._require_initialized()
        self._record["error"] = {
            "stage": str(stage),
            "type": type(error).__name__,
            "message": str(error),
            "timestamp": self._timestamp(),
        }
        self._touch()

    def finalize(self, state: str, *, core_results=None) -> None:
        self._require_initialized()
        self._record["state"] = str(state)
        if core_results is not None and not self._record.get("core_results_hash"):
            self._record["core_results_hash"] = _payload_hash(core_results)
        self.append_event("run_finalized", str(state), {"state": str(state)})
        self._touch()

    def _touch(self) -> None:
        self._record["updated_at"] = self._timestamp()
        self._save_record()

    def _save_record(self) -> None:
        _atomic_json(self.run_record_path, self._record)

    def _timestamp(self) -> str:
        value = self.clock()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ValueError("Audit clock must return a timezone-aware datetime.")
        return value.astimezone(timezone.utc).isoformat()

    def _require_initialized(self) -> None:
        if self._record is None:
            raise RuntimeError("AuditStore.initialize(plan) must be called first.")


def verify_event_log(path: Path) -> bool:
    previous = _ZERO_HASH
    expected_sequence = 1
    try:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            payload = json.loads(line)
            actual = payload.pop("event_hash")
            if payload.get("sequence") != expected_sequence:
                return False
            if payload.get("previous_hash") != previous:
                return False
            expected = _event_hash(payload)
            if actual != expected:
                return False
            previous = actual
            expected_sequence += 1
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return False
    return expected_sequence > 1


def _event_hash(payload) -> str:
    return _payload_hash(payload)


def _payload_hash(payload) -> str:
    encoded = json.dumps(
        _json_safe(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _atomic_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(".{}.{}.tmp".format(path.name, uuid.uuid4().hex))
    try:
        temporary.write_text(
            json.dumps(_json_safe(payload), ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        os.replace(str(temporary), str(path))
    finally:
        if temporary.exists():
            temporary.unlink()


def _json_safe(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        result = {}
        for key, item in value.items():
            text_key = str(key)
            if _is_sensitive_key(text_key):
                result[text_key] = "[REDACTED]"
            else:
                result[text_key] = _json_safe(item)
        return result
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "to_dict"):
        return _json_safe(value.to_dict())
    return repr(value)


def _summary(value):
    safe = _json_safe(value)
    encoded = json.dumps(safe, ensure_ascii=False)
    if len(encoded) <= 2000:
        return safe
    return {"sha256": hashlib.sha256(encoded.encode("utf-8")).hexdigest(), "truncated": True}



def _read_version() -> str:
    path = Path(__file__).resolve().parents[2] / "VERSION"
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError:
        return "unknown"
    return value or "unknown"


def _rules_hash() -> str:
    path = Path(__file__).resolve().parents[2] / "knowledge" / "base_rules.json"
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        digest.update(b"rules-unavailable")
    return digest.hexdigest()


def _is_sensitive_key(value: str) -> bool:
    normalized = "".join(character for character in value.casefold() if character.isalnum())
    return any(
        marker in normalized
        for marker in (
            "password",
            "passwd",
            "secret",
            "token",
            "cookie",
            "authorization",
            "apikey",
            "privatekey",
        )
    )
