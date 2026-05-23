import { useEffect, useRef, useState } from "react";
import * as api from "../api";

const W = 256;
const H = 24;

/**
 * Tiny waveform thumbnail drawn from server-computed peaks. Peaks are
 * fetched lazily (only when the card scrolls near the viewport) so a big
 * library doesn't fan out dozens of requests at once.
 */
export default function Sparkline({ name }: { name: string }) {
  const wrap = useRef<HTMLDivElement | null>(null);
  const canvas = useRef<HTMLCanvasElement | null>(null);
  const [peaks, setPeaks] = useState<number[] | null>(null);

  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    let done = false;
    const io = new IntersectionObserver(
      (entries) => {
        if (!done && entries.some((e) => e.isIntersecting)) {
          done = true;
          io.disconnect();
          api.getPeaks(name).then(setPeaks).catch(() => {});
        }
      },
      { rootMargin: "150px" }
    );
    io.observe(el);
    return () => io.disconnect();
  }, [name]);

  useEffect(() => {
    const cv = canvas.current;
    if (!cv || !peaks) return;
    const ctx = cv.getContext("2d");
    if (!ctx) return;
    ctx.clearRect(0, 0, W, H);
    const n = peaks.length;
    const bw = W / n;
    ctx.fillStyle = "#6b70a0";
    for (let i = 0; i < n; i++) {
      const h = Math.max(1, peaks[i] * (H - 2));
      ctx.fillRect(i * bw, (H - h) / 2, Math.max(1, bw - 1), h);
    }
  }, [peaks]);

  return (
    <div ref={wrap} className="sparkline">
      <canvas ref={canvas} width={W} height={H} />
    </div>
  );
}
