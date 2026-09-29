/**
 * DESIGN_SYSTEM.md section 6: 56 px, product name on the left.
 *
 * The spec's sketch also shows an `[Ask staff]` action on the right. It is not
 * built: there is no contacts table, and AGENTS.md section 6.5 forbids naming a
 * contact that no row supplies. Recorded in the Phase 4 report rather than
 * filled in with a plausible-looking mailto.
 */
import type { ReactNode } from "react";

interface AppHeaderProps {
  /** The right-hand slot. Empty on the student chat, where the spec's
   *  `[Ask staff]` action is deliberately not built; the admin shell puts the
   *  signed-in name and a sign-out button here. */
  right?: ReactNode;
}

export function AppHeader({ right }: AppHeaderProps) {
  return (
    <header className="sticky top-0 z-20 h-14 border-b border-rule bg-surface">
      <div className="mx-auto flex h-full max-w-[1100px] items-center justify-between px-4">
        <span className="font-serif text-section-title font-semibold text-ink">CampusAsk</span>
        {right}
      </div>
    </header>
  );
}
