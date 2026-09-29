import { describe, expect, it } from "vitest";

import { COPY, DEFAULT_RETRY_AFTER_SECONDS } from "./constants";
import { ApiError, NetworkError, toErrorView } from "./errors";

describe("toErrorView", () => {
  it("shows the backend's detail when there is one", () => {
    const view = toErrorView(new ApiError(503, "provider_timeout", "The answer took too long."));
    expect(view.text).toBe("The answer took too long.");
    expect(view.canRetry).toBe(true);
  });

  it("falls back to the network copy when a response arrived with no detail", () => {
    expect(toErrorView(new ApiError(500, "unknown_error", "")).text).toBe(COPY.networkError);
  });

  it("uses the network copy for a failure that never reached the server", () => {
    expect(toErrorView(new NetworkError()).text).toBe(COPY.networkError);
  });

  it("reads the retry window off a 429", () => {
    const view = toErrorView(
      new ApiError(429, "rate_limited", COPY.rateLimited, 12),
    );
    expect(view.text).toBe(COPY.rateLimited);
    expect(view.cooldownSeconds).toBe(12);
    // Held, not merely re-enabled: asking again inside the window is the thing
    // the rate limit is there to stop.
    expect(view.canRetry).toBe(false);
  });

  it("uses the default window when Retry-After was not readable", () => {
    // What a missing CORS `expose_headers` looks like from here: the request
    // fails correctly and the countdown silently falls back to this number.
    const view = toErrorView(new ApiError(429, "rate_limited", COPY.rateLimited, null));
    expect(view.cooldownSeconds).toBe(DEFAULT_RETRY_AFTER_SECONDS);
  });

  it("prefers the backend's rate-limit wording over its own", () => {
    const view = toErrorView(new ApiError(429, "rate_limited", "Too many questions.", 3));
    expect(view.text).toBe("Too many questions.");
  });

  it("treats a thrown non-Error as a network failure", () => {
    // A TypeError from a malformed payload is a bug, but from the student's side
    // nothing loaded, which is what the copy says.
    expect(toErrorView(new TypeError("Failed to fetch")).text).toBe(COPY.networkError);
  });
});
