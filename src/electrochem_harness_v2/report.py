"""Academic Chinese report generated from auditable electrochemical evidence."""
from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Mapping, Sequence
from urllib.parse import urlparse

from .comparison import compare_metric
from .models import ComparisonOutcome, KnowledgeClaim
from .research_direction import build_research_direction


def _text(value) -> str:
    return escape(str(value if value is not None else ""))


def _number(value, digits: int = 2, suffix: str = "") -> str:
    if value is None or value == "":
        return "待确认"
    try:
        return ("{:.%df}" % digits).format(float(value)) + suffix
    except (TypeError, ValueError):
        return _text(value) + suffix


def _safe_link(url) -> str:
    value = str(url or "").strip()
    parsed = urlparse(value)
    return escape(value, quote=True) if parsed.scheme == "https" and parsed.netloc else ""


def _links(urls) -> str:
    links = ["<a href='{}' target='_blank' rel='noopener noreferrer'>来源</a>".format(_safe_link(url)) for url in urls or [] if _safe_link(url)]
    return "；".join(links) or "未提供可访问来源"


def _list(items, empty: str = "暂无") -> str:
    rows = ["<li>{}</li>".format(_text(item)) for item in items or [] if str(item).strip()]
    return "<ul>{}</ul>".format("".join(rows) or "<li class='muted'>{}</li>".format(_text(empty)))


def _metric(label: str, value: str, unit: str, note: str) -> str:
    return "<article class='metric'><span>{}</span><b>{}</b><small>{}</small><p>{}</p></article>".format(
        _text(label), _text(value), _text(unit), _text(note)
    )


def _mapping_rows(values: Mapping) -> str:
    labels = {
        "temperature_C": "测试温度", "current_mA": "测试电流", "pressure_MPa": "堆叠压力",
        "voltage_window_V": "电压窗口", "mass_basis": "容量归一化口径",
    }
    rows = []
    for key, value in values.items():
        if value in (None, "", [], {}):
            continue
        label = labels.get(str(key), str(key))
        rendered = "、".join(map(str, value)) if isinstance(value, list) else str(value)
        rows.append("<tr><th>{}</th><td>{}</td></tr>".format(_text(label), _text(rendered)))
    return "".join(rows) or "<tr><th>实验条件</th><td>关键实验条件尚未完整记录。</td></tr>"


def _curated_knowledge_rows(review: Mapping, studies: Sequence[Mapping]) -> str:
    rows = []
    for item in review.get("knowledge_items") or []:
        if not isinstance(item, Mapping):
            continue
        rows.append("<article class='literature-item'><h3>{}</h3><p><b>为何纳入：</b>{}</p><dl>"
                    "<dt>研究问题</dt><dd>{}</dd><dt>测试与表征</dt><dd>{}</dd>"
                    "<dt>文献学习结果</dt><dd>{}</dd><dt>对本课题的借鉴</dt><dd>{}</dd>"
                    "<dt>来源</dt><dd>{}</dd></dl></article>".format(
                        _text(item.get("title") or "关键文献知识"),
                        _text(item.get("why_selected") or "与本课题的关键科学问题直接相关。"),
                        _text(item.get("question")),
                        _text("；".join(item.get("tests") or []) or "文献中未提取到可用测试信息"),
                        _text(item.get("finding")),
                        _text(item.get("how_to_borrow")),
                        _links(item.get("source_urls")),
                    ))
    for item in studies or []:
        if not isinstance(item, Mapping):
            continue
        rows.append("<article class='literature-item'><h3>{}</h3><dl>"
                    "<dt>研究问题</dt><dd>{}</dd><dt>测试与表征</dt><dd>{}</dd>"
                    "<dt>文献学习结果</dt><dd>{}</dd><dt>对本课题的借鉴</dt><dd>{}</dd>"
                    "<dt>来源</dt><dd>{}</dd></dl></article>".format(
                        _text(item.get("study") or "本地文献知识"),
                        _text(item.get("question")),
                        _text("；".join(item.get("tests") or []) or "文献中未提取到可用测试信息"),
                        _text(item.get("finding")),
                        _text(item.get("how_to_borrow")),
                        _links(item.get("source_urls")),
                    ))
    if not rows:
        return "<p class='muted'>本轮未形成可展示的 Codex 精选文献知识。</p>"
    return "".join(rows)


def _standards_rows(web: Mapping) -> str:
    rows = []
    for item in web.get("standards") or []:
        rows.append("<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
            _text(item.get("name") or item.get("standard")),
            _text(item.get("issuer")),
            _text(item.get("scope") or item.get("purpose")),
            _links([item.get("url")]),
        ))
    if not rows:
        return ""
    return ("<h3>检索到的标准与规范线索</h3><p class='muted'>下列内容用于界定测试与报告要求；除非核对官方正文中的明确阈值，否则不将其用作性能判据。</p>"
            "<table><thead><tr><th>标准/规范</th><th>发布机构</th><th>适用范围</th><th>来源</th></tr></thead><tbody>{}</tbody></table>".format("".join(rows)))


