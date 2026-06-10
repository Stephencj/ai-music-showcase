import { useEffect, useRef } from "react";
import {
  DRUM_LAYOUT, trumpetFingering, trombonePosition, apertureFor, brassKind, woodwindKeys,
  WW_KEY_LABELS, transposeWritten, notesAt, noteName,
} from "../instruments";

// Live diagrams for drums, brass and woodwind. Each builds a static SVG once
// and follows the practice playhead with its own requestAnimationFrame loop,
// DOM-toggling classes (no per-frame React re-render). Brass/woodwind are
// transposition-aware (fingering for the WRITTEN note) and show one fingering
// per sounding voice (a wind section is a trio — up to 3 separate figures).

export interface NoteSec { pitch: number; start: number; dur: number }
type AudioRef = React.RefObject<HTMLAudioElement | null>;

const MAX_VOICES = 3;   // winds/brass cap at a trio
// Sounding pitches at time t, highest first, capped — one per fingering voice.
function voicesAt(ns: NoteSec[], t: number): number[] {
  return notesAt(ns, t).map((n) => n.pitch).sort((a, b) => b - a).slice(0, MAX_VOICES);
}
const SLOTS = [0, 1, 2];

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

// ── Brass (valves or trombone slide) — one figure per sounding voice ─────────
export function BrassDiagram({ notes, audioRef, name }: { notes: NoteSec[]; audioRef: AudioRef; name: string }) {
  const kind = brassKind(name);
  const transpose = transposeWritten(name);
  const slotEls = useRef<(HTMLDivElement | null)[]>([]);
  const noteEls = useRef<(HTMLDivElement | null)[]>([]);
  const partEls = useRef<(HTMLSpanElement | null)[]>([]);
  const apEls = useRef<(SVGEllipseElement | null)[]>([]);
  const valveEls = useRef<(Element | null)[][]>([[], [], []]);
  const slideEls = useRef<Map<number, Element>[]>([new Map(), new Map(), new Map()]);

  useEffect(() => {
    let raf = 0;
    const tick = () => {
      const t = audioRef.current?.currentTime ?? 0;
      const vs = voicesAt(notes, t);
      for (let s = 0; s < MAX_VOICES; s++) {
        const slot = slotEls.current[s];
        if (s >= vs.length) { slot?.classList.add("hidden"); continue; }
        slot?.classList.remove("hidden");
        const concert = vs[s], written = concert + transpose;
        if (noteEls.current[s]) {
          noteEls.current[s]!.textContent = transpose ? `${noteName(written)} ▸ ${noteName(concert)}` : noteName(written);
        }
        let partial = 0;
        if (kind === "valves") {
          const r = trumpetFingering(written); partial = r.partial;
          valveEls.current[s].forEach((el, i) => el?.classList.toggle("pressed", r.valves.includes(i + 1)));
        } else {
          const r = trombonePosition(concert); partial = r.partial;  // trombone is concert pitch
          slideEls.current[s].forEach((el, p) => el.classList.toggle("on", p === r.pos));
        }
        const { ry, word } = apertureFor(partial);
        apEls.current[s]?.setAttribute("ry", String(ry));
        if (partEls.current[s]) partEls.current[s]!.textContent = partial ? `p${partial} · ${word}` : "";
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [notes, audioRef, kind, transpose]);

  slotEls.current = []; noteEls.current = []; partEls.current = []; apEls.current = [];
  valveEls.current = [[], [], []]; slideEls.current = [new Map(), new Map(), new Map()];

  return (
    <div className="inst-fig">
      <div className="inst-orient">
        {kind === "valves" ? "1 nearest you · 3 toward bell" : "◂ in (you)   ·   out ▸"}
      </div>
      <div className="voice-stack">
        {SLOTS.map((s) => (
          <div key={s} className="voice-slot hidden" ref={(el) => { slotEls.current[s] = el; }}>
            <div className="inst-note vsmall" ref={(el) => { noteEls.current[s] = el; }}>—</div>
            {kind === "valves" ? (
              <svg className="brass-valves-mini" viewBox="0 0 86 40" preserveAspectRatio="xMidYMid meet" aria-label="valves">
                {[0, 1, 2].map((i) => {
                  const cx = 17 + i * 26;
                  return (
                    <g key={i}>
                      <circle ref={(el) => { valveEls.current[s][i] = el; }} className="valve" cx={cx} cy={16} r={11} />
                      <text x={cx} y={37} className="valve-num" textAnchor="middle">{i + 1}</text>
                    </g>
                  );
                })}
              </svg>
            ) : (
              <svg className="trombone-mini" viewBox="0 0 168 28" preserveAspectRatio="xMidYMid meet" aria-label="slide">
                {[1, 2, 3, 4, 5, 6, 7].map((p) => {
                  const x = 6 + (p - 1) * 23;
                  return (
                    <g key={p}>
                      <rect ref={(el) => { if (el) slideEls.current[s].set(p, el); }} className="slide-pos" x={x} y={4} width={18} height={20} rx={3} />
                      <text x={x + 9} y={18} className="slide-num" textAnchor="middle">{p}</text>
                    </g>
                  );
                })}
              </svg>
            )}
            <div className="ap-mini">
              <svg className="aperture" viewBox="0 0 40 22" aria-label="aperture">
                <rect x={3} y={4} width={34} height={14} rx={7} className="ap-lips" />
                <ellipse ref={(el) => { apEls.current[s] = el; }} cx={20} cy={11} rx={9} ry={5} className="ap-open" />
              </svg>
              <span className="ap-label" ref={(el) => { partEls.current[s] = el; }} />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Woodwind (simplified) — one fingering per sounding voice ─────────────────
export function WoodwindDiagram({ notes, audioRef, name }: { notes: NoteSec[]; audioRef: AudioRef; name: string }) {
  const transpose = transposeWritten(name);
  const slotEls = useRef<(HTMLDivElement | null)[]>([]);
  const noteEls = useRef<(HTMLDivElement | null)[]>([]);
  const keyEls = useRef<(Element | null)[][]>([[], [], []]); // [slot][0=octave, 1..6 holes]

  useEffect(() => {
    let raf = 0;
    const tick = () => {
      const t = audioRef.current?.currentTime ?? 0;
      const vs = voicesAt(notes, t);
      for (let s = 0; s < MAX_VOICES; s++) {
        const slot = slotEls.current[s];
        if (s >= vs.length) { slot?.classList.add("hidden"); continue; }
        slot?.classList.remove("hidden");
        const concert = vs[s], written = concert + transpose;
        if (noteEls.current[s]) {
          noteEls.current[s]!.textContent = transpose ? `${noteName(written)} ▸ ${noteName(concert)}` : noteName(written);
        }
        const { holes, oct } = woodwindKeys(written);
        keyEls.current[s].forEach((el, i) => el?.classList.toggle("closed", i === 0 ? oct : holes.includes(i - 1)));
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [notes, audioRef, transpose]);

  slotEls.current = []; noteEls.current = []; keyEls.current = [[], [], []];

  return (
    <div className="inst-fig">
      <div className="inst-orient">mouthpiece ▴ · simplified</div>
      <div className="voice-stack">
        {SLOTS.map((s) => (
          <div key={s} className="voice-slot hidden" ref={(el) => { slotEls.current[s] = el; }}>
            <div className="inst-note vsmall" ref={(el) => { noteEls.current[s] = el; }}>—</div>
            <svg className="ww-mini" viewBox="0 0 50 118" preserveAspectRatio="xMidYMid meet" aria-label="woodwind keys">
              <rect x={22} y={6} width={12} height={106} rx={6} className="ww-body" />
              <circle ref={(el) => { keyEls.current[s][0] = el; }} className="ww-key oct" cx={10} cy={20} r={5} />
              {WW_KEY_LABELS.slice(1).map((lab, j) => {
                const cy = 30 + j * 13 + (j >= 3 ? 8 : 0);
                return <circle key={lab} ref={(el) => { keyEls.current[s][j + 1] = el; }} className="ww-key" cx={28} cy={cy} r={5} />;
              })}
            </svg>
          </div>
        ))}
      </div>
    </div>
  );
}
