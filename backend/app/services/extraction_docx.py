"""DOCX text extraction.

python-docx is used rather than unzipping and parsing the XML by hand, because it
already resolves styles, numbering and merged cells.

Heading levels come from real `Heading N` styles, which is genuine structure
rather than a guess -- the reason DOCX sections are better labelled than PDF ones.

**page_number is None for every DOCX chunk.** A .docx has no fixed pagination;
where pages fall depends on the reader, the font substitutions and the paper size.
The spec offers an explicit `w:br w:type="page"` as a page signal, but most
documents contain none, so counting them would label page 9 of a 15-page handbook
as "page 1" -- a confidently wrong citation, which AGENTS.md section 5 forbids. A
citation that shows no page is better than one that shows the wrong page.
"""

from __future__ import annotations

import io
import re
from typing import Any

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph

from app.services.extraction import (
    ExtractedDocument,
    ExtractedPage,
    ExtractionError,
    TextBlock,
    heading_level_from_text,
    looks_like_column_labels,
    render_labelled_row,
)
from app.services.filetypes import UnsupportedFileError, validate_file_bytes

_HEADING_STYLE = re.compile(r"^heading\s+(\d+)$", re.IGNORECASE)
_TITLE_STYLES = frozenset({"title", "subtitle"})
# WordprocessingML namespace, for identifying body children.
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_MAX_HEADING_LEVEL = 3


def extract_docx(data: bytes, *, max_uncompressed_bytes: int) -> ExtractedDocument:
    """Extract text from DOCX bytes as a single unpaginated page."""
    # Re-checked here as well as at upload: a .docx is a ZIP, and python-docx will
    # happily expand a zip bomb handed to it. Cheap insurance against a document
    # that reached Storage before this check existed.
    try:
        validate_file_bytes(data, "docx", max_uncompressed_bytes=max_uncompressed_bytes)
    except UnsupportedFileError as exc:
        raise ExtractionError(str(exc)) from exc

    try:
        document = Document(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001 - python-docx raises several unrelated types
        raise ExtractionError("The file could not be opened as a Word document.") from exc

    blocks: list[TextBlock] = []
    # Iterating the body's children directly is the only way to keep paragraphs and
    # tables in their true order. document.paragraphs and document.tables each
    # return one kind, so a table would drift to the end of its section.
    for child in document.element.body.iterchildren():
        if child.tag == f"{_W}p":
            blocks.extend(_paragraph_blocks(Paragraph(child, document)))
        elif child.tag == f"{_W}tbl":
            blocks.extend(_table_blocks(Table(child, document)))

    return ExtractedDocument(
        pages=[ExtractedPage(page_number=None, blocks=blocks)],
        # Unpaginated, so there is no page count to report.
        page_count=None,
    )


def _paragraph_blocks(paragraph: Paragraph) -> list[TextBlock]:
    text = paragraph.text.strip()
    if not text:
        return []

    level = _style_level(paragraph)
    if level is None:
        # A document that fakes headings with bold text has no style to read, so
        # fall back to the same numbering patterns the PDF extractor uses.
        level = heading_level_from_text(text)
    if level is None:
        return [TextBlock(text=text, kind="paragraph")]
    return [TextBlock(text=text, kind="heading", heading_level=level)]


def _style_level(paragraph: Paragraph) -> int | None:
    try:
        name = (paragraph.style.name or "").strip()
    except Exception:  # noqa: BLE001 - a broken style reference must not fail extraction
        return None

    if name.casefold() in _TITLE_STYLES:
        return 1
    match = _HEADING_STYLE.match(name)
    if match:
        return min(int(match.group(1)), _MAX_HEADING_LEVEL)
    return None


def _table_blocks(table: Table) -> list[TextBlock]:
    rows = [_row_values(row) for row in table.rows]
    rows = [row for row in rows if any(row)]
    if not rows:
        return []

    if len(rows) == 1 or not looks_like_column_labels(rows[0]):
        return [TextBlock(text=" | ".join(row), kind="table_row") for row in rows]

    labels = rows[0]
    blocks = [TextBlock(text=" | ".join(labels), kind="paragraph")]
    for row in rows[1:]:
        rendered = render_labelled_row(labels, row)
        blocks.append(TextBlock(text=rendered or " | ".join(row), kind="table_row"))
    return blocks


def _row_values(row: Any) -> list[str]:
    """A table row's cell texts, with merged cells collapsed.

    python-docx returns the *same* cell object once per grid position a merged
    cell spans, so a two-column merge appears twice. Comparing the underlying
    element is exact, where de-duplicating equal strings would also collapse two
    columns that legitimately hold the same value.
    """
    values: list[str] = []
    previous: Any = None
    for cell in row.cells:
        if cell._tc is previous:
            continue
        previous = cell._tc
        values.append(cell.text.strip())
    return values
