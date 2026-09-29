import { useCallback, useEffect, useReducer, useRef, useState } from "react";

import { askQuestion, sendFeedback } from "../lib/api";
import { toErrorView } from "../lib/errors";
import { buildHistory } from "../lib/history";
import { secondsUntil } from "../lib/format";
import type { CategoryFilter, Message, OpenSource } from "../lib/types";

interface ChatState {
  messages: Message[];
  /** Not a `Message` variant on purpose: it is not part of the transcript, so
   *  it must never reach `buildHistory` or be re-sent as context. */
  status: "idle" | "loading";
  /** Which slip is open. One at a time, because the wide layout has a single
   *  side column to put it in. */
  openSource: OpenSource | null;
  /** Epoch ms. The composer stays disabled until this passes. */
  cooldownUntil: number | null;
  /** Presentation only, per message: the "Show N more sources" affordance. */
  showMore: Record<string, boolean>;
}

type Action =
  | { type: "ask"; id: string; text: string }
  | { type: "succeed"; message: Message }
  | { type: "fail"; id: string; question: string; error: unknown }
  | { type: "toggleSource"; messageId: string; index: number }
  | { type: "closeSource" }
  | { type: "showMore"; messageId: string }
  | { type: "feedback"; messageId: string; value: "helpful" | "not_helpful" }
  | { type: "cooldown"; until: number | null };

const INITIAL: ChatState = {
  messages: [],
  status: "idle",
  openSource: null,
  cooldownUntil: null,
  showMore: {},
};

function reducer(state: ChatState, action: Action): ChatState {
  switch (action.type) {
    case "ask":
      return {
        ...state,
        messages: [...state.messages, { id: action.id, kind: "student", text: action.text }],
        status: "loading",
        // A passage open beside the previous answer would sit next to a
        // loading skeleton and read as though it belonged to the new question.
        openSource: null,
      };

    case "succeed":
      return { ...state, messages: [...state.messages, action.message], status: "idle" };

    case "fail":
      return {
        ...state,
        messages: [
          ...state.messages,
          {
            id: action.id,
            kind: "error",
            question: action.question,
            error: toErrorView(action.error),
          },
        ],
        status: "idle",
      };

    case "toggleSource": {
      const open = state.openSource;
      const same = open?.messageId === action.messageId && open.index === action.index;
      return {
        ...state,
        openSource: same ? null : { messageId: action.messageId, index: action.index },
      };
    }

    case "closeSource":
      return { ...state, openSource: null };

    case "showMore":
      return { ...state, showMore: { ...state.showMore, [action.messageId]: true } };

    case "feedback":
      return {
        ...state,
        messages: state.messages.map((message) =>
          message.id === action.messageId &&
          (message.kind === "answer" || message.kind === "fallback")
            ? { ...message, feedback: action.value }
            : message,
        ),
      };

    case "cooldown":
      return { ...state, cooldownUntil: action.until };

    default:
      return state;
  }
}

