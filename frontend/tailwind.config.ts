import type { Config } from "tailwindcss";

// DESIGN_SYSTEM.md section 12's block, copied as given. The `fontSize` and
// `keyframes`/`animation` additions below are additions, not alterations --
// nothing in the spec's own block is changed.
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        paper: "#F1F3F2",
        surface: "#FFFFFF",
        ink: "#17262B",
        "ink-soft": "#4A5D63",
        rule: "#D5DCDA",
        marine: { DEFAULT: "#0E5A6B", deep: "#0A4350", wash: "#DCEBEE" },
        highlight: "#F6D84C",
        moss: "#2E7A55",
        brick: "#A83A2E",
        "amber-ink": "#7A5A00",
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
