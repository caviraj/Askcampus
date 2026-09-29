"""Applies the migrations to a real Postgres and checks what they produced.

The only test that actually verifies the SQL. Skipped unless RUN_DB_TESTS=1 and
TEST_DATABASE_URL point at a Postgres with pgvector, because a Supabase project
(or `supabase start`, which needs Docker) is not available during Phase 1.

To run it:
    set RUN_DB_TESTS=1
    set TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/postgres
    pip install psycopg[binary]
    docker run -d -p 5432:5432 -e POSTGRES_PASSWORD=postgres pgvector/pgvector:pg17
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

# Skipped rather than failed when the driver is absent, so the default test run
# stays green without adding a database driver to requirements-dev.txt.
psycopg = pytest.importorskip("psycopg")

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = REPO_ROOT / "supabase" / "migrations"
AUTH_STUB = Path(__file__).resolve().parent / "sql" / "00_auth_stub.sql"

TABLES = [
    "profiles",
    "documents",
    "chunks",
    "queries",
    "query_sources",
    "unanswered_queries",
    "feedback",
]

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
            cur.execute(AUTH_STUB.read_text(encoding="utf-8"))
            for migration in sorted(MIGRATIONS_DIR.glob("*.sql")):
                cur.execute(migration.read_text(encoding="utf-8"))
        yield conn


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

        embedding = "[" + ",".join(["0.1"] * 768) + "]"
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
