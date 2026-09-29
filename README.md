# CampusAsk

A RAG-based college helpdesk. Students ask questions in plain language; the system retrieves from an
approved set of college documents and answers **only** from the retrieved text, attaching the source
document and section to every answer. Questions it cannot answer are logged for admins, who manage
the document set and review what students asked.

- `PRD.md` — what the product does and how success is measured
- `ARCHITECTURE.md` — schema, core flows, prompt contract, API surface
- `DESIGN_SYSTEM.md` — tokens, typography, component rules
- `AGENTS.md` — build order and non-negotiable rules

Spec documents live in `docs/`.

## Status

**Phase 2 of 6 (Ingestion) is complete.** What exists: everything from Phase 1, plus the path from an
uploaded file to searchable text — Storage, per-page extraction, cleaning, heading-aware chunking,
batched embeddings with a cache, and the status transitions that carry a document from `uploaded` to
`ready`. An admin can upload a college PDF, poll its status, reprocess it, replace its file or delete
it.

Nothing retrieves or answers yet — `chunks` is populated but nothing reads it, and there is no
question endpoint until Phase 3.

| Phase | Scope | State |
|---|---|---|
| 1 | Scaffold, config, migrations, admin auth gate | done |
| 2 | Ingestion: upload, extraction, chunking, embeddings | done |
| 3 | Retrieval and answering | not started |
| 4 | Student UI | not started |
| 5 | Admin UI | not started |
| 6 | Evaluation and tuning | not started |

## Prerequisites

- Python 3.11 or newer (developed and tested on 3.14)
- Node.js 20 or newer — only needed from Phase 4
- A Supabase project with the `vector` extension, and the migrations applied
- A Gemini API key — ingestion cannot run without one

## Layout

```
backend/     FastAPI application
  app/api/         route handlers — validate input, call a service, shape the response
  app/services/    business logic: extraction, cleaning, chunking, embedding, ingestion
  app/providers/   LLM and embedding interfaces, and the Gemini implementation
  app/db/          Supabase client and data functions
  app/schemas/     Pydantic request and response models
  tests/           all offline; generated file fixtures, no committed binaries
supabase/migrations/   schema, applied in filename order
docs/                  the spec documents
eval/                  Phase 6
frontend/              Phase 4
```

## Setup

```bash
cd backend
python -m venv .venv
.venv/Scripts/activate          # Windows; use source .venv/bin/activate on macOS or Linux
pip install -r requirements.txt -r requirements-dev.txt

cp .env.example .env            # then fill in SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, GEMINI_API_KEY
```

Apply the migrations before uploading anything — the `documents` Storage bucket is created by
`0003_documents_bucket.sql`, and without it every upload fails with "Bucket not found".

`.env` is gitignored. The service role key and the Gemini key are backend-only — they must never
reach the frontend or a commit.

Settings are validated at startup. If `SUPABASE_URL` or `GEMINI_API_KEY` is missing, the process
exits with a `ValidationError` naming the missing field rather than booting into a broken state.
`GEMINI_API_KEY` is required rather than optional because ingestion cannot work without it, and a
failure inside a background task is one nobody sees.

## Run

```bash
cd backend
.venv/Scripts/activate
uvicorn app.main:app --reload --port 8000
```

- `GET /health` → `{"status": "ok", "version": ..., "environment": ...}`. Liveness only; it does not
  touch Supabase.
- `/docs` → interactive API documentation.

## Ingestion

Uploading a document runs a five-stage pipeline. Each stage is a pure function over plain data, so
the parts that decide anything are testable without a database:

```
bytes ─extract─▶ [TextBlock] ─clean─▶ [TextBlock] ─chunk─▶ [Chunk] ─embed─▶ vectors ─▶ RPC
```

- **Extract** — PyMuPDF for PDFs (`page_number` is 1-based, taken from the page the text sits on),
  python-docx for DOCX, and a BOM-aware decoder for TXT. PDF headings come from font size and
  numbering, overridden by the document outline when it has one. Ruled tables are rendered
  self-describing (`Date: 12 December 2026; Fee: 500`) so a row stays readable three chunks away from
  its header. DOCX and TXT have no fixed pages, so their `page_number` is `null` rather than a
  fabricated number.
- **Clean** — NFKC normalisation, whitespace collapse, line-break hyphenation rejoined, and running
  headers and footers dropped when they repeat at the same position across pages. Dates and
  identifiers survive byte-identical.
- **Chunk** — heading-aware, targeting `CHUNK_TARGET_TOKENS` and never exceeding `CHUNK_MAX_TOKENS`,
  with `CHUNK_OVERLAP_TOKENS` of trailing text carried forward. Overlap never crosses a heading
  boundary, and the heading is prefixed into the chunk text so keyword search can match it.
- **Embed** — batches of `EMBED_BATCH_SIZE`, skipping any text whose sha256 is already in
  `embedding_cache`. Only transient failures (timeouts, 429, 5xx) are retried; a retired model is a
  permanent error and fails on the first attempt.
