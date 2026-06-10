import { useEffect, useRef } from "react";
import {
  DRUM_LAYOUT, trumpetFingering, trombonePosition, apertureFor, woodwindKeys,
  WW_KEY_LABELS, notesAt, noteName,
} from "../instruments";
import type { VoiceSpec } from "../instruments";

// Live diagrams for drums and pitched winds/brass. Each builds a static SVG
// once and follows the practice playhead with its own requestAnimationFrame
// loop, DOM-toggling classes (no per-frame React re-render).

export interface NoteSec { pitch: number; start: number; dur: number }
type AudioRef = React.RefObject<HTMLAudioElement | null>;

// Distinct sounding pitches at time t, highest first, capped to `max` — one per
// voice (dedupes octave/unison doublings so they don't waste voice slots).
function voicesAt(ns: NoteSec[], t: number, max: number): number[] {
  const out: number[] = [];
  const seen = new Set<number>();
  for (const p of notesAt(ns, t).map((n) => n.pitch).sort((a, b) => b - a)) {
    if (seen.has(p)) continue;
    seen.add(p); out.push(p);
    if (out.length >= max) break;
  }
  return out;
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

// ── Winds / brass — one fingering figure per voice/member ────────────────────
// `members` is the per-voice plan: a section's member instruments (each its own
// fingering kind + transposition), or a single solo instrument. Voices are
// assigned highest→lowest to the members (top of the chord = top of the
// section).
export function FingeringDiagram({ notes, audioRef, members, onPickMember }: {
  notes: NoteSec[]; audioRef: AudioRef; members: VoiceSpec[];
  onPickMember?: (memberIdx: number) => void;   // click a member → tab that instrument
}) {
  const n = Math.max(1, members.length);
  const isSection = members.length > 1;
  const slotEls = useRef<(HTMLDivElement | null)[]>([]);
  const noteEls = useRef<(HTMLDivElement | null)[]>([]);
  const partEls = useRef<(HTMLSpanElement | null)[]>([]);
  const apEls = useRef<(SVGEllipseElement | null)[]>([]);
  const valveEls = useRef<(Element | null)[][]>([]);
  const slideEls = useRef<Map<number, Element>[]>([]);
  const keyEls = useRef<(Element | null)[][]>([]);

  useEffect(() => {
    let raf = 0;
    let lastVs: number[] = [];
    const clearSlot = (s: number) => {
      (valveEls.current[s] ?? []).forEach((el) => el?.classList.remove("pressed"));
      slideEls.current[s]?.forEach((el) => el.classList.remove("on"));
      (keyEls.current[s] ?? []).forEach((el) => el?.classList.remove("closed"));
      if (partEls.current[s]) partEls.current[s]!.textContent = "";
      if (noteEls.current[s]) noteEls.current[s]!.textContent = "·";
    };
    const tick = () => {
      const t = audioRef.current?.currentTime ?? 0;
      const vs = voicesAt(notes, t, n);
      // While a note sounds it's the bright "hit"; in the gap between notes we
      // keep the SAME positions but dim them (a `held` tone) so you still see
      // where your fingers should be without the figure flashing off.
      const held = vs.length === 0;
      const active = held ? lastVs : vs;
      if (!held) lastVs = vs;
      for (let s = 0; s < n; s++) {
        slotEls.current[s]?.classList.toggle("held", held && s < active.length);
        if (s >= active.length) { clearSlot(s); continue; }   // idle member in a thinner chord
        const m = members[s];
        const concert = active[s], written = concert + m.transpose;
        if (noteEls.current[s]) {
          noteEls.current[s]!.textContent = m.transpose
            ? `${noteName(written)} ▸ ${noteName(concert)}` : noteName(written);
        }
        if (m.kind === "valves") {
          const r = trumpetFingering(written);
          (valveEls.current[s] ?? []).forEach((el, i) => el?.classList.toggle("pressed", r.valves.includes(i + 1)));
          const { ry, word } = apertureFor(r.partial);
          apEls.current[s]?.setAttribute("ry", String(ry));
          if (partEls.current[s]) partEls.current[s]!.textContent = r.partial ? `p${r.partial} · ${word}` : "";
        } else if (m.kind === "slide") {
          const r = trombonePosition(concert);
          slideEls.current[s]?.forEach((el, p) => el.classList.toggle("on", p === r.pos));
          const { ry, word } = apertureFor(r.partial);
          apEls.current[s]?.setAttribute("ry", String(ry));
          if (partEls.current[s]) partEls.current[s]!.textContent = r.partial ? `p${r.partial} · ${word}` : "";
        } else {
          const { holes, oct } = woodwindKeys(written);
          (keyEls.current[s] ?? []).forEach((el, i) => el?.classList.toggle("closed", i === 0 ? oct : holes.includes(i - 1)));
        }
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [notes, audioRef, members, n]);

  slotEls.current = []; noteEls.current = []; partEls.current = []; apEls.current = [];
  valveEls.current = members.map(() => []); slideEls.current = members.map(() => new Map());
  keyEls.current = members.map(() => []);

  const orient = members.some((m) => m.kind === "valves")
    ? "valves: 1 nearest you · 3 toward bell" : isSection ? "top → bottom of the section" : "mouthpiece ▴";

  return (
    <div className="inst-fig">
      <div className="inst-orient">{orient}</div>
      <div className="voice-stack">
        {members.map((m, s) => (
          <div key={s}
            className={`voice-slot voice-${m.kind}` + (onPickMember ? " pickable" : "")}
            ref={(el) => { slotEls.current[s] = el; }}
            role={onPickMember ? "button" : undefined}
            tabIndex={onPickMember ? 0 : undefined}
            title={onPickMember ? `Tab ${m.label}` : undefined}
            onClick={onPickMember ? () => onPickMember(s) : undefined}>
            {isSection && <div className="voice-member">{m.label}{onPickMember ? " ›" : ""}</div>}
            <div className="inst-note vsmall" ref={(el) => { noteEls.current[s] = el; }}>—</div>
            {m.kind === "valves" ? (
              <svg className="brass-valves-mini" viewBox="0 0 86 40" preserveAspectRatio="xMidYMid meet" aria-label="valves">
                {[0, 1, 2].map((i) => {
                  const cx = 17 + i * 26;
                  return (
                    <g key={i}>
                      <circle ref={(el) => { (valveEls.current[s] ??= [])[i] = el; }} className="valve" cx={cx} cy={16} r={11} />
                      <text x={cx} y={37} className="valve-num" textAnchor="middle">{i + 1}</text>
                    </g>
                  );
                })}
              </svg>
            ) : m.kind === "slide" ? (
              <svg className="trombone-mini" viewBox="0 0 168 28" preserveAspectRatio="xMidYMid meet" aria-label="slide">
                {[1, 2, 3, 4, 5, 6, 7].map((p) => {
                  const x = 6 + (p - 1) * 23;
                  return (
                    <g key={p}>
                      <rect ref={(el) => { if (el) (slideEls.current[s] ??= new Map()).set(p, el); }} className="slide-pos" x={x} y={4} width={18} height={20} rx={3} />
                      <text x={x + 9} y={18} className="slide-num" textAnchor="middle">{p}</text>
                    </g>
                  );
                })}
              </svg>
            ) : (
              <svg className="ww-mini" viewBox="0 0 50 118" preserveAspectRatio="xMidYMid meet" aria-label="woodwind keys">
                <rect x={22} y={6} width={12} height={106} rx={6} className="ww-body" />
                <circle ref={(el) => { (keyEls.current[s] ??= [])[0] = el; }} className="ww-key oct" cx={10} cy={20} r={5} />
                {WW_KEY_LABELS.slice(1).map((lab, j) => {
                  const cy = 30 + j * 13 + (j >= 3 ? 8 : 0);
                  return <circle key={lab} ref={(el) => { (keyEls.current[s] ??= [])[j + 1] = el; }} className="ww-key" cx={28} cy={cy} r={5} />;
                })}
              </svg>
            )}
            {(m.kind === "valves" || m.kind === "slide") && (
              <div className="ap-mini">
                <svg className="aperture" viewBox="0 0 40 22" aria-label="aperture">
                  <rect x={3} y={4} width={34} height={14} rx={7} className="ap-lips" />
                  <ellipse ref={(el) => { apEls.current[s] = el; }} cx={20} cy={11} rx={9} ry={5} className="ap-open" />
                </svg>
                <span className="ap-label" ref={(el) => { partEls.current[s] = el; }} />
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
