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
    if (canvas.current && peaks) drawPeaks(canvas.current, peaks);
  }, [peaks]);

  return (
    <div ref={wrap} className="sparkline">
      <canvas ref={canvas} width={W} height={H} />
    </div>
  );
}

/** Draw peaks (0..1) as centred bars filling the canvas. */
export function drawPeaks(cv: HTMLCanvasElement, peaks: number[], color = "#6b70a0") {
  const ctx = cv.getContext("2d");
  if (!ctx) return;
  const { width: w, height: h } = cv;
  ctx.clearRect(0, 0, w, h);
  const n = peaks.length;
  if (!n) return;
  const bw = w / n;
  ctx.fillStyle = color;
  for (let i = 0; i < n; i++) {
    const ph = Math.max(1, peaks[i] * (h - 2));
    ctx.fillRect(i * bw, (h - ph) / 2, Math.max(1, bw - 1), ph);
  }
}
