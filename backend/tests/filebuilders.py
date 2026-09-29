"""Generate PDF, DOCX and TXT fixtures in memory.

Generated rather than committed as binaries: no opaque blobs in git, no fixture
rot when a library changes its output, and the builder doubles as a readable
statement of what each format looks like. "Very long input" is 5,000 generated
paragraphs rather than a checked-in 20 MB file.
"""

from __future__ import annotations

import hashlib
import io
from collections.abc import Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from math import isqrt

import pymupdf

# A4 in points, which is what new_page() defaults to anyway. Stated so the table
# geometry below can be reasoned about.
_PAGE_WIDTH = 595.0
_PAGE_HEIGHT = 842.0

# Where the first line of body text starts.
_MARGIN_X = 60.0
_FIRST_BASELINE_Y = 80.0

# Body text size for generated pages. Headings are deliberately larger, because
# that is the signal the PDF extractor keys on.
_BODY_SIZE = 11.0
_HEADING_SIZE = 18.0
_SUBHEADING_SIZE = 14.0

# Column x positions for the ruled table builder.
_TABLE_COLUMNS = (60.0, 220.0, 380.0)
_TABLE_ROW_HEIGHT = 22.0


@dataclass(frozen=True)
class PdfLine:
    """One line of text on a generated page."""

    text: str
    size: float = _BODY_SIZE
    # Blank lines are used as vertical spacing; `gap` is cleaner than an empty
    # string because an empty string still advances the cursor.
    gap: float = 0.0


@dataclass
class _Builder:
    """Accumulates pages so the caller never touches pymupdf directly."""

    document: pymupdf.Document = field(default_factory=pymupdf.open)

    def add_lines(self, lines: Sequence[PdfLine]) -> None:
        page = self.document.new_page(width=_PAGE_WIDTH, height=_PAGE_HEIGHT)
        y = _FIRST_BASELINE_Y
        for line in lines:
            if line.text:
                page.insert_text(
                    (_MARGIN_X, y),
                    line.text,
                    fontsize=line.size,
                    fontname="helv",
                )
            y += line.size + 8.0 + line.gap

    def tobytes(self) -> bytes:
        return bytes(self.document.tobytes())


def pdf_bytes(
    pages: Sequence[Sequence[PdfLine | str]], *, toc: Sequence[tuple[int, str, int]] = ()
) -> bytes:
    """A PDF with one text page per entry in `pages`.

    A `str` is shorthand for a body-size line. `toc` entries are
    (level, title, page_number) and become a real PDF outline, which the
    extractor prefers over its font-size heuristic.
    """
    builder = _Builder()
    for lines in pages:
        builder.add_lines([PdfLine(text=line) if isinstance(line, str) else line for line in lines])

    if toc:
        builder.document.set_toc([list(entry) for entry in toc])

    return builder.tobytes()


def simple_pdf(*page_texts: str) -> bytes:
    """Convenience: one plain paragraph per page, in order.

    Page numbers are 1-based, so `simple_pdf("a", "b")` puts "a" on page 1.
    """
    return pdf_bytes([[text] for text in page_texts])


def pdf_with_headings() -> bytes:
    """A document with a title, a numbered section and a subsection.

    Sizes are distinct so the font-size heuristic has something real to find,
    rather than the test asserting against a single-size page.
    """
    return pdf_bytes(
        [
            [
                PdfLine("Student Handbook", size=_HEADING_SIZE),
                PdfLine("", gap=6.0),
                PdfLine("1. Examination Fees", size=_SUBHEADING_SIZE),
                PdfLine("", gap=4.0),
                PdfLine("The examination fee for the semester is 500 rupees."),
                PdfLine("A late payment of 100 rupees is charged after the due date."),
            ],
            [
                PdfLine("1.1 Late payment", size=_SUBHEADING_SIZE),
                PdfLine("", gap=4.0),
                PdfLine("The late fee applies from the day after the due date."),
            ],
        ]
    )


def pdf_with_toc() -> bytes:
    """A PDF whose real outline disagrees with its font sizes.

    Both pages use body-size text, so a font-size heuristic finds no headings at
    all. Any heading the extractor reports therefore came from the outline.
    """
    return pdf_bytes(
        [
            [PdfLine("Registration"), PdfLine("Registration closes on 12 December 2026.")],
            [PdfLine("Hostel"), PdfLine("Hostel applications open in June.")],
        ],
        toc=[(1, "Registration", 1), (1, "Hostel", 2)],
    )


def pdf_with_table() -> bytes:
    """A ruled three-column table with a header row.

    Really ruled -- the lines are drawn -- because the extractor reconstructs
    tables geometrically from line positions, and a table without rulings is not
    a table to it.
    """
    builder = _Builder()
    page = builder.document.new_page(width=_PAGE_WIDTH, height=_PAGE_HEIGHT)

    rows = [
        ("Date", "Fee", "Note"),
        ("12 December 2026", "500", "Semester fee"),
        ("15 January 2027", "100", "Late charge"),
    ]

    top = _FIRST_BASELINE_Y - 16.0
    left = _TABLE_COLUMNS[0] - 6.0
    right = _TABLE_COLUMNS[-1] + 60.0

    for index, row in enumerate(rows):
        y = top + index * _TABLE_ROW_HEIGHT
        page.draw_line((left, y), (right, y))
        for column, cell in zip(_TABLE_COLUMNS, row, strict=True):
            page.insert_text((column, y + 15.0), cell, fontsize=_BODY_SIZE, fontname="helv")

    bottom = top + len(rows) * _TABLE_ROW_HEIGHT
    page.draw_line((left, bottom), (right, bottom))
    for column in _TABLE_COLUMNS:
        page.draw_line((column - 6.0, top), (column - 6.0, bottom))
    page.draw_line((right, top), (right, bottom))

    return builder.tobytes()


