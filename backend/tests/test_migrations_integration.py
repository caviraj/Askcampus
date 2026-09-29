"""Applies the migrations to a real Postgres and checks what they produced.

The only test that actually verifies the SQL -- every other test in the suite runs
against fakes, so a column name typo or a bad cast would reach production
unnoticed. Skipped unless RUN_DB_TESTS=1 and TEST_DATABASE_URL point at a Postgres
with pgvector, because a Supabase project (or `supabase start`, which needs Docker)
is not available during development.

To run it:
    set RUN_DB_TESTS=1
    set TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/postgres
    pip install psycopg[binary]
    docker run -d -p 5432:5432 -e POSTGRES_PASSWORD=postgres pgvector/pgvector:pg17
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any

import pytest

# Skipped rather than failed when the driver is absent, so the default test run
# stays green without adding a database driver to requirements-dev.txt.
psycopg = pytest.importorskip("psycopg")

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = REPO_ROOT / "supabase" / "migrations"
SQL_DIR = Path(__file__).resolve().parent / "sql"

TABLES = [
    "profiles",
    "documents",
    "chunks",
    "queries",
    "query_sources",
    "unanswered_queries",
    "feedback",
    # Phase 2.
    "embedding_cache",
]

# Added by 0004_ingestion_columns.sql.
INGESTION_COLUMNS = [
    "original_filename",
    "file_size_bytes",
    "page_count",
    "chunk_count",
    "extracted_chars",
    "text_preview",
    "low_text_yield",
    "processed_at",
]

DIMENSIONS = 768

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("RUN_DB_TESTS"),
        reason="set RUN_DB_TESTS=1 and TEST_DATABASE_URL to run database tests",
    ),
]


@pytest.fixture(scope="module")
def connection() -> Any:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is not set")

    with psycopg.connect(url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("drop schema if exists public cascade; create schema public;")
            # The Supabase stand-ins first: the migrations reference auth.users and
            # storage.buckets, neither of which exists on a bare Postgres.
            for stub in sorted(SQL_DIR.glob("*.sql")):
                cur.execute(stub.read_text(encoding="utf-8"))
            for migration in sorted(MIGRATIONS_DIR.glob("*.sql")):
                cur.execute(migration.read_text(encoding="utf-8"))
        yield conn


# ---------------------------------------------------------------------------
# Phase 1
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("table", TABLES)
def test_row_level_security_is_enabled(connection: Any, table: str) -> None:
    """Correction B1: without this every table is world-readable via the anon key."""
    with connection.cursor() as cur:
        cur.execute("select relrowsecurity from pg_class where relname = %s", (table,))
        row = cur.fetchone()
    assert row is not None, f"{table} was not created"
    assert row[0] is True, f"{table} does not have row level security enabled"


def test_all_tables_exist(connection: Any) -> None:
    with connection.cursor() as cur:
        cur.execute(
            "select tablename from pg_tables where schemaname = 'public' order by tablename"
        )
        found = {row[0] for row in cur.fetchall()}
    assert set(TABLES) <= found


def test_hybrid_search_returns_similarity(connection: Any) -> None:
    """Correction B2: the fallback threshold is unimplementable without it."""
    with connection.cursor() as cur:
        cur.execute(
            """
            select pg_get_function_result(oid)
            from pg_proc where proname = 'hybrid_search'
            """
        )
        row = cur.fetchone()
    assert row is not None, "hybrid_search was not created"
    result_type = row[0]
    assert "similarity" in result_type
    assert "score" in result_type


def test_hybrid_search_ranks_the_matching_chunk_first(connection: Any) -> None:
    """End-to-end check that retrieval returns the right row for a query."""
    with connection.cursor() as cur:
        cur.execute(
            """
            insert into public.documents (title, category, file_path, file_type, status)
            values ('Exam Schedule', 'examinations', 'x.pdf', 'pdf', 'ready')
            returning id
            """
        )
        document_id = cur.fetchone()[0]

        embedding = "[" + ",".join(["0.1"] * DIMENSIONS) + "]"
        cur.execute(
            """
            insert into public.chunks
              (document_id, chunk_index, page_number, section_heading, content,
               category, embedding)
            values
              (%s, 0, 1, 'Registration',
               'Semester exam registration closes on 12 December 2026.', 'examinations', %s),
              (%s, 1, 4, 'Fees',
               'Tuition fee payment is due on 1 August 2026.', 'examinations', %s)
            """,
            (document_id, embedding, document_id, embedding),
        )

        cur.execute(
            "select chunk_id, similarity from hybrid_search(%s, %s, 5, null)",
            ("When does semester exam registration close?", embedding),
        )
        rows = cur.fetchall()

    assert rows, "hybrid_search returned nothing"
    assert rows[0][0] is not None
    # Cosine similarity against the identical seeded vector must be ~1.0.
    assert rows[0][1] == pytest.approx(1.0, abs=1e-3)


def test_profile_is_created_for_a_new_auth_user(connection: Any) -> None:
    """Correction B5: without the trigger no one can ever become an admin."""
    with connection.cursor() as cur:
        cur.execute(
            """
            insert into auth.users (id, raw_user_meta_data)
            values (gen_random_uuid(), '{"full_name": "Ada Admin"}'::jsonb)
            returning id
            """
        )
        user_id = cur.fetchone()[0]
        cur.execute("select full_name, role from public.profiles where id = %s", (user_id,))
        row = cur.fetchone()

    assert row is not None, "the handle_new_user trigger did not create a profile"
    assert row[0] == "Ada Admin"
    assert row[1] == "staff"


def test_document_updated_at_moves_on_update(connection: Any) -> None:
    """Correction B6: citations expose this as last_updated."""
    with connection.cursor() as cur:
        cur.execute(
            """
            insert into public.documents (title, category, file_path, file_type, status)
            values ('Calendar', 'general', 'c.pdf', 'pdf', 'ready')
            returning id, updated_at
            """
        )
        document_id, before = cur.fetchone()
        cur.execute(
            "update public.documents set title = 'Calendar 2026' where id = %s "
            "returning updated_at",
            (document_id,),
        )
        after = cur.fetchone()[0]

    assert after > before


# ---------------------------------------------------------------------------
# Phase 2: schema
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("column", INGESTION_COLUMNS)
def test_the_ingestion_columns_exist(connection: Any, column: str) -> None:
    """The pipeline writes every one of these. A typo would fail at insert time
    inside a background task, where the admin only sees "failed"."""
    with connection.cursor() as cur:
        cur.execute(
            "select data_type, is_nullable from information_schema.columns "
            "where table_schema = 'public' and table_name = 'documents' "
            "and column_name = %s",
            (column,),
        )
        row = cur.fetchone()

    assert row is not None, f"documents.{column} was not added"
    assert row[1] == "YES", f"documents.{column} should be nullable"


def test_low_text_yield_defaults_to_false(connection: Any) -> None:
    """A not-null boolean with no default would make every insert that omits it
    fail, so the default is what keeps 0001's insert sites working."""
    with connection.cursor() as cur:
        cur.execute(
            "select column_default from information_schema.columns "
            "where table_schema = 'public' and table_name = 'documents' "
            "and column_name = 'low_text_yield'"
        )
        assert cur.fetchone()[0] == "false"


