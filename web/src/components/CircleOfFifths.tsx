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
const SHARP = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
// Signed key signature of each MAJOR key by pitch class (+sharps / -flats).
const SIG: Record<number, number> = {
  0: 0, 7: 1, 2: 2, 9: 3, 4: 4, 11: 5, 6: 6, 1: -5, 8: -4, 3: -3, 10: -2, 5: -1,
};
// Semitones from a scale's tonic DOWN to its parent major (for the key sig).
// Non-modal scales borrow their relative major/minor signature.
const PARENT_OFFSET: Record<string, number> = {
  major: 0, dorian: 2, phrygian: 4, lydian: 5, mixolydian: 7, minor: 9, locrian: 11,
  harmonic_minor: 9, melodic_minor: 9, pentatonic_minor: 9, blues: 9, pentatonic_major: 0,
};

export default function CircleOfFifths({
  tonic, mode, onTonic, onMode, onClose, options, sharps,
}: {
  tonic: string;
  mode: string;
  onTonic: (t: string) => void;
  onMode: (m: string) => void;
  onClose: () => void;
  options?: { id: string; label: string }[];   // scale/mode dropdown (default: church modes)
  sharps?: boolean;                              // emit sharp key names (backend-safe for Generate)
}) {
  const opts = options ?? MODES.map((m) => ({ id: m.id, label: m.label }));
  const modeLabel = (opts.find((o) => o.id === mode)?.label || mode).replace(/_/g, " ");
  const tonicPc = rootPc(tonic);
  const parentPc = ((tonicPc - (PARENT_OFFSET[mode] ?? 0)) % 12 + 12) % 12;
  const sig = SIG[parentPc] ?? 0;
  const sigText = sig === 0 ? "♮ no ♯/♭" : sig > 0 ? `${sig}♯` : `${-sig}♭`;
  const cx = 100, cy = 100, R = 78;

  return (
    <div className="cof-backdrop" onClick={onClose}>
      <div className="cof-popup" onClick={(e) => e.stopPropagation()}>
        <div className="cof-head">
          <span className="cof-title">Key</span>
          <select value={mode} onChange={(e) => onMode(e.target.value)}>
            {opts.map((m) => <option key={m.id} value={m.id}>{m.label.replace(/_/g, " ")}</option>)}
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
                onClick={() => onTonic(sharps ? SHARP[k.pc] : k.name)} role="button" tabIndex={0}>
                <circle cx={x} cy={y} r={15} />
                <text x={x} y={y + 4} textAnchor="middle">{k.name}</text>
              </g>
            );
          })}
          <text x={cx} y={cy - 6} textAnchor="middle" className="cof-c-key">{tonic}</text>
          <text x={cx} y={cy + 9} textAnchor="middle" className="cof-c-mode">{modeLabel}</text>
          <text x={cx} y={cy + 24} textAnchor="middle" className="cof-c-sig">{sigText}</text>
        </svg>
        <div className="cof-hint">tonic · parent major (key signature)</div>
      </div>
    </div>
  );
}
