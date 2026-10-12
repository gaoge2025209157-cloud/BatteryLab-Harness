from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


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
