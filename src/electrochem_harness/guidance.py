from pathlib import Path
from typing import List

from .analysis import analyze_cycles, load_cycling_csv
from .knowledge import KnowledgeBase
from .models import (
    ExperimentContext,
    HarnessReport,
    QualityIssue,
    Recommendation,
)


REQUIRED_CONTEXT = ("system_type", "electrolyte", "anode", "atmosphere")
UNKNOWN_VALUES = (None, "", "待填", "???")


def _missing_context(context: ExperimentContext) -> List[str]:
    return [name for name in REQUIRED_CONTEXT if getattr(context, name) in UNKNOWN_VALUES]


def _quality_issues(points, context: ExperimentContext) -> List[QualityIssue]:
    issues = []
    for previous, current in zip(points, points[1:]):
        if current.time_s <= previous.time_s:
            issues.append(
                QualityIssue(
                    code="non_monotonic_time",
                    message="time_s must increase strictly; rows {} and {} violate this rule.".format(
                        previous.source_row, current.source_row
                    ),
                    blocking=True,
                )
            )
            break
    negative_voltage_rows = [point.source_row for point in points if point.voltage_V < 0]
    if negative_voltage_rows:
        issues.append(
            QualityIssue(
                code="negative_voltage",
                message=(
                    "{} points have voltage below 0 V (first source row {}); "
                    "review the configured voltage window and instrument settings."
                ).format(len(negative_voltage_rows), negative_voltage_rows[0]),
                blocking=False,
            )
        )

    cycle_numbers = sorted({point.cycle for point in points})
    jumps = [
        (left, right)
        for left, right in zip(cycle_numbers, cycle_numbers[1:])
        if right != left + 1
    ]
    if jumps:
        issues.append(
            QualityIssue(
                code="cycle_number_jump",
                message="source cycle numbers contain jumps: {}".format(
                    ", ".join("{}->{}".format(left, right) for left, right in jumps)
                ),
                blocking=False,
            )
        )

    for cycle in cycle_numbers:
        currents = [point.current_mA for point in points if point.cycle == cycle]
        has_charge = any(current > 0 for current in currents)
        has_discharge = any(current < 0 for current in currents)
        if not has_charge or not has_discharge:
            missing = "charge" if not has_charge else "discharge"
            issues.append(
                QualityIssue(
                    code="incomplete_cycle",
                    message="source cycle {} has no {} current interval; paired efficiency and retention are unavailable.".format(
                        cycle, missing
                    ),
                    blocking=False,
                )
            )
    if context.active_mass_mg is None:
        issues.append(
            QualityIssue(
                code="missing_active_mass",
                message="active_mass_mg is missing; specific capacity is not calculated.",
                blocking=False,
            )
        )
    elif context.active_mass_mg <= 0:
        issues.append(
            QualityIssue(
                code="invalid_active_mass",
                message="active_mass_mg must be greater than zero.",
                blocking=True,
            )
        )
    return issues


def _conclusions(metrics) -> List[str]:
    if not metrics:
        return []
    latest = metrics[-1]
    conclusions = ["共分析 {} 个循环。".format(len(metrics))]
    conclusions.append(
        "第 {} 圈放电容量为 {:.6g} mAh。".format(
            latest.cycle, latest.discharge_capacity_mAh
        )
    )
    if latest.specific_discharge_capacity_mAh_g is not None:
        conclusions.append(
            "按给定活性物质量归一化后，第 {} 圈放电比容量为 {:.6g} mAh/g。".format(
                latest.cycle, latest.specific_discharge_capacity_mAh_g
            )
        )
    if latest.coulombic_efficiency is not None:
        conclusions.append(
            "第 {} 圈库仑效率为 {:.2%}。".format(
                latest.cycle, latest.coulombic_efficiency
            )
        )
    if latest.capacity_retention is not None:
        conclusions.append(
            "相对首个有效放电循环，第 {} 圈容量保持率为 {:.2%}。".format(
                latest.cycle, latest.capacity_retention
            )
        )
    return conclusions


def _rule_recommendations(context, metrics, knowledge_base) -> List[Recommendation]:
    if not metrics:
        return []
    latest = metrics[-1]
    recommendations = []
    for rule in knowledge_base.matching_rules(context, latest):
        metric = rule["metric"]
        evidence = "{}={:.6g}; criterion {} {}".format(
            metric, rule["observed_value"], rule["operator"], rule["threshold"]
        )
        recommendations.append(
            Recommendation(
                title=rule["claim"],
                observation=evidence,
                action=rule["action"],
                evidence=evidence,
                confidence=float(rule.get("confidence", 0.5)),
                risk="通用规则不能直接证明具体化学机理；需要结合体系信息和复现实验。",
                requires_confirmation=True,
                source_id=rule["id"],
                source=rule.get("source", "unknown"),
            )
        )
    return recommendations


def _experience_recommendations(context, knowledge_base) -> List[Recommendation]:
    if not context.system_type:
        return []
    recommendations = []
    for experience in knowledge_base.experiences.find(
        context.experiment_type, context.system_type, min_confidence=0.5
    ):
        recommendations.append(
            Recommendation(
                title="同体系历史经验候选",
                observation=experience.observation,
                action=experience.action,
                evidence="{}; outcome={}".format(experience.evidence, experience.outcome),
                confidence=experience.confidence,
                risk="历史相关性不等于因果；批次、材料和设备条件可能不同。",
                requires_confirmation=True,
                source_id=experience.id,
                source="project-experience",
            )
        )
    return recommendations


def run_harness_points(
    points, context: ExperimentContext, knowledge_base: KnowledgeBase
) -> HarnessReport:
    points = list(points)
    issues = _quality_issues(points, context)
    missing = _missing_context(context)
    for name in missing:
        issues.append(
            QualityIssue(
                code="missing_context_{}".format(name),
                message="{} is unknown; system-level guidance is downgraded.".format(name),
                blocking=False,
            )
        )

    if any(issue.blocking for issue in issues):
        return HarnessReport(
            status="blocked",
            metrics=[],
            quality_issues=issues,
            conclusions=[],
            recommendations=[],
            missing_context=missing,
        )

    metrics = analyze_cycles(points, context.active_mass_mg)
    recommendations = _rule_recommendations(context, metrics, knowledge_base)
    recommendations.extend(_experience_recommendations(context, knowledge_base))
    status = "warning" if issues or recommendations else "ok"
    return HarnessReport(
        status=status,
        metrics=metrics,
        quality_issues=issues,
        conclusions=_conclusions(metrics),
        recommendations=recommendations,
        missing_context=missing,
    )



def run_harness(
    csv_path: Path, context: ExperimentContext, knowledge_base: KnowledgeBase
) -> HarnessReport:
    return run_harness_points(load_cycling_csv(csv_path), context, knowledge_base)
