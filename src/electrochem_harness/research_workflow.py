"""Unified data-analysis, literature-learning, approval and research-guidance flow."""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Mapping, Sequence

from .academic_search import AcademicSearchRequest
from .knowledge_assistant import (
    KnowledgeAssistantRequest,
    knowledge_candidate_key,
    run_knowledge_assistant,
)
from .llm_provider import LLMConfig, OpenAICompatibleProvider


_DIALOGUE_SYSTEM = """你是电化学研究Harness的课题指导助手。你只能依据给定的确定性分析、已读取原文的学习结果和用户补充的课题信息回答。人工确认知识可作为正式依据；尚未复核的原文学习知识只能用于提出候选解释和判别实验；已拒绝内容不得使用。区分事实、文献依据、假设和建议；不能把相关性写成因果，不能编造数值或文献。回答必须是JSON对象，字段仅为answer、basis、uncertainties、next_actions、questions_for_user；后四项均为字符串数组。使用简洁中文。"""

_DOMAIN_SYNONYMS = {
    "卤化物": ("halide solid electrolyte", "chloride solid electrolyte"),
    "固态电解质": ("solid electrolyte", "solid-state electrolyte"),
    "锂硫": ("lithium sulfur battery", "Li-S battery"),
    "锂离子": ("lithium ion battery", "Li-ion battery"),
    "钠离子": ("sodium ion battery", "Na-ion battery"),
}
_THEME_SYNONYMS = {
    "界面": ("interface stability", "interfacial reaction"),
    "阻抗": ("impedance growth", "interfacial resistance"),
    "衰减": ("capacity fading", "degradation mechanism"),
    "循环": ("cycling stability", "cycle performance"),
    "电导": ("ionic conductivity", "ion transport"),
    "极化": ("electrochemical polarization", "voltage hysteresis"),
}


def _clean(value) -> str:
    return " ".join(str(value or "").split())


def _atomic_json(path: Path, payload: Mapping) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _concept_groups(values: Mapping) -> tuple:
    searchable = " ".join(
        _clean(values.get(name))
        for name in ("research_domain", "research_question", "research_background", "battery_system")
    ).casefold()
    groups = []
    for marker, synonyms in _DOMAIN_SYNONYMS.items():
        if marker.casefold() in searchable:
            active_material = _clean(values.get("active_material"))
            groups.append(tuple(synonyms) + ((active_material,) if active_material else ()))
            break
    if not groups:
        domain = _clean(values.get("research_domain") or values.get("battery_system"))
        groups.append((domain,))
    for marker, synonyms in _THEME_SYNONYMS.items():
        if marker.casefold() in searchable:
            groups.append(synonyms)
            break
    if len(groups) == 1:
        groups.append(("electrochemical performance", "electrochemical behavior"))
    return tuple(groups)


def build_learning_request(values: Mapping, data_file, paper_library_dir="") -> KnowledgeAssistantRequest:
    """Derive an auditable search directly from the experiment and project context."""

    domain = _clean(values.get("research_domain"))
    question = _clean(values.get("research_question"))
    background = _clean(values.get("research_background"))
    profile = "; ".join(
        "{}={}".format(name, _clean(values.get(name)))
        for name in ("battery_system", "active_material", "cell_type", "counter_electrode")
        if _clean(values.get(name))
    )
    full_question = "{}。课题背景：{}。实验体系：{}。".format(question, background, profile)
    search = AcademicSearchRequest(
        domain=domain,
        research_question=full_question,
        concept_groups=_concept_groups(values),
        year_from=int(values.get("literature_year_from", 2018) or 2018),
        year_to=datetime.now(timezone.utc).year,
        databases=("crossref", "openalex", "tju_library", "web_of_science", "wiley"),
        max_results=5,
    )
    return KnowledgeAssistantRequest(
        search=search,
        local_fulltext_dir=_clean(values.get("local_fulltext_dir")),
        paper_library_dir=_clean(paper_library_dir),
        data_file=str(Path(data_file)),
        auto_fetch_publisher_html=True,
        open_guided_pages=False,
        max_documents=5,
        model_document_limit=1,
        max_evidence_chars=26000,
    )


