"""The category rules.

The taxonomy is a `Literal` in the documents schema, so the tests here are about
the rules themselves: what they catch, and -- more often the interesting case --
what they deliberately refuse to decide.
"""

from __future__ import annotations

from typing import get_args

import pytest

from app.schemas.documents import Category
from app.services.classifier import (
    CATEGORY_LABELS,
    STARTER_QUESTIONS,
    category_chips,
    classify,
)

# DESIGN_SYSTEM.md section 8's chips, in its order.
CHIP_ORDER = [
    "examinations",
    "admissions",
    "departments",
    "events",
    "academic_processes",
    "general",
    "all",
]


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("When is the examination fee due?", "examinations"),
        ("How do I apply for a revaluation of my answer sheet?", "examinations"),
        ("What documents do I need for admission?", "admissions"),
        ("What is the eligibility for the entrance test?", "admissions"),
        ("Who is the head of the Computer Science department?", "departments"),
        ("Where is the hostel warden's office?", "departments"),
        ("When is the annual day this year?", "events"),
        ("What events are planned for the cultural fest?", "events"),
        ("When does course registration close?", "academic_processes"),
        ("How do I get a bonafide certificate?", "academic_processes"),
    ],
)
def test_classifies_representative_phrasing(question: str, expected: str) -> None:
    assert classify(question) == expected


@pytest.mark.parametrize(
    "question",
    [
        "What is the wifi password?",
        "What is the capital of France?",
        "who won the match last night",
        "",
        "   ",
        "?!...",
    ],
)
def test_an_unrecognised_question_is_not_filtered(question: str) -> None:
    """None, not "general".

    "general" is a real document category, so defaulting to it would filter
    retrieval down to the general-filed documents and hide the answer whenever
    the rules missed. None means search everything.
    """
    assert classify(question) is None


@pytest.mark.parametrize(
    "question",
    [
        "exam registration",
        "hostel fee",
        "where is the examination cell office",
    ],
)
def test_a_question_split_between_categories_is_left_unfiltered(question: str) -> None:
    """A tie is not a coin toss.

    Each of these matches two categories equally well, and picking either would
    be a guess that narrows retrieval. Searching both is what the question asked
    for.
    """
    assert classify(question) is None


def test_a_clear_winner_beats_a_single_incidental_word():
    """Two matches beat one, so the incidental word does not decide.

    "admission fee" matches admissions twice and examinations once; the answer
    belongs with admissions.
    """
    assert classify("what is the admission fee") == "admissions"


def test_keywords_match_on_word_boundaries():
    assert classify("what are the fees") == "examinations"
    # "examiner" contains "exam" but is not the word "exam".
    assert classify("the examiner arrived") is None


def test_classification_ignores_case_and_punctuation():
    assert classify("WHEN IS THE EXAM FEE DUE???") == "examinations"


def test_the_taxonomy_is_the_documents_taxonomy():
    """One Literal, not two.

    A category added to the documents schema must not be able to go missing from
    the chips, or the chip list would silently stop offering it.
    """
    chip_values = {chip.value for chip in category_chips()}
    assert set(get_args(Category)) <= chip_values
    assert chip_values - {"all"} == set(get_args(Category))
    assert set(CATEGORY_LABELS) == set(get_args(Category))
    assert set(STARTER_QUESTIONS) == chip_values


def test_chips_are_in_the_documented_order():
    assert [chip.value for chip in category_chips()] == CHIP_ORDER


def test_the_all_chip_is_labelled_all():
    """The values are lowercase machine names; the labels are what a student reads."""
    labels = {chip.value: chip.label for chip in category_chips()}
    assert labels["all"] == "All"
    assert labels["academic_processes"] == "Academic processes"


@pytest.mark.parametrize("value", CHIP_ORDER)
def test_every_chip_offers_three_starter_questions(value: str) -> None:
    """DESIGN_SYSTEM.md section 8: "shows three starter questions"."""
    chip = next(chip for chip in category_chips() if chip.value == value)
    assert len(chip.starter_questions) == 3
    assert all(question.strip() for question in chip.starter_questions)
    assert len(set(chip.starter_questions)) == 3


@pytest.mark.parametrize("value", [value for value in CHIP_ORDER if value != "all"])
def test_a_chips_own_questions_classify_as_that_chip(value: str) -> None:
    """Authored content, checked against the rules that will process it.

    A chip whose own starter questions classify as something else would read as a
    bug, even though tapping the chip filters explicitly and never consults the
    classifier. "general" is the exception it proves: its questions match no rule,
    which is what that chip is for.
    """
    expected = None if value == "general" else value
    for question in STARTER_QUESTIONS[value]:
        assert classify(question) == expected, question


def test_the_all_chip_offers_questions_that_do_classify():
    """Its point is that the whole set is searchable, so its examples should be
    the ones a category would have caught."""
    for question in STARTER_QUESTIONS["all"]:
        assert classify(question) is not None
