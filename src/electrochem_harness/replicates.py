"""Transparent replicate-cell statistics for Phase 2.

The module aligns cells by actual cycle number, retains every raw point and never
automatically removes an outlier.  Exclusion is accepted only when the caller
provides a reviewable reason.
"""

import csv
import hashlib
import json
import math
import statistics
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence, Tuple

from .scientific_standard import (
    SCIENTIFIC_STANDARD_VERSION,
    scientific_standard_hash,
)


_METRICS = (
    "charge_specific_capacity_mAh_g",
    "discharge_specific_capacity_mAh_g",
    "coulombic_efficiency",
    "capacity_retention",
    "average_charge_voltage_V",
    "average_discharge_voltage_V",
)

_T95 = {
    1: 12.706,
    2: 4.303,
    3: 3.182,
    4: 2.776,
    5: 2.571,
    6: 2.447,
    7: 2.365,
    8: 2.306,
    9: 2.262,
    10: 2.228,
    11: 2.201,
    12: 2.179,
    13: 2.160,
    14: 2.145,
    15: 2.131,
    16: 2.120,
    17: 2.110,
    18: 2.101,
    19: 2.093,
    20: 2.086,
    25: 2.060,
    30: 2.042,
}


@dataclass(frozen=True)
class ReplicateCell:
    cell_id: str
    condition_fingerprint: str
    cycles: Tuple[Mapping[str, Any], ...]
    excluded: bool = False
    exclusion_reason: str = ""

    def __post_init__(self) -> None:
        if not self.cell_id.strip():
            raise ValueError("cell_id must be nonempty")
        if not self.condition_fingerprint.strip():
            raise ValueError("condition fingerprint must be nonempty")
        if self.excluded and not self.exclusion_reason.strip():
            raise ValueError("excluded replicate requires an exclusion reason")
        object.__setattr__(self, "cycles", tuple(dict(item) for item in self.cycles))


@dataclass(frozen=True)
class ReplicateGroup:
    group_id: str
    condition_fingerprint: str
    cells: Tuple[ReplicateCell, ...]

    def __post_init__(self) -> None:
        if not self.group_id.strip():
            raise ValueError("group_id must be nonempty")
        if not self.cells:
            raise ValueError("replicate group requires at least one cell")
        identifiers = [cell.cell_id for cell in self.cells]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("replicate cell ids must be unique")
        object.__setattr__(self, "cells", tuple(self.cells))


@dataclass(frozen=True)
class RawReplicatePoint:
    cell_id: str
    value: float
    included: bool
    exclusion_reason: str
    outlier_flag: bool

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ReplicateMetric:
    metric: str
    cycle: int
    n: int
    mean: Optional[float]
    sample_sd: Optional[float]
    sem: Optional[float]
    ci95_low: Optional[float]
    ci95_high: Optional[float]
    coefficient_of_variation: Optional[float]
    raw_points: Tuple[RawReplicatePoint, ...]
    included_cell_ids: Tuple[str, ...]
    excluded_cell_ids: Tuple[str, ...]
    missing_cell_ids: Tuple[str, ...]

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["raw_points"] = [point.to_dict() for point in self.raw_points]
        payload["included_cell_ids"] = list(self.included_cell_ids)
        payload["excluded_cell_ids"] = list(self.excluded_cell_ids)
        payload["missing_cell_ids"] = list(self.missing_cell_ids)
        return payload


@dataclass(frozen=True)
class ReplicateResult:
    group_id: str
    condition_fingerprint: str
    standard_version: str
    standard_hash: str
    interpretation: str
    total_cells: int
    included_cells: int
    warnings: Tuple[str, ...]
    metrics: Tuple[ReplicateMetric, ...]

    def metric(self, name: str, cycle: int) -> ReplicateMetric:
        for item in self.metrics:
            if item.metric == name and item.cycle == cycle:
                return item
        raise KeyError("metric not found: {} cycle {}".format(name, cycle))

    def to_dict(self) -> dict:
        return {
            "group_id": self.group_id,
            "condition_fingerprint": self.condition_fingerprint,
            "standard_version": self.standard_version,
            "standard_hash": self.standard_hash,
            "interpretation": self.interpretation,
            "total_cells": self.total_cells,
            "included_cells": self.included_cells,
            "warnings": list(self.warnings),
            "metrics": [metric.to_dict() for metric in self.metrics],
        }


