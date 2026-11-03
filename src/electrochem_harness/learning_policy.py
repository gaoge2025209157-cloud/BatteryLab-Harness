"""Selection policy for cumulative full-text literature learning.

The policy deliberately does not call article citations an impact factor. Journal
quality is based on a small, auditable venue list; scientific relevance is scored
against the user's explicit concept groups. Metadata/abstracts are only a discovery
stage. A paper can enter the learning stage only after a matching full-text document
has been extracted.
"""

from dataclasses import replace
from pathlib import Path
import re
from typing import Iterable, List, Mapping, Sequence, Tuple


MAX_LEARNING_PAPERS = 5
MIN_RELEVANCE_SCORE = 65
MIN_FULLTEXT_CHARS = 1200

# This is an auditable priority list, not a live impact-factor database. Names are
# normalized and matched conservatively. Tier A/B both satisfy the default learning
# gate; the tier is retained in the run record for human review.
_JOURNAL_TIERS = {
    "A": (
        "nature energy",
        "nature materials",
        "nature chemistry",
        "nature nanotechnology",
        "nature sustainability",
        "nature reviews materials",
        "science",
        "joule",
        "energy & environmental science",
        "energy and environmental science",
        "advanced materials",
        "angewandte chemie international edition",
        "journal of the american chemical society",
        "chemical reviews",
    ),
    "B": (
        "nature communications",
        "science advances",
        "advanced energy materials",
        "acs energy letters",
        "energy storage materials",
        "nano energy",
        "advanced functional materials",
        "chemistry of materials",
        "journal of materials chemistry a",
        "acs nano",
        "small methods",
        "materials today",
        "chemical engineering journal",
        "matter",
        "journal of power sources",
        "electrochimica acta",
        "solid state ionics",
        "journal of the electrochemical society",
    ),
}


def _clean(value) -> str:
    return " ".join(str(value or "").split())


def _normalized(value) -> str:
    return re.sub(r"[^a-z0-9]+", " ", _clean(value).casefold()).strip()


def _doi(value) -> str:
    return re.sub(r"^https?://(?:dx\.)?doi\.org/", "", _clean(value).casefold()).rstrip(".,;)")


def journal_quality(journal: str) -> Tuple[str, str]:
    normalized = _normalized(journal)
    for tier, names in _JOURNAL_TIERS.items():
        if any(_normalized(name) == normalized for name in names):
            return tier, "项目内可审计的高水平/权威专业期刊优先名单"
    return "unverified", "期刊水平未在项目优先名单中得到确认"


def _term_matches(term: str, haystack: str) -> bool:
    normalized = _normalized(term)
    if not normalized:
        return False
    if normalized in haystack:
        return True
    tokens = [token for token in normalized.split() if len(token) >= 3]
    return bool(tokens) and all(token in haystack for token in tokens)


def relevance_score(request, record: Mapping) -> Tuple[int, int]:
    title = _normalized(record.get("title"))
    body = _normalized(
        " ".join(
            [
                _clean(record.get("title")),
                _clean(record.get("abstract")),
                " ".join(_clean(item) for item in record.get("topics", []) or []),
            ]
        )
    )
    groups = tuple(request.concept_groups or ())
    matched = 0
    title_matched = 0
    for group in groups:
        if any(_term_matches(term, body) for term in group):
            matched += 1
        if any(_term_matches(term, title) for term in group):
            title_matched += 1
    if not groups:
        return 0, 0
    group_fraction = matched / len(groups)
    title_fraction = title_matched / len(groups)
    exact_bonus = 10 if any(_term_matches(term, body) for term in request.exact_phrases) else 0
    score = min(100, round(70 * group_fraction + 20 * title_fraction + exact_bonus))
    return score, matched


