"""PDF text extraction with page numbers, headings and table rows.

PyMuPDF is used from a stream so the uploaded bytes never touch the filesystem.

**Tables are reconstructed geometrically, not with `page.find_tables()`.**
find_tables is heuristic layout analysis: on a plainly ruled three-column table it
detected only two columns and silently dropped every value in the third. A table
that renders with a missing column is worse than one that renders as loose rows,
because nothing indicates anything is absent. It also pushes toward installing the
separate `pymupdf_layout` package. Grouping lines by baseline and sorting by x
recovers the same information with no new dependency and no silent data loss.

Known limitation: on a genuinely multi-column *page layout* (a newsletter rather
than a table), lines from adjacent columns that share a baseline will be grouped
into one row. College handbooks, notices and fee circulars are single-column.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import pymupdf

from app.services.extraction import (
    ExtractedDocument,
    ExtractedPage,
    ExtractionError,
    TextBlock,
    heading_level_from_text,
    looks_like_column_labels,
    render_labelled_row,
)

# Two lines whose vertical centres are within this many points are one row.
_ROW_TOLERANCE_PT = 2.0
# A horizontal gap wider than this between two runs of text means separate
# columns, not one wrapped line. Smaller gaps are joined back together.
_COLUMN_GAP_PT = 8.0
# A single-column line this many characters or longer is body text, never a heading.
_HEADING_MAX_CHARS = 120
# A line set at least this much larger than the page's body text is a heading.
_HEADING_SIZE_RATIO = 1.15
# Above this ratio it is a top-level heading rather than a subheading.
_HEADING_LEVEL1_RATIO = 1.6

_SENTENCE_END = (".", "?", "!", ";", ",")


@dataclass(frozen=True)
class _Cell:
    """A run of text with a horizontal extent, on one baseline."""

    text: str
    size: float
    x0: float
    x1: float
    y: float


@dataclass
class _Row:
    """Cells sharing a baseline, left to right."""

    cells: list[_Cell] = field(default_factory=list)

    @property
    def y(self) -> float:
        return self.cells[0].y if self.cells else 0.0

    @property
    def is_grid(self) -> bool:
        """Whether this row has more than one column."""
        return len(self.cells) > 1

    @property
    def text(self) -> str:
        return " | ".join(cell.text for cell in self.cells)


def extract_pdf(data: bytes, *, max_pages: int) -> ExtractedDocument:
    """Extract text from PDF bytes, one ExtractedPage per page."""
    try:
        document = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:  # noqa: BLE001 - PyMuPDF raises several unrelated types
        raise ExtractionError("The file could not be opened as a PDF.") from exc

    with document:
        if document.needs_pass:
            raise ExtractionError("The PDF is password protected and cannot be read.")
        if document.page_count == 0:
            raise ExtractionError("The PDF has no pages.")
        if document.page_count > max_pages:
            raise ExtractionError(
                f"The PDF has {document.page_count} pages, above the limit of {max_pages}."
            )

        toc_levels = _toc_levels(document)
        pages = [
            ExtractedPage(
                page_number=index + 1,
                blocks=_page_blocks(document.load_page(index), toc_levels.get(index + 1, {})),
            )
            for index in range(document.page_count)
        ]
        return ExtractedDocument(pages=pages, page_count=document.page_count)


def _toc_levels(document: pymupdf.Document) -> dict[int, dict[str, int]]:
    """Map page number -> {normalised heading text: level} from the PDF outline.

    Real bookmarks beat any font-size heuristic, so when a PDF has them they win.
    """
    levels: dict[int, dict[str, int]] = {}
    try:
        toc = document.get_toc()
    except Exception:  # noqa: BLE001 - a malformed outline must not fail extraction
        return levels

    for entry in toc:
        if len(entry) < 3:
            continue
        level, title, page = entry[0], entry[1], entry[2]
        if not isinstance(page, int) or page < 1 or not title:
            continue
        levels.setdefault(page, {})[_normalise_heading(str(title))] = max(1, min(int(level), 3))
    return levels


def _page_blocks(
    page: pymupdf.Page,
    toc_levels: dict[str, int],
) -> list[TextBlock]:
    try:
        raw = page.get_text("dict", sort=True)
    except Exception as exc:  # noqa: BLE001 - one unreadable page must not fail the document
        raise ExtractionError(f"Page {page.number + 1} could not be read.") from exc

    cells = _cells_from(raw)
    if not cells:
        # No text layer at all: a scanned page. Zero blocks is the honest result,
        # and is what drives the low-yield flag.
        return []

    modal_size = _modal_size(cells)
    rows = _group_rows(cells)

    blocks: list[TextBlock] = []
    index = 0
    while index < len(rows):
        row = rows[index]
        if not row.is_grid:
            blocks.append(_text_block(row.cells[0], toc_levels, modal_size))
            index += 1
            continue

        # Gather consecutive rows of the same width: that is one table.
        width = len(row.cells)
        run = [row]
        cursor = index + 1
        while cursor < len(rows) and rows[cursor].is_grid and len(rows[cursor].cells) == width:
            run.append(rows[cursor])
            cursor += 1

        blocks.extend(_table_blocks(run))
        index = cursor

    return blocks


def _cells_from(raw: dict) -> list[_Cell]:
    """Flatten the `dict` export into one _Cell per visual line."""
    cells: list[_Cell] = []
    for block in raw.get("blocks", []):
        if block.get("type") != 0:
            continue  # images carry no text
        for line in block.get("lines", []):
            spans = [span for span in line.get("spans", []) if span.get("text", "").strip()]
            if not spans:
                continue
            text = "".join(span["text"] for span in spans).strip()
            if not text:
                continue
            bbox = line["bbox"]
            cells.append(
                _Cell(
                    text=text,
                    size=max(float(span["size"]) for span in spans),
                    x0=min(float(span["bbox"][0]) for span in spans),
                    x1=max(float(span["bbox"][2]) for span in spans),
                    y=(float(bbox[1]) + float(bbox[3])) / 2,
                )
            )
    return cells


def _group_rows(cells: list[_Cell]) -> list[_Row]:
    """Bucket cells into baselines, splitting wrapped text back into one cell."""
    rows: list[_Row] = []
    for cell in sorted(cells, key=lambda cell: (cell.y, cell.x0)):
        if rows and abs(cell.y - rows[-1].y) <= _ROW_TOLERANCE_PT:
            rows[-1].cells.append(cell)
        else:
            rows.append(_Row(cells=[cell]))

    for row in rows:
        row.cells = _join_wrapped(row.cells)
    return rows


def _join_wrapped(cells: list[_Cell]) -> list[_Cell]:
    """Re-join text runs that are contiguous, keeping real column gaps separate.

    A single sentence can be exported as several spans with tiny or negative gaps;
    those are one cell. A gap wider than _COLUMN_GAP_PT is a column boundary.
    """
    joined: list[_Cell] = []
    for cell in sorted(cells, key=lambda cell: cell.x0):
        if joined and cell.x0 - joined[-1].x1 <= _COLUMN_GAP_PT:
            previous = joined[-1]
            joined[-1] = _Cell(
                text=f"{previous.text} {cell.text}",
                size=max(previous.size, cell.size),
                x0=previous.x0,
                x1=max(previous.x1, cell.x1),
                y=previous.y,
            )
        else:
            joined.append(cell)
    return joined


def _modal_size(cells: list[_Cell]) -> float:
    """The page's body-text size, weighted by how many characters use it."""
    weights: dict[float, int] = {}
    for cell in cells:
        key = round(cell.size, 1)
        weights[key] = weights.get(key, 0) + len(cell.text)
    if not weights:
        return 0.0
    return max(weights.items(), key=lambda item: item[1])[0]


