"""Local, page-addressable PDF extraction without sending originals off-device."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
from typing import Iterable

import pymupdf

from .models import SourceDocument, SourceSpan


_FIGURE_PATTERN = re.compile(r"\b(?:fig(?:ure)?\.?\s*)(\d+[A-Za-z]?)", re.IGNORECASE)
_PAGE_LABEL_PATTERN = re.compile(r"(?<!\d)(\d{1,4})(?!\d)")


@dataclass(frozen=True)
class PdfReadResult:
    document: SourceDocument
    spans: tuple[SourceSpan, ...]


class LocalPdfReader:
    """Extract every text block while preserving original PDF page coordinates."""

    def read(self, path: Path | str, project_id: str = "unassigned") -> PdfReadResult:
        source = Path(path)
        if not source.is_file():
            raise ValueError("PDF file does not exist: {}".format(source.name))
        raw = source.read_bytes()
        if not raw.startswith(b"%PDF"):
            raise ValueError("Selected file is not a PDF: {}".format(source.name))
        digest = hashlib.sha256(raw).hexdigest()
        project_source_hash = hashlib.sha256(
            "{}:{}".format(project_id, digest).encode("utf-8")
        ).hexdigest()
        source_id = "source-" + project_source_hash[:24]
        try:
            pdf = pymupdf.open(source)
        except Exception as error:
            raise ValueError("PDF cannot be opened: {}".format(source.name)) from error
        try:
            if pdf.is_encrypted:
                raise ValueError("Encrypted PDFs require researcher-provided access before extraction.")
            spans: list[SourceSpan] = []
            text_pages: list[int] = []
            empty_pages: list[int] = []
            figure_pages: list[int] = []
            for page_number, page in enumerate(pdf, start=1):
                blocks = page.get_text("blocks", sort=True)
                page_text = page.get_text("text", sort=True).strip()
                if page_text:
                    text_pages.append(page_number)
                else:
                    empty_pages.append(page_number)
                page_label = self._page_label(page_text)
                for block_number, block in enumerate(blocks, start=1):
                    text = str(block[4]).strip()
                    if not text:
                        continue
                    figure_ids = tuple("Fig. {}".format(item) for item in _FIGURE_PATTERN.findall(text))
                    if figure_ids and page_number not in figure_pages:
                        figure_pages.append(page_number)
                    block_type = "figure_caption" if figure_ids else "text"
                    text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
                    spans.append(
                        SourceSpan(
                            span_id="span-{}-{:04d}-{:04d}".format(project_source_hash[:16], page_number, block_number),
                            source_id=source_id,
                            page_index=page_number,
                            page_label=page_label,
                            block_type=block_type,
                            text=text,
                            text_hash=text_hash,
                            bbox=tuple(float(value) for value in block[:4]),
                            figure_ids=figure_ids,
                        )
                    )
            extraction_status = "complete" if len(text_pages) == len(pdf) else "partial"
            document = SourceDocument(
                source_id=source_id,
                project_id=project_id,
                sha256=digest,
                original_name=source.name,
                mime="application/pdf",
                page_count=len(pdf),
                extraction_status=extraction_status,
                coverage_manifest={
                    "page_count": len(pdf),
                    "text_pages": text_pages,
                    "empty_or_scanned_pages": empty_pages,
                    "needs_ocr": bool(empty_pages),
                    "figure_caption_pages": figure_pages,
                    "supplementary_status": "not_provided",
                    "span_count": len(spans),
                },
            )
            return PdfReadResult(document=document, spans=tuple(spans))
        finally:
            pdf.close()

    @staticmethod
    def file_sha256(path: Path | str) -> str:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()

    @staticmethod
    def _page_label(text: str) -> str | None:
        first_lines: Iterable[str] = text.splitlines()[:6]
        for line in first_lines:
            compact = line.strip()
            if compact.isdigit() and len(compact) <= 4:
                return compact
        match = _PAGE_LABEL_PATTERN.search(text[-300:])
        return match.group(1) if match else None
