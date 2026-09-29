/**
 * The earlier messages sent with a question.
 *
 * The backend uses history for *retrieval only* -- it builds the embedded
 * search text, so a follow-up like "and the late fee?" finds the fee circular.
 * The answering prompt never sees it, so nothing here can become something the
 * model treats as an instruction.
 */
import { MAX_HISTORY_MESSAGES, MAX_TURN_CHARS } from "./constants";
import type { HistoryTurn, Message } from "./types";

/**
 * The last few messages, oldest first.
 *
 * Called with the thread as it was *before* the current question was
 * dispatched. The backend appends `question` to the search text itself, so
 * including it here would weight the student's own words twice.
 */
export function buildHistory(messages: readonly Message[]): HistoryTurn[] {
  const turns: HistoryTurn[] = [];

  for (const message of messages) {
    // Errors never produced an answer, and a fallback's text is the server's
    // "This is not in the college documents I have", whose words no student
    // wrote -- either would put noise into the embedded query.
    if (message.kind !== "student" && message.kind !== "answer") continue;
    const content = message.text;
    // Dropped whole rather than truncated. A half-sentence turn silently
    // changes what the follow-up resolves to, which is worse than having one
    // fewer turn of context.
    if (content.length > MAX_TURN_CHARS) continue;
    turns.push({ role: message.kind === "student" ? "user" : "assistant", content });
  }

  const window = turns.slice(-MAX_HISTORY_MESSAGES);
  // An opening answer whose question fell outside the window is context nobody
  // can interpret, and it would be sent as an assistant turn with no user turn
  // before it.
  while (window.length > 0 && window[0]?.role === "assistant") window.shift();
  return window;
}