def _research_synthesis_html(synthesis: Mapping) -> str:
    question = str(synthesis.get("search_question") or "").strip()
    connection = str(synthesis.get("data_literature_connection") or "").strip()
    boundaries = synthesis.get("evidence_boundaries") or []
    if not question and not connection and not boundaries:
        return ""
    return ("<div class='callout'><b>Codex 的检索与学习判断</b>"
            "<p><b>核心问题：</b>{}</p><p><b>数据与文献的联系：</b>{}</p>{}</div>".format(
                _text(question or "本轮围绕课题关键词和确定性实验特征检索相关研究。"),
                _text(connection or "当前尚未形成可直接用于解释本体系的充分文献证据。"),
                "<p><b>证据边界：</b>{}</p>".format(_text("；".join(map(str, boundaries)))) if boundaries else "",
            ))


def _context_audit_html(manifest: Mapping) -> str:
    if not manifest:
        return "<p class='muted'>本轮未生成统一上下文清单。</p>"
    if manifest.get("status") == "unreadable":
        return "<p class='muted'>本轮上下文清单无法读取，模型依据需人工核查。</p>"
    counts = dict(manifest.get("knowledge_counts") or {})
    context_hash = str(manifest.get("context_hash") or "")
    excluded = list(manifest.get("excluded_sources") or [])
    warnings = list(manifest.get("warnings") or [])
    rows = [
        ("上下文哈希", context_hash[:20] + ("…" if len(context_hash) > 20 else "")),
        ("估算输入Token", manifest.get("input_tokens_estimated") or 0),
        ("已批准知识", counts.get("approved", 0)),
        ("待审核候选知识", counts.get("candidate", 0)),
        ("联网候选来源", counts.get("online_sources", 0)),
        ("被排除来源", len(excluded)),
    ]
    table = "".join("<tr><th>{}</th><td>{}</td></tr>".format(_text(label), _text(value)) for label, value in rows)
    notes = ""
    if warnings:
        notes = "<p class='muted'><b>上下文警告：</b>{}</p>".format(_text("；".join(map(str, warnings))))
    return ("<table class='conditions'><tbody>{}</tbody></table>{}"
            "<p class='muted'>上下文清单记录模型实际使用和排除的来源；候选知识不会被标记为正式科学依据。</p>".format(table, notes))


def _capacity_trend_html(cycles) -> str:
    complete = [row for row in cycles or [] if row.get("complete")]
    if not complete:
        return "<p class='muted'>未识别到可用于趋势分析的完整循环。</p>"
    maximum = max(complete, key=lambda row: float(row.get("discharge_specific_capacity_mAh_g") or 0))
    selected = []
    for row in (complete[0], maximum, complete[-1]):
        if row.get("cycle") not in {item.get("cycle") for item in selected}:
            selected.append(row)
    rows = "".join("<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
        _text(row.get("cycle")), _number(row.get("discharge_specific_capacity_mAh_g"), 1),
        _number(row.get("capacity_retention_percent"), 2, "%"), _number(row.get("polarization_voltage_V"), 3, " V"),
    ) for row in selected)
    first = float(complete[0].get("discharge_specific_capacity_mAh_g") or 0)
    last = float(complete[-1].get("discharge_specific_capacity_mAh_g") or 0)
    change = (last / first - 1) * 100 if first > 0 else None
    summary = "从第 {} 圈的 {:.1f} mAh g⁻¹ 变化至第 {} 圈的 {:.1f} mAh g⁻¹".format(complete[0]["cycle"], first, complete[-1]["cycle"], last)
    if change is not None:
        summary += "，变化幅度为 {:+.2f}%".format(change)
    return "<p>{}</p><table><thead><tr><th>代表循环</th><th>放电比容量 / mAh g⁻¹</th><th>相对首圈保持率</th><th>极化</th></tr></thead><tbody>{}</tbody></table>".format(_text(summary), rows)


def _claim_field(claim, name: str, default=None):
    if isinstance(claim, Mapping):
        return claim.get(name, default)
    return getattr(claim, name, default)


def _as_knowledge_claim(claim) -> KnowledgeClaim | None:
    if isinstance(claim, KnowledgeClaim):
        return claim
    if not isinstance(claim, Mapping):
        return None
    try:
        return KnowledgeClaim(
            claim_id=str(claim.get("claim_id") or ""),
            project_id=str(claim.get("project_id") or ""),
            source_id=str(claim.get("source_id") or ""),
            claim_type=str(claim.get("claim_type") or ""),
            text=str(claim.get("text") or ""),
            metric_id=claim.get("metric_id"),
            value=claim.get("value"),
            unit=claim.get("unit"),
            conditions=dict(claim.get("conditions") or {}),
            evidence_span_ids=tuple(claim.get("evidence_span_ids") or ()),
            limitations=tuple(claim.get("limitations") or ()),
            status=str(claim.get("status") or "candidate"),
            row_version=int(claim.get("row_version") or 1),
            created_at=str(claim.get("created_at") or ""),
        )
    except (TypeError, ValueError):
        return None


