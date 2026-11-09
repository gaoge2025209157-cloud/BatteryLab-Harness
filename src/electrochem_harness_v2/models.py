"""Versioned domain objects for auditable research runs."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
import hashlib
import json
import uuid
from typing import Any, Mapping


VALID_CLAIM_STATUSES = frozenset({"candidate", "approved", "rejected"})


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def stable_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SourceDocument:
    source_id: str
    project_id: str
    sha256: str
    original_name: str
    mime: str
    page_count: int
    extraction_status: str
    coverage_manifest: Mapping[str, Any]
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SourceSpan:
    span_id: str
    source_id: str
    page_index: int
    page_label: str | None
    block_type: str
    text: str
    text_hash: str
    bbox: tuple[float, float, float, float] | None = None
    figure_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class KnowledgeClaim:
    claim_id: str
    project_id: str
    source_id: str
    claim_type: str
    text: str
    metric_id: str | None = None
    value: float | None = None
    unit: str | None = None
    conditions: Mapping[str, Any] = field(default_factory=dict)
    evidence_span_ids: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    status: str = "candidate"
    row_version: int = 1
    created_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if self.status not in VALID_CLAIM_STATUSES:
            raise ValueError("Unsupported claim status: {}".format(self.status))
        if not self.project_id or not self.source_id or not self.claim_type or not self.text:
            raise ValueError("Claim requires project, source, type, and text.")
        if self.value is not None and not isinstance(self.value, (int, float)):
            raise ValueError("Claim numeric value must be numeric or absent.")

    @classmethod
    def new(
        cls,
        project_id: str,
        source_id: str,
        claim_type: str,
        text: str,
        metric_id: str | None = None,
        value: float | None = None,
        unit: str | None = None,
        conditions: Mapping[str, Any] | None = None,
        evidence_span_ids: list[str] | tuple[str, ...] = (),
        limitations: list[str] | tuple[str, ...] = (),
        status: str = "candidate",
    ) -> "KnowledgeClaim":
        identity = {
            "project_id": project_id,
            "source_id": source_id,
            "claim_type": claim_type,
            "text": " ".join(text.split()),
            "metric_id": metric_id,
            "evidence_span_ids": list(evidence_span_ids),
        }
        return cls(
            claim_id="claim-" + stable_hash(identity)[:24],
            project_id=project_id,
            source_id=source_id,
            claim_type=claim_type,
            text=text,
            metric_id=metric_id,
            value=value,
            unit=unit,
            conditions=dict(conditions or {}),
            evidence_span_ids=tuple(evidence_span_ids),
            limitations=tuple(limitations),
            status=status,
        )

    def reviewed(self, status: str) -> "KnowledgeClaim":
        if status not in VALID_CLAIM_STATUSES - {"candidate"}:
            raise ValueError("Review status must be approved or rejected.")
        return replace(self, status=status, row_version=self.row_version + 1)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ReviewEvent:
    event_id: str
    claim_id: str
    previous_status: str
    new_status: str
    reviewer: str
    reason: str
    reviewed_at: str = field(default_factory=utc_now)

    @classmethod
    def new(cls, claim_id: str, previous_status: str, new_status: str, reviewer: str, reason: str) -> "ReviewEvent":
        return cls("review-" + uuid.uuid4().hex, claim_id, previous_status, new_status, reviewer, reason)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ComparisonOutcome:
    claim_id: str
    comparability: str
    decision: str | None
    absolute_difference: float | None
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
