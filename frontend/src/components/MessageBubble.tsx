/**
 * The shell for one message, in the three shapes DESIGN_SYSTEM.md section 8
 * describes: student, answer, fallback.
 *
 * The rail is not here. It belongs to `AnswerBlock`, which spans the answer and
 * its slips together -- "a 3 px `--marine` bar runs down the left edge of the
 * *whole answer block*, joining the answer to its slips" (section 7). A rail on
 * the bubble alone would stop above the evidence it is meant to link.
 */
import type { ReactNode } from "react";

interface MessageBubbleProps {
  variant: "student" | "answer" | "fallback";
  children: ReactNode;
}

const SHELL: Record<MessageBubbleProps["variant"], string> = {
  // Section 8: --marine-wash background, 10 px radius, right aligned, max 80%.
  student:
    "ml-auto max-w-[80%] rounded-panel bg-marine-wash px-4 py-3 font-sans text-ui text-ink",
  // No rail here: section 7 puts the marine bar on the whole answer block, so
  // that it spans the slips too. It is drawn by `AnswerBlock`.
  answer: "rounded-panel border border-rule bg-surface py-4 pr-4",
  // Section 8's fallback row: white, --brick left rail, sans text. This one has
  // no slips to span, so the rail belongs on the bubble itself.
  fallback:
    "rounded-panel border border-rule bg-surface py-4 pl-5 pr-4 font-sans text-ui text-ink [border-left:3px_solid_var(--brick)]",
};

export function MessageBubble({ variant, children }: MessageBubbleProps) {
  return <div className={SHELL[variant]}>{children}</div>;
}
