import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { SourceSlip } from "./SourceSlip";
import { citation } from "../test/fixtures";

describe("SourceSlip", () => {
  it("carries section 7's label format", () => {
    render(<SourceSlip citation={citation()} expanded={false} onToggle={() => undefined} />);
    expect(screen.getByText("Exam Schedule Nov–Dec 2026, page 2")).toBeInTheDocument();
  });

  it("shows the page beside the label", () => {
    render(<SourceSlip citation={citation()} expanded={false} onToggle={() => undefined} />);
    expect(screen.getByText("Page 2")).toBeInTheDocument();
  });

  it("falls back to the section name where a document has no pages", () => {
    // DOCX and TXT carry no page number, so "Title, page null" would be worse
    // than naming the part of the document the passage came from.
    render(
      <SourceSlip
        citation={citation({ page: null, section: "Hostel rules" })}
        expanded={false}
        onToggle={() => undefined}
      />,
    );
    expect(screen.getByText("Exam Schedule Nov–Dec 2026, Hostel rules")).toBeInTheDocument();
    expect(screen.getByText("Hostel rules")).toBeInTheDocument();
  });

  it("reports its expanded state rather than owning it", async () => {
    const onToggle = vi.fn();
    const { rerender } = render(
      <SourceSlip citation={citation()} expanded={false} onToggle={onToggle} />,
    );
    const button = screen.getByRole("button");
    expect(button).toHaveAttribute("aria-expanded", "false");

    await userEvent.click(button);
    expect(onToggle).toHaveBeenCalledTimes(1);

    rerender(
      <SourceSlip citation={citation()} expanded onToggle={onToggle}>
        <p>The passage.</p>
      </SourceSlip>,
    );
    expect(screen.getByRole("button")).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("The passage.")).toBeInTheDocument();
  });

  it("renders nothing inside until it is expanded", () => {
    render(
      <SourceSlip citation={citation()} expanded={false} onToggle={() => undefined}>
        <p>The passage.</p>
      </SourceSlip>,
    );
    expect(screen.queryByText("The passage.")).not.toBeInTheDocument();
  });

  it("opens from the keyboard", async () => {
    const onToggle = vi.fn();
    render(<SourceSlip citation={citation()} expanded={false} onToggle={onToggle} />);

    await userEvent.tab();
    expect(screen.getByRole("button")).toHaveFocus();
    await userEvent.keyboard("{Enter}");
    expect(onToggle).toHaveBeenCalledTimes(1);
  });
});
