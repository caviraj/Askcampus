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

// ---------------------------------------------------------------------------
// Admin. Mirrored from `backend/app/schemas/documents.py` and `admin.py`.
// ---------------------------------------------------------------------------

export type DocumentStatus = "uploaded" | "processing" | "ready" | "failed";

/** A document row. Every field comes from the database; none is inferred. */
export interface AdminDocument {
  id: string;
  title: string;
  category: Category;
  academic_year: string | null;
  department: string | null;
  file_type: string;
  original_filename: string | null;
  file_size_bytes: number | null;
  status: DocumentStatus;
  is_active: boolean;
  error_message: string | null;
  page_count: number | null;
  chunk_count: number | null;
  extracted_chars: number | null;
  low_text_yield: boolean;
  text_preview: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface DocumentListResponse {
  items: AdminDocument[];
  total: number;
  limit: number;
  offset: number;
}

/** One chunk cited by a logged query. Titles are the copy taken at write time,
 *  so a source still names its document after the document is deleted. */
export interface QuerySource {
  rank: number;
  score: number | null;
  document_id: string | null;
  document_title: string | null;
  page_number: number | null;
  section_heading: string | null;
}

export interface AdminQuery {
  id: string;
  session_id: string;
  question: string;
  category: Category | null;
  answer: string | null;
  answered: boolean;
  top_score: number | null;
  latency_ms: number | null;
  created_at: string | null;
  sources: QuerySource[];
  /** Tri-state. `null` is "nobody rated it", which is not "not helpful". */
  helpful: boolean | null;
}

export interface QueryListResponse {
  items: AdminQuery[];
  total: number;
  limit: number;
  offset: number;
}

export type UnansweredStatus = "open" | "resolved";

export interface UnansweredGroup {
  normalized_hash: string;
  question: string;
  category: Category | null;
  count: number;
  first_asked_at: string | null;
  last_asked_at: string | null;
  status: UnansweredStatus;
  resolved_by_document: string | null;
  resolved_by_document_title: string | null;
}

export interface UnansweredListResponse {
  items: UnansweredGroup[];
  total: number;
  limit: number;
  offset: number;
  /** True when the grouping window filled, so `count` and `total` are lower
   *  bounds. Surfaced in the UI rather than hidden. */
  truncated: boolean;
}

export interface FaqItem {
  normalized_hash: string;
  question: string;
  count: number;
  last_asked_at: string | null;
}

export interface FaqGroup {
  /** `null` is the classifier declining to place the question, which is not a
   *  category -- `general` is. */
  category: Category | null;
  total: number;
  items: FaqItem[];
}

export interface FaqListResponse {
  groups: FaqGroup[];
  truncated: boolean;
}

export interface StatCard {
  value: number;
  previous: number;
}

export interface TopCategoryCard {
  category: Category | null;
  count: number;
  previous_category: Category | null;
  previous_count: number;
}

export interface CategoryCount {
  category: Category | null;
  count: number;
}

export interface StatsResponse {
  window_days: number;
  /** Applies to `categories` and `unanswered_preview`, which are grouped from a
   *  bounded window. The three count cards are exact either way. */
  truncated: boolean;
  questions: StatCard;
  answered: StatCard;
  unanswered: StatCard;
  top_category: TopCategoryCard;
  categories: CategoryCount[];
  unanswered_preview: UnansweredGroup[];
}

/** The admin session, as Supabase Auth returns it. */
export interface AdminSession {
  accessToken: string;
  refreshToken: string;
  /** Epoch ms. Derived from `expires_in` at sign-in, not parsed from the JWT. */
  expiresAt: number;
  email: string;
}

export interface AdminIdentity {
  id: string;
  full_name: string | null;
}
