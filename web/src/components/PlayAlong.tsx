import { useEffect, useMemo, useRef, useState } from "react";
import type { RollNote } from "./NotationRoll";
import * as webmidi from "../webmidi";
import { startMicPitch } from "../pitchDetect";

// A scored play-along. Three input modes:
//   • Keys  — 4 lanes by pitch register, hit D/F/J/K (or tap) in time (rhythm).
//   • MIDI  — play the ACTUAL notes on a MIDI instrument (pitch + timing).
//   • Mic   — sing/play; pitch is detected from the microphone.
// Notes flow into a now-line; timing is graded Perfect/Great/Good/Miss with
// score, combo, accuracy % and an S–F grade. Doubles as a graded practice drill
// and the rhythm core of the band game. Motion is rAF-driven off the audio
// clock; judgments are discrete events.

const LANES = 4;
const KEYS = ["d", "f", "j", "k"];
const LANE_COLOR = ["#ef4444", "#f59e0b", "#22c55e", "#38bdf8"];
const PX_PER_S = 240;
const NOW_FRAC = 0.18;
const LANE_H = 46;
const ROLL_H = 220, ROLL_PAD = 14;
const W_PERFECT = 0.05, W_GREAT = 0.095, W_GOOD = 0.16;
const SCORE = { perfect: 100, great: 60, good: 30, miss: 0 };

type Mode = "lanes" | "midi" | "mic";
type Judge = "perfect" | "great" | "good" | "miss";
interface PNote { i: number; pitch: number; lane: number; start: number; }

