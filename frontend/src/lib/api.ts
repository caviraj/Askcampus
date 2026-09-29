/**
 * The only module in the app that calls `fetch` (AGENTS.md section 7).
 *
 * Everything it returns is typed, and every failure is an `ApiError` or a
 * `NetworkError` -- callers never see a raw `Response`, so no component has to
 * remember what the error envelope looks like.
 */
import { DEFAULT_API_URL } from "./constants";
import { ApiError, NetworkError } from "./errors";
import type {
  CategoryListResponse,
  ChatRequestPayload,
  ChatResponse,
  FeedbackRequest,
} from "./types";

const baseUrl = (): string => {
  const configured = import.meta.env.VITE_API_URL?.trim();
  // Trailing slashes stripped so `http://host/` and `http://host` cannot
  // produce `//chat`, which some proxies treat as a different path.
  return (configured || DEFAULT_API_URL).replace(/\/+$/, "");
};

/** Parse `Retry-After`, which is either delta-seconds or an HTTP date. */
function parseRetryAfter(response: Response): number | null {
  const raw = response.headers.get("Retry-After");
  if (!raw) return null;
  const seconds = Number.parseInt(raw, 10);
  if (Number.isFinite(seconds) && seconds >= 0) return seconds;
  const date = Date.parse(raw);
  if (Number.isNaN(date)) return null;
  return Math.max(0, Math.ceil((date - Date.now()) / 1000));
}

/**
 * Read a response, turning anything that is not a 2xx into a typed error.
 *
 * The body is read once as text and parsed, rather than trusting
 * `response.json()`: a proxy's HTML error page and a truncated body both throw
 * from `json()`, and both need to become the same `NetworkError` rather than an
 * unhandled rejection inside a component.
 */
async function readJson<T>(response: Response): Promise<T> {
  const text = await response.text();
  let parsed: unknown = null;
  try {
    parsed = text ? JSON.parse(text) : null;
  } catch {
    parsed = null;
  }

  if (!response.ok) {
    const envelope = parsed as { detail?: unknown; code?: unknown } | null;
    const detail = typeof envelope?.detail === "string" ? envelope.detail : "";
    const code = typeof envelope?.code === "string" ? envelope.code : "unknown_error";
    if (detail || code !== "unknown_error") {
      throw new ApiError(response.status, code, detail, parseRetryAfter(response));
    }
    throw new NetworkError();
  }

  return parsed as T;
}

/** Wrap `fetch` itself: a rejected promise is always a network failure. */
async function send(path: string, init: RequestInit): Promise<Response> {
  try {
    return await fetch(`${baseUrl()}${path}`, init);
  } catch (cause) {
    throw new NetworkError(undefined, { cause });
  }
}

const JSON_HEADERS = { "Content-Type": "application/json" } as const;

export async function askQuestion(payload: ChatRequestPayload): Promise<ChatResponse> {
  const response = await send("/chat", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(payload),
  });
  return readJson<ChatResponse>(response);
}

export async function sendFeedback(payload: FeedbackRequest): Promise<void> {
  const response = await send("/chat/feedback", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(payload),
  });
  // 204 with no body. `readJson` would parse it to null and return, but going
  // through it keeps the error handling in one place.
  await readJson<null>(response);
}

export async function fetchCategories(): Promise<CategoryListResponse> {
  const response = await send("/categories", { method: "GET" });
  return readJson<CategoryListResponse>(response);
}
