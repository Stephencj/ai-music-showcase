// Shared mixing desk: per-track channel strips — mute, volume fader, and an
// EQ·FX panel (3-band EQ, compressor ratio, reverb/delay/chorus/distortion
// sends). Settings are RELATIVE to the engine's family baseline (0/off = no
// change). Used by the producer modal and the ear-training challenge.
import { useState } from "react";

export interface TrackSettings {
  mute?: boolean; gain_db?: number; pan?: number;
  eq?: { low_db?: number; mid_db?: number; high_db?: number };
  comp?: { ratio?: number };
  fx?: { reverb?: number; delay?: number; chorus?: number; distortion?: number };
}
export type MixState = Record<string, TrackSettings>;

// Strip a mix of all default/empty settings → the lean payload for the API.
export function cleanMix(mix: MixState): MixState {
  const out: MixState = {};
  for (const [t, s] of Object.entries(mix)) {
    const c: TrackSettings = {};
    if (s.mute) c.mute = true;
    if (s.gain_db) c.gain_db = s.gain_db;
    if (s.eq && (s.eq.low_db || s.eq.mid_db || s.eq.high_db)) c.eq = s.eq;
    if (s.comp && (s.comp.ratio ?? 1) > 1) c.comp = s.comp;
    if (s.fx && (s.fx.reverb || s.fx.delay || s.fx.chorus || s.fx.distortion)) c.fx = s.fx;
    if (Object.keys(c).length) out[t] = c;
  }
  return out;
}

function Knob({ label, min, max, step, val, def, onCh }: {
  label: string; min: number; max: number; step: number; val: number; def: number; onCh: (v: number) => void;
}) {
  const pct = max <= 1;
  return (
    <label className="mx-knob">
      <span>{label}</span>
      <input type="range" min={min} max={max} step={step} value={val} onChange={(e) => onCh(Number(e.target.value))} />
      <i>{val === def ? "—" : `${val > 0 && !pct ? "+" : ""}${pct ? Math.round(val * 100) + "%" : val}`}</i>
    </label>
  );
}

export default function MixingDesk({ tracks, mix, onChange }: {
  tracks: string[]; mix: MixState; onChange: (m: MixState) => void;
}) {
  const [open, setOpen] = useState<string | null>(null);
  const set = (t: string, patch: (s: TrackSettings) => TrackSettings) =>
    onChange({ ...mix, [t]: patch(mix[t] || {}) });

  return (
    <div className="mx-tracks">
      {tracks.map((t) => {
        const s = mix[t] || {};
        return (
          <div key={t} className={"mx-strip" + (s.mute ? " muted" : "")}>
            <div className="mx-row">
              <button className={"mx-mute" + (s.mute ? " on" : "")}
                onClick={() => set(t, (x) => ({ ...x, mute: !x.mute }))}>{s.mute ? "🔇" : "🔊"}</button>
              <span className="mx-name">{t}</span>
              <input className="mx-fader" type="range" min={-24} max={6} step={1}
                value={s.gain_db ?? 0} onChange={(e) => set(t, (x) => ({ ...x, gain_db: Number(e.target.value) }))} />
              <span className="mx-db">{(s.gain_db ?? 0) > 0 ? "+" : ""}{s.gain_db ?? 0} dB</span>
              <button className={"mx-fx-btn" + (open === t ? " on" : "")}
                onClick={() => setOpen(open === t ? null : t)}>EQ · FX</button>
            </div>
            {open === t && (
              <div className="mx-panel">
                <div className="mx-group"><b>EQ</b>
                  <Knob label="Low" min={-12} max={12} step={1} def={0} val={s.eq?.low_db ?? 0}
                    onCh={(v) => set(t, (x) => ({ ...x, eq: { ...x.eq, low_db: v } }))} />
                  <Knob label="Mid" min={-12} max={12} step={1} def={0} val={s.eq?.mid_db ?? 0}
                    onCh={(v) => set(t, (x) => ({ ...x, eq: { ...x.eq, mid_db: v } }))} />
                  <Knob label="High" min={-12} max={12} step={1} def={0} val={s.eq?.high_db ?? 0}
                    onCh={(v) => set(t, (x) => ({ ...x, eq: { ...x.eq, high_db: v } }))} />
                </div>
                <div className="mx-group"><b>Comp</b>
                  <Knob label="Ratio" min={1} max={8} step={0.5} def={1} val={s.comp?.ratio ?? 1}
                    onCh={(v) => set(t, (x) => ({ ...x, comp: { ...x.comp, ratio: v } }))} />
                </div>
                <div className="mx-group"><b>FX</b>
                  {(["reverb", "delay", "chorus", "distortion"] as const).map((f) => (
                    <Knob key={f} label={f[0].toUpperCase() + f.slice(1, 4)} min={0} max={1} step={0.05} def={0}
                      val={s.fx?.[f] ?? 0} onCh={(v) => set(t, (x) => ({ ...x, fx: { ...x.fx, [f]: v } }))} />
                  ))}
                </div>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
