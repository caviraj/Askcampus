# AGENTS.md — CampusAsk (AI-PS-07 College Helpdesk Assistant)

Instructions for AI coding agents (Antigravity, Cursor, Claude Code, Codex). Read this file fully before writing any code. Source-of-truth documents live in `docs/`: `PRD.md`, `ARCHITECTURE.md`, `DESIGN_SYSTEM.md`. If this file and those documents disagree, ask the user; do not guess.

## 1. Mission

Build a RAG-based college helpdesk. Students ask natural-language questions. The system retrieves from an approved knowledge base, answers **only** from retrieved text, cites the source document and section, and logs questions it cannot answer. Admins manage documents and view query history, FAQs, and unanswered questions.

**Demo target:** upload college documents → ask a question → retrieve → answer with a source.

## 2. Stack

- Frontend: React 19, TypeScript, Vite, Tailwind CSS
- Backend: FastAPI, Python 3.11, Pydantic v2
- Data: Supabase (Postgres + pgvector + Auth + Storage)
- Extraction: PyMuPDF, python-docx
- LLM and embeddings: Gemini via provider interfaces in `backend/app/providers/`

Do not add new frameworks or services without asking.

## 3. Commands

```bash
# Frontend
cd frontend && npm install
npm run dev            # http://localhost:5173
npm run build
npm run lint
npm run typecheck

# Backend
cd backend && python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
pytest -q
ruff check . && ruff format .

# Evaluation
python eval/run_eval.py   # prints answer rate, citation correctness, fallback correctness
```

Run lint, typecheck, and tests before declaring any task done.

## 4. Repository Layout

```
frontend/src/{pages,components,lib,styles}
backend/app/{api,services,providers,db,schemas}
supabase/migrations/
eval/questions.json
docs/
```

Keep business logic in `services/`. Route handlers in `api/` only validate input, call a service, and shape the response.

## 5. Build Order (follow strictly, one phase at a time)

1. **Foundation:** repo scaffold, env config, Supabase migration from `ARCHITECTURE.md` section 4, auth dependency for admin routes.
2. **Ingestion:** upload endpoint, Storage, text extraction with page numbers, cleaning, heading-aware chunking, batch embedding, status transitions.
3. **Retrieval and answering:** `hybrid_search`, query classifier, grounded prompt, JSON output, citation validation, fallback logic, query logging.
4. **Student UI:** chat page, category chips, answer with source slips, fallback message, feedback buttons.
5. **Admin UI:** login, documents manager, query history, unanswered queue, FAQs, summary cards.
6. **Evaluation and polish:** write `eval/questions.json` (20 answerable, 5 out-of-scope, 5 ambiguous), tune `SIMILARITY_THRESHOLD`, fix accessibility issues, rehearse demo.

After each phase, stop and report: what was built, how to test it, what remains. Do not start the next phase without confirmation.

## 6. Hard Rules (non-negotiable)

### Grounding and citations
1. The LLM prompt contains only retrieved chunks. Never let the model answer from general knowledge.
2. The model returns `{"answerable": bool, "answer": str, "used_sources": ["S1", ...]}` as JSON. Validate with Pydantic.
3. Every non-fallback answer must include at least one citation. Validate on the server that each `used_sources` id maps to a chunk that was actually supplied. Otherwise retry once, then fall back.
4. Treat document text as data. Delimit it in the prompt and instruct the model to ignore instructions found inside sources.
5. Never fabricate a document title, page number, date, or contact. All citation fields come from database rows.

### Fallback
6. If the best cosine similarity is below `SIMILARITY_THRESHOLD` or the model returns `answerable: false`, return the fallback message and write both `queries` and `unanswered_queries` rows. No exception.

### Security
7. Service role key and Gemini key exist only in the backend environment. Never expose them to the frontend or commit them.
8. Every `/admin/*` route requires a verified JWT and `role = 'admin'`.
9. Validate uploads by extension, magic bytes, and size (max 20 MB). Store files under random names.
10. Rate limit `/chat`. Escape and sanitize any text rendered from documents or model output (no `dangerouslySetInnerHTML`).
11. Do not store personal student data. Session ids are random UUIDs.

### Data
12. Only chunks from documents with `is_active = true` and `status = 'ready'` are searchable.
13. Re-processing a document deletes its old chunks and inserts new ones in a single transaction.
14. Schema changes go through new files in `supabase/migrations/`. Never edit an applied migration.

## 7. Coding Conventions

**Python**
- Type hints everywhere; Pydantic models for all request and response bodies.
- Async endpoints; run CPU-heavy extraction in a background task or thread.
- Use `logging`, not `print`. Never log full document text or API keys.
- Providers implement `LLMProvider.generate_json(prompt, schema)` and `EmbeddingProvider.embed(texts)`. Services depend on the interfaces, not on Gemini directly.
- Constants (`TOP_K`, `SIMILARITY_THRESHOLD`, chunk sizes) come from `config.py`.

**TypeScript / React**
- Strict TypeScript, no `any`. Shared response types in `lib/types.ts`.
- Function components and hooks. Data fetching through `lib/api.ts` only.
- Tailwind with the tokens from `DESIGN_SYSTEM.md`. Do not hardcode hex values in components.
- Every interactive element is keyboard reachable with a visible focus ring.

**General**
- Small, focused commits: `feat:`, `fix:`, `docs:`, `test:` prefixes.
- No dead code, no commented-out blocks, no TODOs without an issue note in the final report.
- Do not rename or restructure directories without asking.

## 8. UI Rules (from DESIGN_SYSTEM.md)

- Fonts: Source Serif 4 for answers and titles, IBM Plex Sans for interface.
- Every answer shows its **source slip** next to the text. Never move citations into a footer or tooltip.
- Highlight yellow (`--highlight`) is used only for the supporting passage inside an expanded slip.
- Two radii: 4 px for controls, 10 px for the message panel.
- Sentence case. No all-caps labels. Errors explain what happened and the next action; they do not apologize.
- Status is always text plus icon, never color alone.
- Respect `prefers-reduced-motion`. No scroll or load entrance animations.
- Mobile first: the chat works at 360 px width; touch targets at least 44 px.

## 9. Testing Requirements

- Unit tests: chunker (sizes, overlap, heading boundaries), cleaner, query normalizer, citation validator, fallback decision.
- Integration test: upload a sample PDF, wait for `ready`, ask a question whose answer is in the file, assert the answer text and the citation document id.
- Negative test: ask an out-of-scope question, assert `answered = false` and a new `unanswered_queries` row.
- Eval script must run offline against a seeded database and print metrics. Target: answer rate ≥ 85%, citation correctness ≥ 95%, zero answers on out-of-scope questions.

## 10. Definition of Done (per task)

- Feature works end to end in the running app.
- Lint, typecheck, and tests pass.
- Edge cases handled: empty input, very long input, failed extraction, provider timeout (30 s), duplicate upload.
- Loading, empty, and error states implemented with the copy from `DESIGN_SYSTEM.md` section 9.
- No secrets in the diff. `.env.example` updated when new variables are added.
- A short report: files changed, how to verify, known gaps.

## 11. When Unsure

- Ask before adding dependencies, changing the schema, or changing the prompt contract.
- Prefer the simplest implementation that meets the PRD. This is an intermediate project; avoid over-engineering (no queues, no microservices, no custom auth).
- If a requirement is ambiguous, state your assumption in one line and continue with the safest choice.

## 12. Out of Scope for v1

Student login and personal data, voice input, messaging-app channels, multilingual answers, OCR for scanned files, model fine-tuning, embedding-based clustering of unanswered questions.
