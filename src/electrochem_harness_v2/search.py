"""Controlled Crossref and OpenAlex search with auditable evidence levels."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import Callable
from urllib.parse import quote_plus
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class SearchResult:
    query: str
    searched_at: str
    records: list[dict]
    status: str
    error: str | None = None


class LiteratureSearchAdapter:
    """Search metadata and abstracts. Neither is automatically treated as learned PDF evidence."""

    def __init__(self, transport: Callable[[str], dict] | None = None, openalex_transport: Callable[[str], dict] | None = None, timeout_seconds: int = 20):
        self.transport = transport or self._transport
        self.openalex_transport = openalex_transport if openalex_transport is not None else (None if transport is not None else self._transport)
        self.timeout_seconds = timeout_seconds

    def search(self, keywords: list[str], rows: int = 10) -> SearchResult:
        query = " ".join(str(item).strip() for item in keywords if str(item).strip())
        if not query:
            raise ValueError("At least one research keyword is required.")
        searched_at = datetime.now(timezone.utc).isoformat()
        errors = []
        records = []
        try:
            url = "https://api.crossref.org/works?query.bibliographic={}&rows={}".format(quote_plus(query), max(1, min(rows, 50)))
            records.extend(self._crossref_records(self.transport(url)))
        except Exception as error:
            errors.append("Crossref {}: {}".format(type(error).__name__, error))
        if self.openalex_transport is not None:
            try:
                url = "https://api.openalex.org/works?search={}&per-page={}".format(quote_plus(query), max(1, min(rows, 50)))
                records.extend(self._openalex_records(self.openalex_transport(url)))
            except Exception as error:
                errors.append("OpenAlex {}: {}".format(type(error).__name__, error))
        deduplicated = []
        seen = set()
        for record in records:
            identity = record.get("doi") or record.get("openalex_id") or record["title"].casefold()
            if identity in seen:
                continue
            seen.add(identity)
            deduplicated.append(record)
        status = "LITERATURE_SEARCHED" if deduplicated and not errors else "SEARCH_PARTIAL" if deduplicated or errors else "LITERATURE_SEARCHED"
        return SearchResult(query, searched_at, deduplicated, status, " | ".join(errors) or None)

    @staticmethod
    def _crossref_records(payload: dict) -> list[dict]:
        records = []
        for item in ((payload.get("message") or {}).get("items") or []):
            doi = str(item.get("DOI") or "").strip().casefold()
            title = " ".join((item.get("title") or [""])[0].split())
            if not (doi or title):
                continue
            authors = [" ".join(filter(None, [person.get("given"), person.get("family")])).strip() for person in item.get("author") or []]
            records.append({"doi": doi or None, "title": title or "Untitled", "authors": [name for name in authors if name], "published": item.get("published-print") or item.get("published-online") or item.get("issued"), "source": "Crossref", "source_level": "metadata_only", "license": item.get("license") or [], "url": item.get("URL")})
        return records

    @staticmethod
    def _openalex_records(payload: dict) -> list[dict]:
        records = []
        for item in payload.get("results") or []:
            abstract = LiteratureSearchAdapter._abstract(item.get("abstract_inverted_index"))
            doi = str(item.get("doi") or "").removeprefix("https://doi.org/").casefold() or None
            location = item.get("primary_location") or {}
            authors = [str((row.get("author") or {}).get("display_name") or "").strip() for row in item.get("authorships") or []]
            records.append({
                "openalex_id": item.get("id"), "doi": doi, "title": str(item.get("display_name") or "Untitled"),
                "authors": [name for name in authors if name], "published": item.get("publication_year"), "source": "OpenAlex",
                "source_level": "abstract_only" if abstract else "metadata_only", "abstract": abstract or None,
                "url": location.get("landing_page_url") or item.get("doi"), "open_access": item.get("open_access") or {},
                "best_oa_location": item.get("best_oa_location") or {},
            })
        return records

    @staticmethod
    def _abstract(index) -> str:
        if not isinstance(index, dict):
            return ""
        words = []
        for word, positions in index.items():
            for position in positions or []:
                words.append((int(position), str(word)))
        return " ".join(word for _, word in sorted(words))

    def _transport(self, url: str) -> dict:
        request = Request(url, headers={"Accept": "application/json", "User-Agent": "ElectrochemHarness-v2/0.2 (research metadata search)"})
        with urlopen(request, timeout=self.timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))
