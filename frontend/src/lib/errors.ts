/**
 * The single mapping from a failure to what the student reads.
 *
 * Nothing outside this module decides error copy, so there is one place to
 * check that every message explains what happened and the next action, and no
 * apologies (DESIGN_SYSTEM.md section 9).
 */
import { COPY, DEFAULT_RETRY_AFTER_SECONDS } from "./constants";
import type { ErrorView } from "./types";

/** A non-2xx response whose body was the backend's `{detail, code}` envelope. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly detail: string;
  readonly retryAfterSeconds: number | null;

  constructor(
    status: number,
    code: string,
    detail: string,
    retryAfterSeconds: number | null = null,
  ) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.detail = detail;
    this.retryAfterSeconds = retryAfterSeconds;
  }
}

/**
 * No response arrived, or one arrived that was not the envelope.
 *
 * A proxy's HTML 502 and a CORS rejection land here too. From the student's
 * side they are the same event: the answer did not load.
 */
export class NetworkError extends Error {
  /**
   * The message is the student-facing copy, and the cause is carried rather
   * than shown. The browser's own wording for a dropped request -- "Failed to
   * fetch", "Load failed" -- is not a sentence to put in front of a student,
   * and `toErrorView` renders `message` directly.
   */
  constructor(message: string = COPY.networkError, options?: ErrorOptions) {
    super(message, options);
    this.name = "NetworkError";
  }
}

/**
 * The copy for a failure, plus whether a retry will help.
 *
 * The backend's `detail` is preferred wherever it exists. It already owns
 * DESIGN_SYSTEM.md section 9's wording -- the rate-limit string is byte-identical
 * on both sides -- and a client copy that drifted from it would be a second
 * source of truth for copy the spec fixes.
 */
export function toErrorView(error: unknown): ErrorView {
  if (error instanceof NetworkError) {
    return { text: error.message, cooldownSeconds: null, canRetry: true };
  }

  if (error instanceof ApiError) {
    // 429 is the one failure with a wait attached, and the only one where the
    // composer is held rather than simply re-enabled.
    if (error.status === 429) {
      return {
        text: error.detail || COPY.rateLimited,
        cooldownSeconds: error.retryAfterSeconds ?? DEFAULT_RETRY_AFTER_SECONDS,
        canRetry: false,
      };
    }
    // 503 and 422 carry a `detail` written for the student, so it is shown as
    // written. 403 and 404 are reachable only from the feedback call, which is
    // fire-and-forget and never renders any of this.
    return { text: error.detail || COPY.networkError, cooldownSeconds: null, canRetry: true };
  }

  // A bug rather than a server answer: a TypeError from a malformed payload.
  // The network copy is the honest thing to show, because from the student's
  // side nothing loaded.
  return { text: COPY.networkError, cooldownSeconds: null, canRetry: true };
}
