/**
 * DESIGN_SYSTEM.md section 8's admin table, including its two structural rules:
 * "sticky header, 48 px rows, zebra off, 1 px row dividers" and "sortable
 * columns show a direction arrow and `aria-sort`".
 *
 * On mobile the spec says "each row becomes a stacked card". That is a change
 * of *structure*, not of styling: setting `display: block` on a `tr` (or
 * `flex`, which is the usual trick) takes the row out of the table's layout and,
 * with it, out of the accessibility tree -- assistive technology stops
 * announcing "row 3 of 12, column 2 of 5". So the two layouts are two elements:
 * a real `<table>` at `md` and up, and a `<dl>` per row below it. The cells'
 * *content* comes from one `render` function either way, so only the layout is
 * written twice.
 */
import type { ReactNode } from "react";

import { useMediaQuery } from "../../hooks/useMediaQuery";
import { SortIcon } from "../Icons";

export interface Column<T> {
  key: string;
  header: string;
  /** The label above the value in the stacked card. Defaults to `header`;
   *  pass `null` for a cell that carries its own text, such as a row's actions,
   *  so the card does not print a heading the buttons already say. */
  label?: string | null;
  sortable?: boolean;
  /** Right-aligned in the table, which is where numbers read. */
  numeric?: boolean;
  render: (row: T) => ReactNode;
}

export type SortDirection = "asc" | "desc";

interface DataTableProps<T> {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  /** Names the table for a screen reader. Visually hidden -- the page's own
   *  heading is the visible one, and repeating it would read as two headings. */
  caption: string;
  empty: ReactNode;
  sortKey?: string | null;
  sortDirection?: SortDirection;
  onSort?: (key: string) => void;
}

export function DataTable<T>({
  columns,
  rows,
  rowKey,
  caption,
  empty,
  sortKey = null,
  sortDirection = "asc",
  onSort,
}: DataTableProps<T>) {
  const stacked = useMediaQuery(STACKED_QUERY);

  if (rows.length === 0) {
    return (
      <p className="rounded-panel border border-rule bg-surface px-4 py-6 text-ui text-ink-soft">
        {empty}
      </p>
    );
  }

  if (stacked) {
    return (
      <ul className="flex flex-col gap-3">
        {rows.map((row) => (
          <li
            key={rowKey(row)}
            className="rounded-panel border border-rule bg-surface px-4 py-3"
          >
            <dl className="flex flex-col gap-2">
              {columns.map((column) => {
                const label = column.label === undefined ? column.header : column.label;
                return (
                  <div key={column.key} className="flex flex-col gap-0.5">
                    {label !== null && (
                      <dt className="font-sans text-meta text-ink-soft">{label}</dt>
                    )}
                    <dd className={column.numeric ? "text-table-cell tabular-nums" : "text-table-cell"}>
                      {column.render(row)}
                    </dd>
                  </div>
                );
              })}
            </dl>
          </li>
        ))}
      </ul>
    );
  }

  return (
    <div className="overflow-hidden rounded-panel border border-rule bg-surface">
      <table className="w-full border-collapse">
        <caption className="sr-only">{caption}</caption>
        <thead className="sticky top-0 z-10 bg-surface">
          <tr className="border-b border-rule">
            {columns.map((column) => (
              <th
                key={column.key}
                scope="col"
                aria-sort={ariaSort(column, sortKey, sortDirection)}
                className={`px-4 py-3 text-left font-sans text-ui-label font-semibold text-ink-soft ${
                  column.numeric ? "text-right" : ""
                }`}
              >
                {column.sortable && onSort ? (
                  <button
                    type="button"
                    onClick={() => onSort(column.key)}
                    className={`inline-flex items-center gap-1.5 rounded-control hover:text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-marine ${
                      column.numeric ? "flex-row-reverse" : ""
                    }`}
                  >
                    {column.header}
                    <SortIcon
                      aria-hidden="true"
                      className={
                        sortKey === column.key && sortDirection === "asc" ? "rotate-180" : ""
                      }
                    />
                  </button>
                ) : (
                  column.header
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={rowKey(row)} className="h-12 border-b border-rule last:border-b-0">
              {columns.map((column) => (
                <td
                  key={column.key}
                  className={`px-4 py-2 align-middle text-table-cell ${
                    column.numeric ? "text-right tabular-nums" : ""
                  }`}
                >
                  {column.render(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** `md`, matching the `md:` breakpoint Tailwind uses elsewhere in the app. */
const STACKED_QUERY = "(max-width: 767px)";

/**
 * `aria-sort` belongs on the header of the column that *is* sorted, and only
 * that one; every other header takes `none`. A column that is not sortable gets
 * no attribute at all, because `none` on it would claim it could be.
 */
function ariaSort<T>(
  column: Column<T>,
  sortKey: string | null,
  direction: SortDirection,
): "ascending" | "descending" | "none" | undefined {
  if (!column.sortable) return undefined;
  if (column.key !== sortKey) return "none";
  return direction === "asc" ? "ascending" : "descending";
}
