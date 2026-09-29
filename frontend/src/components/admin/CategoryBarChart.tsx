/**
 * DESIGN_SYSTEM.md section 8: "Below: a category bar chart and the unanswered
 * queue preview."
 *
 * One series -- how many questions fell in each category -- so every bar takes
 * the same hue. Colouring each category differently would spend the only free
 * channel on information the row's own label already carries, and shading them
 * by size would double-encode the length as hue. A single series also needs no
 * legend: the heading names what the bars measure.
 *
 * Drawn in HTML rather than SVG. Each row is a term and a value, so the chart
 * *is* its own table view -- the numbers are text a screen reader reads in
 * order, not a graphic that needs a separate accessible rendering. The bar is
 * decorative and marked as such, because the count beside it says the same
 * thing.
 */
import { formatCategory, formatCount } from "../../lib/format";
import type { CategoryCount } from "../../lib/types";

interface CategoryBarChartProps {
  categories: CategoryCount[];
}

export function CategoryBarChart({ categories }: CategoryBarChartProps) {
  if (categories.length === 0) {
    return (
      <p className="rounded-panel border border-rule bg-surface px-4 py-6 text-ui text-ink-soft">
        No questions yet.
      </p>
    );
  }

  // The longest bar fills the track, so the chart shows shares of the busiest
  // category rather than shares of the window's total. The counts are labelled,
  // so nothing here depends on reading the lengths precisely.
  const max = Math.max(...categories.map((entry) => entry.count), 1);

  return (
    <ul className="flex flex-col gap-3">
      {categories.map((entry) => (
        <li
          key={entry.category ?? "__uncategorised"}
          className="grid grid-cols-[minmax(0,7.5rem)_1fr_auto] items-center gap-3"
        >
          <span className="truncate font-sans text-ui-label text-ink">
            {formatCategory(entry.category)}
          </span>
          <span aria-hidden="true" className="h-2 w-full">
            <span
              className="block h-full rounded-r-control bg-marine"
              style={{ width: `${Math.max((entry.count / max) * 100, 2)}%` }}
            />
          </span>
          <span className="text-ui-label tabular-nums text-ink-soft">
            {formatCount(entry.count)}
          </span>
        </li>
      ))}
    </ul>
  );
}
