/**
 * The unanswered queue: what students asked that the knowledge base could not
 * answer, grouped by a normalized hash so the same question asked forty times
 * is one row with a count of forty.
 *
 * The count is the point of the screen. A question asked once is an outlier; a
 * question asked forty times is a document that needs uploading, and that
 * distinction is invisible in a flat list.
 *
 * `truncated` is shown rather than hidden. The grouping runs over a bounded
 * window, so when it fills, the counts are floors -- and a queue that
 * under-reports how often something was asked is worse than one that admits it.
 */
import { useCallback, useState } from "react";

import { DataTable, type Column } from "../../components/admin/DataTable";
import { Pagination } from "../../components/admin/Pagination";
import { ADMIN_COPY } from "../../lib/constants";
import { fetchUnanswered, resolveUnanswered } from "../../lib/api";
import { formatCategory, formatCount, formatDateTime } from "../../lib/format";
import { toErrorView } from "../../lib/errors";
import { PageState } from "./PageState";
import { useAsync } from "../../hooks/useAsync";
import type { ErrorView, UnansweredGroup, UnansweredStatus } from "../../lib/types";

interface UnansweredProps {
  token: string;
}

const PAGE_SIZE = 20;

export function Unanswered({ token }: UnansweredProps) {
  const [status, setStatus] = useState<UnansweredStatus | "all">("open");
  const [offset, setOffset] = useState(0);
  const [pending, setPending] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [actionError, setActionError] = useState<ErrorView | null>(null);

  const { data, error, loading, reload } = useAsync(
    () => fetchUnanswered(token, { status, limit: PAGE_SIZE, offset }),
    `${token}|${status}|${offset}`,
  );

  const setGroupStatus = useCallback(
    async (group: UnansweredGroup, next: UnansweredStatus) => {
      setPending(group.normalized_hash);
      setActionError(null);
      try {
        await resolveUnanswered(token, group.normalized_hash, { status: next });
        setNotice(next === "resolved" ? ADMIN_COPY.resolvedNotice : ADMIN_COPY.reopenedNotice);
        reload();
      } catch (cause) {
        setActionError(toErrorView(cause));
      } finally {
        setPending(null);
      }
    },
    [token, reload],
  );

  const columns: Column<UnansweredGroup>[] = [
    {
      key: "question",
      header: "Question",
      render: (row) => <span className="text-ink">{row.question}</span>,
    },
    {
      key: "category",
      header: "Category",
      render: (row) => formatCategory(row.category),
    },
    {
      key: "count",
      header: "Asked",
      numeric: true,
      render: (row) => (
        <span className="text-ink">{`${formatCount(row.count)}×`}</span>
      ),
    },
    {
      key: "first_asked_at",
      header: "First asked",
      render: (row) => formatDateTime(row.first_asked_at),
    },
    {
      key: "last_asked_at",
      header: "Last asked",
      render: (row) => formatDateTime(row.last_asked_at),
    },
    {
      key: "status",
      header: "Status",
      render: (row) => (
        <div className="flex flex-col">
          <span className="text-ui-label text-ink">
            {row.status === "open" ? "Open" : "Resolved"}
          </span>
          {row.resolved_by_document_title && (
            <span className="text-meta text-ink-soft">{row.resolved_by_document_title}</span>
          )}
        </div>
      ),
    },
    {
      key: "actions",
      header: "Actions",
      label: null,
      render: (row) => {
        const resolving = row.status === "open";
        return (
          <button
            type="button"
            aria-disabled={pending === row.normalized_hash}
            onClick={() => void setGroupStatus(row, resolving ? "resolved" : "open")}
            className="inline-flex h-11 items-center rounded-control border border-marine px-3 font-sans text-ui-label text-marine hover:bg-marine-wash focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-marine"
          >
            {resolving ? "Mark resolved" : "Reopen"}
          </button>
        );
      },
    },
  ];

  if (loading || error || !data) {
    return <PageState loading={loading} error={error} onRetry={reload} title="Unanswered" />;
  }

  return (
    <section className="flex flex-col gap-5">
      <h1 className="font-serif text-page-title text-ink">Unanswered</h1>

      <div className="flex items-center gap-2">
        <label htmlFor="filter-unanswered" className="font-sans text-ui-label text-ink-soft">
          Show
        </label>
        <select
          id="filter-unanswered"
          value={status}
          onChange={(event) => {
            setStatus(event.target.value as UnansweredStatus | "all");
            setOffset(0);
          }}
          className="h-11 rounded-control border border-rule bg-surface px-3 font-sans text-ui text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-marine"
        >
          <option value="open">Open</option>
          <option value="resolved">Resolved</option>
          <option value="all">All</option>
        </select>
      </div>

      {data.truncated && (
        <p className="rounded-panel border border-rule bg-surface px-4 py-3 text-meta text-ink-soft">
          {ADMIN_COPY.truncated}
        </p>
      )}

      {notice && (
        <p aria-live="polite" className="text-ui-label text-ink-soft">
          {notice}
        </p>
      )}

      {actionError && (
        <p role="alert" className="text-ui text-brick">
          {actionError.text}
        </p>
      )}

      <DataTable
        caption="Unanswered questions"
        columns={columns}
        rows={data.items}
        rowKey={(row) => row.normalized_hash}
        empty={ADMIN_COPY.emptyUnanswered}
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
