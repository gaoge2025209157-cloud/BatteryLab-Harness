"""Bounded full-text and data-evidence extraction for the knowledge assistant.

Downloaded or fetched documents are untrusted data.  The extractor never executes
scripts, follows instructions embedded in papers, or reads browser credentials.
"""

from dataclasses import asdict, dataclass
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from typing import Iterable, List, Optional, Sequence, Tuple
from urllib.request import Request, urlopen


MAX_DOCUMENT_BYTES = 30 * 1024 * 1024
SUPPORTED_LOCAL_TEXT = {".html", ".htm", ".txt", ".md"}
HEAVY_DATA_KEYS = {
    "points",
    "raw_points",
    "raw_data",
    "rows",
    "samples",
    "voltage_points",
    "capacity_points",
    "time_series",
}


def _compact(value: str) -> str:
    return " ".join(str(value or "").split())


def _bounded(text: str, limit: int) -> str:
    text = _compact(text)
    if len(text) <= limit:
        return text
    head = max(0, int(limit * 0.72))
    tail = max(0, limit - head - 30)
    return text[:head] + " … [内容已压缩] … " + text[-tail:]


def _extract_doi(text: str) -> str:
    match = re.search(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", str(text or ""), flags=re.IGNORECASE)
    return match.group(0).rstrip(".,;)\"]}").casefold() if match else ""


@dataclass(frozen=True)
class DocumentEvidence:
    source_id: str
    title: str
    doi: str
    source_uri: str
    evidence_level: str
    background_excerpt: str
    methods_excerpt: str
    figure_table_evidence: Tuple[str, ...]
    body_excerpt: str
    content_hash: str
    limitations: Tuple[str, ...]

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["figure_table_evidence"] = list(self.figure_table_evidence)
        payload["limitations"] = list(self.limitations)
        return payload


@dataclass(frozen=True)
class DataSummary:
    source_path: str
    source_hash: str
    text: str
    omitted_fields: Tuple[str, ...]
    limitations: Tuple[str, ...]

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["omitted_fields"] = list(self.omitted_fields)
        payload["limitations"] = list(self.limitations)
        return payload


class _EvidenceHTMLParser(HTMLParser):
    BLOCK_TAGS = {"p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "figcaption"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks: List[Tuple[str, str]] = []
        self._tag: Optional[str] = None
        self._buffer: List[str] = []
        self._table_depth = 0
        self._table_buffer: List[str] = []
        self._skip_depth = 0
        self.title = ""
        self._in_title = False
        self._title_buffer: List[str] = []

    def handle_starttag(self, tag, attrs):
        tag = tag.casefold()
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag == "title":
            self._in_title = True
            self._title_buffer = []
        if tag == "table":
            self._table_depth += 1
            if self._table_depth == 1:
                self._table_buffer = []
        if self._table_depth:
            if tag in {"tr", "br"}:
                self._table_buffer.append(" | ")
            return
        if tag in self.BLOCK_TAGS:
            if self._tag and self._buffer:
                self.blocks.append((self._tag, _compact(" ".join(self._buffer))))
            self._tag = tag
            self._buffer = []

    def handle_endtag(self, tag):
        tag = tag.casefold()
        if tag in {"script", "style", "noscript", "svg"} and self._skip_depth:
            self._skip_depth -= 1
            return
        if self._skip_depth:
            return
        if tag == "title":
            self._in_title = False
            self.title = _compact(" ".join(self._title_buffer))
        if tag == "table" and self._table_depth:
            self._table_depth -= 1
            if self._table_depth == 0:
                table = _compact(" ".join(self._table_buffer))
                if table:
                    self.blocks.append(("table", table))
                self._table_buffer = []
            return
        if tag == self._tag:
            text = _compact(" ".join(self._buffer))
            if text:
                self.blocks.append((self._tag, text))
            self._tag = None
            self._buffer = []

    def handle_data(self, data):
        if self._skip_depth:
            return
        text = _compact(data)
        if not text:
            return
        if self._in_title:
            self._title_buffer.append(text)
        if self._table_depth:
            self._table_buffer.append(text)
        elif self._tag:
            self._buffer.append(text)


def _section_excerpt(
    blocks: Sequence[Tuple[str, str]],
    heading_terms: Sequence[str],
    limit: int,
) -> str:
    terms = tuple(item.casefold() for item in heading_terms)
    collecting = False
    selected: List[str] = []
    for tag, text in blocks:
        lowered = text.casefold()
        if tag.startswith("h"):
            if collecting and selected:
                break
            collecting = any(term in lowered for term in terms)
            continue
        if collecting and tag in {"p", "li"}:
            selected.append(text)
            if sum(len(item) for item in selected) >= limit:
                break
    return _bounded(" ".join(selected), limit) if selected else ""


def _parameter_rich(text: str) -> bool:
    units = r"(?:mA\s*h\s*g-?1|mAh\s*g-?1|mS\s*cm-?1|S\s*cm-?1|MPa|GPa|kPa|°?C|K|Hz|V|mV|%|cycles?)"
    return bool(re.search(r"\d", text) and re.search(units, text, flags=re.IGNORECASE))


def extract_html_evidence(
    html_text: str,
    *,
    source_uri: str,
    title: str = "",
    doi: str = "",
    max_excerpt_chars: int = 12000,
) -> DocumentEvidence:
    parser = _EvidenceHTMLParser()
    parser.feed(html_text)
    parser.close()
    blocks = parser.blocks
    paragraphs = [text for tag, text in blocks if tag in {"p", "li"}]
    background = _section_excerpt(
        blocks,
        ("introduction", "background", "研究背景", "引言", "绪论"),
        max(1000, max_excerpt_chars // 3),
    )
    if not background:
        background = _bounded(" ".join(paragraphs[:5]), max(1000, max_excerpt_chars // 3))
    methods = _section_excerpt(
        blocks,
        ("method", "experimental", "experiment", "materials and methods", "实验", "方法"),
        max(1000, max_excerpt_chars // 4),
    )
    figures = []
    for tag, text in blocks:
        if tag in {"figcaption", "table"}:
            label = "Figure caption" if tag == "figcaption" else "Table"
            figures.append("{}: {}".format(label, _bounded(text, 1800)))
    rich_paragraphs = [text for tag, text in blocks if tag in {"p", "li"} and _parameter_rich(text)]
    figures.extend("Parameter context: {}".format(_bounded(text, 1200)) for text in rich_paragraphs[:8])
    body = _bounded(" ".join(paragraphs), max_excerpt_chars)
    raw_hash = hashlib.sha256(html_text.encode("utf-8", errors="replace")).hexdigest()
    limitations = []
    if not figures:
        limitations.append("No figure caption, table, or parameter-rich paragraph was extracted from HTML.")
    if not methods:
        limitations.append("No explicit methods section was detected.")
    detected_doi = _compact(doi).casefold() or _extract_doi(html_text)
    return DocumentEvidence(
        source_id=(detected_doi or source_uri),
        title=_compact(title or parser.title or "Untitled document"),
        doi=detected_doi,
        source_uri=source_uri,
        evidence_level="fulltext_html",
        background_excerpt=background,
        methods_excerpt=methods,
        figure_table_evidence=tuple(figures[:20]),
        body_excerpt=body,
        content_hash=raw_hash,
        limitations=tuple(limitations),
    )


def _plain_text_evidence(
    text: str,
    *,
    source_uri: str,
    title: str,
    doi: str = "",
    evidence_level: str,
    limitations: Iterable[str] = (),
) -> DocumentEvidence:
    lines = [_compact(line) for line in text.splitlines() if _compact(line)]
    background_lines = []
    parameter_lines = []
    collecting_background = False
    for line in lines:
        lower = line.casefold()
        if re.match(r"^(?:\d+[. ]*)?(introduction|background|引言|研究背景)", lower):
            collecting_background = True
            continue
        if collecting_background and re.match(
            r"^(?:\d+[. ]*)?(method|experimental|result|方法|实验|结果)", lower
        ):
            collecting_background = False
        if collecting_background:
            background_lines.append(line)
        if re.search(r"(?:figure|fig\.|table|图\s*\d|表\s*\d)", line, flags=re.IGNORECASE) or _parameter_rich(line):
            parameter_lines.append(line)
    if not background_lines:
        background_lines = lines[:10]
    digest = hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()
    detected_doi = _compact(doi).casefold() or _extract_doi(text)
    return DocumentEvidence(
        source_id=detected_doi or source_uri,
        title=title,
        doi=detected_doi,
        source_uri=source_uri,
        evidence_level=evidence_level,
        background_excerpt=_bounded(" ".join(background_lines), 5000),
        methods_excerpt="",
        figure_table_evidence=tuple(_bounded(line, 1600) for line in parameter_lines[:20]),
        body_excerpt=_bounded(" ".join(lines), 12000),
        content_hash=digest,
        limitations=tuple(limitations),
    )


def extract_local_document(path, *, doi: str = "", title: str = "") -> DocumentEvidence:
    source = Path(path).resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    if source.stat().st_size > MAX_DOCUMENT_BYTES:
        raise ValueError("Document exceeds the 30 MiB extraction limit: {}".format(source.name))
    suffix = source.suffix.casefold()
    if suffix in {".html", ".htm"}:
        return extract_html_evidence(
            source.read_text(encoding="utf-8", errors="replace"),
            source_uri=str(source),
            title=title or source.stem,
            doi=doi,
        )
    if suffix in {".txt", ".md"}:
        return _plain_text_evidence(
            source.read_text(encoding="utf-8", errors="replace"),
            source_uri=str(source),
            title=title or source.stem,
            doi=doi,
            evidence_level="local_text",
        )
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader  # optional dependency, never installed automatically
        except ImportError:
            import sys

            local_dependencies = Path(__file__).resolve().parents[2] / ".deps"
            if local_dependencies.is_dir() and str(local_dependencies) not in sys.path:
                sys.path.insert(0, str(local_dependencies))
            try:
                from pypdf import PdfReader
            except ImportError as error:
                raise RuntimeError(
                    "PDF已下载，但缺少pypdf解析组件；请将pypdf安装到项目的.deps目录后重试。"
                ) from error
        reader = PdfReader(str(source))
        text = "\n".join((page.extract_text() or "") for page in reader.pages)
        return _plain_text_evidence(
            text,
            source_uri=str(source),
            title=title or source.stem,
            doi=doi,
            evidence_level="local_pdf_text",
            limitations=("PDF figures are represented only by extractable captions/text; no image interpretation was performed.",),
        )
    raise ValueError("Unsupported document format: {}".format(suffix))


def fetch_publisher_html(
    url: str,
    *,
    title: str = "",
    doi: str = "",
    timeout: int = 30,
) -> DocumentEvidence:
    """Fetch HTML through the current network path; never sends browser cookies."""
    request = Request(
        url,
        headers={
            "Accept": "text/html,application/xhtml+xml",
            "User-Agent": "ElectrochemHarness/0.7 knowledge-assistant",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        content_type = response.headers.get("Content-Type", "")
        if "html" not in content_type.casefold():
            raise ValueError("Publisher response is not HTML: {}".format(content_type))
        raw = response.read(MAX_DOCUMENT_BYTES + 1)
        if len(raw) > MAX_DOCUMENT_BYTES:
            raise ValueError("Publisher HTML exceeds the 8 MiB extraction limit.")
        charset = response.headers.get_content_charset() or "utf-8"
        text = raw.decode(charset, errors="replace")
        final_url = response.geturl()
    return extract_html_evidence(
        text,
        source_uri=final_url,
        title=title,
        doi=doi,
    )


def collect_local_documents(folder, max_documents: int = 10) -> List[DocumentEvidence]:
    if not folder:
        return []
    root = Path(folder).resolve()
    if not root.is_dir():
        raise FileNotFoundError(root)
    candidates = sorted(
        path for path in root.iterdir() if path.is_file() and path.suffix.casefold() in SUPPORTED_LOCAL_TEXT | {".pdf"}
    )
    documents = []
    for path in candidates[: max(0, int(max_documents))]:
        documents.append(extract_local_document(path))
    return documents


def _prune_json(value, omitted: List[str], path: str = ""):
    if isinstance(value, dict):
        output = {}
        for key, item in value.items():
            current = "{}.{}".format(path, key).strip(".")
            if key.casefold() in HEAVY_DATA_KEYS:
                omitted.append(current)
                continue
            output[key] = _prune_json(item, omitted, current)
        return output
    if isinstance(value, list):
        if len(value) > 100:
            omitted.append(path or "large_array")
            return {"omitted_item_count": len(value)}
        return [_prune_json(item, omitted, path) for item in value]
    return value


def summarize_data_file(path, max_chars: int = 12000) -> DataSummary:
    source = Path(path).resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    raw = source.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    text = raw.decode("utf-8-sig", errors="replace")
    omitted: List[str] = []
    limitations = []
    if source.suffix.casefold() == ".json":
        payload = json.loads(text)
        pruned = _prune_json(payload, omitted)
        rendered = json.dumps(pruned, ensure_ascii=False, indent=2, sort_keys=True)
    elif source.suffix.casefold() in {".csv", ".tsv"}:
        lines = text.splitlines()
        if len(lines) > 42:
            omitted.append("middle_rows")
            lines = lines[:21] + ["... {} middle rows omitted ...".format(len(lines) - 42)] + lines[-21:]
        rendered = "\n".join(lines)
        limitations.append("Tabular summary contains only the header and bounded edge rows; use calculated metrics for conclusions.")
    elif source.suffix.casefold() in {".md", ".txt"}:
        rendered = text
    else:
        raise ValueError("Data summary must be JSON, CSV, TSV, Markdown, or TXT.")
    rendered = _bounded(rendered, max_chars)
    if len(text) > max_chars:
        limitations.append("Source was compressed before LLM transmission.")
    return DataSummary(
        source_path=str(source),
        source_hash=digest,
        text=rendered,
        omitted_fields=tuple(dict.fromkeys(omitted)),
        limitations=tuple(limitations),
    )
