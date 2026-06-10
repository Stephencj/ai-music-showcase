import { useEffect, useMemo, useRef, useState } from "react";
import { trumpetFingering, trombonePosition, woodwindKeys, noteName } from "../instruments";
import type { FingerKind } from "../instruments";

// A "tab" for a single wind/brass instrument: a scrolling lane (like the guitar
// tab) whose rows are the valves (1/2/3), slide positions (1–7), or keys
// (octave + 6 tone holes). Each note draws markers on the rows it engages as it
// flows right-to-left toward the now-line; the note crossing it lights up.

const PX_PER_S = 120, ROW = 16, PAD_TOP = 28, LABEL_W = 30, NOW_FRAC = 0.26;

const ROWS_BY_KIND: Record<FingerKind, string[]> = {
  valves: ["1", "2", "3"],
  slide: ["1", "2", "3", "4", "5", "6", "7"],
  keys: ["8va", "L1", "L2", "L3", "R1", "R2", "R3"],
};

interface FNote { start: number; dur: number; rows: number[]; label: string; sub: string }

export default function WindTabView({ notes, audioRef, kind, transpose }: {
  notes: { pitch: number; start: number; dur: number }[];
  audioRef: React.RefObject<HTMLAudioElement | null>;
  kind: FingerKind;
  transpose: number;
}) {
  const rows = ROWS_BY_KIND[kind];

  // Per-note fingering (depends only on pitch → precompute once).
  const fnotes = useMemo<FNote[]>(() => notes.map((nt) => {
    if (kind === "valves") {
      const w = nt.pitch + transpose, r = trumpetFingering(w);
      return { start: nt.start, dur: nt.dur, rows: r.valves.map((v) => v - 1),
        label: noteName(w), sub: r.partial ? `p${r.partial}` : "" };
    }
    if (kind === "slide") {
      const r = trombonePosition(nt.pitch);
      return { start: nt.start, dur: nt.dur, rows: [r.pos - 1], label: noteName(nt.pitch), sub: r.partial ? `p${r.partial}` : "" };
    }
    const w = nt.pitch + transpose, { holes, oct } = woodwindKeys(w);
    return { start: nt.start, dur: nt.dur, rows: [...(oct ? [0] : []), ...holes.map((h) => h + 1)], label: noteName(w), sub: "" };
  }), [notes, kind, transpose]);

  const wrapRef = useRef<HTMLDivElement>(null);
  const [w, setW] = useState(640);
  const [t, setT] = useState(0);
  const raf = useRef<number | null>(null);

  useEffect(() => {
    const el = wrapRef.current; if (!el) return;
    const measure = () => setW(el.clientWidth || 640); measure();
    const ro = new ResizeObserver(measure); ro.observe(el);
    return () => ro.disconnect();
  }, []);
  useEffect(() => {
    const tick = () => { const a = audioRef.current; if (a) setT(a.currentTime || 0); raf.current = requestAnimationFrame(tick); };
    raf.current = requestAnimationFrame(tick);
    return () => { if (raf.current) cancelAnimationFrame(raf.current); };
  }, [audioRef]);

  const nRows = rows.length;
  const H = PAD_TOP + ROW * (nRows - 1) + 18;
  const nowX = Math.round(w * NOW_FRAC);
  const rowY = (r: number) => PAD_TOP + r * ROW;

  return (
    <div className="tab-lane-wrap" ref={wrapRef}>
      <svg className="tab-lane" width={w} height={H} role="img" aria-label="fingering tab">
        {rows.map((lab, r) => (
          <g key={r}>
            <line x1={LABEL_W} y1={rowY(r)} x2={w} y2={rowY(r)} className="tab-string" />
            <text x={6} y={rowY(r) + 4} className="tab-strlabel">{lab}</text>
          </g>
        ))}
        <line x1={nowX} y1={PAD_TOP - 14} x2={nowX} y2={rowY(nRows - 1) + 12} className="tab-now" />
        {fnotes.map((fn, i) => {
          const x = nowX + (fn.start - t) * PX_PER_S;
          const wpx = Math.max(9, fn.dur * PX_PER_S - 2);
          if (x + wpx < LABEL_W - 30 || x > w + 30) return null;
          const on = fn.start <= t && t < fn.start + fn.dur;
          const past = t >= fn.start + fn.dur;
          const cls = "wtab-note" + (on ? " on" : past ? " past" : "");
          return (
            <g key={i} className={cls}>
              {fn.rows.map((r) => (
                <rect key={r} x={x} y={rowY(r) - 5} width={wpx} height={10} rx={5} className="wtab-mark" />
              ))}
              {fn.rows.length === 0 && (
                <text x={x + wpx / 2} y={rowY(0) + 4} className="wtab-open" textAnchor="middle">○</text>
              )}
              <text x={x + wpx / 2} y={PAD_TOP - 16} className="wtab-label" textAnchor="middle">{fn.label}</text>
              {fn.sub && <text x={x + wpx / 2} y={H - 4} className="wtab-sub" textAnchor="middle">{fn.sub}</text>}
            </g>
          );
        })}
      </svg>
    </div>
  );
}
