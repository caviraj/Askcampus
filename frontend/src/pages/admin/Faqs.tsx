/**
 * FAQs: the questions students ask most, grouped by category.
 *
 * Derived from the query log rather than curated. Every entry is a question
 * that was actually asked, which is what makes the list worth reading -- a
 * hand-written FAQ answers what the office *thinks* students wonder about.
 *
 * Only answered questions appear, because an entry here is a candidate for a
 * page that answers it, and the unanswered ones are on their own screen with
 * their own workflow.
 */
import { ADMIN_COPY } from "../../lib/constants";
import { fetchFaqs } from "../../lib/api";
import { formatCategory, formatCount, formatDateTime } from "../../lib/format";
import { PageState } from "./PageState";
import { useAsync } from "../../hooks/useAsync";

interface FaqsProps {
  token: string;
}

export function Faqs({ token }: FaqsProps) {
  const { data, error, loading, reload } = useAsync(() => fetchFaqs(token), token);

  if (loading || error || !data) {
    return <PageState loading={loading} error={error} onRetry={reload} title="FAQs" />;
  }

  return (
    <section className="flex flex-col gap-5">
      <h1 className="font-serif text-page-title text-ink">FAQs</h1>

      {data.truncated && (
        <p className="rounded-panel border border-rule bg-surface px-4 py-3 text-meta text-ink-soft">
          {ADMIN_COPY.truncated}
        </p>
      )}

      {data.groups.length === 0 ? (
        <p className="rounded-panel border border-rule bg-surface px-4 py-6 text-ui text-ink-soft">
          {ADMIN_COPY.emptyFaqs}
        </p>
      ) : (
        data.groups.map((group) => (
          <div key={group.category ?? "__uncategorised"} className="flex flex-col gap-3">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <h2 className="font-serif text-section-title text-ink">
                {formatCategory(group.category)}
              </h2>
              <p className="text-meta text-ink-soft">
                {`${formatCount(group.total)} questions`}
              </p>
            </div>
            <ol className="flex flex-col gap-2">
              {group.items.map((item) => (
                <li
                  key={item.normalized_hash}
                  className="flex flex-wrap items-baseline justify-between gap-2 rounded-panel border border-rule bg-surface px-4 py-3"
                >
                  <span className="text-ui text-ink">{item.question}</span>
                  <span className="text-meta text-ink-soft">
                    {`asked ${formatCount(item.count)} times · last ${formatDateTime(item.last_asked_at)}`}
                  </span>
                </li>
              ))}
            </ol>
          </div>
        ))
      )}
    </section>
  );
}