def _approved_claims_html(claims: Sequence) -> str:
    rows = []
    for raw_claim in claims or []:
        claim = _as_knowledge_claim(raw_claim)
        if claim is None or claim.status != "approved":
            continue
        value = ""
        if claim.value is not None:
            value = "{} {}".format(_number(claim.value, 3), _text(claim.unit or "")).strip()
        rows.append("<tr><td>{}</td><td>{}</td><td>{}</td></tr>".format(
            _text(claim.text), value or "非数值声明", _text(claim.source_id),
        ))
    if not rows:
        return "<p class='muted'>本轮没有传入已批准的文献声明；候选声明不作为正式科学依据。</p>"
    return ("<table><thead><tr><th>已批准声明</th><th>批准数值</th><th>来源记录</th></tr></thead>"
            "<tbody>{}</tbody></table>").format("".join(rows))


def _observed_metric(metric_id: str | None, gcd: Mapping):
    aliases = {
        "first_complete_discharge_capacity_mAh_g": ("first_complete_discharge_capacity_mAh_g", "mAh/g"),
        "maximum_complete_discharge_capacity_mAh_g": ("maximum_complete_discharge_capacity_mAh_g", "mAh/g"),
        "latest_complete_discharge_capacity_mAh_g": ("latest_complete_discharge_capacity_mAh_g", "mAh/g"),
        "first_complete_average_discharge_voltage_V": ("first_complete_average_discharge_voltage_V", "V"),
        "latest_average_discharge_voltage_V": ("latest_average_discharge_voltage_V", "V"),
        "latest_polarization_voltage_V": ("latest_polarization_voltage_V", "V"),
        "latest_coulombic_efficiency_percent": ("latest_coulombic_efficiency_percent", "%"),
        "latest_capacity_retention_percent": ("latest_capacity_retention_percent", "%"),
    }
    if str(metric_id or "") not in aliases:
        return None
    key, unit = aliases[str(metric_id)]
    value = gcd.get(key)
    if value in (None, ""):
        return None
    if unit is None:
        unit = "mAh/g" if key.endswith("_mAh_g") else "V" if key.endswith("_V") else "%" if key.endswith("_percent") else ""
    try:
        return float(value), unit
    except (TypeError, ValueError):
        return None


def _formal_comparisons_html(claims: Sequence, comparisons: Sequence, gcd: Mapping, conditions: Mapping) -> str:
    approved = {}
    for raw_claim in claims or []:
        claim = _as_knowledge_claim(raw_claim)
        if claim is not None and claim.status == "approved":
            approved[claim.claim_id] = claim

    supplied = {
        item.claim_id: item for item in comparisons or []
        if isinstance(item, ComparisonOutcome) and item.comparability == "comparable" and item.decision
    }
    labels = {
        "above_reference": "高于已批准参考值",
        "below_reference": "低于已批准参考值",
        "matches_reference": "与已批准参考值一致",
    }
    rows = []
    for claim_id, claim in approved.items():
        observed = _observed_metric(claim.metric_id, gcd)
        outcome = None
        observed_value = None
        if observed is not None:
            observed_value, observed_unit = observed
            outcome = compare_metric(
                observed_value=observed_value,
                observed_unit=observed_unit,
                observed_conditions=conditions,
                claim=claim,
            )
        elif claim_id in supplied:
            outcome = supplied[claim_id]
            if outcome.absolute_difference is not None and claim.value is not None:
                observed_value = float(claim.value) + float(outcome.absolute_difference)
        if outcome is None or outcome.comparability != "comparable" or outcome.decision not in labels or observed_value is None:
            continue
        rows.append("<tr><td>{}</td><td>{} {}</td><td>{} {}</td><td>{}</td></tr>".format(
            _text(claim.text), _number(observed_value, 3), _text(claim.unit or ""),
            _number(claim.value, 3), _text(claim.unit or ""), _text(labels[outcome.decision]),
        ))
    if not rows:
        return "<p class='muted'>没有同时满足批准状态、单位一致和实验条件匹配的数值声明，因此不作正式高低比较。</p>"
    return ("<table><thead><tr><th>已批准参照</th><th>本轮测量</th><th>参考值</th><th>确定性结论</th></tr></thead>"
            "<tbody>{}</tbody></table><p class='muted'>正式比较仅由已批准声明和完全匹配的单位、实验条件生成。</p>").format("".join(rows))


def _reference_html(web: Mapping) -> str:
    rows = []
    for item in web.get("mainstream_systems") or []:
        capacity = item.get("specific_capacity_mAh_g")
        if capacity in (None, "") or not item.get("source_urls"):
            continue
        try:
            capacity = float(capacity)
        except (TypeError, ValueError):
            continue
        rows.append("<tr><td>{}</td><td>{:.1f}</td><td>{}</td><td>{}</td></tr>".format(
            _text(item.get("system")), capacity, "待审背景，不作优劣判断", _links(item.get("source_urls")),
        ))
    if not rows:
        return "<p class='muted'>本轮没有可列示的联网候选容量背景。</p>"
    return ("<table><thead><tr><th>联网候选体系</th><th>候选比容量 / mAh g⁻¹</th><th>证据边界</th><th>来源</th></tr></thead>"
            "<tbody>{}</tbody></table><p class='muted'>联网数值均为待审核背景，不进入正式比较，也不产生更高或更低判断。</p>").format("".join(rows))


