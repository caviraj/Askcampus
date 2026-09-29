import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SourcePassage } from "./SourcePassage";
import { citation } from "../test/fixtures";
import { selectSupportingSentence } from "../lib/highlight";

const ANSWER = "Internal assessment marks are published within seven working days.";

describe("SourcePassage", () => {
  it("names the document, page, section and last update", () => {
    render(<SourcePassage citation={citation()} answer={ANSWER} />);
    expect(screen.getByText("Exam Schedule Nov–Dec 2026")).toBeInTheDocument();
    expect(screen.getByText("Page")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
    expect(screen.getByText("Section")).toBeInTheDocument();
    expect(screen.getByText("Internal assessments")).toBeInTheDocument();
    expect(screen.getByText("Last updated")).toBeInTheDocument();
    expect(screen.getByText("14 August 2026")).toBeInTheDocument();
  });

  it("omits page and section rather than printing a null", () => {
    render(
      <SourcePassage citation={citation({ page: null, section: null })} answer={ANSWER} />,
    );
    expect(screen.queryByText("Page")).not.toBeInTheDocument();
    expect(screen.queryByText("Section")).not.toBeInTheDocument();
  });

  it("says so when the row records no update date", () => {
    render(<SourcePassage citation={citation({ last_updated: null })} answer={ANSWER} />);
    expect(screen.getByText("Not recorded")).toBeInTheDocument();
  });

  it("marks exactly the sentence highlight.ts chose", () => {
    const snippet = citation().snippet;
    const expected = selectSupportingSentence(snippet, ANSWER);
    render(<SourcePassage citation={citation()} answer={ANSWER} />);

    const mark = document.querySelector("mark");
    expect(mark).not.toBeNull();
    expect(mark?.textContent).toBe(expected?.match);
    // The whole passage is still on screen, mark and all. Asserted on the text
    // rather than through `getByText`, whose whitespace normalising cannot
    // express a chunk's line breaks.
    expect(document.querySelector("p")?.textContent).toBe(snippet);
  });

  it("renders the passage unmarked when no sentence can be chosen honestly", () => {
    render(<SourcePassage citation={citation()} answer="hostel mess timings" />);
    expect(document.querySelector("mark")).toBeNull();
    expect(document.querySelector("p")?.textContent).toBe(citation().snippet);
  });

  it("treats document text as text", () => {
    // A chunk containing markup must appear as those characters. There is no
    // `dangerouslySetInnerHTML` anywhere in the app, and this is the assertion
    // that would fail if one were added.
    const snippet = "<script>alert(1)</script> Hostel rules apply.";
    render(<SourcePassage citation={citation({ snippet })} answer="hostel rules" />);
    expect(document.querySelector("script")).toBeNull();
    // Read as characters, not parsed: the paragraph's text is the snippet.
    expect(document.querySelector("p")?.textContent).toBe(snippet);
  });
});
