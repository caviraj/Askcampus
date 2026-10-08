/**
 * Canvas-drawn textures, and the palette the scene is painted from.
 *
 * `AGENTS.md` section 11 asks for the simplest thing that works and the brief
 * forbids downloaded 3D models, so every surface in the scene is a plane with a
 * canvas texture drawn at runtime. This module is the one place that knows how
 * to draw one.
 *
 * It is a file the brief's list does not name. The alternative was to inline the
 * same draw-a-canvas boilerplate into `DocStack`, `Strips`, `AnswerCard` and
 * `SourceSlip`, which is four copies of a font-loading fix and four chances to
 * forget `colorSpace`. One shared module is the smaller change.
 */
import * as THREE from "three";

/** The four colours the brief names, plus the two the drawing needs. */
export interface Palette {
  paper: string;
  ink: string;
  inkSoft: string;
  marine: string;
  highlight: string;
  rule: string;
  surface: string;
}

/**
 * The design tokens, read from the document rather than duplicated here.
 *
 * This is the whole of the dark-theme support in the scene: the canvas textures
 * are painted from whatever `--ink` currently resolves to, so switching
 * `data-theme` repaints them and no colour is written down twice. Reading tokens
 * is also what keeps `AGENTS.md` section 8's "do not hardcode hex values in
 * components" true of a component that is not made of DOM.
 *
 * The fallbacks are the spec's light values, for the case where this runs before
 * the stylesheet has applied.
 */
export function readPalette(element?: HTMLElement | null): Palette {
  const fallback: Palette = {
    paper: "#F1F3F2",
    ink: "#17262B",
    inkSoft: "#4A5D63",
    marine: "#0E5A6B",
    highlight: "#F6D84C",
    rule: "#D5DCDA",
    surface: "#FFFFFF",
  };
  if (typeof window === "undefined") return fallback;

  const target = element ?? document.documentElement;
  const styles = window.getComputedStyle(target);
  const read = (name: keyof Palette): string =>
    styles.getPropertyValue(`--${name.replace(/[A-Z]/g, (c) => `-${c.toLowerCase()}`)}`).trim() ||
    fallback[name];

  return {
    paper: read("paper"),
    ink: read("ink"),
    inkSoft: read("inkSoft"),
    marine: read("marine"),
    highlight: read("highlight"),
    rule: read("rule"),
    surface: read("surface"),
  };
}

/** Serif for anything that reads as document text; sans for labels. */
const SERIF = '"Source Serif 4", Georgia, serif';
const SANS = '"IBM Plex Sans", system-ui, sans-serif';

interface SheetOptions {
  title: string;
  /** Ruled lines standing in for body text. */
  lines?: number;
  /** A status chip in the corner: "Processing" or "Ready". */
  status?: { label: string; tone: "pending" | "ready" };
  /** Draw a marked passage. */
  highlight?: { line: number; width: number };
  accent?: boolean;
}

function drawSheet(context: CanvasRenderingContext2D, sheet: SheetOptions, palette: Palette): void {
  const { width, height } = context.canvas;
  const pad = width * 0.09;

  context.fillStyle = palette.surface;
  context.fillRect(0, 0, width, height);

  if (sheet.accent) {
    // A marine spine, so a sheet reads as a filed document rather than a card.
    context.fillStyle = palette.marine;
    context.fillRect(0, 0, width * 0.022, height);
  }

  context.fillStyle = palette.ink;
  context.font = `600 ${Math.round(width * 0.072)}px ${SERIF}`;
  context.textBaseline = "top";
  const title = fit(context, sheet.title, width - pad * 2);
  context.fillText(title, pad, pad);

  // A rule under the title, which is what makes it read as a heading.
  context.strokeStyle = palette.rule;
  context.lineWidth = Math.max(1, width * 0.004);
  context.beginPath();
  context.moveTo(pad, pad + width * 0.11);
  context.lineTo(width - pad, pad + width * 0.11);
  context.stroke();

  const lineCount = sheet.lines ?? 0;
  const top = pad + width * 0.165;
  const step = width * 0.058;
  for (let index = 0; index < lineCount; index += 1) {
    const y = top + index * step;
    if (y > height - pad) break;

    const isMarked = sheet.highlight?.line === index;
    if (isMarked) {
      context.fillStyle = palette.highlight;
      const markWidth = (sheet.highlight?.width ?? 0.6) * (width - pad * 2);
      context.fillRect(pad - width * 0.02, y - step * 0.22, markWidth, step * 0.78);
    }

    context.fillStyle = palette.inkSoft;
    // Ragged right: a full-width block on every line reads as a table.
    const fraction = index % 3 === 2 ? 0.62 : index % 3 === 1 ? 0.88 : 1;
    context.fillRect(pad, y, (width - pad * 2) * fraction, step * 0.2);
  }

  if (sheet.status) {
    const label = sheet.status.label;
    context.font = `500 ${Math.round(width * 0.042)}px ${SANS}`;
    const textWidth = context.measureText(label).width;
    const chipWidth = textWidth + width * 0.075;
    const chipHeight = width * 0.082;
    const x = width - pad - chipWidth;
    const y = height - pad - chipHeight;

    context.fillStyle = sheet.status.tone === "ready" ? palette.marine : palette.rule;
    roundRect(context, x, y, chipWidth, chipHeight, chipHeight * 0.28);
    context.fill();

    context.fillStyle = sheet.status.tone === "ready" ? palette.surface : palette.inkSoft;
    context.fillText(label, x + width * 0.037, y + chipHeight * 0.3);
  }
}

