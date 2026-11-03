"""Persistent, DOI-keyed paper PDF library for the research workflow.

Only direct HTTP(S) PDF links returned by scholarly metadata services are fetched.
No browser cookie, campus credential, API key, or paywall bypass is used.  Every
successful file is validated by its PDF signature, hashed, indexed atomically, and
reused on later runs instead of being downloaded again.
"""

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import html
import ipaddress
import json
from pathlib import Path
import re
from typing import Callable, Iterable, List, Mapping, Sequence
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen


MAX_PDF_BYTES = 50 * 1024 * 1024


def _clean(value) -> str:
    return " ".join(str(value or "").split())


def _doi(value) -> str:
    return re.sub(r"^https?://(?:dx\.)?doi\.org/", "", _clean(value).casefold()).rstrip(".,;)")


def _safe_filename(doi: str, title: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", title).strip("._")[:80] or "paper"
    identity = hashlib.sha256(doi.encode("utf-8")).hexdigest()[:12]
    return "{}_{}.pdf".format(identity, stem)


def _public_http_url(url: str) -> bool:
    parsed = urlparse(_clean(url))
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    host = parsed.hostname.casefold()
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return True
    return not (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
    )


def candidate_pdf_urls(record: Mapping) -> tuple:
    values = []
    for value in record.get("pdf_urls", ()) or ():
        if _public_http_url(value) and value not in values:
            values.append(_clean(value))
    single = _clean(record.get("pdf_url"))
    if _public_http_url(single) and single not in values:
        values.append(single)
    return tuple(values)


def _repository_landing_urls(record: Mapping) -> tuple:
    values = []
    for value in record.get("fulltext_landing_urls", ()) or ():
        cleaned = _clean(value)
        if _public_http_url(cleaned) and cleaned not in values:
            values.append(cleaned)
    return tuple(values)


def _discover_repository_pdf_urls(url: str, timeout: int = 15) -> tuple:
    """Read a public repository landing page and return declared PDF links."""

    request = Request(
        url,
        headers={
            "Accept": "text/html,application/pdf;q=0.9",
            "User-Agent": "ElectrochemHarness/0.7 paper-library",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        raw = response.read(2 * 1024 * 1024 + 1)
        final_url = response.geturl()
        content_type = _clean(response.headers.get("Content-Type") or "").casefold()
    if len(raw) > 2 * 1024 * 1024:
        return ()
    if b"%PDF-" in raw[:1024] or "application/pdf" in content_type:
        return (final_url,) if _public_http_url(final_url) else ()
    text = html.unescape(raw.decode("utf-8", errors="replace"))
    found = []
    patterns = (
        r'<meta[^>]+(?:name|property)=["\'](?:citation_pdf_url|og:pdf)["\'][^>]+content=["\']([^"\']+)',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:name|property)=["\'](?:citation_pdf_url|og:pdf)["\']',
        r'<a[^>]+href=["\']([^"\']+(?:\.pdf(?:\?[^"\']*)?|/download(?:\?[^"\']*)?))["\']',
    )
    for pattern in patterns:
        for match in re.findall(pattern, text, flags=re.IGNORECASE):
            candidate = urljoin(final_url, _clean(match))
            if _public_http_url(candidate) and candidate not in found:
                found.append(candidate)
    return tuple(found[:8])


@dataclass(frozen=True)
class PaperAcquisition:
    doi: str
    title: str
    journal: str
    year: object
    landing_url: str
    pdf_url: str
    status: str
    local_path: str = ""
    sha256: str = ""
    size_bytes: int = 0
    detail: str = ""

    def to_dict(self, *, public: bool = False) -> dict:
        payload = asdict(self)
        if public and payload["local_path"]:
            payload["local_path"] = Path(payload["local_path"]).name
        return payload


class PaperLibrary:
    """Download and remember one local PDF per DOI."""

    def __init__(self, root):
        self.root = Path(root).resolve()
        self.pdf_dir = self.root / "pdfs"
        self.index_path = self.root / "download_index.json"

    def _load_index(self) -> dict:
        if not self.index_path.is_file():
            return {"version": 1, "papers": {}}
        try:
            payload = json.loads(self.index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"version": 1, "papers": {}}
        if not isinstance(payload, dict) or not isinstance(payload.get("papers"), dict):
            return {"version": 1, "papers": {}}
        return payload

    def _write_index(self, payload: Mapping) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = self.index_path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.index_path)

    def _cached(self, record: Mapping, entry: Mapping) -> PaperAcquisition | None:
        filename = _clean(entry.get("filename"))
        path = self.pdf_dir / filename
        if not filename or not path.is_file():
            return None
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if b"%PDF-" not in raw[:1024] or digest != _clean(entry.get("sha256")):
            return None
        return PaperAcquisition(
            doi=_doi(record.get("doi")),
            title=_clean(record.get("title")),
            journal=_clean(record.get("journal")),
            year=record.get("year"),
            landing_url=_clean(record.get("landing_url")),
            pdf_url=_clean(entry.get("pdf_url")),
            status="cached",
            local_path=str(path),
            sha256=digest,
            size_bytes=len(raw),
            detail="已存在本地PDF，本轮未重复下载",
        )

    @staticmethod
    def _download(url: str, timeout: int = 20) -> bytes:
        request = Request(
            url,
            headers={
                "Accept": "application/pdf",
                "User-Agent": "ElectrochemHarness/0.7 paper-library",
            },
        )
        with urlopen(request, timeout=timeout) as response:
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > MAX_PDF_BYTES:
                raise ValueError("PDF超过50 MiB限制")
            raw = response.read(MAX_PDF_BYTES + 1)
        if len(raw) > MAX_PDF_BYTES:
            raise ValueError("PDF超过50 MiB限制")
        if b"%PDF-" not in raw[:1024]:
            preview = raw[:4096].decode("utf-8", errors="ignore").casefold()
            if any(marker in preview for marker in ("captcha", "just a moment", "bot manager", "cloudflare")):
                raise ValueError("出版社返回反爬验证页，程序不会绕过；请在浏览器中通过校园网下载")
            raise ValueError("服务器返回的不是PDF文件")
        return raw

    def acquire(
        self,
        records: Sequence[Mapping],
        *,
        downloader: Callable[[str], bytes] | None = None,
    ) -> List[PaperAcquisition]:
        """Acquire selected papers in order, reusing valid indexed files."""

        download = downloader or self._download
        index = self._load_index()
        papers = dict(index.get("papers") or {})
        results: List[PaperAcquisition] = []
        changed = False
        for record in records:
            doi = _doi(record.get("doi"))
            base = {
                "doi": doi,
                "title": _clean(record.get("title")),
                "journal": _clean(record.get("journal")),
                "year": record.get("year"),
                "landing_url": _clean(record.get("landing_url")),
            }
            cached = self._cached(record, papers.get(doi, {})) if doi else None
            if cached is not None:
                results.append(cached)
                continue
            urls = list(candidate_pdf_urls(record))
            discovery_errors = []
            for landing_url in _repository_landing_urls(record):
                try:
                    for discovered in _discover_repository_pdf_urls(landing_url):
                        if discovered not in urls:
                            urls.append(discovered)
                except Exception as error:
                    discovery_errors.append("仓储{}: {}".format(urlparse(landing_url).netloc, error))
            if not urls:
                results.append(
                    PaperAcquisition(
                        **base,
                        pdf_url="",
                        status="unavailable",
                        detail=(
                            "元数据及机构仓储均未提供可直接下载的PDF；可通过校园网手动下载后放入原文目录"
                            + ("；" + "；".join(discovery_errors)[:400] if discovery_errors else "")
                        ),
                    )
                )
                continue
            errors = list(discovery_errors)
            acquired = None
            for url in urls:
                try:
                    raw = download(url)
                    if len(raw) > MAX_PDF_BYTES or b"%PDF-" not in raw[:1024]:
                        raise ValueError("下载内容不是有效PDF或超过大小限制")
                    self.pdf_dir.mkdir(parents=True, exist_ok=True)
                    filename = _safe_filename(doi, base["title"])
                    destination = self.pdf_dir / filename
                    temporary = destination.with_suffix(".pdf.part")
                    temporary.write_bytes(raw)
                    temporary.replace(destination)
                    digest = hashlib.sha256(raw).hexdigest()
                    papers[doi] = {
                        "doi": doi,
                        "title": base["title"],
                        "journal": base["journal"],
                        "year": base["year"],
                        "filename": filename,
                        "pdf_url": url,
                        "sha256": digest,
                        "size_bytes": len(raw),
                        "downloaded_at": datetime.now(timezone.utc).isoformat(),
                    }
                    changed = True
                    acquired = PaperAcquisition(
                        **base,
                        pdf_url=url,
                        status="downloaded",
                        local_path=str(destination),
                        sha256=digest,
                        size_bytes=len(raw),
                        detail="本轮已下载并写入DOI去重索引",
                    )
                    break
                except Exception as error:  # one URL failure must not hide other legal locations
                    errors.append("{}: {}".format(urlparse(url).netloc or "URL", error))
            results.append(
                acquired
                or PaperAcquisition(
                    **base,
                    pdf_url=urls[0],
                    status="failed",
                    detail="；".join(errors)[:800] or "PDF下载失败",
                )
            )
        if changed:
            self._write_index(
                {
                    "version": 1,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                    "papers": papers,
                }
            )
        return results
