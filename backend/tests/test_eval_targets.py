"""The `AGENTS.md` section 9 targets, pinned so they cannot regress quietly.

Section 5 step 6 asks for the evaluation; section 9 gives it numbers to reach:
answer rate at least 85 percent, citation correctness at least 95 percent, zero
answers on out-of-scope questions. Sixteen months from now those numbers are
only worth having if something goes red when a prompt, a chunk size or a
threshold moves them, and this module is that something.

It runs the same offline evaluation `python eval/run_eval.py` runs, and asserts
the same exit code that command promises. No API key, no database and no network
are involved: `eval/harness.py` substitutes a lexical embedder and a grounded
model double, so what is under test is the pipeline's decisions -- whether a
good retrieval result is answered, cited and, when it is not good enough,
refused. It says nothing about Gemini's answer quality; `--provider gemini` is
the run that does.

The rest of the module guards the fixture underneath that run. A question set
whose expected passages do not actually discriminate between documents would let
the citation check pass on a wrong citation, and the target would be measuring
nothing.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
for _path in (str(REPO_ROOT), str(REPO_ROOT / "backend")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from eval.harness import Question, corpus_documents, read_questions  # noqa: E402
from eval.run_eval import main  # noqa: E402

EVAL_DIR = REPO_ROOT / "eval"
CORPUS_DIR = EVAL_DIR / "corpus"

# Section 5 step 6, in its own words.
EXPECTED_COUNTS = {"answerable": 20, "out_of_scope": 5, "ambiguous": 5}


@pytest.fixture(scope="module")
def questions() -> list[Question]:
    return read_questions(EVAL_DIR / "questions.json")


@pytest.fixture(scope="module")
def bodies() -> dict[str, str]:
    """Each corpus document's cleaned text, lowercased, keyed by title."""
    return {
        title: "\n".join(block.text for page in document.pages for block in page.blocks).lower()
        for title, document in corpus_documents(CORPUS_DIR).items()
    }


@pytest.fixture(scope="module")
def headings() -> dict[str, list[str]]:
    """Each corpus document's heading text, keyed by title."""
    return {
        title: [
            block.text
            for page in document.pages
            for block in page.blocks
            if block.kind == "heading"
        ]
        for title, document in corpus_documents(CORPUS_DIR).items()
    }


def _of_kind(questions: list[Question], kind: str) -> Iterator[Question]:
    return (question for question in questions if question.kind == kind)


def test_the_offline_evaluation_meets_the_targets(capsys: pytest.CaptureFixture[str]) -> None:
    """The whole contract of `python eval/run_eval.py`, in one assertion.

    The exit code is the thing section 3's command promises and the thing a
    pipeline would branch on, so this asserts it rather than re-deriving the
    three comparisons. The report goes into the failure message because an exit
    code of 1 says a target was missed and the printed metrics say which.
    """
    exit_code = asyncio.run(main([]))
    report = capsys.readouterr().out
    assert exit_code == 0, f"the evaluation reported a missed target:\n\n{report}"


def test_the_question_set_is_the_one_section_5_asks_for(questions: list[Question]) -> None:
    counts = {kind: sum(1 for _ in _of_kind(questions, kind)) for kind in EXPECTED_COUNTS}
    assert counts == EXPECTED_COUNTS


def test_question_ids_are_unique(questions: list[Question]) -> None:
    ids = [question.id for question in questions]
    assert len(set(ids)) == len(ids)


def test_every_cited_document_exists_in_the_corpus(
    questions: list[Question], bodies: dict[str, str]
) -> None:
    """A typo in a title would make a question unanswerable by accident.

    `expected_document` is compared against the citation's document title, so a
    misspelling here does not fail the fixture -- it fails every run of it, and
    the failure looks like a retrieval regression.
    """
    for question in questions:
        for field in ("expected_document", "related_document"):
            named = getattr(question, field)
            if named is not None:
                assert named in bodies, f"{question.id} names {named!r}, which is not in the corpus"


def test_expected_sections_name_a_real_heading(
    questions: list[Question], headings: dict[str, list[str]]
) -> None:
    for question in _of_kind(questions, "answerable"):
        assert question.expected_document is not None
        candidates = headings[question.expected_document]
        assert any(question.expected_section or "" in heading for heading in candidates), (
            f"{question.id} expects section {question.expected_section!r}, "
            f"which is not a heading in {question.expected_document}"
        )


def test_expected_terms_name_one_document_only(
    questions: list[Question], bodies: dict[str, str]
) -> None:
    """The property that makes a citation check mean anything.

    If the passage an answer should cite is also in some other document, a
    citation to that other document satisfies the check and the citation
    correctness target counts a wrong answer as a right one. Each term is
    therefore required to occur in the expected document and in no other -- over
    the cleaned text the chunker sees, because a term straddling a line break in
    the raw file looks absent when it is present.
    """
    for question in _of_kind(questions, "answerable"):
        assert question.expected_terms, f"{question.id} has no expected_terms"
        for term in question.expected_terms:
            found = [title for title, body in bodies.items() if term.lower() in body]
            assert found == [question.expected_document], (
                f"{question.id} expects {term!r} to identify "
                f"{question.expected_document!r}, but it occurs in {found}"
            )
