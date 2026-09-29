/**
 * The client's copies of the server's bounds, and the copy that is only ever
 * shown when the server could not be reached.
 *
 * The numbers mirror `backend/app/config.py` and `app/schemas/chat.py`. They
 * matter for two reasons: `MAX_HISTORY_MESSAGES` is what keeps a long answer
 * from turning the *next* question into a 422, and `MAX_QUESTION_CHARS` is what
 * makes the composer refuse before the request is spent.
 */
import type { ErrorView } from "./types";

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
