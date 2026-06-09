import { useEffect, useRef } from "react";
import type { ScoreData, ChordSpan } from "../api";

// Horizontal "tape" of chords + section markers that flows right-to-left
// through a fixed now-line as the song plays. Current chord sits on the line;
// upcoming chords slide in from the right. Driven by requestAnimationFrame off
// the audio element's currentTime for smooth motion (the timeupdate event is
// too coarse — ~4Hz — for fluid scrolling).

const PPS = 120;          // pixels per second of music
const PLAYHEAD = 0.26;    // now-line position as a fraction of the lane width

export default function TapeView({
  score, labelFor, audioRef,
}: {
  score: ScoreData;
  labelFor: (c: { symbol: string; root: string | null; quality: string | null }) => string;
  audioRef: React.RefObject<HTMLAudioElement | null>;
}) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const laneRef = useRef<HTMLDivElement>(null);
  const blockRefs = useRef<(HTMLDivElement | null)[]>([]);

  useEffect(() => {
    let raf = 0;
    let activeIdx = -1;
    const tick = () => {
      const t = audioRef.current?.currentTime ?? 0;
      const w = wrapRef.current?.clientWidth ?? 0;
      const playheadX = w * PLAYHEAD;
      if (laneRef.current) {
        laneRef.current.style.transform = `translate3d(${playheadX - t * PPS}px,0,0)`;
      }
      // Highlight the chord currently under the now-line (cheap DOM toggle).
      const idx = score.chord_spans.findIndex((s) => t >= s.start_time && t < s.end_time);
      if (idx !== activeIdx) {
        blockRefs.current[activeIdx]?.classList.remove("on");
        blockRefs.current[idx]?.classList.add("on");
        activeIdx = idx;
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [audioRef, score]);

  return (
    <div className="tape" ref={wrapRef}>
      <div className="tape-playhead" style={{ left: `${PLAYHEAD * 100}%` }} />
      <div className="tape-lane" ref={laneRef}>
        {score.sections.map((sec) => (
          <div
            key={`sec-${sec.start_bar}`}
            className="tape-section"
            style={{ left: sec.start_time * PPS }}
          >
            <span>{sec.label}</span>
          </div>
        ))}
        {score.chord_spans.map((s, i) => (
          <div
            key={s.start_bar}
            ref={(el) => { blockRefs.current[i] = el; }}
            className="tape-chord"
            style={{
              left: s.start_time * PPS,
              width: Math.max(46, (s.end_time - s.start_time) * PPS - 4),
            }}
          >
            <span>{labelFor(s as ChordSpan)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
