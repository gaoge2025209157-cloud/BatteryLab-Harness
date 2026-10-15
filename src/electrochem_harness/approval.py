"""Persist explicit human approval bound to an immutable analysis plan."""

import hashlib
import hmac
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from .models import ApprovalRecord


APPROVAL_SCOPES = frozenset(
    {"local_analysis", "network_access", "formal_output"}
)
APPROVAL_SOURCES = frozenset({"gui", "cli", "api", "test"})
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")


class ApprovalError(RuntimeError):
    """Base error for invalid or unusable approval decisions."""


class ApprovalIntegrityError(ApprovalError):
    """Raised when persisted approval content no longer matches its hash."""


class ApprovalPlanMismatch(ApprovalError):
    """Raised when a decision belongs to another plan revision."""


class ApprovalExpired(ApprovalError):
    """Raised when a time-bounded approval is no longer current."""


class ApprovalScopeError(ApprovalError):
    """Raised when approval was denied or lacks an execution scope."""


def create_approval(
    plan_hash: str,
    *,
    scopes: Iterable[str],
    source: str = "cli",
    approved: bool = True,
    now: Optional[datetime] = None,
    expires_at: Optional[datetime] = None,
    reason: str = "",
    approval_id: Optional[str] = None,
) -> ApprovalRecord:
    """Create an integrity-hashed decision without storing user credentials."""

    normalized_hash = _plan_hash(plan_hash)
    normalized_scopes = _scopes(scopes)
    normalized_source = str(source or "").strip().casefold()
    if normalized_source not in APPROVAL_SOURCES:
        raise ValueError(
            "source must be one of: {}".format(", ".join(sorted(APPROVAL_SOURCES)))
        )
    decided = _aware(now or datetime.now(timezone.utc), "now")
    expiry = None if expires_at is None else _aware(expires_at, "expires_at")
    if expiry is not None and expiry <= decided:
        raise ValueError("expires_at must be later than the decision time.")
    if approved and not normalized_scopes:
        raise ValueError("An approved decision must include at least one scope.")
    identifier = approval_id or "approval-{}".format(uuid.uuid4().hex)
    payload = {
        "approval_id": str(identifier),
        "plan_hash": normalized_hash,
        "approved": bool(approved),
        "scopes": list(normalized_scopes),
        "decided_at": decided.isoformat(),
        "source": normalized_source,
        "expires_at": None if expiry is None else expiry.isoformat(),
        "reason": str(reason or ""),
    }
    return ApprovalRecord(
        approval_id=payload["approval_id"],
        plan_hash=payload["plan_hash"],
        approved=payload["approved"],
        scopes=normalized_scopes,
        decided_at=payload["decided_at"],
        source=payload["source"],
        expires_at=payload["expires_at"],
        reason=payload["reason"],
        record_hash=_record_hash(payload),
    )


def revoke_approval(
    record: ApprovalRecord,
    *,
    reason: str,
    now: Optional[datetime] = None,
) -> ApprovalRecord:
    """Return a new denied decision while retaining the approval identifier."""

    _verify_integrity(record)
    return create_approval(
        record.plan_hash,
        scopes=(),
        source=record.source,
        approved=False,
        now=now,
        reason=reason,
        approval_id=record.approval_id,
    )


def validate_approval(
    record: ApprovalRecord,
    plan_hash: str,
    *,
    required_scopes: Iterable[str] = (),
    now: Optional[datetime] = None,
) -> ApprovalRecord:
    """Reject altered, denied, expired, mismatched, or insufficient decisions."""

    _verify_integrity(record)
    expected = _plan_hash(plan_hash)
    if record.plan_hash != expected:
        raise ApprovalPlanMismatch(
            "Approval plan hash does not match the current analysis plan."
        )
    if not record.approved:
        raise ApprovalScopeError("The analysis plan was not approved.")
    current = _aware(now or datetime.now(timezone.utc), "now")
    if record.expires_at is not None:
        expiry = _parse_time(record.expires_at, "expires_at")
        if current >= expiry:
            raise ApprovalExpired("Approval has expired and must be renewed.")
    required = set(_scopes(required_scopes))
    missing = sorted(required - set(record.scopes))
    if missing:
        raise ApprovalScopeError(
            "Approval is missing required scopes: {}".format(", ".join(missing))
        )
    return record


class ApprovalStore:
    """Atomically store the latest approval decision as JSON."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def save(self, record: ApprovalRecord) -> Path:
        _verify_integrity(record)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(
            ".{}.{}.tmp".format(self.path.name, uuid.uuid4().hex)
        )
        try:
            temporary.write_text(
                json.dumps(record.to_dict(), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            os.replace(str(temporary), str(self.path))
        finally:
            if temporary.exists():
                temporary.unlink()
        return self.path

    def load(self) -> ApprovalRecord:
        expected_fields = {
            "approval_id",
            "plan_hash",
            "approved",
            "scopes",
            "decided_at",
            "source",
            "expires_at",
            "reason",
            "record_hash",
        }
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or set(payload) != expected_fields:
                raise ValueError("approval.json fields do not match the schema")
            if not isinstance(payload["approved"], bool):
                raise ValueError("approved must be boolean")
            if not isinstance(payload["scopes"], list):
                raise ValueError("scopes must be a list")
            record = ApprovalRecord.from_dict(payload)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise ApprovalIntegrityError("approval.json is malformed.") from error
        _verify_integrity(record)
        _scopes(record.scopes)
        if record.source not in APPROVAL_SOURCES:
            raise ApprovalIntegrityError("approval.json contains an unknown source.")
        _parse_time(record.decided_at, "decided_at")
        if record.expires_at is not None:
            _parse_time(record.expires_at, "expires_at")
        return record


def _verify_integrity(record: ApprovalRecord) -> None:
    payload = record.to_dict()
    actual = payload.pop("record_hash", None)
    expected = _record_hash(payload)
    if not isinstance(actual, str) or not hmac.compare_digest(actual, expected):
        raise ApprovalIntegrityError(
            "Approval record hash does not match its persisted content."
        )


def _record_hash(payload) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _plan_hash(value: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value.strip()):
        raise ValueError("plan_hash must be a 64-character SHA-256.")
    return value.strip().casefold()


def _scopes(values: Iterable[str]):
    normalized = tuple(sorted({str(item).strip() for item in values if str(item).strip()}))
    invalid = sorted(set(normalized) - APPROVAL_SCOPES)
    if invalid:
        raise ValueError("Unknown approval scopes: {}".format(", ".join(invalid)))
    return normalized


def _aware(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("{} must be a timezone-aware datetime.".format(name))
    return value.astimezone(timezone.utc)


def _parse_time(value: str, name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as error:
        raise ApprovalIntegrityError("{} is not a valid ISO timestamp.".format(name)) from error
    return _aware(parsed, name)
