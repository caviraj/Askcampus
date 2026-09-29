import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { mockMatchMedia } from "../test/matchMedia";
import { useMediaQuery, WIDE_LAYOUT_QUERY } from "./useMediaQuery";

describe("useMediaQuery", () => {
  it("reads the viewport during the first render, not after a correction", () => {
    mockMatchMedia(1280);
    const { result } = renderHook(() => useMediaQuery(WIDE_LAYOUT_QUERY));
    // No `act` around the assertion: an effect-based implementation would be
    // false here and only become true on a second pass.
    expect(result.current).toBe(true);
  });

  it("is false below the breakpoint", () => {
    mockMatchMedia(360);
    const { result } = renderHook(() => useMediaQuery(WIDE_LAYOUT_QUERY));
    expect(result.current).toBe(false);
  });

  it("follows the viewport across the breakpoint", () => {
    const media = mockMatchMedia(360);
    const { result } = renderHook(() => useMediaQuery(WIDE_LAYOUT_QUERY));

    act(() => media.setWidth(1280));
    expect(result.current).toBe(true);

    act(() => media.setWidth(768));
    expect(result.current).toBe(false);
  });

  it("unsubscribes on unmount", () => {
    const media = mockMatchMedia(360);
    const { unmount } = renderHook(() => useMediaQuery(WIDE_LAYOUT_QUERY));
    expect(media.listenerCount(WIDE_LAYOUT_QUERY)).toBe(1);

    unmount();
    expect(media.listenerCount(WIDE_LAYOUT_QUERY)).toBe(0);
  });
});