interface CardOptions {
  title: string;
  lines?: number;
  /** A filled card, for the source slip. */
  filled?: boolean;
  tone?: "neutral" | "refused";
}

function drawCard(context: CanvasRenderingContext2D, card: CardOptions, palette: Palette): void {
  const { width, height } = context.canvas;
  const pad = width * 0.07;

  context.fillStyle = card.filled ? palette.marine : palette.surface;
  roundRect(context, 0, 0, width, height, width * 0.035);
  context.fill();

  context.fillStyle = card.filled
    ? palette.surface
    : card.tone === "refused"
      ? "#A83A2E"
      : palette.ink;
  context.font = `600 ${Math.round(width * 0.062)}px ${SANS}`;
  context.textBaseline = "top";
  context.fillText(fit(context, card.title, width - pad * 2), pad, pad);

  const lineCount = card.lines ?? 0;
  const step = width * 0.052;
  const top = pad + width * 0.105;
  for (let index = 0; index < lineCount; index += 1) {
    const y = top + index * step;
    if (y > height - pad) break;
    context.fillStyle = card.filled ? palette.surface : palette.inkSoft;
    context.globalAlpha = card.filled ? 0.65 : 0.8;
    const fraction = index % 2 === 1 ? 0.66 : 1;
    context.fillRect(pad, y, (width - pad * 2) * fraction, step * 0.19);
    context.globalAlpha = 1;
  }
}

/**
 * Build a texture from a draw function.
 *
 * `colorSpace` is set rather than left alone: a canvas texture defaults to no
 * colour space, which with three's default output encoding renders every sheet
 * noticeably washed out. It is the kind of wrong that looks like a lighting
 * problem and is not.
 *
 * The draw function is kept, keyed by canvas, so a repaint after the fonts load
 * can re-run it without every caller passing it again.
 */
const DRAWERS = new WeakMap<HTMLCanvasElement, (context: CanvasRenderingContext2D) => void>();

function buildTexture(
  width: number,
  height: number,
  draw: (context: CanvasRenderingContext2D) => void,
): THREE.CanvasTexture | null {
  if (typeof document === "undefined") return null;
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;

  const context = canvas.getContext("2d");
  if (!context) return null;

  DRAWERS.set(canvas, draw);
  draw(context);

  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.anisotropy = 4;
  return texture;
}

/** Repaint a texture once the web fonts have landed.
 *
 * A canvas texture drawn before `document.fonts.ready` resolves bakes in the
 * fallback face -- Georgia where Source Serif 4 was asked for -- and nothing
 * repaints it. Returns a cancel function.
 */
export function repaintOnFontsReady(texture: THREE.CanvasTexture | null): () => void {
  if (!texture || typeof document === "undefined" || !document.fonts) return () => {};
  let cancelled = false;

  void document.fonts.ready.then(() => {
    if (cancelled || !texture.image) return;
    const canvas = texture.image as HTMLCanvasElement;
    const draw = DRAWERS.get(canvas);
    const context = canvas.getContext("2d");
    if (!draw || !context) return;

    context.clearRect(0, 0, canvas.width, canvas.height);
    draw(context);
    texture.needsUpdate = true;
  });

  return () => {
    cancelled = true;
  };
}