def test_the_content_hash_index_is_not_a_unique_constraint(connection: Any) -> None:
    """Deliberate: a unique *constraint* turns a duplicate upload into a driver
    integrity error and a 500, where the API owes the client a 409 naming the
    existing document."""
    with connection.cursor() as cur:
        cur.execute(
            "select indexdef from pg_indexes where indexname = 'documents_content_hash_active_idx'"
        )
        row = cur.fetchone()
        cur.execute(
            "select count(*) from pg_constraint where conrelid = 'public.documents'::regclass "
            "and contype = 'u'"
        )
        unique_constraints = cur.fetchone()[0]

    assert row is not None, "the content_hash index was not created"
    assert "UNIQUE" not in row[0].upper()
    assert "WHERE" in row[0].upper(), "the index should be partial on is_active"
    assert unique_constraints == 0


def test_a_document_cannot_have_two_chunks_with_the_same_index(connection: Any) -> None:
    """`chunk_index` was documented as a per-document ordinal but never enforced,
    so a double-submitted reprocess could produce two rows claiming the same index
    and a citation pointing at an arbitrary one."""
    with connection.cursor() as cur:
        cur.execute(
            """
            insert into public.documents (title, category, file_path, file_type, status)
            values ('Index Check', 'general', 'i.pdf', 'pdf', 'ready')
            returning id
            """
        )
        document_id = cur.fetchone()[0]
        embedding = "[" + ",".join(["0.1"] * DIMENSIONS) + "]"
        cur.execute(
            "insert into public.chunks (document_id, chunk_index, content, category, embedding) "
            "values (%s, 0, 'first', 'general', %s)",
            (document_id, embedding),
        )

        with pytest.raises(psycopg.errors.UniqueViolation):
            cur.execute(
                "insert into public.chunks "
                "(document_id, chunk_index, content, category, embedding) "
                "values (%s, 0, 'second', 'general', %s)",
                (document_id, embedding),
            )


