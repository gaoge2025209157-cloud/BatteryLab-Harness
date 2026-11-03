"""Academic discovery and guided advanced-search planning.

Public APIs (Crossref/OpenAlex) are used for automated metadata discovery.  Licensed
bibliographic databases are opened in the user's own browser so campus-IP access,
login, terms of use, CAPTCHA, and download decisions remain under human control.
"""

from dataclasses import asdict, dataclass
import hashlib
import html
import json
import re
import webbrowser
from typing import Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


CROSSREF_WORKS = "https://api.crossref.org/works"
OPENALEX_WORKS = "https://api.openalex.org/works"
GUIDED_DATABASE_URLS = {
    "tju_library": "https://home.lib.tju.edu.cn/",
    "web_of_science": "https://www.webofscience.com/wos/woscc/advanced-search",
    "wiley": "https://onlinelibrary.wiley.com/action/doSearch",
    "scopus": "https://www.scopus.com/search/form.uri?display=advanced",
    "cnki": "https://kns.cnki.net/kns8s/AdvSearch",
    "google_scholar": "https://scholar.google.com/scholar",
}
AUTOMATIC_DATABASES = ("crossref", "openalex")
SUPPORTED_DATABASES = set(AUTOMATIC_DATABASES) | set(GUIDED_DATABASE_URLS)


def _clean(value: str) -> str:
    return " ".join(str(value or "").split())


def _tuple(values: Iterable[str]) -> Tuple[str, ...]:
    return tuple(value for value in (_clean(item) for item in values) if value)


def parse_concept_groups(text: str) -> Tuple[Tuple[str, ...], ...]:
    """Parse ``concept A|synonym; concept B|synonym`` into AND/OR groups."""
    groups = []
    for raw_group in re.split(r"[;；\n]+", text or ""):
        values = _tuple(re.split(r"[|｜]+", raw_group))
        if values:
            groups.append(values)
    return tuple(groups)


@dataclass(frozen=True)
class AcademicSearchRequest:
    domain: str
    research_question: str
    concept_groups: Tuple[Tuple[str, ...], ...]
    exact_phrases: Tuple[str, ...] = ()
    exclusions: Tuple[str, ...] = ()
    year_from: Optional[int] = None
    year_to: Optional[int] = None
    databases: Tuple[str, ...] = AUTOMATIC_DATABASES
    max_results: int = 5
    language: str = "any"

    def __post_init__(self):
        domain = _clean(self.domain)
        question = _clean(self.research_question)
        groups = tuple(_tuple(group) for group in self.concept_groups if _tuple(group))
        databases = tuple(dict.fromkeys(_clean(item).casefold() for item in self.databases))
        if not domain:
            raise ValueError("Knowledge domain is required.")
        if not question:
            raise ValueError("Research question is required.")
        if not groups:
            raise ValueError("At least one keyword concept group is required.")
        unsupported = sorted(set(databases) - SUPPORTED_DATABASES)
        if unsupported:
            raise ValueError("Unsupported academic databases: {}".format(", ".join(unsupported)))
        if not databases:
            raise ValueError("At least one academic database must be selected.")
        if not 1 <= int(self.max_results) <= 5:
            raise ValueError("max_results must be between 1 and 5 for one learning run.")
        if self.year_from is not None and int(self.year_from) < 1900:
            raise ValueError("year_from must be 1900 or later.")
        if self.year_to is not None and int(self.year_to) < 1900:
            raise ValueError("year_to must be 1900 or later.")
        if self.year_from and self.year_to and int(self.year_from) > int(self.year_to):
            raise ValueError("year_from cannot be later than year_to.")
        object.__setattr__(self, "domain", domain)
        object.__setattr__(self, "research_question", question)
        object.__setattr__(self, "concept_groups", groups)
        object.__setattr__(self, "exact_phrases", _tuple(self.exact_phrases))
        object.__setattr__(self, "exclusions", _tuple(self.exclusions))
        object.__setattr__(self, "databases", databases)
        object.__setattr__(self, "max_results", int(self.max_results))
        if self.year_from is not None:
            object.__setattr__(self, "year_from", int(self.year_from))
        if self.year_to is not None:
            object.__setattr__(self, "year_to", int(self.year_to))

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["concept_groups"] = [list(group) for group in self.concept_groups]
        payload["exact_phrases"] = list(self.exact_phrases)
        payload["exclusions"] = list(self.exclusions)
        payload["databases"] = list(self.databases)
        return payload