- **Write** — a single `replace_document_chunks` RPC, which deletes the old chunks, inserts the new
  ones and updates the derived counts in one transaction. Embeddings are computed *before* it runs,
  so a failed reprocess leaves the previous version of the document intact and still searchable.

A scanned PDF, which has no text layer, is flagged (`low_text_yield`) rather than failed as long as
some text was found; only a document that yields zero chunks fails. OCR is out of scope for v1.

### Admin document routes

All under `/admin/documents`, all requiring an admin token.

| Method | Path | Result |
|---|---|---|
| POST | `/admin/documents` | `202` with the row; processing continues in the background |
| GET | `/admin/documents` | paged list, filtered by `status`, `category`, `is_active` |
| GET | `/admin/documents/{id}` | one document — what the admin UI polls |
| PATCH | `/admin/documents/{id}` | title, category, academic_year, department, is_active |
| POST | `/admin/documents/{id}/reprocess` | `202`; re-extract and re-embed from the stored file |
| POST | `/admin/documents/{id}/replace` | `202`; swap the file, keeping the document id |
| DELETE | `/admin/documents/{id}` | `204`; the row, its chunks and its stored object |

`202` rather than `201` because the resource exists but the work has not happened yet. The status to
poll is in the response body. `replace` is separate from delete-and-re-upload because keeping the id
is the point — query history and existing citations name this document.

## Verify

```bash
cd backend
.venv/Scripts/activate

ruff check .              # lint
ruff format --check .     # formatting
pytest -q                 # tests
```

All three must pass before a change is considered done.

The default run is fully offline — no Supabase project, no network, no database, no Gemini call.
JWT tests use real EC keys and really signed tokens; only the JWKS HTTP fetch is stubbed. The
document routes are wired to an in-memory repository, an in-memory bucket and a fake embedding
provider, so no test can reach a real service by forgetting to override something. The ingestion
pipeline itself runs for real during those tests: only the database, Storage and the model are
fakes, which is what makes the status assertions mean anything.

File fixtures are generated in memory rather than committed as binaries — no opaque blobs in git, and
the builder doubles as a readable statement of what each format looks like.

To check the auth gate by hand:

```bash
curl -i localhost:8000/health                 # 200
curl -i localhost:8000/admin/me               # 401 — no token
curl -i -H "Authorization: Bearer nope" localhost:8000/admin/me   # 401 — malformed token
```

A valid token from a user whose `profiles.role` is not `admin` gets `403`. If the JWKS endpoint is
unreachable the gate returns `503` — it never falls through to allow.

## Database migrations

`supabase/migrations/` holds the schema. Apply them in filename order:

```bash
supabase db push        # linked project
supabase db reset       # local, via supabase start
```

The migrations reference `auth.users` and `storage.buckets`, so they need a real Supabase database.
The bucket creation is guarded on the `storage` schema existing, so applying the whole directory to a
bare Postgres is a no-op for that one file rather than an error.

`test_migrations_integration.py` checks the applied schema against a real Postgres — row level
security on every table, `hybrid_search` returning cosine similarity and ranking correctly, the
triggers, the ingestion columns, the private `documents` bucket, the `embedding_cache` grants, the
unique chunk index, and the single-transaction property of `replace_document_chunks` (it calls the
function with an embedding that cannot cast, then asserts the previous chunks are still there). It is
skipped unless you opt in:

```bash
pip install "psycopg[binary]"
RUN_DB_TESTS=1 TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/postgres pytest -q -m integration
```

`test_ingestion_e2e.py` runs a generated PDF through real Storage and real Gemini. It needs a live
project and a real key, and every document it creates is deleted again:

```bash
RUN_LIVE_TESTS=1 pytest -q tests/test_ingestion_e2e.py
```

After creating your first admin user in Supabase Auth, promote them once:

```sql
update public.profiles set role = 'admin' where id = '<user-uuid>';
```

A trigger creates the `profiles` row on signup, so the row already exists. Role is read from that
table on every admin request — never from the token. A token whose own `role` claim says `admin`
grants nothing.

## Configuration

All variables are documented in `backend/.env.example`. Constants such as `TOP_K`,
`SIMILARITY_THRESHOLD`, and `MAX_UPLOAD_MB` live in `app/config.py` and are imported from there;
nothing hardcodes them.

## Frontend contract

Phase 4 reads these three variables from `frontend/.env`. They are recorded now so the naming is
fixed before anything depends on it:

```
VITE_SUPABASE_URL=https://your-project-ref.supabase.co
VITE_SUPABASE_ANON_KEY=your-anon-key
VITE_API_URL=http://localhost:8000
```

Only the anon key is exposed to the browser. The anon key grants nothing directly — every table has
row level security enabled with default-deny, so PostgREST returns no rows to it. All reads and
writes go through the FastAPI backend, which holds the service role key.