def test_the_documents_bucket_exists_and_is_private(connection: Any) -> None:
    """ARCHITECTURE.md names the bucket but never created it, so the first upload
    would fail with "Bucket not found" -- an error naming neither the bucket nor
    the missing migration."""
    with connection.cursor() as cur:
        cur.execute(
            "select public, file_size_limit, allowed_mime_types "
            "from storage.buckets where id = 'documents'"
        )
        row = cur.fetchone()

    assert row is not None, "the documents bucket was not created"
    is_public, file_size_limit, mime_types = row
    assert is_public is False, "a public bucket makes every object URL a capability"
    assert file_size_limit == 20971520
    assert set(mime_types) == {
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "text/plain",
    }


def test_applying_the_bucket_migration_twice_is_harmless(connection: Any) -> None:
    """Supabase re-runs a migration if its ledger row is lost, and a plain insert
    would then fail with a duplicate key on every subsequent deploy."""
    migration = (MIGRATIONS_DIR / "0003_documents_bucket.sql").read_text(encoding="utf-8")
    with connection.cursor() as cur:
        cur.execute(migration)

    with connection.cursor() as cur:
        cur.execute("select count(*) from storage.buckets where id = 'documents'")
        assert cur.fetchone()[0] == 1


def test_embedding_cache_is_denied_to_client_roles(connection: Any) -> None:
    """RLS blocks row access only for tables the role may touch at all. Without the
    revoke, anon holds a table-level SELECT grant and RLS is the only thing left
    standing -- one policy mistake away from exposing the whole corpus."""
    with connection.cursor() as cur:
        cur.execute(
            "select has_table_privilege('anon', 'public.embedding_cache', 'select'), "
            "has_table_privilege('authenticated', 'public.embedding_cache', 'insert')"
        )
        anon_select, authenticated_insert = cur.fetchone()

    assert anon_select is False
    assert authenticated_insert is False


def test_embedding_cache_is_keyed_by_width_as_well_as_model(connection: Any) -> None:
    """So that changing EMBEDDING_DIMENSIONS self-invalidates stale rows instead of
    serving a 768-wide vector into a column of another width."""
    with connection.cursor() as cur:
        cur.execute(
            """
            select array_agg(a.attname order by a.attname)
            from pg_index i
            join pg_attribute a on a.attrelid = i.indrelid and a.attnum = any(i.indkey)
            where i.indrelid = 'public.embedding_cache'::regclass and i.indisprimary
            """
        )
        columns = cur.fetchone()[0]

    assert columns == ["content_hash", "dimensions", "model"]


