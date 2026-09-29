/**
 * Inline SVG, `aria-hidden` throughout.
 *
 * Every icon here sits beside a text label, which is what DESIGN_SYSTEM.md
 * section 3 requires -- "status is never color only: always pair with a text
 * label and icon". So none of them carries a title or a role of its own; the
 * label does the talking and the icon is decoration.
 *
 * Sized in `em` rather than pixels so an icon tracks the type scale it sits in
 * without a size prop at every call site.
 */
import type { SVGProps } from "react";

type IconProps = SVGProps<SVGSVGElement>;

const BASE: IconProps = {
  viewBox: "0 0 16 16",
  width: "1em",
  height: "1em",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.5,
  strokeLinecap: "round",
  strokeLinejoin: "round",
  "aria-hidden": true,
  focusable: false,
};

export function DocumentIcon(props: IconProps) {
  return (
    <svg {...BASE} {...props}>
      <path d="M4 1.75h5L12.25 5v9.25H4z" />
      <path d="M9 1.75V5h3.25" />
      <path d="M6 8.5h4M6 11h4" />
    </svg>
  );
}

export function CheckIcon(props: IconProps) {
  return (
    <svg {...BASE} {...props}>
      <path d="M3 8.5 6.5 12 13 4.5" />
    </svg>
  );
}

export function SendIcon(props: IconProps) {
  return (
    <svg {...BASE} {...props}>
      <path d="M2 8 14 2 11 14 8 9z" />
      <path d="M8 9 14 2" />
    </svg>
  );
}

export function ChevronIcon(props: IconProps) {
  return (
    <svg {...BASE} {...props}>
      <path d="M4 6.5 8 10.5 12 6.5" />
    </svg>
  );
}

export function AlertIcon(props: IconProps) {
  return (
    <svg {...BASE} {...props}>
      <circle cx="8" cy="8" r="6.25" />
      <path d="M8 4.75v4M8 11.25h.01" />
    </svg>
  );
}
