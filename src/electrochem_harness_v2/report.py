"""Academic Chinese report generated from auditable electrochemical evidence."""
from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Mapping, Sequence
from urllib.parse import urlparse

from .research_direction import build_research_direction
from .theoretical_energy import calculate_theoretical_energy


USER_CONFIRMED_P2O5_REACTION = "P₂O₅ + 16Li → 5Li₂O + 2Li₃P"
COMMERCIAL_ENERGY_REFERENCES = (
    {
        "chemistry": "宁德时代麒麟 NMC 动力电池",
        "energy_density_Wh_kg": 265,
        "basis": "制造商公开产品级指标",
        "source_urls": ["https://www.catl.com/en/research/technology/"],
    },
    {
        "chemistry": "宁德时代麒麟 LFP 动力电池",
        "energy_density_Wh_kg": 205,
        "basis": "制造商公开产品级指标",
        "source_urls": ["https://www.catl.com/en/research/technology/"],
    },
)


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


def _reference_html(web: Mapping, maximum_capacity) -> str:
    rows = []
    for item in web.get("mainstream_systems") or []:
        capacity = item.get("specific_capacity_mAh_g")
        if capacity in (None, "") or not item.get("source_urls"):
            continue
        try:
            capacity = float(capacity)
        except (TypeError, ValueError):
            continue
        comparison = "仅作条件未匹配的学术参考"
        if maximum_capacity not in (None, ""):
            comparison = "当前峰值高 {:.1f}%".format((float(maximum_capacity) / capacity - 1) * 100) if float(maximum_capacity) > capacity else "当前峰值低 {:.1f}%".format((1 - float(maximum_capacity) / capacity) * 100)
        rows.append("<tr><td>{}</td><td>{:.1f}</td><td>{}</td><td>{}</td></tr>".format(
            _text(item.get("system")), capacity, _text(comparison), _links(item.get("source_urls")),
        ))
    if not rows:
        return "<p class='muted'>本轮尚未获得同时具备数值、测试条件和可追溯来源的同行评议容量参照，因此不判断当前峰值是否高于领域报道。</p>"
    return "<table><thead><tr><th>同行评议参考体系</th><th>文献比容量 / mAh g⁻¹</th><th>与当前峰值</th><th>来源</th></tr></thead><tbody>{}</tbody></table><p class='muted'>以上只比较活性物质比容量；构型、质量分母、温度、倍率、压力和电压窗口不一致时，不构成综合性能优劣结论。</p>".format("".join(rows))


