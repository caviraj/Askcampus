/**
 * The admin area: sign-in, the shell from DESIGN_SYSTEM.md section 6, and the
 * route switch inside it.
 *
 * Signing in is not the same as being allowed in. Supabase Auth will happily
 * authenticate any account in the project, and `AGENTS.md` section 6 requires
 * `role = 'admin'` on every `/admin/*` route. So `/admin/me` is called once
 * after sign-in and its answer decides: a 403 means the account is real but not
 * an admin, and it gets a plain explanation instead of five screens of failed
 * requests.
 */
import { useEffect } from "react";

import { AppHeader } from "../../components/AppHeader";
import { AdminNav } from "../../components/admin/AdminNav";
import { ADMIN_HOME, useRoute } from "../../lib/router";
import { fetchAdminIdentity } from "../../lib/api";
import { ADMIN_COPY, ADMIN_NAV } from "../../lib/constants";
import { ApiError } from "../../lib/errors";
import { useAdminSession } from "../../hooks/useAdminSession";
import { useAsync } from "../../hooks/useAsync";
import { Documents } from "./Documents";
import { Faqs } from "./Faqs";
import { Login } from "./Login";
import { Overview } from "./Overview";
import { Queries } from "./Queries";
import { Unanswered } from "./Unanswered";
import type { AdminIdentity } from "../../lib/types";

/**
 * The answer to "may this account use the admin area", as a value rather than
 * as a set of flags set from an effect.
 *
 * The distinction that matters is `denied` against `unreachable`. A 403 is the
 * server saying "authenticated, not an admin". A network failure or a 500 has
 * not made that judgement, and showing it as a permissions problem would send
 * an admin looking in the wrong place.
 */
type Gate =
  | { kind: "allowed"; identity: AdminIdentity }
  | { kind: "denied" }
  | { kind: "unreachable" };

/** Every hash the admin area answers to: the navigation is the list, so a
 *  section cannot be added to one and forgotten in the other. */
const KNOWN_PATHS = new Set<string>(ADMIN_NAV.map((item) => item.path));

export function AdminApp() {
  const { state, session, error, signInWithPassword, signOut } = useAdminSession();
  const { path, navigate } = useRoute();

  const token = session?.accessToken ?? null;
  const gate = useAsync<Gate>(
    async () => {
      if (token === null) return { kind: "unreachable" };
      try {
        return { kind: "allowed", identity: await fetchAdminIdentity(token) };
      } catch (cause) {
        return cause instanceof ApiError && cause.status === 403
          ? { kind: "denied" }
          : { kind: "unreachable" };
      }
    },
    token ?? "anonymous",
  );

  // A hash that matches no section is a stale bookmark, not a crash. Redirecting
  // to the dashboard is more use than a not-found page for a section that only
  // exists in the address that was kept.
  const known = KNOWN_PATHS.has(path);
  useEffect(() => {
    if (!known) navigate(ADMIN_HOME);
  }, [known, navigate]);

  if (state === "anonymous" || session === null) {
    return <Login error={error} onSignIn={signInWithPassword} />;
  }

  if (gate.loading) {
    return <CenteredMessage text="Loading" />;
  }

  // `gate.data` is non-null once loading is false; the loader always resolves.
  switch (gate.data?.kind) {
    case "denied":
      return (
        <CenteredMessage
          text="This account is signed in but is not an admin."
          action={{ label: "Sign out", onClick: signOut }}
        />
      );
    case "unreachable":
      return <CenteredMessage text={ADMIN_COPY.loadFailed} />;
    case "allowed":
      break;
    default:
      return <CenteredMessage text={ADMIN_COPY.loadFailed} />;
  }

  return (
    <div className="min-h-screen bg-paper">
      <AppHeader
        right={
          <div className="flex items-center gap-3">
            {gate.data.kind === "allowed" && (
              <span className="hidden text-ui-label text-ink-soft sm:inline">
                {gate.data.identity.full_name ?? gate.data.identity.id}
              </span>
            )}
            <button
              type="button"
              onClick={signOut}
              className="h-11 rounded-control px-2 font-sans text-ui-label text-marine hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-marine"
            >
              Sign out
            </button>
          </div>
        }
      />
      <div className="mx-auto flex w-full max-w-[1100px] flex-col md:flex-row">
        <AdminNav path={path} />
        <main className="min-w-0 flex-1 p-4 md:p-6">
          {renderSection(path, session.accessToken)}
        </main>
      </div>
    </div>
  );
}

function renderSection(path: string, token: string) {
  switch (path) {
    case "/admin/documents":
      return <Documents token={token} />;
    case "/admin/queries":
      return <Queries token={token} />;
    case "/admin/unanswered":
      return <Unanswered token={token} />;
    case "/admin/faqs":
      return <Faqs token={token} />;
    default:
      return <Overview token={token} />;
  }
}

function CenteredMessage({
  text,
  action,
}: {
  text: string;
  action?: { label: string; onClick: () => void };
}) {
  return (
    <div className="min-h-screen bg-paper">
      <AppHeader />
      <main className="mx-auto flex max-w-md flex-col items-start gap-4 px-4 py-10">
        <p aria-live="polite" className="text-ui text-ink-soft">
          {text}
        </p>
        {action && (
          <button
            type="button"
            onClick={action.onClick}
            className="h-11 rounded-control border border-marine px-4 font-sans text-ui-label text-marine hover:bg-marine-wash focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-marine"
          >
            {action.label}
          </button>
        )}
      </main>
    </div>
  );
}
