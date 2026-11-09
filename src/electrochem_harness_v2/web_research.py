"""Validation for Codex web-search research candidates."""
from __future__ import annotations

from typing import Any, Mapping
from urllib.parse import urlparse


def _https_url(value: Any) -> str:
    text = str(value or "").strip()
    parsed = urlparse(text)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("Every online research source must use an HTTPS URL.")
    return text


def _summary_text(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        return "；".join(str(item).strip() for item in value if str(item).strip())
    return str(value or "").strip()


def validate_web_research(payload: Mapping[str, Any]) -> dict:
    if not isinstance(payload, Mapping):
        raise ValueError("Codex web research result must be an object.")
    for name in ("sources", "mainstream_systems", "standards"):
        if not isinstance(payload.get(name), list):
            raise ValueError("Codex web research field {} must be an array.".format(name))
    sources = []
    allowed_urls = set()
    source_titles = {}
    for row in payload["sources"]:
        if not isinstance(row, Mapping) or not str(row.get("title") or "").strip():
            raise ValueError("Online source requires a title.")
        url = _https_url(row.get("url"))
        allowed_urls.add(url)
        source_titles[url] = str(row["title"]).strip()
        sources.append({
            "title": str(row["title"]).strip(),
            "url": url,
            "source_type": str(row.get("source_type") or "web").strip(),
            "claims": list(row.get("claims") or []),
            "evidence_level": "web_search_candidate",
        })
    priority_sources = []
    for row in payload.get("priority_sources") or []:
        if not isinstance(row, Mapping):
            continue
        try:
            url = _https_url(row.get("url"))
        except ValueError:
            continue
        if url not in allowed_urls:
            continue
        title = str(row.get("title") or source_titles.get(url) or "").strip()
        if not title:
            continue
        priority_sources.append({
            "title": title,
            "url": url,
            "why_relevant": str(row.get("why_relevant") or "").strip(),
            "evidence_level": "web_search_candidate",
        })

    knowledge_digest = []
    rejected_knowledge_digest = []
    digest_rows = payload.get("knowledge_digest") or []
    if not isinstance(digest_rows, list):
        raise ValueError("Codex knowledge_digest must be an array.")
    if len(digest_rows) > 6:
        raise ValueError("Codex knowledge_digest may contain at most 6 items.")
    for number, row in enumerate(digest_rows, start=1):
        if not isinstance(row, Mapping):
            rejected_knowledge_digest.append("知识条目 {} 不是对象。".format(number))
            continue
        required = ("title", "claim", "why_selected", "tests", "question", "finding", "how_to_borrow")
        if any(not str(row.get(field) or "").strip() for field in required) or not row.get("tests"):
            rejected_knowledge_digest.append("知识条目 {} 缺少测试、发现或借鉴方法。".format(number))
            continue
        try:
            urls = [_https_url(value) for value in row.get("source_urls") or []]
        except ValueError:
            rejected_knowledge_digest.append("知识条目 {} 缺少有效 HTTPS 来源。".format(number))
            continue
        if not urls or not set(urls).issubset(allowed_urls):
            rejected_knowledge_digest.append("知识条目 {} 的来源未列入本轮来源表。".format(number))
            continue
        priority = str(row.get("priority") or "medium").strip().casefold()
        if priority not in {"high", "medium", "low"}:
            priority = "medium"
        knowledge_digest.append({
            "title": str(row["title"]).strip(),
            "claim": str(row["claim"]).strip(),
            "priority": priority,
            "why_selected": str(row["why_selected"]).strip(),
            "tests": [str(value).strip() for value in row.get("tests") or [] if str(value).strip()],
            "question": str(row["question"]).strip(),
            "finding": str(row["finding"]).strip(),
            "how_to_borrow": str(row["how_to_borrow"]).strip(),
            "source_urls": urls,
            "evidence_status": "web_search_candidate",
        })

    mainstream = []
    for row in payload["mainstream_systems"]:
        if not isinstance(row, Mapping) or not str(row.get("system") or "").strip():
            raise ValueError("Mainstream system candidate requires a system name.")
        urls = [_https_url(value) for value in row.get("source_urls") or []]
        if not urls or not set(urls).issubset(allowed_urls):
            raise ValueError("Mainstream system candidate must cite a listed source URL.")
        clean = dict(row)
        if clean.get("specific_capacity_mAh_g") in (None, ""):
            clean["specific_capacity_mAh_g"] = clean.get("representative_specific_capacity_mAh_g")
        clean["source_urls"] = urls
        clean["status"] = "candidate"
        mainstream.append(clean)
    standards = []
    for row in payload["standards"]:
        if not isinstance(row, Mapping):
            raise ValueError("Industry standard candidate must be an object.")
        url = _https_url(row.get("url"))
        clean = dict(row)
        clean["url"] = url
        clean["status"] = "candidate"
        standards.append(clean)
    theory = payload.get("theoretical_model")
    if theory is not None:
        if not isinstance(theory, Mapping):
            theory = None
        else:
            try:
                urls = [_https_url(value) for value in theory.get("source_urls") or []]
            except ValueError:
                urls = []
            if not urls or not set(urls).issubset(allowed_urls):
                theory = None
            else:
                theory = dict(theory)
                theory["source_urls"] = urls
                theory["status"] = "candidate"
    studies = []
    for row in payload.get("literature_studies") or []:
        if not isinstance(row, Mapping) or not str(row.get("study") or "").strip() or not row.get("tests") or not str(row.get("how_to_borrow") or "").strip():
            continue
        urls = [_https_url(value) for value in row.get("source_urls") or []]
        if not urls or not set(urls).issubset(allowed_urls):
            continue
        studies.append({
            "study": str(row["study"]).strip(), "tests": [str(value) for value in row.get("tests") or []], "question": str(row.get("question") or "").strip(), "finding": str(row.get("finding") or "").strip(), "how_to_borrow": str(row["how_to_borrow"]).strip(), "source_urls": urls, "evidence_status": "web_search_candidate",
        })
    commercial_batteries = []
    for row in payload.get("commercial_batteries") or []:
        if not isinstance(row, Mapping) or not str(row.get("chemistry") or "").strip():
            continue
        try:
            energy_density = float(row.get("energy_density_Wh_kg"))
            urls = [_https_url(value) for value in row.get("source_urls") or []]
        except (TypeError, ValueError):
            continue
        if energy_density <= 0 or not urls or not set(urls).issubset(allowed_urls):
            continue
        commercial_batteries.append({
            "chemistry": str(row["chemistry"]).strip(),
            "energy_density_Wh_kg": energy_density,
            "basis": str(row.get("basis") or "cell").strip(),
            "source_urls": urls,
            "evidence_status": "web_search_candidate",
        })
    research_synthesis = payload.get("research_synthesis") or {}
    if not isinstance(research_synthesis, Mapping):
        research_synthesis = {}
    research_synthesis = {
        "search_question": _summary_text(research_synthesis.get("search_question")),
        "data_literature_connection": _summary_text(research_synthesis.get("data_literature_connection")),
        "evidence_boundaries": [str(value).strip() for value in research_synthesis.get("evidence_boundaries") or [] if str(value).strip()],
    }
    return {"status": "candidate", "sources": sources, "priority_sources": priority_sources, "knowledge_digest": knowledge_digest, "rejected_knowledge_digest": rejected_knowledge_digest, "mainstream_systems": mainstream, "commercial_batteries": commercial_batteries, "standards": standards, "literature_studies": studies, "research_synthesis": research_synthesis, "theoretical_model": theory}
