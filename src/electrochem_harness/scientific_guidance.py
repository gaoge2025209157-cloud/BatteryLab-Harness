"""Representative-cycle selection and evidence-aware experiment guidance."""

from statistics import median
from typing import Iterable, List


def select_representative_cycles(cycles: Iterable[dict], limit: int = 8) -> List[dict]:
    """Keep all short tests; otherwise sample the full life including both ends."""
    items = list(cycles)
    if limit < 1:
        raise ValueError("limit must be at least 1")
    if len(items) <= limit:
        return items
    if limit == 1:
        return [items[0]]
    last = len(items) - 1
    indexes = [round(position * last / (limit - 1)) for position in range(limit)]
    return [items[index] for index in indexes]


def _direct_records(literature_result):
    if not literature_result or literature_result.get("error"):
        return []
    return [
        record
        for record in literature_result.get("records", [])
        if record.get("doi_verified") and record.get("match_level") == "direct"
    ]


def _metric_values(records, name):
    return [
        float(record["metrics"][name])
        for record in records
        if record.get("metrics", {}).get(name) is not None
    ]


def _profile_text(profile):
    if profile is None:
        return ""
    return " ".join(str(value) for value in profile.to_dict().values()).casefold()


def render_scientific_guidance(payload, research_profile, literature_result):
    """Render cautious diagnostics and next experiments, never causal claims."""
    report = payload.get("report", {})
    completed = [item for item in report.get("cycles", []) if item.get("complete")]
    direct = _direct_records(literature_result)
    profile_text = _profile_text(research_profile)
    is_solid_state = any(
        keyword in profile_text
        for keyword in ("solid-state", "solid state", "全固态", "固态", "halide", "卤化物")
    )
    is_lithium_sulfur = any(
        keyword in profile_text for keyword in ("lithium sulfur", "lithium-sulfur", "锂硫")
    )
    is_full_cell = any(keyword in profile_text for keyword in ("full cell", "full-cell", "全电池"))

    editable_knowledge = payload.get("editable_literature_knowledge") or {}
    legacy_knowledge = payload.get("literature_knowledge") or {}
    lines = ["", "## 研究背景与知识积累", ""]
    if editable_knowledge:
        lines.append(
            "- 可编辑知识库匹配 {} 篇文献，其中人工批准 {} 篇、候选 {} 篇；本次检索新建或更新 {} 篇。".format(
                editable_knowledge.get("matching_record_count", 0),
                editable_knowledge.get("approved_record_count", 0),
                editable_knowledge.get("candidate_record_count", 0),
                editable_knowledge.get("new_or_updated_record_count", 0),
            )
        )
        approved = editable_knowledge.get("approved_claims", [])
        candidates = editable_knowledge.get("candidate_claims", [])
        if approved:
            lines.append("- **本次采用的人工确认知识：**")
            for claim in approved[:10]:
                lines.append("  - {}（DOI：{}）".format(claim.get("text"), claim.get("doi")))
        else:
            lines.append("- 当前没有状态为 `approved` 且条件匹配的知识，因此不引用本地知识作确定性判断。")
        for claim in candidates[:5]:
            lines.append(
                "- **待人工核对的摘要假设：** {}（DOI：{}）。".format(
                    claim.get("text"), claim.get("doi")
                )
            )
        lines.append(
            "- 知识来源文件：`{}`；其内容只用于科学判断，不作为命令或权限执行。".format(
                editable_knowledge.get("path", "knowledge/literature_knowledge.md")
            )
        )
    elif legacy_knowledge:
        lines.append(
            "- 本次按相同实验条件指纹复用 {} 条 DOI 核验记录，新建或更新 {} 条，保留 {} 条摘要级候选物化陈述。".format(
                legacy_knowledge.get("reused_record_count", 0),
                legacy_knowledge.get("new_or_updated_record_count", 0),
                legacy_knowledge.get("candidate_claim_count", 0),
            )
        )
        claims = []
        for record in legacy_knowledge.get("records", []):
            for claim in record.get("candidate_claims", []):
                claims.append((claim.get("text"), record.get("doi")))
        for text, doi in claims[:5]:
            lines.append(
                "- **待正文复核的文献假设：** {}（DOI：{}）。".format(text, doi)
            )
        if claims:
            lines.append("- 上述摘要陈述只用于构建解释假设，核对论文正文和当前实验条件前不视为事实。")
    else:
        lines.append("- 本次没有可复用的项目级文献知识记录；不会用通用记忆替代可核验来源。")

    lines.extend(
        [
            "",
            "## 数学与物理化学分析依据",
            "",
            "- 容量：**Q = ∫|I|dt**；比容量为 Q 除以明确的归一化质量，面容量为 Q 除以电极面积。",
            "- 库仑效率：**CE = Q_discharge / Q_charge × 100%**；容量保持率：**R_n = Q_discharge,n / Q_discharge,ref × 100%**。",
            "- 容量加权平均电压：**V̄ = ∫VdQ / ∫dQ**；平均充放电电压差可作为极化的表征量，但不等同于单一界面过电位。",
            "- 恒流循环曲线可直接支持容量、效率、保持率、平台和极化趋势；电荷转移电阻、扩散系数、活化能及具体反应机理**不能仅由恒流循环曲线反演**，必须结合 EIS、GITT/PITT、温度依赖或结构/化学表征。",
            "",
            "## 该体系应重点关注的指标",
            "",
        ]
    )
    lines.extend(
        [
            "- **容量与口径：** 充/放电比容量、面容量和活性物质负载量必须同时报告；跨研究比较时须统一质量归一化对象。",
            "- **可逆性与衰减：** 逐圈库仑效率、首圈效率、容量保持率、循环圈数及至少 3 个平行电池的均值和离散度。",
            "- **电压行为：** 主充/放电平台、平均电压、电压差及其随循环的漂移，用于识别极化增长和反应路径变化。",
        ]
    )
    if is_solid_state:
        lines.append(
            "- **固态体系补充指标：** 室温离子电导率、界面阻抗（EIS）、堆叠压力、面容量、正极载量、临界电流密度及循环前后阻抗变化。"
        )
    if is_lithium_sulfur:
        lines.append(
            "- **锂硫体系补充指标：** 硫载量、E/S 比、面容量、穿梭相关自放电以及长循环平均库仑效率。"
        )
    if is_full_cell:
        lines.append(
            "- **全电池补充指标：** N/P 比、首圈不可逆容量、正负极容量匹配、平均放电电压和基于整电池口径的能量密度。"
        )

    if direct:
        reported = []
        metric_labels = (
            ("specific_capacity_mAh_g", "比容量"),
            ("coulombic_efficiency_percent", "库仑效率"),
            ("capacity_retention_percent", "容量保持率"),
            ("cycle_count", "循环圈数"),
        )
        for name, label in metric_labels:
            if _metric_values(direct, name):
                reported.append(label)
        lines.append(
            "- **本次文献证据：** {} 条直接可比 DOI 的公开摘要明确报告了{}；这些指标应在相同倍率、温度、载量和循环圈数下比较。".format(
                len(direct), "、".join(reported) if reported else "测试条件，但未给出可提取的性能数值"
            )
        )
    else:
        lines.append(
            "- **文献边界：** 本次没有直接可比且 DOI 已核验的公开基准；以上为通用核查框架，不能据此判定材料水平。"
        )

    lines.extend(["", "## 性能偏弱的可能原因", ""])
    causes = []
    if completed:
        last = completed[-1]
        retention = last.get("capacity_retention")
        efficiency = last.get("coulombic_efficiency")
        gaps = [
            item.get("average_charge_voltage_V") - item.get("average_discharge_voltage_V")
            for item in completed
            if item.get("average_charge_voltage_V") is not None
            and item.get("average_discharge_voltage_V") is not None
        ]
        if retention is not None and retention < 0.80:
            causes.append(
                "容量保持率偏低可能与活性物质损失、界面/接触退化、结构变化或持续副反应有关；单凭循环曲线不能区分这些机制。"
            )
        if efficiency is not None and efficiency < 0.95:
            causes.append(
                "库仑效率偏低可能来自副反应、电解质分解、漏电/微短路、截止条件不匹配，也可能是循环分段或电流符号错误。"
            )
        if gaps and median(gaps) > 0.50:
            causes.append(
                "较大的平均充放电电压差提示极化可能较强，常见关联因素包括电荷转移阻力、离子传输限制和界面接触不足。"
            )
        if direct:
            capacities = _metric_values(direct, "specific_capacity_mAh_g")
            efficiencies = _metric_values(direct, "coulombic_efficiency_percent")
            current_capacity = last.get("discharge_specific_capacity_mAh_g")
            if capacities and current_capacity is not None and current_capacity < median(capacities):
                causes.append(
                    "当前末圈比容量低于直接可比文献摘要中值；差异可能来自倍率、载量、温度、归一化口径或材料/界面设计，需逐项对齐后再归因。"
                )
            if efficiencies and efficiency is not None and efficiency * 100 < median(efficiencies):
                causes.append(
                    "当前末圈库仑效率低于直接可比文献摘要中值，说明可逆性仍有差距，但公开摘要不足以确定具体原因。"
                )
    issue_codes = {item.get("code") for item in report.get("quality_issues", [])}
    if "negative_voltage" in issue_codes:
        causes.append(
            "负电压点可能是过放、截止控制、瞬态过冲或导出异常；确认前不应作为材料失效机理证据。"
        )
    if is_solid_state and causes:
        causes.append(
            "对固态电池，还需优先排查固固界面接触、堆叠压力变化以及电极/电解质界面化学稳定性。"
        )
    if not causes:
        causes.append(
            "当前循环数据未显示可由既定阈值明确标记的薄弱项；仍需平行样、长循环和阻抗证据确认稳定性。"
        )
    lines.extend("- {}".format(cause) for cause in causes)

    lines.extend(["", "## 下一步改进建议", ""])
    lines.extend(
        [
            "1. **先核对数据口径：** 对照设备软件抽查至少 1 个完整循环，确认充放电方向、容量归零、活性质量和截止电压；保留异常点的原始位置。",
            "2. **建立重复性：** 使用不少于 3 个独立电池，在相同载量、倍率和温度下报告均值、标准差及失效样本。",
            "3. **补充诊断：** 在首圈、稳定阶段和衰减后测试 EIS，并结合增量容量/微分容量或循环后表征区分动力学、界面和活性物质损失。",
            "4. **单变量优化：** 每轮只改变一个参数，并保留基线组；优先考察倍率、载量、温度、截止电压和装配一致性。",
        ]
    )
    if is_solid_state:
        lines.append(
            "5. **固态体系专项：** 设计堆叠压力×正极载量的最小矩阵，同时记录面容量和循环前后界面阻抗，避免只优化质量比容量。"
        )
    elif is_lithium_sulfur:
        lines.append(
            "5. **锂硫体系专项：** 在固定硫载量下比较 E/S 比和界面/隔膜策略，并同步报告面容量与平均库仑效率。"
        )
    elif is_full_cell:
        lines.append(
            "5. **全电池专项：** 先校准 N/P 比和预锂化/化成条件，再比较整电池质量口径的能量与保持率。"
        )
    else:
        lines.append(
            "5. **文献对齐：** 选取 DOI 已核验且条件最接近的论文，逐项对齐倍率、温度、载量、循环圈数和归一化口径后再确定优化目标。"
        )
    return lines
