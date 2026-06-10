import { useEffect, useMemo, useRef } from "react";
import type { RollNote } from "./NotationRoll";
import type { TabNote } from "../guitarTab";
import { stringLabelsFor, STANDARD_GUITAR } from "../guitarTab";
import PickerField from "./PickerField";
import InstrumentIcon from "./InstrumentIcon";

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

// Nice open-position voicings (preferred when the root has one).
const OPEN: Record<string, number[]> = {
  "C:maj": [-1, 3, 2, 0, 1, 0], "C:7": [-1, 3, 2, 3, 1, 0], "C:maj7": [-1, 3, 2, 0, 0, 0],
  "A:maj": [-1, 0, 2, 2, 2, 0], "A:min": [-1, 0, 2, 2, 1, 0], "A:7": [-1, 0, 2, 0, 2, 0],
  "A:min7": [-1, 0, 2, 0, 1, 0], "A:maj7": [-1, 0, 2, 1, 2, 0],
  "G:maj": [3, 2, 0, 0, 0, 3], "G:7": [3, 2, 0, 0, 0, 1],
  "E:maj": [0, 2, 2, 1, 0, 0], "E:min": [0, 2, 2, 0, 0, 0], "E:7": [0, 2, 0, 1, 0, 0], "E:min7": [0, 2, 0, 0, 0, 0],
  "D:maj": [-1, -1, 0, 2, 3, 2], "D:min": [-1, -1, 0, 2, 3, 1], "D:7": [-1, -1, 0, 2, 1, 2],
  "D:min7": [-1, -1, 0, 2, 1, 1], "D:maj7": [-1, -1, 0, 2, 2, 2],
};
// Movable barre shapes as fret offsets from the barre, strings low→high
// (E A D G B e); -1 = muted. Two forms per quality (root on the 6th-string =
// "E shape", or 5th-string = "A shape"); we pick whichever sits lowest on the
// neck so each chord shows its easiest CORRECT voicing — no maj/min fakes.
const E_OPEN_PC = 4, A_OPEN_PC = 9;
const E_SHAPE: Record<string, number[]> = {
  maj: [0, 2, 2, 1, 0, 0], min: [0, 2, 2, 0, 0, 0], "7": [0, 2, 0, 1, 0, 0],
  maj7: [0, 2, 1, 1, 0, 0], min7: [0, 2, 0, 0, 0, 0], "6": [0, 2, 2, 1, 2, 0],
  min6: [0, 2, 2, 0, 2, 0], sus4: [0, 2, 2, 2, 0, 0], sus2: [0, 2, 4, 4, 0, 0],
  aug: [0, 3, 2, 1, 1, 0], dim7: [0, 1, 2, 0, 2, 0],
};
const A_SHAPE: Record<string, number[]> = {
  maj: [-1, 0, 2, 2, 2, 0], min: [-1, 0, 2, 2, 1, 0], "7": [-1, 0, 2, 0, 2, 0],
  maj7: [-1, 0, 2, 1, 2, 0], min7: [-1, 0, 2, 0, 1, 0], "6": [-1, 0, 2, 2, 2, 2],
  min6: [-1, 0, 2, 2, 1, 2], sus4: [-1, 0, 2, 2, 3, 0], sus2: [-1, 0, 2, 2, 0, 0],
  aug: [-1, 0, 3, 2, 2, 1], dim7: [-1, 0, 1, 2, 1, 2], m7b5: [-1, 0, 1, 0, 1, -1],
  dim: [-1, 0, 1, 2, 1, -1],
};
function guitarShape(root: string, quality: string): { frets: number[]; approx: boolean } {
  const q = TEMPLATES[quality] ? quality : "maj";
  const approx = !TEMPLATES[quality];               // unknown quality only
  const open = OPEN[`${root}:${q}`];
  if (open) return { frets: open, approx };
  const rpc = rootPc(root);
  const cands: { barre: number; frets: number[] }[] = [];
  if (E_SHAPE[q]) {
    const b = ((rpc - E_OPEN_PC) % 12 + 12) % 12;
    cands.push({ barre: b, frets: E_SHAPE[q].map((o) => (o < 0 ? -1 : b + o)) });
  }
  if (A_SHAPE[q]) {
    const b = ((rpc - A_OPEN_PC) % 12 + 12) % 12;
    cands.push({ barre: b, frets: A_SHAPE[q].map((o) => (o < 0 ? -1 : b + o)) });
  }
  if (!cands.length) {
    const b = ((rpc - E_OPEN_PC) % 12 + 12) % 12;
    return { frets: E_SHAPE.maj.map((o) => b + o), approx: true };
  }
  cands.sort((x, y) => x.barre - y.barre);          // lowest on the neck wins
  return { frets: cands[0].frets, approx };
}
// `shapeRoot`/`quality` are the SHAPE to finger (already transposed for the
// capo by the caller). `capo` only changes how the top of the diagram is drawn:
// with a capo the nut becomes the capo bar (the shape's "open" strings are
// fretted at the capo), so frets are read relative to it.
function ChordShapeGuitar({ root, quality, capo = 0 }: { root: string; quality: string; capo?: number }) {
  const { frets, approx } = guitarShape(root, quality);
  const played = frets.filter((f) => f > 0);
  const maxF = played.length ? Math.max(...played) : 1, minF = played.length ? Math.min(...played) : 1;
  const baseFret = maxF <= 4 ? 1 : minF, span = Math.max(4, maxF - baseFret + 1);
  const left = 26, top = 18, sw = 18, fh = 26;
  const width = left + 5 * sw + 16, height = top + span * fh + 12;
  const atNut = baseFret === 1;
  const dots = frets.map((f, s) => {
    const x = left + s * sw;
    if (f < 0) return <text key={s} x={x} y={top - 6} className="g-x">×</text>;
    if (f === 0) return <circle key={s} cx={x} cy={top - 9} r={4} className="g-o" />;
    return <circle key={s} cx={x} cy={top + (f - baseFret + 0.5) * fh} r={6} className="g-dot" />;
  });
  return (
    <svg className="diagram-guitar" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="xMidYMid meet" role="img" aria-label="guitar chord">
      {atNut
        ? <rect x={left} y={top} width={5 * sw} height={capo > 0 ? 6 : 3} rx={capo > 0 ? 3 : 0}
            fill={capo > 0 ? "#d97706" : "#1e293b"} />
        : <text x={left - 10} y={top + fh * 0.6} className="g-fret">{capo > 0 ? capo + baseFret - 1 : baseFret}fr</text>}
      {capo > 0 && atNut && <text x={left - 10} y={top + 6} className="g-fret" fill="#d97706">{capo}</text>}
      {Array.from({ length: span + 1 }, (_, i) => <line key={`f${i}`} x1={left} y1={top + i * fh} x2={left + 5 * sw} y2={top + i * fh} stroke="#94a3b8" strokeWidth={0.8} />)}
      {Array.from({ length: 6 }, (_, i) => <line key={`s${i}`} x1={left + i * sw} y1={top} x2={left + i * sw} y2={top + span * fh} stroke="#cbd5e1" strokeWidth={0.8} />)}
      {dots}
      {approx && <text x={width / 2} y={height - 2} className="g-approx" textAnchor="middle">approx</text>}
    </svg>
  );
}

