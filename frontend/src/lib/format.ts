/**
 * Display strings derived from API values.
 *
 * Kept out of the components so each rule is stated once and can be tested
 * without rendering anything.
 */
import type { Citation, UnansweredGroup } from "./types";

/** A category as it is displayed. `null` is the classifier declining to place a
 *  question, which is not the same as the `general` category and must not read
 *  as though it were. */
export function formatCategory(category: string | null): string {
  if (!category) return "Uncategorised";
  return category.replace(/_/g, " ").replace(/^./, (letter) => letter.toUpperCase());
}

const SECTION_FALLBACK = "Section not named";

/**
 * DESIGN_SYSTEM.md section 7's label format: `Exam Schedule Nov–Dec 2026, page 2`.
 *
 * The title is never abbreviated beyond truncation, which CSS does. When there
 * is no page number -- DOCX and TXT have none -- the section heading stands in
 * its place, because "Title, page null" is worse than naming the part of the
 * document the passage came from.
 */
export function formatSlipLabel(citation: Citation): string {
  const { document_title: title, page, section } = citation;
  if (page !== null) return `${title}, page ${page}`;
  if (section) return `${title}, ${section}`;
  return title;
}

/** The location shown on the collapsed slip, beside the icon. */
export function formatSlipLocation(citation: Citation): string {
  if (citation.page !== null) return `Page ${citation.page}`;
  if (citation.section) return citation.section;
  return SECTION_FALLBACK;
}

const DATE_FORMAT: Intl.DateTimeFormatOptions = {
  day: "numeric",
  month: "long",
  year: "numeric",
};

/**
 * `last_updated` as a readable date, or null when the row has none.
 *
 * Returns null rather than a placeholder: the meta line omits the field instead
 * of printing "unknown", which would read as a fact about the document.
 */
export function formatLastUpdated(value: string | null): string | null {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return new Intl.DateTimeFormat("en-GB", DATE_FORMAT).format(date);
}

/** Whole seconds left, never negative, for the rate-limit countdown. */
export function secondsUntil(epochMs: number, now: number = Date.now()): number {
  return Math.max(0, Math.ceil((epochMs - now) / 1000));
}

const DATE_TIME_FORMAT: Intl.DateTimeFormatOptions = {
  day: "numeric",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
};

/** A timestamp for a table cell, or an em dash when the row has none. */
export function formatDateTime(value: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("en-GB", DATE_TIME_FORMAT).format(date);
}

/** MB with one decimal, because "1.5 MB" is a size and "2 MB" is a guess. */
export function formatBytes(bytes: number | null): string {
  if (bytes === null || !Number.isFinite(bytes)) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} kB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** A retrieval score as a percentage. `null` means only the keyword list found
 *  the chunk, so there is no cosine similarity to show -- not a zero. */
export function formatScore(score: number | null): string {
  if (score === null) return "—";
  return `${Math.round(score * 100)}%`;
}

/**
 * The change from the previous period, as §8's cards show it.
 *
 * Returns null when there is no previous period to compare against, so the card
 * can omit the line instead of printing "+0 from 0", which reads as no change
 * when it means no data.
 */
export function formatChange(value: number, previous: number): string | null {
  if (previous === 0) return null;
  const delta = value - previous;
  if (delta === 0) return "No change";
  const direction = delta > 0 ? "up" : "down";
  return `${direction} ${Math.abs(delta)}`;
}

/**
 * The label for a linked source on a logged query.
 *
 * Deliberately not `formatSlipLabel`: a history row's source has no `label`
 * field and may have no page, so it reuses the same rule but reads the fields
 * that exist. A missing title is dropped rather than printed as "null".
 */
export function formatHistorySource(source: {
  document_title: string | null;
  page_number: number | null;
  section_heading: string | null;
}): string {
  const title = source.document_title ?? "Deleted document";
  if (source.page_number !== null) return `${title}, page ${source.page_number}`;
  if (source.section_heading) return `${title}, ${source.section_heading}`;
  return title;
}

/**
 * A count with thousands separators.
 *
 * The admin screens are the only place numbers get large -- a query log runs to
 * four or five digits -- and `1204` is read as a year where `1,204` is read as
 * a quantity.
 */
export function formatCount(value: number): string {
  return new Intl.NumberFormat("en-GB").format(value);
}

/** How a queue group's age reads: the most recent time it was asked. */
export function formatGroupMeta(group: UnansweredGroup): string {
  const asked = group.count === 1 ? "asked once" : `asked ${group.count} times`;
  return `${asked} · last ${formatDateTime(group.last_asked_at)}`;
}
