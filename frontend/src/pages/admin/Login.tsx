/**
 * The admin sign-in screen.
 *
 * A real `<form>` with a password input, so a password manager recognises it,
 * and so Enter submits without a key handler.
 *
 * When Supabase is not configured the page says so instead of offering a form
 * that cannot work: `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY` are absent
 * from a fresh checkout, and a failed request would read as a wrong password.
 */
import { useState } from "react";

import { AppHeader } from "../../components/AppHeader";
import { ADMIN_COPY } from "../../lib/constants";
import { isAuthConfigured } from "../../lib/api";
import type { ErrorView } from "../../lib/types";

interface LoginProps {
  error: ErrorView | null;
  onSignIn: (email: string, password: string) => Promise<void>;
}

export function Login({ error, onSignIn }: LoginProps) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const configured = isAuthConfigured();

  const submit = async () => {
    setBusy(true);
    try {
      await onSignIn(email, password);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen bg-paper">
      <AppHeader />
      <main className="mx-auto w-full max-w-md px-4 py-10">
        <h1 className="font-serif text-page-title text-ink">{ADMIN_COPY.signInTitle}</h1>

        {!configured ? (
          <p className="mt-4 rounded-panel border border-rule bg-surface px-4 py-3 text-ui text-ink-soft">
            Sign-in is not configured. Set VITE_SUPABASE_URL and
            VITE_SUPABASE_ANON_KEY in frontend/.env and restart the dev server.
          </p>
        ) : (
          <form
            className="mt-6 flex flex-col gap-4"
            onSubmit={(event) => {
              event.preventDefault();
              void submit();
            }}
          >
            <div className="flex flex-col gap-1">
              <label htmlFor="admin-email" className="font-sans text-ui-label text-ink">
                Email
              </label>
              <input
                id="admin-email"
                type="email"
                autoComplete="username"
                required
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                className="h-11 rounded-control border border-rule bg-surface px-3 font-sans text-composer text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-marine"
              />
            </div>

            <div className="flex flex-col gap-1">
              <label htmlFor="admin-password" className="font-sans text-ui-label text-ink">
                Password
              </label>
              <input
                id="admin-password"
                type="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                className="h-11 rounded-control border border-rule bg-surface px-3 font-sans text-composer text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-marine"
              />
            </div>

            {error && (
              <p role="alert" className="text-ui text-brick">
                {error.text}
              </p>
            )}

            <button
              type="submit"
              aria-disabled={busy}
              className={`h-11 rounded-control bg-marine px-4 font-sans text-ui-label font-semibold text-white hover:bg-marine-deep focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-marine ${
                busy ? "opacity-45" : ""
              }`}
            >
              Sign in
            </button>
          </form>
        )}
      </main>
    </div>
  );
}
