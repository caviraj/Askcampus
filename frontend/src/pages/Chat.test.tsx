/**
 * The whole flow, against a stubbed `fetch`.
 *
 * Everything below the page is exercised through it rather than mocked, so a
 * break in the wiring between the composer, the reducer and the renderer fails
 * here rather than only by hand.
 */
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { Chat } from "./Chat";
import { COPY } from "../lib/constants";
import { mockMatchMedia } from "../test/matchMedia";
import {
  ANSWERED,
  CATEGORIES,
  FALLBACK,
  citation,
  errorResponse,
  jsonResponse,
  stubFetch,
} from "../test/fixtures";
import type { ChatResponse } from "../lib/types";

interface Deferred<T> {
  promise: Promise<T>;
  resolve: (value: T) => void;
}

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

type Handler = Parameters<typeof stubFetch>[0];

/** Render the page with the category list already answered, so no test has to
 *  reason about a second in-flight request. */
async function renderChat(handler: Handler, width = 360) {
  mockMatchMedia(width);
  const stub = stubFetch((url, init) =>
    url.endsWith("/categories") ? jsonResponse(CATEGORIES) : handler(url, init),
  );
  render(<Chat />);
  // A chip, not the group: the group's container is in the DOM from the first
  // paint with nothing in it, so waiting on it would not wait for anything.
  await screen.findByRole("radio", { name: /admissions/i });
  return stub;
}

function ask(question: string) {
  return userEvent.type(screen.getByRole("textbox"), `${question}{Enter}`);
}

