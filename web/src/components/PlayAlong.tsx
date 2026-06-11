import { useEffect, useMemo, useRef, useState } from "react";
import type { RollNote } from "./NotationRoll";

// A scored play-along: the part's notes flow right-to-left into a strike line;
// hit the matching lane (keyboard or tap) in time. Timing is graded
// Perfect/Great/Good/Miss. Doubles as a graded practice drill ("play your part
// in time") and the rhythm core of the band game. Reuses the now-line scroll
// idiom from NotationRoll/TabView; note motion is rAF-driven (no per-frame
// React render), judgments are discrete events.

const LANES = 4;
const KEYS = ["d", "f", "j", "k"];          // home-row, two hands
const LANE_COLOR = ["#ef4444", "#f59e0b", "#22c55e", "#38bdf8"];
const PX_PER_S = 240;
const NOW_FRAC = 0.18;
const ROW_H = 46;
// Timing windows (seconds either side of the note's onset).
const W_PERFECT = 0.045, W_GREAT = 0.09, W_GOOD = 0.15;
const SCORE = { perfect: 100, great: 60, good: 30, miss: 0 };

interface PNote { i: number; lane: number; start: number; }
type Judge = "perfect" | "great" | "good" | "miss";

export default function PlayAlong({ notes, audioRef }: {
  notes: RollNote[];
  audioRef: React.RefObject<HTMLAudioElement | null>;
}) {
  // Map each note to a lane by pitch register.
  const pnotes = useMemo<PNote[]>(() => {
    if (!notes.length) return [];
    const ps = notes.map((n) => n.pitch);
    const lo = Math.min(...ps), hi = Math.max(...ps);
    const span = Math.max(1, hi - lo);
    return notes.map((n, i) => ({
      i,
      lane: Math.max(0, Math.min(LANES - 1, Math.floor((n.pitch - lo) / (span + 0.001) * LANES))),
      start: n.start,
    })).sort((a, b) => a.start - b.start);
  }, [notes]);

  const wrapRef = useRef<HTMLDivElement>(null);
  const laneRef = useRef<HTMLDivElement>(null);
  const noteEls = useRef<(HTMLDivElement | null)[]>([]);
  const judged = useRef<Map<number, Judge>>(new Map());
  const [w, setW] = useState(640);
  const [stats, setStats] = useState({ score: 0, combo: 0, maxCombo: 0, perfect: 0, great: 0, good: 0, miss: 0, total: pnotes.length });
  const [pop, setPop] = useState<{ lane: number; judge: Judge; n: number } | null>(null);
  const [started, setStarted] = useState(false);

  useEffect(() => { judged.current = new Map(); setStarted(false);
    setStats({ score: 0, combo: 0, maxCombo: 0, perfect: 0, great: 0, good: 0, miss: 0, total: pnotes.length }); }, [pnotes]);

  useEffect(() => {
    const el = wrapRef.current; if (!el) return;
    const m = () => setW(el.clientWidth || 640); m();
    const ro = new ResizeObserver(m); ro.observe(el); return () => ro.disconnect();
  }, []);

  const nowX = Math.round(w * NOW_FRAC);

  const record = (judge: Judge, lane: number) => {
    setStats((s) => {
      const combo = judge === "miss" ? 0 : s.combo + 1;
      return {
        ...s, score: s.score + SCORE[judge], combo,
        maxCombo: Math.max(s.maxCombo, combo),
        perfect: s.perfect + (judge === "perfect" ? 1 : 0),
        great: s.great + (judge === "great" ? 1 : 0),
        good: s.good + (judge === "good" ? 1 : 0),
        miss: s.miss + (judge === "miss" ? 1 : 0),
      };
    });
    setPop({ lane, judge, n: Math.random() });
  };

  // Note motion + miss detection.
  useEffect(() => {
    let raf = 0;
    const tick = () => {
      const t = audioRef.current?.currentTime ?? 0;
      if (laneRef.current) laneRef.current.style.transform = `translate3d(${nowX - t * PX_PER_S}px,0,0)`;
      for (const p of pnotes) {
        if (judged.current.has(p.i)) continue;
        if (t - p.start > W_GOOD) {           // passed the window unhit → miss
          judged.current.set(p.i, "miss");
          noteEls.current[p.i]?.classList.add("missed");
          record("miss", p.lane);
        }
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [pnotes, nowX, audioRef]);

  const hitLane = (lane: number) => {
    const t = audioRef.current?.currentTime ?? 0;
    // nearest unjudged note in this lane inside the window
    let best: PNote | null = null, bestDt = W_GOOD + 1;
    for (const p of pnotes) {
      if (p.lane !== lane || judged.current.has(p.i)) continue;
      const dt = Math.abs(p.start - t);
      if (dt < bestDt) { bestDt = dt; best = p; }
    }
    if (!best || bestDt > W_GOOD) { setPop({ lane, judge: "miss", n: Math.random() }); return; }
    const judge: Judge = bestDt <= W_PERFECT ? "perfect" : bestDt <= W_GREAT ? "great" : "good";
    judged.current.set(best.i, judge);
    noteEls.current[best.i]?.classList.add("hit", judge);
    record(judge, lane);
  };

  // Keyboard.
  useEffect(() => {
    const down = (e: KeyboardEvent) => {
      const k = e.key.toLowerCase();
      const lane = KEYS.indexOf(k);
      if (lane >= 0 && !e.repeat) { e.preventDefault(); setStarted(true); hitLane(lane); }
    };
    window.addEventListener("keydown", down);
    return () => window.removeEventListener("keydown", down);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pnotes]);

  const judged_n = stats.perfect + stats.great + stats.good + stats.miss;
  const acc = judged_n ? Math.round((stats.perfect + stats.great * 0.6 + stats.good * 0.3) / judged_n * 100) : 100;
  const done = pnotes.length > 0 && judged_n >= pnotes.length;
  const grade = acc >= 95 ? "S" : acc >= 90 ? "A" : acc >= 80 ? "B" : acc >= 70 ? "C" : acc >= 50 ? "D" : "F";

  if (!pnotes.length) return <div className="practice-hint">This part has no notes to play along to — pick a melodic part above.</div>;

  return (
    <div className="playalong">
      <div className="pa-hud">
        <span className="pa-score">{stats.score.toLocaleString()}</span>
        <span className="pa-combo">{stats.combo > 1 ? `${stats.combo}× combo` : ""}</span>
        <span className="pa-acc">{acc}% <b className={`pa-grade g${grade}`}>{grade}</b></span>
      </div>

      <div className="pa-stage" ref={wrapRef} style={{ height: LANES * ROW_H + 8 }}>
        {Array.from({ length: LANES }, (_, l) => (
          <div key={l} className="pa-lane" style={{ top: l * ROW_H }}>
            <span className="pa-key" style={{ color: LANE_COLOR[l] }}>{KEYS[l].toUpperCase()}</span>
          </div>
        ))}
        <div className="pa-now" style={{ left: nowX }} />
        {pop && (
          <div key={pop.n} className={`pa-pop ${pop.judge}`} style={{ left: nowX, top: pop.lane * ROW_H + ROW_H / 2 }}>
            {pop.judge}
          </div>
        )}
        <div className="pa-scroll" ref={laneRef}>
          {pnotes.map((p) => (
            <div key={p.i} ref={(el) => { noteEls.current[p.i] = el; }}
              className="pa-note"
              style={{ left: p.start * PX_PER_S, top: p.lane * ROW_H + 7, background: LANE_COLOR[p.lane] }} />
          ))}
        </div>
      </div>

      <div className="pa-tap">
        {Array.from({ length: LANES }, (_, l) => (
          <button key={l} className="pa-tapbtn" style={{ borderColor: LANE_COLOR[l] }}
            onPointerDown={(e) => { e.preventDefault(); setStarted(true); hitLane(l); }}>
            {KEYS[l].toUpperCase()}
          </button>
        ))}
      </div>

      <div className="pa-foot">
        {!started
          ? <span>Press <b>D F J K</b> (or tap) as each note hits the line. Start the audio to play along.</span>
          : done
            ? <span>Done — <b className={`pa-grade g${grade}`}>{grade}</b> · {acc}% · best combo {stats.maxCombo} · {stats.perfect} perfect / {stats.miss} missed</span>
            : <span>{stats.perfect} perfect · {stats.great} great · {stats.good} good · {stats.miss} missed</span>}
      </div>
    </div>
  );
}
