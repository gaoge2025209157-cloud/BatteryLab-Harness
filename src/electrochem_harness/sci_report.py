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
    """Render the decision-facing result in plain text.

    The detailed Markdown remains an auditable attachment.  This view is kept
    deliberately short so the GUI answers only four questions: what are the
    numbers, what do they mean, what can the data support, and what should be
    done next.  Every interpretation carries its basis and any usable DOI in
    the same paragraph instead of sending the reader to a separate appendix.
    """

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

    lines = ["关键指标"]
    lines.append("完整循环：{} 圈；未完成循环：{} 圈".format(len(completed), len(cycles) - len(completed)))
    if completed:
        first, last = completed[0], completed[-1]
        first_capacity = first.get("discharge_specific_capacity_mAh_g")
        last_capacity = last.get("discharge_specific_capacity_mAh_g")
        retention = last.get("capacity_retention")
        efficiencies = [
            item.get("coulombic_efficiency")
            for item in completed
            if item.get("coulombic_efficiency") is not None
        ]
        lines.append(
            "放电比容量：{} → {} mAh/g；容量保持率：{}".format(
                _number(first_capacity), _number(last_capacity), _percent(retention)
            )
        )
        if efficiencies:
            lines.append("库仑效率范围：{:.2%}–{:.2%}".format(min(efficiencies), max(efficiencies)))
        voltage_gaps = [
            item.get("average_charge_voltage_V") - item.get("average_discharge_voltage_V")
            for item in completed
            if item.get("average_charge_voltage_V") is not None
            and item.get("average_discharge_voltage_V") is not None
        ]
        if voltage_gaps:
            lines.append("末个完整循环平均充放电电压差：{:.3f} V".format(voltage_gaps[-1]))

        lines.extend(["", "简要结论与科学依据"])
        if first_capacity is not None and last_capacity is not None:
            direction = "下降" if last_capacity < first_capacity else "未下降"
            lines.append(
                "在当前测试区间内，放电比容量{}。依据：首末完整循环由 {:.1f} 变为 {:.1f} mAh/g，保持率为 {}。".format(
                    direction, first_capacity, last_capacity, _percent(retention)
                )
            )
        if efficiencies:
            lines.append(
                "充放电可逆性以库仑效率范围描述。依据：CE = 放电容量/充电容量，本次为 {:.2%}–{:.2%}；该指标不能单独确定副反应机理。".format(
                    min(efficiencies), max(efficiencies)
                )
            )
    else:
        lines.extend(["", "简要结论与科学依据", "当前不能评价循环趋势。依据：没有识别到完整充放电循环。"])

    if references:
        rendered = []
        for record in references[:3]:
            title = str(record.get("title") or "已核验文献").strip()
            rendered.append("{}（DOI: {}）".format(title, record["doi"]))
        comparison = "直接可比" if direct else "仅背景相关"
        lines.append("参考文献：{}；当前属于{}证据，比较时仍需对齐倍率、温度、载量和质量口径。".format("；".join(rendered), comparison))
    else:
        lines.append("参考文献：本次没有获得DOI已核验且条件匹配的文献，因此不作领先、落后或机理定级。")

    lines.extend(["", "实验数据能说明什么"])
    if completed:
        lines.append("可以说明：当前文件中的容量、效率、保持率、平均电压及其随循环的变化。")
        lines.append("不能说明：仅凭充放电曲线不能确定界面成分、电荷转移阻抗、扩散系数或具体衰减机理。")
    else:
        lines.append("可以说明：数据格式或循环完整性存在需要先处理的问题。")
        lines.append("不能说明：没有完整循环时不能评价容量保持和可逆性。")
    if issues:
        lines.append("质量提醒：{}".format("；".join(str(item.get("message", "")) for item in issues[:2])))

    profile_text = "" if research_profile is None else " ".join(
        str(value) for value in research_profile.to_dict().values()
    ).casefold()
    solid_state = any(key in profile_text for key in ("solid", "固态", "halide", "卤化物"))
    lines.extend(["", "下一步怎么做"])
    lines.append("1. 对照设备软件抽查一个完整循环，并补足至少3个同条件平行电池。")
    if solid_state:
        lines.append("2. 在首圈、稳定期和衰减后测试EIS，同时记录温度、压力、载量和面容量。")
        lines.append("3. 用循环前后XRD、Raman、XPS及截面SEM区分主体结构、界面化学和接触退化。")
    else:
        lines.append("2. 在首圈、稳定期和衰减后测试EIS，判断阻抗变化是否与容量衰减同步。")
        lines.append("3. 根据体系补充循环前后结构、成分和界面表征，并设置单变量对照组。")
    lines.append("4. 文献比较前统一倍率、温度、载量、循环圈数和质量归一化口径。")
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
        update_result = None
        if literature_result is not None and not literature_result.get("error"):
            update_result = knowledge_store.update_from_search(
                research_profile, literature_result
            )
        payload["literature_knowledge"] = knowledge_store.summary(
            research_profile, update_result=update_result
        )

    if literature_markdown_path is not None:
        from .markdown_knowledge import MarkdownLiteratureKnowledgeStore

        markdown_store = MarkdownLiteratureKnowledgeStore(literature_markdown_path)
        markdown_update = None
        if literature_result is not None and not literature_result.get("error"):
            markdown_update = markdown_store.update_from_search(
                research_profile, literature_result
            )
        payload["editable_literature_knowledge"] = markdown_store.summary(
            research_profile, update_result=markdown_update
        )

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