def rank_learning_records(request, records: Iterable[Mapping]):
    """Return all eligible records in quality/relevance/full-text priority order."""

    selected: List[dict] = []
    excluded: List[dict] = []
    seen = set()
    for raw in records:
        record = dict(raw)
        doi = _doi(record.get("doi") or record.get("id"))
        identity = doi or _normalized(record.get("title"))
        if not identity or identity in seen:
            continue
        seen.add(identity)
        reasons = []
        if not doi or not re.match(r"^10\.\d{4,9}/\S+$", doi):
            reasons.append("缺少可核验DOI")
        if not _clean(record.get("title")):
            reasons.append("缺少题名")
        tier, quality_basis = journal_quality(_clean(record.get("journal")))
        if tier == "unverified":
            reasons.append("期刊水平未通过默认优先名单")
        score, matched_groups = relevance_score(request, record)
        if score < MIN_RELEVANCE_SCORE:
            reasons.append("相关性评分低于{}".format(MIN_RELEVANCE_SCORE))
        record.update(
            {
                "doi": doi,
                "doi_verified": bool(doi),
                "journal_quality_tier": tier,
                "journal_quality_basis": quality_basis,
                "relevance_score": score,
                "matched_concept_groups": matched_groups,
                "required_concept_groups": len(request.concept_groups),
            }
        )
        if reasons:
            excluded.append(
                {
                    "source_id": doi or identity,
                    "title": _clean(record.get("title")),
                    "journal": _clean(record.get("journal")),
                    "reasons": reasons,
                }
            )
        else:
            selected.append(record)
    tier_rank = {"A": 0, "B": 1}
    selected.sort(
        key=lambda item: (
            -int(bool(item.get("pdf_url") or item.get("pdf_urls") or item.get("fulltext_landing_urls"))),
            tier_rank.get(item.get("journal_quality_tier"), 9),
            -int(item.get("relevance_score", 0) or 0),
            -int(item.get("citation_count", 0) or 0),
            -int(item.get("year", 0) or 0),
        )
    )
    return selected, excluded


def select_learning_records(request, records: Iterable[Mapping], limit: int = MAX_LEARNING_PAPERS):
    """Return at most five strictly eligible records and exclusion reasons."""

    maximum = min(MAX_LEARNING_PAPERS, max(1, int(limit)))
    selected, excluded = rank_learning_records(request, records)
    for item in selected[maximum:]:
        excluded.append(
            {
                "source_id": item.get("doi") or item.get("id"),
                "title": item.get("title"),
                "journal": item.get("journal"),
                "reasons": ["超过每轮最多{}篇的学习上限".format(MAX_LEARNING_PAPERS)],
            }
        )
    return selected[:maximum], excluded


def _title_tokens(value: str) -> set:
    return {
        token
        for token in _normalized(value).split()
        if len(token) >= 4 and token not in {"with", "from", "using", "study", "based"}
    }


def _title_similarity(left: str, right: str) -> float:
    a = _title_tokens(left)
    b = _title_tokens(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def bind_fulltext_documents(records: Sequence[Mapping], documents: Sequence, limit: int = MAX_LEARNING_PAPERS):
    """Bind extracted originals to selected metadata and reject thin/mismatched text."""

    maximum = min(MAX_LEARNING_PAPERS, max(1, int(limit)))
    by_doi = {_doi(item.get("doi")): dict(item) for item in records if _doi(item.get("doi"))}
    matched = []
    excluded = []
    used_dois = set()
    for document in documents:
        body_chars = sum(
            len(_clean(value))
            for value in (
                document.background_excerpt,
                document.methods_excerpt,
                document.body_excerpt,
                " ".join(document.figure_table_evidence),
            )
        )
        record = by_doi.get(_doi(document.doi or document.source_id))
        if record is None:
            candidates = sorted(
                (
                    (_title_similarity(document.title or Path(document.source_uri).stem, item.get("title", "")), item)
                    for item in records
                    if _doi(item.get("doi")) not in used_dois
                ),
                key=lambda pair: pair[0],
                reverse=True,
            )
            if candidates and candidates[0][0] >= 0.45:
                record = dict(candidates[0][1])
        reasons = []
        if record is None:
            reasons.append("原文无法与高质量候选论文的DOI或题名对应")
        if body_chars < MIN_FULLTEXT_CHARS:
            reasons.append("可提取原文不足{}字符，可能只有摘要或目录".format(MIN_FULLTEXT_CHARS))
        if document.evidence_level not in {"fulltext_html", "local_pdf_text", "local_text"}:
            reasons.append("证据等级不是可核验原文")
        if reasons:
            excluded.append(
                {
                    "source_uri": Path(str(document.source_uri)).name,
                    "title": document.title,
                    "reasons": reasons,
                }
            )
            continue
        doi = _doi(record.get("doi"))
        if doi in used_dois:
            excluded.append(
                {
                    "source_uri": Path(str(document.source_uri)).name,
                    "title": document.title,
                    "reasons": ["同一DOI已有一份原文进入本轮学习"],
                }
            )
            continue
        used_dois.add(doi)
        matched.append(
            replace(
                document,
                source_id=doi,
                doi=doi,
                title=_clean(record.get("title")) or document.title,
            )
        )
        if len(matched) >= maximum:
            break
    missing = [
        {
            "source_id": _doi(item.get("doi")),
            "title": _clean(item.get("title")),
            "reasons": ["未找到与该候选论文匹配的可读取原文"],
        }
        for item in records
        if _doi(item.get("doi")) not in used_dois
    ]
    return matched, excluded + missing
