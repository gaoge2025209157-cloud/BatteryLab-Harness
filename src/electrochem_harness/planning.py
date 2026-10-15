"""Build deterministic, reviewable analysis plans before execution."""

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any, Dict, Iterable, Optional

from .models import AnalysisPlan, QualityIssue


class PlanningError(RuntimeError):
    """Base exception for analysis-plan construction failures."""


class BlockingPreflightError(PlanningError):
    """Raised when blocking input issues prohibit plan creation."""


class UnsafeNetworkFieldError(PlanningError):
    """Raised when a plan attempts to transmit an undeclared field."""


PUBLIC_RESEARCH_FIELDS = frozenset(
    {
        "battery_system",
        "active_material",
        "cell_type",
        "counter_electrode",
        "test_current",
        "temperature",
        "normalization_basis",
    }
)

DEFAULT_METRICS = (
    "charge_capacity",
    "discharge_capacity",
    "specific_charge_capacity",
    "specific_discharge_capacity",
    "coulombic_efficiency",
    "capacity_retention",
    "average_charge_voltage",
    "average_discharge_voltage",
    "voltage_gap",
    "dominant_voltage_plateau",
)

_BASE_TOOLS = (
    "parse_land_text",
    "quality_check",
    "calculate_cycle_metrics",
)
_BASE_ARTIFACTS = (
    "关键参数报告.md",
    "关键参数.csv",
    "完整分析.json",
    "Origin_充放电曲线数据.csv",
    "origin_job.json",
)
_LITERATURE_ARTIFACTS = ("文献证据.json", "文献比较.csv")
_ORIGIN_ARTIFACTS = (
    "电化学分析.opju",
    "充放电曲线.png",
    "循环性能.png",
    "origin_status.json",
)
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")


def build_analysis_plan(
    *,
    input_identity: Mapping[str, Any],
    experiment_metadata: Mapping[str, Any],
    preflight_issues: Sequence[Any] = (),
    metrics: Optional[Iterable[str]] = None,
    network_enabled: bool = False,
    network_fields: Optional[Mapping[str, Any]] = None,
    origin_enabled: bool = False,
    limitations: Iterable[str] = (),
    risks: Iterable[str] = (),
) -> AnalysisPlan:
    """Create a canonical plan whose hash changes with any execution scope.

    The builder has no side effects. It neither reads the input file nor starts
    network or Origin operations; those actions belong to registered tools.
    """

    normalized_input = _normalize_input_identity(input_identity)
    normalized_metadata = _json_object(experiment_metadata, "experiment_metadata")
    normalized_issues = tuple(_normalize_issue(issue) for issue in preflight_issues)

    blocking_codes = [
        issue["code"] for issue in normalized_issues if issue["blocking"]
    ]
    if blocking_codes:
        raise BlockingPreflightError(
            "Blocking preflight issues prevent plan creation: {}".format(
                ", ".join(blocking_codes)
            )
        )

    normalized_network = _normalize_network_fields(
        network_enabled=bool(network_enabled),
        network_fields=network_fields,
        experiment_metadata=normalized_metadata,
    )
    normalized_metrics = _text_tuple(metrics or DEFAULT_METRICS, "metrics")

    tools = list(_BASE_TOOLS)
    if network_enabled:
        tools.append("search_literature_metadata")
    tools.append("build_scientific_report")
    if origin_enabled:
        tools.append("build_origin_project")

    artifacts = list(_BASE_ARTIFACTS)
    if network_enabled:
        artifacts.extend(_LITERATURE_ARTIFACTS)
    if origin_enabled:
        artifacts.extend(_ORIGIN_ARTIFACTS)

    normalized_limitations = list(_text_tuple(limitations, "limitations"))
    if normalized_issues:
        normalized_limitations.append("存在非阻断预检查问题，结论必须保留限制说明。")
    if not network_enabled:
        normalized_limitations.append("未授权联网检索，不得判断文献性能水平。")

    normalized_risks = list(_text_tuple(risks, "risks"))
    if network_enabled:
        normalized_risks.append("联网失败时降级为本地分析，不得生成文献水平结论。")
    if origin_enabled:
        normalized_risks.append("Origin失败时保留报告和绘图CSV并记录降级。")

    payload = {
        "input_identity": normalized_input,
        "experiment_metadata": normalized_metadata,
        "preflight_issues": list(normalized_issues),
        "metrics": list(normalized_metrics),
        "tools": tools,
        "network_enabled": bool(network_enabled),
        "network_fields": normalized_network,
        "origin_enabled": bool(origin_enabled),
        "expected_artifacts": artifacts,
        "limitations": _deduplicate(normalized_limitations),
        "risks": _deduplicate(normalized_risks),
    }
    plan_hash = _hash_payload(payload)
    return AnalysisPlan(
        plan_id="plan-{}".format(plan_hash[:16]),
        plan_hash=plan_hash,
        input_identity=payload["input_identity"],
        experiment_metadata=payload["experiment_metadata"],
        preflight_issues=tuple(payload["preflight_issues"]),
        metrics=tuple(payload["metrics"]),
        tools=tuple(payload["tools"]),
        network_enabled=payload["network_enabled"],
        network_fields=payload["network_fields"],
        origin_enabled=payload["origin_enabled"],
        expected_artifacts=tuple(payload["expected_artifacts"]),
        limitations=tuple(payload["limitations"]),
        risks=tuple(payload["risks"]),
    )


