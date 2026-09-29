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

**Phase 4 of 6 (Student UI) is complete.** A student opens the chat page, asks a question in plain
language, and reads an answer drawn only from retrieved document text with a **source slip** beside
it — expandable to the passage it came from, with the supporting sentence marked. Questions the
documents do not answer come back as an honest fallback naming the office that handles them, and are
logged for admins. Phase 5 builds the admin UI and Phase 6 the evaluation set.

| Phase | Scope | State |
|---|---|---|
| 1 | Scaffold, config, migrations, admin auth gate | done |
| 2 | Ingestion: upload, extraction, chunking, embeddings | done |
| 3 | Retrieval and answering | done |
| 4 | Student UI | done |
| 5 | Admin UI | not started |
| 6 | Evaluation and tuning | not started |

## Prerequisites

- Python 3.11 or newer (developed and tested on 3.14)
- Node.js 20 or newer — needed for the frontend from Phase 4 onward
- A Supabase project with the `vector` extension, and the migrations applied
- A Gemini API key — ingestion cannot run without one

## Layout

```
backend/     FastAPI application
  app/api/         route handlers — validate input, call a service, shape the response
  app/services/    business logic: extraction, cleaning, chunking, embedding, ingestion,
                   retrieval, classification, answering, fallback, query logging
  app/providers/   LLM and embedding interfaces, and the Gemini implementation
  app/db/          Supabase client and data functions
  app/schemas/     Pydantic request and response models
  tests/           all offline; generated file fixtures, no committed binaries
supabase/migrations/   schema, applied in filename order
docs/                  the spec documents
eval/                  Phase 6
frontend/              React 19 + Vite + Tailwind student chat
  src/pages/       the chat page
  src/components/  the message list, source slips, chips, composer
  src/hooks/       the chat reducer, media query, textarea autogrow
  src/lib/         the API client, types, error mapping, highlighting
  src/test/        the Vitest harness
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

## Frontend

```bash
cd frontend
npm install
cp .env.example .env            # VITE_API_URL, if the backend is not on :8000
npm run dev                     # http://localhost:5173
```

With the backend running, upload a document through `/docs`, wait for it to reach `ready`, then ask a
question its text answers. The answer arrives with a source slip beside it; expanding the slip shows
the passage with the supporting sentence marked.

```bash
npm run lint && npm run typecheck && npm test && npm run build
```

`npm test` runs Vitest against jsdom with `fetch` stubbed, so the suite needs no backend and no
network. Tailwind does not run in tests — assertions are on token class names, and a mistyped token is
caught by `npm run build`.

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

## Asking a question

```
POST /chat {session_id, question, history?, category?}
  → {query_id, answered, category, answer, citations[]}
```

No token: `AGENTS.md` section 12 puts student login out of scope for v1, so a student is a random
`session_id` and nothing else. The id is also what entitles a caller to rate an answer.

| Method | Path | Result |
|---|---|---|
| POST | `/chat` | `200` — answered or not; a fallback is not an error |
| POST | `/chat/feedback` | `204`; `404` when the query is not this session's |
| GET | `/categories` | `200` — the six categories plus All, each with starter questions |

The pipeline, in order:

1. **Normalise and hash** the raw question, so repeats group in the admin history.
2. **Pick a category** — the chip the student tapped, else the classifier's guess, else none.
   Classifying is word-boundary rules over the question; it is confident only when exactly one
   category matches. Unclassified is `NULL`, never `general`, because `general` is a real category and
   conflating the two would filter every general-filed document out of retrieval.
3. **Retrieve** with `hybrid_search` (RRF over a vector list and a keyword list, both capped) and
   hydrate the returned ids from `chunks` and `documents`, re-checking `is_active` and `status =
   'ready'` so a document deactivated between the two queries can never be cited.
4. **Decide.** `similarity` is `1 - cosine distance` and is `NULL` for a chunk that only the keyword
   list found, so the decision uses the maximum over every returned row. Below `SIMILARITY_THRESHOLD`
   the question never reaches the model — there is nothing to put in the prompt.
5. **Answer** from a prompt containing the six retrieval rules, the question, and one delimited block
   per chunk. The model returns `{"answerable", "answer", "used_sources"}` as JSON, validated by
   Pydantic and re-checked against the labels that were actually supplied.
6. **Validate citations.** A label that was not supplied, or an answer claiming to be answerable with
   no sources, is rejected and the model is asked once more with a corrective note appended after the
   source blocks. Two unusable responses fall back.
7. **Log** `queries`, `query_sources` and — for a fallback — `unanswered_queries`, in one transaction.

Three properties worth stating plainly:

- **The prompt contains only retrieved chunks.** Not conversation history, not the previous answer.
  History builds the *search* text, which is what lets a follow-up like "and the late fee?" retrieve
  sensibly; the stored and hashed question is the raw one.
- **Every citation field comes from a database row.** The model returns labels and nothing else — it
  is never asked for a title, a page or a date, so it has no opportunity to invent one.
- **A fallback writes both rows.** No exception, including when the model returned `answerable:
  false`. If the log write itself fails the answer still returns: a database that refuses the log
  must not also take away the answer the student already has.

`/chat` is rate limited to `CHAT_RATE_LIMIT_PER_MINUTE` per minute, counted separately per client IP
and per session, so one tab cannot spend everyone's allowance. Over either limit it returns `429` with
`Retry-After`. The limiter is in-process, which is the same single-instance assumption the startup
reaper documents.

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

The chat tests work the same way: only the two providers, the chunk repository and the query log are
fakes, so the real `RetrievalService` and `AnsweringService` run behind `POST /chat`. The fallback
tests assert on the fake model's *call count* rather than the answer text, so a plausible-sounding
answer cannot pass a test that was meant to prove the model was never asked.

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
unique chunk index, the single-transaction property of `replace_document_chunks` (it calls the
function with an embedding that cannot cast, then asserts the previous chunks are still there), and
the same property for `log_query` plus the ownership check in `record_feedback`. It is skipped unless
you opt in:

```bash
pip install "psycopg[binary]"
RUN_DB_TESTS=1 TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/postgres pytest -q -m integration
```

`test_ingestion_e2e.py` and `test_chat_e2e.py` run a generated PDF through real Storage and real
Gemini, then ask a question it answers and one it does not. They need a live project and a real key,
and every document they create is deleted again:

```bash
RUN_LIVE_TESTS=1 pytest -q tests/test_ingestion_e2e.py tests/test_chat_e2e.py
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

The student UI reads **one** variable, documented in `frontend/.env.example`:

```
VITE_API_URL=http://localhost:8000
```

It is the only thing the chat needs. The Supabase pair below belongs to Phase 5's admin login: a
student-facing chat has no Supabase client and no auth, so it must not be handed a key it has no use
for. The names are fixed ahead of that phase anyway:

```
VITE_SUPABASE_URL=https://your-project-ref.supabase.co
VITE_SUPABASE_ANON_KEY=<anon-key>          # Phase 5
```

Only the anon key would be exposed to the browser. It grants nothing directly — every table has row
level security enabled with default-deny, so PostgREST returns no rows to it. All reads and writes go
through the FastAPI backend, which holds the service role key.

The API paths carry no `/api` prefix, so `POST /chat`, `POST /chat/feedback` and `GET /categories`
are reached at `${VITE_API_URL}/chat` and so on. Every non-2xx body is exactly `{detail, code}`, and
`answered: false` is a **200**, not an error — it carries the fallback the server decided on.
