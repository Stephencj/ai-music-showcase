import { useEffect, useMemo, useRef } from "react";
import type { RollNote } from "./NotationRoll";

// Two modes:
//  • "chord" (practice): guitar chord SHAPE/fingering + chord tones on a
//    compact piano — how to play the chord.
//  • "neck" (what's on the page): full guitar neck + wide real-octave piano,
//    lighting the ACTUAL notes sounding. Highlights are toggled via direct DOM
//    (rAF) so a busy part doesn't re-render the whole SVG and jank.

const NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
const FLAT_TO_SHARP: Record<string, string> = {
  Db: "C#", Eb: "D#", Gb: "F#", Ab: "G#", Bb: "A#", Cb: "B", Fb: "E",
};
const TEMPLATES: Record<string, number[]> = {
  maj: [0, 4, 7], min: [0, 3, 7], dim: [0, 3, 6], aug: [0, 4, 8],
  sus2: [0, 2, 7], sus4: [0, 5, 7], "6": [0, 4, 7, 9], min6: [0, 3, 7, 9],
  "7": [0, 4, 7, 10], maj7: [0, 4, 7, 11], min7: [0, 3, 7, 10],
  dim7: [0, 3, 6, 9], m7b5: [0, 3, 6, 10],
};
function rootPc(root: string): number {
  const r = FLAT_TO_SHARP[root] ?? root;
  const i = NOTE_NAMES.indexOf(r);
  return i < 0 ? 0 : i;
}
const pc = (p: number) => ((p % 12) + 12) % 12;
const WHITE = new Set([0, 2, 4, 5, 7, 9, 11]);
const isWhite = (p: number) => WHITE.has(pc(p));

// ===== CHORD MODE (compact, static) =======================================
const WHITE_PCS = [0, 2, 4, 5, 7, 9, 11];
const BLACK_AFTER = [0, 1, 3, 4, 5];
function CompactPiano({ tones, root }: { tones: Set<number>; root: number }) {
  const octaves = 2, wk = 22, wh = 96, bk = 13, bh = 60;
  const width = WHITE_PCS.length * octaves * wk;
  const whites: React.ReactNode[] = [], blacks: React.ReactNode[] = [];
  for (let o = 0; o < octaves; o++) {
    for (let i = 0; i < WHITE_PCS.length; i++) {
      const pcv = WHITE_PCS[i], x = (o * WHITE_PCS.length + i) * wk;
      const on = tones.has(pcv), r = on && pcv === root;
      whites.push(<rect key={`w${o}${i}`} x={x} y={0} width={wk - 1} height={wh} rx={2}
        fill={r ? "#2563eb" : on ? "#7eb0ff" : "#fbfdff"} stroke="#1e293b" strokeWidth={0.7} />);
      if (BLACK_AFTER.includes(i)) {
        const bpc = (pcv + 1) % 12, bx = x + wk - bk / 2, bon = tones.has(bpc), br = bon && bpc === root;
        blacks.push(<rect key={`b${o}${i}`} x={bx} y={0} width={bk} height={bh} rx={1.5}
          fill={br ? "#2563eb" : bon ? "#3b6fd6" : "#16202e"} stroke="#0b1118" strokeWidth={0.7} />);
      }
    }
  }
  return <svg className="diagram-piano" viewBox={`0 0 ${width} ${wh}`}
    preserveAspectRatio="xMidYMid meet" role="img" aria-label="piano chord">{whites}{blacks}</svg>;
}

