import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import * as api from "../api";

const GAP = 0.6;           // phrase-break threshold between words (seconds)
const W = 1000, H = 160;   // pitch-lane viewBox
const NOW_X = 220;         // the fixed "now" line
const PX_PER_S = 90;       // horizontal scroll speed

/**
 * Full-screen karaoke: scrolling pitch lane (the melody to sing) + big
 * highlighted lyrics, with a backing track and an audible guide. Record →
 * the existing autotune endpoint snaps your take to the melody.
 */
export default function KaraokeScreen({ block, onClose }: { block: string; onClose: () => void }) {
  const [data, setData] = useState<api.KaraokeData | null>(null);
  const [err, setErr] = useState("");
  const [t, setT] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [guideOn, setGuideOn] = useState(true);
  const [recording, setRecording] = useState(false);
  const [status, setStatus] = useState("");
  const [tunedUrl, setTunedUrl] = useState<string | null>(null);

  const backRef = useRef<HTMLAudioElement | null>(null);
  const guideRef = useRef<HTMLAudioElement | null>(null);
  const recRef = useRef<MediaRecorder | null>(null);
  const chunks = useRef<Blob[]>([]);
  const raf = useRef<number | null>(null);
  const lineRefs = useRef<(HTMLDivElement | null)[]>([]);

  useEffect(() => {
    let alive = true;
    api.getKaraoke(block).then((d) => alive && setData(d)).catch((e) => setErr(String(e)));
    return () => { alive = false; };
  }, [block]);

  // playhead loop
  useEffect(() => {
    const tick = () => {
      if (backRef.current) setT(backRef.current.currentTime);
      raf.current = requestAnimationFrame(tick);
    };
    raf.current = requestAnimationFrame(tick);
    return () => { if (raf.current) cancelAnimationFrame(raf.current); };
  }, []);
  // stop audio on unmount
  useEffect(() => () => { backRef.current?.pause(); guideRef.current?.pause(); }, []);
  // guide mute follows the toggle
  useEffect(() => { if (guideRef.current) guideRef.current.muted = !guideOn; }, [guideOn]);

  const play = useCallback(() => {
    const a = backRef.current; if (!a) return;
    void a.play();
    const g = guideRef.current;
    if (g) { g.muted = !guideOn; g.currentTime = a.currentTime; void g.play(); }
    setPlaying(true);
  }, [guideOn]);
  const pause = useCallback(() => {
    backRef.current?.pause(); guideRef.current?.pause(); setPlaying(false);
  }, []);
  const seek = useCallback((sec: number) => {
    if (backRef.current) backRef.current.currentTime = sec;
    if (guideRef.current) guideRef.current.currentTime = sec;
    setT(sec);
  }, []);

  // Group words into phrase lines on rests; find the active line/word from t.
  const phrases = useMemo(() => {
    const out: { words: api.KaraokeData["words"] }[] = [];
    let cur: api.KaraokeData["words"] = [];
    (data?.words ?? []).forEach((w) => {
      if (cur.length && w.start - cur[cur.length - 1].end > GAP) { out.push({ words: cur }); cur = []; }
      cur.push(w);
    });
    if (cur.length) out.push({ words: cur });
    return out;
  }, [data]);

  const activePhrase = useMemo(() => {
    let idx = 0;
    for (let i = 0; i < phrases.length; i++) {
      if (phrases[i].words[0].start <= t + 0.15) idx = i; else break;
    }
    return idx;
  }, [phrases, t]);

  useEffect(() => {
    lineRefs.current[activePhrase]?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [activePhrase]);

  // pitch-lane vertical range
  const lane = useMemo(() => {
    const notes = data?.notes ?? [];
    if (!notes.length) return null;
    let lo = 127, hi = 0;
    for (const [p] of notes) { lo = Math.min(lo, p); hi = Math.max(hi, p); }
    return { notes, lo: lo - 2, hi: hi + 2 };
  }, [data]);
  const noteY = (p: number) => {
    if (!lane) return H / 2;
    const span = Math.max(1, lane.hi - lane.lo);
    return H - 8 - ((p - lane.lo) / span) * (H - 16);
  };

  async function startRec() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mr = new MediaRecorder(stream);
      chunks.current = [];
      mr.ondataavailable = (e) => { if (e.data.size) chunks.current.push(e.data); };
      mr.onstop = () => {
        stream.getTracks().forEach((tk) => tk.stop());
        const blob = new Blob(chunks.current, { type: mr.mimeType || "audio/webm" });
        pause();
        if (blob.size) void tune(blob);
      };
      setTunedUrl(null);
      seek(0);                 // start from the top so the take aligns to the melody
      mr.start(); recRef.current = mr; setRecording(true);
      play();
    } catch (e) { setStatus("Mic access failed: " + String(e)); }
  }
  function stopRec() { recRef.current?.stop(); setRecording(false); }

  async function tune(blob: Blob) {
    setStatus("Auto-tuning your take to the melody…");
    try {
      const { job_id } = await api.autotuneBlock(block, blob, { mode: "natural", strength: 0.85 });
      const job = await api.pollVocal(job_id, (p, m) => setStatus(m || `…${Math.round(p * 100)}%`));
      const tuned = job.result?.urls?.audio;
      if (job.status === "done" && tuned) {
        setTunedUrl(api.mediaUrl(tuned));
        setStatus("Done — here's your tuned take 🎉");
      } else setStatus("Auto-tune failed: " + (job.error || ""));
    } catch (e) { setStatus(String(e)); }
  }

  const noLead = data != null && !data.has_lead;

  return (
    <div className="karaoke">
      <div className="kk-top">
        <div className="kk-title">{block}{data ? ` · ${data.key} ${data.scale}` : ""}</div>
        <button className="kk-close" onClick={() => { pause(); onClose(); }} aria-label="Close">✕</button>
      </div>

      {err && <div className="kk-err">{err}</div>}
      {noLead && <div className="kk-err">No vocal melody yet — compose one from the lyrics first, then sing along.</div>}

      <svg className="kk-lane" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none">
        <line x1={NOW_X} y1={0} x2={NOW_X} y2={H} className="kk-now" />
        {lane?.notes.map(([p, s, e], i) => {
          const x = NOW_X + (s - t) * PX_PER_S;
          const w = Math.max(3, (e - s) * PX_PER_S);
          if (x + w < -40 || x > W + 40) return null;
          const on = s <= t && t < e;
          return (
            <rect key={i} x={x} y={noteY(p) - 6} width={w} height={12} rx={5}
              className={"kk-note" + (on ? " on" : "")} />
          );
        })}
      </svg>

      <div className="kk-lyrics">
        {phrases.map((ph, pi) => (
          <div
            key={pi}
            ref={(el) => { lineRefs.current[pi] = el; }}
            className={"kk-line" + (pi === activePhrase ? " active" : pi < activePhrase ? " past" : "")}
          >
            {ph.words.map((w, wi) => {
              const sung = t >= w.end;
              const now = t >= w.start && t < w.end;
              return (
                <span key={wi} className={"kk-word" + (now ? " now" : sung ? " sung" : "")}>
                  {w.text}{" "}
                </span>
              );
            })}
          </div>
        ))}
      </div>

      <div className="kk-controls">
        <button className="btn ghost" onClick={() => seek(0)} aria-label="Restart">⏮</button>
        {playing
          ? <button className="btn secondary" onClick={pause}>⏸ Pause</button>
          : <button className="btn secondary" onClick={play} disabled={noLead}>▶ Play</button>}
        <button className={"chip" + (guideOn ? " on" : "")} onClick={() => setGuideOn((g) => !g)}
          title="Hear the melody guide louder (turn off when recording your own take)">♪ guide</button>
        {!recording
          ? <button className="btn danger" disabled={noLead} onClick={startRec}>● Sing</button>
          : <button className="btn danger" onClick={stopRec}>■ Stop &amp; tune</button>}
      </div>

      {status && <div className="kk-status">{status}</div>}
      {tunedUrl && (
        <div className="kk-result">
          <div className="te-note">Your tuned take:</div>
          <audio controls src={tunedUrl} />
        </div>
      )}

      <audio ref={backRef} src={api.blockAudioUrl(block)} preload="auto"
        onEnded={() => { setPlaying(false); recRef.current?.stop(); }} />
      <audio ref={guideRef} src={api.vocalGuideAudioUrl(block)} preload="auto" />
    </div>
  );
}
