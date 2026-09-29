"""DOCX extraction: true element order, real heading styles, no invented pages."""

from __future__ import annotations

import pytest

from app.config import Settings
from app.services.extraction import ExtractionError, extract_document
from tests.filebuilders import docx_bytes, docx_interleaved


def test_paragraphs_and_tables_keep_their_true_order(settings: Settings) -> None:
    """python-docx's `.paragraphs` and `.tables` properties each return one kind,
    so a table drifts to the end of its section. The text below the table would
    then precede it in the index and in any citation."""
    document = extract_document(docx_interleaved(), "docx", settings)
    text = document.text
    assert text.index("Fee schedule") < text.index("Item: Tuition")
    assert text.index("Item: Tuition") < text.index("Fees are payable at the accounts office.")


def test_the_full_block_order_is_preserved(settings: Settings) -> None:
    document = extract_document(docx_interleaved(), "docx", settings)
    kinds = [block.kind for block in document.pages[0].blocks]
    assert kinds == [
        "heading",
        "paragraph",
        "paragraph",  # the column labels
        "table_row",
        "paragraph",
        "heading",
        "paragraph",
    ]


def test_heading_styles_give_real_levels(settings: Settings) -> None:
    """The reason DOCX sections are better labelled than PDF ones: Word records
    the level, so it is read rather than guessed from font size."""
    document = extract_document(docx_interleaved(), "docx", settings)
    headings = {
        block.text: block.heading_level
        for block in document.pages[0].blocks
        if block.kind == "heading"
    }
    assert headings == {"Fee schedule": 1, "Refunds": 2}


def test_a_title_style_is_a_level_one_heading(settings: Settings) -> None:
    data = docx_bytes(paragraphs=[("Student Handbook", "Title"), ("Fees are payable.", None)])
    document = extract_document(data, "docx", settings)
    first = document.pages[0].blocks[0]
    assert first.kind == "heading"
    assert first.heading_level == 1


def test_a_document_with_no_heading_styles_falls_back_to_numbering(
    settings: Settings,
) -> None:
    """Many real documents fake headings with bold body text, which carries no
    style to read."""
    data = docx_bytes(paragraphs=[("1. Examination Fees", None), ("The fee is 500.", None)])
    document = extract_document(data, "docx", settings)
    first = document.pages[0].blocks[0]
    assert first.kind == "heading"
    assert first.heading_level == 1


def test_there_is_no_page_number(settings: Settings) -> None:
    """A .docx has no fixed pagination -- where pages fall depends on the reader
    and the paper size. Reporting "1" for a 15-page handbook would be a
    confidently wrong citation, which AGENTS.md section 5 forbids."""
    document = extract_document(docx_interleaved(), "docx", settings)
    assert document.pages[0].page_number is None
    assert document.page_count is None


def test_a_labelled_table_row_is_self_describing(settings: Settings) -> None:
    document = extract_document(docx_interleaved(), "docx", settings)
    rows = [block.text for block in document.pages[0].blocks if block.kind == "table_row"]
    assert rows == ["Item: Tuition; Amount: 500"]


def test_a_table_without_labels_keeps_its_cells_in_order(settings: Settings) -> None:
    """A digit-bearing first row is data, not labels: rendering it as
    "Semester 1: Semester 2" would be nonsense."""
    data = docx_bytes(tables=[[["Semester 1", "Semester 2"], ["500", "600"]]])
    document = extract_document(data, "docx", settings)
    rows = [block.text for block in document.pages[0].blocks if block.kind == "table_row"]
    assert rows == ["Semester 1 | Semester 2", "500 | 600"]


def test_a_table_row_with_a_blank_cell_does_not_invent_a_value(settings: Settings) -> None:
    """The blank cell has no value to pair with its label, so the label is
    dropped rather than rendered as an empty one."""
    data = docx_bytes(
        tables=[[["Date", "Fee"], ["12 December 2026", "500"], ["15 January 2027", ""]]]
    )
    document = extract_document(data, "docx", settings)
    rows = [block.text for block in document.pages[0].blocks if block.kind == "table_row"]
    assert rows == ["Date: 12 December 2026; Fee: 500", "Date: 15 January 2027"]


def test_an_empty_document_yields_no_blocks(settings: Settings) -> None:
    """Not an error: a Word file that has been saved but never written in is a
    legitimate upload, and it reaches the same "no text" path as a scanned PDF."""
    document = extract_document(docx_bytes(), "docx", settings)
    assert document.pages[0].blocks == []
    assert document.char_count == 0


def test_a_zip_that_is_not_a_word_document_is_rejected(settings: Settings) -> None:
    """PK\\x03\\x04 alone proves nothing -- an .xlsx and a .pptx pass it too."""
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("xl/workbook.xml", "<workbook/>")
    with pytest.raises(ExtractionError):
        extract_document(buffer.getvalue(), "docx", settings)


def test_a_docx_that_expands_past_the_limit_is_rejected(settings: Settings) -> None:
    """Re-checked at extraction as well as at upload: a stored document may
    predate the upload check, and python-docx will happily expand a zip bomb.

    The fixture is one long paragraph rather than many short ones because the
    guard reads the *declared uncompressed* size: repetition compresses to almost
    nothing on disk while expanding to megabytes in memory, which is exactly the
    shape of the attack."""
    expanded = docx_bytes(paragraphs=[("Fees are payable in June. " * 60_000, None)])
    limited = settings.model_copy(update={"max_archive_uncompressed_mb": 1})
    with pytest.raises(ExtractionError, match="above the limit"):
        extract_document(expanded, "docx", limited)
