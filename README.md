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

**Phase 1 of 6 (Foundation) is complete.** What exists: repo scaffold, configuration, the Supabase
schema as migrations, the database client, and the admin auth gate. Nothing retrieves or answers yet
— that starts in Phase 2.

| Phase | Scope | State |
|---|---|---|
| 1 | Scaffold, config, migrations, admin auth gate | done |
| 2 | Ingestion: upload, extraction, chunking, embeddings | not started |
| 3 | Retrieval and answering | not started |
| 4 | Student UI | not started |
| 5 | Admin UI | not started |
| 6 | Evaluation and tuning | not started |

## Prerequisites

- Python 3.11 or newer (developed and tested on 3.14)
- Node.js 20 or newer — only needed from Phase 4
- A Supabase project with the `vector` extension — only needed from Phase 2

No Python packages beyond `requirements.txt` are needed to run Phase 1.

## Layout

```
backend/     FastAPI application
  app/api/         route handlers — validate input, call a service, shape the response
  app/services/    business logic
  app/providers/   LLM and embedding interfaces (no implementation yet)
  app/db/          Supabase client and data functions
  app/schemas/     Pydantic request and response models
  tests/
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

cp .env.example .env            # then fill in SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY
```

`.env` is gitignored. The service role key and the Gemini key are backend-only — they must never
reach the frontend or a commit.

Settings are validated at startup. If `SUPABASE_URL` is missing, the process exits with a
`ValidationError` naming the missing field rather than booting into a broken state.

## Run

```bash
cd backend
.venv/Scripts/activate
uvicorn app.main:app --reload --port 8000
```

- `GET /health` → `{"status": "ok", "version": ..., "environment": ...}`. Liveness only; it does not
  touch Supabase.
- `/docs` → interactive API documentation.

## Verify

```bash
cd backend
.venv/Scripts/activate

ruff check .              # lint
ruff format --check .     # formatting
pytest -q                 # tests
```

All three must pass before a change is considered done.

The tests run offline — no Supabase project, no network, no database. JWT tests use real EC keys and
really signed tokens; only the JWKS HTTP fetch is stubbed. Database access sits behind a repository
protocol that tests replace with an in-memory dict.

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

The migrations reference `auth.users`, so they need a real Supabase database — a bare Postgres will
reject them.

`test_migrations_integration.py` checks the applied schema (row level security is on for all tables,
`hybrid_search` returns cosine similarity, ranking works, triggers fire). It is skipped unless you
opt in:

```bash
RUN_DB_TESTS=1 DATABASE_URL=postgresql://... pytest -q -m integration
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
