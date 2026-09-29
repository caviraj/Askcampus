"""Question normalization and hashing.

FR-8 groups repeated questions by `normalized_hash`, so the properties that
matter here are that the same question written two ways hashes the same, and that
two questions which merely look alike do not.
"""

from __future__ import annotations

import pytest

from app.services.normalization import normalize_question, question_hash


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("When is the exam fee due?", "when is the exam fee due"),
        ("WHEN IS THE EXAM FEE DUE", "when is the exam fee due"),
        ("  when   is  the exam fee due  ", "when is the exam fee due"),
        ("when-is-the-exam-fee-due", "when is the exam fee due"),
        ("When is the exam fee due???", "when is the exam fee due"),
        ("When\nis\tthe exam fee due", "when is the exam fee due"),
    ],
)
def test_folds_what_means_nothing(raw: str, expected: str) -> None:
    assert normalize_question(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", "?!...", "\n\t", "---"])
def test_a_question_with_no_words_normalizes_to_nothing(raw: str) -> None:
    assert normalize_question(raw) == ""


def test_folds_compatibility_forms():
    """A full-width question is the same question.

    NFKC rather than NFC: the full-width characters this catches are what an IME
    or a copy-paste out of a PDF produces, and without folding they would be a
    different string and therefore a different hash.
    """
    assert normalize_question("ＥＸＡＭ　ＦＥＥ") == "exam fee"
    assert normalize_question("ofﬁce hours") == "office hours"


def test_hash_is_stable_across_punctuation_and_case():
    assert question_hash("When is the exam fee due?") == question_hash("when is the exam fee due")


def test_hash_separates_questions_that_are_not_the_same():
    """Deliberately no stemming, so a question and its fragment stay apart.

    Folding these together would make the admin queue report one student where
    two asked different things.
    """
    assert question_hash("is the exam fee refundable") != question_hash("is the exam fee")


def test_hash_of_nothing_is_stable():
    assert question_hash("") == question_hash("   ")


def test_hash_is_a_sha256_digest():
    digest = question_hash("When is the exam fee due?")
    assert len(digest) == 64
    assert set(digest) <= set("0123456789abcdef")
