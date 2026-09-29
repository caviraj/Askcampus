"""Heading-aware chunking.

Turns a cleaned document into the rows that go into `chunks`. Deterministic by
construction -- no randomness, no dependence on dict ordering, no clock -- so the
same bytes always produce the same chunks. That is what makes the unit tests
meaningful and the Phase 6 evaluation reproducible.

Two rules are worth stating because they are not obvious:

**Overlap never crosses a heading boundary.** Carrying text backwards across
sections would leave a chunk holding text its own `section_heading` does not name,
and AGENTS.md section 5 requires citation fields to match reality. Overlap is a
within-section continuity device only.

**The heading is part of the chunk text.** `hybrid_search` searches `content`, and
the generated `fts` column is derived from it (migration 0001), so a chunk about
registration dates cannot be matched by the keyword "Registration" unless the
heading is in the text. It costs a handful of tokens and materially improves the
keyword arm. The heading is a breadcrumb of the enclosing sections, so a
level-3 heading under a level-1 one is cited as "Examination Fees > Late payment"
rather than losing its context.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

from app.config import Settings
from app.services.extraction import BlockKind, ExtractedDocument
from app.services.tokens import count_tokens

# Sentence boundaries, used only when a single block is larger than a whole chunk.
_SENTENCES = re.compile(r"(?<=[.!?])\s+")
# Rough characters per token, for the last-resort cut of a single huge sentence.
_CHARS_PER_TOKEN = 4
_MAX_HEADING_LEVEL = 3


@dataclass(frozen=True)
class Chunk:
    """One row destined for the `chunks` table, minus its embedding."""

    index: int
    content: str
    page_number: int | None
    section_heading: str | None
    token_count: int


@dataclass(frozen=True)
class _Unit:
    """The smallest indivisible piece of text, and where it came from."""

    text: str
    kind: BlockKind
    page_number: int | None


@dataclass
class _Section:
    heading: str | None
    units: list[_Unit]


def chunk_document(document: ExtractedDocument, settings: Settings) -> list[Chunk]:
    """Split a cleaned document into chunks, indexed densely from zero."""
    chunks: list[Chunk] = []
    for section in _sections(document):
        chunks.extend(_chunk_section(section, settings, start_index=len(chunks)))
    return chunks


def _sections(document: ExtractedDocument) -> list[_Section]:
    """Group units under the heading breadcrumb that encloses them."""
    sections: list[_Section] = []
    stack: list[tuple[int, str]] = []
    current = _Section(heading=None, units=[])

    for page in document.pages:
        for block in page.blocks:
            if block.kind == "heading":
                # A heading with no body carries no answerable content, so it is
                # not emitted as a section of its own.
                if current.units:
                    sections.append(current)
                level = min(block.heading_level or 1, _MAX_HEADING_LEVEL)
                while stack and stack[-1][0] >= level:
                    stack.pop()
                stack.append((level, block.text))
                current = _Section(heading=" > ".join(text for _, text in stack), units=[])
                continue

            if block.text.strip():
                current.units.append(
                    _Unit(text=block.text, kind=block.kind, page_number=page.page_number)
                )

    if current.units:
        sections.append(current)
    return sections


def _chunk_section(section: _Section, settings: Settings, start_index: int) -> list[Chunk]:
    prefix = f"{section.heading}\n\n" if section.heading else ""
    prefix_tokens = count_tokens(prefix)
    budget = max(settings.chunk_max_tokens - prefix_tokens, 1)

    units = _explode_oversized(section.units, budget)

    chunks: list[Chunk] = []
    buffer: list[_Unit] = []
    # Units in the buffer that have not been emitted yet. Tracked separately from
    # `buffer` because the buffer also holds carried-over overlap text, and the
    # trailing-merge must not append that text a second time.
    fresh: list[_Unit] = []
    buffer_tokens = prefix_tokens

    def emit(units_to_emit: list[_Unit]) -> None:
        body = "\n".join(unit.text for unit in units_to_emit)
        content = f"{prefix}{body}"
        chunks.append(
            Chunk(
                index=start_index + len(chunks),
                content=content,
                # The page the chunk starts on. A chunk can span a page break, and
                # the citation must name the page the text begins on.
                page_number=units_to_emit[0].page_number,
                section_heading=section.heading,
                token_count=count_tokens(content),
            )
        )

    for unit in units:
        cost = count_tokens(unit.text)
        if buffer and (
            buffer_tokens + cost > settings.chunk_max_tokens
            or buffer_tokens >= settings.chunk_target_tokens
        ):
            emit(buffer)
            buffer = _overlap_tail(buffer, settings.chunk_overlap_tokens)
            fresh = []
            buffer_tokens = prefix_tokens + sum(count_tokens(item.text) for item in buffer)

        buffer.append(unit)
        fresh.append(unit)
        buffer_tokens += cost

    if not fresh:
        # The loop ended exactly on a flush; the buffer now holds nothing but
        # overlap text that has already been emitted.
        return chunks

    fresh_tokens = sum(count_tokens(unit.text) for unit in fresh)
    if fresh_tokens < settings.chunk_min_tokens and chunks:
        # A stub: fold the remainder into the previous chunk rather than indexing
        # a two-word fragment. Only `fresh` is appended, so carried-over text is
        # not duplicated.
        previous = chunks[-1]
        merged = f"{previous.content}\n" + "\n".join(unit.text for unit in fresh)
        chunks[-1] = replace(previous, content=merged, token_count=count_tokens(merged))
        return chunks

    emit(buffer)
    return chunks


def _overlap_tail(units: list[_Unit], overlap_tokens: int) -> list[_Unit]:
    """Whole trailing units worth up to `overlap_tokens`, for continuity.

    Never returns every unit: that would make the next chunk identical to this one
    and the packing loop would never terminate.
    """
    if len(units) <= 1 or overlap_tokens <= 0:
        return []

    carried: list[_Unit] = []
    total = 0
    for unit in reversed(units):
        cost = count_tokens(unit.text)
        if total + cost > overlap_tokens:
            break
        carried.insert(0, unit)
        total += cost

    if len(carried) >= len(units):
        return carried[1:]
    return carried


def _explode_oversized(units: list[_Unit], budget: int) -> list[_Unit]:
    """Split any block too large to fit a chunk on its own.

    Table rows are exempt: a row split across two chunks is worse than a chunk
    that is over budget, because half a fee table is unreadable.
    """
    exploded: list[_Unit] = []
    for unit in units:
        if unit.kind == "table_row" or count_tokens(unit.text) <= budget:
            exploded.append(unit)
        else:
            exploded.extend(_split_text(unit, budget))
    return exploded


def _split_text(unit: _Unit, budget: int) -> list[_Unit]:
    """Split on sentence boundaries, with a hard cut as a last resort."""
    pieces: list[str] = []
    current = ""

    for sentence in _SENTENCES.split(unit.text):
        sentence = sentence.strip()
        if not sentence:
            continue
        if count_tokens(sentence) > budget:
            if current:
                pieces.append(current)
                current = ""
            pieces.extend(_hard_split(sentence, budget))
            continue
        candidate = f"{current} {sentence}".strip() if current else sentence
        if current and count_tokens(candidate) > budget:
            pieces.append(current)
            current = sentence
        else:
            current = candidate

    if current:
        pieces.append(current)
    return [_Unit(text=piece, kind=unit.kind, page_number=unit.page_number) for piece in pieces]


def _hard_split(text: str, budget: int) -> list[str]:
    """Cut a single sentence with no usable boundaries into budget-sized parts."""
    stride = max(budget * _CHARS_PER_TOKEN, 1)
    return [text[start : start + stride] for start in range(0, len(text), stride)]