def verify_plan_hash(plan: AnalysisPlan) -> bool:
    """Return whether the immutable plan still matches its approval hash."""

    payload = plan.to_dict()
    expected = payload.pop("plan_hash")
    payload.pop("plan_id")
    return _hash_payload(payload) == expected


def _normalize_input_identity(value: Mapping[str, Any]) -> Dict[str, Any]:
    payload = _json_object(value, "input_identity")
    display_path = payload.get("display_path")
    sha256 = payload.get("sha256")
    size_bytes = payload.get("size_bytes")
    if not isinstance(display_path, str) or not display_path.strip():
        raise ValueError("input_identity.display_path must be a non-empty string.")
    if not isinstance(sha256, str) or not _SHA256.fullmatch(sha256):
        raise ValueError("input_identity.sha256 must be a 64-character SHA-256.")
    if isinstance(size_bytes, bool) or not isinstance(size_bytes, int) or size_bytes < 0:
        raise ValueError("input_identity.size_bytes must be a non-negative integer.")
    return {
        "display_path": display_path.strip(),
        "sha256": sha256.casefold(),
        "size_bytes": size_bytes,
    }


def _normalize_issue(value: Any) -> Dict[str, Any]:
    if isinstance(value, QualityIssue):
        payload = value.to_dict()
    elif isinstance(value, Mapping):
        payload = _json_object(value, "preflight issue")
    else:
        raise TypeError("preflight issues must be QualityIssue or mapping values.")
    code = payload.get("code")
    message = payload.get("message")
    blocking = payload.get("blocking")
    if not isinstance(code, str) or not code.strip():
        raise ValueError("preflight issue code must be non-empty.")
    if not isinstance(message, str) or not message.strip():
        raise ValueError("preflight issue message must be non-empty.")
    if not isinstance(blocking, bool):
        raise ValueError("preflight issue blocking must be boolean.")
    return {"code": code.strip(), "message": message.strip(), "blocking": blocking}


def _normalize_network_fields(
    *,
    network_enabled: bool,
    network_fields: Optional[Mapping[str, Any]],
    experiment_metadata: Mapping[str, Any],
) -> Dict[str, Any]:
    if not network_enabled:
        if network_fields:
            raise ValueError("network_fields require network_enabled=True.")
        return {}

    selected = network_fields
    if selected is None:
        selected = {
            key: experiment_metadata[key]
            for key in PUBLIC_RESEARCH_FIELDS
            if key in experiment_metadata
        }
    payload = _json_object(selected, "network_fields")
    unsafe = sorted(set(payload) - PUBLIC_RESEARCH_FIELDS)
    if unsafe:
        raise UnsafeNetworkFieldError(
            "Network fields are not approved for transmission: {}".format(
                ", ".join(unsafe)
            )
        )
    if not payload:
        raise ValueError("network_fields must list the public research metadata sent.")
    return payload


def _json_object(value: Mapping[str, Any], name: str) -> Dict[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError("{} must be a mapping.".format(name))
    try:
        encoded = json.dumps(
            dict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise ValueError("{} must contain JSON-compatible values.".format(name)) from error
    return json.loads(encoded)


def _text_tuple(values: Iterable[str], name: str) -> tuple:
    normalized = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("{} entries must be non-empty strings.".format(name))
        normalized.append(value.strip())
    return tuple(_deduplicate(normalized))


def _deduplicate(values: Iterable[str]) -> list:
    return list(dict.fromkeys(values))


def _hash_payload(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        dict(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