@dataclass(frozen=True)
class AdvancedSearchPlan:
    request: AcademicSearchRequest
    canonical_query: str
    database_queries: Mapping[str, str]
    browser_urls: Mapping[str, str]
    automatic_sources: Tuple[str, ...]
    plan_hash: str

    def to_dict(self) -> dict:
        return {
            "request": self.request.to_dict(),
            "canonical_query": self.canonical_query,
            "database_queries": dict(self.database_queries),
            "browser_urls": dict(self.browser_urls),
            "automatic_sources": list(self.automatic_sources),
            "plan_hash": self.plan_hash,
            "access_policy": {
                "automatic": "Crossref/OpenAlex public metadata APIs",
                "guided": "Licensed databases open in the user's browser; no credential or cookie collection",
            },
        }


def _quote_term(term: str) -> str:
    cleaned = _clean(term).replace('"', "")
    if " " in cleaned or "-" in cleaned:
        return '"{}"'.format(cleaned)
    return cleaned


def _base_boolean(request: AcademicSearchRequest) -> str:
    groups = []
    for group in request.concept_groups:
        rendered = " OR ".join(_quote_term(term) for term in group)
        groups.append("({})".format(rendered))
    groups.extend('"{}"'.format(item.replace('"', "")) for item in request.exact_phrases)
    query = " AND ".join(groups)
    if request.exclusions:
        query += " NOT ({})".format(" OR ".join(_quote_term(item) for item in request.exclusions))
    return query