def _energy_reference_html(theory: Mapping, web: Mapping) -> str:
    theory_value = theory.get("theoretical_specific_energy_Wh_kg")
    if theory_value not in (None, ""):
        reaction = str(theory.get("reaction_candidate") or "候选反应模型")
        theory_text = "{}。理论活性物质比容量为 {} mAh g⁻¹；以 {} V 的 {} 计算，比能量投影为 {} Wh kg⁻¹。该值不等同于复合正极、电芯或电池包能量密度。".format(
            reaction,
            _number(theory.get("theoretical_specific_capacity_mAh_g"), 1),
            _number(theory.get("average_discharge_voltage_V"), 3),
            "实验平均放电电压" if str(theory.get("voltage_basis") or "").startswith("first_complete") else "反应模型平均电压",
            _number(theory_value, 1),
        )
    else:
        theory_text = "当前未形成可定量计算的理论比能量：需要可追溯反应式、电子转移数和平均放电电压。"
    rows = []
    references = COMMERCIAL_ENERGY_REFERENCES
    for item in references:
        rows.append("<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
            _text(item.get("chemistry")), _text(item.get("energy_density_Wh_kg")), _text(item.get("basis")), _links(item.get("source_urls")),
        ))
    commercial = "<p class='muted'>本轮未获得带来源和质量基准的商用电池能量密度参考。</p>" if not rows else "<table><thead><tr><th>常用商用电池体系</th><th>能量密度 / Wh kg⁻¹</th><th>质量基准</th><th>来源</th></tr></thead><tbody>{}</tbody></table>".format("".join(rows))
    return "<p>{}</p>{}<p class='muted'>商用电池数据仅用于应用情境参考，不能与活性物质理论值直接比较。</p>".format(_text(theory_text), commercial)


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
    del claims, comparisons
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    analysis = dict(analysis or {})
    gcd = dict(analysis.get("gcd_summary") or {})
    benchmark = dict(benchmark or {})
    web = dict(benchmark.get("codex_web_research") or {})
    research_synthesis = dict(web.get("research_synthesis") or benchmark.get("research_synthesis") or {})
    review = dict(benchmark.get("codex_review") or {})
    guidance = dict(guidance or {})

    project_name = str(summary.get("project_name") or "未命名课题")
    material_system = str(summary.get("material_system") or "待补充")
    keywords = "、".join(map(str, summary.get("keywords") or [])) or "待补充"
    conditions = dict(summary.get("conditions") or {})
    direction = build_research_direction(analysis, conditions)
    has_codex = bool(str(guidance.get("assessment") or "").strip())

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

    figures_html = "".join(
        "<figure><img src='{}' alt='充放电与循环性能图'><figcaption>本轮实验数据的 Origin 导出图。</figcaption></figure>".format(escape(item, quote=True))
        for item in figures
    ) or "<p class='muted'>本轮未提供经校验的曲线图片。</p>"

    first_capacity = gcd.get("first_complete_discharge_capacity_mAh_g")
    li_s_context = ""
    try:
        first_value = float(first_capacity)
        if first_value > 0:
            li_s_context = ("<p>以用户指定的 Li–S 理论比容量 1675 mAh g⁻¹作为情境参照，首个完整候选循环的仪器导出值为 {:.1f} mAh g⁻¹，"
                            "约为前者 {:.2f} 倍。这一比较只说明活性物质比容量这一单一指标的探索潜力，不能替代同构型电池的性能比较。</p>").format(
                                first_value, first_value / 1675.0)
    except (TypeError, ValueError):
        pass

    stage_statement = (
        "当前实验已获得初步电化学性能信号，仍处于“循环分段审核—衰减机制定位”的关键阶段。"
        "活性物质质量应作为本轮实验条件单独登记；容量、极化和可逆性解释还需与仪器步骤、电位参照和对照实验相互印证。"
    )
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

    codex_conclusion = str(guidance.get("assessment") or "").strip()
    conclusion = codex_conclusion or direction["headline"]
    conclusion_label = "Codex 综合判断" if has_codex else "基于确定性数据的综合判断"
    theory = dict(benchmark.get("theoretical_energy") or {})
    p2o5_context = "p2o5" in " ".join((project_name, material_system, keywords)).replace("₂", "2").casefold()
    if p2o5_context and theory.get("theoretical_specific_energy_Wh_kg") in (None, ""):
        voltage = gcd.get("first_complete_average_discharge_voltage_V")
        try:
            theory = calculate_theoretical_energy("P2O5", 16, voltage)
            theory.update({
                "status": "user_confirmed_reaction_experimental_voltage_projection",
                "reaction_candidate": USER_CONFIRMED_P2O5_REACTION,
                "voltage_basis": "first_complete_capacity_weighted_discharge_voltage",
                "source": "user_confirmed_reaction_model",
            })
        except (TypeError, ValueError):
            pass
    theory_note = str((guidance.get("theoretical_energy_assessment") or {}).get("conclusion") or "").strip()
    if not theory_note and theory:
        theory_note = "理论容量和比能量只能在反应路径、电子转移数、质量分母与电压参照明确后用于定量讨论。"
    capacity_trend = _capacity_trend_html(analysis.get("cycles") or [])
    academic_reference = _reference_html(web, maximum_capacity)
    energy_reference = _energy_reference_html(theory, web)
    context_audit = _context_audit_html(benchmark.get("context_manifest") or {})

    body = """<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>{project_name}｜电化学研究报告</title><style>
:root{{--ink:#1e2a35;--muted:#667582;--navy:#203f5b;--blue:#356b89;--teal:#2d7779;--paper:#f4f6f7;--panel:#fff;--line:#d9e2e7;--soft:#edf4f5;--warn:#fff7e9}}*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.75 "Microsoft YaHei UI","Microsoft YaHei",sans-serif}}.wrap{{max-width:1100px;margin:auto;padding:32px 24px 68px}}.hero{{background:linear-gradient(135deg,#1b354d,#386d86);color:#fff;padding:34px 38px;border-radius:16px}}.hero h1{{font-size:31px;margin:5px 0 8px}}.hero p{{margin:5px 0;max-width:900px}}.tag{{display:inline-block;border:1px solid rgba(255,255,255,.32);border-radius:20px;padding:2px 11px;font-size:13px}}.panel{{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:25px 27px;margin-top:18px;box-shadow:0 6px 21px rgba(27,53,77,.05)}}h2{{color:var(--navy);font-size:23px;margin:0 0 15px;padding-bottom:8px;border-bottom:2px solid #d5e4e9}}h3{{color:var(--blue);font-size:17px;margin:21px 0 7px}}p{{margin:8px 0}}.metrics{{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin:18px 0}}.metric{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px}}.metric span,.metric small,.metric p{{display:block;color:var(--muted);font-size:12px}}.metric b{{display:block;color:var(--navy);font-size:21px;margin:3px 0}}.metric p{{line-height:1.35;margin:5px 0 0}}.figures{{display:grid;grid-template-columns:repeat(auto-fit,minmax(360px,1fr));gap:14px}}figure{{margin:0;border:1px solid var(--line);border-radius:9px;overflow:hidden}}figure img{{display:block;width:100%;height:auto}}figcaption{{padding:7px 11px;color:var(--muted);font-size:12px}}.callout{{padding:13px 16px;border-left:4px solid var(--teal);border-radius:5px;background:var(--soft)}}.warning{{background:var(--warn);border-left-color:#ba812d}}ul{{padding-left:22px}}li{{margin:5px 0}}table{{width:100%;border-collapse:collapse;margin-top:8px}}th,td{{padding:9px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}}th{{background:#eef3f5;color:var(--navy);font-weight:600}}.conditions{{max-width:620px}}.conditions th{{width:35%;background:transparent}}.literature-item{{padding:16px 0;border-bottom:1px solid var(--line)}}.literature-item:first-of-type{{padding-top:0}}.literature-item:last-child{{border-bottom:0}}.literature-item h3{{margin-top:0}}dl{{display:grid;grid-template-columns:130px 1fr;gap:7px 12px;margin:10px 0 0}}dt{{font-weight:600;color:var(--navy)}}dd{{margin:0}}a{{color:#126d73}}.muted{{color:var(--muted)}}@media(max-width:850px){{.metrics{{grid-template-columns:repeat(2,1fr)}}.hero{{padding:26px}}.panel{{padding:20px}}dl{{grid-template-columns:1fr}}}}@media print{{body{{background:#fff}}.wrap{{padding:0;max-width:none}}.panel,.metric,.hero{{box-shadow:none;break-inside:avoid}}}}
</style></head><body><main class='wrap'>
<header class='hero'><span class='tag'>电化学研究报告</span><h1>{project_name}</h1><p><b>材料体系：</b>{material_system}</p><p><b>研究关键词：</b>{keywords}</p></header>
<section class='panel'><h2>一、课题背景与研究问题</h2><p>本课题聚焦 {material_system} 体系的电化学行为，目标是在明确容量归属和反应可逆性的前提下，建立容量、平均放电电压、极化和循环稳定性之间的关联。</p><p>当前需要优先回答三个问题：导出容量是否可以可靠归属于目标活性物质；循环过程中的容量衰减主要来自反应、传输还是固—固界面变化；在统一质量口径、温度、堆压和电压窗口后，该体系是否具有可重复的性能信号。</p><h3>本轮实验条件</h3><table class='conditions'><tbody>{conditions}</tbody></table></section>
<section class='panel'><h2>二、实验数据分析</h2><div class='metrics'>{metrics}</div><div class='figures'>{figures}</div><h3>放电比容量变化趋势</h3>{capacity_trend}<h3>当前峰值与同行评议文献参考</h3>{academic_reference}<h3>理论比能量与商用电池情境参考</h3>{energy_reference}<h3>数据趋势与解释边界</h3>{observations}{li_s_context}<h3>需要首先核验的数据边界</h3>{risks}<p class='muted'>{theory_note}</p></section>
<section class='panel'><h2>三、当前课题阶段定位</h2><div class='callout'>{stage_statement}</div><h3>阶段性判断</h3><p>{direction_headline}</p><p>下一阶段应以可重复的对照实验和状态明确的表征为核心。只有当质量口径、循环边界和测试条件得到统一后，才能将容量保持与极化变化用于讨论材料和界面机制。</p>{hypotheses}</section>
<section class='panel'><h2>四、Codex 联网文献学习明细</h2><p>Codex 已围绕课题材料、容量归属、反应可逆性及固态正极极化诊断筛选关键学术文献。检索只保留同行评议论文、期刊 DOI 页面与学术数据库线索，不展示商业标准或产品页面；网页候选的性能数值不直接写入本课题结论。</p>{research_synthesis}{literature_items}</section>
<section class='panel'><h2>五、综合结论与下一步实验</h2><div class='callout'><b>{conclusion_label}：</b>{conclusion}</div><h3>当前结论</h3>{direction_observations}<h3>建议的实验路线</h3><table><thead><tr><th>顺序</th><th>实验设计</th><th>唯一改变项</th><th>预期判定证据</th></tr></thead><tbody>{experiments}</tbody></table><h3>本轮Codex上下文与依据</h3>{context_audit}</section>
</main></body></html>""".format(
        project_name=_text(project_name), material_system=_text(material_system), keywords=_text(keywords),
        conditions=_mapping_rows(conditions), metrics=metrics, figures=figures_html,
        capacity_trend=capacity_trend, academic_reference=academic_reference, energy_reference=energy_reference,
        observations=_list(direction["observations"], "本轮缺少足以形成趋势判断的完整循环数据。"), li_s_context=li_s_context,
        risks=_list(direction["risks"], "本轮未发现需要单列说明的数据质量边界。"), theory_note=_text(theory_note),
        stage_statement=_text(stage_statement), direction_headline=_text(direction["headline"]), hypotheses=hypothesis_table,
        literature_items=_curated_knowledge_rows(review, benchmark.get("literature_studies") or []),
        research_synthesis=_research_synthesis_html(research_synthesis), standards=_standards_rows(web),
        conclusion_label=_text(conclusion_label), conclusion=_text(conclusion),
        direction_observations=_list(direction["observations"], "本轮缺少足以形成阶段性判断的完整循环数据。"),
        experiments="".join(experiments) or "<tr><td colspan='4' class='muted'>暂无可执行的实验建议。</td></tr>",
        context_audit=context_audit,
    )
    target.write_text(body, encoding="utf-8")
    return target