def _energy_reference_html(theory: Mapping, web: Mapping) -> str:
    del web
    approved_statuses = {"approved", "user_provided", "user_confirmed"}
    status = str(theory.get("evidence_status") or theory.get("status") or "").strip().casefold()
    theory_value = theory.get("theoretical_specific_energy_Wh_kg")
    if theory_value in (None, "") or status not in approved_statuses:
        theory_text = "当前没有来自真实输入或批准记录的理论比能量模型，因此不作定量投影。"
    else:
        reaction = str(theory.get("reaction_candidate") or "已记录反应模型")
        theory_text = "{}。理论活性物质比容量为 {} mAh g⁻¹；以 {} V 计算，比能量投影为 {} Wh kg⁻¹。该值不等同于复合电极、电芯或电池包能量密度。".format(
            reaction,
            _number(theory.get("theoretical_specific_capacity_mAh_g"), 1),
            _number(theory.get("average_discharge_voltage_V"), 3),
            _number(theory_value, 1),
        )
    return "<p>{}</p><p class='muted'>未批准的联网模型和商用产品候选值不进入正式能量比较。</p>".format(_text(theory_text))


def _report_analysis(raw: Mapping) -> tuple[str, dict]:
    """Return an analysis type and payload while preserving legacy GCD input."""
    analysis_type = str(raw.get("analysis_type") or "").strip().casefold()
    if analysis_type:
        payload = raw.get("analysis")
        return analysis_type, dict(payload) if isinstance(payload, Mapping) else {}
    if "sweeps" in raw and "cycles" in raw:
        return "cv", dict(raw)
    if "low_frequency_tail" in raw or "minus_z_imag_peak" in raw:
        return "eis", dict(raw)
    if "pulses" in raw and "steps" in raw:
        return "gitt", dict(raw)
    if "sample_standard_deviation" in raw and "metric" in raw:
        return "replicates", dict(raw)
    return "gcd", dict(raw)


def _analysis_table(headers: Sequence[str], rows: Sequence[Sequence]) -> str:
    head = "".join("<th>{}</th>".format(_text(item)) for item in headers)
    body = "".join(
        "<tr>{}</tr>".format("".join("<td>{}</td>".format(_text(value)) for value in row))
        for row in rows
    )
    return "<table><thead><tr>{}</tr></thead><tbody>{}</tbody></table>".format(head, body)