// ===== LIVE MODE (fingerboard + wide piano, DOM-toggled highlights) =========
const INLAYS = new Set([3, 5, 7, 9, 12, 15, 17, 19]);
function octaveFloor(p: number) { return Math.floor(p / 12) * 12; }

type PartOpt = { idx: number; name: string };

function PartSelect({ value, opts, onChange }: {
  value: number; opts: PartOpt[]; onChange: (i: number) => void;
}) {
  return (
    <span onClick={(e) => e.stopPropagation()}>
      <PickerField value={String(value)} label="Part" placeholder="—"
        fullWidth={false} className="part-pick"
        options={opts.map((o) => ({ id: String(o.idx), label: o.name,
          icon: <InstrumentIcon name={o.name} size={15} /> }))}
        onChange={(id) => onChange(Number(id))} />
    </span>
  );
}

export interface PartOption { idx: number; name: string }

// One live diagram card — a piano, or a string-instrument fingerboard. The
// piano lights by pitch; the neck lights the EXACT fret played (tab), the same
// positions the Tab view shows, on a fingerboard drawn from the instrument's
// own tuning (guitar 6/7, bass 4/5, violin, cello, mandolin, …). Multiple of
// these can be shown at once (one per channel/instrument).
export function LiveDiagram({
  kind, notes, tab, range, audioRef, parts, partIdx, onPartIdx, onRemove,
  tuning = STANDARD_GUITAR, frets = 19, instLabel = "Guitar",
  instOptions, instId, onInst,
}: {
  kind: "piano" | "neck";
  notes: RollNote[];
  tab?: TabNote[];
  range?: [number, number];
  audioRef?: React.RefObject<HTMLAudioElement | null>;
  parts: PartOption[];
  partIdx: number;
  onPartIdx: (i: number) => void;
  onRemove?: () => void;
  // neck only:
  tuning?: number[];
  frets?: number;
  instLabel?: string;
  instOptions?: { id: string; label: string }[];
  instId?: string;
  onInst?: (id: string) => void;
}) {
  const [lo, hi] = useMemo(() => {
    let a = range ? range[0] : 48, b = range ? range[1] : 83;
    a = octaveFloor(a); b = octaveFloor(b) + 11;
    while (b - a < 35) b += 12;
    return [Math.max(21, a), Math.min(108, b)];
  }, [range]);

  const byPitch = useRef<Map<number, Element[]>>(new Map());
  const byPos = useRef<Map<string, Element>>(new Map());
  const putPitch = (p: number, el: Element | null) => {
    if (!el) return;
    const a = byPitch.current.get(p) || []; a.push(el); byPitch.current.set(p, a);
  };
  const putPos = (s: number, f: number, el: Element | null) => {
    if (el) byPos.current.set(`${s}:${f}`, el);
  };

  // ---- build the SVG for this kind ----
  let svg: React.ReactNode = null;
  if (kind === "piano") {
    const wk = 15, wh = 66, bk = 9, bh = 40;
    const whites: number[] = [];
    for (let p = lo; p <= hi; p++) if (isWhite(p)) whites.push(p);
    const idx = new Map<number, number>(); whites.forEach((p, i) => idx.set(p, i));
    const pianoW = Math.max(1, whites.length * wk);
    const els: React.ReactNode[] = [];
    whites.forEach((p, i) => {
      els.push(<rect key={`w${p}`} ref={(el) => putPitch(p, el)} className="pk w" x={i * wk} y={0}
        width={wk - 1} height={wh} rx={2} fill="#fbfdff" stroke="#1e293b" strokeWidth={0.6} />);
      if (pc(p) === 0) els.push(<text key={`l${p}`} x={i * wk + wk / 2} y={wh - 4} fontSize={7}
        fill="#64748b" textAnchor="middle">C{Math.floor(p / 12) - 1}</text>);
    });
    for (let p = lo; p <= hi; p++) {
      if (isWhite(p)) continue;
      const below = idx.get(p - 1); if (below == null) continue;
      els.push(<rect key={`b${p}`} ref={(el) => putPitch(p, el)} className="pk b"
        x={below * wk + wk - bk / 2} y={0} width={bk} height={bh} rx={1.5} fill="#16202e" stroke="#0b1118" strokeWidth={0.6} />);
    }
    svg = <svg className="diagram-piano-wide" viewBox={`0 0 ${pianoW} ${wh}`} preserveAspectRatio="xMidYMid meet" aria-label="piano">{els}</svg>;
  } else {
    const nl = 30, nt = 12, fw = 26, sg = 14;
    const nStr = tuning.length;
    const labels = stringLabelsFor(tuning);
    const lastY = nt + (nStr - 1) * sg;
    const neckW = nl + frets * fw + 10, neckH = lastY + 18;
    const yOf = (s: number) => nt + s * sg;
    const els: React.ReactNode[] = [];
    INLAYS.forEach((f) => { if (f <= frets) els.push(<circle key={`in${f}`} cx={nl + (f - 0.5) * fw} cy={nt + ((nStr - 1) / 2) * sg} r={2.5} fill="#cbd5e1" />); });
    for (let f = 0; f <= frets; f++) {
      const x = nl + f * fw;
      els.push(<line key={`f${f}`} x1={x} y1={nt} x2={x} y2={lastY} stroke={f === 0 ? "#1e293b" : "#94a3b8"} strokeWidth={f === 0 ? 3 : 0.8} />);
      if (f > 0) els.push(<text key={`fn${f}`} x={nl + (f - 0.5) * fw} y={neckH - 4} fontSize={8} fill="#64748b" textAnchor="middle">{f}</text>);
    }
    for (let s = 0; s < nStr; s++) {
      els.push(<text key={`sl${s}`} x={6} y={yOf(s) + 3} fontSize={8} fill="#94a3b8"
        fontFamily="ui-monospace, Menlo, monospace">{labels[s]}</text>);
      els.push(<line key={`s${s}`} x1={nl} y1={yOf(s)} x2={nl + frets * fw} y2={yOf(s)} stroke="#cbd5e1" strokeWidth={0.9} />);
      for (let f = 0; f <= frets; f++) {
        const cx = f === 0 ? nl - 9 : nl + (f - 0.5) * fw;
        els.push(<circle key={`d${s}-${f}`} ref={(el) => putPos(s, f, el)} className="nd" cx={cx} cy={yOf(s)} r={f === 0 ? 5 : 6} />);
      }
    }
    svg = <svg className="diagram-guitar-neck" viewBox={`0 0 ${neckW} ${neckH}`} preserveAspectRatio="xMidYMid meet" aria-label="fingerboard">{els}</svg>;
  }

  // ---- highlight driver: piano by pitch, neck by exact tab position ----
  const isNeck = kind === "neck";
  useEffect(() => {
    const pitchMap = byPitch.current, posMap = byPos.current;
    const litPitch = (p: number, on: boolean) => pitchMap.get(p)?.forEach((el) => el.classList.toggle("lit", on));
    const litPos = (k: string, on: boolean) => posMap.get(k)?.classList.toggle("lit", on);
    pitchMap.forEach((a) => a.forEach((el) => el.classList.remove("lit")));
    posMap.forEach((el) => el.classList.remove("lit"));

    const onPitch = new Set<number>(), onPosSet = new Set<string>();
    let raf = 0;
    const tick = () => {
      const t = audioRef?.current?.currentTime ?? 0;
      if (isNeck) {
        const snd = new Set<string>();
        for (const n of tab ?? []) if (t >= n.start && t < n.start + n.dur) snd.add(`${n.string}:${n.fret}`);
        for (const k of onPosSet) if (!snd.has(k)) { litPos(k, false); onPosSet.delete(k); }
        for (const k of snd) if (!onPosSet.has(k)) { litPos(k, true); onPosSet.add(k); }
      } else {
        const snd = new Set<number>();
        for (const n of notes) if (t >= n.start && t < n.start + n.dur) snd.add(n.pitch);
        for (const p of onPitch) if (!snd.has(p)) { litPitch(p, false); onPitch.delete(p); }
        for (const p of snd) if (!onPitch.has(p)) { litPitch(p, true); onPitch.add(p); }
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [notes, tab, isNeck, audioRef, lo, hi]);

  // Reset the ref maps each render so stale element refs don't accumulate.
  byPitch.current = new Map();
  byPos.current = new Map();

  const live = isNeck ? !!(tab && tab.length) : notes.length > 0;
  return (
    <div className="diagram-card">
      <div className="diagram-title">
        <span>{isNeck ? instLabel : "Piano"}{live ? " · live" : ""}</span>
        <span className="dc-head-ctl">
          {isNeck && instOptions && onInst && (
            <span onClick={(e) => e.stopPropagation()}>
              <PickerField value={instId ?? ""} label="Instrument / tuning"
                fullWidth={false} className="part-pick"
                options={instOptions.map((o) => ({ id: o.id, label: o.label,
                  icon: <InstrumentIcon name={o.label} size={15} /> }))}
                onChange={onInst} />
            </span>
          )}
          <PartSelect value={partIdx} opts={parts} onChange={onPartIdx} />
          {onRemove && <button className="dc-remove" onClick={onRemove} title="Remove this diagram" aria-label="Remove">✕</button>}
        </span>
      </div>
      {svg}
    </div>
  );
}

// ===========================================================================
// Chord mode: how to PLAY the current chord (shape + tones), optionally capoed.
export default function ChordDiagram({
  root, quality, capo = 0,
}: {
  root: string;
  quality: string;
  capo?: number;   // finger the shape this many frets lower (capo)
}) {
  const tones = useMemo(() => {
    const offs = TEMPLATES[quality] || TEMPLATES.maj;
    return new Set(offs.map((o) => (rootPc(root) + o) % 12));
  }, [root, quality]);

  // With a capo, the shape you finger is the chord `capo` semitones lower
  // (e.g. play a C shape with capo 2 to sound D). The piano shows real tones.
  const gRoot = FLAT_TO_SHARP[root] ?? root;
  const shapeRoot = capo > 0 ? NOTE_NAMES[((rootPc(gRoot) - capo) % 12 + 12) % 12] : gRoot;
  return (
    <div className="diagrams">
      <div className="diagram-card">
        <div className="diagram-title">Piano</div>
        <CompactPiano tones={tones} root={rootPc(root) % 12} />
      </div>
      <div className="diagram-card">
        <div className="diagram-title">Guitar{capo > 0 ? ` · capo ${capo}` : ""}</div>
        <ChordShapeGuitar root={shapeRoot} quality={quality} capo={capo} />
        {capo > 0 && <div className="g-capo-note">play {shapeRoot} {quality} shape</div>}
      </div>
    </div>
  );
}
