import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MessageBubble } from "./MessageBubble";

/** The class string is the only place a token can be wrong: Tailwind never runs
 *  in tests, and `npm run build` is what rejects a token that does not exist. */
function shellOf(variant: Parameters<typeof MessageBubble>[0]["variant"]): string {
  render(<MessageBubble variant={variant}>text</MessageBubble>);
  return screen.getByText("text").className;
}

describe("MessageBubble", () => {
  it("sets the student's question on the wash, right aligned", () => {
    const shell = shellOf("student");
    expect(shell).toContain("bg-marine-wash");
    expect(shell).toContain("rounded-panel");
    expect(shell).toContain("ml-auto");
  });

  it("gives the fallback its own brick rail", () => {
    // Section 8: the fallback is white with a --brick left rail. It has no
    // slips to span, so unlike the answer the rail belongs on the bubble.
    const shell = shellOf("fallback");
    expect(shell).toContain("var(--brick)");
    expect(shell).not.toContain("var(--marine)");
  });

  it("leaves the marine rail to the block that joins the answer to its slips", () => {
    const shell = shellOf("answer");
    expect(shell).toContain("bg-surface");
    expect(shell).not.toContain("var(--brick)");
    // No left padding either: the rail's gutter comes from `AnswerBlock`, so
    // the bar lines up with the slips as well as the text.
    expect(shell).not.toContain("pl-5");
  });
});
