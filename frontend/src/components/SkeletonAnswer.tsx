/**
 * DESIGN_SYSTEM.md section 8: "Three-line skeleton in `--rule`, no spinner."
 *
 * The loading announcement is a visually hidden string rather than a
 * `role="progressbar"`, because nothing here reports progress -- an indeterminate
 * progressbar would claim a percentage that does not exist.
 */
import { COPY } from "../lib/constants";

export function SkeletonAnswer() {
  return (
    <div className="rounded-panel border border-rule bg-surface px-4 py-4" aria-busy="true">
      <span className="sr-only">{COPY.loading}</span>
      <div className="flex flex-col gap-2" aria-hidden="true">
        <span className="h-3 w-[92%] rounded-control bg-rule" />
        <span className="h-3 w-[78%] rounded-control bg-rule" />
        <span className="h-3 w-[64%] rounded-control bg-rule" />
      </div>
    </div>
  );
}
