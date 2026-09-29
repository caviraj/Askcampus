# Design System — CampusAsk (AI-PS-07)

## 1. Design Intent

**Subject:** a college helpdesk that answers from official documents.
**Audience:** students on phones between classes; staff on laptops managing documents.
**Primary job:** make a student trust the answer within two seconds, by showing where it came from.

**Concept: the reading room.** The interface borrows from a library catalogue: quiet surfaces, reference-book typography, and a "source slip" attached to every answer. The source slip is the one memorable element. Everything else stays calm and plain so the evidence is the visual focus.

## 2. Principles

1. **Evidence beside the answer.** A citation is never hidden in a footer. It sits next to the text it supports.
2. **Say what happened.** Errors and empty states explain the situation and the next action. No apologies, no cleverness.
3. **One accent for meaning.** Highlight yellow means "this is the source passage". It is used for nothing else.
4. **Phone first.** Single column, thumb-reachable input, no hover-only information.
5. **Quiet motion.** Motion only responds to a user action (sending, expanding a source).

## 3. Color

Cool, mineral base. Deliberately not cream and not terracotta.

| Token | Hex | Use |
|---|---|---|
| `--paper` | `#F1F3F2` | App background |
| `--surface` | `#FFFFFF` | Message and panel background |
| `--ink` | `#17262B` | Primary text |
| `--ink-soft` | `#4A5D63` | Secondary text (contrast 6.4:1 on paper) |
| `--rule` | `#D5DCDA` | Borders and dividers |
| `--marine` | `#0E5A6B` | Primary actions, links, focus ring |
| `--marine-deep` | `#0A4350` | Pressed and hover for primary |
| `--marine-wash` | `#DCEBEE` | Student message background, selected rows |
| `--highlight` | `#F6D84C` | Source passage highlight only |
| `--moss` | `#2E7A55` | Ready, success |
| `--brick` | `#A83A2E` | Failed, error |
| `--amber-ink` | `#7A5A00` | Processing, warning text |

Rules:
- Body text on `--surface` or `--paper` uses `--ink`. Never place `--ink-soft` below 14 px.
- Status is never color only: always pair with a text label and icon.
- Dark mode is out of scope for v1. Tokens are named so it can be added later.

## 4. Typography

| Role | Family | Fallback |
|---|---|---|
| Answers, page titles, document titles | **Source Serif 4** | Georgia, serif |
| Interface, inputs, tables, buttons | **IBM Plex Sans** | system-ui, sans-serif |

Serif is used for anything the student reads as content. Sans is used for anything the student operates.

| Style | Font | Size / line height | Weight |
|---|---|---|---|
| Page title | Source Serif 4 | 28 / 34 | 600 |
| Section title | Source Serif 4 | 20 / 28 | 600 |
| Answer text | Source Serif 4 | 17 / 27 | 400 |
| UI body | IBM Plex Sans | 15 / 22 | 400 |
| UI label | IBM Plex Sans | 14 / 20 | 500 |
| Small / meta | IBM Plex Sans | 13 / 18 | 400 |
| Table cell | IBM Plex Sans | 14 / 20 | 400 |

Rules:
- Answer line length is capped at 65 characters (`max-width: 65ch`).
- Sentence case everywhere. No all-caps labels.
- Numbers in tables use `font-variant-numeric: tabular-nums`.

## 5. Spacing, Shape, Elevation

- Spacing scale (px): 4, 8, 12, 16, 24, 32, 48. Base unit 4.
- Radius: **4 px** for inputs, buttons, and chips; **10 px** for the message panel only. Do not use one radius everywhere.
- Borders over shadows: panels use a 1 px `--rule` border. The only shadow is on the floating chat input on mobile (`0 -1px 0 var(--rule)`).
- Touch targets are at least 44 × 44 px.

## 6. Layout

### Student chat (mobile first)

```
┌──────────────────────────┐
│ CampusAsk        [Ask staff]│  header, 56 px
├──────────────────────────┤
│  Answer thread            │
│                           │
│        ┌─────────────────┐│
│        │ You: when does… ││  student, right aligned
│        └─────────────────┘│
│ ┌──┬────────────────────┐ │
│ │▌ │ Registration closes │ │  answer with source rail
│ │▌ │ on 12 December.     │ │
│ │▌ │ [Exam Schedule · p2]│ │  source slip
│ └──┴────────────────────┘ │
├──────────────────────────┤
│ [Exams][Admissions][…]    │  category chips (scroll)
│ [ Ask a question…    ][→] │  input, sticky
└──────────────────────────┘
```

