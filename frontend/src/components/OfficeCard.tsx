/**
 * DESIGN_SYSTEM.md section 8's "Ask the office" action on the fallback bubble.
 *
 * Rendered only when the response carries an office, so the action never
 * appears without a target -- and the fallback copy on that path names the
 * office rather than pointing at one.
 *
 * The card shows the office name and nothing else. Section 9 has no copy for a
 * card, and AGENTS.md section 6.5 forbids a fabricated contact, so there is no
 * phone number, no email address, and no link here: every one of them would
 * have to be invented.
 */
interface OfficeCardProps {
  office: string;
}

export function OfficeCard({ office }: OfficeCardProps) {
  return (
    <div className="mt-3 rounded-control border border-rule bg-surface px-3 py-2">
      <p className="font-sans text-meta text-ink-soft">Office</p>
      <p className="font-serif text-section-title font-semibold text-ink">{office}</p>
    </div>
  );
}
