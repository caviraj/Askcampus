import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CategoryBarChart } from "./CategoryBarChart";

describe("CategoryBarChart", () => {
  it("writes every count as text, so the chart is its own table view", () => {
    render(
      <CategoryBarChart
        categories={[
          { category: "examinations", count: 12 },
          { category: "admissions", count: 4 },
        ]}
      />,
    );
    expect(screen.getByText("Examinations")).toBeInTheDocument();
    expect(screen.getByText("12")).toBeInTheDocument();
    expect(screen.getByText("Admissions")).toBeInTheDocument();
    expect(screen.getByText("4")).toBeInTheDocument();
  });

  it("gives every bar the same hue", () => {
    // One series, one colour. Colouring each category differently would spend
    // the only free channel on what the row's label already says, and shading
    // by size would double-encode the bar's length.
    const { container } = render(
      <CategoryBarChart
        categories={[
          { category: "examinations", count: 12 },
          { category: "admissions", count: 4 },
          { category: "events", count: 1 },
        ]}
      />,
    );
    const bars = container.querySelectorAll(".bg-marine");
    expect(bars).toHaveLength(3);
  });

  it("scales the longest bar to the full track", () => {
    const { container } = render(
      <CategoryBarChart
        categories={[
          { category: "examinations", count: 10 },
          { category: "admissions", count: 5 },
        ]}
      />,
    );
    const widths = Array.from(container.querySelectorAll<HTMLElement>(".bg-marine")).map(
      (bar) => bar.style.width,
    );
    expect(widths).toEqual(["100%", "50%"]);
  });

  it("names the uncategorised bucket rather than printing null", () => {
    render(<CategoryBarChart categories={[{ category: null, count: 2 }]} />);
    expect(screen.getByText("Uncategorised")).toBeInTheDocument();
  });

  it("shows the empty line when nothing has been asked", () => {
    render(<CategoryBarChart categories={[]} />);
    expect(screen.getByText("No questions yet.")).toBeInTheDocument();
  });

  it("marks the bars as decoration, since the count beside them says the same", () => {
    const { container } = render(
      <CategoryBarChart categories={[{ category: "events", count: 3 }]} />,
    );
    const track = container.querySelector("[aria-hidden='true']");
    expect(track).not.toBeNull();
  });
});
