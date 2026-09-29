/**
 * A `matchMedia` jsdom does not have.
 *
 * Without it `useMediaQuery` throws on mount in every test, and DESIGN_SYSTEM.md
 * section 6's 1024 px branch -- inline expansion versus side column -- would be
 * a manual check rather than an assertion.
 *
 * It evaluates the `min-width` / `max-width` the query actually names, so a test
 * asking for a wide viewport gets one for the same reason a browser would, and
 * `setWidth` fires the real `change` event the hook subscribes to.
 */
import { vi } from "vitest";

export interface MatchMediaController {
  /** Move the viewport and fire `change` on every live query. */
  setWidth: (width: number) => void;
  /** Live listener count for a query, so unsubscribing on unmount is testable. */
  listenerCount: (query: string) => number;
}

function evaluate(query: string, width: number): boolean {
  const min = /min-width:\s*(\d+)px/.exec(query);
  if (min?.[1]) return width >= Number(min[1]);
  const max = /max-width:\s*(\d+)px/.exec(query);
  if (max?.[1]) return width <= Number(max[1]);
  return false;
}

export function mockMatchMedia(width: number): MatchMediaController {
  let current = width;
  const lists = new Map<string, { listeners: Set<(event: MediaQueryListEvent) => void> }>();

  const entryFor = (query: string) => {
    let entry = lists.get(query);
    if (!entry) {
      entry = { listeners: new Set() };
      lists.set(query, entry);
    }
    return entry;
  };

  const matchMedia = (query: string): MediaQueryList => {
    const entry = entryFor(query);
    return {
      media: query,
      // A getter rather than a stored boolean, so a list handed out before a
      // `setWidth` reports the new value when the hook next reads it.
      get matches() {
        return evaluate(query, current);
      },
      onchange: null,
      addEventListener: (_type: string, listener: (event: MediaQueryListEvent) => void) => {
        entry.listeners.add(listener);
      },
      removeEventListener: (_type: string, listener: (event: MediaQueryListEvent) => void) => {
        entry.listeners.delete(listener);
      },
      addListener: () => undefined,
      removeListener: () => undefined,
      dispatchEvent: () => true,
    } as unknown as MediaQueryList;
  };

  vi.stubGlobal("matchMedia", matchMedia);

  return {
    setWidth(next: number) {
      current = next;
      for (const [query, entry] of lists) {
        const event = { matches: evaluate(query, current), media: query } as MediaQueryListEvent;
        for (const listener of entry.listeners) listener(event);
      }
    },
    listenerCount(query: string) {
      return lists.get(query)?.listeners.size ?? 0;
    },
  };
}
