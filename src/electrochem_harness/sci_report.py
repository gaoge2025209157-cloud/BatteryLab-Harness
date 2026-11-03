"""Concise scientific report rendering for electrochemical results."""

import csv
import json
from pathlib import Path
from statistics import median
from typing import Optional

from .scientific_guidance import render_scientific_guidance, select_representative_cycles
from .scientific_standard import (
    scientific_standard_identity,
    scientific_standard_manifest,
)


def _number(value, digits=1, missing="—"):
    return missing if value is None else ("{:.{}f}".format(value, digits))


def _percent(value, missing="—"):
    return missing if value is None else "{:.2%}".format(value)


def _reported_metric(records, key):
    values = []
    for record in records:
        value = record.get("metrics", {}).get(key)
        if value is not None:
            values.append(float(value))
    return values


def _render_literature_and_value(payload, research_profile, literature_result):
    lines = ["", "## 文献证据与数据价值", ""]
    if research_profile is None:
        lines.append("**文献对比暂缓。** 尚未填写完整实验元数据。")
        return lines

    missing = research_profile.missing_required()
    if missing:
        lines.append(
            "**文献对比暂缓。** 缺少{}；不同体系、测试条件和归一化口径下的数据不可直接比较。".format(
                "、".join(missing)
            )
        )
        return lines
    if literature_result is None:
        lines.append("实验条件已完整，但本次未启用联网文献检索，因此不生成无来源的水平判断。")
        return lines
    if literature_result.get("error"):
        lines.append(
            "联网检索失败：{}。当前数值分析仍有效，但文献水平与数据价值暂不可判定。".format(
                literature_result["error"]
            )
        )
        return lines

    records = [record for record in literature_result.get("records", []) if record.get("doi_verified")]
    direct = [record for record in records if record.get("match_level") == "direct"]
    lines.append(
        "- 检索源：{}；候选 DOI {} 条，单篇元数据核验通过 {} 条，直接可比 {} 条。".format(
            literature_result.get("source", "—"),
            literature_result.get("candidate_count", literature_result.get("verified_count", 0)),
            literature_result.get("verified_count", len(records)),
            literature_result.get("directly_comparable_count", len(direct)),
        )
    )
    lines.append(
        "- 筛选口径：仅将电池体系、活性物质、电池类型/对电极、测试电流、温度及质量归一化口径均在题名或摘要中明确匹配的论文视为直接可比。"
    )

    if records:
        lines.extend(
            [
                "",
                "### 经 DOI 核验的优先文献",
                "",
                "| 可比性 | 年份 | 期刊 | 题名 | 摘要显式性能 | DOI |",
                "|---|---:|---|---|---|---|",
            ]
        )
        for record in records[:10]:
            metrics = record.get("metrics", {})
            reported = []
            if metrics.get("specific_capacity_mAh_g") is not None:
                reported.append("{:.1f} mAh/g".format(metrics["specific_capacity_mAh_g"]))
            if metrics.get("coulombic_efficiency_percent") is not None:
                reported.append("CE {:.2f}%".format(metrics["coulombic_efficiency_percent"]))
            if metrics.get("capacity_retention_percent") is not None:
                reported.append("保持率 {:.2f}%".format(metrics["capacity_retention_percent"]))
            doi = record["doi"]
            lines.append(
                "| {} | {} | {} | {} | {} | [{}](https://doi.org/{}) |".format(
                    "直接可比" if record.get("match_level") == "direct" else "仅背景相关",
                    record.get("year") or "—",
                    str(record.get("journal") or "—").replace("|", "/"),
                    str(record.get("title") or "—").replace("|", "/"),
                    "；".join(reported) or "摘要未明确给出",
                    doi,
                    doi,
                )
            )

    lines.extend(["", "### 数据价值判断", ""])
    if not direct:
        lines.append(
            "**暂不可判定。** 当前检索结果中暂无直接可比基准；背景相关论文不能用于给出领先、一般或落后的等级结论。"
        )
        return lines

    completed = [item for item in payload["report"].get("cycles", []) if item.get("complete")]
    if not completed:
        lines.append("**暂不可判定。** 当前数据没有完整充放电循环。")
        return lines
    current = completed[-1]
    capacity_values = _reported_metric(direct, "specific_capacity_mAh_g")
    ce_values = _reported_metric(direct, "coulombic_efficiency_percent")
    if capacity_values:
        current_capacity = current.get("discharge_specific_capacity_mAh_g")
        if current_capacity is not None:
            lines.append(
                "- 放电比容量：当前最后完整圈 **{:.1f} mAh/g**；直接可比文献摘要中值 **{:.1f} mAh/g**，范围 {:.1f}–{:.1f} mAh/g（n={}）。".format(
                    current_capacity,
                    median(capacity_values),
                    min(capacity_values),
                    max(capacity_values),
                    len(capacity_values),
                )
            )
    if ce_values:
        current_ce = current.get("coulombic_efficiency")
        if current_ce is not None:
            lines.append(
                "- 库仑效率：当前最后完整圈 **{:.2%}**；直接可比文献摘要中值 **{:.2f}%**（n={}）。".format(
                    current_ce, median(ce_values), len(ce_values)
                )
            )
    retention = current.get("capacity_retention")
    if retention is not None:
        lines.append(
            "- 当前完整循环容量保持率为 **{:.2%}**；比较时仍需对齐文献循环圈数，不能把不同循环长度直接并列。".format(
                retention
            )
        )
    if len(direct) < 3:
        lines.append(
            "- 直接可比文献少于 3 条，当前判断仅是小样本定位；数据价值主要在于形成可复核趋势，尚不足以支持总体竞争力或创新性结论。"
        )
    else:
        lines.append(
            "- 上述定位仅反映公开摘要中的同条件性能区间；创新性仍需结合材料设计、机理证据、重复性和统计误差单独判断。"
        )
    return lines


