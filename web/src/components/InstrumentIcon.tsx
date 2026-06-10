import type { JSX } from "react";

// Compact, schematic line icons for each brass/woodwind instrument so every
// wind selection carries its own accurate glyph (Unicode only has 🎺/🎷/🪈).
// Stroke art on a 0..24 grid, currentColor — reads at ~16–20px.

export type IconKind =
  | "trumpet" | "trombone" | "tuba" | "horn"
  | "sax" | "flute" | "clarinet" | "oboe" | "bassoon";

// Order matters: more specific names first (e.g. "baritone sax" must hit sax
// before "baritone horn" hits tuba; "english horn" must hit oboe before horn).
export function iconKindFor(name: string): IconKind {
  const n = name.toLowerCase();
  if (/sax/.test(n)) return "sax";
  if (/trombone/.test(n)) return "trombone";
  if (/tuba|sousaphone|euphonium|baritone\s*horn/.test(n)) return "tuba";
  if (/english\s*horn|cor\s*anglais|oboe/.test(n)) return "oboe";
  if (/french\s*horn|\bhorn\b/.test(n)) return "horn";
  if (/trumpet|cornet|flugel/.test(n)) return "trumpet";
  if (/clarinet/.test(n)) return "clarinet";
  if (/bassoon/.test(n)) return "bassoon";
  if (/picc|flute|recorder|fife|whistle/.test(n)) return "flute";
  return "trumpet";
}

const GLYPH: Record<IconKind, JSX.Element> = {
  // Horizontal body, bell flaring right, three valve stems on top.
  trumpet: (<>
    <path d="M3 12h11" />
    <path d="M14 10l6-3v10l-6-3z" />
    <circle cx="2.6" cy="12" r="1.1" />
    <path d="M6 12V8.5M9 12V8.5M12 12V8.5" />
  </>),
  // Bell right, long tube, U-slide on the left.
  trombone: (<>
    <path d="M21 7l-5 2.5v5L21 17" />
    <path d="M16 12H6" />
    <path d="M6 9.5h-2v5h2" />
    <path d="M6 12H4" />
  </>),
  // Upward bell (wide at top), body into a coil, mouthpipe stub.
  tuba: (<>
    <path d="M8 4h8l-1.5 5h-5z" />
    <path d="M12 9v5" />
    <circle cx="12" cy="17" r="3.2" />
    <path d="M15.2 16l3-1" />
  </>),
  // Coiled ring with a bell flaring lower-right.
  horn: (<>
    <circle cx="10.5" cy="11.5" r="6.5" />
    <path d="M16 15.5l2.5 2 1-3z" />
    <circle cx="4.4" cy="8" r="1" />
  </>),
  // Hooked body: neck down, hook at the bottom, bell flaring up-right + keys.
  sax: (<>
    <path d="M10 3v7a6 6 0 006 6h0.5l2.2 3" />
    <path d="M16 19l3 2 1.2-3z" />
    <circle cx="10" cy="6" r="0.8" /><circle cx="10" cy="9" r="0.8" /><circle cx="12.4" cy="14.6" r="0.8" />
  </>),
  // Horizontal tube with an embouchure + tone holes.
  flute: (<>
    <rect x="3" y="11" width="17" height="2.6" rx="1.3" />
    <circle cx="6" cy="12.3" r="0.7" /><circle cx="10" cy="12.3" r="0.7" />
    <circle cx="13" cy="12.3" r="0.7" /><circle cx="16" cy="12.3" r="0.7" />
  </>),
  // Vertical tube, flared bell at the bottom, tone holes.
  clarinet: (<>
    <path d="M10.3 3h3.4l-0.6 14h-2.2z" />
    <path d="M9.2 17h5.6l1 3.5h-7.6z" />
    <circle cx="12" cy="6.5" r="0.6" /><circle cx="12" cy="9.5" r="0.6" />
    <circle cx="12" cy="12.5" r="0.6" /><circle cx="12" cy="15" r="0.6" />
  </>),
  // Thinner vertical tube with a double-reed staple on top + small bell.
  oboe: (<>
    <path d="M12 3v3" />
    <path d="M11 6h2l0.6 11h-3.2z" />
    <path d="M10.2 17h3.6l0.9 3h-5.4z" />
    <circle cx="12" cy="9" r="0.55" /><circle cx="12" cy="12" r="0.55" /><circle cx="12" cy="14.8" r="0.55" />
  </>),
  // Tall doubled tubes joined at the foot, with a thin bocal crook on top.
  bassoon: (<>
    <path d="M9 20V7.5M13 20V9.5" />
    <path d="M9 20h4" />
    <path d="M9 7.5q0-3 3-3" />
    <path d="M12 4.5l3.5-1.2" />
  </>),
};

export default function InstrumentIcon({ name, kind, size = 18, className }: {
  name?: string;
  kind?: IconKind;
  size?: number;
  className?: string;
}) {
  const k = kind ?? iconKindFor(name ?? "");
  return (
    <svg className={"inst-ic" + (className ? " " + className : "")}
      width={size} height={size} viewBox="0 0 24 24" aria-hidden="true"
      fill="none" stroke="currentColor" strokeWidth="1.6"
      strokeLinecap="round" strokeLinejoin="round">
      {GLYPH[k]}
    </svg>
  );
}
