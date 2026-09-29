"""AdminHistoryService against a fake repository.

The API tests cover the same code through HTTP; what is left for here is
everything that needs the reporting window to be small enough to reason about.
`admin_aggregate_row_limit` is five thousand in production, and a test that
seeded five thousand rows to prove a flag would be a test nobody runs twice.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.config import Settings
from app.services.history import AdminHistoryService, UnknownDocumentError
from tests.fakes import TEST_SUPABASE_URL, InMemoryHistoryRepository

NOW = datetime.now(UTC)


def build(
    *, window_limit: int = 100, window_days: int = 7
) -> tuple[AdminHistoryService, InMemoryHistoryRepository]:
    settings = Settings(
        _env_file=None,
        supabase_url=TEST_SUPABASE_URL,
        supabase_service_role_key="test-service-role-key",
        gemini_api_key="test-gemini-api-key",
        admin_aggregate_row_limit=window_limit,
        stats_window_days=window_days,
    )
    repository = InMemoryHistoryRepository()
    return AdminHistoryService(repository, settings), repository


class TestTruncation:
    async def test_a_full_window_is_reported_as_truncated(self) -> None:
        service, repository = build(window_limit=3)
        for index in range(3):
            repository.seed_unanswered(question=f"Question {index}")

        _items, _total, truncated = await service.list_unanswered(limit=10, offset=0)

        assert truncated is True

    async def test_a_window_with_room_left_is_not(self) -> None:
        service, repository = build(window_limit=5)
        for index in range(3):
            repository.seed_unanswered(question=f"Question {index}")

        _items, _total, truncated = await service.list_unanswered(limit=10, offset=0)

        assert truncated is False

    async def test_the_faq_window_reports_the_same_way(self) -> None:
        service, repository = build(window_limit=2)
        repository.seed_query(question="One")
        repository.seed_query(question="Two")

        _groups, truncated = await service.faqs()

        assert truncated is True

    async def test_a_truncated_stats_window_says_so(self) -> None:
        service, repository = build(window_limit=1)
        repository.seed_query(question="One", created_at=NOW)
        repository.seed_query(question="Two", created_at=NOW)

        data = await service.stats(preview_limit=5)

        assert data["truncated"] is True

    async def test_the_cards_stay_exact_when_the_chart_is_not(self) -> None:
        # The chart is grouped from a bounded window; the counts are head
        # requests. So a truncated chart beside exact cards is the designed
        # outcome, not a contradiction.
        service, repository = build(window_limit=1)
        for index in range(5):
            repository.seed_query(question=f"Question {index}", created_at=NOW)

        data = await service.stats(preview_limit=5)

        assert data["truncated"] is True
        assert data["questions"]["value"] == 5


class TestStatsWindow:
    async def test_a_row_on_the_boundary_is_counted_once(self) -> None:
        # The windows are half-open: [since, until). Without that, the row
        # exactly `window_days` old would be in both periods, and the change
        # from the previous week would be wrong by one every time.
        service, repository = build(window_days=7)
        repository.seed_query(question="Inside", created_at=NOW - timedelta(days=1))
        repository.seed_query(question="Previous", created_at=NOW - timedelta(days=8))

        data = await service.stats(preview_limit=5)

        assert data["questions"] == {"value": 1, "previous": 1}

    async def test_a_row_older_than_both_windows_is_in_neither(self) -> None:
        service, repository = build(window_days=7)
        repository.seed_query(question="Ancient", created_at=NOW - timedelta(days=30))

        data = await service.stats(preview_limit=5)

        assert data["questions"] == {"value": 0, "previous": 0}

    async def test_the_top_category_compares_against_the_previous_window(self) -> None:
        service, repository = build(window_days=7)
        repository.seed_query(category="admissions", created_at=NOW)
        repository.seed_query(category="events", created_at=NOW - timedelta(days=9))

        data = await service.stats(preview_limit=5)

        assert data["top_category"]["category"] == "admissions"
        assert data["top_category"]["previous_category"] == "events"

    async def test_nothing_in_either_window_is_not_an_error(self) -> None:
        service, _repository = build()

        data = await service.stats(preview_limit=5)

        assert data["top_category"] == {
            "category": None,
            "count": 0,
            "previous_category": None,
            "previous_count": 0,
        }
        assert data["categories"] == []


class TestResolveUnanswered:
    async def test_an_unknown_hash_returns_nothing(self) -> None:
        service, _repository = build()

        result = await service.resolve_unanswered(
            "a" * 64, status="resolved", resolved_by_document=None
        )

        assert result is None

    async def test_an_unknown_document_raises_before_writing(self) -> None:
        service, repository = build()
        digest = repository.seed_unanswered()

        with pytest.raises(UnknownDocumentError):
            await service.resolve_unanswered(
                digest, status="resolved", resolved_by_document=uuid4()
            )

        assert repository.updates == []

    async def test_the_returned_group_is_the_one_the_queue_shows(self) -> None:
        service, repository = build()
        document_id = repository.seed_document("Hostel Rules")
        digest = repository.seed_unanswered(question="Mess menu?", created_at=NOW)
        repository.seed_unanswered(question="Mess menu?", created_at=NOW - timedelta(days=1))

        group = await service.resolve_unanswered(
            digest, status="resolved", resolved_by_document=document_id
        )

        assert group is not None
        assert group["count"] == 2
        assert group["status"] == "resolved"
        assert group["resolved_by_document_title"] == "Hostel Rules"
