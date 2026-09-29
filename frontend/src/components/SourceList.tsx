/**
 * One slip per cited chunk, with DESIGN_SYSTEM.md section 7's "maximum 3
 * visible, 'Show 2 more sources' for the rest".
 *
 * The rule is an inline-space affordance: below 1024 px the slips sit under the
 * answer and three is as many as fit before the answer is pushed off screen. In
 * the side column there is room for all of them, so the chat window renders
 * this list with everything revealed.
 */
import { VISIBLE_SOURCES } from "../lib/constants";
import { SourcePassage } from "./SourcePassage";
import { SourceSlip } from "./SourceSlip";
import type { Citation } from "../lib/types";

interface SourceListProps {
  citations: Citation[];
  answer: string;
  /** Index of the open slip within `citations`, or null. */
  openIndex: number | null;
  /** Whether this answer's "Show more" has been tapped. */
  revealed: boolean;
  /** False in the wide layout, where the side column holds the passage. */
  inlineExpand: boolean;
  onToggleSource: (index: number) => void;
  onReveal: () => void;
}

export function SourceList({
  citations,
  answer,
  openIndex,
  revealed,
  inlineExpand,
  onToggleSource,
  onReveal,
}: SourceListProps) {
  if (citations.length === 0) return null;

  const hidden = citations.length - VISIBLE_SOURCES;
  const visible = revealed ? citations : citations.slice(0, VISIBLE_SOURCES);

  return (
    <div className="mt-3">
      <ul className="flex flex-col gap-2">
        {visible.map((citation, index) => (
          <SourceSlip
            key={citation.label}
            citation={citation}
            expanded={openIndex === index}
            onToggle={() => onToggleSource(index)}
          >
            {inlineExpand ? <SourcePassage citation={citation} answer={answer} /> : null}
          </SourceSlip>
        ))}
      </ul>

      {!revealed && hidden > 0 && (
        <button
          type="button"
          onClick={onReveal}
          className="mt-2 min-h-[44px] rounded-control px-1 font-sans text-ui-label text-marine underline"
        >
          {`Show ${hidden} more source${hidden === 1 ? "" : "s"}`}
        </button>
      )}
    </div>
  );
}
