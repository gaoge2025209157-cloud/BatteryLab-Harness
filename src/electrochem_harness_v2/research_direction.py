"""Deterministic, evidence-bounded research direction from GCD feature summaries."""
from __future__ import annotations

from typing import Mapping


def _as_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def build_research_direction(analysis: Mapping, conditions: Mapping | None = None) -> dict:
    """Return auditable conclusions and actions without asserting a reaction mechanism.

    The result only interprets deterministic GCD summaries and data-quality flags.
    It deliberately separates measured/exported observations from hypotheses requiring
    follow-up evidence.
    """
    gcd = dict(analysis.get("gcd_summary") or {})
    first_capacity = _as_float(gcd.get("first_complete_discharge_capacity_mAh_g"))
    latest_capacity = _as_float(gcd.get("latest_complete_discharge_capacity_mAh_g"))
    retention = _as_float(gcd.get("latest_capacity_retention_percent"))
    polarization = _as_float(gcd.get("latest_polarization_voltage_V"))
    efficiency = _as_float(gcd.get("latest_coulombic_efficiency_percent"))
    negative_voltage = int(analysis.get("negative_voltage_count") or 0)
    time_anomalies = int(analysis.get("repeated_or_reversed_time_pairs") or 0)
    complete_cycles = int(gcd.get("complete_cycle_count") or 0)
    active_mass_mg = _as_float((conditions or {}).get("active_material_mass_mg"))
    has_active_mass = active_mass_mg is not None and active_mass_mg > 0

    observations = []
    risks = []
    actions = []
    if first_capacity is not None:
        observations.append("首个完整候选循环的仪器导出放电比容量为 {:.1f} mAh g⁻¹。".format(first_capacity))
        if has_active_mass:
            observations.append("本轮登记的活性物质质量为 {:.3f} mg；该值作为仪器导出比容量的归一化记录，仍应与电极配方和仪器设置保持一致。".format(active_mass_mg))
        else:
            observations.append("本轮未登记活性物质质量，因此该比容量仅保留为仪器导出值。")
    if latest_capacity is not None and retention is not None:
        observations.append("最新导出放电比容量为 {:.1f} mAh g⁻¹，容量保持率为 {:.2f}%{}。".format(latest_capacity, retention, "（完整候选循环数：{}）".format(complete_cycles) if complete_cycles else ""))
    if polarization is not None:
        observations.append("最新容量加权充放电极化为 {:.3f} V。该数值应在测试条件一致的重复实验中解释。".format(polarization))
    if efficiency is not None:
        observations.append("最新库仑效率为 {:.2f}%。该数值不能独立证明长期可逆性，必须结合绝对容量保持和重复电池验证。".format(efficiency))
    if negative_voltage:
        risks.append("检测到 {} 条负电压记录，需回看电压参照、仪器量程和导出设置。".format(negative_voltage))
    if time_anomalies:
        risks.append("检测到 {} 对重复或倒序相邻时间记录，候选循环边界必须与仪器步骤日志交叉核验。".format(time_anomalies))

    actions.extend([
        {
            "priority": "P0｜核对仪器步骤与分段",
            "goal": "确认循环方向、容量重置与逐步电量是否能够支持当前曲线解释。",
            "single_variable": "不改变电池，只将自动候选分段与仪器步骤编号、原始电流—时间积分逐段对应。",
            "decision_evidence": "步骤方向、容量重置与积分电量相互一致后，才能将完整循环的容量、效率和极化用于后续判断。",
        },
        {
            "priority": "P1｜验证容量趋势",
            "goal": "通过重复实验确认容量变化，并区分材料、界面、传输或测试定义的影响。",
            "single_variable": "在数据口径和步骤定义固定后，只比较相同测试条件与荷电状态的样品。",
            "decision_evidence": "结合重复循环、阻抗或与假设匹配的表征，判断容量变化是否可重复并与其他信号同步。",
        },
        {
            "priority": "P2｜检验倍率响应",
            "goal": "判断测试电流变化是否影响容量和极化，并为后续机理假设提供数据。",
            "single_variable": "保持已登记的其他实验条件不变，只改变测试电流。",
            "decision_evidence": "比较平均放电电压、极化和可逆容量随电流的变化；强烈电流依赖提示动力学或传输限制。",
        },
        {
            "priority": "P3｜验证反应与界面状态",
            "goal": "建立可追溯的反应/界面证据，而不是仅由曲线推断机理。",
            "single_variable": "固定同一电池配方，只改变取样荷电状态：原始、首圈放电平台后、首圈充电后和后期同状态。",
            "decision_evidence": "采用与材料组成和待检验假设相匹配的结构或化学表征，对比不同荷电状态下的信号变化；只有可重复、状态相关的证据才能支持机理假设。",
        },
    ])

    if risks:
        headline = "当前最优先的工作是核对数据质量标志、仪器步骤与循环分段，再在条件一致的重复实验中解释容量和极化变化。"
    else:
        headline = "当前数据质量标志未显示突出异常；下一步应通过重复电池和单变量实验确认趋势。"
    return {
        "headline": headline,
        "observations": observations,
        "risks": risks,
        "actions": actions,
        "scope": "本节由 Harness 根据确定性 GCD 特征和质量标志生成，不使用未核验文献，也不构成反应机理证明。",
    }