function newId(): string {
  return typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
    ? crypto.randomUUID()
    : `m-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

/**
 * Seconds left on the cooldown, re-read once a second while one is running.
 *
 * The count is derived from the deadline during render rather than stored, so
 * nothing is written on the transition into or out of a cooldown -- the
 * transition already re-renders. The interval exists only to force that render
 * once a second, which is also why it carries no state: a copy of the number
 * would be a second value that could disagree with the clock.
 */
function useCooldownSeconds(cooldownUntil: number | null): number | null {
  const [, setTick] = useState(0);

  useEffect(() => {
    if (cooldownUntil === null) return;
    const timer = window.setInterval(() => {
      setTick((value) => value + 1);
      // The last tick past the deadline is what renders "no cooldown", so the
      // interval is cleared after it rather than left running for the session.
      if (secondsUntil(cooldownUntil) <= 0) window.clearInterval(timer);
    }, 1000);
    return () => window.clearInterval(timer);
  }, [cooldownUntil]);

  if (cooldownUntil === null) return null;
  const seconds = secondsUntil(cooldownUntil);
  return seconds > 0 ? seconds : null;
}

export interface ChatThread {
  messages: Message[];
  status: "idle" | "loading";
  openSource: OpenSource | null;
  showMore: Record<string, boolean>;
  /** Seconds remaining on a rate limit, or null when there is none. */
  cooldownSeconds: number | null;
  send: (question: string, category: CategoryFilter | null) => Promise<void>;
  retry: (question: string) => Promise<void>;
  rate: (messageId: string, queryId: string, helpful: boolean) => void;
  toggleSource: (messageId: string, index: number) => void;
  closeSource: () => void;
  revealMore: (messageId: string) => void;
}

export function useChatThread(sessionId: string): ChatThread {
  const [state, dispatch] = useReducer(reducer, INITIAL);
  // Read inside the request without making the callback depend on it: every
  // send would otherwise get a new identity, and the composer's key handler
  // would be rebound mid-typing.
  //
  // Written in an effect rather than during render, which is what the hooks
  // rules require. Nothing is lost: `run` is only ever reached from an event
  // handler, and every one of those happens after this effect has run.
  const messagesRef = useRef(state.messages);
  useEffect(() => {
    messagesRef.current = state.messages;
  }, [state.messages]);

  const cooldownSeconds = useCooldownSeconds(state.cooldownUntil);

  const run = useCallback(
    async (question: string, category: CategoryFilter | null) => {
      const text = question.trim();
      if (!text) return;

      // Built from the thread *before* this question, because the backend
      // appends `question` to the search text itself and sending it twice would
      // weight the student's own words twice.
      const history = buildHistory(messagesRef.current);
      // Two ids: the question and its reply are two messages, and a shared id
      // would collide as a React key and make `find(m => m.id === …)` return the
      // question when the reply was meant -- which is exactly what the side
      // column does to resolve an open slip.
      const id = newId();
      const replyId = newId();
      dispatch({ type: "ask", id, text });

      try {
        const payload = await askQuestion({
          session_id: sessionId,
          question: text,
          history,
          // Omitted rather than sent as "all" when no chip is chosen, so the
          // backend's classifier decides the category. Sending "all" means
          // "filter nothing" and skips the classifier.
          ...(category ? { category } : {}),
        });
        dispatch({
          type: "succeed",
          message: payload.answered
            ? {
                id: replyId,
                kind: "answer",
                queryId: payload.query_id,
                text: payload.answer,
                citations: payload.citations,
                feedback: "idle",
              }
            : {
                id: replyId,
                kind: "fallback",
                queryId: payload.query_id,
                text: payload.answer,
                office: payload.office,
                feedback: "idle",
              },
        });
      } catch (error) {
        dispatch({ type: "fail", id: replyId, question: text, error });
        const view = toErrorView(error);
        if (view.cooldownSeconds !== null) {
          dispatch({ type: "cooldown", until: Date.now() + view.cooldownSeconds * 1000 });
        }
      }
    },
    [sessionId],
  );

  const send = useCallback(
    (question: string, category: CategoryFilter | null) => run(question, category),
    [run],
  );

  const retry = useCallback((question: string) => run(question, null), [run]);

  const rate = useCallback(
    (messageId: string, queryId: string, helpful: boolean) => {
      // Optimistic, and deliberately so. DESIGN_SYSTEM.md section 8 says the
      // confirmation appears after a tap and both buttons disable; there is no
      // failure copy for a lost rating, and re-enabling the buttons would
      // invite a student to rate a second time over something that already
      // happened. A rating that does not land is logged and dropped.
      dispatch({ type: "feedback", messageId, value: helpful ? "helpful" : "not_helpful" });
      void sendFeedback({
        query_id: queryId,
        session_id: sessionId,
        helpful,
      }).catch((error: unknown) => {
        console.warn("Feedback was not recorded.", error);
      });
    },
    [sessionId],
  );

  const toggleSource = useCallback((messageId: string, index: number) => {
    dispatch({ type: "toggleSource", messageId, index });
  }, []);

  const closeSource = useCallback(() => dispatch({ type: "closeSource" }), []);
  const revealMore = useCallback((messageId: string) => {
    dispatch({ type: "showMore", messageId });
  }, []);

  return {
    messages: state.messages,
    status: state.status,
    openSource: state.openSource,
    showMore: state.showMore,
    cooldownSeconds,
    send,
    retry,
    rate,
    toggleSource,
    closeSource,
    revealMore,
  };
}
