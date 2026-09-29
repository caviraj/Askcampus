"""The five admin reads, through the API.

The repository is a fake but the service behind the routes is real, so the
grouping, the reporting window, the truncation flag and the "unanswered is
questions minus answered" invariant are all exercised rather than mocked. The
fake reproduces the filters the SQL applies, so `answered=false` and
`status=open` mean what they say here.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest

from tests.conftest import ADMIN_ID
from tests.fakes import InMemoryHistoryRepository

# Inside the reporting window, and outside it. Anchored to the test run so the
# service's own `datetime.now(UTC)` is what they are compared against.
NOW = datetime.now(UTC)


def hash_of(question: str) -> str:
    return hashlib.sha256(question.encode()).hexdigest()


class TestQueryHistory:
    async def test_returns_the_question_with_its_sources_and_rating(
        self, authorized: httpx.AsyncClient, history_repository: InMemoryHistoryRepository
    ) -> None:
        history_repository.seed_query(
            question="When are marks published?",
            source_count=2,
            helpful=True,
        )

        response = await authorized.get("/admin/queries")

        assert response.status_code == 200
        item = response.json()["items"][0]
        assert item["question"] == "When are marks published?"
        assert [source["rank"] for source in item["sources"]] == [1, 2]
        assert item["sources"][0]["document_title"] == "Document 1"
        assert item["helpful"] is True

    async def test_an_unrated_question_is_null_rather_than_not_helpful(
        self, authorized: httpx.AsyncClient, history_repository: InMemoryHistoryRepository
    ) -> None:
        # The tri-state matters: a student who did not rate an answer has not
        # said it was unhelpful, and a table that rendered null as "no" would
        # report every unanswered rating as a complaint.
        history_repository.seed_query(helpful=None)

        response = await authorized.get("/admin/queries")

        assert response.json()["items"][0]["helpful"] is None

    async def test_filters_to_fallbacks_only(
        self, authorized: httpx.AsyncClient, history_repository: InMemoryHistoryRepository
    ) -> None:
        history_repository.seed_query(question="Answered one", answered=True)
        history_repository.seed_query(question="Fallen back", answered=False)

        response = await authorized.get("/admin/queries", params={"answered": "false"})

        body = response.json()
        assert body["total"] == 1
        assert [item["question"] for item in body["items"]] == ["Fallen back"]

    async def test_filters_by_category(
        self, authorized: httpx.AsyncClient, history_repository: InMemoryHistoryRepository
    ) -> None:
        history_repository.seed_query(category="examinations")
        history_repository.seed_query(category="admissions")

        response = await authorized.get("/admin/queries", params={"category": "admissions"})

        assert [item["category"] for item in response.json()["items"]] == ["admissions"]

    async def test_pages_without_losing_the_total(
        self, authorized: httpx.AsyncClient, history_repository: InMemoryHistoryRepository
    ) -> None:
        for index in range(3):
            history_repository.seed_query(
                question=f"Question {index}",
                created_at=NOW - timedelta(minutes=index),
            )

        response = await authorized.get("/admin/queries", params={"limit": 2, "offset": 0})

        body = response.json()
        assert len(body["items"]) == 2
        assert body["total"] == 3
        assert body["limit"] == 2

        second = await authorized.get("/admin/queries", params={"limit": 2, "offset": 2})
        assert len(second.json()["items"]) == 1

    async def test_newest_first(
        self, authorized: httpx.AsyncClient, history_repository: InMemoryHistoryRepository
    ) -> None:
        history_repository.seed_query(question="Older", created_at=NOW - timedelta(hours=2))
        history_repository.seed_query(question="Newer", created_at=NOW - timedelta(minutes=5))

        response = await authorized.get("/admin/queries")

        assert [item["question"] for item in response.json()["items"]] == ["Newer", "Older"]

    async def test_an_empty_history_is_an_empty_page_not_an_error(
        self, authorized: httpx.AsyncClient
    ) -> None:
        response = await authorized.get("/admin/queries")

        assert response.status_code == 200
        assert response.json() == {"items": [], "total": 0, "limit": 20, "offset": 0}


class TestUnansweredQueue:
    async def test_open_questions_are_grouped_with_a_count(
        self, authorized: httpx.AsyncClient, history_repository: InMemoryHistoryRepository
    ) -> None:
        history_repository.seed_unanswered(question="Mess menu?", created_at=NOW)
        history_repository.seed_unanswered(
            question="Mess menu?", created_at=NOW - timedelta(days=1)
        )

        response = await authorized.get("/admin/unanswered")

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert body["items"][0]["count"] == 2
        assert body["items"][0]["question"] == "Mess menu?"

    async def test_resolved_questions_are_hidden_by_default(
        self, authorized: httpx.AsyncClient, history_repository: InMemoryHistoryRepository
    ) -> None:
        history_repository.seed_unanswered(question="Handled", status="resolved")

        response = await authorized.get("/admin/unanswered")

        assert response.json()["items"] == []

    async def test_all_includes_the_resolved_groups(
        self, authorized: httpx.AsyncClient, history_repository: InMemoryHistoryRepository
    ) -> None:
        history_repository.seed_unanswered(question="Handled", status="resolved")
        history_repository.seed_unanswered(question="Still open")

        response = await authorized.get("/admin/unanswered", params={"status": "all"})

        assert response.json()["total"] == 2

    async def test_the_most_asked_question_comes_first(
        self, authorized: httpx.AsyncClient, history_repository: InMemoryHistoryRepository
    ) -> None:
        for _ in range(3):
            history_repository.seed_unanswered(question="Asked often", created_at=NOW)
        history_repository.seed_unanswered(question="Asked once", created_at=NOW)

        response = await authorized.get("/admin/unanswered")

        assert response.json()["items"][0]["question"] == "Asked often"

    async def test_paging_counts_groups_not_occurrences(
        self, authorized: httpx.AsyncClient, history_repository: InMemoryHistoryRepository
    ) -> None:
        # Four occurrences of one question is one row in the queue, so `total`
        # must be 2 -- not 4, and not the row count of the window.
        for _ in range(4):
            history_repository.seed_unanswered(question="Repeated")
        history_repository.seed_unanswered(question="Different")

        response = await authorized.get("/admin/unanswered", params={"limit": 1})

        body = response.json()
        assert len(body["items"]) == 1
        assert body["total"] == 2

    async def test_a_resolved_group_names_the_document_that_fixed_it(
        self, authorized: httpx.AsyncClient, history_repository: InMemoryHistoryRepository
    ) -> None:
        document_id = history_repository.seed_document("Examination Policy 2026")
        history_repository.seed_unanswered(
            question="Handled", status="resolved", resolved_by_document=document_id
        )

        response = await authorized.get("/admin/unanswered", params={"status": "all"})

        item = response.json()["items"][0]
        assert item["resolved_by_document"] == str(document_id)
        assert item["resolved_by_document_title"] == "Examination Policy 2026"

    # The truncation flag itself is proved in test_history_service.py, where the
    # window can be set to three rows instead of five thousand.


class TestResolvingAQuestion:
    async def test_resolving_moves_every_occurrence(
        self, authorized: httpx.AsyncClient, history_repository: InMemoryHistoryRepository
    ) -> None:
        digest = history_repository.seed_unanswered(question="Mess menu?")
        history_repository.seed_unanswered(question="Mess menu?")

        response = await authorized.patch(
            f"/admin/unanswered/{digest}", json={"status": "resolved"}
        )

        assert response.status_code == 200
        assert response.json()["status"] == "resolved"
        assert response.json()["count"] == 2
        # Both rows moved, not just the one the admin was looking at: a group
        # that reappeared after being resolved would be a lie about the queue.
        assert all(row["status"] == "resolved" for row in history_repository.unanswered_rows)

    async def test_resolving_links_the_document_that_answered_it(
        self, authorized: httpx.AsyncClient, history_repository: InMemoryHistoryRepository
    ) -> None:
        document_id = history_repository.seed_document("Hostel Rules")
        digest = history_repository.seed_unanswered()

        response = await authorized.patch(
            f"/admin/unanswered/{digest}",
            json={"status": "resolved", "resolved_by_document": str(document_id)},
        )

        assert response.json()["resolved_by_document_title"] == "Hostel Rules"

    async def test_reopening_clears_the_resolved_link(
        self, authorized: httpx.AsyncClient, history_repository: InMemoryHistoryRepository
    ) -> None:
        # An open row pointing at the document that resolved it is a
        # contradiction the queue would render.
        document_id = history_repository.seed_document("Hostel Rules")
        digest = history_repository.seed_unanswered()

        await authorized.patch(
            f"/admin/unanswered/{digest}",
            json={"status": "resolved", "resolved_by_document": str(document_id)},
        )
        response = await authorized.patch(f"/admin/unanswered/{digest}", json={"status": "open"})

        assert response.json()["resolved_by_document"] is None
        assert history_repository.updates[-1]["resolved_by_document"] is None

    async def test_a_document_that_does_not_exist_is_a_404(
        self, authorized: httpx.AsyncClient, history_repository: InMemoryHistoryRepository
    ) -> None:
        # Checked before the update: the column is a foreign key, so an unknown
        # id would otherwise surface as a constraint violation and a 500.
        digest = history_repository.seed_unanswered()

        response = await authorized.patch(
            f"/admin/unanswered/{digest}",
            json={"status": "resolved", "resolved_by_document": str(uuid4())},
        )

        assert response.status_code == 404
        assert response.json()["code"] == "document_not_found"
        assert history_repository.updates == []

    async def test_an_unknown_question_is_a_404(self, authorized: httpx.AsyncClient) -> None:
        response = await authorized.patch(
            f"/admin/unanswered/{'a' * 64}", json={"status": "resolved"}
        )

        assert response.status_code == 404
        assert response.json()["code"] == "unanswered_not_found"

    async def test_a_hash_that_is_not_a_hash_never_reaches_the_query(
        self, authorized: httpx.AsyncClient, history_repository: InMemoryHistoryRepository
    ) -> None:
        response = await authorized.patch(
            "/admin/unanswered/not-a-hash", json={"status": "resolved"}
        )

        assert response.status_code == 422
        assert history_repository.updates == []

    async def test_an_unknown_status_is_refused(
        self, authorized: httpx.AsyncClient, history_repository: InMemoryHistoryRepository
    ) -> None:
        digest = history_repository.seed_unanswered()

        response = await authorized.patch(
            f"/admin/unanswered/{digest}", json={"status": "dismissed"}
        )

        assert response.status_code == 422


class TestFaqs:
    async def test_counts_repeats_and_groups_by_category(
        self, authorized: httpx.AsyncClient, history_repository: InMemoryHistoryRepository
    ) -> None:
        history_repository.seed_query(question="When are marks published?", category="examinations")
        history_repository.seed_query(question="When are marks published?", category="examinations")
        history_repository.seed_query(question="How do I apply?", category="admissions")

        response = await authorized.get("/admin/faqs")

        assert response.status_code == 200
        groups = response.json()["groups"]
        assert [group["category"] for group in groups] == ["examinations", "admissions"]
        assert groups[0]["items"][0]["count"] == 2
        assert groups[0]["total"] == 2

    async def test_unanswered_questions_are_not_faqs(
        self, authorized: httpx.AsyncClient, history_repository: InMemoryHistoryRepository
    ) -> None:
        # A question the documents cannot answer is a gap, and the unanswered
        # queue is where it belongs. Listing it here as "frequent" would be a
        # second copy of that queue under a reassuring name.
        history_repository.seed_query(question="Unanswerable", answered=False)

        response = await authorized.get("/admin/faqs")

        assert response.json()["groups"] == []

    async def test_the_number_of_entries_per_category_is_capped(
        self, authorized: httpx.AsyncClient, history_repository: InMemoryHistoryRepository
    ) -> None:
        for index in range(8):
            history_repository.seed_query(question=f"Question {index}", category="examinations")

        response = await authorized.get("/admin/faqs")

        group = response.json()["groups"][0]
        assert len(group["items"]) == 5
        # The total still counts all eight, so a capped list does not make the
        # category look quieter than it is.
        assert group["total"] == 8


class TestStats:
    async def test_the_three_cards_add_up(
        self, authorized: httpx.AsyncClient, history_repository: InMemoryHistoryRepository
    ) -> None:
        # asked == answered + unanswered, derived rather than counted three
        # times, so the cards cannot disagree with each other on screen.
        for index in range(4):
            history_repository.seed_query(question=f"Answered {index}", created_at=NOW)
        history_repository.seed_query(question="Fell back", answered=False, created_at=NOW)

        response = await authorized.get("/admin/stats")

        cards = response.json()
        assert cards["questions"]["value"] == 5
        assert cards["answered"]["value"] == 4
        assert cards["unanswered"]["value"] == 1

    async def test_the_previous_window_is_reported_beside_the_current_one(
        self, authorized: httpx.AsyncClient, history_repository: InMemoryHistoryRepository
    ) -> None:
        history_repository.seed_query(question="This week", created_at=NOW - timedelta(days=1))
        history_repository.seed_query(question="Last week", created_at=NOW - timedelta(days=9))

        response = await authorized.get("/admin/stats")

        assert response.json()["questions"] == {"value": 1, "previous": 1}
        assert response.json()["window_days"] == 7

    async def test_the_chart_counts_the_current_window_only(
        self, authorized: httpx.AsyncClient, history_repository: InMemoryHistoryRepository
    ) -> None:
        history_repository.seed_query(category="events", created_at=NOW)
        history_repository.seed_query(category="events", created_at=NOW - timedelta(days=30))

        response = await authorized.get("/admin/stats")

        assert response.json()["categories"] == [{"category": "events", "count": 1}]

    async def test_the_top_category_carries_the_previous_one(
        self, authorized: httpx.AsyncClient, history_repository: InMemoryHistoryRepository
    ) -> None:
        history_repository.seed_query(category="examinations", created_at=NOW)
        history_repository.seed_query(category="events", created_at=NOW - timedelta(days=9))

        response = await authorized.get("/admin/stats")

        card = response.json()["top_category"]
        assert card["category"] == "examinations"
        assert card["count"] == 1
        assert card["previous_category"] == "events"
        assert card["previous_count"] == 1

    async def test_the_queue_preview_shows_the_worst_first(
        self, authorized: httpx.AsyncClient, history_repository: InMemoryHistoryRepository
    ) -> None:
        for _ in range(3):
            history_repository.seed_unanswered(question="Asked often", created_at=NOW)
        history_repository.seed_unanswered(question="Asked once", created_at=NOW)

        response = await authorized.get("/admin/stats", params={"preview_limit": 1})

        preview = response.json()["unanswered_preview"]
        assert len(preview) == 1
        assert preview[0]["question"] == "Asked often"

    async def test_an_empty_install_reports_zeroes_not_an_error(
        self, authorized: httpx.AsyncClient
    ) -> None:
        response = await authorized.get("/admin/stats")

        body = response.json()
        assert response.status_code == 200
        assert body["questions"] == {"value": 0, "previous": 0}
        assert body["categories"] == []
        assert body["top_category"]["category"] is None
        assert body["unanswered_preview"] == []


class TestTheAdminGate:
    async def test_the_reads_need_a_token(self, client: httpx.AsyncClient) -> None:
        for path in ("/admin/queries", "/admin/unanswered", "/admin/faqs", "/admin/stats"):
            response = await client.get(path)
            assert response.status_code == 401, path

    async def test_resolving_needs_a_token(self, client: httpx.AsyncClient) -> None:
        response = await client.patch(f"/admin/unanswered/{'a' * 64}", json={"status": "resolved"})

        assert response.status_code == 401

    async def test_staff_are_not_admins(
        self, client: httpx.AsyncClient, staff_headers: dict[str, str]
    ) -> None:
        response = await client.get("/admin/stats", headers=staff_headers)

        assert response.status_code == 403

    async def test_the_signed_in_admin_is_still_identifiable(
        self, authorized: httpx.AsyncClient
    ) -> None:
        # /admin/me is what the admin UI checks a stored token against.
        response = await authorized.get("/admin/me")

        assert response.status_code == 200
        assert response.json()["id"] == str(ADMIN_ID)


@pytest.mark.parametrize(
    "path", ["/admin/queries", "/admin/unanswered", "/admin/faqs", "/admin/stats"]
)
async def test_every_read_returns_the_admin_shape(authorized: httpx.AsyncClient, path: str) -> None:
    """No endpoint leaks a raw column or returns a 500 on an empty database."""
    response = await authorized.get(path)

    assert response.status_code == 200, response.text
    assert isinstance(response.json(), dict)
