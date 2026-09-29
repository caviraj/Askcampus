"""Query category classification, by rules only.

ARCHITECTURE.md section 5.2 describes "rules first, LLM fallback". Only the rules
are implemented, decided with the user: a second model call on every question the
rules miss would double the quota cost of the one feature the embedding cache
exists to protect, and it would add a network round trip before retrieval even
starts.

The consequence is chosen rather than tolerated. A category is used only to
*narrow* retrieval, and an unclassified question searches everything, so a rule
that misses costs a little precision and never an answer. That is why an
ambiguous question is classified as nothing at all rather than guessed at.
"""

from __future__ import annotations

import re
from typing import get_args

from app.schemas.chat import CategoryChip, CategoryFilter
from app.schemas.documents import Category
from app.services.normalization import normalize_question

# Keyword rules per category. Matched on word boundaries against the normalized
# question -- lowercase, single-spaced, punctuation already removed -- so a
# phrase like "cut off" is a phrase and not two coincidental word fragments.
_RULES: dict[Category, tuple[str, ...]] = {
    "examinations": (
        "exam",
        "examination",
        "exam form",
        "hall ticket",
        "admit card",
        "invigilator",
        "revaluation",
        "supplementary",
        "internal assessment",
        "viva",
        "result",
        "marks",
        "grade",
        "grading",
        "fee",
        "late fee",
        "fee payment",
    ),
    "admissions": (
        "admission",
        "application",
        "application form",
        "eligibility",
        "entrance",
        "cut off",
        "merit list",
        "quota",
        "reservation",
        "prospectus",
        "enrolment",
        "enrollment",
        "counselling",
        "counseling",
        "waitlist",
        "seat",
        "fee structure",
        "admission fee",
    ),
    "departments": (
        "department",
        "hod",
        "head of department",
        "faculty",
        "professor",
        "staff",
        "warden",
        "hostel",
        "canteen",
        "library",
        "laboratory",
        "lab",
        "campus",
        "building",
        "office",
        "contact",
        "phone",
        "email",
    ),
    "events": (
        "event",
        "fest",
        "festival",
        "cultural",
        "sports",
        "competition",
        "seminar",
        "workshop",
        "conference",
        "guest lecture",
        "orientation",
        "convocation",
        "annual day",
        "holiday",
        "timetable",
        "schedule",
        "calendar",
    ),
    "academic_processes": (
        "registration",
        "register",
        "course",
        "subject",
        "syllabus",
        "curriculum",
        "credit",
        "attendance",
        "transcript",
        "certificate",
        "bonafide",
        "migration",
        "transfer certificate",
        "scholarship",
        "internship",
        "dissertation",
        "thesis",
        "promotion",
        "graduation",
        "degree",
        "marksheet",
        "semester",
        "leave",
    ),
    # Deliberately narrow. Most questions that happen to contain the word
    # "general" want everything searched, and answering them with a filter down to
    # the general-filed documents would be worse than not classifying them at all.
    "general": (
        "general",
        "miscellaneous",
        "other",
    ),
}

CATEGORY_LABELS: dict[Category, str] = {
    "examinations": "Examinations",
    "admissions": "Admissions",
    "departments": "Departments",
    "events": "Events",
    "academic_processes": "Academic processes",
    "general": "General",
}

# DESIGN_SYSTEM.md section 8: "Tapping a chip filters retrieval and shows three
# starter questions." No specification defines the questions themselves, so these
# are authored content rather than derived from a document -- placeholders for
# review, chosen to be the kind of thing a college actually publishes.
#
# Chosen so that each one survives `classify` on its own: a chip's own starter
# questions classifying as a different category would read as a bug even though
# tapping the chip filters explicitly and never consults the classifier.
STARTER_QUESTIONS: dict[CategoryFilter, tuple[str, ...]] = {
    "examinations": (
        "When is the examination fee due?",
        "What is the late fee if I pay after the due date?",
        "What is the revaluation fee for an answer sheet?",
    ),
    "admissions": (
        "What documents do I need for admission?",
        "When does the admission form open?",
        "What is the eligibility for the entrance test?",
    ),
    "departments": (
        "Who is the head of the Computer Science department?",
        "Where is the hostel warden's office?",
        "What are the library timings?",
    ),
    "events": (
        "When is the annual day this year?",
        "What events are planned for the cultural fest?",
        "Is there a holiday on the day of the seminar?",
    ),
    "academic_processes": (
        "When does course registration close?",
        "How do I get a bonafide certificate?",
        "What is the minimum attendance required?",
    ),
    # Questions whose answers live in a notices or handbook document, and which
    # match no category rule -- which is the honest demonstration of what this
    # chip does: it searches everything rather than narrowing.
    "general": (
        "What is the college address?",
        "Where is the notice board?",
        "What are the college timings?",
    ),
    "all": (
        "When is the examination fee due?",
        "What documents do I need for admission?",
        "How do I apply for a bonafide certificate?",
    ),
}


def _pattern(phrase: str) -> re.Pattern[str]:
    """Word-boundary match, tolerant of a trailing plural.

    `(?:s|es)?` rather than a stemmer: it is enough for "fee"/"fees" and
    "process"/"processes" without pulling in a dependency, and it cannot match
    inside a longer word.
    """
    return re.compile(rf"\b{re.escape(phrase)}(?:s|es)?\b")


_PATTERNS: dict[Category, tuple[re.Pattern[str], ...]] = {
    category: tuple(_pattern(phrase) for phrase in phrases) for category, phrases in _RULES.items()
}


def classify(question: str) -> Category | None:
    """The question's category, or None when the rules cannot decide.

    Normalizes internally rather than trusting the caller: a raw question reaching
    these patterns with a capital letter would match nothing, and the failure
    would be a silent loss of precision rather than anything visible.

    Scores each category by how many distinct phrases it matches and takes the
    highest. A tie is None -- "what is the admission fee structure" matches
    admissions twice and examinations once, which is a decision worth making, but
    a question genuinely split between two categories is one that should search
    both.
    """
    text = normalize_question(question)
    if not text:
        return None

    scores = {
        category: sum(1 for pattern in patterns if pattern.search(text))
        for category, patterns in _PATTERNS.items()
    }
    best = max(scores.values(), default=0)
    if best == 0:
        return None

    winners = [category for category, score in scores.items() if score == best]
    return winners[0] if len(winners) == 1 else None


def category_chips() -> list[CategoryChip]:
    """The chip list for GET /categories, in DESIGN_SYSTEM.md section 8's order.

    "all" comes from CategoryFilter rather than from Category, because it is not a
    documents.category value -- it is the absence of a filter.
    """
    ordered: list[CategoryFilter] = [*get_args(Category), "all"]
    return [
        CategoryChip(
            value=value,
            label="All" if value == "all" else CATEGORY_LABELS[value],
            starter_questions=list(STARTER_QUESTIONS[value]),
        )
        for value in ordered
    ]
