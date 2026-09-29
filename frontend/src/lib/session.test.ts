import { beforeEach, describe, expect, it, vi } from "vitest";

import { getSessionId, resetSessionId } from "./session";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

beforeEach(() => {
  resetSessionId();
});

describe("getSessionId", () => {
  it("mints a UUID", () => {
    expect(getSessionId()).toMatch(UUID);
  });

  it("returns the same id on every call in a tab", () => {
    expect(getSessionId()).toBe(getSessionId());
  });

  it("reuses an id already in storage, so a rating still works after a reload", () => {
    const existing = "11111111-2222-4333-8444-555555555555";
    sessionStorage.setItem("campusask.session_id", existing);
    resetSessionId();
    expect(getSessionId()).toBe(existing);
  });

  it("keeps working when storage refuses to read", () => {
    // A private window with site data blocked throws on access. A session id is
    // not worth taking the page down for.
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("denied");
    });
    expect(getSessionId()).toMatch(UUID);
  });

  it("keeps working when storage refuses to write", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("denied");
    });
    const id = getSessionId();
    expect(id).toMatch(UUID);
    // Still stable for the life of the page, even though it was not persisted.
    expect(getSessionId()).toBe(id);
  });

  it("does not reuse an id from a previous page load when storage was cleared", () => {
    const first = getSessionId();
    sessionStorage.clear();
    resetSessionId();
    expect(getSessionId()).not.toBe(first);
  });
});
