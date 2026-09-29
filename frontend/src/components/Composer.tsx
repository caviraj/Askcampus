/**
 * DESIGN_SYSTEM.md section 8's chat input.
 *
 * "Multi-line textarea, auto-grow to 4 lines, 16 px text (prevents zoom on
 * iOS). Send button is disabled while a response is loading. Enter sends,
 * Shift+Enter adds a line."
 */
import { useCallback, useRef, useState } from "react";
import type { KeyboardEvent } from "react";

import { useAutogrow } from "../hooks/useAutogrow";
import { COPY, MAX_QUESTION_CHARS } from "../lib/constants";
import { SendIcon } from "./Icons";

interface ComposerProps {
  /** True while a question is in flight. */
  loading: boolean;
  /** Seconds left on a rate limit, or null. */
  cooldownSeconds: number | null;
  onSend: (question: string) => void;
}

export function Composer({ loading, cooldownSeconds, onSend }: ComposerProps) {
  const [draft, setDraft] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  useAutogrow(textareaRef, draft);

  const blocked = loading || cooldownSeconds !== null;
  const canSend = draft.trim().length > 0 && !blocked;

  const submit = useCallback(() => {
    const question = draft.trim();
    if (!question || blocked) return;
    onSend(question);
    setDraft("");
  }, [draft, blocked, onSend]);

  const onKeyDown = useCallback(
    (event: KeyboardEvent<HTMLTextAreaElement>) => {
      if (event.key !== "Enter" || event.shiftKey) return;
      // An IME uses Enter to accept a candidate. Sending there would submit a
      // half-composed question on every Japanese or Chinese input.
      if (event.nativeEvent.isComposing) return;
      event.preventDefault();
      submit();
    },
    [submit],
  );

  return (
    <form
      className="composer-shadow sticky bottom-0 z-10 border-t border-rule bg-paper px-4 pb-[max(0.75rem,env(safe-area-inset-bottom))] pt-3"
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      <div className="mx-auto flex max-w-[720px] items-end gap-2">
        <label className="sr-only" htmlFor="composer-input">
          Your question
        </label>
        <textarea
          id="composer-input"
          ref={textareaRef}
          rows={1}
          value={draft}
          maxLength={MAX_QUESTION_CHARS}
          disabled={blocked}
          placeholder={COPY.composerPlaceholder}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={onKeyDown}
          className="min-h-[44px] flex-1 resize-none rounded-control border border-rule bg-surface px-3 py-2.5 font-sans text-composer text-ink placeholder:text-ink-soft disabled:opacity-45"
        />
        <button
          type="submit"
          disabled={!canSend}
          aria-disabled={!canSend}
          className="flex min-h-[44px] min-w-[44px] items-center justify-center gap-1.5 rounded-control bg-marine px-4 font-sans text-ui-label text-white hover:bg-marine-deep disabled:opacity-45"
        >
          <SendIcon />
          Send
        </button>
      </div>

      {cooldownSeconds !== null && (
        <p className="mx-auto mt-2 max-w-[720px] font-sans text-meta text-ink-soft" role="status">
          {`You can ask again in ${cooldownSeconds} seconds.`}
        </p>
      )}
    </form>
  );
}
