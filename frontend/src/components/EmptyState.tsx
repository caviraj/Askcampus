/**
 * DESIGN_SYSTEM.md section 9's empty-chat line, verbatim.
 *
 * Distinct from the composer's placeholder (section 8), which is a different
 * string for a different job; both are used as written.
 */
import { COPY } from "../lib/constants";

export function EmptyState() {
  return (
    <p className="max-w-measure py-8 font-serif text-answer text-ink-soft">{COPY.emptyChat}</p>
  );
}
