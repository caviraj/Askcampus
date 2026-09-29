/**
 * The loading and error states every admin page shares.
 *
 * A page renders this instead of its content while the first request is in
 * flight or after it failed, so the heading stays put and the screen does not
 * jump when data arrives.
 *
 * The loading state is a skeleton rather than a spinner, matching section 8's
 * chat rule ("three-line skeleton in `--rule`, no spinner") so the two halves
 * of the product wait the same way.
 */
import { ErrorNotice } from "../../components/ErrorNotice";
import type { ErrorView } from "../../lib/types";

interface PageStateProps {
  title: string;
  loading: boolean;
  error: ErrorView | null;
  onRetry: () => void;
}

export function PageState({ title, loading, error, onRetry }: PageStateProps) {
  return (
    <section className="flex flex-col gap-6">
      <h1 className="font-serif text-page-title text-ink">{title}</h1>
      {error ? (
        <ErrorNotice error={error} onRetry={onRetry} />
      ) : (
        loading && (
          <div aria-busy="true" className="flex flex-col gap-3">
            <span className="sr-only">Loading</span>
            {[0, 1, 2].map((line) => (
              <span
                key={line}
                aria-hidden="true"
                className="block h-4 rounded-control bg-rule"
                style={{ width: `${100 - line * 18}%` }}
              />
            ))}
          </div>
        )
      )}
    </section>
  );
}