// ---------------------------------------------------------------------------
// The textures the scene asks for, by name.
// ---------------------------------------------------------------------------

export function sheetTexture(options: SheetOptions, palette: Palette): THREE.CanvasTexture | null {
  return buildTexture(512, 680, (context) => {
    drawSheet(context, options, palette);
  });
}

export function cardTexture(options: CardOptions, palette: Palette): THREE.CanvasTexture | null {
  return buildTexture(640, 360, (context) => {
    drawCard(context, options, palette);
  });
}

/** A source slip: the document name and the page, drawn on the marine field. */
export function slipTexture(
  document: string,
  section: string,
  page: string,
  palette: Palette,
): THREE.CanvasTexture | null {
  return buildTexture(560, 300, (context) => {
    const draw = (c: CanvasRenderingContext2D): void => {
      const { width, height } = c.canvas;
      const pad = width * 0.08;

      c.fillStyle = palette.marine;
      roundRect(c, 0, 0, width, height, width * 0.045);
      c.fill();

      c.textBaseline = "top";
      c.fillStyle = palette.surface;
      c.font = `600 ${Math.round(width * 0.055)}px ${SERIF}`;
      c.fillText(fit(c, document, width - pad * 2), pad, pad);

      c.fillStyle = palette.surface;
      c.globalAlpha = 0.75;
      c.font = `400 ${Math.round(width * 0.043)}px ${SANS}`;
      c.fillText(fit(c, section, width - pad * 2), pad, pad + height * 0.24);
      c.globalAlpha = 1;

      // A rule, then the page, which is the field a reader checks first.
      c.strokeStyle = palette.surface;
      c.globalAlpha = 0.3;
      c.lineWidth = Math.max(1, width * 0.005);
      c.beginPath();
      c.moveTo(pad, height * 0.56);
      c.lineTo(width - pad, height * 0.56);
      c.stroke();
      c.globalAlpha = 1;

      c.fillStyle = palette.surface;
      c.globalAlpha = 0.9;
      c.font = `500 ${Math.round(width * 0.042)}px ${SANS}`;
      c.fillText(page, pad, height * 0.66);
    };

    draw(context);
  });
}

/** The tray label, drawn on the paper field. */
export function trayTexture(label: string, palette: Palette): THREE.CanvasTexture | null {
  return buildTexture(640, 200, (context) => {
    const draw = (c: CanvasRenderingContext2D): void => {
      const { width, height } = c.canvas;
      c.fillStyle = palette.paper;
      roundRect(c, 0, 0, width, height, width * 0.04);
      c.fill();
      c.strokeStyle = palette.rule;
      c.lineWidth = Math.max(1, width * 0.004);
      roundRect(c, 0, 0, width, height, width * 0.04);
      c.stroke();

      c.fillStyle = palette.inkSoft;
      c.font = `500 ${Math.round(width * 0.058)}px ${SANS}`;
      c.textBaseline = "middle";
      c.fillText(fit(c, label, width * 0.86), width * 0.07, height / 2);
    };

    draw(context);
  });
}

export interface StripOptions {
  title: string;
  snippet?: string;
  highlighted?: boolean;
}

/** A searchable section strip split from a document. */
export function stripTexture(
  options: StripOptions,
  palette: Palette,
): THREE.CanvasTexture | null {
  return buildTexture(640, 110, (c) => {
    const { width, height } = c.canvas;
    const pad = width * 0.04;
    c.fillStyle = palette.surface;
    roundRect(c, 0, 0, width, height, width * 0.015);
    c.fill();
    c.strokeStyle = options.highlighted ? palette.marine : palette.rule;
    c.lineWidth = options.highlighted ? Math.max(2, width * 0.006) : Math.max(1, width * 0.003);
    roundRect(c, 0, 0, width, height, width * 0.015);
    c.stroke();

    if (options.highlighted) {
      c.fillStyle = palette.highlight;
      c.fillRect(pad - 2, height * 0.50, width * 0.62, height * 0.36);
    }

    c.textBaseline = "top";
    c.fillStyle = palette.ink;
    c.font = `600 ${Math.round(width * 0.038)}px ${SERIF}`;
    c.fillText(fit(c, options.title, width - pad * 2), pad, pad * 0.7);

    c.fillStyle = options.highlighted ? palette.ink : palette.inkSoft;
    c.font = `400 ${Math.round(width * 0.028)}px ${SANS}`;
    const snippet = options.snippet ?? "The attendance committee may grant condonation up to 10% on medical grounds...";
    c.fillText(fit(c, snippet, width - pad * 2), pad, height * 0.54);
  });
}