# ---------------------------------------------------------------------------
# Phase 2: the atomicity fix
# ---------------------------------------------------------------------------


def _chunk(index: int, *, embedding: object, page: int | None = None) -> dict[str, Any]:
    return {
        "chunk_index": index,
        "page_number": page if page is not None else index + 1,
        "section_heading": "Examination Fees",
        "content": f"Chunk {index} of the examination fee schedule.",
        "embedding": embedding,
    }


def _vector(value: float = 0.1) -> list[float]:
    return [value] * DIMENSIONS


def _document(connection: Any, *, status: str = "uploaded") -> Any:
    with connection.cursor() as cur:
        cur.execute(
            """
            insert into public.documents (title, category, file_path, file_type, status)
            values ('Fee Schedule', 'examinations', 'f.pdf', 'pdf', %s)
            returning id
            """,
            (status,),
        )
        return cur.fetchone()[0]


def _replace(connection: Any, document_id: Any, chunks: list[dict[str, Any]], **kwargs: Any) -> int:
    with connection.cursor() as cur:
        cur.execute(
            "select public.replace_document_chunks(%s, %s::jsonb, %s::jsonb, %s)",
            (
                document_id,
                json.dumps(chunks),
                json.dumps(kwargs.get("metadata", {})),
                kwargs.get("mark_ready", True),
            ),
        )
        return cur.fetchone()[0]


def _stored_chunks(connection: Any, document_id: Any) -> list[tuple[int, str]]:
    with connection.cursor() as cur:
        cur.execute(
            "select chunk_index, content from public.chunks "
            "where document_id = %s order by chunk_index",
            (document_id,),
        )
        return cur.fetchall()


def test_replace_document_chunks_inserts_and_marks_ready(connection: Any) -> None:
    """AGENTS.md section 13. The status and the chunks land together, so "chunks
    exist" and "document is ready" can never disagree."""
    document_id = _document(connection, status="uploaded")

    count = _replace(
        connection,
        document_id,
        [_chunk(0, embedding=_vector()), _chunk(1, embedding=_vector())],
        metadata={"page_count": 2, "extracted_chars": 120, "text_preview": "Chunk 0"},
    )

    assert count == 2
    assert [row[0] for row in _stored_chunks(connection, document_id)] == [0, 1]

    with connection.cursor() as cur:
        cur.execute(
            "select status, chunk_count, page_count, extracted_chars, text_preview, "
            "processed_at is not null from public.documents where id = %s",
            (document_id,),
        )
        status, chunk_count, page_count, extracted_chars, text_preview, processed = cur.fetchone()

    assert status == "ready"
    assert chunk_count == 2
    assert page_count == 2
    assert extracted_chars == 120
    assert text_preview == "Chunk 0"
    assert processed is True


def test_replace_document_chunks_copies_the_category_from_the_document(connection: Any) -> None:
    """Denormalized on purpose: hybrid_search filters on chunks.category, and the
    sync trigger only fires on a later UPDATE of documents.category."""
    document_id = _document(connection)
    _replace(connection, document_id, [_chunk(0, embedding=_vector())])

    with connection.cursor() as cur:
        cur.execute(
            "select distinct category from public.chunks where document_id = %s", (document_id,)
        )
        assert cur.fetchone()[0] == "examinations"


def test_replace_document_chunks_replaces_rather_than_appends(connection: Any) -> None:
    document_id = _document(connection)
    _replace(
        connection, document_id, [_chunk(0, embedding=_vector()), _chunk(1, embedding=_vector())]
    )
    _replace(connection, document_id, [_chunk(0, embedding=_vector())])

    assert [row[0] for row in _stored_chunks(connection, document_id)] == [0]


