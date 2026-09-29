import { useLayoutEffect } from "react";
import type { RefObject } from "react";

import { COMPOSER_LINE_HEIGHT_PX, COMPOSER_MAX_LINES } from "../lib/constants";

/**
 * Grow a textarea with its content, up to a cap, then scroll instead.
 *
 * `useLayoutEffect` so the height is set before the browser paints: measuring in
 * an effect would show one frame at the old height on every keystroke.
 *
 * `scrollHeight` is the content's height regardless of the element's current
 * one, so the height has to be reset to `auto` before measuring -- otherwise
 * the box can only ever grow, since the measurement includes the height already
 * applied.
 */
export function useAutogrow(
  ref: RefObject<HTMLTextAreaElement | null>,
  value: string,
): void {
  useLayoutEffect(() => {
    const element = ref.current;
    if (!element) return;

    const maxHeight = COMPOSER_LINE_HEIGHT_PX * COMPOSER_MAX_LINES;
    element.style.height = "auto";
    const next = Math.min(element.scrollHeight, maxHeight);
    element.style.height = `${next}px`;
    element.style.overflowY = element.scrollHeight > maxHeight ? "auto" : "hidden";
  }, [ref, value]);
}