export default function PlayAlong({ notes, audioRef }: {
  notes: RollNote[];
  audioRef: React.RefObject<HTMLAudioElement | null>;
}) {
  const [mode, setMode] = useState<Mode>("lanes");
  const [inputErr, setInputErr] = useState<string | null>(null);

  const { pnotes, lo, hi } = useMemo(() => {
    if (!notes.length) return { pnotes: [] as PNote[], lo: 60, hi: 72 };
    const ps = notes.map((n) => n.pitch);
    const mn = Math.min(...ps), mx = Math.max(...ps);
    const span = Math.max(1, mx - mn);
    const pn = notes.map((n, i) => ({
      i, pitch: n.pitch,
      lane: Math.max(0, Math.min(LANES - 1, Math.floor((n.pitch - mn) / (span + 0.001) * LANES))),
      start: n.start,
    })).sort((a, b) => a.start - b.start);
    return { pnotes: pn, lo: mn - 2, hi: mx + 2 };
  }, [notes]);

  const wrapRef = useRef<HTMLDivElement>(null);
  const laneRef = useRef<HTMLDivElement>(null);
  const noteEls = useRef<(HTMLDivElement | null)[]>([]);
  const judged = useRef<Map<number, Judge>>(new Map());
  const curPitch = useRef<number | null>(null);
  const markerRef = useRef<HTMLDivElement>(null);
  const [w, setW] = useState(640);
  const [stats, setStats] = useState({ score: 0, combo: 0, maxCombo: 0, perfect: 0, great: 0, good: 0, miss: 0 });
  const [pop, setPop] = useState<{ x: number; y: number; judge: Judge; n: number } | null>(null);
  const [started, setStarted] = useState(false);

  const pitchMode = mode === "midi" || mode === "mic";
  const stageH = pitchMode ? ROLL_H : LANES * LANE_H + 8;
  const nowX = Math.round(w * NOW_FRAC);
  const usable = ROLL_H - ROLL_PAD * 2;
  const span = Math.max(1, hi - lo);
  const yOf = (p: number) => ROLL_PAD + (hi - p) * (usable / span);

  useEffect(() => {
    judged.current = new Map(); setStarted(false);
    setStats({ score: 0, combo: 0, maxCombo: 0, perfect: 0, great: 0, good: 0, miss: 0 });
  }, [pnotes, mode]);

  useEffect(() => {
    const el = wrapRef.current; if (!el) return;
    const m = () => setW(el.clientWidth || 640); m();
    const ro = new ResizeObserver(m); ro.observe(el); return () => ro.disconnect();
  }, []);

  const record = (judge: Judge, x: number, y: number) => {
    setStats((s) => {
      const combo = judge === "miss" ? 0 : s.combo + 1;
      return {
        score: s.score + SCORE[judge], combo, maxCombo: Math.max(s.maxCombo, combo),
        perfect: s.perfect + (judge === "perfect" ? 1 : 0),
        great: s.great + (judge === "great" ? 1 : 0),
        good: s.good + (judge === "good" ? 1 : 0),
        miss: s.miss + (judge === "miss" ? 1 : 0),
      };
    });
    setPop({ x, y, judge, n: Math.random() });
  };

  // Latest hit-logic in a ref so MIDI/mic subscriptions never go stale.
  const tryPitchRef = useRef<(m: number) => void>(() => {});
  tryPitchRef.current = (midi: number) => {
    const t = audioRef.current?.currentTime ?? 0;
    let best: PNote | null = null, bestDt = W_GOOD + 1;
    for (const p of pnotes) {
      if (judged.current.has(p.i) || (p.pitch % 12) !== (midi % 12)) continue;
      const dt = Math.abs(p.start - t);
      if (dt < bestDt) { bestDt = dt; best = p; }
    }
    if (!best || bestDt > W_GOOD) return;
    const judge: Judge = bestDt <= W_PERFECT ? "perfect" : bestDt <= W_GREAT ? "great" : "good";
    judged.current.set(best.i, judge);
    noteEls.current[best.i]?.classList.add("hit", judge);
    setStarted(true);
    record(judge, nowX, yOf(best.pitch));
  };

  const hitLane = (lane: number) => {
    const t = audioRef.current?.currentTime ?? 0;
    let best: PNote | null = null, bestDt = W_GOOD + 1;
    for (const p of pnotes) {
      if (p.lane !== lane || judged.current.has(p.i)) continue;
      const dt = Math.abs(p.start - t);
      if (dt < bestDt) { bestDt = dt; best = p; }
    }
    setStarted(true);
    if (!best || bestDt > W_GOOD) { setPop({ x: nowX, y: lane * LANE_H + LANE_H / 2, judge: "miss", n: Math.random() }); return; }
    const judge: Judge = bestDt <= W_PERFECT ? "perfect" : bestDt <= W_GREAT ? "great" : "good";
    judged.current.set(best.i, judge);
    noteEls.current[best.i]?.classList.add("hit", judge);
    record(judge, nowX, best.lane * LANE_H + LANE_H / 2);
  };

  // Scroll + miss detection + the live pitch marker.
  useEffect(() => {
    let raf = 0;
    const tick = () => {
      const t = audioRef.current?.currentTime ?? 0;
      if (laneRef.current) laneRef.current.style.transform = `translate3d(${nowX - t * PX_PER_S}px,0,0)`;
      if (markerRef.current) {
        const p = curPitch.current;
        markerRef.current.style.opacity = p == null ? "0" : "1";
        if (p != null) markerRef.current.style.top = `${yOf(p) - 5}px`;
      }
      for (const p of pnotes) {
        if (judged.current.has(p.i)) continue;
        if (t - p.start > W_GOOD) {
          judged.current.set(p.i, "miss");
          noteEls.current[p.i]?.classList.add("missed");
          record(judge_miss(), nowX, pitchMode ? yOf(p.pitch) : p.lane * LANE_H + LANE_H / 2);
        }
      }
      raf = requestAnimationFrame(tick);
    };
    const judge_miss = (): Judge => "miss";
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pnotes, nowX, mode]);

  // Keyboard (lanes mode).
  useEffect(() => {
    if (mode !== "lanes") return;
    const down = (e: KeyboardEvent) => {
      const lane = KEYS.indexOf(e.key.toLowerCase());
      if (lane >= 0 && !e.repeat) { e.preventDefault(); hitLane(lane); }
    };
    window.addEventListener("keydown", down);
    return () => window.removeEventListener("keydown", down);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, pnotes]);

  // MIDI input.
  useEffect(() => {
    if (mode !== "midi") return;
    let off = () => {};
    let live = true;
    (async () => {
      try {
        await webmidi.initMidi();
        if (!webmidi.listInputs().length) setInputErr("No MIDI input detected — connect a keyboard/controller.");
        else setInputErr(null);
        if (live) off = webmidi.onMidiNoteOn((pitch) => { curPitch.current = pitch; tryPitchRef.current(pitch); });
      } catch (e) { setInputErr(String(e)); }
    })();
    return () => { live = false; off(); curPitch.current = null; };
  }, [mode]);

  // Mic input.
  useEffect(() => {
    if (mode !== "mic") return;
    let stop = () => {};
    let live = true;
    setInputErr(null);
    startMicPitch((midi) => {
      curPitch.current = midi;
      if (midi != null) tryPitchRef.current(midi);
    }).then((s) => { if (live) stop = s; else s(); })
      .catch((e) => setInputErr("Mic unavailable: " + e));
    return () => { live = false; stop(); curPitch.current = null; };
  }, [mode]);

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
        <div className="seg pa-modes">
          {(["lanes", "midi", "mic"] as Mode[]).map((m) => (
            <button key={m} className={mode === m ? "on" : ""} onClick={() => setMode(m)}>
              {m === "lanes" ? "Keys" : m === "midi" ? "MIDI" : "Mic"}
            </button>
          ))}
        </div>
        <span className="pa-acc">{acc}% <b className={`pa-grade g${grade}`}>{grade}</b></span>
      </div>

      <div className="pa-stage" ref={wrapRef} style={{ height: stageH }}>
        {!pitchMode && Array.from({ length: LANES }, (_, l) => (
          <div key={l} className="pa-lane" style={{ top: l * LANE_H }}>
            <span className="pa-key" style={{ color: LANE_COLOR[l] }}>{KEYS[l].toUpperCase()}</span>
          </div>
        ))}
        <div className="pa-now" style={{ left: nowX }} />
        {pitchMode && <div className="pa-marker" ref={markerRef} style={{ left: nowX - 7 }} />}
        {pop && (
          <div key={pop.n} className={`pa-pop ${pop.judge}`} style={{ left: pop.x, top: pop.y }}>{pop.judge}</div>
        )}
        <div className="pa-scroll" ref={laneRef}>
          {pnotes.map((p) => (
            <div key={p.i} ref={(el) => { noteEls.current[p.i] = el; }} className="pa-note"
              style={pitchMode
                ? { left: p.start * PX_PER_S, top: yOf(p.pitch) - 5, width: 26, height: 10,
                    background: LANE_COLOR[p.lane] }
                : { left: p.start * PX_PER_S, top: p.lane * LANE_H + 7, width: 30, height: 32,
                    background: LANE_COLOR[p.lane] }} />
          ))}
        </div>
      </div>

      {mode === "lanes" && (
        <div className="pa-tap">
          {Array.from({ length: LANES }, (_, l) => (
            <button key={l} className="pa-tapbtn" style={{ borderColor: LANE_COLOR[l] }}
              onPointerDown={(e) => { e.preventDefault(); hitLane(l); }}>{KEYS[l].toUpperCase()}</button>
          ))}
        </div>
      )}

      <div className="pa-foot">
        {inputErr ? <span className="pa-err">{inputErr}</span>
          : !started
            ? <span>{mode === "lanes" ? <>Hit <b>D F J K</b> (or tap) as notes reach the line.</>
              : mode === "midi" ? <>Play the notes on your MIDI instrument as they reach the line.</>
                : <>Sing or play the notes as they reach the line.</>}{" "}Start the audio to play along.</span>
            : done
              ? <span>Done — <b className={`pa-grade g${grade}`}>{grade}</b> · {acc}% · best combo {stats.maxCombo} · {stats.perfect} perfect / {stats.miss} missed</span>
              : <span>{stats.perfect} perfect · {stats.great} great · {stats.good} good · {stats.miss} missed</span>}
      </div>
    </div>
  );
}
