"""Plain-text extraction.

Text is the one format whose "page" is a convention rather than a property, so
page numbers are only assigned when the file actually carries page separators.
Form feed (\\f) is what word processors and PDF-to-text tools emit between pages,
so when it is present every page after the first is genuinely a new page.
"""

from __future__ import annotations

import re

from app.services.extraction import (
    ExtractedDocument,
    ExtractedPage,
    ExtractionError,
    TextBlock,
    heading_level_from_text,
)
from app.services.filetypes import UTF16_BOMS

_PAGE_SEPARATOR = "\f"
_BLANK_LINES = re.compile(r"\n\s*\n")


def extract_txt(data: bytes) -> ExtractedDocument:
    """Extract text from plain-text bytes."""
    text = _decode(data)
    if not text.strip():
        raise ExtractionError("The file contains no text.")

    raw_pages = text.split(_PAGE_SEPARATOR)
    # A single form feed at the end of a file is a trailing separator, not a page.
    if len(raw_pages) > 1 and not raw_pages[-1].strip():
        raw_pages = raw_pages[:-1]
    # Pagination is only claimed when the file actually carries more than one
    # page. A single page has no page information worth recording, and inventing
    # "1" for a file with no separator at all would fabricate a citation field.
    paginated = len(raw_pages) > 1

    pages = [
        ExtractedPage(
            page_number=index + 1 if paginated else None,
            blocks=_blocks(raw),
        )
        for index, raw in enumerate(raw_pages)
    ]
    return ExtractedDocument(pages=pages, page_count=len(pages) if paginated else None)


def _decode(data: bytes) -> str:
    """Decode text bytes, trusting a BOM when there is one.

    UTF-16 is attempted only when a BOM announces it, and that restriction is the
    point. UTF-16 accepts almost any even-length byte string, so trying it on
    every file means a cp1252 document "decodes" successfully into CJK mojibake
    rather than failing and falling through to the encoding that reads it
    correctly. A wrong decode is worse than a rejection: it puts
    plausible-looking nonsense into a citation, with nothing to indicate it.
    """
    if data.startswith(UTF16_BOMS):
        try:
            return data.decode("utf-16")
        except UnicodeDecodeError as exc:
            # Not retried as cp1252: the BOM is evidence about what this file is,
            # and decoding it as something else would produce mojibake.
            raise ExtractionError("The file is not valid UTF-16 text.") from exc

    try:
        # Handles plain UTF-8 too; with no BOM it simply decodes.
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        pass

    try:
        return data.decode("cp1252")
    except UnicodeDecodeError as exc:
        raise ExtractionError("The file could not be decoded as text.") from exc


def _blocks(page_text: str) -> list[TextBlock]:
    """One block per line, with blank lines separating nothing in particular.

    Wrapped text produces many short lines; the chunker fills to its token target,
    so they are recombined there rather than guessed at here.
    """
    normalised = _BLANK_LINES.sub("\n", page_text)
    blocks: list[TextBlock] = []
    for line in normalised.splitlines():
        text = line.strip()
        if not text:
            continue
        level = heading_level_from_text(text)
        if level is None:
            blocks.append(TextBlock(text=text, kind="paragraph"))
        else:
            blocks.append(TextBlock(text=text, kind="heading", heading_level=level))
    return blocks
