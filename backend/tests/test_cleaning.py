"""Cleaning: whitespace, hyphen re-joining, running header removal.

These are the two transformations that cannot happen in the extractor, because
both need more than one block in hand.
"""

from __future__ import annotations

from app.services.cleaning import clean_document
from app.services.extraction import ExtractedDocument, ExtractedPage, TextBlock


def _document(*pages: list[TextBlock], page_count: int | None = None) -> ExtractedDocument:
    return ExtractedDocument(
        pages=[
            ExtractedPage(page_number=index + 1, blocks=list(blocks))
            for index, blocks in enumerate(pages)
        ],
        page_count=page_count if page_count is not None else len(pages),
    )


def _paragraphs(*texts: str) -> list[TextBlock]:
    return [TextBlock(text=text) for text in texts]


def test_whitespace_is_collapsed() -> None:
    cleaned = clean_document(_document(_paragraphs("Fees   are\tpayable\nin June.")))
    assert cleaned.pages[0].blocks[0].text == "Fees are payable in June."


def test_a_block_that_becomes_empty_is_dropped() -> None:
    """An empty block would otherwise become a zero-token chunk candidate."""
    cleaned = clean_document(_document(_paragraphs("Fees.", "   \t  ", "June.")))
    assert [block.text for block in cleaned.pages[0].blocks] == ["Fees.", "June."]


def test_a_word_split_over_a_line_break_is_rejoined() -> None:
    """A wrapped word arrives as two blocks. Left alone, neither half matches a
    search for the whole word, and the citation reads "regis-tration"."""
    cleaned = clean_document(_document(_paragraphs("Regis-", "tration opens in May.")))
    assert [block.text for block in cleaned.pages[0].blocks] == ["Registration opens in May."]


def test_the_rejoined_block_keeps_its_position() -> None:
    """The merge must not reorder the document: a chunk's page number and section
    are taken from where its text sits."""
    cleaned = clean_document(
        _document(
            _paragraphs("Fees are due.", "Regis-", "tration opens in May.", "Hostel forms follow.")
        )
    )
    assert [block.text for block in cleaned.pages[0].blocks] == [
        "Fees are due.",
        "Registration opens in May.",
        "Hostel forms follow.",
    ]


def test_a_code_split_over_a_line_break_is_left_alone() -> None:
    """ "CIA-" followed by "2" is a code, not a hyphenated word. The continuation
    must start lower-case, which is the whole distinction."""
    cleaned = clean_document(_document(_paragraphs("CIA-", "2 is the form.")))
    assert [block.text for block in cleaned.pages[0].blocks] == ["CIA-", "2 is the form."]


def test_a_hyphenated_range_is_not_joined() -> None:
    """A preceding digit or a double dash is a range or a dash, never
    hyphenation."""
    cleaned = clean_document(_document(_paragraphs("pages 3-", "and 4")))
    assert [block.text for block in cleaned.pages[0].blocks] == ["pages 3-", "and 4"]


def test_a_heading_is_never_joined_into_the_block_before_it() -> None:
    """Joining would move the heading's level onto a merged block and lose the
    section boundary the chunker depends on."""
    cleaned = clean_document(
        _document(
            [TextBlock(text="Fees-"), TextBlock(text="heading", kind="heading", heading_level=1)]
        )
    )
    assert [block.kind for block in cleaned.pages[0].blocks] == ["paragraph", "heading"]


def test_a_running_header_is_removed() -> None:
    pages = [_paragraphs("Student Handbook", f"Body text for page {index}.") for index in range(10)]
    cleaned = clean_document(_document(*pages))
    assert all(block.text != "Student Handbook" for page in cleaned.pages for block in page.blocks)


def test_a_running_footer_is_removed() -> None:
    pages = [_paragraphs(f"Body text for page {index}.", "Page 1 of 10") for index in range(10)]
    cleaned = clean_document(_document(*pages))
    assert all("Page 1 of 10" not in block.text for page in cleaned.pages for block in page.blocks)


def test_a_one_off_opening_sentence_survives() -> None:
    """The failure the ratio guards against: a sentence that happens to open one
    page must not be deleted because it is not the most common opener."""
    pages = [_paragraphs("Student Handbook", f"Body {index}.") for index in range(9)]
    pages.append(_paragraphs("Scholarships are awarded in June.", "Body 9."))
    cleaned = clean_document(_document(*pages))
    assert any(
        block.text == "Scholarships are awarded in June." for block in cleaned.pages[9].blocks
    )


def test_a_short_document_is_not_cleaned_of_its_headers() -> None:
    """Two pages cannot distinguish a running header from a heading, so the rule
    stays out of the way rather than deleting real content."""
    pages = [_paragraphs("Student Handbook", f"Body {index}.") for index in range(2)]
    cleaned = clean_document(_document(*pages))
    assert cleaned.pages[0].blocks[0].text == "Student Handbook"


def test_a_header_shared_by_most_but_not_all_pages_is_still_removed() -> None:
    """8 of 10 is above the ratio; a header missing from two pages is still a
    header."""
    pages = [_paragraphs("Student Handbook", f"Body {index}.") for index in range(8)]
    pages.append(_paragraphs("Chapter 2", "Body 8."))
    pages.append(_paragraphs("Chapter 3", "Body 9."))
    cleaned = clean_document(_document(*pages))
    assert all(block.text != "Student Handbook" for page in cleaned.pages for block in page.blocks)
    # The two pages with a different opener keep theirs.
    assert cleaned.pages[8].blocks[0].text == "Chapter 2"


def test_a_long_repeated_block_is_not_treated_as_a_header() -> None:
    """Headers are short. A long block that repeats is more likely to be real
    content, and deleting it would lose text the admin uploaded."""
    long_text = "Fees are payable in June. " * 12
    pages = [_paragraphs(long_text, f"Body {index}.") for index in range(6)]
    cleaned = clean_document(_document(*pages))
    assert cleaned.pages[0].blocks[0].text == long_text.strip()


def test_a_date_survives_byte_identical() -> None:
    """AGENTS.md section 5: never fabricate a date. A near-miss in cleaning would
    put a date in a citation that is not the one in the document."""
    cleaned = clean_document(_document(_paragraphs("Fees are due on 12 December 2026.")))
    assert "12 December 2026" in cleaned.pages[0].blocks[0].text


def test_an_identifier_survives_byte_identical() -> None:
    cleaned = clean_document(_document(_paragraphs("Course code CS-2026-114 applies.")))
    assert "CS-2026-114" in cleaned.pages[0].blocks[0].text


def test_ligatures_are_normalised() -> None:
    """A PDF may emit "ﬁ" as one codepoint, which then fails to match a search for
    "fi" and renders inconsistently."""
    cleaned = clean_document(_document(_paragraphs("The ﬁne is 500 rupees.")))
    assert cleaned.pages[0].blocks[0].text == "The fine is 500 rupees."


def test_page_numbers_and_count_are_preserved() -> None:
    """Cleaning must not lose the citation fields it is not responsible for."""
    cleaned = clean_document(_document(_paragraphs("One."), _paragraphs("Two.")))
    assert [page.page_number for page in cleaned.pages] == [1, 2]
    assert cleaned.page_count == 2


def test_cleaning_is_idempotent() -> None:
    """Running it twice must not change the result, or a reprocess would produce
    different chunks from identical bytes."""
    once = clean_document(
        _document(_paragraphs("Fees  are payable.", "Regis-", "tration is open."))
    )
    twice = clean_document(once)
    assert [block.text for page in twice.pages for block in page.blocks] == [
        block.text for page in once.pages for block in page.blocks
    ]
