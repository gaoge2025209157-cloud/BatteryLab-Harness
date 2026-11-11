"""Controlled Crossref and OpenAlex search with bounded network retries."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import socket
import time
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus
from urllib.request import Request, urlopen


RETRYABLE_HTTP_STATUSES = frozenset({429, 500, 502, 503, 504})
SEARCH_ADAPTER_VERSION = "2"


@dataclass(frozen=True)
class SearchResult:
    query: str
    searched_at: str
    records: list[dict]
    status: str
    error: str | None = None
    source_status: dict[str, dict] = field(default_factory=dict)


class LiteratureSearchAdapter:
    """Search metadata and abstracts. Neither is automatically treated as learned PDF evidence."""

    def __init__(
        self,
        transport: Callable[[str], dict] | None = None,
        openalex_transport: Callable[[str], dict] | None = None,
        timeout_seconds: int = 20,
        max_attempts: int = 3,
        backoff_base_seconds: float = 0.5,
        max_backoff_seconds: float = 8.0,
        sleep: Callable[[float], None] = time.sleep,
    ):
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1.")
        if backoff_base_seconds < 0 or max_backoff_seconds < 0:
            raise ValueError("Backoff values cannot be negative.")
        self.transport = transport or self._transport
        self.openalex_transport = openalex_transport if openalex_transport is not None else (None if transport is not None else self._transport)
        self.timeout_seconds = timeout_seconds
        self.max_attempts = max_attempts
        self.backoff_base_seconds = backoff_base_seconds
        self.max_backoff_seconds = max_backoff_seconds
        self.sleep = sleep

    def search(self, keywords: list[str], rows: int = 10) -> SearchResult:
        query = " ".join(str(item).strip() for item in keywords if str(item).strip())
        if not query:
            raise ValueError("At least one research keyword is required.")
        searched_at = datetime.now(timezone.utc).isoformat()
        errors: list[str] = []
        records: list[dict] = []
        source_status: dict[str, dict] = {}

        crossref_url = "https://api.crossref.org/works?query.bibliographic={}&rows={}".format(
            quote_plus(query), max(1, min(rows, 50))
        )
        payload, outcome = self._request_with_retry("Crossref", self.transport, crossref_url)
        source_status["Crossref"] = outcome
        if payload is not None:
            records.extend(self._crossref_records(payload))
        else:
            errors.append("Crossref {}".format(outcome["error"]))

        if self.openalex_transport is not None:
            openalex_url = "https://api.openalex.org/works?search={}&per-page={}".format(
                quote_plus(query), max(1, min(rows, 50))
            )
            payload, outcome = self._request_with_retry("OpenAlex", self.openalex_transport, openalex_url)
            source_status["OpenAlex"] = outcome
            if payload is not None:
                records.extend(self._openalex_records(payload))
            else:
                errors.append("OpenAlex {}".format(outcome["error"]))
        else:
            source_status["OpenAlex"] = {"attempts": 0, "status": "disabled", "error": None}

        deduplicated = []
        seen = set()
        for record in records:
            identity = record.get("doi") or record.get("openalex_id") or record["title"].casefold()
            if identity in seen:
                continue
            seen.add(identity)
            deduplicated.append(record)
        status = "LITERATURE_SEARCHED" if deduplicated and not errors else "SEARCH_PARTIAL" if deduplicated or errors else "LITERATURE_SEARCHED"
        return SearchResult(
            query=query,
            searched_at=searched_at,
            records=deduplicated,
            status=status,
            error=" | ".join(errors) or None,
            source_status=source_status,
        )

    def _request_with_retry(
        self,
        source: str,
        transport: Callable[[str], dict],
        url: str,
    ) -> tuple[dict | None, dict]:
        for attempt in range(1, self.max_attempts + 1):
            try:
                return transport(url), {"attempts": attempt, "status": "success", "error": None}
            except Exception as error:
                final_error = "{}: {}".format(type(error).__name__, error)
                should_retry = attempt < self.max_attempts and self._is_retryable(error)
                delay = self._retry_delay(error, attempt) if should_retry else None
                if isinstance(error, HTTPError):
                    error.close()
                if not should_retry:
                    return None, {"attempts": attempt, "status": "error", "error": final_error}
                self.sleep(delay if delay is not None else 0.0)
        raise AssertionError("Retry loop exited unexpectedly for {}".format(source))

    @staticmethod
    def _is_retryable(error: Exception) -> bool:
        if isinstance(error, HTTPError):
            return error.code in RETRYABLE_HTTP_STATUSES
        return isinstance(error, (TimeoutError, ConnectionError, socket.timeout, URLError))

    def _retry_delay(self, error: Exception, failed_attempt: int) -> float:
        retry_after = self._retry_after_seconds(error)
        delay = retry_after if retry_after is not None else self.backoff_base_seconds * (2 ** (failed_attempt - 1))
        return min(delay, self.max_backoff_seconds)

    @staticmethod
    def _retry_after_seconds(error: Exception) -> float | None:
        if not isinstance(error, HTTPError) or error.headers is None:
            return None
        value = error.headers.get("Retry-After")
        if value is None:
            return None
        try:
            seconds = float(value.strip())
        except (AttributeError, TypeError, ValueError):
            return None
        return max(0.0, seconds)

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
