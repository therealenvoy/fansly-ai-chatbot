"""Governed PDF ingestion and compact, source-backed knowledge retrieval."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import io
import re
from typing import Iterable

from pypdf import PdfReader


MAX_PDF_BYTES = 25 * 1024 * 1024
MAX_PAGES = 1_000
MIN_PAGE_TEXT = 24
TOKEN_RE = re.compile(r"[a-z0-9']{2,}", re.IGNORECASE)


class KnowledgeIngestionError(ValueError):
    """A privacy-safe operator error for invalid or unreadable uploads."""


@dataclass(frozen=True)
class ExtractedPage:
    page_number: int
    content: str
    fingerprint: str
    quality: float
    unreadable: bool


@dataclass(frozen=True)
class ExtractedDocument:
    name: str
    mime_type: str
    fingerprint: str
    pages: tuple[ExtractedPage, ...]
    status: str
    report: dict

    @property
    def content(self) -> str:
        return "\n\n".join(page.content for page in self.pages if page.content)


def _normalize_text(value: object) -> str:
    text = str(value or "").replace("\x00", " ")
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def extract_pdf(
    payload: bytes,
    *,
    filename: str,
    mime_type: str = "application/pdf",
) -> ExtractedDocument:
    """Extract text page-by-page without OCR or unrestricted raw persistence."""
    if not isinstance(payload, bytes) or not payload:
        raise KnowledgeIngestionError("Select a non-empty PDF")
    if len(payload) > MAX_PDF_BYTES:
        raise KnowledgeIngestionError("PDF must be 25 MB or smaller")
    safe_name = str(filename or "").strip()[:256]
    if not safe_name.lower().endswith(".pdf"):
        raise KnowledgeIngestionError("Only PDF playbooks are supported")
    normalized_mime = str(mime_type or "").split(";", 1)[0].strip().lower()
    if normalized_mime not in {"application/pdf", "application/octet-stream"}:
        raise KnowledgeIngestionError("File type does not match PDF")
    if not payload.startswith(b"%PDF-"):
        raise KnowledgeIngestionError("The uploaded file is not a valid PDF")
    try:
        # Real operator playbooks frequently contain harmless producer quirks.
        # Lenient parsing still fails closed when no page has extractable text.
        reader = PdfReader(io.BytesIO(payload), strict=False)
    except Exception as error:
        raise KnowledgeIngestionError("The PDF could not be read") from error
    if len(reader.pages) > MAX_PAGES:
        raise KnowledgeIngestionError("PDF has more than 1,000 pages")

    pages: list[ExtractedPage] = []
    unreadable_pages: list[int] = []
    for index, page in enumerate(reader.pages, start=1):
        try:
            content = _normalize_text(page.extract_text())
        except Exception:
            content = ""
        readable = len(content) >= MIN_PAGE_TEXT
        if not readable:
            unreadable_pages.append(index)
        quality = min(1.0, len(content) / 800.0) if readable else 0.0
        pages.append(
            ExtractedPage(
                page_number=index,
                content=content,
                fingerprint=hashlib.sha256(content.encode("utf-8")).hexdigest(),
                quality=round(quality, 4),
                unreadable=not readable,
            )
        )
    readable_pages = len(pages) - len(unreadable_pages)
    if not pages or readable_pages == 0:
        raise KnowledgeIngestionError(
            "The PDF has no extractable text; OCR is not performed automatically"
        )
    ratio = readable_pages / len(pages)
    status = "complete" if ratio >= 0.9 else "needs_review"
    return ExtractedDocument(
        name=safe_name,
        mime_type="application/pdf",
        fingerprint=hashlib.sha256(payload).hexdigest(),
        pages=tuple(pages),
        status=status,
        report={
            "page_count": len(pages),
            "readable_pages": readable_pages,
            "unreadable_pages": unreadable_pages[:100],
            "readable_ratio": round(ratio, 4),
            "ocr_used": False,
        },
    )


def tokenize(*values: object) -> set[str]:
    return {
        token.lower()
        for value in values
        for token in TOKEN_RE.findall(str(value or ""))
    }


def lexical_score(query: Iterable[str], text: object) -> float:
    query_tokens = set(query)
    if not query_tokens:
        return 0.0
    document_tokens = tokenize(text)
    return len(query_tokens & document_tokens) / max(1, len(query_tokens))