def _t95(df: int) -> float:
    if df <= 0:
        raise ValueError("degrees of freedom must be positive")
    for threshold in sorted(_T95):
        if df <= threshold:
            return _T95[threshold]
    return 1.96


def _outlier_ids(values: Sequence[Tuple[str, float]]) -> set:
    """Flag robust modified-z outliers for n>=5; do not remove them."""

    if len(values) < 5:
        return set()
    numbers = [value for _, value in values]
    centre = statistics.median(numbers)
    deviations = [abs(value - centre) for value in numbers]
    mad = statistics.median(deviations)
    if mad == 0:
        nonzero = [value for value in deviations if value > 0]
        if not nonzero:
            return set()
        scale = min(nonzero)
    else:
        scale = mad
    return {
        cell_id
        for cell_id, value in values
        if 0.6745 * abs(value - centre) / scale > 3.5
    }


def _finite(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _statistic(group: ReplicateGroup, cycle_number: int, metric: str) -> ReplicateMetric:
    observations = []
    missing = []
    for cell in group.cells:
        cycle = next(
            (
                item
                for item in cell.cycles
                if int(item.get("cycle", -1)) == cycle_number and bool(item.get("complete", True))
            ),
            None,
        )
        value = None if cycle is None else _finite(cycle.get(metric))
        if value is None:
            missing.append(cell.cell_id)
            continue
        observations.append((cell, value))

    included = [(cell.cell_id, value) for cell, value in observations if not cell.excluded]
    flagged = _outlier_ids(included)
    raw = tuple(
        RawReplicatePoint(
            cell.cell_id,
            value,
            not cell.excluded,
            cell.exclusion_reason,
            cell.cell_id in flagged,
        )
        for cell, value in observations
    )
    values = [value for _, value in included]
    n = len(values)
    mean = statistics.fmean(values) if values else None
    sample_sd = statistics.stdev(values) if n >= 2 else None
    sem = sample_sd / math.sqrt(n) if sample_sd is not None else None
    margin = _t95(n - 1) * sem if sem is not None else None
    cv = abs(sample_sd / mean) if sample_sd is not None and mean not in (None, 0.0) else None
    return ReplicateMetric(
        metric,
        cycle_number,
        n,
        mean,
        sample_sd,
        sem,
        None if margin is None else mean - margin,
        None if margin is None else mean + margin,
        cv,
        raw,
        tuple(cell_id for cell_id, _ in included),
        tuple(cell.cell_id for cell, _ in observations if cell.excluded),
        tuple(missing),
    )


def analyze_replicates(group: ReplicateGroup) -> ReplicateResult:
    mismatched = [
        cell.cell_id
        for cell in group.cells
        if cell.condition_fingerprint != group.condition_fingerprint
    ]
    if mismatched:
        raise ValueError(
            "condition fingerprint mismatch for cells: {}".format(", ".join(mismatched))
        )
    included_cells = sum(not cell.excluded for cell in group.cells)
    interpretation = "replicated" if included_cells >= 3 else "exploratory"
    warnings = []
    if included_cells < 3:
        warnings.append("独立电池少于3个，只能作为探索性结果，不能证明重复性。")
    if any(cell.excluded for cell in group.cells):
        warnings.append("存在人工排除样本；报告保留原始点和排除理由，需由科学审核者确认事前规则。")

    cycle_numbers = sorted(
        {
            int(item["cycle"])
            for cell in group.cells
            for item in cell.cycles
            if "cycle" in item
        }
    )
    metrics = []
    for cycle in cycle_numbers:
        for metric in _METRICS:
            item = _statistic(group, cycle, metric)
            if item.raw_points or item.missing_cell_ids:
                metrics.append(item)
                if any(point.outlier_flag for point in item.raw_points):
                    warnings.append(
                        "{} 第{}圈存在MAD异常提示；该点仍纳入统计，除非按事前规则人工排除。".format(metric, cycle)
                    )
    return ReplicateResult(
        group.group_id,
        group.condition_fingerprint,
        SCIENTIFIC_STANDARD_VERSION,
        scientific_standard_hash(),
        interpretation,
        len(group.cells),
        included_cells,
        tuple(dict.fromkeys(warnings)),
        tuple(metrics),
    )


def _replicate_svg(result: ReplicateResult) -> str:
    selected = [
        item
        for item in result.metrics
        if item.metric == "discharge_specific_capacity_mAh_g" and item.mean is not None
    ]
    width, height = 1000, 650
    left, right, top, bottom = 110, 50, 55, 100
    plot_width = width - left - right
    plot_height = height - top - bottom
    if not selected:
        return (
            '<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="650" viewBox="0 0 1000 650">'
            '<rect width="100%" height="100%" fill="white"/>'
            '<text x="500" y="325" text-anchor="middle" font-family="Times New Roman" font-size="24">'
            'No complete specific-capacity replicate data</text></svg>\n'
        )

    cycles = [item.cycle for item in selected]
    values = [point.value for item in selected for point in item.raw_points]
    bounds = []
    for item in selected:
        bounds.append(item.mean)
        if item.sample_sd is not None:
            bounds.extend((item.mean - item.sample_sd, item.mean + item.sample_sd))
    y_min = min(values + bounds)
    y_max = max(values + bounds)
    span = y_max - y_min
    padding = span * 0.12 if span > 0 else max(abs(y_max) * 0.1, 1.0)
    y_min -= padding
    y_max += padding
    x_min, x_max = min(cycles), max(cycles)

    def x_position(cycle, offset=0.0):
        if x_max == x_min:
            return left + plot_width / 2.0 + offset
        return left + (cycle - x_min) * plot_width / (x_max - x_min) + offset

    def y_position(value):
        return top + (y_max - value) * plot_height / (y_max - y_min)

    lines = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="650" viewBox="0 0 1000 650">',
        '<rect width="100%" height="100%" fill="white"/>',
        '<text x="500" y="34" text-anchor="middle" font-family="Times New Roman" font-size="24">Replicate discharge capacity</text>',
        '<line x1="{0}" y1="{1}" x2="{2}" y2="{1}" stroke="black" stroke-width="3"/>'.format(left, top + plot_height, left + plot_width),
        '<line x1="{0}" y1="{1}" x2="{0}" y2="{2}" stroke="black" stroke-width="3"/>'.format(left, top, top + plot_height),
    ]
    for tick in range(6):
        value = y_min + tick * (y_max - y_min) / 5.0
        y = y_position(value)
        lines.append('<line x1="{0}" y1="{1:.2f}" x2="{2}" y2="{1:.2f}" stroke="#dddddd" stroke-width="1"/>'.format(left, y, left + plot_width))
        lines.append('<text x="{0}" y="{1:.2f}" text-anchor="end" dominant-baseline="middle" font-family="Times New Roman" font-size="18">{2:.4g}</text>'.format(left - 12, y, value))
    for item in selected:
        x = x_position(item.cycle)
        lines.append('<line x1="{0:.2f}" y1="{1}" x2="{0:.2f}" y2="{2}" stroke="black" stroke-width="2"/>'.format(x, top + plot_height, top + plot_height + 8))
        lines.append('<text x="{0:.2f}" y="{1}" text-anchor="middle" font-family="Times New Roman" font-size="18">{2}</text>'.format(x, top + plot_height + 32, item.cycle))
        if item.sample_sd is not None:
            high = y_position(item.mean + item.sample_sd)
            low = y_position(item.mean - item.sample_sd)
            lines.extend(
                [
                    '<line data-role="sd-error-bar" x1="{0:.2f}" y1="{1:.2f}" x2="{0:.2f}" y2="{2:.2f}" stroke="#222222" stroke-width="2"/>'.format(x, high, low),
                    '<line x1="{0:.2f}" y1="{1:.2f}" x2="{2:.2f}" y2="{1:.2f}" stroke="#222222" stroke-width="2"/>'.format(x - 8, high, x + 8),
                    '<line x1="{0:.2f}" y1="{1:.2f}" x2="{2:.2f}" y2="{1:.2f}" stroke="#222222" stroke-width="2"/>'.format(x - 8, low, x + 8),
                ]
            )
        ordered = sorted(item.raw_points, key=lambda point: point.cell_id)
        centre = (len(ordered) - 1) / 2.0
        for index, point in enumerate(ordered):
            offset = (index - centre) * 9.0
            colour = "#999999" if not point.included else ("#d62728" if point.outlier_flag else "#1f77b4")
            lines.append(
                '<circle data-cell="{}" cx="{:.2f}" cy="{:.2f}" r="5" fill="{}" fill-opacity="0.72" stroke="black" stroke-width="1"/>'.format(
                    point.cell_id.replace('"', ""), x_position(item.cycle, offset), y_position(point.value), colour
                )
            )
        lines.append('<rect x="{0:.2f}" y="{1:.2f}" width="10" height="10" fill="black" transform="translate(-5,-5)"/>'.format(x, y_position(item.mean)))
    lines.extend(
        [
            '<text x="{0}" y="{1}" text-anchor="middle" font-family="Times New Roman" font-size="22">Cycle Number</text>'.format(left + plot_width / 2.0, height - 28),
            '<text x="28" y="{0}" text-anchor="middle" font-family="Times New Roman" font-size="22" transform="rotate(-90 28 {0})">Specific Capacity (mAh g^-1)</text>'.format(top + plot_height / 2.0),
            '<circle cx="720" cy="620" r="5" fill="#1f77b4" stroke="black"/><text x="734" y="626" font-family="Times New Roman" font-size="16">raw cell</text>',
            '<rect x="825" y="615" width="10" height="10" fill="black"/><text x="842" y="626" font-family="Times New Roman" font-size="16">mean ± sample SD</text>',
            '</svg>',
        ]
    )
    return "\n".join(lines) + "\n"


