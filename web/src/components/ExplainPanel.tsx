import { useEffect, useState } from "react";
import * as api from "../api";
import type { ExplainData } from "../types";

// "Show under the hood" — a plain-English, teaching-oriented breakdown of a
// generated block: its key, how each section relates to it, the chords with
// their harmonic function, named progressions/devices, and why the
// arrangement does what it does. The whole point of the product.
const FUNC_COLOR: Record<string, string> = {
  tonic: "#22c55e", predominant: "#f59e0b", dominant: "#ef4444",
};
function funcColor(fn: string): string {
  for (const k of Object.keys(FUNC_COLOR)) if (fn.startsWith(k)) return FUNC_COLOR[k];
  return "#7c8aa5";
}

export default function ExplainPanel({ blockName }: { blockName: string }) {
  const [data, setData] = useState<ExplainData | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    setData(null); setErr(null);
    api.getExplain(blockName).then(setData).catch((e) => setErr(String(e)));
  }, [blockName]);

  if (err) return <div className="practice-hint">Couldn't analyze this block: {err}</div>;
  if (!data) return <div className="practice-hint">Analyzing…</div>;

  return (
    <div className="explain">
      <div className="explain-head">
        <h3>{data.genre}</h3>
        <div className="explain-meta">
          <span><b>Key:</b> {data.key}</span>
          {data.tempo != null && <span><b>Tempo:</b> {Math.round(data.tempo)} BPM</span>}
          <span><b>Form:</b> {data.form.join(" · ")}</span>
        </div>
        <div className="explain-legend">
          <span><i style={{ background: FUNC_COLOR.tonic }} />tonic (home)</span>
          <span><i style={{ background: FUNC_COLOR.predominant }} />predominant (tension building)</span>
          <span><i style={{ background: FUNC_COLOR.dominant }} />dominant (wants to resolve)</span>
        </div>
      </div>

      {data.sections.map((s, i) => (
        <div key={i} className="explain-sec">
          <div className="explain-sec-head">
            <span className="explain-sec-label">{s.label}</span>
            <span className="explain-sec-feel">{s.feel}</span>
            <span className="explain-sec-bars">{s.bars} bars</span>
            {s.tempo != null && <span className="explain-sec-bars">{Math.round(s.tempo)} BPM</span>}
          </div>
          <div className="explain-key">{s.key_relation}</div>

          {s.chords.length > 0 && (
            <div className="explain-chords">
              {s.chords.map((c, j) => (
                <span key={j} className="explain-chord" title={`${c.function} · Nashville ${c.nashville}`}>
                  <span className="ec-roman" style={{ color: funcColor(c.function) }}>{c.roman}</span>
                  <span className="ec-name">{c.name}</span>
                </span>
              ))}
            </div>
          )}

          {s.progression_name && <div className="explain-prog">→ {s.progression_name}</div>}
          {s.devices.map((d, j) => <div key={j} className="explain-device">✦ {d}</div>)}
          {s.arrangement && <div className="explain-arr">🎚 {s.arrangement}</div>}
        </div>
      ))}
    </div>
  );
}
