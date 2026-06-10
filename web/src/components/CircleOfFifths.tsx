import { MODES, rootPc } from "../chordLabels";

// Circle-of-fifths key picker. Click a key to set the tonic; the mode dropdown
// re-homes the highlighted "parent major" (the key signature the mode borrows)
// and the centre readout. Major key spellings around the wheel (sharps top-
// right, flats top-left), in fifths order from C at 12 o'clock.
const CIRCLE = [
  { name: "C", pc: 0 }, { name: "G", pc: 7 }, { name: "D", pc: 2 }, { name: "A", pc: 9 },
  { name: "E", pc: 4 }, { name: "B", pc: 11 }, { name: "F#", pc: 6 }, { name: "Db", pc: 1 },
  { name: "Ab", pc: 8 }, { name: "Eb", pc: 3 }, { name: "Bb", pc: 10 }, { name: "F", pc: 5 },
];
// Signed key signature of each MAJOR key by pitch class (+sharps / -flats).
const SIG: Record<number, number> = {
  0: 0, 7: 1, 2: 2, 9: 3, 4: 4, 11: 5, 6: 6, 1: -5, 8: -4, 3: -3, 10: -2, 5: -1,
};
// Major-scale degree each mode starts on → the parent major is `degree` below.
const MODE_OFFSET = [0, 2, 4, 5, 7, 9, 11];

export default function CircleOfFifths({
  tonic, mode, onTonic, onMode, onClose,
}: {
  tonic: string;
  mode: string;
  onTonic: (t: string) => void;
  onMode: (m: string) => void;
  onClose: () => void;
}) {
  const tonicPc = rootPc(tonic);
  const modeIdx = Math.max(0, MODES.findIndex((m) => m.id === mode));
  const parentPc = ((tonicPc - MODE_OFFSET[modeIdx]) % 12 + 12) % 12;
  const sig = SIG[parentPc] ?? 0;
  const sigText = sig === 0 ? "♮ no ♯/♭" : sig > 0 ? `${sig}♯` : `${-sig}♭`;
  const cx = 100, cy = 100, R = 78;

  return (
    <div className="cof-backdrop" onClick={onClose}>
      <div className="cof-popup" onClick={(e) => e.stopPropagation()}>
        <div className="cof-head">
          <span className="cof-title">Key</span>
          <select value={mode} onChange={(e) => onMode(e.target.value)}>
            {MODES.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
          </select>
          <button className="cof-close" onClick={onClose} aria-label="Close">✕</button>
        </div>
        <svg viewBox="0 0 200 200" className="cof-svg" role="img" aria-label="circle of fifths">
          <circle cx={cx} cy={cy} r={R + 15} className="cof-ring" />
          {CIRCLE.map((k, i) => {
            const a = ((i * 30 - 90) * Math.PI) / 180;
            const x = cx + R * Math.cos(a), y = cy + R * Math.sin(a);
            const isTonic = k.pc === tonicPc;
            const isParent = k.pc === parentPc && !isTonic;
            return (
              <g key={k.pc} className={`cof-key${isTonic ? " tonic" : isParent ? " parent" : ""}`}
                onClick={() => onTonic(k.name)} role="button" tabIndex={0}>
                <circle cx={x} cy={y} r={15} />
                <text x={x} y={y + 4} textAnchor="middle">{k.name}</text>
              </g>
            );
          })}
          <text x={cx} y={cy - 6} textAnchor="middle" className="cof-c-key">{tonic}</text>
          <text x={cx} y={cy + 9} textAnchor="middle" className="cof-c-mode">{MODES[modeIdx].label.split(" ")[0]}</text>
          <text x={cx} y={cy + 24} textAnchor="middle" className="cof-c-sig">{sigText}</text>
        </svg>
        <div className="cof-hint">tonic · parent major (key signature)</div>
      </div>
    </div>
  );
}