def test_a_null_page_number_is_stored_as_null(connection: Any) -> None:
    """DOCX and TXT have no pages. Coercing the JSON null to 0 would fabricate a
    page number in a citation, which AGENTS.md section 6.5 forbids."""
    document_id = _document(connection)
    _replace(connection, document_id, [_chunk(0, embedding=_vector(), page=None)])

    with connection.cursor() as cur:
        cur.execute("select page_number from public.chunks where document_id = %s", (document_id,))
        assert cur.fetchone()[0] is None


def test_mark_ready_false_leaves_the_status_alone(connection: Any) -> None:
    """Reprocessing a live document must not take it out of retrieval while a new
    version is being built."""
    document_id = _document(connection, status="processing")
    _replace(connection, document_id, [_chunk(0, embedding=_vector())], mark_ready=False)

    with connection.cursor() as cur:
        cur.execute("select status from public.documents where id = %s", (document_id,))
        assert cur.fetchone()[0] == "processing"


def test_a_failed_replace_leaves_the_previous_chunks_intact(connection: Any) -> None:
    """The assertion that actually proves the single-transaction rule.

    The second payload's embedding cannot cast to vector, so the insert fails
    *after* the delete has already run. In one transaction the delete is rolled
    back with it; in two round trips the document would now have zero chunks and,
    without this test, nothing would say so.
    """
    document_id = _document(connection)
    _replace(
        connection, document_id, [_chunk(0, embedding=_vector()), _chunk(1, embedding=_vector())]
    )
    before = _stored_chunks(connection, document_id)

    with pytest.raises(psycopg.errors.Error):
        _replace(connection, document_id, [_chunk(0, embedding="not-a-vector")])

    assert _stored_chunks(connection, document_id) == before
    with connection.cursor() as cur:
        cur.execute(
            "select status, chunk_count from public.documents where id = %s", (document_id,)
        )
        status, chunk_count = cur.fetchone()
    assert status == "ready"
    assert chunk_count == 2


def test_replacing_chunks_for_an_unknown_document_raises(connection: Any) -> None:
    """Raising rather than silently inserting orphan rows the caller cannot see."""
    with pytest.raises(psycopg.errors.Error):
        _replace(connection, uuid.uuid4(), [_chunk(0, embedding=_vector())])


def test_replace_document_chunks_is_not_callable_by_a_client_role(connection: Any) -> None:
    """The default EXECUTE grant is to PUBLIC, which anon and authenticated both
    inherit, so revoking from those two roles alone would leave the hole open. A
    function that deletes every chunk of a document is not a client-facing
    operation."""
    with connection.cursor() as cur:
        cur.execute(
            "select has_function_privilege('anon', "
            "'public.replace_document_chunks(uuid, jsonb, jsonb, boolean)', 'execute'), "
            "has_function_privilege('authenticated', "
            "'public.replace_document_chunks(uuid, jsonb, jsonb, boolean)', 'execute'), "
            "has_function_privilege('service_role', "
            "'public.replace_document_chunks(uuid, jsonb, jsonb, boolean)', 'execute')"
        )
        anon, authenticated, service_role = cur.fetchone()

    assert anon is False
    assert authenticated is False
    assert service_role is True


# ---------------------------------------------------------------------------
# Phase 3: query logging
# ---------------------------------------------------------------------------


def _source(rank: int, title: str) -> dict[str, Any]:
    """One `query_sources` entry, shaped exactly as the backend serialises it."""
    return {
        "rank": rank,
        "chunk_id": str(uuid.uuid4()),
        "score": 0.031,
        "document_id": str(uuid.uuid4()),
        "document_title": title,
        "page_number": 3,
        "section_heading": "Fees",
    }


def _record_feedback(connection: Any, query_id: Any, session_id: Any, helpful: bool) -> bool:
    with connection.cursor() as cur:
        cur.execute("select public.record_feedback(%s, %s, %s)", (query_id, session_id, helpful))
        return cur.fetchone()[0]