def provider_from_environment():
    return OpenAICompatibleProvider(
        LLMConfig(
            base_url=os.environ.get("ELECTROCHEM_LLM_BASE_URL", "http://127.0.0.1:11434/v1"),
            model=os.environ.get("ELECTROCHEM_LLM_MODEL", "qwen3:4b-q4_K_M"),
            max_tokens=5000,
            max_input_chars=36000,
        )
    )


def run_integrated_learning(values: Mapping, *, data_file, project_root, progress_callback=None):
    request = build_learning_request(
        values,
        data_file,
        paper_library_dir=Path(project_root) / "knowledge" / "paper_library",
    )
    return run_knowledge_assistant(
        request,
        provider_from_environment(),
        run_root=Path(project_root) / "knowledge" / "runs",
        knowledge_path=Path(project_root) / "knowledge" / "research_knowledge.md",
        progress_callback=progress_callback,
    )


def candidate_statuses(reasoning: Mapping, status_by_id: Mapping[str, str]) -> list:
    rows = []
    for item in reasoning.get("knowledge_candidates", []):
        candidate_id = knowledge_candidate_key(item)
        rows.append(
            {
                "candidate_id": candidate_id,
                "status": status_by_id.get(candidate_id, "candidate"),
                "claim": _clean(item.get("claim")),
                "source_ids": list(item.get("source_ids", [])),
                "conditions": _clean(item.get("conditions")),
                "confidence": _clean(item.get("confidence")),
                "verification_needed": _clean(item.get("verification_needed")),
            }
        )
    return rows


