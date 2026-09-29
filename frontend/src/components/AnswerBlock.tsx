/**
 * An answer and its evidence, joined by DESIGN_SYSTEM.md section 7's 3 px
 * `--marine` rail down the left edge of the whole block.
 *
 * This is where section 10's one orchestrated moment lives: the rail draws top
 * to bottom over 250 ms and then the slips fade in. That is the single piece of
 * motion in the app, and it is a response to the student sending a question --
 * not an entrance animation on load or on scroll, which section 10 forbids.
 *
 * Both animations are declared only in `tailwind.config.ts`'s keyframes, so
 * `prefers-reduced-motion` can switch them off without leaving anything hidden.
 */
import type { ReactNode } from "react";

interface AnswerBlockProps {
  children: ReactNode;
}

export function AnswerBlock({ children }: AnswerBlockProps) {
  return (
    <div className="relative">
      <span
        aria-hidden="true"
        className="absolute inset-y-0 left-0 w-[3px] origin-top rounded-full bg-marine animate-rail-draw"
      />
      {/*
        The gutter that keeps the rail clear of the bubble's border. It lives
        here rather than on `MessageBubble` so the slips share it -- the bar is
        meant to run down the edge of the answer *and* its evidence, which only
        lines up if both start at the same x.
      */}
      <div className="pl-5">{children}</div>
    </div>
  );
}
