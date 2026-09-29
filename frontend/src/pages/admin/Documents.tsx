/**
 * The documents manager: upload, filter, reprocess, replace, activate and
 * delete.
 *
 * Two things section 8 asks for that shape the table:
 * - "Failed rows show the error message inline and a Reprocess button", so the
 *   failure reason is a cell rather than something behind an expansion.
 * - Status is the badge component, never colour alone.
 *
 * Sorting is applied to the rows on screen, not to the whole table. The list
 * endpoint takes no `order` parameter, so a click here cannot reorder rows that
 * have not been fetched; the page says so while a sort is active rather than
 * letting the arrow imply otherwise.
 */
import { useCallback, useMemo, useState } from "react";

import { DataTable, type Column, type SortDirection } from "../../components/admin/DataTable";
import { Pagination } from "../../components/admin/Pagination";
import { StatusBadge } from "../../components/admin/StatusBadge";
import { UploadDialog } from "../../components/admin/UploadDialog";
import { ADMIN_COPY, DOCUMENT_CATEGORIES } from "../../lib/constants";
import {
  deleteDocument,
  fetchDocuments,
  reprocessDocument,
  replaceDocument,
} from "../../lib/api";
import { formatBytes, formatCategory, formatDateTime } from "../../lib/format";
import { toErrorView } from "../../lib/errors";
import { PageState } from "./PageState";
import { useAsync, usePolling } from "../../hooks/useAsync";
import type { AdminDocument, DocumentStatus, ErrorView } from "../../lib/types";

interface DocumentsProps {
  token: string;
}

const PAGE_SIZE = 20;