- Answers are left aligned, student messages right aligned.
- On screens ≥ 1024 px: a centered 720 px thread column, with the source panel opening as a 320 px side column instead of an inline expansion.

### Admin (desktop first)

```
┌────────┬───────────────────────────────┐
│ Docs   │ Page title              [Upload]│
│ Queries│ ┌─────────────────────────────┐ │
│ Unans. │ │ Table / cards               │ │
│ FAQs   │ └─────────────────────────────┘ │
└────────┴───────────────────────────────┘
```

- Left navigation 208 px, content max width 1100 px, left aligned.
- Below 768 px the navigation becomes a top tab bar.

## 7. Signature Component: Source Slip

The source slip is a compact catalogue card attached to the answer.

**Collapsed**
- Height 40 px, 4 px radius, 1 px `--rule` border, white background.
- Content: document icon, document title (truncate), page or section, category tag.
- A 3 px `--marine` bar runs down the left edge of the *whole answer block*, joining the answer to its slips.

**Expanded** (tap or Enter)
- Shows the retrieved passage in Source Serif 4, 15 / 24, with the exact supporting sentence marked by `--highlight` at 60% opacity.
- Meta line: document title, page, section, last updated date.
- Action: "Open document" (admin-approved public link if available).

**Rules**
- One slip per cited chunk, maximum 3 visible, "Show 2 more sources" for the rest.
- Slip label format: `Exam Schedule Nov–Dec 2026, page 2`. Never abbreviate the title beyond truncation.
- Expansion animates height in 150 ms. Respect `prefers-reduced-motion` (no animation).

## 8. Components

### Buttons
| Type | Style | Use |
|---|---|---|
| Primary | `--marine` fill, white text, 4 px radius, 44 px height | Send, Upload, Save changes |
| Secondary | White fill, `--marine` text, 1 px `--marine` border | Cancel, Reprocess |
| Quiet | No border, `--marine` text | Show more sources |
| Danger | `--brick` text and border | Delete document |

States: hover uses `--marine-deep`; focus shows a 2 px `--marine` ring with 2 px offset; disabled at 45% opacity with `aria-disabled`.

### Chat input
- Multi-line textarea, auto-grow to 4 lines, 16 px text (prevents zoom on iOS).
- Send button is disabled while a response is loading. Enter sends, Shift+Enter adds a line.
- Placeholder: "Ask about exams, admissions, departments, events…"

### Category chips
- Six chips: Examinations, Admissions, Departments, Events, Academic processes, All.
- Selected chip: `--marine-wash` fill, `--marine` text, and a check icon (not color only).
- Tapping a chip filters retrieval and shows three starter questions.

### Message types
| Type | Appearance |
|---|---|
| Student | `--marine-wash` background, 10 px radius, right aligned, max 80% width |
| Answer | White background, `--rule` border, marine left rail, serif text |
| Fallback | White background, `--brick` left rail, sans text, "Ask the office" action |
| Loading | Three-line skeleton in `--rule`, no spinner |

### Feedback
Two text buttons under each answer: "Helpful" and "Not helpful". After a tap, show "Thanks for the feedback" and disable both.

### Status badges (admin)
| Status | Label | Color | Icon |
|---|---|---|---|
| uploaded | Uploaded | `--ink-soft` | clock |
| processing | Processing | `--amber-ink` | loop |
| ready | Ready | `--moss` | check |
| failed | Failed | `--brick` | alert |

Failed rows show the error message inline and a "Reprocess" button.

### Tables (admin)
- Sticky header, 48 px rows, zebra off, 1 px row dividers.
- Sortable columns show a direction arrow and `aria-sort`.
- On mobile each row becomes a stacked card.

### Upload dialog
Fields: file (drag and drop plus button), title, category (required), academic year, department. Validation messages appear under the field. Progress is a determinate bar with the current step named: "Uploading", "Extracting text", "Creating searchable sections".

### Dashboard cards
Four number cards (Questions, Answered, Unanswered, Top category) in a row on desktop, 2 × 2 on mobile. Each shows the value, a plain label, and the change from the previous 7 days. Below: a category bar chart and the unanswered queue preview.

