"""Governance checks for evidence-backed scientific release.

The gate is intentionally conservative: draft analysis can proceed while the
scientific release remains blocked or pending human confirmation.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable, List, Optional, Tuple

from .evidence import EvidenceRecord, validate_evidence_records


REQUIRED_REVIEWERS: Tuple[str, ...] = ("J", "C")
REQUIRED_EXPERIMENT_ISSUES: Tuple[str, ...] = (
    "cycle_mapping",
    "normalization",
    "negative_voltage",
    "incomplete_cycle",
)


class GateStatus(str, Enum):
    BLOCKED = "blocked"
    PENDING_CONFIRMATION = "pending_confirmation"
    OPEN = "open"


@dataclass(frozen=True)
class ReviewerConfirmation:
    reviewer: str
    confirmed: bool
    scope: str = "scientific_release"
    note: str = ""


@dataclass(frozen=True)
class GateDecision:
    status: GateStatus
    reasons: Tuple[str, ...]
    missing_reviewers: Tuple[str, ...]

    @property
    def can_publish(self) -> bool:
        return self.status is GateStatus.OPEN

    def to_dict(self) -> dict:
        return {
            "status": self.status.value,
            "can_publish": self.can_publish,
            "reasons": list(self.reasons),
            "missing_reviewers": list(self.missing_reviewers),
        }


def _matrix_errors(matrix: Optional[Any]) -> List[str]:
    if matrix is None:
        return []
    validate = getattr(matrix, "validation_errors", None)
    if validate is None:
        return ["hypothesis matrix does not expose validation_errors()"]
    return list(validate())


def evaluate_publication_gate(
    *,
    evidence_records: Iterable[EvidenceRecord] = (),
    hypothesis_matrix: Optional[Any] = None,
    reviewer_confirmations: Iterable[ReviewerConfirmation] = (),
    real_data_reviewed: bool = False,
    metric_tolerances_confirmed: bool = False,
    private_artifacts_excluded: bool = True,
    resolved_experiment_issues: Iterable[str] = (),
) -> GateDecision:
    """Evaluate recorded human decisions; never infer experimental resolution.

    Callers must retain the decision and evidence identifiers for each resolved
    issue in their review record. An issue that does not apply still requires an
    explicit reviewed decision. Omitting these attestations fails closed.
    """
    records = list(evidence_records)
    reasons: List[str] = []
    reasons.extend(validate_evidence_records(records))
    reasons.extend(_matrix_errors(hypothesis_matrix))
    resolved = set(resolved_experiment_issues)
    for issue in REQUIRED_EXPERIMENT_ISSUES:
        if issue not in resolved:
            reasons.append("experimental issue is not resolved: " + issue)

    if not real_data_reviewed:
        reasons.append("private real-data Blue/Manual/Harness review is not recorded")
    if not metric_tolerances_confirmed:
        reasons.append("J/C confirmation of metric tolerances is not recorded")
    if not private_artifacts_excluded:
        reasons.append("private data, credentials, cookies, PDFs, or personal paths are not excluded")

    confirmed = {
        item.reviewer.strip().upper(): item
        for item in reviewer_confirmations
        if item.scope == "scientific_release" and item.confirmed
    }
    missing = tuple(reviewer for reviewer in REQUIRED_REVIEWERS if reviewer not in confirmed)

    if reasons:
        return GateDecision(GateStatus.BLOCKED, tuple(reasons), missing)
    if missing:
        return GateDecision(
            GateStatus.PENDING_CONFIRMATION,
            ("required human confirmations are missing",),
            missing,
        )
    return GateDecision(GateStatus.OPEN, (), ())
