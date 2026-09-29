"""Shared types for text extraction, and the dispatcher.

The pipeline is a chain of pure functions over plain data:

    bytes -> extract -> [ExtractedPage] -> clean -> chunk -> embed

`page_number` lives on the page rather than on the finished chunk, which is what
makes per-page citation exact instead of approximate: a chunk can span a page
break, and its citation must name the page the text actually starts on.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal, Protocol

from app.config import Settings

# `table_row` is separate from `paragraph` because the chunker must never split a
# row: half a fee table is worse than no fee table.
BlockKind = Literal["heading", "paragraph", "table_row"]

# A column label is short and carries no data value.
_LABEL_MAX_CHARS = 40

# "1. Introduction", "2.3. Fees".
_NUMBERED_HEADING = re.compile(r"^(\d+(?:\.\d+)*)\.\s+\S")
# "2.3 Fees" -- dotted numbering with no trailing period. Deliberately does not
# match a sentence that merely starts with a number, such as "500 rupees is due":
# that needs either a period after the number or a dotted number.
_DOTTED_HEADING = re.compile(r"^(\d+(?:\.\d+)+)\s+\S")
# "Section 4", "Appendix II", "Schedule 3".
_WORD_HEADING = re.compile(
    r"^(?:section|chapter|appendix|annexure|schedule|part)\s+[0-9ivxl]+\b",
    re.IGNORECASE,
)


def heading_level_from_text(text: str) -> int | None:
    """Heading level implied by a numbering or section-word pattern, else None.

    Shared by the PDF and DOCX extractors: a numbered heading is a heading in
    either format, and only PDFs additionally get a font-size signal.
    """
    numbered = _NUMBERED_HEADING.match(text) or _DOTTED_HEADING.match(text)
    if numbered:
        return min(numbered.group(1).count(".") + 1, 3)
    if _WORD_HEADING.match(text):
        return 2
    return None


def looks_like_column_labels(cells: Sequence[str]) -> bool:
    """Whether a row reads as column headings rather than data.

    Short and digit-free. Without this check a headerless table would have its
    first data row mistaken for labels, producing the nonsense
    "Semester 1: Semester 2".
    """
    for cell in cells:
        text = cell.strip()
        if not text or len(text) > _LABEL_MAX_CHARS or any(char.isdigit() for char in text):
            return False
    return True


def render_labelled_row(labels: Sequence[str], values: Sequence[str]) -> str:
    """Render a table row as "Date: 12 December 2026; Fee: 500".

    Self-describing on purpose: a bare row loses its meaning as soon as the
    chunker separates it from the header, and FR-3 requires dates and rules to
    stay readable.
    """
    pairs = [
        f"{label}: {value.strip()}"
        # strict=False on purpose: a row with fewer cells than the header is
        # normal (a trailing blank cell is often not extracted at all), and those
        # labels simply have no value to pair with.
        for label, value in zip(labels, values, strict=False)
        if value.strip()
    ]
    return "; ".join(pairs)


class ExtractionError(Exception):
    """Raised when a file cannot be read at all.

    Distinct from "read successfully but found no text": that is a scanned
    document and is flagged, not failed.
    """


@dataclass(frozen=True)
class TextBlock:
    """One indivisible unit of extracted text."""

    text: str
    kind: BlockKind = "paragraph"
    # 1-3 for a heading; None for everything else.
    heading_level: int | None = None


@dataclass
class ExtractedPage:
    """The blocks read from one page.

    `page_number` is None for formats with no fixed pagination (DOCX), and for
    text files with no page separators. It is never invented -- a fabricated page
    number in a citation is exactly what AGENTS.md section 5 forbids.
    """

    page_number: int | None
    blocks: list[TextBlock] = field(default_factory=list)

    @property
    def char_count(self) -> int:
        return sum(len(block.text) for block in self.blocks)

    @property
    def text(self) -> str:
        return "\n".join(block.text for block in self.blocks)


@dataclass
class ExtractedDocument:
    pages: list[ExtractedPage]
    # What the format reports, or None when it reports nothing. For a PDF this is
    # the declared page count, which can exceed len(pages) if a page failed.
    page_count: int | None = None

    @property
    def char_count(self) -> int:
        return sum(page.char_count for page in self.pages)

    @property
    def text(self) -> str:
        return "\n\n".join(page.text for page in self.pages if page.text)


class TextExtractor(Protocol):
    """Sync on purpose: the orchestrator owns the thread hop.

    Extraction is CPU-bound, so it runs in a worker thread via
    anyio.to_thread.run_sync. Making the protocol async would invite an
    implementation that blocks the event loop instead.
    """

    def extract(self, data: bytes) -> ExtractedDocument: ...


def is_low_text_yield(
    document: ExtractedDocument,
    *,
    min_chars_per_page: int,
    page_ratio: float,
) -> bool:
    """Whether extraction found almost no text.

    In practice this means a scanned document with no text layer. PRD section 10
    asks for such documents to be *flagged*, not rejected, so this is a signal for
    the admin rather than a failure.
    """
    if document.char_count == 0:
        return True

    numbered_pages = [page for page in document.pages if page.page_number is not None]
    if not numbered_pages:
        # No fixed pagination to judge per page, so judge the body as a whole.
        return document.char_count < min_chars_per_page

    sparse = sum(1 for page in numbered_pages if page.char_count < min_chars_per_page)
    return sparse / len(numbered_pages) >= page_ratio


def extract_document(data: bytes, file_type: str, settings: Settings) -> ExtractedDocument:
    """Dispatch to the extractor for `file_type`.

    Imports are local so that a missing optional extractor for one format cannot
    break the others -- and so importing this module stays cheap.
    """
    normalised = file_type.strip().lstrip(".").lower()

    if normalised == "pdf":
        from app.services.extraction_pdf import extract_pdf

        return extract_pdf(data, max_pages=settings.max_document_pages)

    if normalised == "docx":
        from app.services.extraction_docx import extract_docx

        return extract_docx(data, max_uncompressed_bytes=settings.max_archive_uncompressed_bytes)

    if normalised == "txt":
        from app.services.extraction_txt import extract_txt

        return extract_txt(data)

    raise ExtractionError(f"No extractor is available for '{file_type}' files.")