## 9. Content and Voice

Plain verbs, sentence case, active voice. The interface speaks as a helpdesk, not as a person. Errors do not apologize.

| Situation | Copy |
|---|---|
| Empty chat | "Ask about exams, admissions, departments, events, or academic processes." |
| Fallback | "This is not in the college documents I have. Try the office below, or ask staff." |
| Fallback (contact known) | "This is not in the documents I have. The Examination Cell handles this." |
| Network error | "The answer could not be loaded. Check your connection and send the question again." |
| Rate limited | "Too many questions in a short time. Wait a minute and ask again." |
| Empty documents (admin) | "No documents yet. Upload an academic calendar or exam schedule to begin." |
| Empty unanswered (admin) | "Every question so far has an answer." |
| Upload success | "Uploaded. Processing has started." |
| Processing done | "Ready. Students can now get answers from this document." |
| Upload failed | "The file could not be read. Upload a text-based PDF, DOCX, or TXT file under 20 MB." |
| Delete confirm | "Delete this document? Its sections are removed and answers can no longer cite it." |

Action names stay consistent: the button says "Upload", the toast says "Uploaded". The button says "Delete", the toast says "Deleted".

## 10. Motion

- No entrance animations on load or on scroll.
- One orchestrated moment: when an answer arrives, the marine rail draws top to bottom over 250 ms, then the slips fade in. This links the answer to its evidence.
- Expanding a slip, opening a dialog, and toast appearance are 150 ms responses to user action.
- All motion is disabled under `prefers-reduced-motion`.

## 11. Accessibility

- WCAG 2.1 AA. Text contrast at least 4.5:1, UI components at least 3:1.
- Visible focus ring on every interactive element.
- Chat thread is an `aria-live="polite"` region; the loading state announces "Finding an answer".
- Source slips are buttons with `aria-expanded`.
- Category chips use `role="radiogroup"`.
- Full keyboard operation of chat and admin flows.
- Language attribute set on `<html>`; layout tested at 200% zoom.

## 12. Design Tokens

### `tokens.css`

```css
:root {
  --paper: #F1F3F2;
  --surface: #FFFFFF;
  --ink: #17262B;
  --ink-soft: #4A5D63;
  --rule: #D5DCDA;
  --marine: #0E5A6B;
  --marine-deep: #0A4350;
  --marine-wash: #DCEBEE;
  --highlight: #F6D84C;
  --moss: #2E7A55;
  --brick: #A83A2E;
  --amber-ink: #7A5A00;

  --font-serif: "Source Serif 4", Georgia, serif;
  --font-sans: "IBM Plex Sans", system-ui, sans-serif;

  --radius-control: 4px;
  --radius-panel: 10px;

  --space-1: 4px;  --space-2: 8px;  --space-3: 12px;
  --space-4: 16px; --space-5: 24px; --space-6: 32px; --space-7: 48px;

  --measure: 65ch;
}

@media (prefers-reduced-motion: reduce) {
  * { animation: none !important; transition: none !important; }
}
```

### `tailwind.config.ts` (extend)

```ts
export default {
  theme: {
    extend: {
      colors: {
        paper: "#F1F3F2", surface: "#FFFFFF", ink: "#17262B",
        "ink-soft": "#4A5D63", rule: "#D5DCDA",
        marine: { DEFAULT: "#0E5A6B", deep: "#0A4350", wash: "#DCEBEE" },
        highlight: "#F6D84C", moss: "#2E7A55", brick: "#A83A2E", "amber-ink": "#7A5A00",
      },
      fontFamily: {
        serif: ['"Source Serif 4"', "Georgia", "serif"],
        sans: ['"IBM Plex Sans"', "system-ui", "sans-serif"],
      },
      borderRadius: { control: "4px", panel: "10px" },
      maxWidth: { measure: "65ch" },
    },
  },
};
```

Load fonts with `font-display: swap`, weights: Source Serif 4 (400, 600), IBM Plex Sans (400, 500).

## 13. Do and Do Not

| Do | Do not |
|---|---|
| Keep the source slip next to every answer | Put citations in a footer or tooltip |
| Use highlight yellow only on source passages | Use yellow for warnings or decoration |
| Use two radii with clear roles | Round everything equally |
| Explain errors with a next step | Write "Oops" or "Something went wrong" |
| Pair status color with text and icon | Rely on color alone |