def _non_gcd_analysis_context(analysis_type: str, analysis: Mapping) -> dict:
    """Build deterministic method-specific report content without GCD claims."""
    boundary = "本报告不能自动推断反应、等效电路或扩散系数。"
    if analysis_type == "cv":
        cycles = list(analysis.get("cycles") or [])
        first = cycles[0] if cycles else {}
        oxidation = dict(first.get("oxidation_peak") or {})
        reduction = dict(first.get("reduction_peak") or {})
        metrics = "".join([
            _metric("扫描循环", _number(analysis.get("cycle_count"), 0), "个", "按电位扫描方向分段"),
            _metric("完整循环", _number(analysis.get("complete_cycle_count"), 0), "个", "同时含氧化与还原候选峰"),
            _metric("扫描速率", _number(analysis.get("scan_rate_V_s"), 4), "V s⁻¹", "由实验条件明确提供"),
            _metric("氧化候选峰电位", _number(oxidation.get("potential_V"), 3), "V", "离散采样点极值"),
            _metric("还原候选峰电位", _number(reduction.get("potential_V"), 3), "V", "离散采样点极值"),
            _metric("首圈峰间距", _number(first.get("peak_separation_V"), 3), "V", "仅在完整扫描对中报告"),
        ])
        rows = [
            (row.get("sweep"), row.get("direction"), row.get("peak_type"),
             _number(row.get("peak_potential_V"), 3), _number(row.get("peak_current_A"), 6),
             _number(row.get("integrated_charge_C"), 6))
            for row in analysis.get("sweeps") or []
        ]
        detail = _analysis_table(
            ("扫描段", "方向", "峰类型", "峰电位 / V", "峰电流 / A", "积分电荷 / C"), rows
        ) if rows else "<p class='muted'>未识别到可展示的 CV 扫描段。</p>"
        observations = [
            "CV 仅报告扫描方向、离散候选峰和在已知扫描速率下的积分电荷。",
            "候选峰类型来自电流极值和扫描方向，不代表已确认的电化学反应。",
            boundary,
        ]
        return {
            "name": "循环伏安（CV）", "metrics": metrics, "detail": detail,
            "detail_title": "CV 扫描段确定性摘要", "observations": observations,
            "risks": ["未进行基线扣除、平滑、峰拟合或反应归属。"],
            "headline": "当前仅形成 CV 采样特征摘要；峰归属和机理解释需要独立证据。",
        }
    if analysis_type == "eis":
        frequency = dict(analysis.get("frequency_range_Hz") or {})
        intercept = dict(analysis.get("high_frequency_real_axis_intercept_candidate") or {})
        peak = dict(analysis.get("minus_z_imag_peak") or {})
        tail = dict(analysis.get("low_frequency_tail") or {})
        metrics = "".join([
            _metric("数据点", _number(analysis.get("point_count"), 0), "个", "按频率降序归一化"),
            _metric("最低频率", _number(frequency.get("minimum"), 4), "Hz", "实测频率范围"),
            _metric("最高频率", _number(frequency.get("maximum"), 4), "Hz", "实测频率范围"),
            _metric("高频实轴截距候选", _number(intercept.get("z_real_ohm"), 4), "Ω", "最高频窗口内 |Z″| 最小点"),
            _metric("−Z″ 峰值", _number(peak.get("minus_z_imag_ohm"), 4), "Ω", "离散采样点最大值"),
            _metric("低频尾部斜率", _number(tail.get("slope_d_minus_z_imag_d_z_real"), 4), "", "OLS 描述量"),
        ])
        detail = _analysis_table(
            ("描述量", "数值", "选择口径"),
            (
                ("高频实轴截距候选", _number(intercept.get("z_real_ohm"), 4, " Ω"), intercept.get("selection") or "实测点候选"),
                ("−Z″ 最大值", _number(peak.get("minus_z_imag_ohm"), 4, " Ω"), "离散采样点"),
                ("低频尾部斜率", _number(tail.get("slope_d_minus_z_imag_d_z_real"), 4), "指定尾部比例的 OLS"),
            ),
        )
        return {
            "name": "电化学阻抗谱（EIS）", "metrics": metrics, "detail": detail,
            "detail_title": "EIS 描述量确定性摘要",
            "observations": [
                "EIS 仅报告实测截距候选、−Z″ 离散峰值和指定低频尾部的线性斜率。",
                "未选择或拟合等效电路，低频尾部斜率不等同于扩散系数。",
                boundary,
            ],
            "risks": ["截距和峰值是采样点候选，结果受频率范围与采样密度限制。"],
            "headline": "当前仅形成 EIS 几何描述量摘要；电路元件和传输机理需要独立建模与验证。",
        }
    if analysis_type == "gitt":
        pulses = list(analysis.get("pulses") or [])
        first = pulses[0] if pulses else {}
        metrics = "".join([
            _metric("步骤数", _number(analysis.get("step_count"), 0), "个", "按电流阈值分段"),
            _metric("脉冲数", _number(analysis.get("pulse_count"), 0), "个", "|I| 超过阈值"),
            _metric("电流阈值", _number(analysis.get("current_threshold_A"), 6), "A", "由实验条件明确提供"),
            _metric("首脉冲瞬时电压变化", _number(first.get("instantaneous_voltage_change_V"), 4), "V", "相对前一静置末点"),
            _metric("首脉冲末端电压变化", _number(first.get("pulse_end_voltage_change_V"), 4), "V", "相对前一静置末点"),
            _metric("首脉冲弛豫电压变化", _number(first.get("relaxation_voltage_change_V"), 4), "V", "后续静置末点相对脉冲末点"),
        ])
        rows = [
            (row.get("pulse"), row.get("polarity"), _number(row.get("duration_s"), 3),
             _number(row.get("instantaneous_voltage_change_V"), 4),
             _number(row.get("steady_state_voltage_change_V"), 4),
             "未计算")
            for row in pulses
        ]
        detail = _analysis_table(
            ("脉冲", "极性", "持续时间 / s", "瞬时 ΔV / V", "稳态 ΔV / V", "扩散系数"), rows
        ) if rows else "<p class='muted'>未识别到可展示的 GITT 脉冲。</p>"
        return {
            "name": "恒电流间歇滴定（GITT）", "metrics": metrics, "detail": detail,
            "detail_title": "GITT 脉冲确定性摘要",
            "observations": [
                "GITT 仅按明确电流阈值报告脉冲、静置和电压变化。",
                "缺少几何、组成和热力学响应参数，因此未计算扩散系数。",
                boundary,
            ],
            "risks": ["步骤时长按首末采样点计算，不推断未采样的切换时刻。"],
            "headline": "当前仅形成 GITT 分段与电压响应摘要；扩散参数和反应解释不能由这些描述量自动得到。",
        }
    if analysis_type in {"replicate", "replicates", "replicate_stats"}:
        metric = str(analysis.get("metric") or "未命名指标")
        unit = str(analysis.get("unit") or "")
        metrics = "".join([
            _metric("重复指标", metric, unit, "所有输入必须同名同单位"),
            _metric("重复次数", _number(analysis.get("n"), 0), "次", "描述性统计样本数"),
            _metric("均值", _number(analysis.get("mean"), 6), unit, "算术平均值"),
            _metric("样本标准差", _number(analysis.get("sample_standard_deviation"), 6), unit, "n−1 分母"),
            _metric("变异系数", _number(analysis.get("coefficient_of_variation_percent"), 2), "%", "均值非零时报告"),
            _metric("范围", "{}–{}".format(_number(analysis.get("minimum"), 6), _number(analysis.get("maximum"), 6)), unit, "最小值至最大值"),
        ])
        detail = _analysis_table(
            ("指标", "单位", "n", "均值", "样本标准差", "变异系数"),
            ((metric, unit, analysis.get("n"), _number(analysis.get("mean"), 6),
              _number(analysis.get("sample_standard_deviation"), 6),
              _number(analysis.get("coefficient_of_variation_percent"), 2, "%")),),
        )
        return {
            "name": "重复实验统计", "metrics": metrics, "detail": detail,
            "detail_title": "同名同单位指标的重复统计摘要",
            "observations": [
                "重复统计仅汇总同名同单位指标，不执行单位换算或混合。",
                "结果仅为描述性统计，不包含显著性检验、离群值删除或置信区间。",
                boundary,
            ],
            "risks": ["重复次数少于 3 时不足以作重复性层面的解释。"] if int(analysis.get("n") or 0) < 3 else ["描述性统计不能替代预先定义的推断统计方案。"],
            "headline": "当前仅形成同名同单位指标的描述性重复统计，不作显著性或因果判断。",
        }
    raise ValueError("Unsupported report analysis_type {!r}.".format(analysis_type))


