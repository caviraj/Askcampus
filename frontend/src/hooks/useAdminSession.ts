import { useCallback, useEffect, useRef, useState } from "react";

import { refreshSession, signIn } from "../lib/api";
import {
  clearStoredSession,
  isExpired,
  needsRefresh,
  readStoredSession,
  storeSession,
} from "../lib/adminSession";
import { toErrorView } from "../lib/errors";
import type { AdminSession, ErrorView } from "../lib/types";

export type SessionState = "anonymous" | "signed-in";

export interface AdminSessionHandle {
  state: SessionState;
  session: AdminSession | null;
  /** The most recent sign-in failure, or null. Cleared on a successful sign-in. */
  error: ErrorView | null;
  signInWithPassword: (email: string, password: string) => Promise<void>;
  signOut: () => void;
}

/** How long before `expiresAt` the token is refreshed in the background. */
const REFRESH_MARGIN_MS = 60_000;

/**
 * The stored session, read once when the hook first renders.
 *
 * Read in a lazy initialiser rather than in an effect. An effect would mean a
 * first paint with no session, which renders the login form at an admin who is
 * already signed in -- the flash the old `restoring` state existed to hide. The
 * read is synchronous and the app has no server renderer, so there is nothing
 * to defer to.
 *
 * An expired session is reported as absent here and cleared by the effect
 * below: an initialiser runs during render, and removing a storage key is a
 * write.
 */
function initialSession(): AdminSession | null {
  const stored = readStoredSession();
  return stored !== null && !isExpired(stored) ? stored : null;
}

export function useAdminSession(): AdminSessionHandle {
  const [session, setSession] = useState<AdminSession | null>(initialSession);
  const [error, setError] = useState<ErrorView | null>(null);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    // The write that the initialiser deliberately left out. It touches no
    // state: the initialiser has already decided the session is absent, and
    // setting it again here would be the cascading render this avoids.
    const stored = readStoredSession();
    if (stored !== null && isExpired(stored)) clearStoredSession();
    return () => {
      mounted.current = false;
    };
  }, []);

  /** Persist and publish a session, and start the refresh timer for it. */
  const accept = useCallback((next: AdminSession) => {
    storeSession(next);
    setSession(next);
    setError(null);
  }, []);

  // Refresh shortly before expiry so a long-lived admin tab does not fail a
  // request with a token that expired while it sat open.
  useEffect(() => {
    if (session === null) return;
    const delay = Math.max(0, session.expiresAt - Date.now() - REFRESH_MARGIN_MS);
    const timer = window.setTimeout(() => {
      void refreshSession(session.refreshToken)
        .then((next) => {
          if (mounted.current) accept(next);
        })
        .catch(() => {
          // A refused refresh means the refresh token is done. Signing out is
          // the honest outcome: the alternative is leaving a token in place
          // that every request will now reject.
          if (mounted.current) {
            clearStoredSession();
            setSession(null);
          }
        });
    }, delay);
    return () => window.clearTimeout(timer);
  }, [session, accept]);

  const signInWithPassword = useCallback(
    async (email: string, password: string) => {
      setError(null);
      try {
        accept(await signIn(email.trim(), password));
      } catch (cause) {
        setError(toErrorView(cause));
      }
    },
    [accept],
  );

  const signOut = useCallback(() => {
    // Local only. Supabase's token revocation endpoint needs the service role
    // key, which is backend-only (AGENTS.md section 7), so the frontend cannot
    // revoke; it drops the token instead. The refresh token stays valid until
    // it expires, which is the same window any stolen token would have.
    clearStoredSession();
    setSession(null);
  }, []);

  return {
    state: session === null ? "anonymous" : "signed-in",
    session,
    error,
    signInWithPassword,
    signOut,
  };
}

export { needsRefresh };
