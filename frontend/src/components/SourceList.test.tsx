import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { SourceList } from "./SourceList";
import { citation } from "../test/fixtures";
import type { Citation } from "../lib/types";

const ANSWER = "Internal assessment marks are published within seven working days.";

function many(count: number): Citation[] {
  return Array.from({ length: count }, (_, index) =>
    citation({ label: `S${index + 1}`, document_title: `Document ${index + 1}` }),
  );
}

function renderList(overrides: Partial<Parameters<typeof SourceList>[0]> = {}) {
  const props = {
    citations: many(3),
    answer: ANSWER,
    openIndex: null,
    revealed: false,
    inlineExpand: true,
    onToggleSource: vi.fn(),
    onReveal: vi.fn(),
    ...overrides,
  };
  return { ...render(<SourceList {...props} />), props };
}

describe("SourceList", () => {
  it("shows three slips when there are three", () => {
    renderList({ citations: many(3) });
    expect(screen.getAllByRole("button")).toHaveLength(3);
    expect(screen.queryByText(/Show .* more source/)).not.toBeInTheDocument();
  });

  it("shows three and offers the rest", () => {
    renderList({ citations: many(5) });
    expect(screen.getAllByRole("button")).toHaveLength(4);
    expect(screen.getByText("Show 2 more sources")).toBeInTheDocument();
  });

  it("says source, not sources, for one", () => {
    renderList({ citations: many(4) });
    expect(screen.getByText("Show 1 more source")).toBeInTheDocument();
  });

  it("shows every slip once the rest are revealed", () => {
    renderList({ citations: many(5), revealed: true });
    expect(screen.getAllByRole("button")).toHaveLength(5);
    expect(screen.queryByText(/Show .* more source/)).not.toBeInTheDocument();
  });

  it("asks to reveal rather than revealing on its own", async () => {
    const { props } = renderList({ citations: many(5) });
    await userEvent.click(screen.getByText("Show 2 more sources"));
    expect(props.onReveal).toHaveBeenCalledTimes(1);
    // Still three: the state lives in the thread, not here.
    expect(screen.getAllByRole("button")).toHaveLength(4);
  });

  it("renders nothing when nothing was cited", () => {
    const { container } = renderList({ citations: [] });
    expect(container).toBeEmptyDOMElement();
  });

  it("passes the open index to the slip it belongs to", () => {
    renderList({ citations: many(3), openIndex: 1 });
    const buttons = screen.getAllByRole("button");
    expect(buttons[0]).toHaveAttribute("aria-expanded", "false");
    expect(buttons[1]).toHaveAttribute("aria-expanded", "true");
  });

  it("renders the passage under the slip inline", () => {
    renderList({ citations: many(3), openIndex: 0, inlineExpand: true });
    // The paragraph is the passage. Compared as text, because a chunk keeps its
    // own line breaks and no text query normalises the same way twice.
    expect(document.querySelector("p")?.textContent).toBe(citation().snippet);
  });

  it("renders no passage inline in the wide layout, where the side column holds it", () => {
    renderList({ citations: many(3), openIndex: 0, inlineExpand: false });
    expect(document.querySelector("p")).toBeNull();
  });

  it("reports which slip was toggled", async () => {
    const { props } = renderList({ citations: many(3) });
    await userEvent.click(screen.getAllByRole("button")[2] as HTMLElement);
    expect(props.onToggleSource).toHaveBeenCalledWith(2);
  });
});
