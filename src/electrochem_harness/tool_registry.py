"""Sealed allow-list for deterministic Harness tools."""

import re
import threading
import time
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional, Tuple

from .approval import validate_approval
from .models import ApprovalRecord


_TOOL_ID = re.compile(r"^[a-z][a-z0-9_]{1,63}$")


class ToolRegistryError(RuntimeError):
    """Base error for controlled tool execution."""


class ToolNotAllowed(ToolRegistryError):
    """Raised for unregistered tools or tools absent from the approved plan."""


class ToolRegistrySealed(ToolRegistryError):
    """Raised when runtime code tries to alter a sealed allow-list."""


class ExecutionCancelled(ToolRegistryError):
    """Raised when cooperative cancellation has been requested."""


class ToolTimeout(ToolRegistryError):
    """Raised when a trusted tool crosses its registered execution deadline."""


class FailurePolicy(str, Enum):
    FAIL = "fail"
    DEGRADE = "degrade"


class CancellationToken:
    """Thread-safe cooperative cancellation checked between tool boundaries."""

    def __init__(self):
        self._event = threading.Event()
        self._reason = ""

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    @property
    def reason(self) -> str:
        return self._reason

    def cancel(self, reason: str = "user cancelled") -> None:
        self._reason = str(reason or "user cancelled")
        self._event.set()

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise ExecutionCancelled(self.reason)


@dataclass(frozen=True)
class ToolContext:
    run_id: str
    plan_hash: str
    output_dir: Path
    cancellation: CancellationToken
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)
    shared: Dict[str, Any] = field(default_factory=dict)
    deadline_monotonic: Optional[float] = None

    def checkpoint(self) -> None:
        self.cancellation.raise_if_cancelled()
        if (
            self.deadline_monotonic is not None
            and time.perf_counter() >= self.deadline_monotonic
        ):
            raise ToolTimeout("Tool exceeded its registered execution deadline.")


@dataclass(frozen=True)
class ToolOutcome:
    value: Any = None
    artifacts: Tuple[Path, ...] = ()
    warnings: Tuple[str, ...] = ()
    attempts: int = 1
    duration_seconds: float = 0.0


@dataclass(frozen=True)
class ToolSpec:
    tool_id: str
    handler: Callable[..., Any]
    requires_network: bool = False
    writes_output: bool = False
    failure_policy: FailurePolicy = FailurePolicy.FAIL
    timeout_seconds: int = 300
    max_retries: int = 0
    allowed_arguments: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not _TOOL_ID.fullmatch(self.tool_id):
            raise ValueError("tool_id must use lower-case letters, digits, and underscores.")
        if not callable(self.handler):
            raise TypeError("handler must be callable.")
        if isinstance(self.timeout_seconds, bool) or self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive.")
        if isinstance(self.max_retries, bool) or self.max_retries < 0:
            raise ValueError("max_retries must be non-negative.")
        normalized_arguments = tuple(dict.fromkeys(str(item).strip() for item in self.allowed_arguments))
        if any(not _TOOL_ID.fullmatch(item) for item in normalized_arguments):
            raise ValueError("allowed_arguments entries must be safe lower-case identifiers.")
        object.__setattr__(self, "allowed_arguments", normalized_arguments)
        object.__setattr__(self, "failure_policy", FailurePolicy(self.failure_policy))


class ToolRegistry:
    """Register tools during composition, then seal before executing a run."""

    def __init__(self):
        self._specs: Dict[str, ToolSpec] = {}
        self._sealed = False

    @property
    def sealed(self) -> bool:
        return self._sealed

    def register(self, spec: ToolSpec) -> None:
        if self._sealed:
            raise ToolRegistrySealed("The tool registry is sealed for this run.")
        if spec.tool_id in self._specs:
            raise ValueError("Duplicate tool_id: {}".format(spec.tool_id))
        self._specs[spec.tool_id] = spec

    def seal(self) -> None:
        self._sealed = True

    def get(self, tool_id: str) -> ToolSpec:
        try:
            return self._specs[tool_id]
        except KeyError as error:
            raise ToolNotAllowed("Tool is not registered: {}".format(tool_id)) from error

    def manifest(self) -> Tuple[Mapping[str, Any], ...]:
        return tuple(
            {
                "tool_id": spec.tool_id,
                "requires_network": spec.requires_network,
                "writes_output": spec.writes_output,
                "failure_policy": spec.failure_policy.value,
                "timeout_seconds": spec.timeout_seconds,
                "max_retries": spec.max_retries,
                "allowed_arguments": list(spec.allowed_arguments),
            }
            for spec in self._specs.values()
        )

    def execute(
        self,
        tool_id: str,
        planned_tools,
        approval: ApprovalRecord,
        context: ToolContext,
        arguments: Optional[Mapping[str, Any]] = None,
    ) -> ToolOutcome:
        if not self._sealed:
            self.seal()
        spec = self.get(tool_id)
        if tool_id not in tuple(planned_tools):
            raise ToolNotAllowed("Tool is not present in the approved plan: {}".format(tool_id))
        required = {"local_analysis"}
        if spec.requires_network:
            required.add("network_access")
        if spec.writes_output:
            required.add("formal_output")
        validate_approval(
            approval,
            context.plan_hash,
            required_scopes=required,
            now=context.clock(),
        )
        context.cancellation.raise_if_cancelled()
        supplied_arguments = dict(arguments or {})
        unknown_arguments = sorted(set(supplied_arguments) - set(spec.allowed_arguments))
        if unknown_arguments:
            raise ToolNotAllowed(
                "Tool arguments are not allow-listed for {}: {}".format(
                    tool_id, ", ".join(unknown_arguments)
                )
            )
        started = time.perf_counter()
        execution_context = replace(
            context, deadline_monotonic=started + float(spec.timeout_seconds)
        )
        attempts = 0
        while True:
            attempts += 1
            try:
                execution_context.checkpoint()
                value = spec.handler(execution_context, **supplied_arguments)
                execution_context.checkpoint()
                duration = time.perf_counter() - started
                if isinstance(value, ToolOutcome):
                    return replace(value, attempts=attempts, duration_seconds=duration)
                return ToolOutcome(
                    value=value,
                    attempts=attempts,
                    duration_seconds=duration,
                )
            except ExecutionCancelled:
                raise
            except Exception:
                if attempts > spec.max_retries:
                    raise
                context.cancellation.raise_if_cancelled()
