"""The grouping behind the admin screens, as pure functions.

PostgREST has no GROUP BY, so the answers to "how many students asked this" and
"which category is busiest" are computed here. Everything in this module runs
without a database, a clock or a settings object -- which is the point: the
counting rules are the part that can be wrong, and they are also the part a
fake repository would have hidden.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.services.history import (
    count_by_category,
    group_faqs,
    group_unanswered,
    top_category,
)

EARLY = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)
MIDDLE = datetime(2026, 9, 4, 9, 0, tzinfo=UTC)
LATE = datetime(2026, 9, 8, 9, 0, tzinfo=UTC)


def row(
    *,
    normalized_hash: str = "a" * 64,
    question: str = "What is the hostel mess menu?",
    category: str | None = None,
    status: str = "open",
    created_at: datetime | None = None,
    resolved_by_document: object = None,
) -> dict[str, object]:
    return {
        "id": uuid4(),
        "query_id": uuid4(),
        "normalized_hash": normalized_hash,
        "question": question,
        "category": category,
        "status": status,
        "resolved_by_document": resolved_by_document,
        "created_at": created_at or EARLY,
    }


class TestGroupUnanswered:
    def test_one_row_per_question_with_a_count(self) -> None:
        groups = group_unanswered(
            [row(created_at=LATE), row(created_at=MIDDLE), row(created_at=EARLY)]
        )

        assert len(groups) == 1
        assert groups[0]["count"] == 3

    def test_the_newest_wording_is_the_one_shown(self) -> None:
        # Newest first, which is how the query orders them -- so a group shows
        # the phrasing an admin most recently had to turn away.
        groups = group_unanswered(
            [
                row(question="mess menu?", created_at=LATE),
                row(question="what is the hostel mess menu", created_at=EARLY),
            ]
        )

        assert groups[0]["question"] == "mess menu?"

    def test_the_span_runs_from_the_first_ask_to_the_last(self) -> None:
        groups = group_unanswered([row(created_at=LATE), row(created_at=EARLY)])

        assert groups[0]["first_asked_at"] == EARLY
        assert groups[0]["last_asked_at"] == LATE

    def test_a_group_is_open_while_any_occurrence_is_open(self) -> None:
        # The alternative would drop a question out of the queue the moment one
        # of forty students had it answered -- the case where the count matters
        # most.
        groups = group_unanswered(
            [
                row(status="open", created_at=LATE),
                row(status="resolved", created_at=EARLY),
            ]
        )

        assert groups[0]["status"] == "open"

    def test_a_group_is_resolved_only_when_every_occurrence_is(self) -> None:
        groups = group_unanswered(
            [row(status="resolved", created_at=LATE), row(status="resolved", created_at=EARLY)]
        )

        assert groups[0]["status"] == "resolved"

    def test_the_newest_resolved_link_wins(self) -> None:
        recent = uuid4()
        older = uuid4()
        groups = group_unanswered(
            [
                row(status="resolved", resolved_by_document=recent, created_at=LATE),
                row(status="resolved", resolved_by_document=older, created_at=EARLY),
            ]
        )

        assert groups[0]["resolved_by_document"] == recent

    def test_questions_are_ordered_by_how_often_they_were_asked(self) -> None:
        often = "b" * 64
        groups = group_unanswered(
            [
                row(normalized_hash=often, created_at=MIDDLE),
                row(normalized_hash=often, created_at=EARLY),
                row(normalized_hash="c" * 64, created_at=LATE),
            ]
        )

        assert [group["normalized_hash"] for group in groups] == [often, "c" * 64]

    def test_a_tie_goes_to_the_most_recently_asked(self) -> None:
        groups = group_unanswered(
            [
                row(normalized_hash="b" * 64, created_at=LATE),
                row(normalized_hash="c" * 64, created_at=MIDDLE),
            ]
        )

        assert groups[0]["normalized_hash"] == "b" * 64

    def test_a_row_without_a_hash_is_skipped_rather_than_bucketed(self) -> None:
        # It cannot be grouped and it cannot be resolved either: the PATCH route
        # addresses a group by exactly this value, so "" would be a group no
        # admin could ever close.
        groups = group_unanswered([row(normalized_hash=""), row()])

        assert len(groups) == 1
        assert groups[0]["count"] == 1

    def test_rows_may_carry_timestamps_as_strings(self) -> None:
        # PostgREST sends timestamptz as ISO 8601 text; the test doubles hand
        # over datetimes. Both have to work.
        groups = group_unanswered(
            [
                row(created_at="2026-09-08T09:00:00+00:00"),  # type: ignore[arg-type]
                row(created_at="2026-09-01T09:00:00+00:00"),  # type: ignore[arg-type]
            ]
        )

        assert groups[0]["last_asked_at"] == LATE
        assert groups[0]["first_asked_at"] == EARLY

    def test_an_empty_queue_groups_to_nothing(self) -> None:
        assert group_unanswered([]) == []


class TestGroupFaqs:
    def answered(
        self,
        *,
        category: str | None,
        digest: str,
        created_at: datetime,
        question: str = "When are marks published?",
    ) -> dict[str, object]:
        return {
            "normalized_hash": digest,
            "question": question,
            "category": category,
            "created_at": created_at,
        }

    def test_counts_repeats_of_the_same_wording(self) -> None:
        groups = group_faqs(
            [
                self.answered(category="examinations", digest="a" * 64, created_at=LATE),
                self.answered(category="examinations", digest="a" * 64, created_at=EARLY),
            ],
            max_per_category=5,
        )

        assert groups[0]["items"][0]["count"] == 2
        assert groups[0]["total"] == 2

    def test_the_total_counts_every_occurrence_not_every_wording(self) -> None:
        # A truncated item list must not make the category total look smaller
        # than it is: "12 questions in examinations" is the number that says
        # whether the category is worth reading.
        groups = group_faqs(
            [
                self.answered(category="examinations", digest="a" * 64, created_at=LATE),
                self.answered(category="examinations", digest="b" * 64, created_at=MIDDLE),
                self.answered(category="examinations", digest="c" * 64, created_at=EARLY),
            ],
            max_per_category=1,
        )

        assert len(groups[0]["items"]) == 1
        assert groups[0]["total"] == 3

    def test_categories_are_ordered_by_how_much_was_asked(self) -> None:
        groups = group_faqs(
            [
                self.answered(category="admissions", digest="a" * 64, created_at=LATE),
                self.answered(category="admissions", digest="a" * 64, created_at=MIDDLE),
                self.answered(category="events", digest="b" * 64, created_at=EARLY),
            ],
            max_per_category=5,
        )

        assert [group["category"] for group in groups] == ["admissions", "events"]

    def test_unclassified_questions_are_their_own_group(self) -> None:
        # The classifier returns None rather than "general" on purpose, so a
        # null category is an absence and folding it into a real category would
        # misreport both.
        groups = group_faqs(
            [self.answered(category=None, digest="a" * 64, created_at=LATE)],
            max_per_category=5,
        )

        assert groups[0]["category"] is None

    def test_nothing_asked_groups_to_nothing(self) -> None:
        assert group_faqs([], max_per_category=5) == []


class TestCountByCategory:
    def test_categories_follow_the_display_order(self) -> None:
        # Dict insertion order would put the newest category first, which is not
        # the order the chips are in -- so the chart would move between loads.
        rows = [
            {"category": "events"},
            {"category": "examinations"},
            {"category": "examinations"},
        ]

        assert count_by_category(rows) == [
            {"category": "examinations", "count": 2},
            {"category": "events", "count": 1},
        ]

    def test_a_category_with_no_questions_is_omitted(self) -> None:
        # A fixed row of empty bars would claim the corpus covers a category it
        # has never been asked about.
        assert count_by_category([{"category": "events"}]) == [{"category": "events", "count": 1}]

    def test_unclassified_questions_are_counted_and_come_last(self) -> None:
        rows = [{"category": None}, {"category": None}, {"category": "events"}]

        assert count_by_category(rows) == [
            {"category": "events", "count": 1},
            {"category": None, "count": 2},
        ]

    def test_a_category_the_schema_does_not_know_about_is_still_shown(self) -> None:
        # A hand-edited row, or a category removed from the taxonomy later. The
        # chart claims to summarise every question, so it must not silently drop
        # one it does not recognise.
        rows = [{"category": "examinations"}, {"category": "hostel"}]

        assert count_by_category(rows) == [
            {"category": "examinations", "count": 1},
            {"category": "hostel", "count": 1},
        ]


class TestTopCategory:
    def test_the_busiest_category_wins(self) -> None:
        rows = [{"category": "events"}, {"category": "events"}, {"category": "examinations"}]

        assert top_category(rows) == ("events", 2)

    def test_a_tie_goes_to_the_display_order(self) -> None:
        # So the answer is stable between two requests rather than following
        # whichever row the database happened to return first.
        rows = [{"category": "events"}, {"category": "examinations"}]

        assert top_category(rows) == ("examinations", 1)

    def test_nothing_to_count_is_not_a_category(self) -> None:
        assert top_category([]) == (None, 0)
