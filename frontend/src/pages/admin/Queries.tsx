/**
 * Query history: every question asked, with what it was answered from.
 *
 * The question is the row; the answer sits under it, truncated. An admin
 * scanning this list is looking for a pattern -- the same topic asked badly, a
 * category that never answers -- so the questions need to line up vertically,
 * and a full answer in every cell would push the next question off the screen.
 *
 * "Feedback" is deliberately three-valued. `null` renders as "Not rated", not
 * as "Not helpful": nobody having rated a question is not the same as somebody
 * finding it useless, and collapsing the two would make every new question look
 * like a complaint.
 */
import { useState } from "react";

import { DataTable, type Column } from "../../components/admin/DataTable";
import { Pagination } from "../../components/admin/Pagination";
import { ADMIN_COPY, DOCUMENT_CATEGORIES } from "../../lib/constants";
import { fetchQueries } from "../../lib/api";
import {
  formatCategory,
  formatDateTime,
  formatHistorySource,
  formatScore,
} from "../../lib/format";
import { AlertIcon, CheckIcon } from "../../components/Icons";
import { PageState } from "./PageState";
import { useAsync } from "../../hooks/useAsync";
import type { AdminQuery } from "../../lib/types";

interface QueriesProps {
  token: string;
}

const PAGE_SIZE = 20;

export function Queries({ token }: QueriesProps) {
  const [answered, setAnswered] = useState<"all" | "answered" | "unanswered">("all");
  const [category, setCategory] = useState("all");
  const [offset, setOffset] = useState(0);

  const { data, error, loading, reload } = useAsync(
    () =>
      fetchQueries(token, {
        // The API takes a tri-state as an optional boolean: absent means both.
        ...(answered === "all" ? {} : { answered: answered === "answered" }),
        category,
        limit: PAGE_SIZE,
        offset,
      }),
    `${token}|${answered}|${category}|${offset}`,
  );

  const columns: Column<AdminQuery>[] = [
    {
      key: "question",
      header: "Question",
      render: (row) => (
        <div className="flex flex-col gap-0.5">
          <span className="text-ink">{row.question}</span>
          {row.answer && (
            <span className="line-clamp-2 text-meta text-ink-soft">{row.answer}</span>
          )}
        </div>
      ),
    },
    {
      key: "category",
      header: "Category",
      render: (row) => formatCategory(row.category),
    },
    {
      key: "answered",
      header: "Answered",
      render: (row) => (
        // Text plus icon, never colour alone (section 3).
        <span
          className={`inline-flex items-center gap-1.5 text-ui-label ${
            row.answered ? "text-moss" : "text-ink-soft"
          }`}
        >
          {row.answered ? <CheckIcon aria-hidden="true" /> : <AlertIcon aria-hidden="true" />}
          {row.answered ? "Answered" : "Fallback"}
        </span>
      ),
    },
    {
      key: "sources",
      header: "Sources",
      render: (row) =>
        row.sources.length === 0 ? (
          <span className="text-ink-soft">—</span>
        ) : (
          <ul className="flex flex-col gap-0.5">
            {row.sources.map((source) => (
              <li key={source.rank} className="text-meta text-ink-soft">
                {formatHistorySource(source)}
              </li>
            ))}
          </ul>
        ),
    },
    {
      key: "top_score",
      header: "Best score",
      numeric: true,
      render: (row) => formatScore(row.top_score),
    },
    {
      key: "helpful",
      header: "Feedback",
      render: (row) =>
        row.helpful === null ? "Not rated" : row.helpful ? "Helpful" : "Not helpful",
    },
    {
      key: "created_at",
      header: "Asked",
      render: (row) => formatDateTime(row.created_at),
    },
  ];

  if (loading || error || !data) {
    return <PageState loading={loading} error={error} onRetry={reload} title="Query history" />;
  }

  return (
    <section className="flex flex-col gap-5">
      <h1 className="font-serif text-page-title text-ink">Query history</h1>

      <div className="flex flex-wrap gap-3">
        <Select
          id="filter-answered"
          label="Show"
          value={answered}
          onChange={(value) => {
            setAnswered(value as "all" | "answered" | "unanswered");
            setOffset(0);
          }}
          options={[
            { value: "all", label: "All" },
            { value: "answered", label: "Answered" },
            { value: "unanswered", label: "Unanswered" },
          ]}
        />
        <Select
          id="filter-query-category"
          label="Category"
          value={category}
          onChange={(value) => {
            setCategory(value);
            setOffset(0);
          }}
          options={[
            { value: "all", label: "All" },
            ...DOCUMENT_CATEGORIES.map((value) => ({
              value,
              label: formatCategory(value),
            })),
          ]}
        />
      </div>

      <DataTable
        caption="Query history"
        columns={columns}
        rows={data.items}
        rowKey={(row) => row.id}
        empty={ADMIN_COPY.emptyQueries}
      />

      <Pagination
        total={data.total}
        limit={data.limit}
        offset={data.offset}
        onChange={setOffset}
      />
    </section>
  );
}

function Select({
  id,
  label,
  value,
  options,
  onChange,
}: {
  id: string;
  label: string;
  value: string;
  options: { value: string; label: string }[];
  onChange: (value: string) => void;
}) {
  return (
    <div className="flex items-center gap-2">
      <label htmlFor={id} className="font-sans text-ui-label text-ink-soft">
        {label}
      </label>
      <select
        id={id}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="h-11 rounded-control border border-rule bg-surface px-3 font-sans text-ui text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-marine"
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </div>
  );
}