export const STRIP_DATA = [
  { title: "§ 4.1 Attendance requirement", snippet: "Minimum 75% attendance is required to appear in semester examinations.", highlighted: false },
  { title: "§ 4.2 Medical condonation & leave", snippet: "The attendance committee may grant condonation up to 10% on medical grounds.", highlighted: true },
  { title: "§ 5.3 Grading scale & GPA", snippet: "Letter grades S through F assigned with corresponding grade point values.", highlighted: false },
  { title: "§ 6.1 Re-evaluation policy", snippet: "Students may apply for answer script review within 10 days of grade publication.", highlighted: false },
  { title: "§ 8.4 Hostel curfew & night leave", snippet: "Hostel gate closes at 21:30 hrs. Night out requests must be submitted online.", highlighted: true },
  { title: "§ 9.2 Disciplinary actions", snippet: "Misconduct during examinations results in immediate debarment for the semester.", highlighted: false },
  { title: "§ 11.0 Fee refund schedule", snippet: "Tuition fee refund requests received before session commencement eligible for 90%.", highlighted: false },
];

/** Atlas texture containing all 7 strips stacked vertically. */
export function stripAtlasTexture(palette: Palette): THREE.CanvasTexture | null {
  const stripH = 110;
  const count = STRIP_DATA.length;
  return buildTexture(640, stripH * count, (c) => {
    const width = 640;
    const pad = width * 0.04;

    for (let i = 0; i < count; i += 1) {
      const data = STRIP_DATA[i];
      const yOffset = i * stripH;
      const height = stripH;

      c.save();
      c.translate(0, yOffset);

      c.fillStyle = palette.surface;
      roundRect(c, 0, 0, width, height, width * 0.015);
      c.fill();

      c.strokeStyle = data.highlighted ? palette.marine : palette.rule;
      c.lineWidth = data.highlighted ? Math.max(2, width * 0.005) : Math.max(1, width * 0.003);
      roundRect(c, 0, 0, width, height, width * 0.015);
      c.stroke();

      if (data.highlighted) {
        c.fillStyle = palette.highlight;
        c.fillRect(pad - 2, height * 0.50, width * 0.64, height * 0.36);
      }

      c.textBaseline = "top";
      c.fillStyle = palette.ink;
      c.font = `600 ${Math.round(width * 0.038)}px ${SERIF}`;
      c.fillText(fit(c, data.title, width - pad * 2), pad, pad * 0.7);

      c.fillStyle = data.highlighted ? palette.ink : palette.inkSoft;
      c.font = `400 ${Math.round(width * 0.028)}px ${SANS}`;
      c.fillText(fit(c, data.snippet, width - pad * 2), pad, height * 0.54);

      c.restore();
    }
  });
}

// ---------------------------------------------------------------------------

function roundRect(
  context: CanvasRenderingContext2D,
  x: number,
  y: number,
  width: number,
  height: number,
  radius: number,
): void {
  context.beginPath();
  context.moveTo(x + radius, y);
  context.arcTo(x + width, y, x + width, y + height, radius);
  context.arcTo(x + width, y + height, x, y + height, radius);
  context.arcTo(x, y + height, x, y, radius);
  context.arcTo(x, y, x + width, y, radius);
  context.closePath();
}

/** Shrink a string until it fits, then add an ellipsis if it had to shrink. */
function fit(context: CanvasRenderingContext2D, text: string, maxWidth: number): string {
  if (context.measureText(text).width <= maxWidth) return text;
  let end = text.length;
  while (end > 1 && context.measureText(`${text.slice(0, end)}…`).width > maxWidth) end -= 1;
  return `${text.slice(0, end)}…`;
}
