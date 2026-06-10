import { useEffect, useRef } from "react";
import {
  DRUM_LAYOUT, TRUMPET_VALVES, TROMBONE_SLIDE, brassKind, woodwindKeys,
  WW_KEY_LABELS, transposeWritten, notesAt, noteName,
} from "../instruments";

// Live diagrams for drums, brass and woodwind. Each builds a static SVG once
// and follows the practice playhead with its own requestAnimationFrame loop,
// DOM-toggling classes (no per-frame React re-render). Brass/woodwind are
// transposition-aware: the fingering is for the WRITTEN note (concert + offset)
// and the caption shows written ▸ concert.

export interface NoteSec { pitch: number; start: number; dur: number }
type AudioRef = React.RefObject<HTMLAudioElement | null>;

function topNote(ns: NoteSec[]): number | null {
  let best: number | null = null;
  for (const n of ns) if (best == null || n.pitch > best) best = n.pitch;
  return best;
}
const pcOf = (p: number) => ((p % 12) + 12) % 12;

// ── Drums ───────────────────────────────────────────────────────────────────
export function DrumDiagram({ notes, audioRef }: { notes: NoteSec[]; audioRef: AudioRef }) {
  const pads = useRef<Map<number, Element>>(new Map());
  const put = (note: number, el: Element | null) => { if (el) pads.current.set(note, el); };

  useEffect(() => {
    const map = pads.current;
    const on = new Set<number>();
    let raf = 0;
    const tick = () => {
      const t = audioRef.current?.currentTime ?? 0;
      const snd = new Set<number>();
      for (const n of notesAt(notes, t)) snd.add(n.pitch);
      for (const k of on) if (!snd.has(k)) { map.get(k)?.classList.remove("lit"); on.delete(k); }
      for (const k of snd) if (!on.has(k)) { map.get(k)?.classList.add("lit"); on.add(k); }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [notes, audioRef]);

  pads.current = new Map();
  return (
    <svg className="drum-kit" viewBox="0 0 100 104" preserveAspectRatio="xMidYMid meet" aria-label="drum kit">
      {DRUM_LAYOUT.map((p) => (
        <g key={p.note}>
          <circle ref={(el) => put(p.note, el)} className={`drum-pad ${p.group}`} cx={p.x} cy={p.y} r={p.r} />
          <text x={p.x} y={p.group === "kit" ? p.y + 2.5 : p.y - p.r - 1.5}
            className="drum-label" textAnchor="middle" fontSize={p.group === "kit" ? 4 : 3}>{p.label}</text>
        </g>
      ))}
    </svg>
  );
}

// ── Brass (valves or trombone slide) ─────────────────────────────────────────
export function BrassDiagram({ notes, audioRef, name }: { notes: NoteSec[]; audioRef: AudioRef; name: string }) {
  const kind = brassKind(name);
  const transpose = transposeWritten(name);
  const valveRefs = useRef<(Element | null)[]>([]);
  const slideRefs = useRef<Map<number, Element>>(new Map());
  const headRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let raf = 0;
    const tick = () => {
      const t = audioRef.current?.currentTime ?? 0;
      const top = topNote(notesAt(notes, t));
      if (top == null) {
        if (headRef.current) headRef.current.textContent = "—";
        valveRefs.current.forEach((el) => el?.classList.remove("pressed"));
        slideRefs.current.forEach((el) => el.classList.remove("on"));
      } else {
        const written = top + transpose;
        if (headRef.current) {
          headRef.current.textContent = transpose ? `${noteName(written)} ▸ ${noteName(top)} (concert)` : noteName(top);
        }
        if (kind === "valves") {
          const combo = TRUMPET_VALVES[pcOf(written)] ?? [];
          valveRefs.current.forEach((el, i) => el?.classList.toggle("pressed", combo.includes(i + 1)));
        } else {
          const pos = TROMBONE_SLIDE[pcOf(top)] ?? 1; // trombone is concert pitch
          slideRefs.current.forEach((el, p) => el.classList.toggle("on", p === pos));
        }
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [notes, audioRef, kind, transpose]);

  valveRefs.current = [];
  slideRefs.current = new Map();
  return (
    <div className="inst-fig">
      <div className="inst-note" ref={headRef}>—</div>
      {kind === "valves" ? (
        <svg className="brass-valves" viewBox="0 0 120 78" preserveAspectRatio="xMidYMid meet" aria-label="valves">
          {[0, 1, 2].map((i) => {
            const cx = 24 + i * 36;
            return (
              <g key={i}>
                <rect x={cx - 13} y={8} width={26} height={56} rx={11} className="valve-casing" />
                <circle ref={(el) => { valveRefs.current[i] = el; }} className="valve" cx={cx} cy={30} r={13} />
                <text x={cx} y={70} className="valve-num" textAnchor="middle">{i + 1}</text>
              </g>
            );
          })}
        </svg>
      ) : (
        <svg className="trombone-slide" viewBox="0 0 160 40" preserveAspectRatio="xMidYMid meet" aria-label="slide">
          {[1, 2, 3, 4, 5, 6, 7].map((p) => {
            const x = 6 + (p - 1) * 21;
            return (
              <g key={p}>
                <rect ref={(el) => { if (el) slideRefs.current.set(p, el); }} className="slide-pos" x={x} y={8} width={17} height={24} rx={3} />
                <text x={x + 8.5} y={24} className="slide-num" textAnchor="middle">{p}</text>
              </g>
            );
          })}
        </svg>
      )}
    </div>
  );
}

// ── Woodwind (simplified main-key chart) ─────────────────────────────────────
export function WoodwindDiagram({ notes, audioRef, name }: { notes: NoteSec[]; audioRef: AudioRef; name: string }) {
  const transpose = transposeWritten(name);
  const keyRefs = useRef<(Element | null)[]>([]);
  const headRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let raf = 0;
    const tick = () => {
      const t = audioRef.current?.currentTime ?? 0;
      const top = topNote(notesAt(notes, t));
      if (top == null) {
        if (headRef.current) headRef.current.textContent = "—";
        keyRefs.current.forEach((el) => el?.classList.remove("closed"));
      } else {
        const written = top + transpose;
        if (headRef.current) {
          headRef.current.textContent = transpose ? `${noteName(written)} ▸ ${noteName(top)} (concert)` : noteName(top);
        }
        const { holes, oct } = woodwindKeys(written);
        keyRefs.current.forEach((el, i) => el?.classList.toggle("closed", i === 0 ? oct : holes.includes(i - 1)));
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [notes, audioRef, transpose]);

  keyRefs.current = [];
  return (
    <div className="inst-fig">
      <div className="inst-note" ref={headRef}>—</div>
      <svg className="ww-keys" viewBox="0 0 64 152" preserveAspectRatio="xMidYMid meet" aria-label="woodwind keys">
        {WW_KEY_LABELS.map((lab, i) => {
          const cy = 12 + i * 20;
          return (
            <g key={i}>
              <circle ref={(el) => { keyRefs.current[i] = el; }} className={`ww-key${i === 0 ? " oct" : ""}`} cx={22} cy={cy} r={8} />
              <text x={38} y={cy + 3} className="ww-klabel">{lab}</text>
            </g>
          );
        })}
      </svg>
      <div className="inst-hint">simplified</div>
    </div>
  );
}
