import { useMemo } from "react";

// Two modes:
//  • "chord" (practice): the guitar chord SHAPE/fingering + chord tones on a
//    compact 2-octave piano — how to play the chord.
//  • "neck" (what's on the page): the full guitar neck horizontally + a wide
//    real-octave piano lighting the ACTUAL notes sounding (or the chord's tones
//    in every position when there's no note data).

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

// ===== CHORD MODE =========================================================
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

const STRING_PCS = [4, 9, 2, 7, 11, 4]; // low-E..high-E open pitch classes
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

// ===== NECK MODE ==========================================================
function octaveFloor(p: number) { return Math.floor(p / 12) * 12; }

function WidePiano({ lo, hi, lit, root }: { lo: number; hi: number; lit: (p: number) => boolean; root: number }) {
  const whites: number[] = [];
  for (let p = lo; p <= hi; p++) if (isWhite(p)) whites.push(p);
  const wk = 15, wh = 66, bk = 9, bh = 40;
  const idx = new Map<number, number>(); whites.forEach((p, i) => idx.set(p, i));
  const width = Math.max(1, whites.length * wk);
  const els: React.ReactNode[] = [];
  whites.forEach((p, i) => {
    const on = lit(p), r = on && pc(p) === root;
    els.push(<rect key={`w${p}`} x={i * wk} y={0} width={wk - 1} height={wh} rx={2}
      fill={r ? "#2563eb" : on ? "#7eb0ff" : "#fbfdff"} stroke="#1e293b" strokeWidth={0.6} />);
    if (pc(p) === 0) els.push(<text key={`l${p}`} x={i * wk + wk / 2} y={wh - 4} fontSize={7} fill="#64748b" textAnchor="middle">C{Math.floor(p / 12) - 1}</text>);
  });
  for (let p = lo; p <= hi; p++) {
    if (isWhite(p)) continue;
    const below = idx.get(p - 1); if (below == null) continue;
    const on = lit(p), r = on && pc(p) === root;
    els.push(<rect key={`b${p}`} x={below * wk + wk - bk / 2} y={0} width={bk} height={bh} rx={1.5}
      fill={r ? "#2563eb" : on ? "#3b6fd6" : "#16202e"} stroke="#0b1118" strokeWidth={0.6} />);
  }
  return <svg className="diagram-piano-wide" viewBox={`0 0 ${width} ${wh}`} preserveAspectRatio="xMidYMid meet" role="img" aria-label="piano">{els}</svg>;
}

const STRING_MIDI = [64, 59, 55, 50, 45, 40]; // high-E..low-E (top..bottom)
const FRETS = 15;
const INLAYS = new Set([3, 5, 7, 9, 12, 15]);
function FullNeck({ lit, root }: { lit: (p: number) => boolean; root: number }) {
  const left = 22, top = 12, fw = 26, sg = 14;
  const width = left + FRETS * fw + 10, height = top + 5 * sg + 18;
  const yOf = (s: number) => top + s * sg;
  const els: React.ReactNode[] = [];
  INLAYS.forEach((f) => els.push(<circle key={`in${f}`} cx={left + (f - 0.5) * fw} cy={top + 2.5 * sg} r={2.5} fill="#cbd5e1" />));
  for (let f = 0; f <= FRETS; f++) {
    const x = left + f * fw;
    els.push(<line key={`f${f}`} x1={x} y1={top} x2={x} y2={top + 5 * sg} stroke={f === 0 ? "#1e293b" : "#94a3b8"} strokeWidth={f === 0 ? 3 : 0.8} />);
    if (f > 0) els.push(<text key={`fn${f}`} x={left + (f - 0.5) * fw} y={height - 4} fontSize={8} fill="#64748b" textAnchor="middle">{f}</text>);
  }
  for (let s = 0; s < 6; s++) {
    els.push(<line key={`s${s}`} x1={left} y1={yOf(s)} x2={left + FRETS * fw} y2={yOf(s)} stroke="#cbd5e1" strokeWidth={0.9} />);
    const openP = STRING_MIDI[s];
    if (lit(openP)) els.push(<circle key={`o${s}`} cx={left - 9} cy={yOf(s)} r={5} fill={pc(openP) === root ? "#2563eb" : "#38bdf8"} />);
    for (let f = 1; f <= FRETS; f++) {
      const p = openP + f;
      if (lit(p)) els.push(<circle key={`d${s}-${f}`} cx={left + (f - 0.5) * fw} cy={yOf(s)} r={6} fill={pc(p) === root ? "#2563eb" : "#38bdf8"} />);
    }
  }
  return <svg className="diagram-guitar-neck" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="xMidYMid meet" role="img" aria-label="guitar neck">{els}</svg>;
}

// ===========================================================================
export default function ChordDiagram({
  root, quality, activePitches, range, neck = false,
}: {
  root: string;
  quality: string;
  activePitches?: number[];
  range?: [number, number];
  neck?: boolean;
}) {
  const live = !!(activePitches && activePitches.length);
  const exact = useMemo(() => new Set(activePitches || []), [activePitches]);
  const tones = useMemo(() => {
    const offs = TEMPLATES[quality] || TEMPLATES.maj;
    return new Set(offs.map((o) => (rootPc(root) + o) % 12));
  }, [root, quality]);
  const rpc = live ? (activePitches!.length ? pc(Math.min(...activePitches!)) : -1) : rootPc(root) % 12;
  const lit = (p: number) => (live ? exact.has(p) : tones.has(pc(p)));

  const [lo, hi] = useMemo(() => {
    let a = range ? range[0] : 48, b = range ? range[1] : 83;
    a = octaveFloor(a); b = octaveFloor(b) + 11;
    while (b - a < 35) b += 12;
    return [Math.max(21, a), Math.min(108, b)];
  }, [range]);

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
  return (
    <div className="diagrams diagrams-wide">
      <div className="diagram-card">
        <div className="diagram-title">Piano{live ? " · live" : ""}</div>
        <WidePiano lo={lo} hi={hi} lit={lit} root={rpc} />
      </div>
      <div className="diagram-card">
        <div className="diagram-title">Guitar neck{live ? " · live" : ""}</div>
        <FullNeck lit={lit} root={rpc} />
      </div>
    </div>
  );
}
