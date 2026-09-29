/**
 * The visible thread, one element per message.
 *
 * There is no `FallbackMessage` error state here: `answered: false` is a 200
 * carrying an honest "this is not in the documents I have", so it renders as a
 * bubble with the brick rail and keeps its feedback buttons -- a fallback rated
 * "not helpful" is the clearest signal the corpus needs work. Only a request
 * that never produced a response reaches `ErrorNotice`.
 */
import { AnswerBlock } from "./AnswerBlock";
import { ErrorNotice } from "./ErrorNotice";
import { FeedbackButtons } from "./FeedbackButtons";
import { MessageBubble } from "./MessageBubble";
import { OfficeCard } from "./OfficeCard";
import { SourceList } from "./SourceList";
import type { Message, OpenSource } from "../lib/types";

interface MessageListProps {
  messages: Message[];
  openSource: OpenSource | null;
  showMore: Record<string, boolean>;
  /** False above 1024 px, where the side column holds the passage instead. */
  inlineExpand: boolean;
  onToggleSource: (messageId: string, index: number) => void;
  onReveal: (messageId: string) => void;
  onRate: (messageId: string, queryId: string, helpful: boolean) => void;
  onRetry: (question: string) => void;
}

export function MessageList({
  messages,
  openSource,
  showMore,
  inlineExpand,
  onToggleSource,
  onReveal,
  onRate,
  onRetry,
}: MessageListProps) {
  return (
    <ul className="flex flex-col gap-5">
      {messages.map((message) => (
        <li key={message.id}>
          {message.kind === "student" && <MessageBubble variant="student">{message.text}</MessageBubble>}

          {message.kind === "answer" && (
            <AnswerBlock>
              <MessageBubble variant="answer">
                <p className="max-w-measure whitespace-pre-wrap font-serif text-answer text-ink">
                  {message.text}
                </p>
                <SourceList
                  citations={message.citations}
                  answer={message.text}
                  openIndex={
                    openSource?.messageId === message.id ? openSource.index : null
                  }
                  revealed={showMore[message.id] === true}
                  inlineExpand={inlineExpand}
                  onToggleSource={(index) => onToggleSource(message.id, index)}
                  onReveal={() => onReveal(message.id)}
                />
                <FeedbackButtons
                  state={message.feedback}
                  onRate={(helpful) => onRate(message.id, message.queryId, helpful)}
                />
              </MessageBubble>
            </AnswerBlock>
          )}

          {message.kind === "fallback" && (
            <MessageBubble variant="fallback">
              <p className="max-w-measure">{message.text}</p>
              {/* Only when the response named an office. Section 8's action must
                  never appear without a target. */}
              {message.office !== null && <OfficeCard office={message.office} />}
              <FeedbackButtons
                state={message.feedback}
                onRate={(helpful) => onRate(message.id, message.queryId, helpful)}
              />
            </MessageBubble>
          )}

          {message.kind === "error" && (
            <ErrorNotice error={message.error} onRetry={() => onRetry(message.question)} />
          )}
        </li>
      ))}
    </ul>
  );
}
