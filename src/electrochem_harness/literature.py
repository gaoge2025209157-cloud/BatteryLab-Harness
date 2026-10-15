"""Verified literature retrieval and comparability screening.

Only DOI records re-fetched from Crossref's single-work endpoint are retained.
Bibliometric counts help order records but are never treated as journal quality or
proof that an experimental result is superior.
"""

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import html
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Dict, List, Optional
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


CROSSREF_WORKS = "https://api.crossref.org/works"
OPENALEX_WORKS = "https://api.openalex.org/works"


def _is_unknown(value: str) -> bool:
    return value.strip().casefold() in {"", "待填", "未知", "unknown", "n/a", "na", "???"}


@dataclass(frozen=True)
class ResearchProfile:
    battery_system: str = ""
    active_material: str = ""
    cell_type: str = ""
    counter_electrode: str = ""
    test_current: str = ""
    temperature: str = ""
    normalization_basis: str = ""

    @property
    def cell_description(self) -> str:
        values = [self.cell_type.strip()]
        if self.counter_electrode.strip():
            values.append("对电极：{}".format(self.counter_electrode.strip()))
        return "；".join(value for value in values if value)

    def missing_required(self) -> List[str]:
        fields = [
            ("battery_system", "电池体系"),
            ("active_material", "活性物质"),
            ("cell_type", "电池类型"),
            ("counter_electrode", "对电极"),
            ("test_current", "测试电流/倍率"),
            ("temperature", "测试温度"),
            ("normalization_basis", "质量归一化口径"),
        ]
        return [label for name, label in fields if _is_unknown(getattr(self, name))]

    def to_dict(self) -> Dict[str, str]:
        return asdict(self)


PROMPTS = [
    ("battery_system", "电池体系（如锂硫电池、钠离子电池）"),
    ("active_material", "活性物质（写明化学式/复合材料）"),
    ("cell_type", "电池类型（半电池/全电池/对称电池）"),
    ("counter_electrode", "对电极或另一电极（如 Li、Na、NMC811）"),
    ("test_current", "测试电流或倍率（如 100 mA g-1、0.1 C）"),
    ("temperature", "测试温度（如 25 C）"),
    ("normalization_basis", "比容量质量归一化口径（如硫质量、正极活性物质质量）"),
]


def collect_research_profile(
    defaults: Optional[ResearchProfile] = None,
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], None] = print,
) -> ResearchProfile:
    """Interactively collect the minimum metadata needed for comparison."""
    current = defaults or ResearchProfile()
    values = {}
    output_fn("请填写文献比较条件；不确定时输入‘待填’，程序将暂缓水平判断。")
    for name, label in PROMPTS:
        default = getattr(current, name).strip()
        suffix = " [{}]".format(default) if default else ""
        entered = input_fn("{}{}: ".format(label, suffix)).strip()
        values[name] = entered or default
    return ResearchProfile(**values)


def _fetch_json(url: str) -> dict:
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "ElectrochemHarness/0.2 (mailto:unknown@example.invalid)",
        },
    )
    with urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _abstract_from_inverted_index(index) -> str:
    if not isinstance(index, dict) or not index:
        return ""
    positioned = []
    for word, positions in index.items():
        for position in positions or []:
            positioned.append((int(position), str(word)))
    positioned.sort()
    return " ".join(word for _, word in positioned)


def _enrich_from_openalex(record, getter):
    if not record or record.get("abstract"):
        return record
    work_id = quote("https://doi.org/{}".format(record["doi"]), safe="")
    payload = getter("{}/{}".format(OPENALEX_WORKS, work_id))
    abstract = _abstract_from_inverted_index(payload.get("abstract_inverted_index"))
    if abstract:
        record["abstract"] = abstract
        searchable = "{} {} {}".format(
            record.get("title", ""), abstract, record.get("journal", "")
        )
        record["metrics"] = extract_reported_metrics(searchable)
    record["openalex_id"] = payload.get("id")
    record["openalex_cited_by_count"] = payload.get("cited_by_count")
    record["openalex_topics"] = [
        topic.get("display_name")
        for topic in payload.get("topics", [])[:10]
        if topic.get("display_name")
    ]
    record["metadata_sources"] = ["Crossref", "OpenAlex"]
    return record


