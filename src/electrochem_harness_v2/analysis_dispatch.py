"""Stable dispatch and replicate helpers for deterministic analyses."""
from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from typing import Any

from .analysis_common import SCHEMA_VERSION
from .csv_importer import GcdCsvImporter
from .cv_analysis import analyze_cv
from .eis_analysis import analyze_eis
from .gitt_analysis import analyze_gitt
from .replicate_stats import summarize_replicates

_SUPPORTED_METHODS = {"gcd", "cv", "eis", "gitt"}
_MISSING = object()


def analyze_experiment(
    method: str,
    source: Any,
    conditions: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Route one experiment and return a common, versioned envelope.

    Method-specific analysis parameters are accepted only through ``conditions``:
    ``scan_rate`` for CV, ``tail_fraction`` for EIS, and
    ``current_threshold_A`` for GITT. GCD retains the importer conditions API.
    """
    normalized_method = str(method or "").strip().casefold()
    if normalized_method not in _SUPPORTED_METHODS:
        raise ValueError(
            "Unknown analysis method {!r}; expected one of: gcd, cv, eis, gitt.".format(method)
        )
    if conditions is None:
        supplied_conditions: dict[str, Any] = {}
    elif isinstance(conditions, Mapping):
        supplied_conditions = dict(conditions)
    else:
        raise TypeError("conditions must be a mapping when provided.")

    if normalized_method == "gcd":
        imported = GcdCsvImporter().read(source, conditions=supplied_conditions)
        native = dict(imported.analysis)
        limitations = list(native.get("limitations") or [])
        quality_flags = list(native.get("warnings") or [])
        metadata = asdict(imported.metadata)
        metadata["conditions"] = supplied_conditions
    elif normalized_method == "cv":
        scan_rate = _optional_positive_number(supplied_conditions, "scan_rate")
        scan_rate_unit = supplied_conditions.get("scan_rate_unit", "V/s")
        native_result = analyze_cv(
            source,
            units=_optional_units(supplied_conditions),
            scan_rate=scan_rate,
            scan_rate_unit=scan_rate_unit,
        )
        native, limitations, quality_flags = _split_native_result(native_result)
        metadata = _metadata(source, supplied_conditions)
    elif normalized_method == "eis":
        tail_fraction = _optional_positive_number(
            supplied_conditions, "tail_fraction", default=0.3
        )
        native_result = analyze_eis(
            source,
            units=_optional_units(supplied_conditions),
            tail_fraction=tail_fraction,
        )
        native, limitations, quality_flags = _split_native_result(native_result)
        metadata = _metadata(source, supplied_conditions)
    else:
        threshold = _required_positive_number(supplied_conditions, "current_threshold_A", "gitt")
        native_result = analyze_gitt(
            source,
            units=_optional_units(supplied_conditions),
            current_threshold_A=threshold,
        )
        native, limitations, quality_flags = _split_native_result(native_result)
        metadata = _metadata(source, supplied_conditions)

    return {
        "schema_version": SCHEMA_VERSION,
        "analysis_type": normalized_method,
        "metadata": metadata,
        "analysis": native,
        "limitations": limitations,
        "quality_flags": sorted(set(quality_flags)),
    }


def extract_replicate_metric(
    analysis_result: Mapping[str, Any],
    metric: str,
    unit: str | None = None,
) -> dict[str, Any]:
    """Extract one finite scalar metric as a row accepted by replicate_stats.

    ``metric`` may be a dotted path, including list indexes, or a simple key.
    A simple key must occur exactly once in the analysis payload. Units are
    inferred from canonical metric suffixes or read from an explicit
    ``{"value": ..., "unit": ...}`` metric value.
    """
    if not isinstance(analysis_result, Mapping):
        raise TypeError("Each analysis result must be a mapping.")
    metric_name = str(metric or "").strip()
    if not metric_name:
        raise ValueError("metric is required.")

    root = analysis_result.get("analysis", analysis_result)
    value = _resolve_metric(root, metric_name)
    declared_unit = None
    if isinstance(value, Mapping) and "value" in value:
        declared_unit = str(value.get("unit") or "").strip() or None
        value = value["value"]

    metadata = analysis_result.get("metadata")
    if declared_unit is None and isinstance(metadata, Mapping):
        metric_units = metadata.get("metric_units")
        if isinstance(metric_units, Mapping) and metric_name in metric_units:
            declared_unit = str(metric_units[metric_name]).strip() or None
    inferred_unit = _metric_unit(metric_name)
    actual_unit = declared_unit or inferred_unit
    requested_unit = str(unit).strip() if unit is not None else None
    if not actual_unit:
        if not requested_unit:
            raise ValueError("unit is required because it cannot be inferred from metric {!r}.".format(metric_name))
        actual_unit = requested_unit
    if requested_unit and actual_unit != requested_unit:
        raise ValueError(
            "Metric {!r} has unit {!r}, not {!r}; implicit conversion is not supported.".format(
                metric_name, actual_unit, requested_unit
            )
        )
    if isinstance(value, bool):
        raise ValueError("Metric {!r} must be a finite numeric scalar.".format(metric_name))
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError("Metric {!r} must be a finite numeric scalar.".format(metric_name)) from error
    if not math.isfinite(number):
        raise ValueError("Metric {!r} must be a finite numeric scalar.".format(metric_name))
    return {"value": number, "metric": metric_name, "unit": actual_unit}


def summarize_analysis_replicates(
    analyses: Iterable[Mapping[str, Any]],
    metric: str,
    unit: str | None = None,
) -> dict[str, Any]:
    """Summarize one same-name, same-unit metric across analysis results."""
    rows = [extract_replicate_metric(item, metric, unit=unit) for item in analyses]
    return summarize_replicates(rows)


def _optional_positive_number(
    conditions: Mapping[str, Any],
    key: str,
    *,
    default: float | None = None,
) -> float | None:
    value = conditions.get(key, default)
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError("conditions[{!r}] must be a finite positive number.".format(key))
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError("conditions[{!r}] must be a finite positive number.".format(key)) from error
    if not math.isfinite(number) or number <= 0:
        raise ValueError("conditions[{!r}] must be a finite positive number.".format(key))
    return number


def _required_positive_number(conditions: Mapping[str, Any], key: str, method: str) -> float:
    value = conditions.get(key, _MISSING)
    if value is _MISSING or value is None or value == "" or isinstance(value, bool):
        raise ValueError("{} analysis requires conditions[{!r}].".format(method.upper(), key))
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError("conditions[{!r}] must be a finite positive number.".format(key)) from error
    if not math.isfinite(number) or number <= 0:
        raise ValueError("conditions[{!r}] must be a finite positive number.".format(key))
    return number


def _optional_units(conditions: Mapping[str, Any]) -> Mapping[str, str] | None:
    units = conditions.get("units")
    if units is None:
        return None
    if not isinstance(units, Mapping):
        raise TypeError("conditions['units'] must be a mapping.")
    return units


def _metadata(source: Any, used_conditions: Mapping[str, Any]) -> dict[str, Any]:
    source_name = Path(source).name if isinstance(source, (str, Path)) else None
    if isinstance(source, (str, Path)):
        source_hash = hashlib.sha256(Path(source).read_bytes()).hexdigest()
    else:
        serialized = json.dumps(source, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
        source_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    return {"source_name": source_name, "sha256": source_hash, "conditions": dict(used_conditions)}


_RAW_FEATURE_KEYS = frozenset({
    "normalized_points", "points", "rows", "series", "raw_points", "raw_rows",
    "raw_series", "data_points", "measurements", "point_level_data",
})


def build_analysis_feature_packet(analysis_payload: Mapping[str, Any]) -> dict[str, Any]:
    """Build the smallest method-aware model packet without point-level arrays."""
    method = str(analysis_payload.get("analysis_type") or "gcd").strip().casefold()
    if method == "gcd":
        from .gcd_metrics import build_codex_feature_packet
        return build_codex_feature_packet(dict(analysis_payload))

    def scrub(value: Any) -> Any:
        if isinstance(value, Mapping):
            return {
                str(key): scrub(item)
                for key, item in value.items()
                if str(key).casefold() not in _RAW_FEATURE_KEYS
            }
        if isinstance(value, (list, tuple)):
            return [scrub(item) for item in value]
        return value

    metadata = dict(analysis_payload.get("metadata") or {})
    native = scrub(dict(analysis_payload.get("analysis") or {}))
    return {
        "analysis_type": method,
        "source_sha256": metadata.get("sha256"),
        "source_name": metadata.get("source_name"),
        "conditions": scrub(dict(metadata.get("conditions") or {})),
        "deterministic_metrics": native,
        "limitations": [str(item) for item in analysis_payload.get("limitations") or []],
        "quality_flags": [str(item) for item in analysis_payload.get("quality_flags") or []],
        "feature_boundary": "Only deterministic aggregate features are supplied; normalized points, raw points, rows, and series are excluded.",
    }


def _split_native_result(result: Mapping[str, Any]) -> tuple[dict[str, Any], list[str], list[str]]:
    native = dict(result)
    native.pop("schema_version", None)
    limitations = list(native.pop("limitations", []) or [])
    quality_flags = list(native.pop("quality_flags", []) or [])
    return native, limitations, quality_flags


def _resolve_metric(root: Any, metric: str) -> Any:
    if "." in metric:
        current = root
        for part in metric.split("."):
            if isinstance(current, Mapping):
                if part not in current:
                    raise ValueError("Metric path {!r} was not found.".format(metric))
                current = current[part]
            elif isinstance(current, (list, tuple)) and part.isdigit():
                try:
                    current = current[int(part)]
                except IndexError as error:
                    raise ValueError("Metric path {!r} was not found.".format(metric)) from error
            else:
                raise ValueError("Metric path {!r} was not found.".format(metric))
        return current

    matches: list[Any] = []

    def visit(value: Any) -> None:
        if isinstance(value, Mapping):
            if metric in value:
                matches.append(value[metric])
            for child in value.values():
                visit(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                visit(child)

    visit(root)
    if not matches:
        raise ValueError("Metric {!r} was not found.".format(metric))
    if len(matches) > 1:
        raise ValueError("Metric {!r} is ambiguous; use a dotted path.".format(metric))
    return matches[0]


def _metric_unit(metric: str) -> str | None:
    name = metric.rsplit(".", 1)[-1]
    suffixes = (
        ("_mAh_g", "mAh/g"),
        ("_m2_s", "m2/s"),
        ("_V_s", "V/s"),
        ("_Hz", "Hz"),
        ("_ohm", "ohm"),
        ("_percent", "%"),
        ("_V", "V"),
        ("_A", "A"),
        ("_s", "s"),
        ("_C", "C"),
    )
    for suffix, metric_unit in suffixes:
        if name.endswith(suffix):
            return metric_unit
    if name == "slope_d_minus_z_imag_d_z_real":
        return "1"
    return None
