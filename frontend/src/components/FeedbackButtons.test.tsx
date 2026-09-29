import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { FeedbackButtons } from "./FeedbackButtons";
import { COPY } from "../lib/constants";

describe("FeedbackButtons", () => {
  it("offers both ratings under an idle answer", () => {
    render(<FeedbackButtons state="idle" onRate={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Helpful" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Not helpful" })).toBeInTheDocument();
  });

  it("reports a helpful rating once", async () => {
    const onRate = vi.fn();
    render(<FeedbackButtons state="idle" onRate={onRate} />);
    await userEvent.click(screen.getByRole("button", { name: "Helpful" }));
    expect(onRate).toHaveBeenCalledTimes(1);
    expect(onRate).toHaveBeenCalledWith(true);
  });

  it("reports a not-helpful rating", async () => {
    const onRate = vi.fn();
    render(<FeedbackButtons state="idle" onRate={onRate} />);
    await userEvent.click(screen.getByRole("button", { name: "Not helpful" }));
    expect(onRate).toHaveBeenCalledWith(false);
  });

  it("confirms and takes both buttons away once rated", () => {
    render(<FeedbackButtons state="helpful" onRate={vi.fn()} />);
    expect(screen.getByRole("status")).toHaveTextContent(COPY.feedbackThanks);
    // Disabled buttons that still accept a second tap would invite a rating
    // over something that already happened, so they are gone entirely.
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("confirms after a not-helpful rating too", () => {
    render(<FeedbackButtons state="not_helpful" onRate={vi.fn()} />);
    expect(screen.getByRole("status")).toHaveTextContent(COPY.feedbackThanks);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("cannot be rated twice from the keyboard", async () => {
    const onRate = vi.fn();
    const { rerender } = render(<FeedbackButtons state="idle" onRate={onRate} />);
    await userEvent.tab();
    await userEvent.keyboard("{Enter}");
    expect(onRate).toHaveBeenCalledTimes(1);

    rerender(<FeedbackButtons state="helpful" onRate={onRate} />);
    await userEvent.tab();
    await userEvent.keyboard("{Enter}");
    expect(onRate).toHaveBeenCalledTimes(1);
  });
});
