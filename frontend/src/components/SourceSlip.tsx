/**
 * DESIGN_SYSTEM.md section 7's collapsed slip: a 40 px catalogue card.
 *
 * Presentation only. It does not own its expansion state: above 1024 px the
 * expanded passage renders in a side column owned by the chat window, and if
 * the slip held the state too, the two copies would disagree the moment the
 * viewport crossed the breakpoint -- a slip open in one layout and closed in
 * the other.
 */
import { ChevronIcon, DocumentIcon } from "./Icons";
import { formatSlipLabel, formatSlipLocation } from "../lib/format";
import type { Citation } from "../lib/types";
import type { ReactNode } from "react";

interface SourceSlipProps {
  citation: Citation;
  expanded: boolean;
  onToggle: () => void;
  /** The expanded body, when it belongs inline. Omitted in the wide layout,
   *  where the side column renders it instead. */
  children?: ReactNode;
}

export function SourceSlip({ citation, expanded, onToggle, children }: SourceSlipProps) {
  const label = formatSlipLabel(citation);

  return (
    <li className="animate-slip-in">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={expanded}
        // Section 7 fixes the visible box at 40 px; section 5 and AGENTS.md
        // section 8 require a 44 px touch target. The pseudo-element extends the
        // hit area by 2 px top and bottom without changing what is drawn, so
        // both hold -- rather than one silently overruling the other.
        className="relative flex h-10 w-full items-center gap-2 rounded-control border border-rule bg-surface px-3 text-left after:absolute after:-inset-y-0.5 after:left-0 after:right-0 after:content-[''] hover:border-marine"
      >
        <DocumentIcon className="shrink-0 text-ink-soft" />
        <span className="min-w-0 flex-1 truncate font-sans text-ui-label text-ink">{label}</span>
        <span className="shrink-0 font-sans text-meta text-ink-soft">
          {formatSlipLocation(citation)}
        </span>
        <ChevronIcon
          className={`shrink-0 text-ink-soft transition-transform ${expanded ? "rotate-180" : ""}`}
        />
      </button>
      {expanded && children}
    </li>
  );
}
