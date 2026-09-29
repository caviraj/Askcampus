import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { DataTable, type Column } from "./DataTable";
import { mockMatchMedia } from "../../test/matchMedia";

interface Row {
  id: string;
  title: string;
  count: number;
}

const ROWS: Row[] = [
  { id: "a", title: "Exam Schedule", count: 12 },
  { id: "b", title: "Hostel Rules", count: 3 },
];

function columns(): Column<Row>[] {
  return [
    { key: "title", header: "Title", sortable: true, render: (row) => row.title },
    {
      key: "count",
      header: "Sections",
      numeric: true,
      render: (row) => String(row.count),
    },
  ];
}

function table(props: Partial<Parameters<typeof DataTable<Row>>[0]> = {}) {
  return (
    <DataTable
      caption="Documents"
      columns={columns()}
      rows={ROWS}
      rowKey={(row) => row.id}
      empty="Nothing here."
      {...props}
    />
  );
}

describe("DataTable", () => {
  it("renders a real table at the wide breakpoint", () => {
    mockMatchMedia(1280);
    render(table());
    expect(screen.getByRole("table", { name: "Documents" })).toBeInTheDocument();
    expect(screen.getAllByRole("row")).toHaveLength(3);
  });

  it("keeps the table's structure on mobile rather than restyling the rows", () => {
    // The usual mobile trick -- `display: block` on a `tr` -- takes the row out
    // of the accessibility tree, so the two layouts are two elements. This
    // asserts the narrow one is a list, not a table whose rows were restyled.
    mockMatchMedia(360);
    render(table());
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
    // The values are still there, each under the header it belongs to.
    expect(screen.getByText("Exam Schedule")).toBeInTheDocument();
    // One header label per card, so each value sits under the header it belongs
    // to without a column position to say so.
    expect(screen.getAllByText("Sections")).toHaveLength(2);
  });

  it("omits a column's label in the stacked card when the cell carries its own", () => {
    mockMatchMedia(360);
    render(
      <DataTable
        caption="Documents"
        columns={[
          { key: "title", header: "Title", render: (row) => row.title },
          { key: "actions", header: "Actions", label: null, render: () => <button>Delete</button> },
        ]}
        rows={ROWS}
        rowKey={(row) => row.id}
        empty="Nothing here."
      />,
    );
    expect(screen.queryByText("Actions")).not.toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Delete" })).toHaveLength(2);
  });

  it("reports which column is sorted, and in which direction", () => {
    mockMatchMedia(1280);
    render(table({ sortKey: "title", sortDirection: "desc" }));
    const headers = screen.getAllByRole("columnheader");
    expect(headers[0]).toHaveAttribute("aria-sort", "descending");
    // `none` on the columns that could be sorted but are not; a column that
    // cannot be sorted gets no attribute at all, rather than claiming one.
    expect(headers[1]).not.toHaveAttribute("aria-sort");
  });

  it("asks the caller to sort rather than reordering what it was given", async () => {
    mockMatchMedia(1280);
    const onSort = vi.fn();
    render(table({ onSort }));
    await userEvent.click(screen.getByRole("button", { name: /Title/ }));
    expect(onSort).toHaveBeenCalledWith("title");
  });

  it("shows the empty message in place of the table", () => {
    mockMatchMedia(1280);
    render(table({ rows: [] }));
    expect(screen.getByText("Nothing here.")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("puts the caption on the table, not above it", () => {
    mockMatchMedia(1280);
    render(table());
    const table_ = screen.getByRole("table");
    expect(within(table_).getByText("Documents")).toBeInTheDocument();
  });
});
