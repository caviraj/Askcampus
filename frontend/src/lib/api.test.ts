import { describe, expect, it } from "vitest";

import { askQuestion, fetchCategories, sendFeedback } from "./api";
import { DEFAULT_API_URL } from "./constants";
import { ApiError, NetworkError } from "./errors";
import { ANSWERED, CATEGORIES, FALLBACK, errorResponse, jsonResponse, stubFetch } from "../test/fixtures";

const PAYLOAD = {
  session_id: "6f9a1c2e-0000-4000-8000-00000000000a",
  question: "When are marks published?",
  history: [{ role: "user" as const, content: "earlier" }],
};

describe("askQuestion", () => {
  it("posts the question to /chat with no /api prefix", async () => {
    const stub = stubFetch(() => jsonResponse(ANSWERED));
    await askQuestion({ ...PAYLOAD, category: "examinations" });

    expect(stub.calls[0]?.url).toBe(`${DEFAULT_API_URL}/chat`);
    expect(stub.calls[0]?.method).toBe("POST");
    expect(stub.calls[0]?.body).toEqual({ ...PAYLOAD, category: "examinations" });
  });

  it("omits category rather than sending null, so the classifier runs", async () => {
    const stub = stubFetch(() => jsonResponse(ANSWERED));
    await askQuestion(PAYLOAD);
    expect(stub.calls[0]?.body).not.toHaveProperty("category");
  });

  it("returns the citations with the answer", async () => {
    stubFetch(() => jsonResponse(ANSWERED));
    const response = await askQuestion(PAYLOAD);
    expect(response.answered).toBe(true);
    expect(response.citations[0]?.document_title).toBe(ANSWERED.citations[0]?.document_title);
  });

  it("treats an unanswerable question as a success, not a failure", async () => {
    // `answered: false` is a 200 carrying the fallback the server decided on.
    // Throwing here would render it with error styling and lose the office.
    stubFetch(() => jsonResponse(FALLBACK));
    const response = await askQuestion(PAYLOAD);
    expect(response.answered).toBe(false);
    expect(response.office).toBe("Examinations");
  });

  it("turns the error envelope into an ApiError", async () => {
    stubFetch(() => errorResponse(503, "The answer took too long.", "provider_timeout"));
    await expect(askQuestion(PAYLOAD)).rejects.toBeInstanceOf(ApiError);

    const error = await askQuestion(PAYLOAD).catch((cause: unknown) => cause);
    expect(error).toMatchObject({
      status: 503,
      code: "provider_timeout",
      detail: "The answer took too long.",
    });
  });

  it("reads Retry-After as delta-seconds", async () => {
    stubFetch(() => errorResponse(429, "Too many questions.", "rate_limited", { "Retry-After": "42" }));
    const error = await askQuestion(PAYLOAD).catch((cause: unknown) => cause);
    expect((error as ApiError).retryAfterSeconds).toBe(42);
  });

  it("reads Retry-After as an HTTP date", async () => {
    const soon = new Date(Date.now() + 30_000).toUTCString();
    stubFetch(() => errorResponse(429, "Too many questions.", "rate_limited", { "Retry-After": soon }));
    const error = await askQuestion(PAYLOAD).catch((cause: unknown) => cause);
    expect((error as ApiError).retryAfterSeconds).toBeGreaterThan(25);
    expect((error as ApiError).retryAfterSeconds).toBeLessThanOrEqual(30);
  });

  it("reports a dropped connection as a NetworkError", async () => {
    stubFetch(() => Promise.reject(new TypeError("Failed to fetch")));
    await expect(askQuestion(PAYLOAD)).rejects.toBeInstanceOf(NetworkError);
  });

  it("reports an HTML error page as a NetworkError, not a parse crash", async () => {
    // A proxy's 502 page is not the envelope. `response.json()` would throw
    // inside the component; this reads the body once and types the failure.
    stubFetch(() => new Response("<html>Bad gateway</html>", { status: 502 }));
    await expect(askQuestion(PAYLOAD)).rejects.toBeInstanceOf(NetworkError);
  });
});

describe("sendFeedback", () => {
  it("accepts a 204 with no body", async () => {
    const stub = stubFetch(() => new Response(null, { status: 204 }));
    await expect(
      sendFeedback({ query_id: "q1", session_id: "s1", helpful: true }),
    ).resolves.toBeUndefined();
    expect(stub.calls[0]?.url).toBe(`${DEFAULT_API_URL}/chat/feedback`);
  });

  it("surfaces a rejected rating", async () => {
    stubFetch(() => errorResponse(404, "No such query.", "query_not_found"));
    await expect(
      sendFeedback({ query_id: "q1", session_id: "s1", helpful: false }),
    ).rejects.toBeInstanceOf(ApiError);
  });
});

describe("fetchCategories", () => {
  it("returns the chips the server serves, including the ones the spec omits", async () => {
    stubFetch(() => jsonResponse(CATEGORIES));
    const payload = await fetchCategories();
    expect(payload.categories).toHaveLength(7);
    expect(payload.categories.map((chip) => chip.value)).toContain("general");
  });
});
