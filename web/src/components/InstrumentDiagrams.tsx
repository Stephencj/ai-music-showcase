import { useEffect, useRef } from "react";
import {
  DRUM_LAYOUT, trumpetFingering, trombonePosition, apertureFor, brassKind, woodwindKeys,
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
  const apertureRef = useRef<SVGEllipseElement>(null);
  const partialRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let raf = 0;
    const setAperture = (partial: number) => {
      const { ry, word } = apertureFor(partial);
      apertureRef.current?.setAttribute("ry", String(ry));
      if (partialRef.current) {
        partialRef.current.textContent = partial ? `partial ${partial} · aperture ${word}` : "—";
      }
    };
    const tick = () => {
      const t = audioRef.current?.currentTime ?? 0;
      const top = topNote(notesAt(notes, t));
      if (top == null) {
        if (headRef.current) headRef.current.textContent = "—";
        valveRefs.current.forEach((el) => el?.classList.remove("pressed"));
        slideRefs.current.forEach((el) => el.classList.remove("on"));
        setAperture(0);
      } else {
        const written = top + transpose;
        if (headRef.current) {
          headRef.current.textContent = transpose ? `${noteName(written)} ▸ ${noteName(top)} (concert)` : noteName(top);
        }
        if (kind === "valves") {
          const { valves, partial } = trumpetFingering(written);
          valveRefs.current.forEach((el, i) => el?.classList.toggle("pressed", valves.includes(i + 1)));
          setAperture(partial);
        } else {
          const { pos, partial } = trombonePosition(top); // trombone is concert pitch
          slideRefs.current.forEach((el, p) => el.classList.toggle("on", p === pos));
          setAperture(partial);
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
        // Side view, player's hold: mouthpiece (you) at left, bell pointing
        // away at right. Valve 1 is nearest the mouthpiece (index finger),
        // valve 3 nearest the bell. Pressed valves push down + light up.
        <svg className="brass-valves" viewBox="0 0 178 100" preserveAspectRatio="xMidYMid meet" aria-label="trumpet valves">
          <circle cx={8} cy={58} r={5} className="brass-mp" />
          <line x1={12} y1={58} x2={126} y2={58} className="brass-tube" />
          <path d="M126 58 Q158 58 172 38 L172 78 Q158 58 126 58 Z" className="brass-bell" />
          {[0, 1, 2].map((i) => {
            const cx = 56 + i * 30;
            return (
              <g key={i}>
                <rect x={cx - 10} y={24} width={20} height={40} rx={9} className="valve-casing" />
                <circle ref={(el) => { valveRefs.current[i] = el; }} className="valve" cx={cx} cy={20} r={10} />
                <text x={cx} y={78} className="valve-num" textAnchor="middle">{i + 1}</text>
              </g>
            );
          })}
          <text x={8} y={74} className="brass-orient" textAnchor="middle">you</text>
          <text x={158} y={92} className="brass-orient" textAnchor="middle">bell ▸</text>
          <text x={89} y={97} className="brass-cap" textAnchor="middle">1 nearest you · 3 toward bell</text>
        </svg>
      ) : (
        // Trombone slide, player at left: position 1 is all the way in (nearest
        // you), 7 is fully out. The current position lights up.
        <svg className="trombone-slide" viewBox="0 0 188 58" preserveAspectRatio="xMidYMid meet" aria-label="trombone slide">
          <circle cx={7} cy={18} r={4} className="brass-mp" />
          <line x1={11} y1={13} x2={180} y2={13} className="tb-tube" />
          <line x1={11} y1={23} x2={180} y2={23} className="tb-tube" />
          {[1, 2, 3, 4, 5, 6, 7].map((p) => {
            const x = 22 + (p - 1) * 24;
            return (
              <g key={p}>
                <rect ref={(el) => { if (el) slideRefs.current.set(p, el); }} className="slide-pos" x={x - 8} y={4} width={16} height={28} rx={3} />
                <text x={x} y={22} className="slide-num" textAnchor="middle">{p}</text>
              </g>
            );
          })}
          <text x={6} y={50} className="brass-cap" textAnchor="start">◂ in (you)</text>
          <text x={182} y={50} className="brass-cap" textAnchor="end">out ▸</text>
        </svg>
      )}
      {/* Aperture / harmonic: the valve combo or slide only sets the tube
          length — which note sounds is the partial you lock in with the lip
          aperture. Tighter aperture (smaller opening) → higher partial. */}
      <div className="aperture-row">
        <svg className="aperture" viewBox="0 0 56 30" aria-label="lip aperture">
          <rect x={5} y={5} width={46} height={20} rx={10} className="ap-lips" />
          <ellipse ref={apertureRef} cx={28} cy={15} rx={13} ry={6} className="ap-open" />
        </svg>
        <div className="ap-label" ref={partialRef}>—</div>
      </div>
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
      {/* Instrument body held upright: mouthpiece/top at the top, tone holes
          down the body — left hand (top 3) over right hand (bottom 3), with the
          octave/register key off to the side. Closed holes light up. */}
      <svg className="ww-keys" viewBox="0 0 84 178" preserveAspectRatio="xMidYMid meet" aria-label="woodwind fingering">
        <rect x={31} y={12} width={18} height={150} rx={9} className="ww-body" />
        <text x={40} y={8} className="ww-end" textAnchor="middle">▴ mouthpiece</text>
        {/* octave / register key on the side */}
        <circle ref={(el) => { keyRefs.current[0] = el; }} className="ww-key oct" cx={16} cy={34} r={6} />
        <text x={6} y={37} className="ww-klabel">8</text>
        {/* 6 tone holes: L1-L3 then a gap then R1-R3 */}
        {WW_KEY_LABELS.slice(1).map((lab, j) => {
          const cy = 44 + j * 18 + (j >= 3 ? 14 : 0);
          return (
            <g key={lab}>
              <circle ref={(el) => { keyRefs.current[j + 1] = el; }} className="ww-key" cx={40} cy={cy} r={6} />
              <text x={56} y={cy + 3} className="ww-klabel">{lab}</text>
            </g>
          );
        })}
        <text x={10} y={70} className="ww-hand" textAnchor="middle">L</text>
        <text x={10} y={138} className="ww-hand" textAnchor="middle">R</text>
      </svg>
      <div className="inst-hint">simplified</div>
    </div>
  );
}
