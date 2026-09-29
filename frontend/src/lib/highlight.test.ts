import { describe, expect, it } from "vitest";

import { selectSupportingSentence } from "./highlight";

const SNIPPET =
  "Internal assessment marks are published within seven working days.\n" +
  "Students may appeal to the Examinations office after that.";

describe("selectSupportingSentence", () => {
  it("marks the sentence the answer's words come from", () => {
    const span = selectSupportingSentence(
      SNIPPET,
      "Internal assessment marks are published within seven working days.",
    );
    expect(span?.match).toBe(
      "Internal assessment marks are published within seven working days.",
    );
  });

  it("returns three slices that rebuild the snippet exactly", () => {
    // The component renders these as three text nodes. A dropped character
    // would silently change the passage rather than throw, so the invariant is
    // asserted rather than assumed.
    for (const answer of ["seven working days", "appeal to the Examinations office", "marks"]) {
      const span = selectSupportingSentence(SNIPPET, answer);
      expect(span).not.toBeNull();
      expect(`${span?.before}${span?.match}${span?.after}`).toBe(SNIPPET);
    }
  });

  it("keeps a heading off the sentence that follows it", () => {
    const snippet = "Examination Cell\nMarks are published in seven days.";
    const span = selectSupportingSentence(snippet, "Marks are published in seven days.");
    expect(span?.match).toBe("Marks are published in seven days.");
    expect(span?.match).not.toContain("Examination Cell");
  });

  it("takes the earliest sentence when two score the same", () => {
    const snippet = "The library closes at six. The library opens at nine.";
    expect(selectSupportingSentence(snippet, "library")?.match).toBe(
      "The library closes at six.",
    );
  });

  it("weights a shared number above a shared word", () => {
    // Without the double weight this is 2 against 3 and the wrong sentence wins.
    const snippet = "The late fee is 500. The late fee applies after the due date.";
    const span = selectSupportingSentence(snippet, "500 late fee applies");
    expect(span?.match).toBe("The late fee is 500.");
  });

  it.each([
    ["Rs. 500", "The fine is Rs. 500 for late submission.", "fine 500 late submission"],
    ["Nov. 2026", "The form opens in Nov. 2026 and closes later.", "form opens Nov 2026"],
    ["Ph.D. 2019", "She joined in Ph.D. 2019 and left later.", "joined left"],
  ])("does not split after the abbreviation in %s", (_label, snippet, answer) => {
    const span = selectSupportingSentence(snippet, answer);
    expect(span?.match).toBe(snippet);
  });

  it("marks nothing when no sentence overlaps the answer", () => {
    expect(selectSupportingSentence(SNIPPET, "hostel mess timings")).toBeNull();
  });

  it("marks nothing when the answer has no content words", () => {
    expect(selectSupportingSentence(SNIPPET, "")).toBeNull();
    expect(selectSupportingSentence(SNIPPET, "the and of it")).toBeNull();
  });

  it("marks nothing when the snippet is a single unpunctuated fragment", () => {
    expect(selectSupportingSentence("Library timings", "examination results")).toBeNull();
  });

  it("is deterministic across calls", () => {
    const first = selectSupportingSentence(SNIPPET, "seven working days");
    const second = selectSupportingSentence(SNIPPET, "seven working days");
    expect(second).toEqual(first);
  });

  it("does not carry regex state between calls", () => {
    // `SENTENCE_BREAK` is global, so its `lastIndex` survives a call. If it were
    // not reset, the second call would start scanning mid-string and return a
    // different sentence.
    const snippet = "Alpha beta. Gamma delta. Epsilon zeta.";
    const first = selectSupportingSentence(snippet, "gamma delta");
    const second = selectSupportingSentence(snippet, "gamma delta");
    expect(first?.match).toBe("Gamma delta.");
    expect(second?.match).toBe("Gamma delta.");
  });
});
