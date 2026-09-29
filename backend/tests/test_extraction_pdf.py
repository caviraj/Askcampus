"""PDF extraction: page numbers, headings, tables, and the cases that fail.

PDFs carry no structural markup, so the extractor works from three signals --
font size, numbering patterns, and the document's own outline. These tests pin
what each one is responsible for.
"""

from __future__ import annotations

import pytest

from app.config import Settings
from app.services.extraction import ExtractionError, extract_document
from tests.filebuilders import (
    PdfLine,
    encrypted_pdf,
    pdf_bytes,
    pdf_with_headings,
    pdf_with_table,
    pdf_with_toc,
    scanned_pdf,
    simple_pdf,
)


def test_page_numbers_are_one_based(settings: Settings) -> None:
    """A zero-based page number would be off by one in every citation, and the
    error would be invisible in the UI."""
    document = extract_document(simple_pdf("First page.", "Second page."), "pdf", settings)
    assert [page.page_number for page in document.pages] == [1, 2]
    assert document.page_count == 2


def test_text_is_attributed_to_the_right_page(settings: Settings) -> None:
    document = extract_document(simple_pdf("Alpha.", "Beta."), "pdf", settings)
    assert document.pages[0].text.strip() == "Alpha."
    assert document.pages[1].text.strip() == "Beta."


def test_a_larger_font_becomes_a_heading(settings: Settings) -> None:
    document = extract_document(pdf_with_headings(), "pdf", settings)
    first = document.pages[0]
    headings = [block for block in first.blocks if block.kind == "heading"]
    assert [block.text for block in headings] == ["Student Handbook", "1. Examination Fees"]
    assert all(block.heading_level is not None for block in headings)


def test_body_text_is_not_mistaken_for_a_heading(settings: Settings) -> None:
    document = extract_document(pdf_with_headings(), "pdf", settings)
    body = [
        block.text for page in document.pages for block in page.blocks if block.kind == "paragraph"
    ]
    assert "The examination fee for the semester is 500 rupees." in body


def test_numbering_sets_the_heading_level(settings: Settings) -> None:
    """ "1.1 Late payment" is a subsection, so it must not sit at the same level
    as its parent -- the section_heading breadcrumb is built from these."""
    document = extract_document(pdf_with_headings(), "pdf", settings)
    late = next(
        block
        for page in document.pages
        for block in page.blocks
        if block.text == "1.1 Late payment"
    )
    assert late.kind == "heading"
    assert late.heading_level == 2


def test_the_document_outline_overrides_the_font_size_heuristic(settings: Settings) -> None:
    """Every line in this fixture is the same size, so the font-size signal finds
    nothing. Any heading reported must have come from the real outline -- which is
    structure the document actually declares, not a guess."""
    document = extract_document(pdf_with_toc(), "pdf", settings)
    headings = [
        block.text for page in document.pages for block in page.blocks if block.kind == "heading"
    ]
    assert headings == ["Registration", "Hostel"]


def test_a_page_number_setting_does_not_leak_between_pages(settings: Settings) -> None:
    """A heading on page 1 must not make page 2's body text a heading."""
    document = extract_document(
        pdf_bytes(
            [
                [PdfLine("Fees", size=18.0), PdfLine("The fee is 500 rupees.")],
                [PdfLine("The late fee applies from the next day.")],
            ]
        ),
        "pdf",
        settings,
    )
    second = [block.kind for block in document.pages[1].blocks]
    assert second == ["paragraph"]


def test_table_rows_are_rendered_self_describing(settings: Settings) -> None:
    """FR-3 requires fees and dates to stay readable. A bare row loses its meaning
    the moment the chunker separates it from the header row."""
    document = extract_document(pdf_with_table(), "pdf", settings)
    rows = [
        block.text for page in document.pages for block in page.blocks if block.kind == "table_row"
    ]
    assert rows == [
        "Date: 12 December 2026; Fee: 500; Note: Semester fee",
        "Date: 15 January 2027; Fee: 100; Note: Late charge",
    ]


def test_table_values_are_not_also_emitted_as_loose_text(settings: Settings) -> None:
    """The failure this guards against is silent duplication: the same fee twice in
    two chunks, which then compete with each other in retrieval."""
    document = extract_document(pdf_with_table(), "pdf", settings)
    text = document.text
    assert text.count("12 December 2026") == 1
    assert text.count("Semester fee") == 1


def test_the_table_header_row_is_not_emitted_as_a_data_row(settings: Settings) -> None:
    """A header row has no values, so rendering it as "Date: Fee" would be
    nonsense in the index."""
    document = extract_document(pdf_with_table(), "pdf", settings)
    assert "Date: Fee" not in document.text


def test_a_scanned_pdf_yields_no_text(settings: Settings) -> None:
    document = extract_document(scanned_pdf(), "pdf", settings)
    assert document.char_count == 0
    assert document.page_count == 2


def test_a_password_protected_pdf_is_rejected(settings: Settings) -> None:
    with pytest.raises(ExtractionError, match="password"):
        extract_document(encrypted_pdf(), "pdf", settings)


def test_bytes_that_are_not_a_pdf_are_rejected(settings: Settings) -> None:
    with pytest.raises(ExtractionError):
        extract_document(b"this is not a pdf at all", "pdf", settings)


def test_more_pages_than_the_limit_is_rejected_rather_than_truncated(
    settings: Settings,
) -> None:
    """Truncating would silently index half a document and cite it as if complete.
    Failing is the honest outcome."""
    limited = settings.model_copy(update={"max_document_pages": 1})
    with pytest.raises(ExtractionError, match="above the limit"):
        extract_document(simple_pdf("One.", "Two."), "pdf", limited)


def test_an_unknown_file_type_is_rejected(settings: Settings) -> None:
    with pytest.raises(ExtractionError):
        extract_document(b"whatever", "xlsx", settings)
