/**
 * DESIGN_SYSTEM.md section 8's status badge table.
 *
 * The colour is never the only signal: §3 requires a text label and an icon
 * beside it, so each state has all three. The classes are token names rather
 * than hex values, which is what `AGENTS.md` section 7 asks for -- Tailwind
 * resolves them from `tailwind.config.ts`, itself copied from §12.
 */
import { STATUS_LABELS } from "../../lib/constants";
import { AlertIcon, CheckIcon, ClockIcon, LoopIcon } from "../Icons";
import type { DocumentStatus } from "../../lib/types";

const BADGE: Record<DocumentStatus, { className: string; Icon: typeof ClockIcon }> = {
  uploaded: { className: "text-ink-soft", Icon: ClockIcon },
  processing: { className: "text-amber-ink", Icon: LoopIcon },
  ready: { className: "text-moss", Icon: CheckIcon },
  failed: { className: "text-brick", Icon: AlertIcon },
};

interface StatusBadgeProps {
  status: DocumentStatus;
}

export function StatusBadge({ status }: StatusBadgeProps) {
  const { className, Icon } = BADGE[status];
  return (
    <span className={`inline-flex items-center gap-1.5 font-sans text-ui-label ${className}`}>
      <Icon aria-hidden="true" />
      {STATUS_LABELS[status]}
    </span>
  );
}