def write_report(
    path: Path | str,
    summary: Mapping,
    claims: Sequence,
    comparisons: Sequence,
    guidance: Mapping | None = None,
    analysis: Mapping | None = None,
    benchmark: Mapping | None = None,
    figures: Sequence[str] = (),
) -> Path:
    """Write a concise academic report without operational or implementation logs."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    raw_analysis = dict(analysis or {})
    analysis_type, analysis = _report_analysis(raw_analysis)
    is_gcd = analysis_type == "gcd"
    gcd = dict(analysis.get("gcd_summary") or {}) if is_gcd else {}
    benchmark = dict(benchmark or {})
    web = dict(benchmark.get("codex_web_research") or {})
    research_synthesis = dict(web.get("research_synthesis") or benchmark.get("research_synthesis") or {})
    review = dict(benchmark.get("codex_review") or {})
    guidance = dict(guidance or {})
    has_online_evidence = bool(web or research_synthesis)
    literature_intro = (
        "联网检索围绕课题材料、测量指标和证据边界筛选学术文献。网页候选内容只作为待审背景，不作为正式科学依据或性能优劣结论。"
        if has_online_evidence
        else "本轮没有可展示的联网文献结果。已批准的本地声明仍可作为受限依据。"
    )

    project_name = str(summary.get("project_name") or "未命名课题")
    material_system = str(summary.get("material_system") or "待补充")
    keywords = "、".join(map(str, summary.get("keywords") or [])) or "待补充"
    conditions = dict(summary.get("conditions") or {})
    comparison_conditions = dict(conditions)
    if material_system and material_system != "待补充":
        comparison_conditions.setdefault("material_system", material_system)

    if is_gcd:
        direction = build_research_direction(analysis, conditions)
        complete_cycles = [row for row in analysis.get("cycles") or [] if row.get("complete")]
        maximum_capacity = gcd.get("maximum_complete_discharge_capacity_mAh_g")
        if maximum_capacity in (None, "") and complete_cycles:
            maximum_capacity = max(float(row.get("discharge_specific_capacity_mAh_g") or 0) for row in complete_cycles)
        mass_note = "研究者已登记活性物质质量" if _number(conditions.get("active_material_mass_mg"), 3) != "待确认" else "仪器导出值；活性物质质量尚未登记"
        metrics = "".join([
            _metric("放电比容量", _number(gcd.get("latest_complete_discharge_capacity_mAh_g"), 1), "mAh g⁻¹", mass_note),
            _metric("平均放电电压", _number(gcd.get("latest_average_discharge_voltage_V"), 3), "V", "按容量增量加权"),
            _metric("充放电极化", _number(gcd.get("latest_polarization_voltage_V"), 3), "V", "平均充电电压减平均放电电压"),
            _metric("库仑效率", _number(gcd.get("latest_coulombic_efficiency_percent"), 2), "%", "表征当前循环的电荷收支"),
            _metric("容量保持率", _number(gcd.get("latest_capacity_retention_percent"), 2), "%", "相对首个完整循环"),
            _metric("最高放电比容量", _number(maximum_capacity, 1), "mAh g⁻¹", "完整循环中的最高值"),
        ])
        analysis_name = "恒流充放电（GCD）"
        detail_title = "放电比容量变化趋势"
        analysis_detail = _capacity_trend_html(analysis.get("cycles") or [])
        analysis_intro = "本课题聚焦 {} 体系的电化学行为，目标是在明确数据口径和证据边界的前提下，分析容量、平均放电电压、极化和循环稳定性之间的关系。".format(material_system)
        validation_intro = "当前需要优先确认导出数据是否可追溯、循环分段是否可靠，以及已登记测试条件是否足以支持重复实验和正式比较。"
    else:
        method_context = _non_gcd_analysis_context(analysis_type, analysis)
        direction = {
            "headline": method_context["headline"],
            "observations": method_context["observations"],
            "risks": method_context["risks"],
            "actions": [],
        }
        metrics = method_context["metrics"]
        analysis_name = method_context["name"]
        detail_title = method_context["detail_title"]
        analysis_detail = method_context["detail"]
        analysis_intro = "本课题聚焦 {} 体系的 {} 数据，报告仅呈现由输入数据确定性计算的描述量。".format(material_system, analysis_name)
        validation_intro = "所有方法参数必须由实验条件明确提供；本报告不把非 GCD 描述量解释为容量、反应、等效电路或扩散系数结论。"

    figures_html = "".join(
        "<figure><img src='{}' alt='{} 数据图'><figcaption>本轮实验数据的 Origin 导出图。</figcaption></figure>".format(
            escape(item, quote=True), _text(analysis_name)
        )
        for item in figures
    ) or "<p class='muted'>本轮未提供经校验的曲线图片。</p>"

    if is_gcd:
        stage_statement = (
            "当前实验已获得初步电化学数据，仍需核对循环分段和数据归一化口径。"
            "容量、极化和可逆性解释还需与仪器步骤、测试条件及对照实验相互印证。"
        )
        stage_next = "下一阶段应以可重复的对照实验和状态明确的表征为核心。只有当数据口径、循环边界和测试条件得到统一后，才能进一步讨论材料、反应或界面机制。"
    else:
        stage_statement = "当前实验已形成 {} 的确定性描述摘要，方法参数、单位和数据质量标记仍需随原始记录复核。".format(analysis_name)
        stage_next = "下一阶段应以重复实验和独立表征核验描述量。本报告不能自动推断反应、等效电路或扩散系数。"
    hypotheses = []
    for index, item in enumerate(guidance.get("hypotheses") or [], 1):
        hypotheses.append("<tr><td>{}</td><td>{}</td><td>{}</td></tr>".format(
            index, _text(item.get("claim")), _text(item.get("test"))
        ))
    hypothesis_table = ("<h3>需要区分的解释</h3><table><thead><tr><th>序号</th><th>待验证解释</th><th>判别实验</th></tr></thead><tbody>{}</tbody></table>".format("".join(hypotheses)) if hypotheses else "")

    experiments = []
    for index, item in enumerate(guidance.get("next_experiments") or direction["actions"], 1):
        action = item.get("action") or item.get("goal")
        variable = item.get("variable") or item.get("single_variable")
        evidence = item.get("expected_evidence") or item.get("decision_evidence")
        experiments.append("<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
            index, _text(action), _text(variable), _text(evidence)
        ))

    conclusion = direction["headline"]
    conclusion_label = "基于确定性数据的综合判断"
    theory = dict(benchmark.get("theoretical_energy") or {})
    if is_gcd:
        theory_note = "理论容量和比能量只有在反应路径、电子转移数、质量分母与电压参照来自真实输入或批准记录时，才能用于定量讨论。"
        candidate_reference = _reference_html(web)
        energy_reference = _energy_reference_html(theory, web)
        formal_comparisons = _formal_comparisons_html(claims, comparisons, gcd, comparison_conditions)
    else:
        theory_note = "非 GCD 数据不生成容量结论；本报告不能自动推断反应、等效电路或扩散系数。"
        candidate_reference = "<p class='muted'>非 GCD 分析不展示或比较容量候选值。</p>"
        energy_reference = "<p class='muted'>非 GCD 分析不生成理论容量或比能量投影。</p>"
        formal_comparisons = "<p class='muted'>本轮不把 GCD 容量声明套用于 {} 结果。</p>".format(_text(analysis_name))
    approved_claims = _approved_claims_html(claims)
    context_audit = _context_audit_html(benchmark.get("context_manifest") or {})

    body = """<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>{project_name}｜电化学研究报告</title><style>