def finalize_research_guidance(
    *,
    deterministic_conclusion,
    reasoning: Mapping,
    status_by_id: Mapping[str, str],
    values: Mapping,
    target,
    require_review: bool = True,
) -> Path:
    """Combine deterministic metrics with full-text learning and optional review."""

    reviews = candidate_statuses(reasoning, status_by_id)
    pending = [item for item in reviews if item["status"] == "candidate"]
    if pending and require_review:
        raise ValueError("仍有{}条候选知识未完成批准或拒绝。".format(len(pending)))
    approved = [item for item in reviews if item["status"] == "approved"]
    usable_learned = [item for item in reviews if item["status"] != "rejected"]
    deterministic_text = Path(deterministic_conclusion).read_text(encoding="utf-8").strip()

    lines = [
        "一、实验数据分析全景",
        deterministic_text,
        "",
        "二、原文学习记录（供人工核对，不自动进入正式结论）",
    ]
    findings = list(reasoning.get("article_core_findings", []))
    if findings:
        for index, item in enumerate(findings, 1):
            lines.append(
                "文献{}：{}；方法：{}；核心发现：{}；正文位置：{}；限制：{}。".format(
                    index, _clean(item.get("source_id")), _clean(item.get("method")),
                    _clean(item.get("core_finding")), _clean(item.get("evidence_location")),
                    _clean(item.get("limitations")),
                )
            )
    else:
        lines.append("本轮没有形成可核对的逐篇原文提炼；以下文献相关内容不能替代原文证据。")

    backgrounds = list(reasoning.get("research_background", []))
    foundations = list(reasoning.get("electrochemistry_foundations", []))
    if backgrounds:
        lines.append("领域背景：")
        for item in backgrounds:
            lines.append("- {}；来源：{}；证据等级：{}；边界：{}。".format(
                _clean(item.get("claim")), "、".join(item.get("source_ids", [])),
                _clean(item.get("evidence_level")), _clean(item.get("limitations")),
            ))
    if foundations:
        lines.append("可迁移的电化学知识：")
        for item in foundations:
            lines.append("- {}：{}；来源：{}；适用边界：{}。".format(
                _clean(item.get("concept")), _clean(item.get("explanation")),
                "、".join(item.get("source_ids", [])), _clean(item.get("boundaries")),
            ))

    lines.extend(["", "三、与本实验直接相关的图表参数和逻辑"])
    figure_items = list(reasoning.get("key_figures_tables", []))
    if figure_items:
        for item in figure_items:
            lines.append("{} {}：{} {}；条件：{}；科学逻辑：{}；与本实验关系：{}。".format(
                _clean(item.get("source_id")), _clean(item.get("location")),
                _clean(item.get("parameter")), "{} {}".format(_clean(item.get("value")), _clean(item.get("unit"))).strip(),
                _clean(item.get("conditions")), _clean(item.get("scientific_logic")),
                _clean(item.get("relevance_to_experiment")),
            ))
    else:
        lines.append("本轮没有提取到可核对的图表参数；不要用空缺参数进行性能对标。")

    lines.extend(["", "四、模型生成的候选判断（仅供审核，不作为正式依据）"])
    lines.append(_clean(reasoning.get("summary")) or "当前原文证据不足，不能形成进一步候选判断。")
    assessments = list(reasoning.get("data_value_assessment", []))
    if assessments:
        for item in assessments:
            lines.append("判断：{}；研究价值：{}；依据：{}；置信度：{}；限制：{}。".format(
                _clean(item.get("finding")), _clean(item.get("value")), _clean(item.get("evidence")),
                _clean(item.get("confidence")), _clean(item.get("limitations")),
            ))
    else:
        lines.append("未形成额外的数据价值判断，保留上面的确定性指标和边界。")

    lines.extend(["", "五、已学习知识及复核状态"])
    if usable_learned:
        for item in usable_learned:
            review_label = "已人工确认" if item["status"] == "approved" else "原文已学习，待人工复核"
            lines.append("{}：{}；来源：{}；适用条件：{}；仍需核对：{}。".format(
                review_label, item["claim"], "、".join(item["source_ids"]),
                item["conditions"] or "待进一步限定", item["verification_needed"] or "无",
            ))
    else:
        lines.append("本轮没有可用的原文知识；后续建议仅依据确定性数据现象生成。")

    unknowns = [_clean(item) for item in reasoning.get("cannot_determine", []) if _clean(item)]
    lines.extend(["", "六、候选解释与证据缺口"])
    if unknowns:
        for item in unknowns:
            lines.append("尚不能判断：{}".format(item))
    else:
        lines.append("模型未列出不能判断项；人工仍需检查是否遗漏替代解释。")
    if approved:
        lines.append("已人工确认知识可作为文献依据；仍需遵守其适用条件，不能把文献中的相关性直接写成本实验的因果关系。")
    elif usable_learned:
        lines.append("本轮原文学习知识尚未人工复核，只用于提出候选解释和设计判别实验，不作为已证实机理。")
    else:
        lines.append("没有可用原文知识时，不选择唯一机理，只根据数据现象安排判别实验。")

    experiments = list(reasoning.get("missing_experiments", []))
    characterizations = list(reasoning.get("missing_characterization", []))
    lines.extend(["", "七、下一轮判别实验"])
    if experiments:
        for index, item in enumerate(experiments, 1):
            expected = _clean(item.get("expected_evidence"))
            lines.append("实验{}（{}）：要回答{}；方案：{}；主要变量/对照：{}；支持结果：{}；反证结果：若预期变化不出现或与候选解释相反，则降低该解释优先级。".format(
                index, _clean(item.get("priority")), _clean(item.get("question")),
                _clean(item.get("experiment")), _clean(item.get("variables")), expected,
            ))
    else:
        lines.append("暂无模型建议；先完成至少3个同条件平行电池和一个完整循环的独立复算。")

    lines.extend(["", "八、下一轮表征与取样"])
    if characterizations:
        for index, item in enumerate(characterizations, 1):
            expected = _clean(item.get("expected_evidence"))
            lines.append("表征{}（{}）：要回答{}；方法：{}；取样：{}；支持结果：{}；反证结果：未出现对应结构、化学态或形貌变化。".format(
                index, _clean(item.get("priority")), _clean(item.get("question")),
                _clean(item.get("characterization")), _clean(item.get("sampling")), expected,
            ))
    else:
        lines.append("暂无模型建议；至少保留未循环、首圈后、稳定期和明显衰减后的可比样品。")

    lines.extend(["", "九、知识增长与后续检索"])
    deltas = list(reasoning.get("learning_delta", []))
    if deltas:
        for item in deltas:
            lines.append("新增认识：{}；与既有知识关系：{}；来源：{}；未解决问题：{}。".format(
                _clean(item.get("new_understanding")), _clean(item.get("relationship_to_prior")),
                "、".join(item.get("source_ids", [])), _clean(item.get("unresolved_question")),
            ))
    else:
        lines.append("本轮没有形成明确的知识增量；下一轮应围绕当前证据缺口检索，而不是重复积累题录。")

    lines.extend([
        "",
        "十、整体课题推进建议",
        "研究领域：{}。".format(_clean(values.get("research_domain"))),
        "课题背景：{}。".format(_clean(values.get("research_background"))),
        "优先级1：确认数据口径与至少3个同条件平行电池，判断现象是否可重复。",
        "优先级2：围绕容量、平均放电电压、极化差和比能量中变化最大的指标，设计一个单变量对照。",
        "优先级3：把EIS与结构、成分、界面表征安排在相同循环节点，建立跨测试证据链。",
        "优先级4：每轮根据支持结果或反证结果淘汰候选解释，再决定下一轮实验与文献检索问题。",
    ])
    destination = Path(target)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    _atomic_json(
        destination.with_suffix(".json"),
        {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "research_domain": _clean(values.get("research_domain")),
            "research_question": _clean(values.get("research_question")),
            "candidate_reviews": reviews,
            "approved_count": len(approved),
            "learned_usable_count": len(usable_learned),
            "pending_review_count": len(pending),
            "review_required_for_generation": bool(require_review),
            "guidance_file": destination.name,
            "guidance_sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
            "source_reasoning_fields": sorted(reasoning.keys()),
        },
    )
    return destination


