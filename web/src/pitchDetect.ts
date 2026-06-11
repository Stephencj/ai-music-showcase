// Microphone pitch detection via normalized autocorrelation (a YIN-lite). Used
// by the play-along so a singer / acoustic instrument can play their part with
// no MIDI gear. Returns a stop() fn; calls back each frame with the detected
// MIDI pitch (rounded) or null when there's no clear pitch / it's too quiet.

function autoCorrelate(buf: Float32Array, sampleRate: number): number {
  let size = buf.length;
  let rms = 0;
  for (let i = 0; i < size; i++) rms += buf[i] * buf[i];
  rms = Math.sqrt(rms / size);
  if (rms < 0.012) return -1;                 // too quiet to call

  // Trim leading/trailing low-amplitude samples.
  let r1 = 0, r2 = size - 1;
  const thres = 0.2;
  for (let i = 0; i < size / 2; i++) if (Math.abs(buf[i]) < thres) { r1 = i; break; }
  for (let i = 1; i < size / 2; i++) if (Math.abs(buf[size - i]) < thres) { r2 = size - i; break; }
  buf = buf.subarray(r1, r2);
  size = buf.length;

  // Autocorrelation, restricted to musical lags (~73–1100 Hz).
  const minLag = Math.floor(sampleRate / 1100);
  const maxLag = Math.min(size - 1, Math.floor(sampleRate / 73));
  let bestLag = -1, bestVal = 0;
  for (let lag = minLag; lag <= maxLag; lag++) {
    let sum = 0;
    for (let i = 0; i < size - lag; i++) sum += buf[i] * buf[i + lag];
    if (sum > bestVal) { bestVal = sum; bestLag = lag; }
  }
  if (bestLag <= 0) return -1;
  // Parabolic interpolation around the peak for sub-sample accuracy.
  const c = (lag: number) => {
    let s = 0; for (let i = 0; i < size - lag; i++) s += buf[i] * buf[i + lag]; return s;
  };
  const x1 = c(bestLag - 1), x2 = c(bestLag), x3 = c(bestLag + 1);
  const a = (x1 + x3 - 2 * x2) / 2, b = (x3 - x1) / 2;
  const lag = a ? bestLag - b / (2 * a) : bestLag;
  return sampleRate / lag;
}

export async function startMicPitch(
  onPitch: (midi: number | null) => void,
): Promise<() => void> {
  const Ctx = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
  const ctx = new Ctx();
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false },
  });
  const src = ctx.createMediaStreamSource(stream);
  const analyser = ctx.createAnalyser();
  analyser.fftSize = 1024;
  src.connect(analyser);
  const buf = new Float32Array(analyser.fftSize);
  let raf = 0;
  const tick = () => {
    analyser.getFloatTimeDomainData(buf);
    const f = autoCorrelate(buf, ctx.sampleRate);
    onPitch(f > 0 ? Math.round(69 + 12 * Math.log2(f / 440)) : null);
    raf = requestAnimationFrame(tick);
  };
  raf = requestAnimationFrame(tick);
  return () => {
    cancelAnimationFrame(raf);
    stream.getTracks().forEach((t) => t.stop());
    ctx.close().catch(() => {});
  };
}
