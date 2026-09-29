"""Text cleaning.

Runs between extraction and chunking. Two things happen here that cannot happen in
the extractor:

1. **Hyphen re-joining across blocks.** A word wrapped at a line break arrives from
   a PDF as two blocks ("regis-" then "tration"). Only here, with both in hand, can
   they be put back together. The guard matters as much as the join: "CIA-" followed
   by "2" is a code, not a word, and must survive untouched.

2. **Running header and footer removal.** They repeat on every page, so they would
   otherwise be embedded once per page and pollute retrieval with text that answers
   nothing.

Dates, codes and identifiers pass through byte-identical -- NFKC normalises
presentation forms such as ligatures and full-width digits, and leaves ASCII
alone.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter

from app.services.extraction import ExtractedDocument, ExtractedPage, TextBlock

_WHITESPACE = re.compile(r"\s+")
# A line ending in a hyphen whose preceding character is a letter. "3-" and "--"
# deliberately do not match: those are ranges and dashes, not hyphenation.
_TRAILING_HYPHEN = re.compile(r"(?<=[^\W\d_])-$")

# The repeat rule needs enough pages to tell a running header from a heading.
_MIN_PAGES_FOR_REPEAT = 3
# A block counts as a running header when it opens this fraction of pages.
_REPEAT_RATIO = 0.6
# Headers and footers are short. A long repeated block is more likely to be real
# content, so it is left alone.
_MAX_RUNNING_EDGE_CHARS = 160


def clean_document(document: ExtractedDocument) -> ExtractedDocument:
    """Normalise an extracted document in place-free fashion."""
    joined = [
        ExtractedPage(
            page_number=page.page_number,
            blocks=_join_hyphenated(page.blocks),
        )
        for page in document.pages
    ]
    _drop_running_edges(joined)

    pages = [
        ExtractedPage(
            page_number=page.page_number,
            blocks=[
                normalised
                for normalised in (_normalise(block) for block in page.blocks)
                if normalised is not None
            ],
        )
        for page in joined
    ]
    return ExtractedDocument(pages=pages, page_count=document.page_count)


def _join_hyphenated(blocks: list[TextBlock]) -> list[TextBlock]:
    """Re-join a word split across a line break."""
    merged: list[TextBlock] = []
    for block in blocks:
        if merged and _is_hyphen_continuation(merged[-1], block):
            previous = merged[-1]
            merged[-1] = TextBlock(
                text=f"{previous.text[:-1]}{block.text}",
                kind=previous.kind,
                heading_level=previous.heading_level,
            )
            continue
        merged.append(block)
    return merged


def _is_hyphen_continuation(previous: TextBlock, current: TextBlock) -> bool:
    if previous.kind == "heading" or current.kind == "heading":
        return False
    if not _TRAILING_HYPHEN.search(previous.text):
        return False
    # The continuation must start lower-case, which is what distinguishes
    # "regis-" + "tration" from "CIA-" + "2" or "Section A-" + "Grades".
    return current.text[:1].islower()


def _normalise(block: TextBlock) -> TextBlock | None:
    text = _WHITESPACE.sub(" ", unicodedata.normalize("NFKC", block.text)).strip()
    if not text:
        return None
    if text == block.text:
        return block
    return TextBlock(text=text, kind=block.kind, heading_level=block.heading_level)


def _drop_running_edges(pages: list[ExtractedPage]) -> None:
    """Remove the first and last block when they repeat across most pages.

    Only pages with at least two blocks are considered, so a page consisting solely
    of a header is left as it is rather than emptied.
    """
    eligible = [page for page in pages if len(page.blocks) >= 2]
    if len(eligible) < _MIN_PAGES_FOR_REPEAT:
        return

    for index in (0, -1):
        candidates = [
            page.blocks[index].text.strip()
            for page in eligible
            if len(page.blocks[index].text.strip()) <= _MAX_RUNNING_EDGE_CHARS
        ]
        if not candidates:
            continue

        text, count = Counter(candidates).most_common(1)[0]
        if count / len(eligible) < _REPEAT_RATIO:
            continue

        key = text.casefold()
        for page in eligible:
            if page.blocks[index].text.strip().casefold() == key:
                del page.blocks[index]
