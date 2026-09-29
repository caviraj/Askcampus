/**
 * What the student sees when the request itself failed.
 *
 * Never used for `answered: false`. That is a 200 carrying an honest "this is
 * not in the documents I have", and it renders as a fallback bubble with the
 * brick rail -- not as an error. Styling it as a failure would tell a student
 * the system broke when it worked exactly as intended.
 */
import { AlertIcon } from "./Icons";
import type { ErrorView } from "../lib/types";

interface ErrorNoticeProps {
  error: ErrorView;
  onRetry: () => void;
}

export function ErrorNotice({ error, onRetry }: ErrorNoticeProps) {
  return (
    <div
      role="alert"
      className="rounded-panel border border-rule bg-surface py-4 pl-5 pr-4 [border-left:3px_solid_var(--brick)]"
    >
      <p className="flex items-start gap-2 font-sans text-ui text-ink">
        <AlertIcon className="mt-1 shrink-0 text-brick" />
        <span>{error.text}</span>
      </p>

      {/*
        No countdown here even on a 429. The composer is sticky at the bottom of
        the same screen and counts the wait down next to the box the student has
        to wait for; printing the same number twice in one viewport is noise.
      */}
      {error.canRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="mt-2 min-h-[44px] rounded-control px-1 font-sans text-ui-label text-marine underline"
        >
          Send it again
        </button>
      )}
    </div>
  );
}
