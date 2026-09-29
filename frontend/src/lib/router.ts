/**
 * Routing, in about thirty lines and no dependency.
 *
 * `AGENTS.md` section 11 asks for the simplest thing that works and section 7
 * fixes the shape of the data layer, so a router library would be a third
 * dependency (after React and Tailwind) earning its place on four screens that
 * share one layout. `react-router-dom` would also want a server rewrite rule
 * for deep links; a hash route needs none, which matters because the build in
 * `dist/` is served as static files.
 *
 * The trade is real and worth stating: hash routes are not the pretty URLs a
 * history API gives, and there is no nested-route or loader machinery to grow
 * into. If the admin area ever needs either, this is the file to replace.
 */
import { useCallback, useSyncExternalStore } from "react";

/** The student chat, at no hash or at `#/`. */
export const CHAT_PATH = "/";
export const ADMIN_ROOT = "/admin";

/** Where a signed-in admin lands: the dashboard, which FR-9 requires. */
export const ADMIN_HOME = "/admin";

function currentPath(): string {
  const hash = window.location.hash;
  if (hash.length <= 1) return CHAT_PATH;
  const path = hash.slice(1);
  return path.startsWith("/") ? path : `/${path}`;
}

function subscribe(onChange: () => void): () => void {
  // `hashchange` covers the back button, a typed URL and a link alike, so
  // there is no second mechanism to keep in step with this one.
  window.addEventListener("hashchange", onChange);
  return () => window.removeEventListener("hashchange", onChange);
}

/**
 * The current path, and a way to change it.
 *
 * `useSyncExternalStore` rather than `useState` plus an effect: the hash is
 * external mutable state, and reading it during the first render is what stops
 * a deep link from flashing the chat page before the effect runs.
 */
export function useRoute(): { path: string; navigate: (path: string) => void } {
  const path = useSyncExternalStore(subscribe, currentPath, () => CHAT_PATH);

  const navigate = useCallback((next: string) => {
    window.location.hash = next;
  }, []);

  return { path, navigate };
}

/** A link that changes the hash, so it is reachable by keyboard and reported by
 *  a screen reader as the link it is -- rather than a button that navigates. */
export function routeHref(path: string): string {
  return `#${path}`;
}
