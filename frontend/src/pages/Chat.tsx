/**
 * DESIGN_SYSTEM.md section 6's student page: a 56 px header, the thread, the
 * chips and the composer. One page, so App renders this directly and there is
 * no router (AGENTS.md section 11: nothing ahead of need).
 *
 * The page's whole job is the two things that must exist before the first
 * question: the session id, and the category list. Everything else is
 * `ChatWindow`.
 */
import { useEffect, useState } from "react";

import { AppHeader } from "../components/AppHeader";
import { ChatWindow } from "../components/ChatWindow";
import { fetchCategories } from "../lib/api";
import { getSessionId } from "../lib/session";
import type { CategoryChip } from "../lib/types";

export function Chat() {
  // Minted once, in an initialiser rather than a bare call in the body, so a
  // re-render cannot hand the window a different id mid-conversation.
  const [sessionId] = useState(getSessionId);
  const [categories, setCategories] = useState<CategoryChip[]>([]);

  useEffect(() => {
    let active = true;
    void fetchCategories()
      .then((payload) => {
        if (active) setCategories(payload.categories);
      })
      .catch((error: unknown) => {
        // The chips are a convenience, not the product: every question can be
        // typed without one and the backend classifies it. A failure here
        // leaves the chip row empty rather than taking the page down, and the
        // console is the honest place to record it -- there is no student-facing
        // copy for "the category list failed", and inventing one would report a
        // fault the student cannot act on.
        console.warn("The category list could not be loaded.", error);
      });
    return () => {
      active = false;
    };
  }, []);

  return (
    <div className="flex min-h-dvh flex-col bg-paper">
      <AppHeader />
      <ChatWindow sessionId={sessionId} categories={categories} />
    </div>
  );
}