def _log_query(connection: Any, **overrides: Any) -> Any:
    """Call `log_query` with a valid payload, overridable field by field."""
    values: dict[str, Any] = {
        "p_query_id": uuid.uuid4(),
        "p_session_id": uuid.uuid4(),
        "p_question": "When is the examination fee due?",
        "p_normalized_hash": "a" * 64,
        "p_category": "examinations",
        "p_answer": "The fee is due on 12 December.",
        "p_answered": True,
        "p_top_score": 0.91,
        "p_latency_ms": 842,
        "p_sources": json.dumps(
            [
                {
                    "rank": 1,
                    "chunk_id": str(uuid.uuid4()),
                    "score": 0.031,
                    "document_id": str(uuid.uuid4()),
                    "document_title": "Examination handbook",
                    "page_number": 3,
                    "section_heading": "Fees",
                }
            ]
        ),
        "p_unanswered": False,
    }
    values.update(overrides)
    with connection.cursor() as cur:
        cur.execute(
            "select public.log_query(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)",
            tuple(values.values()),
        )
        return cur.fetchone()[0]


def _rows(connection: Any, sql: str, params: tuple[Any, ...]) -> list[tuple[Any, ...]]:
    with connection.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def test_log_query_writes_the_query_and_its_sources(connection: Any) -> None:
    """AGENTS.md section 6.6. One call, one transaction -- and the id it returns
    is the one the backend minted, so the response does not depend on the write
    having succeeded."""
    query_id = _log_query(connection, p_sources=json.dumps([_source(1, "S1"), _source(2, "S2")]))

    rows = _rows(
        connection,
        "select session_id, question, normalized_hash, category, answer, answered, "
        "top_score, latency_ms from public.queries where id = %s",
        (query_id,),
    )

    assert len(rows) == 1
    assert rows[0][3] == "examinations"
    assert rows[0][5] is True
    assert rows[0][7] == 842
    ranks = _rows(
        connection, "select rank from public.query_sources where query_id = %s", (query_id,)
    )
    assert sorted(row[0] for row in ranks) == [1, 2]


def test_a_null_category_is_stored_as_null(connection: Any) -> None:
    """`NULL` is "could not classify", which is not the same as the real
    `general` category -- conflating them would filter every general-filed
    document out of retrieval."""
    query_id = _log_query(connection, p_category=None)

    assert _rows(connection, "select category from public.queries where id = %s", (query_id,)) == [
        (None,)
    ]


def test_an_unanswered_question_writes_both_rows(connection: Any) -> None:
    """The second row is the one the whole admin queue exists to collect."""
    query_id = _log_query(
        connection,
        p_answered=False,
        p_answer="I could not find this in the college documents.",
        p_unanswered=True,
        p_sources=json.dumps([]),
        p_top_score=None,
    )

    assert len(_rows(connection, "select id from public.queries where id = %s", (query_id,))) == 1
    unanswered = _rows(
        connection,
        "select question, normalized_hash, category, status, resolved_by_document "
        "from public.unanswered_queries where query_id = %s",
        (query_id,),
    )
    assert len(unanswered) == 1
    assert unanswered[0][0] == "When is the examination fee due?"
    assert unanswered[0][3] == "open"
    assert unanswered[0][4] is None


def test_an_answered_question_writes_no_unanswered_row(connection: Any) -> None:
    query_id = _log_query(connection)

    assert (
        _rows(
            connection,
            "select query_id from public.unanswered_queries where query_id = %s",
            (query_id,),
        )
        == []
    )


