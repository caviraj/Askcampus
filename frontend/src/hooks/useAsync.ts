import { useCallback, useEffect, useRef, useState } from "react";

import { toErrorView } from "../lib/errors";
import type { ErrorView } from "../lib/types";

export interface AsyncResult<T> {
  data: T | null;
  error: ErrorView | null;
  /** True only while the *first* load is in flight. A reload keeps the previous
   *  data on screen, so a table does not blank itself while refreshing. */
  loading: boolean;
  reload: () => void;
}

interface Settled<T> {
  /** The request this answer belongs to. */
  key: string;
  data: T | null;
  error: ErrorView | null;
}

/**
 * One request, its three states, and a way to run it again.
 *
 * The loader is held in a ref so a page can write
 * `useAsync(() => fetchStats(token), token)` without the inline arrow
 * restarting the request on every render.
 *
 * The second argument is a *key*, not a dependency array. `loading` is derived
 * by comparing the key of the answer in hand with the key of the request
 * wanted, which is why nothing here calls `setState` while an effect body is
 * running: React's lint rules treat a synchronous state write in an effect as a
 * cascading render, and the honest fix is to compute the flag rather than store
 * it. A dependency array could not be compared cheaply without serialising
 * objects, so the caller states the identity explicitly.
 *
 * A response that arrives after the key changed, or after unmount, is discarded
 * rather than written: a stale page that resolves late would otherwise
 * overwrite the current one with data for a different query.
 */
export function useAsync<T>(load: () => Promise<T>, key: string): AsyncResult<T> {
  const [settled, setSettled] = useState<Settled<T> | null>(null);
  const [nonce, setNonce] = useState(0);

  const loader = useRef(load);
  useEffect(() => {
    loader.current = load;
  });

  const requestKey = `${nonce}\u0000${key}`;

  useEffect(() => {
    let active = true;
    loader.current().then(
      (value) => {
        if (active) setSettled({ key: requestKey, data: value, error: null });
      },
      (cause: unknown) => {
        if (active) setSettled({ key: requestKey, data: null, error: toErrorView(cause) });
      },
    );
    return () => {
      active = false;
    };
  }, [requestKey]);

  const reload = useCallback(() => setNonce((value) => value + 1), []);

  // An answer for an older key is not this request's answer, and neither is it
  // an error worth showing: a reload that fails should not display the previous
  // failure while the new attempt is still running.
  const current = settled !== null && settled.key === requestKey ? settled : null;

  return {
    data: current?.data ?? null,
    error: current?.error ?? null,
    loading: current === null,
    reload,
  };
}

/**
 * Repeat a request on an interval while `active`.
 *
 * Used for polling a document's status while it processes. Polling stops on
 * unmount, on a terminal status, and while the tab is hidden -- a background
 * tab polling every two seconds for a job that finished ten minutes ago is a
 * request nobody reads.
 */
export function usePolling(
  run: () => void,
  { active, intervalMs }: { active: boolean; intervalMs: number },
): void {
  const runner = useRef(run);
  useEffect(() => {
    runner.current = run;
  });

  useEffect(() => {
    if (!active) return;

    const tick = () => {
      if (!document.hidden) runner.current();
    };
    const timer = window.setInterval(tick, intervalMs);
    // The tab may have been hidden for the whole interval, so the first tick
    // after it comes back is what catches up rather than waiting another one.
    document.addEventListener("visibilitychange", tick);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", tick);
    };
  }, [active, intervalMs]);
}
