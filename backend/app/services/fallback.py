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

# DESIGN_SYSTEM.md section 9, verbatim.
#
# Its second sentence says "the office below", and the low-similarity path this
# is used on has no office to show. Left as specified rather than reworded,
# flagged in the Phase 3 report for Phase 4 to resolve together with the
# "Ask the office" action in DESIGN_SYSTEM.md section 8.
FALLBACK_GENERIC = (
    "This is not in the college documents I have. Try the office below, or ask staff."
)

# DESIGN_SYSTEM.md section 9's contact-known variant, with the office named.
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


def fallback_message(chunks: Sequence[RetrievedChunk]) -> str:
    """The message for a question the documents did not answer."""
    office = office_from(chunks)
    if office is None:
        return FALLBACK_GENERIC
    return FALLBACK_OFFICE.format(office=office)
