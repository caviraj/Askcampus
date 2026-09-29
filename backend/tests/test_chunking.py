"""Chunking: sizes, overlap, section boundaries, and the awkward inputs.

The chunk constants are pinned to the spec's values (target 300, max 500, overlap
50) so the arithmetic in each test is readable rather than depending on whatever
config happens to hold.
"""

from __future__ import annotations

import pytest

from app.config import Settings
from app.services.chunking import Chunk, chunk_document
from app.services.extraction import ExtractedDocument, ExtractedPage, TextBlock
from app.services.tokens import count_tokens

_LETTERS = "abcdefghijklmnopqrstuvwxyz"


@pytest.fixture
def chunk_settings(settings: Settings) -> Settings:
    """The spec's chunk constants, pinned."""
    return settings.model_copy(
        update={
            "chunk_target_tokens": 300,
            "chunk_max_tokens": 500,
            "chunk_overlap_tokens": 50,
            "chunk_min_tokens": 40,
        }
    )


def _label(index: int) -> str:
    """A distinct four-letter word, so every unit is identifiable and costs
    exactly one token."""
    return "".join(_LETTERS[(index // (26**power)) % 26] for power in (3, 2, 1, 0))


def _unit_text(index: int, *, tokens: int = 5) -> str:
    """One block of exactly `tokens` tokens, unique to `index`."""
    return " ".join([_label(index)] * tokens)


def _paragraph(text: str) -> TextBlock:
    return TextBlock(text=text)


def _heading(text: str, level: int = 1) -> TextBlock:
    return TextBlock(text=text, kind="heading", heading_level=level)


def _document(*pages: list[TextBlock]) -> ExtractedDocument:
    return ExtractedDocument(
        pages=[
            ExtractedPage(page_number=index + 1, blocks=list(blocks))
            for index, blocks in enumerate(pages)
        ],
        page_count=len(pages),
    )


def _uniform_document(units: int, *, tokens: int = 5) -> ExtractedDocument:
    """One section of `units` equally sized blocks, each uniquely labelled."""
    return _document([_paragraph(_unit_text(index, tokens=tokens)) for index in range(units)])


def _lines(chunk: Chunk) -> list[str]:
    return chunk.content.split("\n")


def _shared_run(left: Chunk, right: Chunk) -> list[str]:
    """The longest run of lines ending `left` that opens `right`."""
    tail, head = _lines(left), _lines(right)
    for size in range(min(len(tail), len(head)), 0, -1):
        if tail[-size:] == head[:size]:
            return tail[-size:]
    return []


def test_an_empty_document_produces_no_chunks(chunk_settings: Settings) -> None:
    assert chunk_document(_document([]), chunk_settings) == []


def test_a_document_with_no_blocks_produces_no_chunks(chunk_settings: Settings) -> None:
    assert chunk_document(_document([], []), chunk_settings) == []


def test_a_heading_with_no_body_produces_no_chunks(chunk_settings: Settings) -> None:
    """A section heading on its own carries no answerable text, so indexing it
    would only ever produce a chunk that cannot answer anything."""
    assert chunk_document(_document([_heading("Examination Fees")]), chunk_settings) == []


def test_chunk_indices_are_dense_and_zero_based(chunk_settings: Settings) -> None:
    chunks = chunk_document(_uniform_document(120, tokens=60), chunk_settings)
    assert [chunk.index for chunk in chunks] == list(range(len(chunks)))
    assert chunks[0].index == 0


def test_no_chunk_exceeds_the_maximum(chunk_settings: Settings) -> None:
    chunks = chunk_document(_uniform_document(120, tokens=60), chunk_settings)
    assert len(chunks) > 1
    assert all(chunk.token_count <= chunk_settings.chunk_max_tokens for chunk in chunks)


def test_no_chunk_falls_below_the_minimum(chunk_settings: Settings) -> None:
    """A two-word fragment in the index is a chunk that can never be a useful
    answer, and it competes with real chunks for the same query."""
    chunks = chunk_document(_uniform_document(120, tokens=60), chunk_settings)
    assert all(chunk.token_count >= chunk_settings.chunk_min_tokens for chunk in chunks)


def test_a_chunk_holds_more_than_one_block(chunk_settings: Settings) -> None:
    """Packing small blocks together is the point: one chunk per paragraph would
    scatter a single rule across several citations."""
    chunks = chunk_document(_uniform_document(120, tokens=5), chunk_settings)
    assert all(len(_lines(chunk)) > 1 for chunk in chunks)


def test_consecutive_chunks_overlap(chunk_settings: Settings) -> None:
    chunks = chunk_document(_uniform_document(128, tokens=5), chunk_settings)
    assert len(chunks) >= 3
    for left, right in zip(chunks, chunks[1:], strict=False):
        shared = _shared_run(left, right)
        assert shared, "no continuity between consecutive chunks"
        assert 0 < count_tokens("\n".join(shared)) <= chunk_settings.chunk_overlap_tokens


def test_a_single_block_larger_than_a_chunk_is_split_on_sentences(
    chunk_settings: Settings,
) -> None:
    sentence = f"{' '.join(['fees'] * 29)}."
    assert count_tokens(sentence) == 30
    document = _document([_paragraph(" ".join([sentence] * 40))])

    chunks = chunk_document(document, chunk_settings)
    assert len(chunks) > 1
    assert all(chunk.token_count <= chunk_settings.chunk_max_tokens for chunk in chunks)
    # Split on real boundaries: every piece ends where a sentence ended.
    assert all(chunk.content.rstrip().endswith(".") for chunk in chunks)


def test_a_sentence_with_no_boundaries_is_cut_rather_than_dropped(
    chunk_settings: Settings,
) -> None:
    """A wall of text with no full stop has to be cut somewhere; losing it
    entirely would be worse than cutting mid-sentence."""
    document = _document([_paragraph("fees " * 3000)])
    chunks = chunk_document(document, chunk_settings)
    assert len(chunks) > 1
    assert all(chunk.token_count <= chunk_settings.chunk_max_tokens for chunk in chunks)
    assert "".join("".join(chunk.content.split()) for chunk in chunks) == "fees" * 3000


def test_a_table_row_is_never_split(chunk_settings: Settings) -> None:
    """Half a fee table is unreadable, so an over-budget row is kept whole and
    the chunk is allowed to exceed the maximum instead."""
    row = TextBlock(text=" ".join(["fees"] * 600) + ".", kind="table_row")
    chunks = chunk_document(_document([row]), chunk_settings)

    assert len(chunks) == 1
    assert chunks[0].content == row.text
    assert chunks[0].token_count > chunk_settings.chunk_max_tokens


def test_the_heading_is_prefixed_into_the_content(chunk_settings: Settings) -> None:
    """`hybrid_search` searches `content` only, and the generated `fts` column
    comes from it, so a chunk about registration dates cannot be matched by the
    keyword "Registration" unless the heading is in the text."""
    document = _document([_heading("Examination Fees"), _paragraph(_unit_text(0, tokens=60))])
    chunk = chunk_document(document, chunk_settings)[0]
    assert chunk.content.startswith("Examination Fees\n\n")
    assert chunk.section_heading == "Examination Fees"


def test_the_section_heading_is_a_breadcrumb(chunk_settings: Settings) -> None:
    """A subsection keeps its parent, so a citation reads
    "Examination Fees > Late payment" rather than losing its context."""
    document = _document(
        [
            _heading("Examination Fees"),
            _paragraph(_unit_text(0, tokens=60)),
            _heading("Late payment", level=2),
            _paragraph(_unit_text(1, tokens=60)),
        ]
    )
    chunks = chunk_document(document, chunk_settings)
    assert chunks[0].section_heading == "Examination Fees"
    assert chunks[1].section_heading == "Examination Fees > Late payment"
    assert chunks[1].content.startswith("Examination Fees > Late payment\n\n")


def test_a_sibling_heading_replaces_the_previous_one(chunk_settings: Settings) -> None:
    document = _document(
        [
            _heading("Fees"),
            _paragraph(_unit_text(0, tokens=60)),
            _heading("Hostel"),
            _paragraph(_unit_text(1, tokens=60)),
        ]
    )
    chunks = chunk_document(document, chunk_settings)
    assert chunks[1].section_heading == "Hostel"


def test_overlap_never_crosses_a_heading_boundary(chunk_settings: Settings) -> None:
    """Carrying text backwards over a heading would leave a chunk holding text its
    own section_heading does not name, and AGENTS.md section 5 requires citation
    fields to match reality."""
    document = _document(
        [
            # Long enough that the first section flushes several times, giving the
            # overlap rule every chance to fire across the boundary.
            _heading("Fees"),
            *[_paragraph(_unit_text(index, tokens=60)) for index in range(8)],
            _heading("Hostel"),
            _paragraph(_unit_text(100, tokens=60)),
        ]
    )
    chunks = chunk_document(document, chunk_settings)
    fees = [chunk for chunk in chunks if chunk.section_heading == "Fees"]
    hostel = [chunk for chunk in chunks if chunk.section_heading == "Hostel"]

    assert len(fees) > 1 and hostel
    first_hostel = _lines(hostel[0])
    # The new section's chunk opens with its own heading, then only its own text.
    assert first_hostel[0] == "Hostel"
    assert all(line in ("", _unit_text(100, tokens=60)) for line in first_hostel[1:])


def test_a_trailing_stub_is_folded_into_the_previous_chunk(
    chunk_settings: Settings,
) -> None:
    """Ten tokens on their own would be a fragment that can answer nothing, so
    they join the chunk before them instead."""
    document = _document(
        [
            *[_paragraph(_unit_text(index, tokens=60)) for index in range(5)],
            _paragraph(_unit_text(99, tokens=10)),
        ]
    )
    chunks = chunk_document(document, chunk_settings)
    assert len(chunks) == 1
    assert _unit_text(99, tokens=10) in chunks[0].content


def test_a_document_shorter_than_the_minimum_still_produces_one_chunk(
    chunk_settings: Settings,
) -> None:
    """There is no previous chunk to fold into, and dropping the document's only
    text would make it silently unsearchable."""
    chunks = chunk_document(_document([_paragraph("Fees are payable in June.")]), chunk_settings)
    assert len(chunks) == 1
    assert chunks[0].content == "Fees are payable in June."


def test_the_page_number_is_the_page_the_chunk_starts_on(chunk_settings: Settings) -> None:
    """A chunk can span a page break, and the citation must name the page the
    text begins on -- otherwise it points at a page that does not contain it."""
    document = _document(
        [_paragraph(_unit_text(index, tokens=5)) for index in range(60)],
        [_paragraph(_unit_text(index, tokens=5)) for index in range(60, 120)],
    )
    chunks = chunk_document(document, chunk_settings)
    assert chunks[0].page_number == 1
    assert chunks[-1].page_number in (1, 2)
    assert all(chunk.page_number in (1, 2) for chunk in chunks)


def test_a_chunk_on_the_second_page_reports_page_two(chunk_settings: Settings) -> None:
    """Page 1 is filled to exactly the flush point, so the next block opens a new
    chunk -- and that chunk's citation must name page 2."""
    document = _document(
        [_paragraph(_unit_text(index, tokens=60)) for index in range(5)],
        [_paragraph(_unit_text(50, tokens=60))],
    )
    chunks = chunk_document(document, chunk_settings)
    assert [chunk.page_number for chunk in chunks] == [1, 2]


def test_the_same_input_always_produces_the_same_chunks(chunk_settings: Settings) -> None:
    """Determinism is what makes the Phase 6 evaluation reproducible: a reprocess
    must not silently re-index the same bytes differently."""
    document = _document(
        [_heading("Fees"), *[_paragraph(_unit_text(index, tokens=5)) for index in range(80)]]
    )
    assert chunk_document(document, chunk_settings) == chunk_document(document, chunk_settings)


def test_token_count_matches_the_content(chunk_settings: Settings) -> None:
    """The stored count is what a future retrieval budget is spent against, so it
    must describe the text actually stored."""
    chunks = chunk_document(_uniform_document(40, tokens=60), chunk_settings)
    assert all(chunk.token_count == count_tokens(chunk.content) for chunk in chunks)
