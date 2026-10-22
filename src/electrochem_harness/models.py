from dataclasses import asdict, dataclass, field
from types import MappingProxyType
from typing import Any, Dict, List, Mapping, Optional, Tuple


@dataclass(frozen=True)
class CyclingPoint:
    cycle: int
    time_s: float
    current_mA: float
    voltage_V: float
    source_row: int


@dataclass(frozen=True)
class ExperimentContext:
    experiment_type: str = "galvanostatic_cycling"
    system_type: Optional[str] = None
    electrolyte: Optional[str] = None
    anode: Optional[str] = None
    atmosphere: Optional[str] = None
    active_mass_mg: Optional[float] = None
    nominal_capacity_mAh_g: Optional[float] = None
    voltage_window_V: Optional[List[float]] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CycleMetrics:
    cycle: int
    charge_capacity_mAh: float
    discharge_capacity_mAh: float
    charge_energy_mWh: float
    discharge_energy_mWh: float
    specific_charge_capacity_mAh_g: Optional[float]
    specific_discharge_capacity_mAh_g: Optional[float]
    coulombic_efficiency: Optional[float]
    capacity_retention: Optional[float]
    average_charge_voltage_V: Optional[float]
    average_discharge_voltage_V: Optional[float]
    voltage_gap_V: Optional[float]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class QualityIssue:
    code: str
    message: str
    blocking: bool

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Recommendation:
    title: str
    observation: str
    action: str
    evidence: str
    confidence: float
    risk: str
    requires_confirmation: bool
    source_id: str
    source: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Experience:
    id: str
    experiment_type: str
    system_type: str
    observation: str
    action: str
    outcome: str
    evidence: str
    validated: bool
    confidence: float
    supports: int
    contradicts: int
    created_at: str
    feedback_evidence: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "Experience":
        return cls(**payload)


def _freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _freeze_json(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    return value


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


@dataclass(frozen=True)
class AnalysisPlan:
    """Immutable execution plan bound to an approval hash."""

    plan_id: str
    plan_hash: str
    input_identity: Mapping[str, Any]
    experiment_metadata: Mapping[str, Any]
    preflight_issues: Tuple[Mapping[str, Any], ...]
    metrics: Tuple[str, ...]
    tools: Tuple[str, ...]
    network_enabled: bool
    network_fields: Mapping[str, Any]
    origin_enabled: bool
    expected_artifacts: Tuple[str, ...]
    limitations: Tuple[str, ...]
    risks: Tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "input_identity", _freeze_json(self.input_identity))
        object.__setattr__(
            self, "experiment_metadata", _freeze_json(self.experiment_metadata)
        )
        object.__setattr__(
            self,
            "preflight_issues",
            tuple(_freeze_json(item) for item in self.preflight_issues),
        )
        object.__setattr__(self, "metrics", tuple(self.metrics))
        object.__setattr__(self, "tools", tuple(self.tools))
        object.__setattr__(self, "network_fields", _freeze_json(self.network_fields))
        object.__setattr__(self, "expected_artifacts", tuple(self.expected_artifacts))
        object.__setattr__(self, "limitations", tuple(self.limitations))
        object.__setattr__(self, "risks", tuple(self.risks))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "plan_hash": self.plan_hash,
            "input_identity": _thaw_json(self.input_identity),
            "experiment_metadata": _thaw_json(self.experiment_metadata),
            "preflight_issues": _thaw_json(self.preflight_issues),
            "metrics": list(self.metrics),
            "tools": list(self.tools),
            "network_enabled": self.network_enabled,
            "network_fields": _thaw_json(self.network_fields),
            "origin_enabled": self.origin_enabled,
            "expected_artifacts": list(self.expected_artifacts),
            "limitations": list(self.limitations),
            "risks": list(self.risks),
        }


@dataclass
class HarnessReport:
    status: str
    metrics: List[CycleMetrics]
    quality_issues: List[QualityIssue]
    conclusions: List[str]
    recommendations: List[Recommendation]
    missing_context: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "metrics": [item.to_dict() for item in self.metrics],
            "quality_issues": [item.to_dict() for item in self.quality_issues],
            "conclusions": list(self.conclusions),
            "recommendations": [item.to_dict() for item in self.recommendations],
            "missing_context": list(self.missing_context),
        }



@dataclass(frozen=True)
class ApprovalRecord:
    """Immutable, integrity-hashed decision bound to one analysis plan."""

    approval_id: str
    plan_hash: str
    approved: bool
    scopes: Tuple[str, ...]
    decided_at: str
    source: str
    expires_at: Optional[str]
    reason: str
    record_hash: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "approval_id": self.approval_id,
            "plan_hash": self.plan_hash,
            "approved": self.approved,
            "scopes": list(self.scopes),
            "decided_at": self.decided_at,
            "source": self.source,
            "expires_at": self.expires_at,
            "reason": self.reason,
            "record_hash": self.record_hash,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ApprovalRecord":
        return cls(
            approval_id=str(payload["approval_id"]),
            plan_hash=str(payload["plan_hash"]),
            approved=bool(payload["approved"]),
            scopes=tuple(str(item) for item in payload["scopes"]),
            decided_at=str(payload["decided_at"]),
            source=str(payload["source"]),
            expires_at=(
                None if payload.get("expires_at") is None else str(payload["expires_at"])
            ),
            reason=str(payload.get("reason", "")),
            record_hash=str(payload["record_hash"]),
        )
