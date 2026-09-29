import { describe, expect, it } from "vitest";

import { MAX_TURN_CHARS } from "./constants";
import { buildHistory } from "./history";
import type { Message } from "./types";

const question = (id: string, text: string): Message => ({ id, kind: "student", text });

const answer = (id: string, text: string): Message => ({
  id,
  kind: "answer",
  queryId: `q-${id}`,
  text,
  citations: [],
  feedback: "idle",
});

const fallback = (id: string, text: string): Message => ({
  id,
  kind: "fallback",
  queryId: `q-${id}`,
  text,
  office: null,
  feedback: "idle",
});

const failure = (id: string): Message => ({
  id,
  kind: "error",
  question: "what happened",
  error: { text: "…", cooldownSeconds: null, canRetry: true },
});

describe("buildHistory", () => {
  it("keeps the question and answer roles in order", () => {
    expect(buildHistory([question("1", "When are marks out?"), answer("2", "In a week.")])).toEqual([
      { role: "user", content: "When are marks out?" },
      { role: "assistant", content: "In a week." },
    ]);
  });

  it("sends four messages at most, because that is what the backend compares against", () => {
    // `chat_history_max_turns` is checked against a list of individual messages,
    // so four means two exchanges -- not four. This is the assertion that would
    // fail if someone "corrected" the constant to eight.
    const thread: Message[] = [];
    for (let index = 1; index <= 5; index += 1) {
      thread.push(question(`q${index}`, `question ${index}`));
      thread.push(answer(`a${index}`, `answer ${index}`));
    }

    const history = buildHistory(thread);
    expect(history).toHaveLength(4);
    expect(history.map((turn) => turn.content)).toEqual([
      "question 4",
      "answer 4",
      "question 5",
      "answer 5",
    ]);
  });

  it("drops a leading answer whose question fell outside the window", () => {
    const thread: Message[] = [
      question("q1", "question 1"),
      answer("a1", "answer 1"),
      question("q2", "question 2"),
      answer("a2", "answer 2"),
      question("q3", "question 3"),
    ];

    const history = buildHistory(thread);
    expect(history[0]).toEqual({ role: "user", content: "question 2" });
    expect(history.map((turn) => turn.role)).toEqual(["user", "assistant", "user"]);
  });

  it("drops errors, which never produced an answer", () => {
    const history = buildHistory([question("1", "hello"), failure("2")]);
    expect(history).toEqual([{ role: "user", content: "hello" }]);
  });

  it("drops fallbacks, whose words no student wrote", () => {
    const history = buildHistory([
      question("1", "what about the hostel?"),
      fallback("2", "This is not in the documents I have."),
      question("3", "and the mess?"),
    ]);
    expect(history.map((turn) => turn.content)).toEqual([
      "what about the hostel?",
      "and the mess?",
    ]);
  });

  it("drops an over-length turn whole rather than truncating it", () => {
    const long = "x".repeat(MAX_TURN_CHARS + 1);
    const history = buildHistory([
      question("0", "first question"),
      question("1", long),
      answer("2", "short answer"),
    ]);
    // The long question is gone entirely -- not cut to 1000 characters, which
    // would leave three turns here instead of two.
    expect(history).toEqual([
      { role: "user", content: "first question" },
      { role: "assistant", content: "short answer" },
    ]);
  });

  it("keeps a turn exactly at the limit", () => {
    const atLimit = "x".repeat(MAX_TURN_CHARS);
    expect(buildHistory([question("1", atLimit)])).toHaveLength(1);
  });

  it("returns nothing for an empty thread", () => {
    expect(buildHistory([])).toEqual([]);
  });
});
