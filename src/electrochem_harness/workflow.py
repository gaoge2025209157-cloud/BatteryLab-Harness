"""Controlled workflow state machine for auditable analysis runs."""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional, Tuple


class WorkflowState(str, Enum):
    """Stable states exposed to GUI, CLI, audit, and evaluation layers."""

    CREATED = "created"
    PREFLIGHT = "preflight"
    BLOCKED = "blocked"
    PLAN_READY = "plan_ready"
    AWAITING_APPROVAL = "awaiting_approval"
    RUNNING = "running"
    VALIDATING = "validating"
    COMPLETED = "completed"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WorkflowError(RuntimeError):
    """Base exception for rejected workflow operations."""


class InvalidTransition(WorkflowError):
    """Raised when a state transition is not permitted."""


class ApprovalRequired(InvalidTransition):
    """Raised when execution is attempted without valid plan approval."""


class PlanHashMismatch(WorkflowError):
    """Raised when approval does not match the current analysis plan."""


@dataclass(frozen=True)
class TransitionRecord:
    """Minimal immutable event that can later be timestamped by the audit layer."""

    from_state: WorkflowState
    to_state: WorkflowState
    reason: str = ""

    def to_dict(self) -> Dict[str, str]:
        return {
            "from_state": self.from_state.value,
            "to_state": self.to_state.value,
            "reason": self.reason,
        }


_ALLOWED_TRANSITIONS = {
    WorkflowState.CREATED: {
        WorkflowState.PREFLIGHT,
        WorkflowState.CANCELLED,
    },
    WorkflowState.PREFLIGHT: {
        WorkflowState.BLOCKED,
        WorkflowState.PLAN_READY,
        WorkflowState.FAILED,
        WorkflowState.CANCELLED,
    },
    WorkflowState.BLOCKED: {
        WorkflowState.PREFLIGHT,
        WorkflowState.CANCELLED,
    },
    WorkflowState.PLAN_READY: {
        WorkflowState.AWAITING_APPROVAL,
        WorkflowState.PREFLIGHT,
        WorkflowState.FAILED,
        WorkflowState.CANCELLED,
    },
    WorkflowState.AWAITING_APPROVAL: {
        WorkflowState.RUNNING,
        WorkflowState.PLAN_READY,
        WorkflowState.PREFLIGHT,
        WorkflowState.FAILED,
        WorkflowState.CANCELLED,
    },
    WorkflowState.RUNNING: {
        WorkflowState.VALIDATING,
        WorkflowState.FAILED,
        WorkflowState.CANCELLED,
    },
    WorkflowState.VALIDATING: {
        WorkflowState.COMPLETED,
        WorkflowState.COMPLETED_WITH_WARNINGS,
        WorkflowState.FAILED,
        WorkflowState.CANCELLED,
    },
    WorkflowState.COMPLETED: set(),
    WorkflowState.COMPLETED_WITH_WARNINGS: set(),
    WorkflowState.FAILED: set(),
    WorkflowState.CANCELLED: set(),
}


class WorkflowStateMachine:
    """Enforce workflow order without performing analysis side effects.

    Approval is intentionally bound to the exact current plan hash. Re-entering
    preflight or replacing a plan invalidates approval before any analysis can
    enter ``RUNNING``.
    """

    def __init__(self) -> None:
        self._state = WorkflowState.CREATED
        self._current_plan_hash: Optional[str] = None
        self._approved_plan_hash: Optional[str] = None
        self._history = []

    @property
    def state(self) -> WorkflowState:
        return self._state

    @property
    def current_plan_hash(self) -> Optional[str]:
        return self._current_plan_hash

    @property
    def is_approved(self) -> bool:
        return (
            self._current_plan_hash is not None
            and self._approved_plan_hash == self._current_plan_hash
        )

    @property
    def history(self) -> Tuple[TransitionRecord, ...]:
        return tuple(self._history)

    def transition(
        self,
        target: WorkflowState,
        *,
        reason: str = "",
        plan_hash: Optional[str] = None,
    ) -> TransitionRecord:
        """Move to ``target`` if the transition and its guards are valid."""

        target = self._coerce_state(target)
        if target not in _ALLOWED_TRANSITIONS[self._state]:
            raise InvalidTransition(
                f"Cannot transition from {self._state.value} to {target.value}."
            )

        normalized_plan_hash = None
        if target == WorkflowState.PLAN_READY:
            normalized_plan_hash = self._require_plan_hash(plan_hash)
        elif plan_hash is not None:
            raise ValueError("plan_hash is only accepted when entering PLAN_READY.")

        if target == WorkflowState.AWAITING_APPROVAL and not self._current_plan_hash:
            raise InvalidTransition("A current plan is required before requesting approval.")

        if target == WorkflowState.RUNNING and not self.is_approved:
            raise ApprovalRequired(
                "The current analysis plan must be approved before execution."
            )

        previous = self._state
        if target == WorkflowState.PREFLIGHT:
            self._current_plan_hash = None
            self._approved_plan_hash = None
        elif target == WorkflowState.PLAN_READY:
            self._current_plan_hash = normalized_plan_hash
            self._approved_plan_hash = None

        self._state = target
        record = TransitionRecord(previous, target, str(reason or ""))
        self._history.append(record)
        return record

    def approve(self, plan_hash: str) -> None:
        """Approve only the exact plan currently awaiting approval."""

        if self._state != WorkflowState.AWAITING_APPROVAL:
            raise InvalidTransition(
                "Approval is only accepted while awaiting plan approval."
            )
        normalized = self._require_plan_hash(plan_hash)
        if normalized != self._current_plan_hash:
            raise PlanHashMismatch(
                "Approval plan hash does not match the current analysis plan."
            )
        self._approved_plan_hash = normalized

    def replace_plan(self, plan_hash: str, *, reason: str = "") -> TransitionRecord:
        """Replace a prepared plan and invalidate any prior approval."""

        if self._state not in {
            WorkflowState.PLAN_READY,
            WorkflowState.AWAITING_APPROVAL,
        }:
            raise InvalidTransition(
                "A plan can only be replaced after it has been prepared."
            )
        normalized = self._require_plan_hash(plan_hash)
        previous = self._state
        self._current_plan_hash = normalized
        self._approved_plan_hash = None
        self._state = WorkflowState.PLAN_READY
        record = TransitionRecord(previous, self._state, str(reason or ""))
        self._history.append(record)
        return record

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-ready snapshot without exposing approval internals."""

        return {
            "state": self._state.value,
            "current_plan_hash": self._current_plan_hash,
            "is_approved": self.is_approved,
            "history": [record.to_dict() for record in self._history],
        }

    @staticmethod
    def _coerce_state(value: WorkflowState) -> WorkflowState:
        if isinstance(value, WorkflowState):
            return value
        try:
            return WorkflowState(value)
        except (TypeError, ValueError) as error:
            raise ValueError(f"Unknown workflow state: {value!r}") from error

    @staticmethod
    def _require_plan_hash(value: Optional[str]) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("plan_hash must be a non-empty string.")
        return value.strip()
