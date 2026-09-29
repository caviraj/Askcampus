"""Answering: the fallback decision, citation validation, and the log.

The two properties worth more than the rest, because they are the ones AGENTS.md
states without qualification:

* a question whose retrieval did not clear the threshold never reaches the model
  (section 6.1 -- the prompt contains only retrieved chunks, so there is nothing
  to put in it);
* every terminal path writes the history rows, the fallback included (section
  6.6 -- "No exception").

Both are asserted against call counts and the log's own record rather than
against the answer text, so a plausible-sounding answer cannot pass a test that
was meant to prove the model was never asked.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.config import Settings
from app.providers.errors import ProviderError
from app.schemas.chat import HistoryTurn, ModelAnswer
from app.services.answering import _RULES, AnsweringService
from app.services.embedding import EmbeddingService
from app.services.fallback import FALLBACK_GENERIC, FALLBACK_OFFICE
from app.services.normalization import question_hash
from app.services.retrieval import RetrievalService
from tests.fakes import (
    FakeEmbeddingProvider,
    FakeLLMProvider,
    InMemoryChunkRepository,
    InMemoryEmbeddingCache,
    InMemoryQueryLogRepository,
    answer_payload,
)

SESSION = UUID("44444444-4444-4444-4444-444444444444")
GOOD = 0.91
WEAK = 0.2

RULE_LINES = [line.strip() for line in _RULES.splitlines()]


@dataclass
class Harness:
    service: AnsweringService
    repository: InMemoryChunkRepository
    embeddings: FakeEmbeddingProvider
    llm: FakeLLMProvider
    log: InMemoryQueryLogRepository
    # The ranking as seeded so far, best first. Kept here rather than rebuilt
    # from the repository because `prime` replaces the ranking, so seeding twice
    # without accumulating would silently discard the first one.
    ranked: list[tuple[UUID, float | None]] = field(default_factory=list)

    def seed(
        self,
        *,
        similarity: float | None = GOOD,
        category: str = "general",
        department: str | None = None,
        title: str = "Examination handbook",
        content: str = "The examination fee is due on 12 December.",
        page_number: int | None = 3,
        section_heading: str | None = "Fees",
    ) -> UUID:
        """One citable chunk, added to the ranking at the next rank."""
        document_id = self.repository.seed_document(
            title=title, department=department, category=category
        )
        chunk_id = self.repository.seed_chunk(
            document_id,
            content=content,
            page_number=page_number,
            section_heading=section_heading,
        )
        self.ranked.append((chunk_id, similarity))
        self.repository.prime(self.ranked)
        return chunk_id

    async def ask(self, question: str = "When is the examination fee due?", **kwargs: Any) -> Any:
        return await self.service.answer(session_id=SESSION, question=question, **kwargs)

    @property
    def entry(self) -> dict[str, Any]:
        assert self.log.entries, "nothing was logged"
        return self.log.entries[-1]


@pytest.fixture
def make(settings: Settings):
    def build(
        responses: list[Any] | None = None,
        *,
        llm_error: ProviderError | None = None,
        log_error: Exception | None = None,
    ) -> Harness:
        repository = InMemoryChunkRepository()
        embeddings = FakeEmbeddingProvider()
        llm = FakeLLMProvider(responses, error=llm_error)
        log = InMemoryQueryLogRepository(error=log_error)
        return Harness(
            service=AnsweringService(
                retrieval=RetrievalService(
                    EmbeddingService(embeddings, settings, InMemoryEmbeddingCache()),
                    repository,
                    settings,
                ),
                llm=llm,
                query_log=log,
            ),
            repository=repository,
            embeddings=embeddings,
            llm=llm,
            log=log,
        )

    return build


# ---------------------------------------------------------------------------
# The fallback decision, made before the model is ever called
# ---------------------------------------------------------------------------


async def test_a_weak_match_never_reaches_the_model(make: Any) -> None:
    harness = make()
    harness.seed(similarity=WEAK)

    outcome = await harness.ask()

    assert outcome.answered is False
    assert harness.llm.calls == 0


async def test_a_keyword_only_match_never_reaches_the_model(make: Any) -> None:
    """NULL similarity is no cosine evidence, so there is nothing to clear the
    threshold with -- not even when the keyword match looked exact."""
    harness = make()
    harness.seed(similarity=None)

    outcome = await harness.ask()

    assert outcome.answered is False
    assert harness.llm.calls == 0


async def test_nothing_retrieved_never_reaches_the_model(make: Any) -> None:
    harness = make()

    outcome = await harness.ask()

    assert outcome.answered is False
    assert harness.llm.calls == 0


async def test_a_match_exactly_at_the_threshold_is_answered(make: Any, settings: Settings) -> None:
    """The rule is "below the threshold", so the threshold itself is answered."""
    harness = make([answer_payload()])
    harness.seed(similarity=settings.similarity_threshold)

    outcome = await harness.ask()

    assert outcome.answered is True
    assert harness.llm.calls == 1


async def test_the_fallback_is_logged_as_unanswered(make: Any) -> None:
    """AGENTS.md section 6.6: both rows, no exception.

    `unanswered` is the flag `log_query` uses to write the second row, so this is
    the atomicity requirement as the service can express it.
    """
    harness = make()
    harness.seed(similarity=WEAK)

    await harness.ask()

    assert len(harness.log.entries) == 1
    assert harness.entry["unanswered"] is True
    assert harness.entry["answered"] is False


async def test_the_log_records_the_fallback_the_student_was_shown(make: Any) -> None:
    """Without it, the admin history shows an unanswered question and no record
    of the answer the student actually received."""
    harness = make()
    harness.seed(similarity=WEAK)

    outcome = await harness.ask()

    assert harness.entry["answer"] == outcome.answer
    assert outcome.answer == FALLBACK_GENERIC


async def test_the_office_variant_names_a_department_from_a_row(make: Any) -> None:
    harness = make()
    harness.seed(similarity=WEAK, department="Examinations")

    outcome = await harness.ask()

    assert outcome.answer == FALLBACK_OFFICE.format(office="Examinations")


async def test_a_document_with_no_department_gives_the_generic_message(make: Any) -> None:
    """Never an invented office: with no row to read it from, there is no name."""
    harness = make()
    harness.seed(similarity=WEAK, department=None)

    assert (await harness.ask()).answer == FALLBACK_GENERIC


async def test_the_office_comes_from_the_best_ranked_chunk_that_has_one(make: Any) -> None:
    """The top chunk is the likeliest to be from a document with no department
    recorded, and any of them beats naming no office at all."""
    harness = make()
    harness.seed(similarity=WEAK, department=None)
    harness.seed(similarity=WEAK, department="Admissions")

    outcome = await harness.ask()

    assert outcome.answer == FALLBACK_OFFICE.format(office="Admissions")


async def test_an_unanswerable_response_is_a_fallback(make: Any) -> None:
    """`answerable: false` is the model saying the sources do not hold it."""
    harness = make([answer_payload(answerable=False, sources=[])])
    harness.seed()

    outcome = await harness.ask()

    assert outcome.answered is False
    assert outcome.citations == []
    assert harness.entry["unanswered"] is True


async def test_a_provider_failure_falls_back_without_a_second_attempt(make: Any) -> None:
    """ARCHITECTURE.md section 5.2's "retry once" is about citation validation.

    Asking a student to sit through a second 30-second timeout serves them worse
    than telling them plainly that the documents do not answer this.
    """
    harness = make(llm_error=ProviderError("The provider is busy.", transient=True))
    harness.seed()

    outcome = await harness.ask()

    assert outcome.answered is False
    assert harness.llm.calls == 1
    assert harness.entry["unanswered"] is True


# ---------------------------------------------------------------------------
# The answer, and its citations
# ---------------------------------------------------------------------------


async def test_an_answer_is_returned_with_a_citation_from_the_cited_source(make: Any) -> None:
    harness = make([answer_payload("The fee is due on 12 December.")])
    harness.seed()

    outcome = await harness.ask()

    assert outcome.answered is True
    assert outcome.answer == "The fee is due on 12 December."
    assert len(outcome.citations) == 1
    citation = outcome.citations[0]
    assert citation.label == "S1"
    assert citation.document_title == "Examination handbook"
    assert citation.page == 3
    assert citation.section == "Fees"
    assert citation.snippet == "The examination fee is due on 12 December."
    assert citation.last_updated == datetime.fromisoformat("2026-09-10T09:00:00+00:00")


async def test_only_the_cited_sources_become_citations(make: Any) -> None:
    """A source the answer did not use is not a source slip.

    Showing all five would tell the student the answer rests on evidence it does
    not rest on.
    """
    harness = make([answer_payload(sources=["S2"])])
    harness.seed(title="First source")
    harness.seed(title="Second source", content="The late fee is 500 rupees.")

    outcome = await harness.ask()

    assert [citation.label for citation in outcome.citations] == ["S2"]
    assert outcome.citations[0].document_title == "Second source"


async def test_labels_are_matched_however_the_model_cases_them(make: Any) -> None:
    harness = make([answer_payload(sources=[" s1 "])])
    harness.seed()

    outcome = await harness.ask()

    assert outcome.answered is True
    assert [citation.label for citation in outcome.citations] == ["S1"]


async def test_the_log_records_only_the_cited_sources(make: Any) -> None:
    """`query_sources` is a record of the evidence the answer used, ranked from
    one, not of everything retrieval happened to return."""
    harness = make([answer_payload(sources=["S2"])])
    harness.seed(title="First source")
    harness.seed(title="Second source", content="The late fee is 500 rupees.")

    await harness.ask()

    assert [source.rank for source in harness.entry["sources"]] == [1]
    assert harness.entry["sources"][0].document_title == "Second source"


async def test_the_log_records_the_score_the_decision_used(make: Any) -> None:
    harness = make([answer_payload()])
    harness.seed(similarity=GOOD)

    await harness.ask()

    assert harness.entry["top_score"] == pytest.approx(GOOD)


async def test_the_log_records_the_raw_question_and_its_hash(make: Any) -> None:
    """The hash groups repeats in the admin history, so it has to be the question
    the student asked -- not the search text, which carries the history."""
    harness = make([answer_payload()])
    harness.seed()
    question = "When is the Examination Fee due?"

    await harness.ask(question=question, history=[HistoryTurn(role="user", content="hello")])

    assert harness.entry["question"] == question
    assert harness.entry["normalized_hash"] == question_hash(question)
    assert harness.entry["normalized_hash"] != question_hash(f"hello {question}")


# ---------------------------------------------------------------------------
# Citation validation, and the single retry
# ---------------------------------------------------------------------------


async def test_a_fabricated_label_is_rejected_and_asked_once_more(make: Any) -> None:
    """AGENTS.md section 6.3: validate that every id maps to a supplied chunk,
    then retry once before falling back."""
    harness = make([answer_payload(sources=["S9"]), answer_payload(sources=["S1"])])
    harness.seed()

    outcome = await harness.ask()

    assert harness.llm.calls == 2
    assert outcome.answered is True
    assert [citation.label for citation in outcome.citations] == ["S1"]


async def test_an_answerable_response_citing_nothing_is_rejected(make: Any) -> None:
    harness = make(
        [answer_payload("It is due in December.", sources=[]), answer_payload(sources=["S1"])]
    )
    harness.seed()

    outcome = await harness.ask()

    assert harness.llm.calls == 2
    assert outcome.answered is True


async def test_an_answerable_response_with_an_empty_answer_is_rejected(make: Any) -> None:
    harness = make([answer_payload("   "), answer_payload(sources=["S1"])])
    harness.seed()

    outcome = await harness.ask()

    assert harness.llm.calls == 2
    assert outcome.answered is True


async def test_two_unusable_responses_fall_back(make: Any) -> None:
    harness = make([answer_payload(sources=["S9"]), answer_payload(sources=["S8"])])
    harness.seed()

    outcome = await harness.ask()

    assert harness.llm.calls == 2
    assert outcome.answered is False
    assert harness.entry["unanswered"] is True


async def test_an_unanswerable_response_citing_a_fabricated_label_is_rejected(
    make: Any,
) -> None:
    """The subset check does not depend on `answerable`.

    A label that was never supplied is a fabricated citation whether or not the
    model claimed to have answered.
    """
    harness = make(
        [
            answer_payload(answerable=False, sources=["S9"]),
            answer_payload(answerable=False, sources=[]),
        ]
    )
    harness.seed()

    outcome = await harness.ask()

    assert harness.llm.calls == 2
    assert outcome.answered is False


async def test_the_retry_says_what_was_wrong_and_keeps_every_rule(make: Any) -> None:
    """A verbatim re-ask at temperature 0 would be near-deterministic.

    The correction sits after the source blocks, so rule 4 keeps one meaning:
    everything inside a block is data, everything outside it is instruction.
    """
    harness = make([answer_payload(sources=["S9"]), answer_payload(sources=["S1"])])
    harness.seed()

    await harness.ask()

    first, second = harness.llm.prompts
    assert second != first
    assert "S9" in second
    for line in RULE_LINES:
        assert line in second
    # Appended, not woven in: the rules and the sources keep their order.
    assert second.index("<<<END SOURCE S1>>>") < second.index("rejected")


async def test_the_model_is_asked_with_the_schema_the_contract_names(make: Any) -> None:
    """AGENTS.md section 6.2: the response is validated with Pydantic, which means
    the provider is constrained by the model class itself, not a prompt asking
    nicely for JSON."""
    harness = make([answer_payload()])
    harness.seed()

    await harness.ask()

    assert harness.llm.schemas == [ModelAnswer]


# ---------------------------------------------------------------------------
# History, categories, and a failing log
# ---------------------------------------------------------------------------


async def test_history_shapes_the_search_but_never_enters_the_prompt(make: Any) -> None:
    """AGENTS.md section 6.1 is absolute, and a previous turn is not a retrieved
    chunk. But "and the late fee?" has to retrieve sensibly, which is what the
    search text is for.
    """
    harness = make([answer_payload()])
    harness.seed()
    history = [HistoryTurn(role="assistant", content="MARKER FROM THE LAST TURN")]

    await harness.ask(question="and the late fee?", history=history)

    assert harness.embeddings.queries == ["MARKER FROM THE LAST TURN and the late fee?"]
    assert "MARKER FROM THE LAST TURN" not in harness.llm.prompts[0]


async def test_an_explicit_category_is_what_is_searched(make: Any) -> None:
    """A tapped chip filters, whatever the question would have classified as."""
    harness = make([answer_payload()])
    harness.seed(category="admissions", similarity=GOOD)

    outcome = await harness.ask("When is the examination fee due?", requested_category="admissions")

    assert harness.repository.searched == ["admissions"]
    assert outcome.category == "admissions"


async def test_the_classifier_supplies_the_category_when_none_was_asked_for(make: Any) -> None:
    harness = make([answer_payload()])
    harness.seed(category="examinations", similarity=GOOD)

    outcome = await harness.ask("When is the examination fee due?")

    assert harness.repository.searched == ["examinations"]
    assert outcome.category == "examinations"


async def test_the_all_chip_does_not_fall_back_to_the_classifier(make: Any) -> None:
    """Three cases, and the first two are not the same.

    A question that classifies as examinations, asked with the "all" chip
    selected, must search everything. Treating "all" as "no chip chosen" would
    narrow the very search the chip exists to widen.
    """
    harness = make()
    harness.seed(similarity=WEAK)

    outcome = await harness.ask("When is the examination fee due?", requested_category="all")

    assert harness.repository.searched == [None]
    assert outcome.category is None


async def test_an_unclassifiable_question_searches_everything(make: Any) -> None:
    harness = make()
    harness.seed(similarity=WEAK)

    outcome = await harness.ask("What is the wifi password?")

    assert harness.repository.searched == [None]
    assert outcome.category is None


async def test_a_query_id_is_returned_even_when_the_log_write_fails(make: Any) -> None:
    """Assumption 13: the log is attempted on every path and never fails the
    answer. The id is minted before the write, so the response has the same shape
    either way -- a feedback call against a row that never landed is a 404.
    """
    harness = make([answer_payload()], log_error=RuntimeError("the database is down"))
    harness.seed()

    outcome = await harness.ask()

    assert outcome.answered is True
    assert isinstance(outcome.query_id, UUID)
    assert harness.log.entries == []


async def test_a_fallback_still_returns_its_query_id_when_the_log_fails(make: Any) -> None:
    harness = make(log_error=RuntimeError("the database is down"))
    harness.seed(similarity=WEAK)

    outcome = await harness.ask()

    assert outcome.answered is False
    assert isinstance(outcome.query_id, UUID)


async def test_each_question_gets_its_own_query_id(make: Any) -> None:
    harness = make([answer_payload(), answer_payload()])
    harness.seed()

    first = await harness.ask()
    second = await harness.ask()

    assert first.query_id != second.query_id
    assert first.query_id != uuid4()
