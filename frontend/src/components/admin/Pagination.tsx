/**
 * Offset paging for the three list screens.
 *
 * The API counts the whole result separately from the page it returns, so the
 * range line can say "1-20 of 137" rather than "page 1", which is the number an
 * admin actually wants. Both buttons are `aria-disabled` at the ends rather
 * than `disabled`: a button that disappears from the tab order moves the focus
 * ring somewhere the user did not put it.
 */
import { formatCount } from "../../lib/format";

interface PaginationProps {
  total: number;
  limit: number;
  offset: number;
  onChange: (offset: number) => void;
}

export function Pagination({ total, limit, offset, onChange }: PaginationProps) {
  if (total <= limit) return null;

  const first = offset + 1;
  const last = Math.min(offset + limit, total);
  const atStart = offset <= 0;
  const atEnd = offset + limit >= total;

  return (
    <nav
      aria-label="Result pages"
      className="flex flex-wrap items-center justify-between gap-3 px-1 py-3"
    >
      <p className="text-meta text-ink-soft" aria-live="polite">
        {`${formatCount(first)}–${formatCount(last)} of ${formatCount(total)}`}
      </p>
      <div className="flex gap-2">
        <PageButton
          label="Previous"
          disabled={atStart}
          onClick={() => onChange(Math.max(0, offset - limit))}
        />
        <PageButton
          label="Next"
          disabled={atEnd}
          onClick={() => onChange(offset + limit)}
        />
      </div>
    </nav>
  );
}

function PageButton({
  label,
  disabled,
  onClick,
}: {
  label: string;
  disabled: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      aria-disabled={disabled}
      onClick={() => {
        if (!disabled) onClick();
      }}
      className={`inline-flex h-11 min-w-[44px] items-center justify-center rounded-control border border-marine px-4 font-sans text-ui-label text-marine hover:bg-marine-wash focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-marine ${
        disabled ? "opacity-45" : ""
      }`}
    >
      {label}
    </button>
  );
}
