import { useEffect, useRef, useState } from "react";
import type { TabNote } from "../guitarTab";

// Scrolling guitar/bass tab lane. The string lines are fixed; fret-number
// bubbles flow right-to-left toward a "now" line as the audio plays (driven by
// the shared practice playhead, same as TapeView / the karaoke lane). The note
// crossing the now-line lights up.

const PX_PER_S = 120;   // horizontal scroll speed
const ROW = 22;         // vertical spacing between strings
const PAD_TOP = 22;     // headroom above the top string
const LABEL_W = 26;     // room for the string-name column on the left
const NOW_FRAC = 0.26;  // the now-line sits ~1/4 in from the left

export default function TabView({
  tabNotes, stringLabels, audioRef,
}: {
  tabNotes: TabNote[];                 // start/dur in seconds
  stringLabels: string[];              // top→bottom
  audioRef: React.RefObject<HTMLAudioElement | null>;
}) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const [w, setW] = useState(640);
  const [t, setT] = useState(0);
  const raf = useRef<number | null>(null);

  // Track the available width so the lane (and the now-line) fill the panel.
  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const measure = () => setW(el.clientWidth || 640);
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Follow the playhead every frame.
  useEffect(() => {
    const tick = () => {
      const a = audioRef.current;
      if (a) setT(a.currentTime || 0);
      raf.current = requestAnimationFrame(tick);
    };
    raf.current = requestAnimationFrame(tick);
    return () => { if (raf.current) cancelAnimationFrame(raf.current); };
  }, [audioRef]);

  const n = stringLabels.length;
  const H = PAD_TOP + ROW * (n - 1) + PAD_TOP;
  const nowX = Math.round(w * NOW_FRAC);
  const stringY = (s: number) => PAD_TOP + s * ROW;

  return (
    <div className="tab-lane-wrap" ref={wrapRef}>
      <svg className="tab-lane" width={w} height={H} role="img" aria-label="Guitar tab">
        {/* string lines + name column */}
        {stringLabels.map((lab, s) => (
          <g key={s}>
            <line x1={LABEL_W} y1={stringY(s)} x2={w} y2={stringY(s)} className="tab-string" />
            <text x={6} y={stringY(s) + 4} className="tab-strlabel">{lab}</text>
          </g>
        ))}

        {/* the fixed "now" line */}
        <line x1={nowX} y1={PAD_TOP - 10} x2={nowX} y2={stringY(n - 1) + 10} className="tab-now" />

        {/* fret bubbles */}
        {tabNotes.map((nt, i) => {
          const x = nowX + (nt.start - t) * PX_PER_S;
          if (x < LABEL_W - 30 || x > w + 30) return null;
          const on = nt.start <= t && t < nt.start + nt.dur;
          const past = t >= nt.start + nt.dur;
          const y = stringY(nt.string);
          return (
            <g key={i} className={"tab-note" + (on ? " on" : past ? " past" : "")}>
              <rect x={x - 11} y={y - 9} width={22} height={18} rx={9} className="tab-note-bg" />
              <text x={x} y={y + 4} className="tab-fret" textAnchor="middle">{nt.fret}</text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}