def render_readable_summary(payload, research_profile=None, literature_result=None) -> str:
    """Render a decision-facing plain-text analysis with auditable limits."""

    report = payload.get("report", {})
    cycles = list(report.get("cycles", ()))
    completed = [item for item in cycles if item.get("complete")]
    issues = list(report.get("quality_issues", ()))
    verified = [
        record
        for record in (literature_result or {}).get("records", ())
        if record.get("doi_verified") and record.get("doi")
    ]
    direct = [record for record in verified if record.get("match_level") == "direct"]
    references = direct or verified

    def metric(item, *names):
        for name in names:
            value = item.get(name)
            if value is not None:
                try:
                    return float(value)
                except (TypeError, ValueError):
                    return None
        return None

    lines = ["数据质量与范围"]
    lines.append("有效完整循环：{} 圈；未完成或未配对循环：{} 圈。".format(len(completed), len(cycles) - len(completed)))
    if report.get("duration_h") is not None:
        lines.append("测试时长：{:.3g} h；电压范围：{} V。".format(
            float(report["duration_h"]),
            "—" if not report.get("voltage_range_V") else "{:.3f}–{:.3f}".format(*report["voltage_range_V"]),
        ))
    if issues:
        lines.append("数据提醒：{}".format("；".join(str(item.get("message", "")) for item in issues[:4])))
    else:
        lines.append("数据提醒：未发现当前规则能够识别的阻断问题；这不替代对原始曲线和设备记录的人工抽查。")

    lines.extend(["", "关键指标全景"])
    if not completed:
        lines.append("没有完整充放电循环，容量保持、效率趋势、电压趋势和能量指标暂不成立。")
    else:
        first, last = completed[0], completed[-1]
        discharge = [metric(item, "discharge_specific_capacity_mAh_g", "specific_discharge_capacity_mAh_g") for item in completed]
        charge = [metric(item, "charge_specific_capacity_mAh_g", "specific_charge_capacity_mAh_g") for item in completed]
        ce = [metric(item, "coulombic_efficiency") for item in completed]
        avg_charge = [metric(item, "average_charge_voltage_V") for item in completed]
        avg_discharge = [metric(item, "average_discharge_voltage_V") for item in completed]
        gaps = [
            metric(item, "voltage_gap_V")
            if metric(item, "voltage_gap_V") is not None
            else (
                metric(item, "average_charge_voltage_V") - metric(item, "average_discharge_voltage_V")
                if metric(item, "average_charge_voltage_V") is not None and metric(item, "average_discharge_voltage_V") is not None
                else None
            )
            for item in completed
        ]
        charge_plateau = [metric(item, "charge_plateau_voltage_V") for item in completed]
        discharge_plateau = [metric(item, "discharge_plateau_voltage_V") for item in completed]
        specific_discharge_energy = [
            capacity * voltage if capacity is not None and voltage is not None else None
            for capacity, voltage in zip(discharge, avg_discharge)
        ]
        specific_charge_energy = [
            capacity * voltage if capacity is not None and voltage is not None else None
            for capacity, voltage in zip(charge, avg_charge)
        ]
        energy_efficiency = [
            out_energy / in_energy if out_energy is not None and in_energy not in (None, 0) else None
            for out_energy, in_energy in zip(specific_discharge_energy, specific_charge_energy)
        ]
        retention = metric(last, "capacity_retention")

        if discharge[0] is not None and discharge[-1] is not None:
            lines.append("放电比容量：首个 {:.1f}，末个 {:.1f} mAh/g；变化 {:+.1f} mAh/g；容量保持率 {}。".format(
                discharge[0], discharge[-1], discharge[-1] - discharge[0], _percent(retention)
            ))
        if charge[0] is not None and charge[-1] is not None:
            lines.append("充电比容量：首个 {:.1f}，末个 {:.1f} mAh/g。".format(charge[0], charge[-1]))
        valid_ce = [value for value in ce if value is not None]
        if valid_ce:
            lines.append("库仑效率：首个 {:.2%}，末个 {:.2%}，平均 {:.2%}，范围 {:.2%}–{:.2%}。".format(
                valid_ce[0], valid_ce[-1], sum(valid_ce) / len(valid_ce), min(valid_ce), max(valid_ce)
            ))
        valid_discharge_v = [value for value in avg_discharge if value is not None]
        valid_charge_v = [value for value in avg_charge if value is not None]
        if valid_discharge_v:
            lines.append("平均放电电压：首个 {:.3f}，末个 {:.3f} V；变化 {:+.3f} V。".format(
                valid_discharge_v[0], valid_discharge_v[-1], valid_discharge_v[-1] - valid_discharge_v[0]
            ))
        if valid_charge_v:
            lines.append("平均充电电压：首个 {:.3f}，末个 {:.3f} V；变化 {:+.3f} V。".format(
                valid_charge_v[0], valid_charge_v[-1], valid_charge_v[-1] - valid_charge_v[0]
            ))
        valid_gaps = [value for value in gaps if value is not None]
        if valid_gaps:
            lines.append("平均充放电电压差：首个 {:.3f}，末个 {:.3f} V；变化 {:+.3f} V，可用于描述极化趋势但不能单独归因。".format(
                valid_gaps[0], valid_gaps[-1], valid_gaps[-1] - valid_gaps[0]
            ))
        valid_discharge_plateau = [value for value in discharge_plateau if value is not None]
        valid_charge_plateau = [value for value in charge_plateau if value is not None]
        if valid_discharge_plateau:
            lines.append("主放电平台：首个 {:.3f}，末个 {:.3f} V；漂移 {:+.3f} V。".format(
                valid_discharge_plateau[0], valid_discharge_plateau[-1], valid_discharge_plateau[-1] - valid_discharge_plateau[0]
            ))
        else:
            lines.append("主放电平台：当前数据未提供可计算的平台容量分布。")
        if valid_charge_plateau:
            lines.append("主充电平台：首个 {:.3f}，末个 {:.3f} V；漂移 {:+.3f} V。".format(
                valid_charge_plateau[0], valid_charge_plateau[-1], valid_charge_plateau[-1] - valid_charge_plateau[0]
            ))
        else:
            lines.append("主充电平台：当前数据未提供可计算的平台容量分布。")
        valid_specific_energy = [value for value in specific_discharge_energy if value is not None]
        if valid_specific_energy:
            lines.append("按文件比容量口径估算的放电比能量：首个 {:.1f}，末个 {:.1f} Wh/kg；变化 {:+.1f} Wh/kg。依据：比容量×容量加权平均放电电压。".format(
                valid_specific_energy[0], valid_specific_energy[-1], valid_specific_energy[-1] - valid_specific_energy[0]
            ))
            lines.append("能量口径限制：该值沿用文件中的质量分母，不能据此当作整电池能量密度；体积能量密度还需要电极或电芯体积。")
        valid_energy_efficiency = [value for value in energy_efficiency if value is not None]
        if valid_energy_efficiency:
            lines.append("近似能量效率：首个 {:.2%}，末个 {:.2%}。依据：放电比能量/充电比能量。".format(
                valid_energy_efficiency[0], valid_energy_efficiency[-1]
            ))

        lines.extend(["", "趋势与异常"])
        if len(completed) < 2:
            lines.append("只有一个完整循环，只能描述该圈指标，不能判断长期变化率或稳定性。")
        else:
            cycle_span = max(1, int(last.get("cycle", len(completed))) - int(first.get("cycle", 1)))
            if discharge[0] is not None and discharge[-1] is not None:
                slope = (discharge[-1] - discharge[0]) / cycle_span
                rises = sum(1 for left, right in zip(discharge, discharge[1:]) if left is not None and right is not None and right > left)
                lines.append("放电容量平均变化率：{:+.2f} mAh/g/圈；相邻循环中出现 {} 次容量回升，需结合化成、波动或数据分段核对。".format(slope, rises))
            if valid_ce:
                lines.append("效率稳定性：极差 {:.2%}；低效率或明显波动既可能来自不可逆反应，也可能来自循环划分、截止条件或接触异常。".format(max(valid_ce) - min(valid_ce)))
            if len(valid_gaps) >= 2:
                tendency = "增大" if valid_gaps[-1] > valid_gaps[0] else "未增大"
                lines.append("极化表征量{}：平均电压差由 {:.3f} 变为 {:.3f} V。".format(tendency, valid_gaps[0], valid_gaps[-1]))

        lines.extend(["", "数据支持的判断"])
        lines.append("可以直接支持：容量、库仑效率、保持率、平均电压、平台位置、极化表征量及文件质量口径下比能量的数值与循环趋势。")
        lines.append("不能直接支持：具体界面产物、电荷转移电阻、离子扩散系数、活化能、结构相变归属或唯一衰减机理。")
        lines.append("结论强度：单个电池用于发现趋势和提出假设；重复性与批次稳定性需要至少3个同条件独立电池。")

        lines.extend(["", "候选解释与判别依据"])
        capacity_drop = discharge[0] is not None and discharge[-1] is not None and discharge[-1] < discharge[0] * 0.95
        gap_growth = len(valid_gaps) >= 2 and valid_gaps[-1] - valid_gaps[0] > 0.05
        low_ce = bool(valid_ce) and (sum(valid_ce) / len(valid_ce) < 0.98 or min(valid_ce) < 0.95)
        if capacity_drop and gap_growth:
            lines.append("候选解释A：动力学、界面接触或传输受限加剧。支持依据：容量下降同时平均电压差增大；缺失证据：分阶段EIS和压力记录。判别实验：固定其余条件，在首圈、稳定期和衰减后测EIS；若阻抗分量与电压差同步增长则支持，若不增长则削弱该解释。")
        elif capacity_drop:
            lines.append("候选解释A：活性物质利用率下降、反应库存损失、接触退化或结构变化均可能造成容量衰减。支持依据：容量下降；缺失证据：阻抗、结构和界面化学。判别实验：同一电池分阶段EIS并对循环前后样品做结构/界面表征，用不同证据组合排除替代解释。")
        else:
            lines.append("候选解释A：当前区间未见超过5%的容量下降，但循环长度仍不足以证明长期稳定。判别实验：延长循环并设置同条件平行电池，观察保持率和离散度是否维持。")
        if low_ce:
            lines.append("候选解释B：持续副反应、漏电/微短路或测试分段问题可能导致效率偏低。支持依据：本次CE水平或波动；缺失证据：空白/对照电池、原始电流与截止日志。判别实验：复核循环边界并设置电解质/电极对照；若对照中同样偏低则优先排查测试或共性界面问题。")
        else:
            lines.append("候选解释B：库仑效率未触发当前低效率阈值，但高CE不能排除缓慢副反应、接触损失或可逆容量逐步减少。")

    if references:
        rendered = ["{}（DOI: {}）".format(str(record.get("title") or "已核验文献").strip(), record["doi"]) for record in references[:3]]
        comparison = "直接可比" if direct else "仅背景相关"
        lines.append("参考文献：{}；当前属于{}证据，性能对比仍需对齐倍率、温度、压力、载量、循环圈数和质量口径。".format("；".join(rendered), comparison))
    else:
        lines.append("参考文献：本次确定性摘要未获得已核验且条件匹配的原文知识；机理与性能水平需在原文学习和人工批准后补入最终指导。")

    profile_text = "" if research_profile is None else " ".join(str(value) for value in research_profile.to_dict().values()).casefold()
    solid_state = any(key in profile_text for key in ("solid", "固态", "halide", "卤化物"))
    lines.extend(["", "下一轮实验决策"])
    lines.append("1. 重复性：制作至少3个同批、同载量、同电流、同温度电池；保留单电池散点，并比较均值、标准差和失效样本。")
    if solid_state:
        lines.append("2. 单变量优先级：先固定正极配比和载量，只改变堆叠压力；记录面容量、平均电压差和分阶段EIS。支持结果：压力改善伴随极化与阻抗同步下降；反证结果：阻抗和容量对压力不敏感。")
        lines.append("3. 界面判别：选取未循环、首圈后和明显衰减后样品做XPS/Raman及截面SEM。支持结果：新化学态或接触裂隙与衰减同步出现；反证结果：界面化学与形貌基本不变。")
    else:
        lines.append("2. 动力学判别：在首圈、稳定期和衰减后测EIS，保持温度、SOC和静置时间一致。支持结果：阻抗增长与极化、容量衰减同步；反证结果：阻抗基本不变。")
        lines.append("3. 结构/界面判别：对循环前后样品做体系适用的XRD、Raman、XPS和形貌表征，并设置未循环对照。")
    lines.append("4. 决策规则：一次只改变一个关键变量；每轮先写明支持结果与反证结果，再根据结果决定下一轮，而不是无差别增加测试。")
    return "\n".join(lines) + "\n"


