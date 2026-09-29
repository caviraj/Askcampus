/**
 * One of DESIGN_SYSTEM.md section 8's four dashboard numbers: "the value, a
 * plain label, and the change from the previous 7 days".
 *
 * The change line is omitted rather than zeroed when there is no previous
 * period to compare against -- `formatChange` returns null for that case, and
 * "+0 from 0" would claim a measured stillness the data does not support.
 */
import { formatChange, formatCount } from "../../lib/format";

interface StatCardProps {
  label: string;
  value: number;
  previous?: number | undefined;
  /** Shown instead of the formatted count, for a card whose value is a name. */
  valueText?: string | undefined;
  /** A second line under the value, for a number that needs its denominator --
   *  PRD FR-9 asks for an answer *rate*, which is a count over a count. */
  note?: string | undefined;
  /** Replaces the computed change line. The top-category card compares labels
   *  rather than counts, so the arithmetic `formatChange` does would be wrong
   *  there. `null` omits the line. */
  changeText?: string | null | undefined;
}

export function StatCard({
  label,
  value,
  previous,
  valueText,
  note,
  changeText,
}: StatCardProps) {
  const change =
    changeText !== undefined
      ? changeText
      : previous === undefined
        ? null
        : formatChange(value, previous);

  return (
    <div className="flex flex-col gap-1 rounded-panel border border-rule bg-surface px-4 py-3">
      <p className="font-sans text-ui-label text-ink-soft">{label}</p>
      <p className="font-serif text-page-title text-ink">
        {valueText ?? formatCount(value)}
      </p>
      {note !== undefined && <p className="text-meta text-ink-soft">{note}</p>}
      {change !== null && <p className="text-meta text-ink-soft">{change}</p>}
    </div>
  );
}
