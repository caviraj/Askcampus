import { useCallback, useSyncExternalStore } from "react";

/**
 * Whether a media query currently matches.
 *
 * `useSyncExternalStore` over `matchMedia` rather than an effect plus state:
 * the effect version renders once with the wrong answer and corrects itself,
 * which on a desktop viewport would flash the source panel's inline position
 * before moving it to the side column. `useSyncExternalStore` reads the real
 * value during the first render, and re-reads it when React needs to confirm
 * the store has not changed underneath it.
 */
export function useMediaQuery(query: string): boolean {
  const subscribe = useCallback(
    (onChange: () => void) => {
      const list = window.matchMedia(query);
      list.addEventListener("change", onChange);
      return () => list.removeEventListener("change", onChange);
    },
    [query],
  );

  return useSyncExternalStore(
    subscribe,
    () => window.matchMedia(query).matches,
    // No `matchMedia` on the server, and this app has no server renderer; the
    // narrow layout is the safe assumption if one is ever added.
    () => false,
  );
}

/** DESIGN_SYSTEM.md section 6: at this width the source panel becomes a side
 *  column instead of an inline expansion. */
export const WIDE_LAYOUT_QUERY = "(min-width: 1024px)";