def scanned_pdf(page_count: int = 2) -> bytes:
    """A PDF with no text layer, standing in for a scan.

    Pages hold an image and nothing else, so extraction legitimately finds no
    text -- which is the case that must be flagged rather than failed.
    """
    builder = _Builder()
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 120, 120))
    pixmap.set_rect(pixmap.irect, (200, 200, 200))

    for _ in range(page_count):
        page = builder.document.new_page(width=_PAGE_WIDTH, height=_PAGE_HEIGHT)
        page.insert_image(pymupdf.Rect(60, 60, 400, 400), pixmap=pixmap)

    return builder.tobytes()


@lru_cache(maxsize=4)
def large_pdf(*, minimum_bytes: int = 2 * 1024 * 1024) -> bytes:
    """A real, extractable PDF comfortably over `minimum_bytes`.

    Exists for one test: that an upload larger than Starlette's 1 MB multipart
    default is actually accepted. A 2 MB blob is not committed to git, and
    building this out of *text* is not viable -- PyMuPDF's text layout costs
    roughly four seconds per megabyte, which would dominate the suite.

    So the bulk is a page-sized image of pseudo-random noise. Noise is
    incompressible, which makes the size predictable instead of depending on how
    repetitive the text happens to be, and inserting one image is a single call.
    Real text is added alongside it so the result is a legitimate document that
    the pipeline can extract, not a fixture that only satisfies a size check.

    Cached because the noise digest is the expensive part and the value is
    immutable bytes.
    """
    side = isqrt(minimum_bytes // 3) + 40
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, side, side), False)
    pixmap.samples_mv[:] = hashlib.shake_128(b"campusask-large-fixture").digest(
        len(pixmap.samples_mv)
    )

    builder = _Builder()
    page = builder.document.new_page(width=_PAGE_WIDTH, height=_PAGE_HEIGHT)
    page.insert_image(pymupdf.Rect(0, 0, _PAGE_WIDTH, _PAGE_HEIGHT), pixmap=pixmap)
    for index, line in enumerate(
        [
            "1. Examination Fees",
            "The examination fee for the semester is 500 rupees.",
            "A late payment of 100 rupees is charged after the due date.",
        ]
    ):
        page.insert_text(
            (_MARGIN_X, _FIRST_BASELINE_Y + index * 20.0),
            line,
            fontsize=_BODY_SIZE,
            fontname="helv",
        )

    return builder.tobytes()


def many_page_pdf(paragraphs: int = 2000, *, lines_per_page: int = 40) -> bytes:
    """A very long but text-light PDF, for the "very long input" edge case.

    The page count is bounded by `lines_per_page`, so the cost is the text drawn
    rather than a page object per paragraph.
    """
    builder = _Builder()
    pending: list[PdfLine] = []
    for index in range(paragraphs):
        if index % lines_per_page == 0:
            pending.append(PdfLine(f"Section {index // lines_per_page + 1}"))
        pending.append(PdfLine(f"Paragraph {index} about the admission process."))
        if len(pending) >= lines_per_page:
            builder.add_lines(pending)
            pending = []

    if pending:
        builder.add_lines(pending)
    return builder.tobytes()


def docx_bytes(
    *,
    paragraphs: Sequence[tuple[str, str | None]] = (),
    tables: Sequence[Sequence[Sequence[str]]] = (),
) -> bytes:
    """A DOCX from paragraphs followed by tables.

    Paragraphs are (text, style) pairs with style None for body text; tables are
    lists of rows of cell strings. Use `docx_interleaved` when the order of the
    two matters, since this emits every paragraph before every table.
    """
    from docx import Document

    document = Document()
    for text, style in paragraphs:
        if style:
            document.add_paragraph(text, style=style)
        else:
            document.add_paragraph(text)

    for rows in tables:
        table = document.add_table(rows=0, cols=len(rows[0]))
        for row in rows:
            cells = table.add_row().cells
            for cell, value in zip(cells, row, strict=True):
                cell.text = value

    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def encrypted_pdf(password: str = "secret") -> bytes:
    """A PDF that requires a password to open.

    A realistic upload failure: the admin has a protected file and the pipeline
    has to say so rather than storing a document that can never be read.
    """
    builder = _Builder()
    builder.add_lines([PdfLine("Fees are payable in June.")])
    return bytes(
        builder.document.tobytes(
            encryption=pymupdf.PDF_ENCRYPT_AES_256,
            owner_pw=password,
            user_pw=password,
        )
    )


def docx_interleaved() -> bytes:
    """A DOCX where a table sits between two paragraphs.

    Built by walking python-docx's XML body so the order is genuinely
    paragraph, table, paragraph rather than all paragraphs then all tables.
    """
    from docx import Document

    document = Document()
    document.add_heading("Fee schedule", level=1)
    document.add_paragraph("The table below lists the fees.")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Item"
    table.cell(0, 1).text = "Amount"
    table.cell(1, 0).text = "Tuition"
    table.cell(1, 1).text = "500"
    document.add_paragraph("Fees are payable at the accounts office.")
    document.add_heading("Refunds", level=2)
    document.add_paragraph("Refunds are issued within 30 days.")

    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def txt_bytes(text: str, *, encoding: str = "utf-8") -> bytes:
    """Text encoded for a .txt fixture. `utf-8` gets a BOM on request only."""
    return text.encode(encoding)


def txt_with_page_breaks(page_texts: Sequence[str]) -> bytes:
    """A text file using the conventional form feed as a page separator."""
    return "\f".join(page_texts).encode("utf-8")
