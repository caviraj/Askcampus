"""The token approximation.

The exact numbers matter less than three properties: it is deterministic, empty
input is zero, and it never under-counts badly enough to overflow a chunk. The
tests pin the first two exactly and the third as a bound.
"""

from __future__ import annotations

import pytest

from app.services.tokens import count_tokens


def test_empty_input_is_zero() -> None:
    assert count_tokens("") == 0


def test_whitespace_only_is_zero() -> None:
    """Whitespace is not a token, so a page of blank lines costs nothing.

    This is what lets the chunker use token counts as its only size signal
    without every blank line inflating a chunk.
    """
    assert count_tokens("   \n\n\t ") == 0


def test_a_short_word_costs_one_token() -> None:
    assert count_tokens("fee") == 1


def test_longer_words_cost_more_than_shorter_ones() -> None:
    assert count_tokens("registration") > count_tokens("fee")


def test_digits_cost_more_than_letters_of_the_same_length() -> None:
    """A number is split into shorter subword pieces than a word is."""
    assert count_tokens("1234567890") > count_tokens("abcdefghij")


def test_punctuation_is_never_free() -> None:
    assert count_tokens("...") == 3


def test_is_deterministic() -> None:
    text = "The examination fee for semester 3 is 500 rupees, payable by 12 December 2026."
    assert count_tokens(text) == count_tokens(text)
    assert count_tokens(text) > 0


def test_over_estimates_rather_than_under_estimates() -> None:
    """The direction of the error is the point.

    A four-characters-per-token heuristic is the usual rough rule for English
    prose; the approximation must not come out below it, because under-counting
    overflows the model's context while over-counting only makes chunks smaller.
    """
    prose = "The hostel application must be submitted before the end of June."
    assert count_tokens(prose) >= len(prose) / 4


def test_scales_with_length() -> None:
    short = count_tokens("The fee is 500 rupees.")
    long = count_tokens("The fee is 500 rupees. " * 10)
    assert long > short * 5


@pytest.mark.parametrize(
    "text",
    [
        "500",
        "12 December 2026",
        "regis-tration",
        "student's",
        "II",
        "’quoted’",
        "a1b2c3",
    ],
)
def test_never_returns_a_negative_or_zero_count_for_real_text(text: str) -> None:
    assert count_tokens(text) >= 1
