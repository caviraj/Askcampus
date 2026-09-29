/**
 * DESIGN_SYSTEM.md section 8: "Two text buttons under each answer: 'Helpful'
 * and 'Not helpful'. After a tap, show 'Thanks for the feedback' and disable
 * both."
 *
 * Shown under fallbacks as well as answers. The spec says "under each answer"
 * without excluding the fallback, and the backend already accepts a fallback's
 * `query_id` -- a fallback rated "not helpful" is the strongest signal there is
 * that the corpus or the threshold needs work.
 */
import { COPY } from "../lib/constants";
import type { FeedbackState } from "../lib/types";

interface FeedbackButtonsProps {
  state: FeedbackState;
  onRate: (helpful: boolean) => void;
}

export function FeedbackButtons({ state, onRate }: FeedbackButtonsProps) {
  if (state !== "idle") {
    return (
      <p className="mt-3 font-sans text-meta text-ink-soft" role="status">
        {COPY.feedbackThanks}
      </p>
    );
  }

  return (
    <div className="mt-3 flex gap-2">
      {[true, false].map((helpful) => (
        <button
          key={String(helpful)}
          type="button"
          onClick={() => onRate(helpful)}
          className="min-h-[44px] rounded-control border border-rule px-3 font-sans text-ui-label text-ink hover:border-marine hover:text-marine"
        >
          {helpful ? "Helpful" : "Not helpful"}
        </button>
      ))}
    </div>
  );
}
