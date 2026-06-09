import { useEffect, useMemo, useRef } from "react";

// A scrolling piano-roll "notation roll": notes flow right-to-left through a
// fixed now-line, positioned by time (x) and pitch (y), with octave reference
// lines and note names. Notes under the now-line glow. Driven by rAF off the
// audio clock for smooth motion (shared idiom with TapeView).

const NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
const PPS = 120;        // pixels per second
const PLAYHEAD = 0.26;  // now-line position (fraction of width)
const H = 190;          // roll height (px)
const PAD = 14;

export interface RollNote { pitch: number; start: number; dur: number }

function noteName(p: number): string {
  return NOTE_NAMES[((p % 12) + 12) % 12] + (Math.floor(p / 12) - 1);
}

export default function NotationRoll({
  notes, audioRef,
}: {
  notes: RollNote[];
  audioRef: React.RefObject<HTMLAudioElement | null>;
}) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const laneRef = useRef<HTMLDivElement>(null);
  const noteRefs = useRef<(HTMLDivElement | null)[]>([]);

  const { lo, hi, rowH, y } = useMemo(() => {
    const ps = notes.map((n) => n.pitch);
    let mn = ps.length ? Math.min(...ps) : 60;
    let mx = ps.length ? Math.max(...ps) : 72;
    // pad the range a little and keep at least an octave
    mn -= 2; mx += 2;
    if (mx - mn < 12) { mx = mn + 12; }
    const span = mx - mn;
    const usable = H - PAD * 2;
    const rh = Math.max(5, Math.min(16, usable / (span + 1)));
    const yf = (p: number) => PAD + (mx - p) * (usable / span);
    return { lo: mn, hi: mx, rowH: rh, y: yf };
  }, [notes]);

  // Octave reference lines (every C in range).
  const octaves = useMemo(() => {
    const out: number[] = [];
    for (let p = Math.ceil(lo / 12) * 12; p <= hi; p += 12) out.push(p);
    return out;
  }, [lo, hi]);

  useEffect(() => {
    let raf = 0;
    const lit = new Set<number>();
    const tick = () => {
      const t = audioRef.current?.currentTime ?? 0;
      const w = wrapRef.current?.clientWidth ?? 0;
      const playheadX = w * PLAYHEAD;
      if (laneRef.current) {
        laneRef.current.style.transform = `translate3d(${playheadX - t * PPS}px,0,0)`;
      }
      // Toggle "on" for notes currently sounding (cheap DOM diff).
      notes.forEach((n, i) => {
        const on = t >= n.start && t < n.start + n.dur;
        if (on && !lit.has(i)) { noteRefs.current[i]?.classList.add("on"); lit.add(i); }
        else if (!on && lit.has(i)) { noteRefs.current[i]?.classList.remove("on"); lit.delete(i); }
      });
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [notes, audioRef]);

  return (
    <div className="roll" ref={wrapRef} style={{ height: H }}>
      <div className="roll-grid">
        {octaves.map((c) => (
          <div key={c} className="roll-line" style={{ top: y(c) }}>
            <span>{noteName(c)}</span>
          </div>
        ))}
      </div>
      <div className="roll-now" style={{ left: `${PLAYHEAD * 100}%` }} />
      <div className="roll-lane" ref={laneRef}>
        {notes.map((n, i) => {
          const wpx = Math.max(8, n.dur * PPS - 2);
          return (
            <div
              key={i}
              ref={(el) => { noteRefs.current[i] = el; }}
              className="roll-note"
              style={{ left: n.start * PPS, top: y(n.pitch) - rowH / 2, width: wpx, height: rowH }}
            >
              {rowH >= 11 && wpx >= 20 && <span>{noteName(n.pitch)}</span>}
            </div>
          );
        })}
      </div>
    </div>
  );
}
