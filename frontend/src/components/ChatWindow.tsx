/**
 * The thread, its evidence, the chips and the composer -- everything below the
 * header.
 *
 * It owns the request lifecycle rather than the page, because the composer and
 * the message list are on opposite sides of the layout and both need `send`.
 * Splitting them would mean lifting the whole reducer one level up and passing
 * eight props back down through two layers.
 *
 * DESIGN_SYSTEM.md section 6 puts the expanded passage in one of two places: an
 * inline expansion under the slip below 1024 px, and a 320 px side column above
 * it. Two positions, one piece of state -- so `useChatThread` holds it, this
 * component decides where to draw it, and `SourceSlip` holds none.
 */
import { useEffect, useRef, useState } from "react";

import { useChatThread } from "../hooks/useChatThread";
import { useMediaQuery, WIDE_LAYOUT_QUERY } from "../hooks/useMediaQuery";
import { CategoryChips } from "./CategoryChips";
import { Composer } from "./Composer";
import { EmptyState } from "./EmptyState";
import { MessageList } from "./MessageList";
import { SkeletonAnswer } from "./SkeletonAnswer";
import { SourcePassage } from "./SourcePassage";
import type { CategoryChip, CategoryFilter } from "../lib/types";

interface ChatWindowProps {
  sessionId: string;
  categories: CategoryChip[];
}

export function ChatWindow({ sessionId, categories }: ChatWindowProps) {
  const thread = useChatThread(sessionId);
  const wide = useMediaQuery(WIDE_LAYOUT_QUERY);
  const [category, setCategory] = useState<CategoryFilter | null>(null);

  const endRef = useRef<HTMLDivElement>(null);
  const lastMessage = thread.messages[thread.messages.length - 1];

  // Scroll on a new message and on a new skeleton, so the newest thing is the
  // thing on screen. `block: "end"` and no `behavior: "smooth"`: smooth
  // scrolling is motion, and section 10 asks for none without a reason.
  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [thread.messages.length, thread.status]);

  // The passage the side column shows, resolved from the open-slip state. Only
  // an answer message has citations, so a fallback can never reach the column
  // however the state is set.
  const openId = thread.openSource?.messageId ?? null;
  const openMessage = openId
    ? thread.messages.find((message) => message.id === openId)
    : undefined;
  const openAnswer = openMessage?.kind === "answer" ? openMessage : null;
  const citation = wide
    ? (openAnswer?.citations[thread.openSource?.index ?? -1] ?? null)
    : null;

  return (
    <div className="flex flex-1 flex-col">
      <div className="mx-auto flex w-full max-w-[1100px] flex-1 gap-6 px-4 py-6">
        <div className="flex min-w-0 flex-1 flex-col">
          {/*
            Mounted on the first paint and never conditionally rendered. A
            screen reader only announces mutations inside a region that already
            existed, so a region that mounts already holding the answer
            announces nothing at all. The chips and the composer sit outside it
            -- inside, every keystroke in the textarea would be read aloud.
          */}
          <div aria-live="polite" aria-atomic="false" className="flex-1">
            {thread.messages.length === 0 && thread.status === "idle" ? (
              <EmptyState />
            ) : (
              <MessageList
                messages={thread.messages}
                openSource={thread.openSource}
                showMore={thread.showMore}
                inlineExpand={!wide}
                onToggleSource={thread.toggleSource}
                onReveal={thread.revealMore}
                onRate={thread.rate}
                onRetry={(question) => void thread.retry(question)}
              />
            )}

            {thread.status === "loading" && (
              <div className={lastMessage ? "mt-5" : ""}>
                <SkeletonAnswer />
              </div>
            )}
          </div>

          <div ref={endRef} />

          <div className="mt-6">
            <CategoryChips
              categories={categories}
              selected={category}
              onSelect={setCategory}
              onAsk={(question) => void thread.send(question, category)}
            />
          </div>
        </div>

        {wide && openAnswer && citation && (
          <aside
            aria-label="Cited passage"
            className="w-80 shrink-0 self-start rounded-panel border border-rule bg-surface"
          >
            <SourcePassage citation={citation} answer={openAnswer.text} />
            <div className="border-t border-rule px-3 py-2">
              <button
                type="button"
                onClick={thread.closeSource}
                className="min-h-[44px] rounded-control px-1 font-sans text-ui-label text-marine underline"
              >
                Close
              </button>
            </div>
          </aside>
        )}
      </div>

      <Composer
        loading={thread.status === "loading"}
        cooldownSeconds={thread.cooldownSeconds}
        onSend={(question) => void thread.send(question, category)}
      />
    </div>
  );
}
