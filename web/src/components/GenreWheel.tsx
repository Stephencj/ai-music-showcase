import { useState } from "react";
import type { GenreFamily } from "../types";

// A radial genre picker (circle-of-fifths style): the ring is divided into
// family wedges; tap a wedge to reveal that family's genres, tap a genre to
// pick it. The hub shows the current selection.
const SHORT: Record<string, string> = {
  "Rock & Metal": "Rock", "Blues & Jazz": "Jazz", "Soul & Funk": "Funk",
  "Hip-Hop & R&B": "Hip-Hop", "Latin & World": "World",
  "Cinematic & Classical": "Cinematic",
};

export default function GenreWheel({ families, value, onChange, onClose }: {
  families: GenreFamily[];
  value: string;
  onChange: (id: string) => void;
  onClose: () => void;
}) {
  const curFamIdx = families.findIndex((f) => f.genres.some((g) => g.id === value));
  const [active, setActive] = useState(curFamIdx >= 0 ? curFamIdx : 0);
  const curName = families.flatMap((f) => f.genres).find((g) => g.id === value)?.name || "—";

  const cx = 110, cy = 110, R = 104, rHole = 48;
  const n = Math.max(1, families.length);
  const step = 360 / n;

  const wedge = (i: number) => {
    const a0 = (i * step - 90) * Math.PI / 180;
    const a1 = ((i + 1) * step - 90) * Math.PI / 180;
    const p = (r: number, a: number) => `${cx + r * Math.cos(a)},${cy + r * Math.sin(a)}`;
    const large = step > 180 ? 1 : 0;
    return `M${p(rHole, a0)} L${p(R, a0)} A${R},${R} 0 ${large} 1 ${p(R, a1)} `
      + `L${p(rHole, a1)} A${rHole},${rHole} 0 ${large} 0 ${p(rHole, a0)} Z`;
  };
  const labelPos = (i: number) => {
    const a = ((i + 0.5) * step - 90) * Math.PI / 180, r = (R + rHole) / 2;
    return { x: cx + r * Math.cos(a), y: cy + r * Math.sin(a) };
  };

  return (
    <div className="cof-backdrop" onClick={onClose}>
      <div className="gw-popup" onClick={(e) => e.stopPropagation()}>
        <div className="cof-head">
          <span className="cof-title">Genre</span>
          <button className="cof-close" onClick={onClose} aria-label="Close">✕</button>
        </div>
        <svg viewBox="0 0 220 220" className="gw-svg" role="img" aria-label="genre wheel">
          {families.map((f, i) => {
            const p = labelPos(i);
            const sel = i === active;
            const hasCur = i === curFamIdx;
            return (
              <g key={f.family} className={"gw-wedge" + (sel ? " active" : "")}
                onClick={() => setActive(i)} role="button" tabIndex={0}>
                <path d={wedge(i)} fill={f.color} fillOpacity={sel ? 0.96 : 0.45}
                  stroke={hasCur ? "#fff" : "rgba(0,0,0,0.35)"} strokeWidth={hasCur ? 2 : 1} />
                <text x={p.x} y={p.y + 3} textAnchor="middle" className="gw-wlabel">
                  {SHORT[f.family] || f.family}</text>
              </g>
            );
          })}
          <circle cx={cx} cy={cy} r={rHole - 3} className="gw-hub" />
          <text x={cx} y={cy - 1} textAnchor="middle" className="gw-cur">{curName}</text>
          <text x={cx} y={cy + 13} textAnchor="middle" className="gw-cur-fam">
            {curFamIdx >= 0 ? (SHORT[families[curFamIdx].family] || families[curFamIdx].family) : ""}
          </text>
        </svg>
        <div className="gw-fam-name" style={{ color: families[active]?.color }}>
          {families[active]?.family}
        </div>
        <div className="gw-genres">
          {(families[active]?.genres || []).map((g) => (
            <button key={g.id}
              className={"gw-genre" + (g.id === value ? " sel" : "")}
              style={g.id === value ? { background: families[active].color, borderColor: families[active].color } : { borderColor: families[active].color }}
              onClick={() => { onChange(g.id); onClose(); }}>{g.name}</button>
          ))}
        </div>
      </div>
    </div>
  );
}
