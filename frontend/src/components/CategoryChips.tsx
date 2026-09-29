/**
 * DESIGN_SYSTEM.md section 8's category chips.
 *
 * `radiogroup` rather than a toolbar: the chips are mutually exclusive, and a
 * screen reader then announces "2 of 7" and the arrow-key behaviour comes with
 * the role instead of being reimplemented.
 *
 * The chip list is whatever `GET /categories` returns. Section 8 lists six and
 * the API serves seven -- it includes `general`, which the spec's list omits --
 * and rendering the payload means the two cannot drift apart.
 */
import { useRef } from "react";

import { CheckIcon } from "./Icons";
import type { CategoryChip, CategoryFilter } from "../lib/types";

interface CategoryChipsProps {
  categories: CategoryChip[];
  /** Null until a chip is tapped, which is not the same as "All": see below. */
  selected: CategoryFilter | null;
  onSelect: (value: CategoryFilter) => void;
  onAsk: (question: string) => void;
}

export function CategoryChips({ categories, selected, onSelect, onAsk }: CategoryChipsProps) {
  const listRef = useRef<HTMLDivElement>(null);

  const active = categories.find((chip) => chip.value === selected);

  const move = (delta: number): void => {
    const buttons = listRef.current?.querySelectorAll<HTMLButtonElement>("[role='radio']");
    if (!buttons || buttons.length === 0) return;
    const current = Array.from(buttons).findIndex((button) => button === document.activeElement);
    const next = (current + delta + buttons.length) % buttons.length;
    buttons[next]?.focus();
  };

  return (
    <div className="flex flex-col gap-2">
      <div
        ref={listRef}
        role="radiogroup"
        aria-label="Filter by category"
        className="flex gap-2 overflow-x-auto pb-1"
        onKeyDown={(event) => {
          if (event.key === "ArrowRight" || event.key === "ArrowDown") {
            event.preventDefault();
            move(1);
          } else if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
            event.preventDefault();
            move(-1);
          }
        }}
      >
        {categories.map((chip) => {
          const isSelected = chip.value === selected;
          return (
            <button
              key={chip.value}
              type="button"
              role="radio"
              aria-checked={isSelected}
              // Roving tabindex: one stop for the whole group, arrows move
              // within it, which is what the radiogroup role promises.
              tabIndex={isSelected || (selected === null && chip === categories[0]) ? 0 : -1}
              onClick={() => onSelect(chip.value)}
              className={`flex min-h-[44px] shrink-0 items-center gap-1.5 rounded-control border px-3 font-sans text-ui-label ${
                isSelected
                  ? "border-marine bg-marine-wash text-marine"
                  : "border-rule bg-surface text-ink hover:border-marine"
              }`}
            >
              {/* Section 8: a check icon, not colour alone. */}
              {isSelected && <CheckIcon />}
              {chip.label}
            </button>
          );
        })}
      </div>

      {active && active.starter_questions.length > 0 && (
        <ul className="flex flex-wrap gap-2">
          {active.starter_questions.map((question) => (
            <li key={question}>
              <button
                type="button"
                onClick={() => onAsk(question)}
                className="min-h-[44px] rounded-control border border-rule bg-surface px-3 text-left font-sans text-meta text-ink-soft hover:border-marine hover:text-marine"
              >
                {question}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