:root{{--ink:#1e2a35;--muted:#667582;--navy:#203f5b;--blue:#356b89;--teal:#2d7779;--paper:#f4f6f7;--panel:#fff;--line:#d9e2e7;--soft:#edf4f5;--warn:#fff7e9}}*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.75 "Microsoft YaHei UI","Microsoft YaHei",sans-serif}}.wrap{{max-width:1100px;margin:auto;padding:32px 24px 68px}}.hero{{background:linear-gradient(135deg,#1b354d,#386d86);color:#fff;padding:34px 38px;border-radius:16px}}.hero h1{{font-size:31px;margin:5px 0 8px}}.hero p{{margin:5px 0;max-width:900px}}.tag{{display:inline-block;border:1px solid rgba(255,255,255,.32);border-radius:20px;padding:2px 11px;font-size:13px}}.panel{{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:25px 27px;margin-top:18px;box-shadow:0 6px 21px rgba(27,53,77,.05)}}h2{{color:var(--navy);font-size:23px;margin:0 0 15px;padding-bottom:8px;border-bottom:2px solid #d5e4e9}}h3{{color:var(--blue);font-size:17px;margin:21px 0 7px}}p{{margin:8px 0}}.metrics{{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin:18px 0}}.metric{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px}}.metric span,.metric small,.metric p{{display:block;color:var(--muted);font-size:12px}}.metric b{{display:block;color:var(--navy);font-size:21px;margin:3px 0}}.metric p{{line-height:1.35;margin:5px 0 0}}.figures{{display:grid;grid-template-columns:repeat(auto-fit,minmax(360px,1fr));gap:14px}}figure{{margin:0;border:1px solid var(--line);border-radius:9px;overflow:hidden}}figure img{{display:block;width:100%;height:auto}}figcaption{{padding:7px 11px;color:var(--muted);font-size:12px}}.callout{{padding:13px 16px;border-left:4px solid var(--teal);border-radius:5px;background:var(--soft)}}.warning{{background:var(--warn);border-left-color:#ba812d}}ul{{padding-left:22px}}li{{margin:5px 0}}table{{width:100%;border-collapse:collapse;margin-top:8px}}th,td{{padding:9px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}}th{{background:#eef3f5;color:var(--navy);font-weight:600}}.conditions{{max-width:620px}}.conditions th{{width:35%;background:transparent}}.literature-item{{padding:16px 0;border-bottom:1px solid var(--line)}}.literature-item:first-of-type{{padding-top:0}}.literature-item:last-child{{border-bottom:0}}.literature-item h3{{margin-top:0}}dl{{display:grid;grid-template-columns:130px 1fr;gap:7px 12px;margin:10px 0 0}}dt{{font-weight:600;color:var(--navy)}}dd{{margin:0}}a{{color:#126d73}}.muted{{color:var(--muted)}}@media(max-width:850px){{.metrics{{grid-template-columns:repeat(2,1fr)}}.hero{{padding:26px}}.panel{{padding:20px}}dl{{grid-template-columns:1fr}}}}@media print{{body{{background:#fff}}.wrap{{padding:0;max-width:none}}.panel,.metric,.hero{{box-shadow:none;break-inside:avoid}}}}
</style></head><body><main class='wrap'>
<header class='hero'><span class='tag'>电化学研究报告</span><h1>{project_name}</h1><p><b>材料体系：</b>{material_system}</p><p><b>研究关键词：</b>{keywords}</p></header>
<section class='panel'><h2>一、课题背景与研究问题</h2><p>{analysis_intro}</p><p>{validation_intro}</p><h3>本轮实验条件</h3><table class='conditions'><tbody>{conditions}</tbody></table></section>
<section class='panel'><h2>二、实验数据分析</h2><div class='metrics'>{metrics}</div><div class='figures'>{figures}</div><h3>{detail_title}</h3>{analysis_detail}<h3>基于已批准声明的正式比较</h3>{formal_comparisons}<h3>联网候选数值背景</h3>{candidate_reference}<h3>理论比能量边界</h3>{energy_reference}<h3>数据趋势与解释边界</h3>{observations}<h3>需要首先核验的数据边界</h3>{risks}<p class='muted'>{theory_note}</p></section>
<section class='panel'><h2>三、当前课题阶段定位</h2><div class='callout'>{stage_statement}</div><h3>阶段性判断</h3><p>{direction_headline}</p><p>{stage_next}</p>{hypotheses}</section>
<section class='panel'><h2>四、文献与知识依据</h2><p>{literature_intro}</p><h3>已批准文献声明</h3>{approved_claims}{research_synthesis}{literature_items}</section>
<section class='panel'><h2>五、综合结论与下一步实验</h2><div class='callout'><b>{conclusion_label}：</b>{conclusion}</div><h3>当前结论</h3>{direction_observations}<h3>建议的实验路线</h3><table><thead><tr><th>顺序</th><th>实验设计</th><th>唯一改变项</th><th>预期判定证据</th></tr></thead><tbody>{experiments}</tbody></table><h3>本轮Codex上下文与依据</h3>{context_audit}</section>
</main></body></html>""".format(
        project_name=_text(project_name), material_system=_text(material_system), keywords=_text(keywords),
        analysis_intro=_text(analysis_intro), validation_intro=_text(validation_intro),
        conditions=_mapping_rows(conditions), metrics=metrics, figures=figures_html,
        detail_title=_text(detail_title), analysis_detail=analysis_detail, formal_comparisons=formal_comparisons,
        candidate_reference=candidate_reference, energy_reference=energy_reference,
        observations=_list(direction["observations"], "本轮缺少足以形成确定性摘要的数据。"),
        risks=_list(direction["risks"], "本轮未发现需要单列说明的数据质量边界。"), theory_note=_text(theory_note),
        stage_statement=_text(stage_statement), direction_headline=_text(direction["headline"]), stage_next=_text(stage_next), hypotheses=hypothesis_table,
        approved_claims=approved_claims,
        literature_intro=_text(literature_intro),
        literature_items=_curated_knowledge_rows(review, benchmark.get("literature_studies") or []),
        research_synthesis=_research_synthesis_html(research_synthesis), standards=_standards_rows(web),
        conclusion_label=_text(conclusion_label), conclusion=_text(conclusion),
        direction_observations=_list(direction["observations"], "本轮缺少足以形成阶段性判断的完整循环数据。"),
        experiments="".join(experiments) or "<tr><td colspan='4' class='muted'>暂无可执行的实验建议。</td></tr>",
        context_audit=context_audit,
    )
    target.write_text(body, encoding="utf-8")
    return target
