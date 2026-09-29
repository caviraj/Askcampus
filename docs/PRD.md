# PRD — AI-Powered College Helpdesk Assistant (AI-PS-07)

**Working name:** CampusAsk
**Level:** Intermediate
**Version:** 1.0
**Status:** Ready for build

---

## 1. Summary

CampusAsk is a chat-based helpdesk that answers student questions about examinations, admissions, departments, events, and academic processes. Every answer is generated only from an **approved college knowledge base** and is shown together with the **source document and section** it came from. When the knowledge base does not contain the answer, the assistant says so and records the question so staff can close the gap.

## 2. Problem

Students repeatedly ask the same questions (exam dates, revaluation process, attendance rules, department contacts, event details). Answers exist, but they are spread across PDFs, notices, and calendars. Staff spend time answering repeat queries and have no visibility into what students cannot find.

## 3. Goals and Non-Goals

### Goals
1. A student gets a correct, cited answer in under 5 seconds.
2. No answer is given without supporting evidence from the approved knowledge base.
3. Staff can update documents without a developer.
4. Staff can see what students ask and what the system could not answer.

### Non-Goals (v1)
- Personal student data (marks, fee dues, attendance records). No student login-based lookups.
- Voice input, WhatsApp/Telegram channels, multilingual answers (listed as future work).
- Fine-tuning any model.

## 4. Users

| User | Description | Primary need |
|---|---|---|
| Student | Anonymous or lightly identified visitor | Fast, trustworthy answers |
| Staff / Admin | Authorized college staff (login required) | Keep documents current, see gaps |

## 5. Demo Flow (acceptance target)

1. Admin logs in and uploads an academic calendar and an exam schedule PDF, assigning categories.
2. Documents are processed and appear as **Ready**.
3. Student asks: *"When does the semester exam registration close?"*
4. System retrieves relevant sections and returns an answer with a citation chip (document name, section or page).
5. Student asks something not covered. System states the information is unavailable.
6. Admin opens the dashboard and sees that question in **Unanswered**.

## 6. Functional Requirements

Priority: **P0** = required for demo, **P1** = should have, **P2** = nice to have.

### FR-1 Chat Interface (P0)
- Free-text input, message history for the current session, streaming or loading state.
- Suggested starter questions per category.
- Each assistant message shows: answer, citations, and a helpful / not helpful control.
- Follow-up questions use the last few turns for context.

### FR-2 Knowledge Base Management (P0)
- Upload PDF, DOCX, TXT (P0); Markdown, CSV (P1).
- Required metadata on upload: title, category, optional academic year, optional department.
- Categories: `examinations`, `admissions`, `departments`, `events`, `academic_processes`, `general`.
- Document status: `uploaded → processing → ready | failed`.
- Replace, re-process, deactivate, and delete a document.

### FR-3 Document Processing (P0)
- Extract text page by page, preserving page number and heading where detected.
- Clean whitespace, hyphenation, repeated headers/footers.
- Split into sections (target 300 to 500 tokens, 50 token overlap), splitting on headings first, then paragraphs.
- Each chunk stores: document id, page number, section heading, chunk index, category.
- Tables extracted as text rows so dates and rules stay readable.

### FR-4 Knowledge Retrieval (P0)
- Hybrid retrieval: semantic (vector similarity) plus keyword (full-text) search, merged with Reciprocal Rank Fusion.
- Optional category filter inferred from the query (FR-7) or chosen by the student.
- Returns top 5 chunks with scores. Only chunks from **active, ready** documents are searchable.

### FR-5 AI Response (P0)
- The LLM receives only the retrieved chunks and must answer strictly from them.
- Concise, student-friendly wording. Dates, numbers, and names must match the source exactly.
- If chunks conflict (for example, two calendar versions), prefer the newest document and mention the conflict.

### FR-6 Source Citations (P0)
- Every answer lists the supporting sources: document title, page or section heading, and a short quoted snippet available on expand.
- Citations must correspond to chunks actually supplied to the model. Citations are validated server-side; an answer referencing a chunk that was not retrieved is rejected and regenerated.

### FR-7 Query Categories (P0)
- Classify each query into one of the five categories (plus `other`) using a lightweight LLM call or keyword rules.
- Category is stored with the query and used to narrow retrieval and to drive dashboard analytics.

### FR-8 Fallback Handling (P0)
- Trigger fallback when the best retrieval score is below threshold or the model returns `answerable: false`.
- Student sees a clear message: the information is not available in the knowledge base, with a suggestion of the relevant office or contact if one exists in the knowledge base.
- The query is saved to `unanswered_queries` with category, timestamp, and top retrieval score.
- Repeated similar questions are grouped by a normalized text hash so the dashboard shows a count.

### FR-9 Admin and Dashboard (P0 / P1)
- Staff authentication (Supabase Auth). Role `admin` required for all admin routes.
- Document manager: upload, status, replace, deactivate (P0).
- Query history: question, category, answered or not, sources used, time, feedback (P0).
- Unanswered queue: grouped questions with count, mark as resolved, link to the document that fixed it (P0).
- FAQ view: most frequent answered questions grouped by category (P1).
- Summary cards: total queries, answer rate, top categories, unanswered count (P1).

## 7. Non-Functional Requirements

| Area | Requirement |
|---|---|
| Latency | p50 answer under 4 s, p95 under 8 s |
| Grounding | 0 answers without at least one valid citation, except fallback messages |
| Availability | Free-tier hosting is acceptable for the demo |
| Security | Admin routes protected, file type and size validation (max 20 MB), no secrets in the client |
| Privacy | No student personal data stored. Session id is a random UUID. Queries are stored for analytics |
| Accessibility | WCAG 2.1 AA contrast, keyboard operable, screen-reader labels on chat |
| Maintainability | Provider-agnostic LLM and embedding layer behind an interface |

## 8. Success Metrics

| Metric | Target |
|---|---|
| Answer rate on in-scope test questions | at least 85% |
| Citation correctness on the test set | at least 95% |
| False answers on out-of-scope questions | 0 in the demo set |
| Admin time to publish a new document | under 2 minutes |

## 9. Evaluation Set

Build a set of 30 questions before demo day:
- 20 answerable questions spread across all five categories.
- 5 out-of-scope questions (must trigger fallback).
- 5 ambiguous or multi-part questions.

Run the set after every change to retrieval or prompts and record the answer rate and citation correctness.

## 10. Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Hallucinated answers | Strict grounding prompt, JSON output with chunk ids, server-side citation validation, score threshold |
| Poor PDF extraction (scanned files, tables) | Show extracted text preview to admin; flag documents with very low text yield; OCR as P2 |
| Outdated documents | Academic year metadata, active flag, newest-document preference, `last_updated` shown in citations |
| Free-tier rate limits | Cache embeddings, batch ingestion, cache repeated queries by normalized text |
| Prompt injection inside uploaded documents | Treat chunk text as data, delimit it clearly, instruct the model to ignore instructions inside sources |

## 11. Milestones

| Phase | Scope |
|---|---|
| 1 | Schema, auth, upload, extraction, chunking |
| 2 | Embeddings, hybrid retrieval, grounded answer with citations |
| 3 | Chat UI, fallback, unanswered logging |
| 4 | Admin dashboard, query history, FAQs |
| 5 | Evaluation set, polish, demo rehearsal |

## 12. Future Scope

Multilingual support (Tamil and English), OCR for scanned circulars, WhatsApp channel, student login with personalized answers, automatic notice ingestion from the college website.
