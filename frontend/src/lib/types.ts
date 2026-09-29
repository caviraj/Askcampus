/**
 * The API's response types, mirrored from `backend/app/schemas/chat.py`.
 *
 * Mirrored rather than generated: there are four of them and no codegen in the
 * stack (AGENTS.md section 2). A field added on the server without a matching
 * change here shows up as a TypeScript error at the call site, which is the
 * point of keeping them in one file.
 */

/** The six document categories plus "all", the chip that filters nothing. */
export type Category =
  | "examinations"
  | "admissions"
  | "departments"
  | "events"
  | "academic_processes"
  | "general";

export type CategoryFilter = Category | "all";

/** One earlier message, for resolving what a follow-up question refers to. */
export interface HistoryTurn {
  role: "user" | "assistant";
  content: string;
}

/**
 * A source slip. Every field comes from a database row on the server — the
 * model returns only labels — so nothing here can be a fabrication.
 */
export interface Citation {
  label: string;
  document_title: string;
  /** 1-based. `null` for DOCX and TXT, which have no fixed pages. */
  page: number | null;
  section: string | null;
  /** The whole retrieved chunk, not an excerpt: the marked sentence is chosen
   *  from this on the client and a truncation could cut it off. */
  snippet: string;
  last_updated: string | null;
}

export interface ChatResponse {
  query_id: string;
  /** The discriminator. `false` is a fallback, which is a 200 and not an error. */
  answered: boolean;
  category: Category | null;
  answer: string;
  citations: Citation[];
  /** The office the fallback names, when it names one. Never on an answer. */
  office: string | null;
}

export interface CategoryChip {
  value: CategoryFilter;
  label: string;
  starter_questions: string[];
}

export interface CategoryListResponse {
  categories: CategoryChip[];
}

export interface FeedbackRequest {
  query_id: string;
  session_id: string;
  helpful: boolean;
}

/**
 * The `POST /chat` body.
 *
 * `category` is omitted rather than sent as `null` when no chip is selected, so
 * the backend runs its classifier. Sending `"all"` is *not* the same thing: that
 * resolves to "filter nothing" and skips the classifier entirely.
 */
export interface ChatRequestPayload {
  session_id: string;
  question: string;
  history: HistoryTurn[];
  category?: CategoryFilter;
}

/** One message in the visible thread. `kind` is the discriminator. */
export type Message =
  | { id: string; kind: "student"; text: string }
  | {
      id: string;
      kind: "answer";
      queryId: string;
      text: string;
      citations: Citation[];
      feedback: FeedbackState;
    }
  | {
      id: string;
      kind: "fallback";
      queryId: string;
      text: string;
      office: string | null;
      feedback: FeedbackState;
    }
  /** A request that never produced an answer. Carries the question so the
   *  student can send it again without retyping it. */
  | { id: string; kind: "error"; question: string; error: ErrorView };

export type FeedbackState = "idle" | "helpful" | "not_helpful";

/** Which slip is open, and in which answer. One at a time. */
export interface OpenSource {
  messageId: string;
  index: number;
}

/** What a failure reads as, and whether the student can act on it. */
export interface ErrorView {
  text: string;
  /** Seconds to wait, for the rate-limited state. `null` when not rate limited. */
  cooldownSeconds: number | null;
  canRetry: boolean;
}
