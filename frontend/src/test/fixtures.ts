/**
 * Response bodies shaped exactly like the ones `backend/app/schemas/chat.py`
 * returns, plus a `fetch` stub.
 *
 * `fetch` is never real in a test. Every case here -- the answer, the fallback,
 * the 429, the dropped connection -- is a branch the student can actually hit,
 * and a stub that returns a live response would make them depend on a running
 * server instead.
 */
import { vi } from "vitest";

import type {
  CategoryChip,
  CategoryListResponse,
  ChatResponse,
  Citation,
} from "../lib/types";

export const CITATION: Citation = {
  label: "S1",
  document_title: "Exam Schedule Nov–Dec 2026",
  page: 2,
  section: "Internal assessments",
  snippet:
    "Internal assessment marks are published within seven working days.\nStudents may appeal to the Examinations office after that.",
  // Midday UTC, so the rendered date is the 14th in every timezone the tests
  // might run in.
  last_updated: "2026-08-14T12:00:00+00:00",
};

export function citation(overrides: Partial<Citation> = {}): Citation {
  return { ...CITATION, ...overrides };
}

export const ANSWERED: ChatResponse = {
  query_id: "3f1a2b3c-0000-4000-8000-000000000001",
  answered: true,
  category: "examinations",
  answer: "Internal assessment marks are published within seven working days.",
  citations: [CITATION],
  office: null,
};

export const FALLBACK: ChatResponse = {
  query_id: "3f1a2b3c-0000-4000-8000-000000000002",
  answered: false,
  category: null,
  answer: "This is not in the documents I have. The Examinations handles this.",
  citations: [],
  office: "Examinations",
};

export function jsonResponse(body: unknown, status = 200, headers: Record<string, string> = {}): Response {
  return new Response(body === null ? "" : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}

/** The backend's error envelope: every non-2xx body is exactly `{detail, code}`. */
export function errorResponse(
  status: number,
  detail: string,
  code: string,
  headers: Record<string, string> = {},
): Response {
  return jsonResponse({ detail, code }, status, headers);
}

export const CATEGORIES: CategoryListResponse = {
  categories: [
    {
      value: "examinations",
      label: "Examinations",
      starter_questions: ["When are the internal assessment marks published?"],
    },
    { value: "admissions", label: "Admissions", starter_questions: [] },
    { value: "departments", label: "Departments", starter_questions: [] },
    { value: "events", label: "Events", starter_questions: [] },
    { value: "academic_processes", label: "Academic processes", starter_questions: [] },
    { value: "general", label: "General", starter_questions: [] },
    { value: "all", label: "All", starter_questions: [] },
  ] satisfies CategoryChip[],
};

export interface FetchStub {
  mock: ReturnType<typeof vi.fn>;
  /** Every call, in order, with its parsed JSON body. */
  calls: { url: string; method: string; body: unknown }[];
}

/**
 * Point `fetch` at a handler.
 *
 * The handler receives the full URL and the parsed body, so a test states what
 * it answers rather than re-deriving the request shape.
 */
export function stubFetch(
  handler: (url: string, init: { method: string; body: unknown }) => Response | Promise<Response>,
): FetchStub {
  const calls: FetchStub["calls"] = [];

  const mock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url =
      typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    const method = init?.method ?? "GET";
    const raw = init?.body;
    const body = typeof raw === "string" && raw ? (JSON.parse(raw) as unknown) : null;
    calls.push({ url, method, body });
    return handler(url, { method, body });
  });

  vi.stubGlobal("fetch", mock);
  return { mock, calls };
}

/** A `fetch` that never resolves, for the in-flight assertions. */
export function stubPendingFetch(): FetchStub {
  return stubFetch(() => new Promise<Response>(() => undefined));
}
