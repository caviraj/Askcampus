import type { Config } from "tailwindcss";

// DESIGN_SYSTEM.md section 12's block, copied as given. The `fontSize` and
// `keyframes`/`animation` additions below are additions, not alterations --
// nothing in the spec's own block is changed.
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      // Every colour is now a custom property defined in `styles/tokens.css`,
      // which holds DESIGN_SYSTEM.md section 12's block verbatim plus the dark
      // theme. The rendered light values are identical to the hex literals this
      // replaced -- the indirection buys a theme switch and costs nothing.
      //
      // The trade it does cost: Tailwind cannot apply an alpha modifier to a
      // `var()`, so `bg-ink/40` and `bg-highlight/60` no longer work. Both were
      // replaced by named tokens (`scrim`, `highlight-wash`) in the same change.
      colors: {
        paper: "var(--paper)",
        surface: "var(--surface)",
        ink: { DEFAULT: "var(--ink)", soft: "var(--ink-soft)" },
        rule: "var(--rule)",
        marine: {
          DEFAULT: "var(--marine)",
          deep: "var(--marine-deep)",
          wash: "var(--marine-wash)",
        },
        "on-marine": "var(--on-marine)",
        "on-highlight": "var(--on-highlight)",
        highlight: "var(--highlight)",
        "highlight-wash": "var(--highlight-wash)",
        scrim: "var(--scrim)",
        moss: "var(--moss)",
        brick: "var(--brick)",
        "amber-ink": "var(--amber-ink)",
      },
      fontFamily: {
        serif: ['"Source Serif 4"', "Georgia", "serif"],
        sans: ['"IBM Plex Sans"', "system-ui", "sans-serif"],
      },
      borderRadius: { control: "4px", panel: "10px" },
      maxWidth: { measure: "65ch" },

      // Section 4's type scale. That table gives sizes and line heights as
      // prose rather than custom properties, so without this the components
      // would carry `text-[17px] leading-[27px]` -- the hardcoded values
      // section 12 exists to prevent. Weights stay in the class, because a
      // Tailwind v3 font-size tuple cannot express one.
      fontSize: {
        "page-title": ["28px", { lineHeight: "34px" }],
        "section-title": ["20px", { lineHeight: "28px" }],
        answer: ["17px", { lineHeight: "27px" }],
        ui: ["15px", { lineHeight: "22px" }],
        "ui-label": ["14px", { lineHeight: "20px" }],
        meta: ["13px", { lineHeight: "18px" }],
        "table-cell": ["14px", { lineHeight: "20px" }],
        // Section 7's expanded slip passage, and section 8's composer. The
        // composer is 16px on purpose: anything smaller makes iOS Safari zoom
        // the page when the textarea takes focus.
        "slip-passage": ["15px", { lineHeight: "24px" }],
        composer: ["16px", { lineHeight: "24px" }],
      },

      // Section 10: the rail draws, then the slips fade in.
      //
      // These start states live inside the keyframes and nowhere else. The
      // global `prefers-reduced-motion` rule in tokens.css disables every
      // animation; an `opacity-0` utility class on the slip would therefore
      // hide it *permanently* for anyone with reduced motion on, because the
      // animation that was meant to reveal it never runs. `backwards` fill
      // holds the start state through the delay and then releases the element
      // to its own natural opacity of 1, so with animations off it still shows.
      keyframes: {
        "rail-draw": { from: { transform: "scaleY(0)" }, to: { transform: "scaleY(1)" } },
        "slip-in": { from: { opacity: "0" }, to: { opacity: "1" } },
      },
      animation: {
        "rail-draw": "rail-draw 250ms ease-out",
        "slip-in": "slip-in 150ms ease-out 250ms backwards",
      },
    },
  },
  plugins: [],
} satisfies Config;