const STRING_PCS = [4, 9, 2, 7, 11, 4];
const OPEN: Record<string, number[]> = {
  "C:maj": [-1, 3, 2, 0, 1, 0], "C:7": [-1, 3, 2, 3, 1, 0], "C:maj7": [-1, 3, 2, 0, 0, 0],
  "A:maj": [-1, 0, 2, 2, 2, 0], "A:min": [-1, 0, 2, 2, 1, 0], "A:7": [-1, 0, 2, 0, 2, 0],
  "A:min7": [-1, 0, 2, 0, 1, 0], "A:maj7": [-1, 0, 2, 1, 2, 0],
  "G:maj": [3, 2, 0, 0, 0, 3], "G:7": [3, 2, 0, 0, 0, 1],
  "E:maj": [0, 2, 2, 1, 0, 0], "E:min": [0, 2, 2, 0, 0, 0], "E:7": [0, 2, 0, 1, 0, 0], "E:min7": [0, 2, 0, 0, 0, 0],
  "D:maj": [-1, -1, 0, 2, 3, 2], "D:min": [-1, -1, 0, 2, 3, 1], "D:7": [-1, -1, 0, 2, 1, 2],
  "D:min7": [-1, -1, 0, 2, 1, 1], "D:maj7": [-1, -1, 0, 2, 2, 2],
};
const E_SHAPE: Record<string, number[]> = {
  maj: [0, 2, 2, 1, 0, 0], min: [0, 2, 2, 0, 0, 0], "7": [0, 2, 0, 1, 0, 0], min7: [0, 2, 0, 0, 0, 0], maj7: [0, 2, 1, 1, 0, 0],
};
const GUITAR_REDUCE: Record<string, string> = {
  "6": "maj", min6: "min", dim: "min", aug: "maj", sus2: "maj", sus4: "maj", dim7: "min", m7b5: "min7",
};
function guitarShape(root: string, quality: string): { frets: number[]; approx: boolean } {
  const q0 = TEMPLATES[quality] ? quality : "maj";
  let q = q0; let approx = false;
  const open = OPEN[`${root}:${q}`];
  if (open) return { frets: open, approx: false };
  if (!E_SHAPE[q]) { q = GUITAR_REDUCE[q] || "maj"; approx = q !== q0; }
  if (!E_SHAPE[q]) { q = "maj"; approx = true; }
  const barre = ((rootPc(root) - STRING_PCS[0]) % 12 + 12) % 12;
  return { frets: E_SHAPE[q].map((o) => barre + o), approx };
}
function ChordShapeGuitar({ root, quality }: { root: string; quality: string }) {
  const { frets, approx } = guitarShape(root, quality);
  const played = frets.filter((f) => f > 0);
  const maxF = played.length ? Math.max(...played) : 1, minF = played.length ? Math.min(...played) : 1;
  const baseFret = maxF <= 4 ? 1 : minF, span = Math.max(4, maxF - baseFret + 1);
  const left = 26, top = 18, sw = 18, fh = 26;
  const width = left + 5 * sw + 16, height = top + span * fh + 12;
  const dots = frets.map((f, s) => {
    const x = left + s * sw;
    if (f < 0) return <text key={s} x={x} y={top - 6} className="g-x">×</text>;
    if (f === 0) return <circle key={s} cx={x} cy={top - 9} r={4} className="g-o" />;
    return <circle key={s} cx={x} cy={top + (f - baseFret + 0.5) * fh} r={6} className="g-dot" />;
  });
  return (
    <svg className="diagram-guitar" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="xMidYMid meet" role="img" aria-label="guitar chord">
      {baseFret === 1 ? <rect x={left} y={top} width={5 * sw} height={3} fill="#1e293b" />
        : <text x={left - 10} y={top + fh * 0.6} className="g-fret">{baseFret}fr</text>}
      {Array.from({ length: span + 1 }, (_, i) => <line key={`f${i}`} x1={left} y1={top + i * fh} x2={left + 5 * sw} y2={top + i * fh} stroke="#94a3b8" strokeWidth={0.8} />)}
      {Array.from({ length: 6 }, (_, i) => <line key={`s${i}`} x1={left + i * sw} y1={top} x2={left + i * sw} y2={top + span * fh} stroke="#cbd5e1" strokeWidth={0.8} />)}
      {dots}
      {approx && <text x={width / 2} y={height - 2} className="g-approx" textAnchor="middle">approx</text>}
    </svg>
  );
}

// ===== NECK MODE (full neck + wide piano, DOM-toggled highlights) ==========
const STRING_MIDI = [64, 59, 55, 50, 45, 40]; // high-E..low-E (top..bottom)
const FRETS = 15;
const INLAYS = new Set([3, 5, 7, 9, 12, 15]);
function octaveFloor(p: number) { return Math.floor(p / 12) * 12; }

