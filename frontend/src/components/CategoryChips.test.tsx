import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { CategoryChips } from "./CategoryChips";
import { CATEGORIES } from "../test/fixtures";

function setup(selected: Parameters<typeof CategoryChips>[0]["selected"] = null) {
  const onSelect = vi.fn();
  const onAsk = vi.fn();
  render(
    <CategoryChips
      categories={CATEGORIES.categories}
      selected={selected}
      onSelect={onSelect}
      onAsk={onAsk}
    />,
  );
  return { onSelect, onAsk };
}

describe("CategoryChips", () => {
  it("is a radiogroup, so the arrow keys come with the role", () => {
    setup();
    expect(screen.getByRole("radiogroup", { name: "Filter by category" })).toBeInTheDocument();
    expect(screen.getAllByRole("radio")).toHaveLength(7);
  });

  it("serves whatever the API returns, including the chip the spec omits", () => {
    setup();
    expect(screen.getByRole("radio", { name: /general/i })).toBeInTheDocument();
  });

  it("checks nothing at first, so the backend classifies the question", () => {
    // The subtlety: no chip selected means `category` is omitted from the
    // request and the classifier runs. Tapping "All" sends "all", which means
    // "filter nothing" and skips the classifier -- so "All" must not be the
    // default.
    setup();
    for (const chip of screen.getAllByRole("radio")) {
      expect(chip).toHaveAttribute("aria-checked", "false");
    }
  });

  it("marks the selected chip with more than colour", () => {
    setup("examinations");
    const selected = screen.getByRole("radio", { name: /examinations/i });
    expect(selected).toHaveAttribute("aria-checked", "true");
    // Section 8: a check icon, not colour alone.
    expect(selected.querySelector("svg")).not.toBeNull();
    expect(screen.getByRole("radio", { name: /admissions/i }).querySelector("svg")).toBeNull();
  });

  it("reports the value, not the label", async () => {
    const { onSelect } = setup();
    await userEvent.click(screen.getByRole("radio", { name: /academic processes/i }));
    expect(onSelect).toHaveBeenCalledWith("academic_processes");
  });

  it("keeps one tab stop for the whole group and moves with the arrows", async () => {
    setup("examinations");
    const chips = screen.getAllByRole("radio");
    expect(chips.filter((chip) => chip.getAttribute("tabindex") === "0")).toHaveLength(1);

    await userEvent.tab();
    expect(screen.getByRole("radio", { name: /examinations/i })).toHaveFocus();

    await userEvent.keyboard("{ArrowRight}");
    expect(screen.getByRole("radio", { name: /admissions/i })).toHaveFocus();

    await userEvent.keyboard("{ArrowLeft}");
    expect(screen.getByRole("radio", { name: /examinations/i })).toHaveFocus();
  });

  it("finds the group from the keyboard when nothing is selected yet", async () => {
    setup();
    await userEvent.tab();
    expect(screen.getAllByRole("radio")[0]).toHaveFocus();
  });

  it("offers the selected chip's starter questions", async () => {
    const { onAsk } = setup("examinations");
    const starter = screen.getByRole("button", {
      name: "When are the internal assessment marks published?",
    });
    await userEvent.click(starter);
    expect(onAsk).toHaveBeenCalledWith("When are the internal assessment marks published?");
  });

  it("offers none for a chip that has none", () => {
    setup("departments");
    expect(screen.queryByRole("list")).not.toBeInTheDocument();
  });
});