def _clean_markup(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value or "")
    return " ".join(html.unescape(value).split())


def _first(value, default=""):
    if isinstance(value, list):
        return value[0] if value else default
    return value or default


def _year(item: dict):
    for key in ("published-print", "published-online", "issued"):
        parts = item.get(key, {}).get("date-parts", [])
        if parts and parts[0]:
            return parts[0][0]
    return None


def _normalize(value: str) -> str:
    value = value.casefold().replace("−", "-").replace("–", "-")
    return "".join(character for character in value if character.isalnum() or character in ".-")


def _condition_matches(profile: ResearchProfile, text: str) -> Dict[str, bool]:
    normalized_text = _normalize(text)
    return {
        name: not _is_unknown(value) and _normalize(value) in normalized_text
        for name, value in profile.to_dict().items()
    }


def _metric(patterns: List[str], text: str):
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return float(match.group(1))
    return None


def extract_reported_metrics(text: str) -> dict:
    """Extract only explicitly labelled values from title/abstract metadata."""
    cleaned = text.replace("−", "-").replace("–", "-")
    return {
        "specific_capacity_mAh_g": _metric(
            [r"(\d+(?:\.\d+)?)\s*mA\s*h\s*(?:/\s*g|g\s*-?\s*1)"], cleaned
        ),
        "coulombic_efficiency_percent": _metric(
            [r"(\d+(?:\.\d+)?)\s*%\s*(?:coulombic\s+efficiency|CE\b)"], cleaned
        ),
        "capacity_retention_percent": _metric(
            [r"(\d+(?:\.\d+)?)\s*%\s*(?:capacity\s+retention|retention)"], cleaned
        ),
        "cycle_count": _metric(
            [r"(?:after|over|for)\s+(\d+(?:\.\d+)?)\s+cycles?"], cleaned
        ),
    }


def _record_from_item(
    item: dict, profile: ResearchProfile, research_roles=None
) -> Optional[dict]:
    if item.get("type") != "journal-article" or not item.get("DOI"):
        return None
    title = str(_first(item.get("title")))
    abstract = _clean_markup(item.get("abstract", ""))
    searchable = " ".join(
        [title, abstract, str(_first(item.get("container-title")))]
    )
    matches = _condition_matches(profile, searchable)
    matched = sum(matches.values())
    direct = bool(matches) and matched == len(matches)
    authors = []
    for author in item.get("author", [])[:6]:
        name = "{} {}".format(author.get("given", ""), author.get("family", "")).strip()
        if name:
            authors.append(name)
    doi = item["DOI"].strip().lower()
    return {
        "title": title,
        "authors": authors,
        "journal": str(_first(item.get("container-title"))),
        "year": _year(item),
        "doi": doi,
        "url": "https://doi.org/{}".format(doi),
        "doi_verified": True,
        "citation_count": int(item.get("is-referenced-by-count", 0) or 0),
        "abstract": abstract,
        "metrics": extract_reported_metrics(searchable),
        "condition_matches": matches,
        "matched_condition_count": matched,
        "match_level": "direct" if direct else "context_only",
        "research_roles": sorted(set(research_roles or ["benchmark"])),
    }


def _search_url(profile: ResearchProfile, rows: int) -> str:
    terms = [
        profile.battery_system,
        profile.active_material,
        profile.cell_type,
        profile.counter_electrode,
        profile.test_current,
        profile.temperature,
        "electrochemical performance capacity",
    ]
    params = {
        "query.bibliographic": " ".join(term for term in terms if term.strip()),
        "filter": "type:journal-article",
        "rows": max(1, min(rows, 1000)),
    }
    return "{}?{}".format(CROSSREF_WORKS, urlencode(params))


def _background_search_url(profile: ResearchProfile, rows: int) -> str:
    terms = [
        profile.battery_system,
        profile.active_material,
        "review mechanism interface kinetics thermodynamics degradation",
    ]
    params = {
        "query.bibliographic": " ".join(term for term in terms if term.strip()),
        "filter": "type:journal-article",
        "rows": max(1, min(rows, 1000)),
    }
    return "{}?{}".format(CROSSREF_WORKS, urlencode(params))


