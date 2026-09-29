/**
 * The student's session id: a random UUID and nothing else (AGENTS.md section
 * 6.11). No login, no personal data.
 *
 * `sessionStorage` rather than `localStorage`, because the id is what entitles
 * a caller to rate an answer and what the backend counts against the rate
 * limit. A tab-scoped id survives a reload -- so a rating still works after one
 * -- and is discarded when the tab closes, which leaves nothing durable about a
 * student on the device.
 */

const STORAGE_KEY = "campusask.session_id";

function mint(): string {
  // `crypto.randomUUID` is unavailable on insecure origins in some browsers.
  // The fallback is still a random UUID-shaped value and never leaves an empty
  // id behind, which would make every tab share one session.
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  const hex = "0123456789abcdef";
  let out = "";
  for (let index = 0; index < 36; index += 1) {
    if (index === 8 || index === 13 || index === 18 || index === 23) out += "-";
    else if (index === 14) out += "4";
    else if (index === 19) out += hex[(Math.random() * 4) | 0] ?? "8";
    else out += hex[(Math.random() * 16) | 0] ?? "0";
  }
  return out;
}

let cached: string | null = null;

/**
 * The id for this tab, minted on first use and stable afterwards.
 *
 * Reads and writes are both guarded: storage throws in a private window with
 * site data blocked, and a session id is not worth taking the app down for. If
 * it cannot be persisted, the id still works for the life of the page.
 */
export function getSessionId(): string {
  if (cached) return cached;

  try {
    const stored = sessionStorage.getItem(STORAGE_KEY);
    if (stored) {
      cached = stored;
      return cached;
    }
  } catch {
    // Storage refused. Fall through and mint one that lives in memory only.
  }

  cached = mint();
  try {
    sessionStorage.setItem(STORAGE_KEY, cached);
  } catch {
    // Not persisted, still usable.
  }
  return cached;
}

/** Test seam: forget the id so the next call mints a fresh one. */
export function resetSessionId(): void {
  cached = null;
}