describe("Chat", () => {
  it("announces the answer inside a live region that existed beforehand", async () => {
    // A region that mounts already holding the answer announces nothing, so it
    // has to be there from the first paint.
    await renderChat(() => jsonResponse(ANSWERED));
    expect(document.querySelector('[aria-live="polite"]')).not.toBeNull();
  });

  it("shows the skeleton while the answer is in flight", async () => {
    const pending = deferred<Response>();
    await renderChat(() => pending.promise);

    await ask("When are marks published?");
    expect(screen.getByText("When are marks published?")).toBeInTheDocument();
    expect(screen.getByText(COPY.loading)).toBeInTheDocument();

    // Resolving only starts the chain -- the body is read as text and parsed
    // behind several awaits -- so the assertion waits for the reply rather than
    // for the resolve.
    act(() => {
      pending.resolve(jsonResponse(ANSWERED));
    });
    expect(await screen.findByText(ANSWERED.answer)).toBeInTheDocument();
    expect(screen.queryByText(COPY.loading)).not.toBeInTheDocument();
  });

  it("shows the answer with its source slip beside it", async () => {
    await renderChat(() => jsonResponse(ANSWERED));
    await ask("When are marks published?");

    expect(await screen.findByText(ANSWERED.answer)).toBeInTheDocument();
    expect(screen.getByText("Exam Schedule Nov–Dec 2026, page 2")).toBeInTheDocument();
    // Not in a footer, not in a tooltip: an expandable card in the thread.
    expect(screen.getByRole("button", { name: /Exam Schedule/ })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
  });

  it("sends the question with the session id and no category until a chip is tapped", async () => {
    const stub = await renderChat(() => jsonResponse(ANSWERED));
    await ask("When are marks published?");

    const body = stub.calls.find((call) => call.url.endsWith("/chat"))?.body as Record<
      string,
      unknown
    >;
    expect(body.session_id).toEqual(expect.any(String));
    expect(body.question).toBe("When are marks published?");
    // Omitted rather than sent as null or "all", so the backend classifies it.
    expect(body).not.toHaveProperty("category");
    expect(body.history).toEqual([]);
  });

  it("sends the chosen category once a chip is tapped", async () => {
    const stub = await renderChat(() => jsonResponse(ANSWERED));
    await userEvent.click(screen.getByRole("radio", { name: /examinations/i }));
    await ask("When are marks published?");

    const body = stub.calls.find((call) => call.url.endsWith("/chat"))?.body as Record<
      string,
      unknown
    >;
    expect(body.category).toBe("examinations");
  });

  it("sends the earlier exchange with a follow-up, and never the question itself", async () => {
    const stub = await renderChat(() => jsonResponse(ANSWERED));
    await ask("First question");
    await screen.findByText(ANSWERED.answer);
    await ask("Second question");

    const bodies = stub.calls
      .filter((call) => call.url.endsWith("/chat"))
      .map((call) => call.body as { history: unknown[]; question: string });

    expect(bodies[0]?.history).toEqual([]);
    expect(bodies[1]?.history).toEqual([
      { role: "user", content: "First question" },
      { role: "assistant", content: ANSWERED.answer },
    ]);
  });

  it("opens one slip at a time", async () => {
    const two: ChatResponse = {
      ...ANSWERED,
      citations: [
        citation({ label: "S1", document_title: "Doc A" }),
        citation({ label: "S2", document_title: "Doc B" }),
      ],
    };
    await renderChat(() => jsonResponse(two));
    await ask("When are marks published?");

    const first = await screen.findByRole("button", { name: /Doc A/ });
    const second = screen.getByRole("button", { name: /Doc B/ });

    await userEvent.click(first);
    expect(first).toHaveAttribute("aria-expanded", "true");

    await userEvent.click(second);
    expect(second).toHaveAttribute("aria-expanded", "true");
    expect(first).toHaveAttribute("aria-expanded", "false");

    await userEvent.click(second);
    expect(second).toHaveAttribute("aria-expanded", "false");
  });

  it("moves the passage into a side column above 1024 px", async () => {
    await renderChat(() => jsonResponse(ANSWERED), 1280);
    await ask("When are marks published?");

    const slip = await screen.findByRole("button", { name: /Exam Schedule/ });
    await userEvent.click(slip);

    const aside = screen.getByRole("complementary", { name: "Cited passage" });
    expect(aside.querySelector("mark")).not.toBeNull();
    // One copy of the passage, in the column -- not one inline and one beside it.
    expect(document.querySelectorAll("mark")).toHaveLength(1);

    await userEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("complementary")).not.toBeInTheDocument();
  });

  it("renders a fallback as an answer, not as an error", async () => {
    await renderChat(() => jsonResponse(FALLBACK));
    await ask("What is the hostel mess menu?");

    expect(await screen.findByText(FALLBACK.answer)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    // The office the message names, and no invented contact detail. Scoped
    // through the card's own label, because "Examinations" is also a chip.
    expect(screen.getByText("Office").parentElement).toHaveTextContent("Examinations");
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("shows no office card when the documents named no office", async () => {
    await renderChat(() =>
      jsonResponse({ ...FALLBACK, office: null, answer: "This is not in the college documents I have." }),
    );
    await ask("What is the hostel mess menu?");

    expect(await screen.findByText("This is not in the college documents I have.")).toBeInTheDocument();
    expect(screen.queryByText("Office")).not.toBeInTheDocument();
  });

  it("records a rating once and confirms it", async () => {
    const stub = await renderChat(() => jsonResponse(ANSWERED));
    await ask("When are marks published?");
    await screen.findByText(ANSWERED.answer);

    await userEvent.click(screen.getByRole("button", { name: "Helpful" }));

    expect(screen.getByText(COPY.feedbackThanks)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Helpful" })).not.toBeInTheDocument();

    const posts = stub.calls.filter((call) => call.url.endsWith("/chat/feedback"));
    expect(posts).toHaveLength(1);
    expect(posts[0]?.body).toMatchObject({
      query_id: ANSWERED.query_id,
      helpful: true,
    });
  });

  it("keeps the confirmation when a rating never reaches the server", async () => {
    // Optimistic on purpose: DESIGN_SYSTEM.md section 8 defines no failure copy
    // for a rating, and re-enabling the buttons would invite a second tap over
    // something that already happened. The loss is logged, not shown.
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    await renderChat((url) =>
      url.endsWith("/chat/feedback")
        ? errorResponse(404, "No such query.", "query_not_found")
        : jsonResponse(ANSWERED),
    );
    await ask("When are marks published?");
    await screen.findByText(ANSWERED.answer);

    await userEvent.click(screen.getByRole("button", { name: "Helpful" }));
    await waitFor(() => expect(warn).toHaveBeenCalled());

    expect(screen.getByText(COPY.feedbackThanks)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("holds the composer and counts down when rate limited", async () => {
    await renderChat(() =>
      errorResponse(429, COPY.rateLimited, "rate_limited", { "Retry-After": "12" }),
    );
    await ask("When are marks published?");

    expect(await screen.findByRole("alert")).toHaveTextContent(COPY.rateLimited);
    expect(screen.getByRole("status")).toHaveTextContent("You can ask again in 12 seconds.");
    expect(screen.getByRole("textbox")).toBeDisabled();
    // Nothing to retry: the wait is the next action.
    expect(screen.queryByRole("button", { name: "Send it again" })).not.toBeInTheDocument();
  });

  it("offers a retry when the request itself failed", async () => {
    let attempts = 0;
    await renderChat(() => {
      attempts += 1;
      return attempts === 1
        ? errorResponse(503, "The answer took too long.", "provider_timeout")
        : jsonResponse(ANSWERED);
    });

    await ask("When are marks published?");
    expect(await screen.findByRole("alert")).toHaveTextContent("The answer took too long.");

    await userEvent.click(screen.getByRole("button", { name: "Send it again" }));
    expect(await screen.findByText(ANSWERED.answer)).toBeInTheDocument();
  });

  it("reports a dropped connection without pretending an answer arrived", async () => {
    await renderChat(() => Promise.reject(new TypeError("Failed to fetch")));
    await ask("When are marks published?");

    expect(await screen.findByRole("alert")).toHaveTextContent(COPY.networkError);
    expect(screen.getByRole("button", { name: "Send it again" })).toBeInTheDocument();
  });

  it("starts with the empty-chat line and replaces it on the first question", async () => {
    await renderChat(() => jsonResponse(ANSWERED));
    expect(screen.getByText(COPY.emptyChat)).toBeInTheDocument();

    await ask("When are marks published?");
    expect(screen.queryByText(COPY.emptyChat)).not.toBeInTheDocument();
  });
});
