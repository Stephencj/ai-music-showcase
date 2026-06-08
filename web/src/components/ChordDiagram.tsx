import { useMemo } from "react";

// Pitch-class names (sharps), matching the backend NOTE_NAMES order.
const NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
const FLAT_TO_SHARP: Record<string, string> = {
  Db: "C#", Eb: "D#", Gb: "F#", Ab: "G#", Bb: "A#", Cb: "B", Fb: "E",
};

// Chord pitch-class templates (offsets from root), mirroring chord_analysis.py.
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

// ---- Piano ----------------------------------------------------------------
// Two octaves from C. White keys carry pcs [0,2,4,5,7,9,11]; black keys sit
// between them at pcs [1,3,6,8,10].
const WHITE_PCS = [0, 2, 4, 5, 7, 9, 11];
const BLACK_AFTER = [0, 1, 3, 4, 5]; // white-key indices that have a black key after them

function Piano({ tones, root }: { tones: Set<number>; root: number }) {
  const octaves = 2;
  const wk = 22; // white key width
  const wh = 96; // white key height
  const bk = 13; // black key width
  const bh = 60;
  const whiteCount = WHITE_PCS.length * octaves;
  const width = whiteCount * wk;

  const whites = [];
  const blacks = [];
  for (let o = 0; o < octaves; o++) {
    for (let i = 0; i < WHITE_PCS.length; i++) {
      const pc = WHITE_PCS[i];
      const idx = o * WHITE_PCS.length + i;
      const x = idx * wk;
      const on = tones.has(pc);
      const isRoot = on && pc === root;
      whites.push(
        <g key={`w${idx}`}>
          <rect x={x} y={0} width={wk - 1} height={wh} rx={2}
            fill={isRoot ? "#2563eb" : on ? "#7eb0ff" : "#fbfdff"}
            stroke="#1e293b" strokeWidth={0.7} />
          {on && <circle cx={x + wk / 2} cy={wh - 12} r={4}
            fill={isRoot ? "#fff" : "#1e3a8a"} />}
        </g>
      );
      if (BLACK_AFTER.includes(i)) {
        const bpc = (pc + 1) % 12;
        const bx = x + wk - bk / 2;
        const bon = tones.has(bpc);
        const bIsRoot = bon && bpc === root;
        blacks.push(
          <g key={`b${idx}`}>
            <rect x={bx} y={0} width={bk} height={bh} rx={1.5}
              fill={bIsRoot ? "#2563eb" : bon ? "#3b6fd6" : "#16202e"}
              stroke="#0b1118" strokeWidth={0.7} />
            {bon && <circle cx={bx + bk / 2} cy={bh - 9} r={3.2}
              fill="#fff" />}
          </g>
        );
      }
    }
  }
  return (
    <svg className="diagram-piano" viewBox={`0 0 ${width} ${wh}`}
      preserveAspectRatio="xMidYMid meet" role="img" aria-label="piano chord">
      {whites}{blacks}
    </svg>
  );
}

// ---- Guitar ---------------------------------------------------------------
// Open string pitch classes, low → high (EADGBE).
const STRING_PCS = [4, 9, 2, 7, 11, 4];
// Familiar open shapes for the common keys (low E → high E; -1 = muted).
const OPEN: Record<string, number[]> = {
  "C:maj": [-1, 3, 2, 0, 1, 0], "C:7": [-1, 3, 2, 3, 1, 0], "C:maj7": [-1, 3, 2, 0, 0, 0],
  "A:maj": [-1, 0, 2, 2, 2, 0], "A:min": [-1, 0, 2, 2, 1, 0], "A:7": [-1, 0, 2, 0, 2, 0],
  "A:min7": [-1, 0, 2, 0, 1, 0], "A:maj7": [-1, 0, 2, 1, 2, 0],
  "G:maj": [3, 2, 0, 0, 0, 3], "G:7": [3, 2, 0, 0, 0, 1],
  "E:maj": [0, 2, 2, 1, 0, 0], "E:min": [0, 2, 2, 0, 0, 0], "E:7": [0, 2, 0, 1, 0, 0],
  "E:min7": [0, 2, 0, 0, 0, 0],
  "D:maj": [-1, -1, 0, 2, 3, 2], "D:min": [-1, -1, 0, 2, 3, 1], "D:7": [-1, -1, 0, 2, 1, 2],
  "D:min7": [-1, -1, 0, 2, 1, 1], "D:maj7": [-1, -1, 0, 2, 2, 2],
};
// Movable E-shape barre templates (offsets from barre fret), low → high.
const E_SHAPE: Record<string, number[]> = {
  maj: [0, 2, 2, 1, 0, 0], min: [0, 2, 2, 0, 0, 0], "7": [0, 2, 0, 1, 0, 0],
  min7: [0, 2, 0, 0, 0, 0], maj7: [0, 2, 1, 1, 0, 0],
};
// Reduce qualities we don't draw to the closest shape we do.
const GUITAR_REDUCE: Record<string, string> = {
  "6": "maj", min6: "min", dim: "min", aug: "maj", sus2: "maj", sus4: "maj",
  dim7: "min", m7b5: "min7",
};

