"""Plain-text extraction: encodings, page separators, heading patterns."""

from __future__ import annotations

import pytest

from app.services.extraction import ExtractionError
from app.services.extraction_txt import extract_txt
from tests.filebuilders import txt_bytes, txt_with_page_breaks


def test_reads_utf8_text() -> None:
    document = extract_txt(txt_bytes("The fee is 500 rupees."))
    assert document.text == "The fee is 500 rupees."


def test_a_utf8_bom_is_consumed() -> None:
    """Otherwise the BOM survives as a stray character at the start of the text,
    which shows up in a citation and in the search index."""
    document = extract_txt(txt_bytes("Fees", encoding="utf-8-sig"))
    assert document.text == "Fees"


def test_reads_utf16_by_its_bom() -> None:
    document = extract_txt(txt_bytes("Fees are payable in June.", encoding="utf-16"))
    assert document.text == "Fees are payable in June."


def test_falls_back_to_cp1252() -> None:
    """A Windows-exported file with cp1252-only characters is not valid UTF-8, so
    without the fallback it would be rejected rather than read.

    The regression this pins: UTF-16 used to be tried before cp1252, and UTF-16
    accepts almost any even-length byte string -- so this file decoded
    "successfully" into CJK mojibake instead of reaching the encoding that reads
    it correctly.
    """
    document = extract_txt(txt_bytes("Café fees – 500 rupees", encoding="cp1252"))
    assert "500 rupees" in document.text
    assert "Café" in document.text


def test_utf16_is_only_used_when_a_bom_says_so() -> None:
    """The counterpart to the test above: with a BOM, UTF-16 really is used."""
    document = extract_txt(txt_bytes("Fees are payable in June.", encoding="utf-16"))
    assert document.text == "Fees are payable in June."


def test_a_truncated_utf16_file_is_rejected_rather_than_reinterpreted() -> None:
    """A BOM is evidence about what the file is, so a broken UTF-16 file is an
    error rather than something to re-decode as cp1252."""
    with pytest.raises(ExtractionError):
        extract_txt(b"\xff\xfe\x41\x00\x42")


def test_cp1252_undefined_bytes_are_rejected() -> None:
    """cp1252 has five undefined byte values, and they are the only way a
    NUL-free text file fails to decode at all."""
    with pytest.raises(ExtractionError):
        extract_txt(b"Fees \x81 payable")


def test_an_empty_file_is_rejected() -> None:
    with pytest.raises(ExtractionError):
        extract_txt(b"   \n\n  ")


def test_no_separator_means_no_page_numbers() -> None:
    """A page number that was never in the file would be an invented citation
    field, which AGENTS.md section 5 forbids."""
    document = extract_txt(txt_bytes("One line.\nAnother line."))
    assert [page.page_number for page in document.pages] == [None]
    assert document.page_count is None


def test_form_feeds_become_one_based_pages() -> None:
    document = extract_txt(txt_with_page_breaks(["First page.", "Second page.", "Third page."]))
    assert [page.page_number for page in document.pages] == [1, 2, 3]
    assert document.page_count == 3


def test_a_trailing_form_feed_does_not_add_an_empty_page() -> None:
    document = extract_txt(txt_with_page_breaks(["Only page.", ""]))
    assert len(document.pages) == 1
    assert document.pages[0].text == "Only page."


def test_a_single_page_is_not_treated_as_paginated() -> None:
    """A file whose only page separator is trailing has one page and no page
    information worth recording, so the page number stays None rather than
    being asserted as 1."""
    document = extract_txt(txt_with_page_breaks(["Only page.", ""]))
    assert document.page_count is None
    assert document.pages[0].page_number is None


def test_numbered_lines_become_headings() -> None:
    document = extract_txt(txt_bytes("1. Examination Fees\nThe fee is 500 rupees."))
    kinds = [block.kind for block in document.pages[0].blocks]
    assert kinds == ["heading", "paragraph"]
    assert document.pages[0].blocks[0].heading_level == 1


def test_a_dotted_number_sets_a_deeper_level() -> None:
    document = extract_txt(txt_bytes("1.1 Late payment\nA late fee applies."))
    assert document.pages[0].blocks[0].heading_level == 2


def test_a_sentence_starting_with_a_number_is_not_a_heading() -> None:
    """The guard against over-eager heading detection: "500 rupees is due" is a
    sentence, not a section, and marking it as one would put a bogus
    section_heading on a citation."""
    document = extract_txt(txt_bytes("500 rupees is due in June."))
    assert document.pages[0].blocks[0].kind == "paragraph"


def test_blank_lines_do_not_produce_empty_blocks() -> None:
    document = extract_txt(txt_bytes("First.\n\n\n\nSecond."))
    assert [block.text for block in document.pages[0].blocks] == ["First.", "Second."]


def test_character_count_sums_the_blocks() -> None:
    document = extract_txt(txt_bytes("abc\ndef"))
    assert document.char_count == 6