function NeckDiagrams({
  notes, audioRef, range, chordTones,
}: {
  notes: RollNote[];
  audioRef?: React.RefObject<HTMLAudioElement | null>;
  range?: [number, number];
  chordTones: Set<number>;
}) {
  const [lo, hi] = useMemo(() => {
    let a = range ? range[0] : 48, b = range ? range[1] : 83;
    a = octaveFloor(a); b = octaveFloor(b) + 11;
    while (b - a < 35) b += 12;
    return [Math.max(21, a), Math.min(108, b)];
  }, [range]);

  // Element refs keyed by pitch (a pitch can have several positions on the neck).
  const elsByPitch = useRef<Map<number, Element[]>>(new Map());
  const put = (p: number, el: Element | null) => {
    if (!el) return;
    const a = elsByPitch.current.get(p) || [];
    a.push(el); elsByPitch.current.set(p, a);
  };

  // ---- static piano ----
  const wk = 15, wh = 66, bk = 9, bh = 40;
  const whites: number[] = [];
  for (let p = lo; p <= hi; p++) if (isWhite(p)) whites.push(p);
  const idx = new Map<number, number>(); whites.forEach((p, i) => idx.set(p, i));
  const pianoW = Math.max(1, whites.length * wk);
  const pianoEls: React.ReactNode[] = [];
  whites.forEach((p, i) => {
    pianoEls.push(<rect key={`w${p}`} ref={(el) => put(p, el)} className="pk w" x={i * wk} y={0}
      width={wk - 1} height={wh} rx={2} fill="#fbfdff" stroke="#1e293b" strokeWidth={0.6} />);
    if (pc(p) === 0) pianoEls.push(<text key={`l${p}`} x={i * wk + wk / 2} y={wh - 4} fontSize={7}
      fill="#64748b" textAnchor="middle">C{Math.floor(p / 12) - 1}</text>);
  });
  for (let p = lo; p <= hi; p++) {
    if (isWhite(p)) continue;
    const below = idx.get(p - 1); if (below == null) continue;
    pianoEls.push(<rect key={`b${p}`} ref={(el) => put(p, el)} className="pk b"
      x={below * wk + wk - bk / 2} y={0} width={bk} height={bh} rx={1.5} fill="#16202e" stroke="#0b1118" strokeWidth={0.6} />);
  }

  // ---- static neck ----
  const nl = 22, nt = 12, fw = 26, sg = 14;
  const neckW = nl + FRETS * fw + 10, neckH = nt + 5 * sg + 18;
  const yOf = (s: number) => nt + s * sg;
  const neckEls: React.ReactNode[] = [];
  INLAYS.forEach((f) => neckEls.push(<circle key={`in${f}`} cx={nl + (f - 0.5) * fw} cy={nt + 2.5 * sg} r={2.5} fill="#cbd5e1" />));
  for (let f = 0; f <= FRETS; f++) {
    const x = nl + f * fw;
    neckEls.push(<line key={`f${f}`} x1={x} y1={nt} x2={x} y2={nt + 5 * sg} stroke={f === 0 ? "#1e293b" : "#94a3b8"} strokeWidth={f === 0 ? 3 : 0.8} />);
    if (f > 0) neckEls.push(<text key={`fn${f}`} x={nl + (f - 0.5) * fw} y={neckH - 4} fontSize={8} fill="#64748b" textAnchor="middle">{f}</text>);
  }
  for (let s = 0; s < 6; s++) {
    neckEls.push(<line key={`s${s}`} x1={nl} y1={yOf(s)} x2={nl + FRETS * fw} y2={yOf(s)} stroke="#cbd5e1" strokeWidth={0.9} />);
    for (let f = 0; f <= FRETS; f++) {
      const p = STRING_MIDI[s] + f;
      const cx = f === 0 ? nl - 9 : nl + (f - 0.5) * fw;
      neckEls.push(<circle key={`d${s}-${f}`} ref={(el) => put(p, el)} className="nd" cx={cx} cy={yOf(s)} r={f === 0 ? 5 : 6} />);
    }
  }

  // ---- highlight driver ----
  useEffect(() => {
    const map = elsByPitch.current;
    const setP = (p: number, on: boolean) => map.get(p)?.forEach((el) => el.classList.toggle("lit", on));
    map.forEach((arr) => arr.forEach((el) => el.classList.remove("lit")));

    if (!notes.length) {
      // No note data → light the chord's tones in every position (static).
      map.forEach((arr, p) => { if (chordTones.has(pc(p))) arr.forEach((el) => el.classList.add("lit")); });
      return;
    }
    let raf = 0;
    const on = new Set<number>();
    const tick = () => {
      const t = audioRef?.current?.currentTime ?? 0;
      const snd = new Set<number>();
      for (const n of notes) if (t >= n.start && t < n.start + n.dur) snd.add(n.pitch);
      for (const p of on) if (!snd.has(p)) { setP(p, false); on.delete(p); }
      for (const p of snd) if (!on.has(p)) { setP(p, true); on.add(p); }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
    // Rebuilt elements (new refs) whenever the key range changes.
  }, [notes, audioRef, chordTones, lo, hi]);

  // Reset the ref map each render so stale element refs don't accumulate.
  elsByPitch.current = new Map();

  return (
    <div className="diagrams diagrams-wide">
      <div className="diagram-card">
        <div className="diagram-title">Piano{notes.length ? " · live" : ""}</div>
        <svg className="diagram-piano-wide" viewBox={`0 0 ${pianoW} ${wh}`} preserveAspectRatio="xMidYMid meet" aria-label="piano">{pianoEls}</svg>
      </div>
      <div className="diagram-card">
        <div className="diagram-title">Guitar neck{notes.length ? " · live" : ""}</div>
        <svg className="diagram-guitar-neck" viewBox={`0 0 ${neckW} ${neckH}`} preserveAspectRatio="xMidYMid meet" aria-label="guitar neck">{neckEls}</svg>
      </div>
    </div>
  );
}

// ===========================================================================
export default function ChordDiagram({
  root, quality, notes, audioRef, range, neck = false,
}: {
  root: string;
  quality: string;
  notes?: RollNote[];
  audioRef?: React.RefObject<HTMLAudioElement | null>;
  range?: [number, number];
  neck?: boolean;
}) {
  const tones = useMemo(() => {
    const offs = TEMPLATES[quality] || TEMPLATES.maj;
    return new Set(offs.map((o) => (rootPc(root) + o) % 12));
  }, [root, quality]);

  if (!neck) {
    return (
      <div className="diagrams">
        <div className="diagram-card">
          <div className="diagram-title">Piano</div>
          <CompactPiano tones={tones} root={rootPc(root) % 12} />
        </div>
        <div className="diagram-card">
          <div className="diagram-title">Guitar</div>
          <ChordShapeGuitar root={FLAT_TO_SHARP[root] ?? root} quality={quality} />
        </div>
      </div>
    );
  }
  return <NeckDiagrams notes={notes || []} audioRef={audioRef} range={range} chordTones={tones} />;
}
