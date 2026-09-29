/**
 * Where the admin's tokens live between page loads.
 *
 * `localStorage`, which is a deliberate choice rather than a default, and the
 * trade is worth writing down because it is a security trade:
 *
 * - The refresh token is what makes an admin's session outlive a tab. Keeping
 *   it in `sessionStorage` (where the student's session id goes) would sign
 *   them out every time they closed the tab, which for a tool used in bursts
 *   between other work is the wrong answer.
 * - `localStorage` is readable by any script on this origin, so a cross-site
 *   scripting bug on the admin pages would hand over a refresh token. The
 *   alternative -- an httpOnly cookie -- needs a server that sets it, and this
 *   app's backend deliberately has no login route: Supabase Auth issues the
 *   token and the frontend holds it (`supabase/migrations/0001` says the
 *   frontend talks to Supabase Auth and to nothing else).
 * - What limits the damage: the refresh token is the *only* thing stored, the
 *   anon key it was exchanged for grants no table access under row level
 *   security, and every admin route re-reads the role from `profiles` on every
 *   request rather than trusting the token.
 *
 * Reading and writing are separate from React so that what is stored, and what
 * happens when the store is unavailable, is testable without a component.
 */
import type { AdminSession } from "./types";

const STORAGE_KEY = "campusask.admin.session";

/** Treat a session as expired slightly early, so a request is not sent with a
 *  token that expires while it is in flight. */
export const EXPIRY_SKEW_MS = 30_000;

function storage(): Storage | null {
  try {
    return window.localStorage;
  } catch {
    // Blocked by a privacy setting, or a sandboxed iframe. Sign-in still works
    // for this page view; it just does not survive a reload.
    return null;
  }
}

/** The stored session, or null when there is none or it cannot be trusted.
 *
 * A malformed value is discarded rather than repaired: a half-read session
 * would produce a request with an undefined token and a confusing 401.
 */
export function readStoredSession(): AdminSession | null {
  const store = storage();
  if (!store) return null;
  try {
    const raw = store.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed !== "object" || parsed === null) return null;
    const candidate = parsed as Partial<AdminSession>;
    if (
      typeof candidate.accessToken !== "string" ||
      typeof candidate.refreshToken !== "string" ||
      typeof candidate.expiresAt !== "number" ||
      typeof candidate.email !== "string"
    ) {
      return null;
    }
    return {
      accessToken: candidate.accessToken,
      refreshToken: candidate.refreshToken,
      expiresAt: candidate.expiresAt,
      email: candidate.email,
    };
  } catch {
    return null;
  }
}

export function storeSession(session: AdminSession): void {
  try {
    storage()?.setItem(STORAGE_KEY, JSON.stringify(session));
  } catch {
    // A full or unavailable store costs persistence, not the session.
  }
}

export function clearStoredSession(): void {
  try {
    storage()?.removeItem(STORAGE_KEY);
  } catch {
    // Nothing to do: the in-memory session is cleared either way.
  }
}

/** Whether the access token is close enough to expiry to need refreshing. */
export function needsRefresh(session: AdminSession, now: number = Date.now()): boolean {
  return session.expiresAt - EXPIRY_SKEW_MS <= now;
}

/** Whether the session is past the point of refreshing -- the refresh token
 *  itself has a lifetime, and this is the fallback when a refresh is refused. */
export function isExpired(session: AdminSession, now: number = Date.now()): boolean {
  return session.expiresAt <= now;
}
