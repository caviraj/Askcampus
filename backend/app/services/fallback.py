"""What the student is told when the documents do not answer the question.

Everything here is copy, not logic, except one lookup: when retrieval found
something that merely scored too low, the best-ranked chunk's document usually
names the office that would know. That name is read from `documents.department`
and never invented -- `AGENTS.md` section 6 forbids fabricating a contact, and
the surest way to keep that promise is to have no string in this module that
could become one.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.services.retrieval import RetrievedChunk

# DESIGN_SYSTEM.md section 9's "Fallback" row, first sentence only.
#
# The row in full reads: "This is not in the college documents I have. Try the
# office below, or ask staff." The second sentence is dropped, and only on this
# path: nothing retrieved names a department, so there is no office below, and
# `[Ask staff]` is not built because there is no contacts table. A sentence
# pointing at two things that are not on the screen is worse than a shorter one
# that points at nothing.
#
# Purely subtractive -- the first sentence is byte-identical to the spec and the
# second is removed, never reworded. DESIGN_SYSTEM.md section 9 is locked, so
# this is agreed with the user and recorded in the Phase 4 report.
FALLBACK_GENERIC = "This is not in the college documents I have."

# DESIGN_SYSTEM.md section 9's "Fallback (contact known)" row, with the office
# named. Self-contained: it names the office rather than pointing at one, so it
# needs no second sentence removed and no action behind it.
FALLBACK_OFFICE = "This is not in the documents I have. The {office} handles this."


def office_from(chunks: Sequence[RetrievedChunk]) -> str | None:
    """The department of the best-ranked chunk that has one, or None.

    First non-null in rank order rather than the top chunk's value outright: the
    top chunk is the one most likely to be from a document with no department
    recorded, and any of them beats naming no office at all.
    """
    for chunk in chunks:
        if chunk.department:
            return chunk.department
    return None


def fallback_for(chunks: Sequence[RetrievedChunk]) -> tuple[str, str | None]:
    """The message for a question the documents did not answer, and the office it names.

    Both together, because they are one decision. The route reports the office
    this function chose; recomputing it at the call site would be a second place
    that has to agree about which chunk won, and the two could drift -- leaving
    the student with a message naming one office and a card naming another.
    """
    office = office_from(chunks)
    if office is None:
        return FALLBACK_GENERIC, None
    return FALLBACK_OFFICE.format(office=office), office


def fallback_message(chunks: Sequence[RetrievedChunk]) -> str:
    """The message alone, for a caller with nowhere to put the office."""
    return fallback_for(chunks)[0]
