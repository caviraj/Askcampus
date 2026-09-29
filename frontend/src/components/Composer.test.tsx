import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { Composer } from "./Composer";
import { COPY, MAX_QUESTION_CHARS } from "../lib/constants";

function setup(props: Partial<Parameters<typeof Composer>[0]> = {}) {
  const onSend = vi.fn();
  render(<Composer loading={false} cooldownSeconds={null} onSend={onSend} {...props} />);
  return { onSend, textarea: screen.getByRole("textbox") };
}

describe("Composer", () => {
  it("sends on Enter and clears the box", async () => {
    const { onSend, textarea } = setup();
    await userEvent.type(textarea, "When are marks published?{Enter}");

    expect(onSend).toHaveBeenCalledWith("When are marks published?");
    expect(textarea).toHaveValue("");
  });

  it("adds a line on Shift+Enter instead of sending", async () => {
    const { onSend, textarea } = setup();
    await userEvent.type(textarea, "first line{Shift>}{Enter}{/Shift}second line");

    expect(onSend).not.toHaveBeenCalled();
    expect(textarea).toHaveValue("first line\nsecond line");
  });

  it("sends with the button as well as the keyboard", async () => {
    const { onSend, textarea } = setup();
    await userEvent.type(textarea, "Hello");
    await userEvent.click(screen.getByRole("button", { name: /send/i }));
    expect(onSend).toHaveBeenCalledWith("Hello");
  });

  it("refuses an empty question", async () => {
    const { onSend, textarea } = setup();
    await userEvent.click(screen.getByRole("button", { name: /send/i }));
    await userEvent.type(textarea, "   {Enter}");
    expect(onSend).not.toHaveBeenCalled();
  });

  it("trims what it sends", async () => {
    const { onSend, textarea } = setup();
    await userEvent.type(textarea, "  spaced out  {Enter}");
    expect(onSend).toHaveBeenCalledWith("spaced out");
  });

  it("cannot send while an answer is loading", async () => {
    const { onSend, textarea } = setup({ loading: true });
    expect(textarea).toBeDisabled();
    expect(screen.getByRole("button", { name: /send/i })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: /send/i }));
    expect(onSend).not.toHaveBeenCalled();
  });

  it("holds the composer for the length of a rate limit", async () => {
    const { onSend, textarea } = setup({ cooldownSeconds: 42 });
    expect(textarea).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent("You can ask again in 42 seconds.");
    await userEvent.click(screen.getByRole("button", { name: /send/i }));
    expect(onSend).not.toHaveBeenCalled();
  });

  it("stops at the backend's question limit rather than letting a 422 happen", () => {
    const { textarea } = setup();
    expect(textarea).toHaveAttribute("maxlength", String(MAX_QUESTION_CHARS));
  });

  it("says what the box is for", () => {
    const { textarea } = setup();
    expect(textarea).toHaveAttribute("placeholder", COPY.composerPlaceholder);
    expect(screen.getByLabelText("Your question")).toBe(textarea);
  });
});
