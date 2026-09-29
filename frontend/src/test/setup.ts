/**
 * The two jsdom gaps that would otherwise make the interesting branches
 * untestable, plus the per-test reset.
 *
 * Kept deliberately small: every mock here is one that jsdom does not provide
 * at all. Anything jsdom *does* implement is tested against the real thing.
 */
import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach, vi } from "vitest";

import { resetSessionId } from "../lib/session";

beforeEach(() => {
  // jsdom does not implement scrolling, and two behaviours call it: scrolling
  // to the newest message, and to a newly opened slip. Without this every
  // render of the thread throws.
  Element.prototype.scrollIntoView = vi.fn();
});

afterEach(() => {
  cleanup();
  // Both are module- or storage-level state that would leak between tests: an
  // id reused from a previous file would hide a bug in `getSessionId`, and a
  // stubbed `matchMedia` from one file would silently answer another's query.
  sessionStorage.clear();
  resetSessionId();
  vi.unstubAllGlobals();
});