def _text_block(cell: _Cell, toc_levels: dict[str, int], modal_size: float) -> TextBlock:
    text = cell.text.strip()
    level = _heading_level(text, cell.size, modal_size, toc_levels.get(_normalise_heading(text)))
    if level is None:
        return TextBlock(text=text, kind="paragraph")
    return TextBlock(text=text, kind="heading", heading_level=level)


def _heading_level(
    text: str,
    size: float,
    modal_size: float,
    toc_level: int | None,
) -> int | None:
    """Decide whether a single-column line is a heading, and at what level."""
    if toc_level is not None:
        return toc_level
    if len(text) > _HEADING_MAX_CHARS:
        return None

    patterned = heading_level_from_text(text)
    if patterned is not None:
        return patterned

    # A line ending in sentence punctuation is prose that happens to be large,
    # not a title.
    if (
        not text.endswith(_SENTENCE_END)
        and modal_size > 0
        and size >= modal_size * _HEADING_SIZE_RATIO
    ):
        return 1 if size >= modal_size * _HEADING_LEVEL1_RATIO else 2
    return None


def _table_blocks(run: list[_Row]) -> list[TextBlock]:
    """Render a run of same-width grid rows.

    When the first row looks like column labels, later rows are rendered
    self-describing ("Date: 12 December 2026; Fee: 500") so a value stays
    meaningful even if the chunker separates it from the header. When there is no
    header, the rows are emitted as-is rather than inventing labels.
    """
    if len(run) == 1:
        return [TextBlock(text=run[0].text, kind="table_row")]

    header, *body = run
    if not looks_like_column_labels([cell.text for cell in header.cells]):
        return [TextBlock(text=row.text, kind="table_row") for row in run]

    labels = [cell.text for cell in header.cells]
    blocks = [TextBlock(text=header.text, kind="paragraph")]
    for row in body:
        rendered = render_labelled_row(labels, [cell.text for cell in row.cells])
        blocks.append(TextBlock(text=rendered or row.text, kind="table_row"))
    return blocks


def _normalise_heading(text: str) -> str:
    """Fold a heading for matching against the outline."""
    return re.sub(r"\s+", " ", text).strip().strip(".").casefold()
