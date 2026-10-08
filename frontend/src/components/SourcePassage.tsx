/**
 * The expanded body of a source slip.
 *
 * Rendered in whichever position DESIGN_SYSTEM.md section 6 calls for -- inline
 * under the slip below 1024 px, and in the 320 px side column above it -- so it
 * is one component with no idea where it is.
 */
import { formatLastUpdated } from "../lib/format";
import { selectSupportingSentence } from "../lib/highlight";
import type { Citation } from "../lib/types";

interface SourcePassageProps {
  citation: Citation;
  /** The answer this passage was cited for. The supporting sentence is chosen
   *  by overlap with it, so without it nothing can be marked honestly. */
  answer: string;
}

export function SourcePassage({ citation, answer }: SourcePassageProps) {
  const highlighted = selectSupportingSentence(citation.snippet, answer);
  const updated = formatLastUpdated(citation.last_updated);

  return (
    <div className="border-t border-rule bg-surface px-3 py-3">
      {/*
        The passage is rendered as three plain text nodes, never as HTML.
        AGENTS.md section 6.10 forbids `dangerouslySetInnerHTML`, and document
        text is data -- a chunk containing markup must appear as those
        characters, not be parsed.
      */}
      <p className="max-w-measure whitespace-pre-wrap font-serif text-slip-passage text-ink">
        {highlighted ? (
          <>
            {highlighted.before}
            <mark className="bg-highlight-wash text-on-highlight">{highlighted.match}</mark>
            {highlighted.after}
          </>
        ) : (
          citation.snippet
        )}
      </p>

      <dl className="mt-3 flex flex-wrap gap-x-4 gap-y-1 font-sans text-meta text-ink-soft">
        <div className="flex gap-1">
          <dt className="sr-only">Document</dt>
          <dd>{citation.document_title}</dd>
        </div>
        {citation.page !== null && (
          <div className="flex gap-1">
            <dt>Page</dt>
            <dd>{citation.page}</dd>
          </div>
        )}
        {citation.section && (
          <div className="flex gap-1">
            <dt>Section</dt>
            <dd>{citation.section}</dd>
          </div>
        )}
        <div className="flex gap-1">
          <dt>Last updated</dt>
          {/* Omitted rather than shown as "unknown", which would read as a fact
              about the document rather than a gap in the row. */}
          <dd>{updated ?? "Not recorded"}</dd>
        </div>
      </dl>
    </div>
  );
}