function guitarShape(root: string, quality: string): { frets: number[]; approx: boolean } {
  const q0 = TEMPLATES[quality] ? quality : "maj";
  let q = q0;
  let approx = false;
  const open = OPEN[`${root}:${q}`];
  if (open) return { frets: open, approx: false };
  if (!E_SHAPE[q]) {
    q = GUITAR_REDUCE[q] || "maj";
    approx = q !== q0;
  }
  if (!E_SHAPE[q]) { q = "maj"; approx = true; }
  // Barre fret = where the root sits on the low-E string.
  const barre = ((rootPc(root) - STRING_PCS[0]) % 12 + 12) % 12;
  const tmpl = E_SHAPE[q];
  const frets = tmpl.map((o) => barre + o);
  return { frets, approx };
}

function Guitar({ root, quality }: { root: string; quality: string }) {
  const { frets, approx } = guitarShape(root, quality);
  const played = frets.filter((f) => f > 0);
  const minF = played.length ? Math.min(...played) : 1;
  const maxF = played.length ? Math.max(...played) : 1;
  // Window of frets to draw (at least 4).
  const baseFret = maxF <= 4 ? 1 : minF;
  const span = Math.max(4, maxF - baseFret + 1);

  const left = 26, top = 18, sw = 18, fh = 26;
  const width = left + 5 * sw + 16;
  const height = top + span * fh + 12;

  const dots = frets.map((f, s) => {
    const x = left + s * sw;
    if (f < 0) return <text key={s} x={x} y={top - 6} className="g-x">×</text>;
    if (f === 0) return <circle key={s} cx={x} cy={top - 9} r={4} className="g-o" />;
    const cy = top + (f - baseFret + 0.5) * fh;
    return <circle key={s} cx={x} cy={cy} r={6} className="g-dot" />;
  });

  return (
    <svg className="diagram-guitar" viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="xMidYMid meet" role="img" aria-label="guitar chord">
      {/* nut or starting-fret marker */}
      {baseFret === 1
        ? <rect x={left} y={top} width={5 * sw} height={3} fill="#1e293b" />
        : <text x={left - 10} y={top + fh * 0.6} className="g-fret">{baseFret}fr</text>}
      {/* frets */}
      {Array.from({ length: span + 1 }, (_, i) => (
        <line key={`f${i}`} x1={left} y1={top + i * fh} x2={left + 5 * sw} y2={top + i * fh}
          stroke="#94a3b8" strokeWidth={0.8} />
      ))}
      {/* strings */}
      {Array.from({ length: 6 }, (_, i) => (
        <line key={`s${i}`} x1={left + i * sw} y1={top} x2={left + i * sw} y2={top + span * fh}
          stroke="#cbd5e1" strokeWidth={0.8} />
      ))}
      {dots}
      {approx && <text x={width / 2} y={height - 2} className="g-approx" textAnchor="middle">approx</text>}
    </svg>
  );
}

export default function ChordDiagram({ root, quality }: { root: string; quality: string }) {
  const tones = useMemo(() => {
    const offs = TEMPLATES[quality] || TEMPLATES.maj;
    return new Set(offs.map((o) => (rootPc(root) + o) % 12));
  }, [root, quality]);

  return (
    <div className="diagrams">
      <div className="diagram-card">
        <div className="diagram-title">Piano</div>
        <Piano tones={tones} root={rootPc(root) % 12} />
      </div>
      <div className="diagram-card">
        <div className="diagram-title">Guitar</div>
        <Guitar root={FLAT_TO_SHARP[root] ?? root} quality={quality} />
      </div>
    </div>
  );
}
