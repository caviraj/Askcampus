"""Question normalization.

One job: turn questions that mean the same thing into the same string, so
FR-8's grouping by `normalized_hash` counts "What is the exam fee?" and "what is
the exam fee" once rather than twice.

Deliberately no stemming and no stop-word removal. Both would fold more questions
together, and both would also fold together questions that are not the same
question -- "is the exam fee refundable" and "is the exam fee" would collide, and
the admin queue would report one student instead of two. AGENTS.md section 12
rules out embedding-based clustering of unanswered questions, so this is the
whole of the grouping logic.
"""

from __future__ import annotations

import re
import unicodedata

from app.services.hashing import sha256_hex

# Everything that is not a letter or digit becomes a separator. Runs collapse, so
# punctuation, spacing and line breaks all normalize to a single space.
_NOT_ALPHANUMERIC = re.compile(r"[^0-9a-z]+")


def normalize_question(text: str) -> str:
    """Fold a question to lowercase words separated by single spaces.

    NFKC first, so a full-width or ligature form of a character is compared as
    the character it means rather than as a different one.
    """
    folded = unicodedata.normalize("NFKC", text).casefold()
    return _NOT_ALPHANUMERIC.sub(" ", folded).strip()


def question_hash(text: str) -> str:
    """Stable key for grouping repeated questions.

    Hashes the normalized form, not the raw text, so the hash is stable across
    the punctuation and casing differences that carry no meaning.
    """
    return sha256_hex(normalize_question(text))
