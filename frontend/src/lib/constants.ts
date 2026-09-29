/**
 * The client's copies of the server's bounds, and the copy that is only ever
 * shown when the server could not be reached.
 *
 * The numbers mirror `backend/app/config.py` and `app/schemas/chat.py`. They
 * matter for two reasons: `MAX_HISTORY_MESSAGES` is what keeps a long answer
 * from turning the *next* question into a 422, and `MAX_QUESTION_CHARS` is what
 * makes the composer refuse before the request is spent.
 */
import type { Category, DocumentStatus, ErrorView } from "./types";

export const MAX_QUESTION_CHARS = 1000;
/** `chat_history_max_turns` is compared against a list of individual messages,
 *  so four means four messages -- two question-and-answer pairs, not four
 *  exchanges. The backend's name is misleading and this is the one place the
 *  real meaning is written down. */
export const MAX_HISTORY_MESSAGES = 4;
export const MAX_TURN_CHARS = 1000;

/** DESIGN_SYSTEM.md section 7: "maximum 3 visible, 'Show 2 more sources'". */
export const VISIBLE_SOURCES = 3;

/** Composer grows to this many lines, then scrolls (section 8). */
export const COMPOSER_MAX_LINES = 4;
export const COMPOSER_LINE_HEIGHT_PX = 24;

/**
 * DESIGN_SYSTEM.md section 9, verbatim.
 *
 * The fallback strings are deliberately *not* here: the server sends those in
 * the response body and the client renders `answer` as it arrives. Holding a
 * second copy would be a second source of truth, and the two would drift.
 */
export const COPY = {
  emptyChat: "Ask about exams, admissions, departments, events, or academic processes.",
  composerPlaceholder: "Ask about exams, admissions, departments, events…",
  networkError:
    "The answer could not be loaded. Check your connection and send the question again.",
  rateLimited: "Too many questions in a short time. Wait a minute and ask again.",
  loading: "Finding an answer",
  feedbackThanks: "Thanks for the feedback",
} as const;

/**
 * DESIGN_SYSTEM.md section 9's admin rows, verbatim, plus the in-between states
 * that section 9 does not have a row for.
 *
 * The rows it *does* define are quoted exactly. The added ones follow the same
 * voice -- state what happened, then the next action, never apologize -- and are
 * marked, so the ones that are the spec's can be told from the ones that are
 * mine. The upload progress steps are section 8's three named steps.
 */
export const ADMIN_COPY = {
  emptyDocuments: "No documents yet. Upload an academic calendar or exam schedule to begin.",
  emptyUnanswered: "Every question so far has an answer.",
  uploadSuccess: "Uploaded. Processing has started.",
  processingDone: "Ready. Students can now get answers from this document.",
  uploadFailed:
    "The file could not be read. Upload a text-based PDF, DOCX, or TXT file under 20 MB.",
  deleteConfirm:
    "Delete this document? Its sections are removed and answers can no longer cite it.",

  // Not in section 9.
  signInTitle: "Sign in to manage documents",
  signInFailed: "That email and password did not match. Check them and try again.",
  sessionExpired: "Your session has expired. Sign in again.",
  emptyQueries: "No questions yet. They appear here as students ask them.",
  emptyFaqs: "No answered questions yet. FAQs appear once students start asking.",
  loadFailed: "This could not be loaded. Try again.",
  saveFailed: "The change was not saved. Try again.",
  truncated:
    "Counts cover the most recent questions only, so a total may be lower than the real one.",
  resolvedNotice: "Marked resolved.",
  reopenedNotice: "Reopened.",
} as const;

/**
 * The six categories a document can be filed under, in section 8's chip order.
 *
 * Listed here rather than fetched: `/categories` returns chips with starter
 * questions, which is a student-facing shape, and a `<select>` needs the values
 * and nothing else. `formatCategory` supplies the labels, so there is still one
 * rule for how a category is spelled.
 */
export const DOCUMENT_CATEGORIES: Category[] = [
  "examinations",
  "admissions",
  "departments",
  "events",
  "academic_processes",
  "general",
];

/** The extensions the server accepts, for the file picker and the pre-check.
 *  Mirrors `allowed_extensions` in `backend/app/config.py`. */
export const ALLOWED_UPLOAD_EXTENSIONS = [".pdf", ".docx", ".txt"] as const;

/** Section 8's three named upload steps, in order. */
export const UPLOAD_STEPS = ["Uploading", "Extracting text", "Creating searchable sections"];

/** Section 8's status badge labels, keyed by the API's status value. */
export const STATUS_LABELS: Record<DocumentStatus, string> = {
  uploaded: "Uploaded",
  processing: "Processing",
  ready: "Ready",
  failed: "Failed",
};

/**
 * The admin navigation.
 *
 * Section 6's diagram shows four entries -- Docs, Queries, Unans., FAQs -- as an
 * abbreviated sketch of the shell. `Overview` is added first because PRD FR-9
 * requires a dashboard with summary cards and section 8 describes its contents,
 * and a screen nothing links to is a screen nobody opens. Stated as an
 * assumption rather than a silent addition.
 */
export const ADMIN_NAV = [
  { path: "/admin", label: "Overview" },
  { path: "/admin/documents", label: "Documents" },
  { path: "/admin/queries", label: "Query history" },
  { path: "/admin/unanswered", label: "Unanswered" },
  { path: "/admin/faqs", label: "FAQs" },
] as const;

/** The maximum upload size, mirroring `max_upload_mb` in `backend/app/config.py`.
 *  Checked before the request so a 30 MB file is refused in the browser rather
 *  than after a wasted upload. The server checks again; this is a convenience,
 *  not the enforcement. */
export const MAX_UPLOAD_MB = 20;
export const MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024;

/** Used when a 429 arrives without a readable `Retry-After`, which is what a
 *  missing CORS `expose_headers` looks like from here. */
export const DEFAULT_RETRY_AFTER_SECONDS = 60;

/** The last resort, so a blank or misconfigured `VITE_API_URL` still resolves
 *  to the documented dev server rather than to a relative path that 404s. */
export const DEFAULT_API_URL = "http://localhost:8000";

export const EMPTY_ERROR: ErrorView = {
  text: COPY.networkError,
  cooldownSeconds: null,
  canRetry: true,
};