def search_crossref(
    profile: ResearchProfile,
    max_results: int = 50,
    fetch_json: Optional[Callable[[str], dict]] = None,
) -> dict:
    """Search Crossref and retain only records re-fetched by DOI.

    A complete profile is required. Search candidates are individually looked up
    through ``/works/{doi}``; failures and non-journal records are excluded.
    """
    missing = profile.missing_required()
    if missing:
        return {
            "source": "Crossref REST API",
            "searched_at": datetime.now(timezone.utc).isoformat(),
            "query": profile.to_dict(),
            "missing_conditions": missing,
            "candidate_count": 0,
            "verified_count": 0,
            "directly_comparable_count": 0,
            "records": [],
            "limitations": ["检索未执行：比较条件不完整。"],
        }

    getter = fetch_json or _fetch_json
    query_rows = max(max_results * 2, 50)
    query_urls = {
        "benchmark": _search_url(profile, query_rows),
        "background": _background_search_url(profile, query_rows),
    }
    role_dois = {"benchmark": [], "background": []}
    candidate_roles = {}
    for role, url in query_urls.items():
        response = getter(url)
        for item in response.get("message", {}).get("items", []):
            doi = str(item.get("DOI", "")).strip().lower()
            if item.get("type") != "journal-article" or not doi:
                continue
            candidate_roles.setdefault(doi, set()).add(role)
            if doi not in role_dois[role]:
                role_dois[role].append(doi)

    dois = []
    longest = max((len(values) for values in role_dois.values()), default=0)
    for index in range(longest):
        for role in ("benchmark", "background"):
            values = role_dois[role]
            if index < len(values) and values[index] not in dois:
                dois.append(values[index])
                if len(dois) >= max_results:
                    break
        if len(dois) >= max_results:
            break

    def verify(doi):
        try:
            payload = getter("{}/{}".format(CROSSREF_WORKS, quote(doi, safe="")))
            record = _record_from_item(
                payload.get("message", {}), profile, candidate_roles.get(doi, set())
            )
            if fetch_json is None and record and not record.get("abstract"):
                try:
                    record = _enrich_from_openalex(record, getter)
                except Exception:
                    record["metadata_sources"] = ["Crossref"]
                    record["openalex_enrichment_failed"] = True
            return record
        except Exception:
            return None

    records = []
    if fetch_json is not None or len(dois) <= 1:
        records = [record for record in (verify(doi) for doi in dois) if record]
    else:
        with ThreadPoolExecutor(max_workers=min(8, len(dois))) as executor:
            futures = {executor.submit(verify, doi): doi for doi in dois}
            for future in as_completed(futures):
                record = future.result()
                if record:
                    records.append(record)

    records.sort(
        key=lambda record: (
            record["match_level"] == "direct",
            record["matched_condition_count"],
            record["citation_count"],
            record["year"] or 0,
        ),
        reverse=True,
    )
    direct_count = sum(record["match_level"] == "direct" for record in records)
    return {
        "source": "Crossref REST API",
        "searched_at": datetime.now(timezone.utc).isoformat(),
        "query": profile.to_dict(),
        "search_queries": query_urls,
        "search_strategy": ["direct_performance_benchmark", "background_mechanism_and_physical_chemistry"],
        "missing_conditions": [],
        "candidate_count": len(dois),
        "verified_count": len(records),
        "directly_comparable_count": direct_count,
        "records": records,
        "limitations": [
            "仅保留经 Crossref 单篇接口复核的 DOI 期刊论文。",
            "Crossref 缺少摘要时尝试用 OpenAlex DOI 记录补全摘要和主题；OpenAlex 不替代 DOI 核验。",
            "Crossref/OpenAlex 元数据不提供期刊影响因子；引用次数仅用于排序，不代表研究质量。",
            "性能数值只从题名/摘要显式表达中提取，正文未公开时不推断测试条件。",
            "只有全部实验条件在元数据中明确匹配的记录才标记为直接可比。",
        ],
    }
