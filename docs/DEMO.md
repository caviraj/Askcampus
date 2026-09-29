# Running the demo

`AGENTS.md` section 1 fixes the demo target: **upload college documents → ask a question → retrieve →
answer with a source.** This is the script for that, in about ten minutes, plus what to do when
something in the room does not cooperate.

## Before the room fills

Everything here is one-time setup. Do it the day before, not in front of an audience.

**1. The backend is configured and the migrations are applied.** See the README's Setup section. The
`documents` Storage bucket is created by migration `0003`, so a project without the migrations fails
every upload with "Bucket not found".

**2. An admin user exists and is promoted.** Create the user in the Supabase dashboard (Auth → Users
→ Add user), then promote them once, in the SQL editor:

```sql
update public.profiles set role = 'admin' where id = '<the-user-uuid>';
```

A trigger creates the `profiles` row on signup, so the row is already there to update. The role is
read from this table on every admin request — never from the token — so this is the whole of the
authorisation setup.

**3. `frontend/.env` holds the two admin variables.** The student chat needs only `VITE_API_URL`, but
the sign-in screen needs these, and without them it says so plainly rather than failing on submit:

```
VITE_SUPABASE_URL=https://<project-ref>.supabase.co
VITE_SUPABASE_ANON_KEY=<anon-key>
```

Use the **anon** key. The service role key stays in the backend; `AGENTS.md` section 6.7.

**4. Both servers run.**

```bash
# terminal 1
cd backend && .venv/Scripts/activate && uvicorn app.main:app --reload --port 8000

# terminal 2
cd frontend && npm run dev
```

## The 60-second pre-flight

Don't skip this. Each of these answers a question you do not want to answer live.

```bash
curl -s localhost:8000/health                  # {"status":"ok",...}
curl -s localhost:8000/categories | head -c 200 # the six categories plus All
curl -i -s localhost:8000/admin/me | head -1    # 401 without a token -- the gate is closed
```

Then, in the browser, sign in at `http://localhost:5173/#/admin` and make sure **Documents** loads.
If that works, the database, the auth gate and the API are all up, and the rest is the pipeline.

A last check worth doing: ask an out-of-scope question on the chat page before anyone is watching,
and confirm the fallback message appears. It is the most likely thing to have broken and the least
likely thing to be noticed until it matters.

## The demo

### Beat 1 — it refuses before it answers (1 min)

On the chat page, no sign-in, ask:

> How do I apply for a passport?

Nothing has been uploaded yet, and even after it has been this is not in the corpus. The reply is the
fallback message from `DESIGN_SYSTEM.md` section 9, not a guess.

Say the thing this beat is for: the system answers from the documents and nothing else, so a question
the documents do not cover gets a refusal rather than a plausible invention. Everything after this is
about how it answers; this is about what it does when it can't.

### Beat 2 — upload the documents (3 min)

Sign in at `#/admin` and open **Documents**. Upload the six files from `eval/corpus/` — the same
documents the evaluation scores against, so what the report says and what the room sees are the same
fixture:

| File | Category |
|---|---|
| `examination-handbook.txt` | Examinations |
| `admission-brochure.txt` | Admissions |
| `academic-regulations.txt` | Academic processes |
| `campus-directory.txt` | Departments |
| `events-calendar.txt` | Events |
| `general-notices.txt` | General |

Each takes a few seconds. The dialog names the stage it is on — extracting, cleaning, chunking,
embedding, writing — and the row moves `uploaded → processing → ready`. Expand a row to see the
chunk count and the extracted text preview.

Two things worth pointing at while it runs:

- The **chunk count** is the unit of retrieval. A 40-page handbook becomes a few hundred chunks, and
  a question retrieves the handful nearest to it — that is the whole trick.
- A document that is not `ready` is **not searchable**. Uploading one and asking about it immediately
  is a supported way to see the fallback again.

They are `.txt` files on purpose: the PDF path exists and is what production uses, but a text file
has no extraction step to fail in front of an audience, and the room can open it and read the answer
themselves.

### Beat 3 — ask, and get a source (2 min)

Back on the chat page, ask:

> What is the late fee if I pay the examination fee after the due date?

The answer arrives with a **source slip** beside it — document title and section. Expand the slip: the
supporting sentence is highlighted inside the passage. Then ask a second one from a different
document, to show it is retrieving rather than matching a phrase:

> Who is the head of the Computer Science department?

The slip now names the Campus Directory instead of the Examination Handbook. Two questions, two
documents, each with the passage it came from.

If someone asks where the citation comes from: the model returns labels — `S1`, `S2` — and nothing
else. It is never asked for a title, a page or a date, so it has no opportunity to invent one; every
field on the slip is read from a database row. That is `AGENTS.md` section 6, rules 2 to 5.

### Beat 4 — the ones it got wrong are in a queue (2 min)

Ask an ambiguous one — a real question about a real document that the document does not answer:

> What is the hostel room rent per semester?

The directory has the hostel's gate timings, so retrieval finds *something*, and the system still
refuses rather than half-answering. That refusal is now on the admin side: open **Unanswered**, and
both this question and Beat 1's passport question are there, grouped, with a count.

Then **Overview**: the summary cards and the query-counts-by-category chart, both built from the same
`queries` rows. And **Query history**, where every question is listed with the sources its answer
cited, and the refusals sit alongside the answered ones.

The closing line for the whole demo: every answer is logged, every refusal is logged, and the
questions it could not answer are a list someone can act on — which is the point of the admin side
existing at all.

## What not to demo

Two known failures, both measured, neither hidden:

- **"What is the annual tuition fee for a postgraduate programme?"** cites the Examination Handbook's
  examination-fee section. The category classifier matches the bare word "fee" and routes the
  question to Examinations; the filtered search then scores that wrong chunk high enough that the
  wider search never runs. The correct passage scores *higher* unfiltered. This is a defect in
  `app/services/classifier.py`, not in retrieval, and it is the one citation the Gemini evaluation
  counts wrong.
- **"Which documents do I need to submit for admission?"** was refused on the Gemini run even though
  the right passage was retrieved at rank 1. The cause is in the answering step and is not yet
  explained; the run that would have captured the model's raw response coincided with a provider
  outage.

Both are in the report as open. If the room asks to see them, show them — a demo that only works on
the questions it was rehearsed on is worth less than one that shows where the edge is.

## Recovery

**The answer takes 30 seconds or returns an error.** The provider timeout is 30 s
(`provider_timeout_seconds`). If Gemini is slow, ask a different question rather than waiting in
silence.

**A "could not be reached" message.** The Gemini generation endpoint returns 503 under load; this
happened repeatedly during evaluation. The question is reported as unanswered and logged. The fix is
to ask again. Note that the answering path does *not* retry a transient provider error the way
ingestion does — that asymmetry is a known gap, listed in the report.

**Uploads fail.** Check the bucket first: `0003_documents_bucket.sql`. A project without the
migrations fails every upload the same way.

**The chat is slow on the first question after a restart.** The first `/chat` builds the JWKS cache
and warms the embedding client. Ask one question yourself, before the room arrives.

**Nothing loads and the console shows a CORS error.** `VITE_API_URL` and `CORS_ORIGINS` disagree
about the frontend's origin. Both default to `http://localhost:5173`; a demo on a different port
needs both changed.

## Rehearsing the numbers

The live demo is the qualitative half. The quantitative half is one command, and it is worth running
the morning of, because it is the same fixture the demo uploads:

```bash
python eval/run_eval.py                     # offline; no key, no network
python eval/run_eval.py --provider gemini   # the real model and embedder
```

See `eval/README.md` for what each run does and does not measure.
