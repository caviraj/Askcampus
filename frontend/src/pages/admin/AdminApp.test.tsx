import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AdminApp } from "./AdminApp";
import { mockMatchMedia } from "../../test/matchMedia";

const STORAGE_KEY = "campusask.admin.session";

function storeSession(): void {
  window.localStorage.setItem(
    STORAGE_KEY,
    JSON.stringify({
      accessToken: "access-token",
      refreshToken: "refresh-token",
      // Farther out than the refresh margin, so the background refresh timer
      // does not fire during a test.
      expiresAt: Date.now() + 3_600_000,
      email: "registrar@college.example",
    }),
  );
}

/** The dashboard's own response, which the overview screen renders. */
const STATS = {
  window_days: 7,
  truncated: false,
  questions: { value: 0, previous: 0 },
  answered: { value: 0, previous: 0 },
  unanswered: { value: 0, previous: 0 },
  top_category: { category: null, count: 0, previous_category: null, previous_count: 0 },
  categories: [],
  unanswered_preview: [],
};

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

/**
 * A `fetch` that routes by path.
 *
 * Routing matters: the shell asks `/admin/me` and then the section it lands on
 * asks for its own data, so a stub that answered everything with the same body
 * would feed the dashboard an identity object.
 */
function stubApi(meStatus: number, meBody: unknown = {}): void {
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL) => {
      // Every call in this app passes a string path; `RequestInfo` allows an
      // object, which would stringify to "[object Object]" and route nothing.
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : "";
      if (url.includes("/admin/me")) return Promise.resolve(json(meStatus, meBody));
      if (url.includes("/admin/stats")) return Promise.resolve(json(200, STATS));
      return Promise.resolve(json(200, { items: [], total: 0, limit: 20, offset: 0 }));
    }),
  );
}

beforeEach(() => {
  window.location.hash = "#/admin";
});

afterEach(() => {
  window.localStorage.clear();
  window.location.hash = "";
  vi.unstubAllGlobals();
});

describe("AdminApp", () => {
  it("shows the sign-in form when no session is stored", () => {
    mockMatchMedia(1280);
    render(<AdminApp />);
    expect(screen.getByRole("heading", { name: "Sign in to manage documents" })).toBeInTheDocument();
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
  });

  it("does not flash the login form at an admin who is already signed in", () => {
    // The stored session is read during the first render, so there is no pass
    // in which the form is on screen.
    mockMatchMedia(1280);
    storeSession();
    stubApi(200, { id: "u1", full_name: "Registrar" });
    render(<AdminApp />);
    expect(screen.queryByLabelText("Password")).not.toBeInTheDocument();
  });

  it("opens the admin shell once the server confirms the role", async () => {
    mockMatchMedia(1280);
    storeSession();
    stubApi(200, { id: "u1", full_name: "Registrar" });
    render(<AdminApp />);

    // Both arrangements of the navigation are in the tree; CSS picks one.
    expect(
      await screen.findAllByRole("navigation", { name: "Admin sections" }),
    ).toHaveLength(2);
    expect(screen.getByText("Registrar")).toBeInTheDocument();
  });

  it("tells a signed-in non-admin that the account lacks the role", async () => {
    // Signing in and being allowed in are different things: Supabase Auth will
    // authenticate any account, and every /admin route needs role = 'admin'.
    mockMatchMedia(1280);
    storeSession();
    stubApi(403, { detail: "Admin role required.", code: "forbidden" });
    render(<AdminApp />);

    expect(
      await screen.findByText("This account is signed in but is not an admin."),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign out" })).toBeInTheDocument();
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
  });

  it("does not report a transport failure as a permissions problem", async () => {
    // A 500 has not judged the caller's role, and saying "not an admin" would
    // send an admin looking in the wrong place.
    mockMatchMedia(1280);
    storeSession();
    vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new TypeError("Failed to fetch"))));
    render(<AdminApp />);

    expect(await screen.findByText(/could not be loaded/)).toBeInTheDocument();
    expect(
      screen.queryByText("This account is signed in but is not an admin."),
    ).not.toBeInTheDocument();
  });

  it("offers both arrangements of the navigation, one per breakpoint", async () => {
    mockMatchMedia(1280);
    storeSession();
    stubApi(200, { id: "u1", full_name: null });
    render(<AdminApp />);

    await waitFor(() => expect(screen.getAllByRole("navigation")).toHaveLength(2));
    for (const nav of screen.getAllByRole("navigation")) {
      expect(nav).toHaveAccessibleName("Admin sections");
    }
  });

  it("lands on the overview and marks it as the current page", async () => {
    mockMatchMedia(1280);
    storeSession();
    stubApi(200, { id: "u1", full_name: null });
    render(<AdminApp />);

    const current = await screen.findAllByRole("link", { current: "page" });
    expect(current[0]).toHaveAttribute("href", "#/admin");
  });
});