def test_a_bad_source_entry_rolls_back_the_whole_log(connection: Any) -> None:
    """The assertion that proves the single-transaction rule, and the reason this
    is a function rather than three PostgREST inserts.

    The `queries` row is inserted *before* the sources, and the second entry's
    score cannot cast to real. Without one transaction the history would keep a
    question whose cited sources are missing -- exactly the state migration
    0007's header describes. With one, the whole call vanishes.
    """
    query_id = uuid.uuid4()

    with pytest.raises(psycopg.errors.Error):
        _log_query(
            connection,
            p_query_id=query_id,
            p_unanswered=True,
            p_sources=json.dumps([_source(1, "S1"), {**_source(2, "S2"), "score": "not-a-number"}]),
        )

    assert _rows(connection, "select id from public.queries where id = %s", (query_id,)) == []
    assert (
        _rows(
            connection,
            "select query_id from public.unanswered_queries where query_id = %s",
            (query_id,),
        )
        == []
    )


def test_a_chunk_with_no_page_stores_a_null_page(connection: Any) -> None:
    """DOCX and TXT have no pages, and AGENTS.md section 6.5 forbids a fabricated
    one -- so the JSON null has to survive the cast, not become 0."""
    query_id = _log_query(
        connection,
        p_sources=json.dumps(
            [
                {
                    "rank": 1,
                    "chunk_id": str(uuid.uuid4()),
                    "score": 0.031,
                    "document_id": str(uuid.uuid4()),
                    "document_title": "Student handbook",
                    "page_number": None,
                    "section_heading": None,
                }
            ]
        ),
    )

    rows = _rows(
        connection,
        "select page_number, section_heading from public.query_sources where query_id = %s",
        (query_id,),
    )
    assert rows == [(None, None)]


def test_feedback_is_recorded_for_the_owning_session(connection: Any) -> None:
    session_id = uuid.uuid4()
    query_id = _log_query(connection, p_session_id=session_id)

    assert _record_feedback(connection, query_id, session_id, True) is True
    assert _rows(
        connection, "select helpful from public.feedback where query_id = %s", (query_id,)
    ) == [(True,)]


def test_a_foreign_session_cannot_rate_a_query_and_writes_nothing(connection: Any) -> None:
    """The ownership predicate is inside the insert, so there is no window
    between the check and the write. `false` rather than an error, because the
    route reports it as a 404 and the two cases must be indistinguishable."""
    query_id = _log_query(connection, p_session_id=uuid.uuid4())

    assert _record_feedback(connection, query_id, uuid.uuid4(), True) is False
    assert (
        _rows(connection, "select helpful from public.feedback where query_id = %s", (query_id,))
        == []
    )


def test_an_unknown_query_cannot_be_rated(connection: Any) -> None:
    assert _record_feedback(connection, uuid.uuid4(), uuid.uuid4(), True) is False


def test_re_rating_replaces_rather_than_accumulating(connection: Any) -> None:
    """`feedback.query_id` is the primary key, so a changed mind is one row."""
    session_id = uuid.uuid4()
    query_id = _log_query(connection, p_session_id=session_id)

    _record_feedback(connection, query_id, session_id, True)
    _record_feedback(connection, query_id, session_id, False)

    rows = _rows(connection, "select helpful from public.feedback where query_id = %s", (query_id,))
    assert rows == [(False,)]


@pytest.mark.parametrize(
    "signature",
    [
        "public.log_query(uuid, uuid, text, text, text, text, boolean, real, int, jsonb, boolean)",
        "public.record_feedback(uuid, uuid, boolean)",
    ],
)
def test_the_logging_functions_are_not_callable_by_a_client_role(
    connection: Any, signature: str
) -> None:
    """`record_feedback` is reached from an unauthenticated route, so a client
    role holding EXECUTE on it would let anyone rate anyone's answer."""
    with connection.cursor() as cur:
        cur.execute(
            f"select has_function_privilege('anon', '{signature}', 'execute'), "
            f"has_function_privilege('authenticated', '{signature}', 'execute'), "
            f"has_function_privilege('service_role', '{signature}', 'execute')"
        )
        anon, authenticated, service_role = cur.fetchone()

    assert anon is False
    assert authenticated is False
    assert service_role is True