def build_advanced_search_plan(request: AcademicSearchRequest) -> AdvancedSearchPlan:
    base = _base_boolean(request)
    year_clause = ""
    if request.year_from or request.year_to:
        start = request.year_from or 1900
        end = request.year_to or 2100
        year_clause = " AND PY=({}-{})".format(start, end)
    queries: Dict[str, str] = {}
    if "crossref" in request.databases:
        queries["crossref"] = base
    if "openalex" in request.databases:
        queries["openalex"] = base
    if "web_of_science" in request.databases:
        queries["web_of_science"] = "TS=({}){}".format(base, year_clause)
    if "scopus" in request.databases:
        scopus = "TITLE-ABS-KEY({})".format(base)
        if request.year_from:
            scopus += " AND PUBYEAR >= {}".format(request.year_from)
        if request.year_to:
            scopus += " AND PUBYEAR <= {}".format(request.year_to)
        queries["scopus"] = scopus
    if "cnki" in request.databases:
        year_text = ""
        if request.year_from or request.year_to:
            year_text = "；年份={}–{}".format(request.year_from or "不限", request.year_to or "不限")
        queries["cnki"] = "主题=({}){}".format(base, year_text)
    if "wiley" in request.databases:
        queries["wiley"] = base
    if "tju_library" in request.databases:
        queries["tju_library"] = "数据库导航：Web of Science、Wiley Online Library"
    if "google_scholar" in request.databases:
        queries["google_scholar"] = base

    browser_urls = {}
    for key, url in GUIDED_DATABASE_URLS.items():
        if key not in request.databases:
            continue
        if key == "google_scholar":
            browser_urls[key] = "{}?{}".format(url, urlencode({"q": base}))
        elif key == "wiley":
            browser_urls[key] = "{}?{}".format(url, urlencode({"AllField": base}))
        else:
            browser_urls[key] = url
    automatic = tuple(item for item in AUTOMATIC_DATABASES if item in request.databases)
    canonical = json.dumps(
        {"request": request.to_dict(), "queries": queries},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    plan_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return AdvancedSearchPlan(
        request=request,
        canonical_query=base,
        database_queries=queries,
        browser_urls=browser_urls,
        automatic_sources=automatic,
        plan_hash=plan_hash,
    )


def open_guided_search_pages(
    plan: AdvancedSearchPlan,
    opener: Callable[[str], bool] = webbrowser.open,
) -> Tuple[str, ...]:
    opened = []
    for database, url in plan.browser_urls.items():
        if opener(url):
            opened.append(database)
    return tuple(opened)


def _get_json(url: str) -> dict:
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "ElectrochemHarness/0.7 knowledge-assistant (mailto:unknown@example.invalid)",
        },
    )
    with urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _clean_markup(value: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", value or "")).split())


def _doi(value: str) -> str:
    value = _clean(value).casefold()
    return re.sub(r"^https?://(?:dx\.)?doi\.org/", "", value)


def _openalex_abstract(index) -> str:
    positioned = []
    for word, positions in (index or {}).items():
        for position in positions or []:
            positioned.append((int(position), str(word)))
    positioned.sort()
    return " ".join(word for _, word in positioned)


def _year_from_crossref(item: dict):
    for name in ("published-print", "published-online", "issued"):
        parts = item.get(name, {}).get("date-parts", [])
        if parts and parts[0]:
            return parts[0][0]
    return None


def _crossref_records(payload: dict) -> List[dict]:
    records = []
    for item in payload.get("message", {}).get("items", []):
        doi = _doi(item.get("DOI", ""))
        if not doi:
            continue
        title = item.get("title") or []
        journal = item.get("container-title") or []
        pdf_urls = []
        for link in item.get("link", []) or []:
            url = _clean(link.get("URL") or "")
            content_type = _clean(link.get("content-type") or "").casefold()
            if url and ("pdf" in content_type or url.casefold().split("?", 1)[0].endswith(".pdf")):
                if url not in pdf_urls:
                    pdf_urls.append(url)
        records.append(
            {
                "id": doi,
                "doi": doi,
                "title": _clean(title[0] if title else ""),
                "year": _year_from_crossref(item),
                "journal": _clean(journal[0] if journal else ""),
                "abstract": _clean_markup(item.get("abstract", "")),
                "landing_url": "https://doi.org/{}".format(doi),
                "pdf_url": pdf_urls[0] if pdf_urls else "",
                "pdf_urls": pdf_urls,
                "citation_count": int(item.get("is-referenced-by-count", 0) or 0),
                "source": "crossref",
                "evidence_level": "abstract" if item.get("abstract") else "metadata",
            }
        )
    return records


def _openalex_records(payload: dict) -> List[dict]:
    records = []
    for item in payload.get("results", []):
        doi = _doi((item.get("doi") or ""))
        source = ((item.get("primary_location") or {}).get("source") or {})
        location = item.get("primary_location") or {}
        identifier = doi or str(item.get("id") or "")
        if not identifier:
            continue
        abstract = _openalex_abstract(item.get("abstract_inverted_index"))
        pdf_urls = []
        fulltext_landing_urls = []
        for candidate in [item.get("best_oa_location") or {}, location, *(item.get("locations") or [])]:
            url = _clean(candidate.get("pdf_url") or "")
            if url and url not in pdf_urls:
                pdf_urls.append(url)
            landing = _clean(candidate.get("landing_page_url") or "")
            if landing and not landing.casefold().startswith("https://doi.org/") and landing not in fulltext_landing_urls:
                fulltext_landing_urls.append(landing)
            lowered = landing.casefold().split("?", 1)[0]
            if landing and (lowered.endswith(".pdf") or "/bitstreams/" in lowered and lowered.endswith("/download")):
                if landing not in pdf_urls:
                    pdf_urls.append(landing)
        records.append(
            {
                "id": identifier,
                "doi": doi,
                "title": _clean(item.get("display_name") or item.get("title") or ""),
                "year": item.get("publication_year"),
                "journal": _clean(source.get("display_name") or ""),
                "abstract": abstract,
                "landing_url": (
                    "https://doi.org/{}".format(doi)
                    if doi
                    else _clean(location.get("landing_page_url") or item.get("id") or "")
                ),
                "pdf_url": pdf_urls[0] if pdf_urls else "",
                "pdf_urls": pdf_urls,
                "fulltext_landing_urls": fulltext_landing_urls,
                "citation_count": int(item.get("cited_by_count", 0) or 0),
                "open_access": dict(item.get("open_access") or {}),
                "topics": [
                    topic.get("display_name")
                    for topic in (item.get("topics") or [])[:8]
                    if topic.get("display_name")
                ],
                "source": "openalex",
                "evidence_level": "abstract" if abstract else "metadata",
            }
        )
    return records


def _merge_record(existing: dict, incoming: dict) -> dict:
    merged = dict(existing)
    if len(incoming.get("abstract", "")) > len(merged.get("abstract", "")):
        merged["abstract"] = incoming["abstract"]
        merged["evidence_level"] = incoming.get("evidence_level", merged.get("evidence_level"))
    for name in ("title", "year", "journal", "landing_url", "pdf_url", "open_access", "topics"):
        if not merged.get(name) and incoming.get(name):
            merged[name] = incoming[name]
    pdf_urls = []
    for source_record in (existing, incoming):
        for url in source_record.get("pdf_urls", ()) or ():
            cleaned = _clean(url)
            if cleaned and cleaned not in pdf_urls:
                pdf_urls.append(cleaned)
        single = _clean(source_record.get("pdf_url") or "")
        if single and single not in pdf_urls:
            pdf_urls.append(single)
    merged["pdf_urls"] = pdf_urls
    if pdf_urls:
        merged["pdf_url"] = pdf_urls[0]
    landing_urls = []
    for source_record in (existing, incoming):
        for url in source_record.get("fulltext_landing_urls", ()) or ():
            cleaned = _clean(url)
            if cleaned and cleaned not in landing_urls:
                landing_urls.append(cleaned)
    merged["fulltext_landing_urls"] = landing_urls
    sources = set(str(merged.get("source", "")).split("+")) | set(
        str(incoming.get("source", "")).split("+")
    )
    merged["source"] = "+".join(sorted(item for item in sources if item))
    merged["citation_count"] = max(
        int(merged.get("citation_count", 0) or 0),
        int(incoming.get("citation_count", 0) or 0),
    )
    return merged


def _search_public_records(
    request: AcademicSearchRequest,
    getter: Callable[[str], dict] = _get_json,
) -> List[dict]:
    """Search selected public APIs and return all DOI-deduplicated candidates."""
    plan = build_advanced_search_plan(request)
    records: List[dict] = []
    pool_size = max(20, request.max_results * 5)
    if "crossref" in plan.automatic_sources:
        params = {
            "query.bibliographic": plan.canonical_query,
            "rows": pool_size,
            "select": "DOI,title,container-title,published-print,published-online,issued,abstract,is-referenced-by-count,type,link",
        }
        filters = ["type:journal-article"]
        if request.year_from:
            filters.append("from-pub-date:{}-01-01".format(request.year_from))
        if request.year_to:
            filters.append("until-pub-date:{}-12-31".format(request.year_to))
        params["filter"] = ",".join(filters)
        records.extend(_crossref_records(getter("{}?{}".format(CROSSREF_WORKS, urlencode(params)))))
    if "openalex" in plan.automatic_sources:
        params = {"search": plan.canonical_query, "per-page": pool_size}
        filters = ["type:article"]
        if request.year_from:
            filters.append("from_publication_date:{}-01-01".format(request.year_from))
        if request.year_to:
            filters.append("to_publication_date:{}-12-31".format(request.year_to))
        params["filter"] = ",".join(filters)
        records.extend(_openalex_records(getter("{}?{}".format(OPENALEX_WORKS, urlencode(params)))))

    merged: Dict[str, dict] = {}
    for record in records:
        key = record.get("doi") or record.get("id")
        if not key:
            continue
        merged[key] = _merge_record(merged[key], record) if key in merged else record
    return list(merged.values())


def search_public_candidate_pool(
    request: AcademicSearchRequest,
    getter: Callable[[str], dict] = _get_json,
) -> List[dict]:
    """Return a bounded pool so inaccessible PDFs can be replaced automatically."""

    return _search_public_records(request, getter=getter)


def search_public_metadata(
    request: AcademicSearchRequest,
    getter: Callable[[str], dict] = _get_json,
) -> List[dict]:
    """Return the top at-most-five metadata records for compatibility callers."""

    from .learning_policy import select_learning_records

    selected, _excluded = select_learning_records(
        request,
        _search_public_records(request, getter=getter),
        limit=request.max_results,
    )
    return selected
