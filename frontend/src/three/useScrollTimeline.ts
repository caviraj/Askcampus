/**
 * The scroll timeline: one number, 0 to 1, that the scene reads every frame.
 *
 * Two decisions worth stating, because both are about performance rather than
 * about animation:
 *
 * - **The progress lives in a ref, not in state.** A scroll produces a value on
 *   every frame; putting that in `useState` would re-render the whole React tree
 *   sixty times a second to move some meshes. The scene reads the ref inside
 *   `useFrame` instead, so a scroll costs one number write. Only the *caption
 *   index* is state, because it changes six times over the whole page.
 * - **Smoothing happens in the scene, not in gsap.** `scrub: 1` would ask gsap
 *   to tween the value for us, which means a second animation clock running
 *   alongside the render loop. Damping toward the raw value in `useFrame` is the
 *   same feel, tied to the renderer's own clock, and it is what makes the story
 *   play backwards as smoothly as forwards -- a scrubbed tween already in flight
 *   has to be reversed, whereas a damped value simply has a new target.
 */
import { useEffect, useRef, useState } from "react";
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";

/** One step of the story. `caption` is the only text a visitor must read. */
export interface SceneStep {
  id: string;
  caption: string;
}

/**
 * The six steps, in the order the brief gives them.
 *
 * Captions are sentence case and under twelve words. They carry the whole
 * meaning of the scene: the canvas is `aria-hidden`, so a visitor who never sees
 * it -- reduced motion, no WebGL, a screen reader -- reads the story here and
 * loses nothing.
 */
export const SCENE_STEPS: readonly SceneStep[] = [
  { id: "stack", caption: "Your college's documents sit in one place." },
  { id: "upload", caption: "Upload a new one. It becomes searchable when it is ready." },
  { id: "split", caption: "Each document is split into the sections it already has." },
  { id: "search", caption: "A question finds the sections that hold its answer." },
  { id: "answer", caption: "The answer cites the passage it came from." },
  { id: "fallback", caption: "Nothing in the documents? It says so, and staff see it." },
];

export const FIRST_STEP = 0;
export const LAST_STEP = SCENE_STEPS.length - 1;

/** Hold a value inside 0 and 1. */
export function clamp01(value: number): number {
  return value < 0 ? 0 : value > 1 ? 1 : value;
}

/**
 * How far into a step the story is, from 0 to 1.
 *
 * The whole animation is expressed as these: nothing has a duration, everything
 * has a *position in the story*. That is what makes it reversible -- given any
 * scroll position the scene can be built from scratch, so scrolling up is not a
 * rewind of playback but the same pure function of a smaller number.
 */
export function phase(step: number, from: number, to: number): number {
  if (to === from) return step >= to ? 1 : 0;
  return clamp01((step - from) / (to - from));
}

/** Linear interpolation. The one place a position is actually computed. */
export function mix(from: number, to: number, t: number): number {
  return from + (to - from) * t;
}

/** Smoothstep: eases both ends, so nothing starts or stops abruptly. */
export function easeInOut(t: number): number {
  const clamped = clamp01(t);
  return clamped * clamped * (3 - 2 * clamped);
}

/** Ease and mix in one call, which is what most of the scene wants. */
export function mixEased(from: number, to: number, t: number): number {
  return mix(from, to, easeInOut(t));
}

/** Which step a raw 0-1 progress sits in. */
export function stepFromProgress(progress: number): number {
  const scaled = clamp01(progress) * LAST_STEP;
  return Math.min(LAST_STEP, Math.max(FIRST_STEP, Math.round(scaled)));
}

/**
 * How much scroll the pinned section consumes, in viewport heights.
 *
 * Roughly half a screen per step: enough that each caption is readable while it
 * is on screen, short enough that the story does not feel like a hostage
 * situation. The skill's guidance is explicit that pinning more than a section
 * or two fights native scrolling, so this pins exactly one.
 */
const SCROLL_LENGTH_VH = 3.4;

export interface ScrollTimeline {
  /** Attach to the section that gets pinned. */
  sectionRef: React.RefObject<HTMLDivElement | null>;
  /** Raw scroll progress, 0 to 1. Read this inside `useFrame`, never in render. */
  progress: React.RefObject<number>;
  /** The step whose caption should be showing. */
  step: number;
  /** Move to a step directly -- used by the caption list's own controls. */
  goToStep: (index: number) => void;
}

/**
 * Drive the story from scroll position.
 *
 * `enabled` is false under reduced motion, and then nothing is pinned, no
 * listener is attached, and the caller renders the static fallback instead.
 * The hook is still called -- hooks cannot be conditional -- so it must be
 * inert rather than merely unused.
 */
export function useScrollTimeline(enabled: boolean): ScrollTimeline {
  const sectionRef = useRef<HTMLDivElement | null>(null);
  const progress = useRef(0);
  const [step, setStep] = useState(FIRST_STEP);

  useEffect(() => {
    const section = sectionRef.current;
    if (!enabled || !section) return;

    // Registered once. `registerPlugin` is idempotent, but doing it per
    // ScrollTrigger is the habit that ends in a duplicate-plugin warning.
    gsap.registerPlugin(ScrollTrigger);

    const trigger = ScrollTrigger.create({
      trigger: section,
      start: "top top",
      end: () => `+=${window.innerHeight * SCROLL_LENGTH_VH}`,
      pin: true,
      // Pins a little early so the section is settled before the first frame of
      // the story, rather than arriving mid-step during a fast flick.
      anticipatePin: 1,
      onUpdate: (self) => {
        progress.current = self.progress;
        const next = stepFromProgress(self.progress);
        setStep((current) => (current === next ? current : next));
      },
    });

    // A pinned section's height depends on the web fonts being loaded, because
    // the captions set the section's own height. Without this refresh, the pin
    // is measured against Georgia and the story drifts by a step near the end.
    let cancelled = false;
    if (typeof document !== "undefined" && document.fonts) {
      void document.fonts.ready.then(() => {
        if (!cancelled) ScrollTrigger.refresh();
      });
    }

    return () => {
      cancelled = true;
      trigger.kill();
    };
  }, [enabled]);

  /** Jump to a step by scrolling to the offset that produces it. */
  const goToStep = (index: number): void => {
    const section = sectionRef.current;
    if (!section || !enabled) return;
    const target = Math.min(LAST_STEP, Math.max(FIRST_STEP, index));
    const travel = window.innerHeight * SCROLL_LENGTH_VH;
    const top = section.getBoundingClientRect().top + window.scrollY;
    window.scrollTo({
      top: top + (travel * target) / LAST_STEP,
      behavior: prefersReducedMotion() ? "auto" : "smooth",
    });
  };

  return { sectionRef, progress, step, goToStep };
}

function prefersReducedMotion(): boolean {
  return typeof window !== "undefined"
    ? window.matchMedia("(prefers-reduced-motion: reduce)").matches
    : false;
}