def render_concise_markdown(
    payload: dict,
    material: Optional[str],
    cell_configuration: Optional[str],
    rate: Optional[str],
    temperature: Optional[str],
    research_profile=None,
    literature_result=None,
) -> str:
    report = payload["report"]
    cycles = report.get("cycles", [])
    completed = [item for item in cycles if item.get("complete")]
    lines = ["# 电化学关键参数报告", "", "## 实验条件", ""]
    if research_profile is not None:
        profile_fields = [
            ("电池体系", research_profile.battery_system),
            ("活性物质", research_profile.active_material),
            ("电池类型/对电极", research_profile.cell_description),
            ("测试电流/倍率", research_profile.test_current),
            ("测试温度", research_profile.temperature),
            ("质量归一化口径", research_profile.normalization_basis),
        ]
        lines.extend("- {}：{}".format(label, value or "待填") for label, value in profile_fields)
    else:
        lines.extend(
            [
                "- 材料/活性物质：{}".format(material or "待填"),
                "- 电池结构：{}".format(cell_configuration or "待填"),
                "- 测试电流/倍率：{}".format(rate or "待填"),
                "- 测试温度：{}".format(temperature or "待填"),
            ]
        )

    lines.extend(["", "## 关键参数", ""])
    initial = report.get("initial_discharge_capacity_mAh_g")
    if initial is not None:
        lines.append("- 初始放电比容量：**{:.1f} mAh/g**".format(initial))
    lines.extend(
        [
            "- 完整充放电循环：**{} 圈**".format(len(completed)),
            "- 未完成循环：**{} 圈**".format(len(cycles) - len(completed)),
            "",
            "| 循环 | 充电比容量 (mAh/g) | 放电比容量 (mAh/g) | 库仑效率 | 保持率 | 平均充/放电电压 (V) | 主充/放电平台 (V) |",
            "|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for item in cycles:
        lines.append(
            "| {cycle} | {charge} | {discharge} | {ce} | {retention} | {avg_c}/{avg_d} | {plat_c}/{plat_d} |".format(
                cycle=item["cycle"],
                charge=_number(item.get("charge_specific_capacity_mAh_g")),
                discharge=_number(item.get("discharge_specific_capacity_mAh_g")),
                ce=_percent(item.get("coulombic_efficiency")),
                retention=_percent(item.get("capacity_retention")),
                avg_c=_number(item.get("average_charge_voltage_V"), 3),
                avg_d=_number(item.get("average_discharge_voltage_V"), 3),
                plat_c=_number(item.get("charge_plateau_voltage_V"), 3),
                plat_d=_number(item.get("discharge_plateau_voltage_V"), 3),
            )
        )

    lines.extend(["", "## 数据结论", ""])
    if completed:
        first, last = completed[0], completed[-1]
        efficiencies = [item["coulombic_efficiency"] for item in completed if item.get("coulombic_efficiency") is not None]
        lines.append(
            "- 完整循环放电比容量由 **{:.1f}** 降至 **{:.1f} mAh/g**，容量保持率为 **{:.2%}**。".format(
                first["discharge_specific_capacity_mAh_g"],
                last["discharge_specific_capacity_mAh_g"],
                last["capacity_retention"],
            )
        )
        if efficiencies:
            lines.append(
                "- 完整循环库仑效率范围为 **{:.2%}–{:.2%}**。".format(min(efficiencies), max(efficiencies))
            )
        if any(not item.get("complete") for item in cycles):
            lines.append("- 文件末尾循环未完成，未将其部分容量用于效率或保持率判断。")
    else:
        lines.append("- 未识别到可用于趋势判断的完整充放电循环。")

    issues = report.get("quality_issues", [])
    if issues:
        lines.extend(["", "## 质量提示", ""])
        for issue in issues:
            lines.append("- `{}`：{}".format(issue["code"], issue["message"]))

    if research_profile is None:
        from .literature import ResearchProfile

        research_profile = ResearchProfile(
            active_material=material or "",
            cell_type=cell_configuration or "",
            test_current=rate or "",
            temperature=temperature or "",
        )
    lines.extend(_render_literature_and_value(payload, research_profile, literature_result))
    lines.extend(render_scientific_guidance(payload, research_profile, literature_result))
    standard = payload.get("scientific_standard", scientific_standard_identity())
    lines.extend(
        [
            "",
            "## 科学计算口径与统计边界",
            "",
            "- 核心指标标准版本：**{}**；标准SHA-256：`{}`。".format(
                standard["version"], standard["sha256"]
            ),
            "- 本报告来自单个电池，只能作为**探索性结果**，不能证明材料重复性、批次稳定性或总体性能。",
            "- 重复性结论至少需要3个同条件独立电池，并同时展示原始散点、均值、样本标准差和95%置信区间。",
            "- 统计异常只作提示，不自动删除；任何人工排除必须记录事前规则和理由。",
        ]
    )
    lines.extend(
        [
            "",
            "## 平台计算口径",
            "",
            "平均电压按容量增量对电压加权；主平台为 0.05 V 电压窗口内承载容量增量最多的区间中心。该结果是可复现的数值描述，不等同于机理归属。",
        ]
    )
    return "\n".join(lines) + "\n"


def create_scientific_bundle(
    input_path,
    output_dir,
    material=None,
    cell_configuration=None,
    rate=None,
    temperature=None,
    research_profile=None,
    search_literature=False,
    max_literature=50,
    literature_knowledge_path=None,
    literature_markdown_path=None,
    origin_plot_mode="both",
):
    from .land_curve import (
        _decode,
        _find_table,
        _time_factor_to_hours,
        analyze_land_capacity_curve,
    )
    from .literature import ResearchProfile, search_crossref

    source = Path(input_path).resolve()
    target = Path(output_dir).resolve()
    target.mkdir(parents=True, exist_ok=True)
    payload = analyze_land_capacity_curve(source)
    payload["scientific_standard"] = scientific_standard_identity()
    if research_profile is None:
        research_profile = ResearchProfile(
            active_material=material or "",
            cell_type=cell_configuration or "",
            test_current=rate or "",
            temperature=temperature or "",
        )
    payload["experiment_context"] = research_profile.to_dict()

    literature_result = None
    if search_literature:
        try:
            literature_result = search_crossref(research_profile, max_results=max_literature)
        except Exception as error:
            literature_result = {
                "source": "Crossref REST API",
                "searched_at": None,
                "query": research_profile.to_dict(),
                "candidate_count": 0,
                "verified_count": 0,
                "directly_comparable_count": 0,
                "records": [],
                "error": "{}: {}".format(type(error).__name__, error),
                "limitations": ["联网检索失败；未生成文献水平结论。"],
            }
        payload["literature_search"] = literature_result

    if literature_knowledge_path is not None:
        from .literature_knowledge import LiteratureKnowledgeStore

        knowledge_store = LiteratureKnowledgeStore(literature_knowledge_path)
        payload["literature_knowledge"] = knowledge_store.summary(
            research_profile, update_result=None
        )
        payload["literature_knowledge"]["write_policy"] = "metadata_and_abstract_discovery_results_are_not_persisted"

    if literature_markdown_path is not None:
        from .markdown_knowledge import MarkdownLiteratureKnowledgeStore

        markdown_store = MarkdownLiteratureKnowledgeStore(literature_markdown_path)
        payload["editable_literature_knowledge"] = markdown_store.summary(
            research_profile, update_result=None
        )
        payload["editable_literature_knowledge"]["write_policy"] = "fulltext_llm_learning_only"

    report_path = target / "关键参数报告.md"
    report_path.write_text(
        render_concise_markdown(
            payload,
            material,
            cell_configuration,
            rate,
            temperature,
            research_profile=research_profile,
            literature_result=literature_result,
        ),
        encoding="utf-8",
    )
    conclusion_path = target / "关键结论.txt"
    conclusion_path.write_text(
        render_readable_summary(payload, research_profile, literature_result),
        encoding="utf-8",
    )

    summary_path = target / "关键参数.csv"
    fields = [
        "cycle",
        "charge_specific_capacity_mAh_g",
        "discharge_specific_capacity_mAh_g",
        "coulombic_efficiency_percent",
        "capacity_retention_percent",
        "average_charge_voltage_V",
        "average_discharge_voltage_V",
        "charge_plateau_voltage_V",
        "discharge_plateau_voltage_V",
        "complete",
    ]
    with summary_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for item in payload["report"]["cycles"]:
            writer.writerow(
                {
                    "cycle": item["cycle"],
                    "charge_specific_capacity_mAh_g": item["charge_specific_capacity_mAh_g"],
                    "discharge_specific_capacity_mAh_g": item["discharge_specific_capacity_mAh_g"],
                    "coulombic_efficiency_percent": None if item["coulombic_efficiency"] is None else item["coulombic_efficiency"] * 100,
                    "capacity_retention_percent": None if item["capacity_retention"] is None else item["capacity_retention"] * 100,
                    "average_charge_voltage_V": item.get("average_charge_voltage_V"),
                    "average_discharge_voltage_V": item.get("average_discharge_voltage_V"),
                    "charge_plateau_voltage_V": item.get("charge_plateau_voltage_V"),
                    "discharge_plateau_voltage_V": item.get("discharge_plateau_voltage_V"),
                    "complete": item["complete"],
                }
            )

    text, _ = _decode(source)
    _, rows, header_index, mapping = _find_table(text)
    factor = _time_factor_to_hours(rows[header_index][mapping["time"]])
    points = []
    for row in rows[header_index + 1 :]:
        if row and any(cell.strip() for cell in row):
            points.append((float(row[mapping["time"]]) * factor, float(row[mapping["capacity"]]), float(row[mapping["voltage"]])))
    segments = []
    start = 0
    for index, (left, right) in enumerate(zip(points, points[1:])):
        if left[1] > 1.0 and right[1] <= max(0.05, left[1] * 0.1):
            segments.append(points[start:index + 1])
            start = index + 1
    segments.append(points[start:])

    complete_cycles = [item for item in payload["report"]["cycles"] if item["complete"]]
    selected = select_representative_cycles(complete_cycles, limit=8)
    curves_path = target / "Origin_充放电曲线数据.csv"
    with curves_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["cycle", "direction", "specific_capacity_mAh_g", "voltage_V"])
        for item in selected:
            for direction, segment_number in (("charge", item["charge_segment"]), ("discharge", item["discharge_segment"])):
                for _, capacity, voltage in segments[segment_number - 1]:
                    writer.writerow([item["cycle"], direction, capacity, voltage])

    standard_path = target / "科学计算标准.json"
    standard_path.write_text(
        json.dumps(
            {
                "identity": scientific_standard_identity(),
                "manifest": scientific_standard_manifest(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    json_path = target / "完整分析.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    job_path = target / "origin_job.json"
    status_path = target / "origin_status.json"
    job = {
        "curves_csv": str(curves_path),
        "summary_csv": str(summary_path),
        "project_path": str(target / "电化学分析.opju"),
        "curve_png": str(target / "充放电曲线.png"),
        "cycling_png": str(target / "循环性能.png"),
        "status_path": str(status_path),
        "plot_mode": origin_plot_mode,
        "selected_cycles": [item["cycle"] for item in selected],
        "representative_cycle_limit": 8,
    }
    job_path.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
    result_paths = {
        "report": report_path,
        "conclusion": conclusion_path,
        "summary": summary_path,
        "curves": curves_path,
        "json": json_path,
        "standard": standard_path,
        "job": job_path,
        "status": status_path,
    }
    if literature_markdown_path is not None:
        result_paths["knowledge_markdown"] = Path(literature_markdown_path).resolve()
    if literature_result is not None:
        literature_path = target / "文献证据.json"
        literature_path.write_text(json.dumps(literature_result, ensure_ascii=False, indent=2), encoding="utf-8")
        comparison_path = target / "文献比较.csv"
        comparison_fields = [
            "match_level", "year", "journal", "title", "doi", "citation_count",
            "specific_capacity_mAh_g", "coulombic_efficiency_percent",
            "capacity_retention_percent", "cycle_count",
        ]
        with comparison_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=comparison_fields)
            writer.writeheader()
            for record in literature_result.get("records", []):
                row = {name: record.get(name) for name in comparison_fields}
                row.update(record.get("metrics", {}))
                writer.writerow({name: row.get(name) for name in comparison_fields})
        result_paths["literature"] = literature_path
        result_paths["comparison"] = comparison_path
    return result_paths
