"""Phase 1 controlled execution orchestrator."""

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional, Tuple

from .approval import validate_approval
from .audit import AuditStore
from .models import AnalysisPlan, ApprovalRecord
from .planning import verify_plan_hash
from .tool_registry import (
    CancellationToken,
    ExecutionCancelled,
    FailurePolicy,
    ToolContext,
    ToolRegistry,
)
from .validation import ValidationResult, validate_run_outputs
from .workflow import ApprovalRequired, WorkflowState, WorkflowStateMachine


_NETWORK_ARTIFACTS = frozenset({"文献清单.json", "文献学习结果.json", "文献学习审计.json", "研究结论与指导.txt", "研究分析报告.html", "文献证据.json", "文献比较.csv"})
_ORIGIN_ARTIFACTS = frozenset(
    {"电化学分析.opju", "充放电曲线.png", "循环性能.png", "origin_status.json"}
)


@dataclass(frozen=True)
class Degradation:
    tool_id: str
    reason: str


@dataclass(frozen=True)
class ControlledRunResult:
    state: WorkflowState
    run_dir: Path
    outputs: Mapping[str, Any]
    degradations: Tuple[Degradation, ...]
    validation: Optional[ValidationResult]


class ControlledAnalysisRun:
    """Execute exactly one immutable plan through the Phase 1 safety gates."""

    def __init__(
        self,
        plan: AnalysisPlan,
        registry: ToolRegistry,
        runs_root: Path,
        *,
        run_id: str,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ):
        if not verify_plan_hash(plan):
            raise ValueError("Analysis plan content does not match its plan hash.")
        self.plan = plan
        self.registry = registry
        if not self.registry.sealed:
            self.registry.seal()
        self.clock = clock
        self.machine = WorkflowStateMachine()
        self.run_dir = Path(runs_root) / run_id
        self.output_dir = self.run_dir / "artifacts"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.audit = AuditStore(self.run_dir, run_id=run_id, clock=clock)
        self.audit.initialize(plan)
        self.audit.set_tool_manifest(registry.manifest())
        self._approval: Optional[ApprovalRecord] = None
        self._outputs: Dict[str, Any] = {}
        self._degradations = []
        self._validation = None
        self._transition(WorkflowState.PREFLIGHT, reason="input and metadata accepted")
        self._transition(
            WorkflowState.PLAN_READY,
            reason="immutable analysis plan prepared",
            plan_hash=plan.plan_hash,
        )
        self._transition(
            WorkflowState.AWAITING_APPROVAL,
            reason="explicit human approval required",
        )

    @property
    def state(self) -> WorkflowState:
        return self.machine.state

    def grant(self, record: ApprovalRecord) -> None:
        required = {"local_analysis", "formal_output"}
        if self.plan.network_enabled:
            required.add("network_access")
        validate_approval(
            record,
            self.plan.plan_hash,
            required_scopes=required,
            now=self.clock(),
        )
        self.machine.approve(self.plan.plan_hash)
        self._approval = record
        self.audit.save_approval(record)

    def execute(
        self,
        *,
        tool_arguments: Optional[Mapping[str, Mapping[str, Any]]] = None,
        cancellation: Optional[CancellationToken] = None,
    ) -> ControlledRunResult:
        if self._approval is None or not self.machine.is_approved:
            raise ApprovalRequired(
                "A persisted approval matching the current plan is required."
            )
        validate_approval(
            self._approval,
            self.plan.plan_hash,
            required_scopes=self._required_scopes(),
            now=self.clock(),
        )
        token = cancellation or CancellationToken()
        if token.cancelled:
            self._transition(WorkflowState.CANCELLED, reason=token.reason)
            self.audit.finalize(self.state.value, core_results=self._outputs)
            return self._result()

        self._transition(WorkflowState.RUNNING, reason="approved plan execution started")
        context = ToolContext(
            run_id=self.audit.run_id,
            plan_hash=self.plan.plan_hash,
            output_dir=self.output_dir,
            cancellation=token,
            clock=self.clock,
            shared=self._outputs,
        )
        allowed_missing = set()
        for tool_id in self.plan.tools:
            spec = self.registry.get(tool_id)
            arguments = (tool_arguments or {}).get(tool_id)
            try:
                outcome = self.registry.execute(
                    tool_id,
                    self.plan.tools,
                    self._approval,
                    context,
                    arguments=arguments,
                )
                self._outputs[tool_id] = outcome.value
                for warning in outcome.warnings:
                    self.audit.add_warning("{}: {}".format(tool_id, warning))
                self.audit.record_tool(
                    tool_id,
                    "success",
                    outcome.attempts,
                    arguments=arguments,
                    duration_seconds=outcome.duration_seconds,
                    output={
                        "value": outcome.value,
                        "artifacts": [str(path) for path in outcome.artifacts],
                        "duration_seconds": outcome.duration_seconds,
                    },
                )
            except ExecutionCancelled as error:
                self.audit.record_tool(
                    tool_id, "cancelled", 1, arguments=arguments, error=error
                )
                self._transition(WorkflowState.CANCELLED, reason=str(error))
                self.audit.finalize(self.state.value, core_results=self._outputs)
                return self._result()
            except Exception as error:
                self.audit.record_tool(
                    tool_id,
                    "failed",
                    spec.max_retries + 1,
                    arguments=arguments,
                    error=error,
                )
                if spec.failure_policy == FailurePolicy.DEGRADE:
                    degradation = Degradation(tool_id, "{}: {}".format(type(error).__name__, error))
                    self._degradations.append(degradation)
                    self.audit.add_degradation(tool_id, degradation.reason)
                    allowed_missing.update(self._optional_artifacts(tool_id))
                    continue
                self.audit.set_error(error, stage=tool_id)
                self._transition(WorkflowState.FAILED, reason="required tool failed: {}".format(tool_id))
                self.audit.finalize(self.state.value, core_results=self._outputs)
                return self._result()

        self._transition(WorkflowState.VALIDATING, reason="tool execution completed")
        self._validation = validate_run_outputs(
            self._outputs,
            self.output_dir,
            expected_artifacts=self.plan.expected_artifacts,
            allowed_missing_artifacts=allowed_missing,
        )
        self.audit.save_validation(self._validation)
        if not self._validation.valid:
            error = RuntimeError("Run output validation failed.")
            self.audit.set_error(error, stage="validation")
            self._transition(WorkflowState.FAILED, reason="output validation failed")
        elif self._degradations or self._validation.issues:
            self._transition(
                WorkflowState.COMPLETED_WITH_WARNINGS,
                reason="local analysis preserved with explicit warnings",
            )
        else:
            self._transition(WorkflowState.COMPLETED, reason="all validations passed")
        self.audit.finalize(self.state.value, core_results=self._outputs)
        return self._result()

    def cancel(self, reason: str = "user cancelled") -> ControlledRunResult:
        self._transition(WorkflowState.CANCELLED, reason=reason)
        self.audit.finalize(self.state.value, core_results=self._outputs)
        return self._result()

    def _required_scopes(self):
        scopes = {"local_analysis", "formal_output"}
        if self.plan.network_enabled:
            scopes.add("network_access")
        return scopes

    def _transition(self, target, *, reason="", plan_hash=None):
        record = self.machine.transition(target, reason=reason, plan_hash=plan_hash)
        self.audit.record_transition(record)
        return record

    @staticmethod
    def _optional_artifacts(tool_id: str):
        if tool_id == "search_literature_metadata":
            return _NETWORK_ARTIFACTS
        if tool_id == "build_origin_project":
            return _ORIGIN_ARTIFACTS
        return frozenset()

    def _result(self) -> ControlledRunResult:
        return ControlledRunResult(
            self.state,
            self.run_dir,
            dict(self._outputs),
            tuple(self._degradations),
            self._validation,
        )
