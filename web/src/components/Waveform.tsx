import { useEffect, useRef, useState } from "react";
import WaveSurfer from "wavesurfer.js";

/**
 * Lazy waveform player. Mounted on demand (one WaveSurfer instance per
 * mount) so a 50-block library doesn't spin up 50 decoders at once —
 * cards create this only when the user taps Preview.
 */
export default function Waveform({
  url,
  height = 48,
  autoplay = false,
}: {
  url: string;
  height?: number;
  autoplay?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const ws = useRef<WaveSurfer | null>(null);
  const [playing, setPlaying] = useState(false);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!ref.current) return;
    const w = WaveSurfer.create({
      container: ref.current,
      url,
      height,
      waveColor: "#5b6080",
      progressColor: "#8b5cf6",
      cursorColor: "#38bdf8",
      barWidth: 2,
      barGap: 1,
      barRadius: 2,
      normalize: true,
    });
    ws.current = w;
    w.on("ready", () => {
      setReady(true);
      if (autoplay) w.play();
    });
    w.on("play", () => setPlaying(true));
    w.on("pause", () => setPlaying(false));
    w.on("finish", () => setPlaying(false));
    return () => {
      w.destroy();
      ws.current = null;
    };
  }, [url, height, autoplay]);

  return (
    <div className="waveform">
      <button
        className="wf-play"
        onClick={() => ws.current?.playPause()}
        disabled={!ready}
        aria-label={playing ? "Pause" : "Play"}
      >
        {playing ? "⏸" : "▶"}
      </button>
      <div className="wf-canvas" ref={ref} />
    </div>
  );
}