def _display(value: Optional[float]) -> str:
    return "—" if value is None else "{:.6g}".format(value)


def write_replicate_outputs(result: ReplicateResult, output_dir: Path) -> dict:
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    json_path = target / "平行电池统计.json"
    csv_path = target / "平行电池统计.csv"
    report_path = target / "平行电池统计报告.md"
    plot_path = target / "平行电池统计图.svg"
    json_path.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    plot_path.write_text(_replicate_svg(result), encoding="utf-8")

    fields = [
        "metric", "cycle", "n", "mean", "sample_sd", "sem", "ci95_low", "ci95_high",
        "coefficient_of_variation", "cell_id", "raw_value", "included", "outlier_flag", "exclusion_reason",
    ]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for metric in result.metrics:
            for point in metric.raw_points:
                writer.writerow(
                    {
                        "metric": metric.metric,
                        "cycle": metric.cycle,
                        "n": metric.n,
                        "mean": metric.mean,
                        "sample_sd": metric.sample_sd,
                        "sem": metric.sem,
                        "ci95_low": metric.ci95_low,
                        "ci95_high": metric.ci95_high,
                        "coefficient_of_variation": metric.coefficient_of_variation,
                        "cell_id": point.cell_id,
                        "raw_value": point.value,
                        "included": point.included,
                        "outlier_flag": point.outlier_flag,
                        "exclusion_reason": point.exclusion_reason,
                    }
                )

    lines = [
        "# 平行电池统计报告",
        "",
        "- 实验组：{}".format(result.group_id),
        "- 独立电池：{}个；纳入统计：{}个".format(result.total_cells, result.included_cells),
        "- 解释等级：{}".format("重复性统计" if result.interpretation == "replicated" else "探索性单/双样本"),
        "- 科学标准：{}（SHA-256 `{}`）".format(result.standard_version, result.standard_hash),
        "- 统计口径：算术均值、样本标准差（n-1）、标准误和双侧95% Student t区间；原始散点全部保留。",
        "",
    ]
    if result.warnings:
        lines.extend(["## 警告", ""] + ["- {}".format(item) for item in result.warnings] + [""])
    lines.extend(
        [
            "## 汇总",
            "",
            "| 指标 | 循环 | n | 均值 | 样本标准差 | SEM | 95% CI |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for metric in result.metrics:
        lines.append(
            "| {} | {} | {} | {} | {} | {} | {}–{} |".format(
                metric.metric,
                metric.cycle,
                metric.n,
                _display(metric.mean),
                _display(metric.sample_sd),
                _display(metric.sem),
                _display(metric.ci95_low),
                _display(metric.ci95_high),
            )
        )
    lines.extend(["", "## 原始散点与审计", "", "完整原始点、异常提示和人工排除理由见 `平行电池统计.csv`；异常提示不会自动删除数据。", ""])
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return {"json": json_path, "csv": csv_path, "report": report_path, "plot": plot_path}



def _condition_fingerprint(metadata: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        dict(metadata), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _normalize_raw_cycles(metrics) -> Tuple[Mapping[str, Any], ...]:
    cycles = []
    for item in metrics:
        payload = item.to_dict()
        cycles.append(
            {
                "cycle": payload["cycle"],
                "charge_specific_capacity_mAh_g": payload.get("specific_charge_capacity_mAh_g"),
                "discharge_specific_capacity_mAh_g": payload.get("specific_discharge_capacity_mAh_g"),
                "coulombic_efficiency": payload.get("coulombic_efficiency"),
                "capacity_retention": payload.get("capacity_retention"),
                "average_charge_voltage_V": payload.get("average_charge_voltage_V"),
                "average_discharge_voltage_V": payload.get("average_discharge_voltage_V"),
                "complete": bool(
                    payload.get("charge_capacity_mAh", 0) > 0
                    and payload.get("discharge_capacity_mAh", 0) > 0
                ),
            }
        )
    return tuple(cycles)


def _load_cell_cycles(source: Path, active_mass_mg: Optional[float]) -> Tuple[Mapping[str, Any], ...]:
    try:
        from .land_curve import analyze_land_capacity_curve

        payload = analyze_land_capacity_curve(source)
        return tuple(dict(item) for item in payload["report"].get("cycles", ()))
    except (OSError, UnicodeError, ValueError):
        from .analysis import analyze_cycles
        from .land import load_land_export

        imported = load_land_export(source)
        return _normalize_raw_cycles(analyze_cycles(imported.points, active_mass_mg=active_mass_mg))


def load_replicate_manifest(path: Path) -> ReplicateGroup:
    manifest_path = Path(path).resolve()
    payload = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, Mapping):
        raise ValueError("replicate manifest root must be a JSON object")
    metadata = payload.get("experiment_metadata", {})
    if not isinstance(metadata, Mapping) or not metadata:
        raise ValueError("replicate manifest requires experiment_metadata")
    fingerprint = _condition_fingerprint(metadata)
    cells = []
    for item in payload.get("cells", ()):
        if not isinstance(item, Mapping):
            raise ValueError("replicate cells must be JSON objects")
        relative = Path(str(item.get("input_file", "")))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("replicate input paths must be relative to the manifest")
        source = (manifest_path.parent / relative).resolve()
        try:
            source.relative_to(manifest_path.parent)
        except ValueError as error:
            raise ValueError("replicate input resolves outside the manifest directory") from error
        if not source.is_file():
            raise ValueError("replicate input is missing: {}".format(relative))
        active_mass = item.get("active_mass_mg")
        if active_mass is not None:
            active_mass = float(active_mass)
        cells.append(
            ReplicateCell(
                cell_id=str(item.get("cell_id", "")),
                condition_fingerprint=fingerprint,
                cycles=_load_cell_cycles(source, active_mass),
                excluded=bool(item.get("excluded", False)),
                exclusion_reason=str(item.get("exclusion_reason", "")),
            )
        )
    return ReplicateGroup(str(payload.get("group_id", "")), fingerprint, tuple(cells))


def run_replicate_manifest(path: Path, output_dir: Path):
    result = analyze_replicates(load_replicate_manifest(path))
    return result, write_replicate_outputs(result, output_dir)