export function Documents({ token }: DocumentsProps) {
  const [status, setStatus] = useState<DocumentStatus | "all">("all");
  const [category, setCategory] = useState("all");
  const [offset, setOffset] = useState(0);
  const [uploading, setUploading] = useState(false);
  const [pending, setPending] = useState<string | null>(null);
  const [actionError, setActionError] = useState<ErrorView | null>(null);
  const [sortKey, setSortKey] = useState<string | null>(null);
  const [sortDirection, setSortDirection] = useState<SortDirection>("asc");

  const { data, error, loading, reload } = useAsync(
    () => fetchDocuments(token, { status, category, limit: PAGE_SIZE, offset }),
    `${token}|${status}|${category}|${offset}`,
  );

  // A row that is still being processed will change on its own, so the list
  // re-reads until none of them are. This is the same wait the upload dialog
  // does, continued on the page an admin lands on afterwards.
  const working = (data?.items ?? []).some(
    (item) => item.status === "uploaded" || item.status === "processing",
  );
  usePolling(reload, { active: working, intervalMs: 2500 });

  const run = useCallback(
    async (id: string, action: () => Promise<unknown>) => {
      setPending(id);
      setActionError(null);
      try {
        await action();
        reload();
      } catch (cause) {
        setActionError(toErrorView(cause));
      } finally {
        setPending(null);
      }
    },
    [reload],
  );

  const sorted = useMemo(
    () => sortDocuments(data?.items ?? [], sortKey, sortDirection),
    [data, sortKey, sortDirection],
  );

  const columns: Column<AdminDocument>[] = [
    {
      key: "title",
      header: "Title",
      sortable: true,
      render: (row) => (
        <div className="flex flex-col">
          <span className="text-ink">{row.title}</span>
          {row.status === "failed" && row.error_message && (
            <span className="text-meta text-brick">{row.error_message}</span>
          )}
        </div>
      ),
    },
    {
      key: "category",
      header: "Category",
      sortable: true,
      render: (row) => formatCategory(row.category),
    },
    {
      key: "academic_year",
      header: "Year",
      render: (row) => row.academic_year ?? "—",
    },
    {
      key: "department",
      header: "Department",
      render: (row) => row.department ?? "—",
    },
    {
      key: "status",
      header: "Status",
      render: (row) => (
        <div className="flex flex-col gap-1">
          <StatusBadge status={row.status} />
          {!row.is_active && <span className="text-meta text-ink-soft">Not searchable</span>}
        </div>
      ),
    },
    {
      key: "size",
      header: "Size",
      numeric: true,
      render: (row) => formatBytes(row.file_size_bytes),
    },
    {
      key: "chunks",
      header: "Sections",
      numeric: true,
      sortable: true,
      render: (row) => (row.chunk_count === null ? "—" : String(row.chunk_count)),
    },
    {
      key: "updated_at",
      header: "Updated",
      sortable: true,
      render: (row) => formatDateTime(row.updated_at),
    },
    {
      key: "actions",
      header: "Actions",
      // No label: the buttons carry their own text, and a "Actions" heading
      // above three verbs would read as a fourth field.
      label: null,
      render: (row) => (
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            aria-disabled={pending === row.id}
            onClick={() => void run(row.id, () => reprocessDocument(token, row.id))}
            className="inline-flex h-11 items-center rounded-control border border-marine px-3 font-sans text-ui-label text-marine hover:bg-marine-wash focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-marine"
          >
            Reprocess
          </button>
          <label className="inline-flex h-11 cursor-pointer items-center rounded-control px-3 font-sans text-ui-label text-marine hover:bg-marine-wash focus-within:outline focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-marine">
            <span className="sr-only">{`Replace the file for ${row.title}`}</span>
            <span aria-hidden="true">Replace</span>
            <input
              type="file"
              className="sr-only"
              onChange={(event) => {
                const file = event.target.files?.[0];
                event.target.value = "";
                if (file) void run(row.id, () => replaceDocument(token, row.id, file));
              }}
            />
          </label>
          <button
            type="button"
            aria-disabled={pending === row.id}
            onClick={() => {
              if (window.confirm(ADMIN_COPY.deleteConfirm)) {
                void run(row.id, () => deleteDocument(token, row.id));
              }
            }}
            className="inline-flex h-11 items-center rounded-control border border-brick px-3 font-sans text-ui-label text-brick hover:bg-paper focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brick"
          >
            Delete
          </button>
        </div>
      ),
    },
  ];

  if (loading || error || !data) {
    return <PageState loading={loading} error={error} onRetry={reload} title="Documents" />;
  }

  return (
    <section className="flex flex-col gap-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="font-serif text-page-title text-ink">Documents</h1>
        <button
          type="button"
          onClick={() => setUploading(true)}
          className="h-11 rounded-control bg-marine px-4 font-sans text-ui-label font-semibold text-white hover:bg-marine-deep focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-marine"
        >
          Upload
        </button>
      </div>

      <div className="flex flex-wrap gap-3">
        <FilterSelect
          id="filter-status"
          label="Status"
          value={status}
          onChange={(value) => {
            setStatus(value as DocumentStatus | "all");
            setOffset(0);
          }}
          options={[
            { value: "all", label: "All" },
            { value: "uploaded", label: "Uploaded" },
            { value: "processing", label: "Processing" },
            { value: "ready", label: "Ready" },
            { value: "failed", label: "Failed" },
          ]}
        />
        <FilterSelect
          id="filter-category"
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

      {actionError && (
        <p role="alert" className="text-ui text-brick">
          {actionError.text}
        </p>
      )}

      {sortKey !== null && (
        <p className="text-meta text-ink-soft">
          Sorted within this page. Earlier pages are not included.
        </p>
      )}

      <DataTable
        caption="Documents"
        columns={columns}
        rows={sorted}
        rowKey={(row) => row.id}
        empty={ADMIN_COPY.emptyDocuments}
        sortKey={sortKey}
        sortDirection={sortDirection}
        onSort={(key) => {
          if (key === sortKey) {
            setSortDirection((current) => (current === "asc" ? "desc" : "asc"));
          } else {
            setSortKey(key);
            setSortDirection("asc");
          }
        }}
      />

      <Pagination
        total={data.total}
        limit={data.limit}
        offset={data.offset}
        onChange={setOffset}
      />

      {uploading && (
        <UploadDialog
          token={token}
          onClose={() => setUploading(false)}
          onUploaded={() => reload()}
        />
      )}
    </section>
  );
}

function FilterSelect({
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

/** Sorts the loaded page. A null key leaves the server's own order alone, which
 *  is newest first. */
function sortDocuments(
  rows: AdminDocument[],
  key: string | null,
  direction: SortDirection,
): AdminDocument[] {
  if (key === null) return rows;
  const sign = direction === "asc" ? 1 : -1;
  return [...rows].sort((left, right) => {
    const a = left[key as keyof AdminDocument];
    const b = right[key as keyof AdminDocument];
    // A missing value sorts last in either direction: an absent year is not
    // "before 2024", it is unknown.
    if (a === null || a === undefined) return 1;
    if (b === null || b === undefined) return -1;
    if (typeof a === "number" && typeof b === "number") return sign * (a - b);
    return sign * String(a).localeCompare(String(b));
  });
}