def ask_research_question(
    *, provider, values: Mapping, guidance_text: str, reasoning: Mapping,
    history: Sequence[Mapping], user_message: str, status_by_id: Mapping[str, str] | None = None,
) -> dict:
    reviewed = candidate_statuses(reasoning, status_by_id or {})
    approved = [item for item in reviewed if item["status"] == "approved"]
    learned_pending = [item for item in reviewed if item["status"] == "candidate"]
    payload = {
        "project": {
            "domain": _clean(values.get("research_domain")),
            "background": _clean(values.get("research_background")),
            "question": _clean(values.get("research_question")),
            "battery_system": _clean(values.get("battery_system")),
            "active_material": _clean(values.get("active_material")),
        },
        "deterministic_analysis": guidance_text[-18000:],
        "literature_learning": {
            "approved_knowledge": approved,
            "learned_pending_review": learned_pending,
            "cannot_determine": list(reasoning.get("cannot_determine", [])),
            "rejected_content_omitted": True,
            "usage_rule": "approved可作为文献依据；pending只能用于候选解释和判别实验",
        },
        "recent_dialogue": [dict(item) for item in history[-8:]],
        "user_message": _clean(user_message),
    }
    result = provider.generate_json(_DIALOGUE_SYSTEM, payload)
    response = dict(result.payload)
    allowed = {"answer", "basis", "uncertainties", "next_actions", "questions_for_user"}
    if set(response) - allowed or not _clean(response.get("answer")):
        raise ValueError("课题对话模型返回格式不完整。")
    normalized = {"answer": _clean(response.get("answer"))}
    for field in ("basis", "uncertainties", "next_actions", "questions_for_user"):
        value = response.get(field, [])
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, list):
            raise ValueError("课题对话字段{}必须是列表。".format(field))
        normalized[field] = [_clean(item) for item in value if _clean(item)]
    normalized["model"] = result.model
    normalized["total_tokens"] = result.total_tokens
    return normalized


def append_dialogue(path, record: Mapping) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(dict(record), ensure_ascii=False) + "\n")
