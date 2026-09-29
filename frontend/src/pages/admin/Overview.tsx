/**
 * The dashboard: PRD FR-9's summary cards, plus DESIGN_SYSTEM.md section 8's
 * "category bar chart and the unanswered queue preview".
 *
 * The four cards are section 8's set -- Questions, Answered, Unanswered, Top
 * category. PRD FR-9 lists "total queries, answer rate, top categories,
 * unanswered count", which is the same four with the answer *rate* where
 * section 8 has a bare Answered count. Both are kept: the Answered card's value
 * is the count and the rate sits under it, so neither document's number is
 * missing.
 *
 * `truncated` is surfaced rather than swallowed. The grouped figures come from
 * a bounded window, and a dashboard that quietly under-reports is worse than
 * one that says its totals are floors.
 */
import { CategoryBarChart } from "../../components/admin/CategoryBarChart";
import { StatCard } from "../../components/admin/StatCard";
import { ADMIN_COPY } from "../../lib/constants";
import { fetchStats } from "../../lib/api";
import { formatCategory, formatCount, formatGroupMeta } from "../../lib/format";
import { PageState } from "./PageState";
import { useAsync } from "../../hooks/useAsync";
import { routeHref } from "../../lib/router";

interface OverviewProps {
  token: string;
}

export function Overview({ token }: OverviewProps) {
  const { data, error, loading, reload } = useAsync(() => fetchStats(token), token);

  if (loading || error || !data) {
    return <PageState loading={loading} error={error} onRetry={reload} title="Overview" />;
  }

  const answered = data.answered.value;
  const questions = data.questions.value;
  const rate = questions === 0 ? null : Math.round((answered / questions) * 100);
  const top = data.top_category;

  return (
    <section className="flex flex-col gap-6">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h1 className="font-serif text-page-title text-ink">Overview</h1>
        <p className="text-meta text-ink-soft">{`Last ${data.window_days} days`}</p>
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatCard
          label="Questions"
          value={questions}
          previous={data.questions.previous}
        />
        <StatCard
          label="Answered"
          value={answered}
          previous={data.answered.previous}
          note={rate === null ? undefined : `${rate}% of questions`}
        />
        <StatCard
          label="Unanswered"
          value={data.unanswered.value}
          previous={data.unanswered.previous}
        />
        <StatCard
          label="Top category"
          value={top.count}
          valueText={top.category === null ? "None" : formatCategory(top.category)}
          note={top.count === 0 ? undefined : `${formatCount(top.count)} questions`}
          changeText={
            top.previous_category === null || top.previous_category === top.category
              ? null
              : `Was ${formatCategory(top.previous_category)}`
          }
        />
      </div>

      {data.truncated && (
        <p className="rounded-panel border border-rule bg-surface px-4 py-3 text-meta text-ink-soft">
          {ADMIN_COPY.truncated}
        </p>
      )}

      <div className="flex flex-col gap-3">
        <h2 className="font-serif text-section-title text-ink">Questions by category</h2>
        <CategoryBarChart categories={data.categories} />
      </div>

      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="font-serif text-section-title text-ink">Unanswered</h2>
          <a
            href={routeHref("/admin/unanswered")}
            className="rounded-control font-sans text-ui-label text-marine hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-marine"
          >
            View all
          </a>
        </div>
        {data.unanswered_preview.length === 0 ? (
          <p className="rounded-panel border border-rule bg-surface px-4 py-6 text-ui text-ink-soft">
            {ADMIN_COPY.emptyUnanswered}
          </p>
        ) : (
          <ul className="flex flex-col gap-2">
            {data.unanswered_preview.map((group) => (
              <li
                key={group.normalized_hash}
                className="rounded-panel border border-rule bg-surface px-4 py-3"
              >
                <p className="text-ui text-ink">{group.question}</p>
                <p className="mt-1 text-meta text-ink-soft">{formatGroupMeta(group)}</p>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
