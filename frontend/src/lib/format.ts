/**
 * Display strings derived from API values.
 *
 * Kept out of the components so each rule is stated once and can be tested
 * without rendering anything.
 */
import type { Citation } from "./types";

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
