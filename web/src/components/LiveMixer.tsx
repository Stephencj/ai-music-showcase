// Live mixing: load a block's baseline stems into Web Audio and mix them in
// REAL TIME. Each stem gets its own node chain — 3-band EQ → distortion shaper
// → compressor → fader — plus reverb/delay sends to shared buses. The
// MixingDesk's controls drive the node params live (no server round-trip), so
// moving a fader or EQ band is heard instantly while the song plays. "Bounce"
// commits the current mix to the song via the producer endpoint (offline render
// — that pass also applies chorus and the master chain).
import { useEffect, useRef, useState } from "react";
import * as api from "../api";
import MixingDesk, { type MixState, type TrackSettings, cleanMix } from "./MixingDesk";

const dbToGain = (db: number) => Math.pow(10, db / 20);

// One stem's real-time chain. Sources are one-shot, recreated on each Play.
interface Chan {
  name: string;
  buffer: AudioBuffer;
  src: AudioBufferSourceNode | null;
  low: BiquadFilterNode; mid: BiquadFilterNode; high: BiquadFilterNode;
  shaper: WaveShaperNode;
  chorusWet: GainNode;    // modulated-delay chorus, mixed in parallel with dry
  comp: DynamicsCompressorNode;
  fader: GainNode;        // gain + mute
  revSend: GainNode; dlySend: GainNode;
}

// A soft-clip curve for the distortion shaper; amount 0 → near-linear.
function distortionCurve(amount: number): Float32Array<ArrayBuffer> {
  const n = 1024, curve = new Float32Array(new ArrayBuffer(n * 4)), k = amount * 60;
  for (let i = 0; i < n; i++) {
    const x = (i / (n - 1)) * 2 - 1;
    curve[i] = amount <= 0 ? x : ((1 + k) * x) / (1 + k * Math.abs(x));
  }
  return curve;
}

// A short decaying-noise impulse response — a serviceable plate-ish reverb
// without shipping an audio asset.
function makeIR(ctx: AudioContext, seconds = 2.2, decay = 3.0): AudioBuffer {
  const rate = ctx.sampleRate, len = Math.floor(rate * seconds);
  const ir = ctx.createBuffer(2, len, rate);
  for (let c = 0; c < 2; c++) {
    const d = ir.getChannelData(c);
    for (let i = 0; i < len; i++)
      d[i] = (Math.random() * 2 - 1) * Math.pow(1 - i / len, decay);
  }
  return ir;
}

export default function LiveMixer({ blockName, onClose, onBounced }: {
  blockName: string; onClose: () => void;
  onBounced?: (name: string, production: number) => void;
}) {
  const [tracks, setTracks] = useState<string[]>([]);
  const [mix, setMix] = useState<MixState>({});
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [playing, setPlaying] = useState(false);
  const [pos, setPos] = useState(0);          // playhead seconds
  const [dur, setDur] = useState(0);
  const [bouncing, setBouncing] = useState(false);
  const [bounced, setBounced] = useState<number | null>(null);

  const ctxRef = useRef<AudioContext | null>(null);
  const chansRef = useRef<Chan[]>([]);
  const masterRef = useRef<GainNode | null>(null);
  const startRef = useRef(0);                  // ctx time when playback began
  const rafRef = useRef(0);
  const mixRef = useRef<MixState>(mix);
  mixRef.current = mix;

  // ── Load stems + build the graph ──────────────────────────────────────────
  useEffect(() => {
    let dead = false;
    const ctx = new (window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext)();
    ctxRef.current = ctx;
    const master = ctx.createGain(); master.gain.value = 0.9; master.connect(ctx.destination);
    masterRef.current = master;

    // Shared FX buses.
    const conv = ctx.createConvolver(); conv.buffer = makeIR(ctx); conv.connect(master);
    const delay = ctx.createDelay(1.0); delay.delayTime.value = 0.25;
    const fb = ctx.createGain(); fb.gain.value = 0.3;
    delay.connect(fb); fb.connect(delay); delay.connect(master);

    (async () => {
      try {
        const meta = await api.liveStems(blockName);
        if (dead) return;
        setDur(meta.duration);
        const loaded = await Promise.all(meta.tracks.map(async (t) => {
          const ab = await fetch(api.mediaUrl(t.url)).then((r) => r.arrayBuffer());
          const buffer = await ctx.decodeAudioData(ab);
          const low = ctx.createBiquadFilter(); low.type = "lowshelf"; low.frequency.value = 120;
          const mid = ctx.createBiquadFilter(); mid.type = "peaking"; mid.frequency.value = 1000; mid.Q.value = 0.8;
          const high = ctx.createBiquadFilter(); high.type = "highshelf"; high.frequency.value = 4500;
          const shaper = ctx.createWaveShaper(); shaper.curve = distortionCurve(0);
          const comp = ctx.createDynamicsCompressor();
          comp.threshold.value = 0; comp.ratio.value = 1; comp.attack.value = 0.012; comp.release.value = 0.14;
          const fader = ctx.createGain();
          const revSend = ctx.createGain(); revSend.gain.value = 0; revSend.connect(conv);
          const dlySend = ctx.createGain(); dlySend.gain.value = 0; dlySend.connect(delay);
          // Chorus: a short delay (~27 ms) whose time is swept by an LFO; the
          // pitch-wobbled copy is mixed back in parallel with the dry signal.
          const chDelay = ctx.createDelay(0.1); chDelay.delayTime.value = 0.027;
          const lfo = ctx.createOscillator(); lfo.type = "sine"; lfo.frequency.value = 0.8;
          const lfoGain = ctx.createGain(); lfoGain.gain.value = 0.004;   // ±4 ms depth
          lfo.connect(lfoGain); lfoGain.connect(chDelay.delayTime); lfo.start();
          const chorusWet = ctx.createGain(); chorusWet.gain.value = 0;
          // Chain: low → mid → high → shaper → [dry → comp] + [chDelay → wet → comp]
          low.connect(mid); mid.connect(high); high.connect(shaper);
          shaper.connect(comp);
          shaper.connect(chDelay); chDelay.connect(chorusWet); chorusWet.connect(comp);
          comp.connect(fader);
          fader.connect(master); fader.connect(revSend); fader.connect(dlySend);
          return { name: t.name, buffer, src: null, low, mid, high, shaper, chorusWet, comp, fader, revSend, dlySend } as Chan;
        }));
        if (dead) { ctx.close(); return; }
        chansRef.current = loaded;
        setTracks(loaded.map((c) => c.name));
        setLoading(false);
      } catch (e) {
        if (!dead) { setErr(e instanceof Error ? e.message : "Couldn't load stems"); setLoading(false); }
      }
    })();

    return () => {
      dead = true;
      cancelAnimationFrame(rafRef.current);
      try { ctx.close(); } catch { /* already closed */ }
    };
  }, [blockName]);

  // ── Push the current mix onto the live node params ────────────────────────
  const applyMix = (m: MixState) => {
    const ctx = ctxRef.current; if (!ctx) return;
    for (const c of chansRef.current) {
      const s: TrackSettings = m[c.name] || {};
      c.low.gain.value = s.eq?.low_db ?? 0;
      c.mid.gain.value = s.eq?.mid_db ?? 0;
      c.high.gain.value = s.eq?.high_db ?? 0;
      const dist = s.fx?.distortion ?? 0;
      c.shaper.curve = distortionCurve(dist);
      const ratio = s.comp?.ratio ?? 1;
      c.comp.ratio.value = ratio;
      c.comp.threshold.value = ratio > 1 ? -20 : 0;
      c.fader.gain.value = s.mute ? 0 : dbToGain(s.gain_db ?? 0);
      c.chorusWet.gain.value = (s.fx?.chorus ?? 0) * 0.7;
      c.revSend.gain.value = s.fx?.reverb ?? 0;
      c.dlySend.gain.value = (s.fx?.delay ?? 0) * 0.6;
    }
  };
  useEffect(() => { applyMix(mix); }, [mix]);

  const tick = () => {
    const ctx = ctxRef.current; if (!ctx) return;
    const t = ctx.currentTime - startRef.current;
    if (t >= dur) { stop(); return; }
    setPos(t);
    rafRef.current = requestAnimationFrame(tick);
  };

  const play = async (from = 0) => {
    const ctx = ctxRef.current; if (!ctx || !chansRef.current.length) return;
    if (ctx.state === "suspended") await ctx.resume();
    const at = ctx.currentTime + 0.06;        // common start for sample-accurate sync
    for (const c of chansRef.current) {
      const src = ctx.createBufferSource(); src.buffer = c.buffer;
      src.connect(c.low); src.start(at, from); c.src = src;
    }
    applyMix(mixRef.current);
    startRef.current = at - from;
    setPlaying(true);
    cancelAnimationFrame(rafRef.current);
    rafRef.current = requestAnimationFrame(tick);
  };

  const stop = () => {
    cancelAnimationFrame(rafRef.current);
    for (const c of chansRef.current) { try { c.src?.stop(); } catch { /* not started */ } c.src = null; }
    setPlaying(false);
  };

  const bounce = async () => {
    setBouncing(true);
    try {
      const r = await api.produceBlock(blockName, { track_mix: cleanMix(mix), master_preset: "default" });
      setBounced(r.production);
      onBounced?.(r.name, r.production);
    } finally { setBouncing(false); }
  };

  const mm = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

  return (
    <div className="cof-backdrop" onClick={onClose}>
      <div className="gig-modal" onClick={(e) => e.stopPropagation()}>
        <div className="cof-head">
          <span className="cof-title">🎚 Live mix · {blockName}</span>
          <button className="cof-close" onClick={onClose}>✕</button>
        </div>
        {err ? <div className="practice-hint">{err}</div>
          : loading ? <div className="practice-hint">Loading stems into the mixer…</div>
          : (
            <>
              <div className="lm-transport">
                <button className="btn" style={{ width: "auto" }}
                  onClick={() => (playing ? stop() : play(pos >= dur ? 0 : pos))}>
                  {playing ? "⏸ Stop" : "▶ Play"}
                </button>
                <button className="btn ghost sm" style={{ width: "auto" }}
                  onClick={() => { stop(); setPos(0); }}>⏮</button>
                <div className="lm-time">{mm(pos)} / {mm(dur)}</div>
                <div className="lm-bar"><i style={{ width: dur ? `${(pos / dur) * 100}%` : 0 }} /></div>
              </div>
              <div className="meta" style={{ margin: "2px 0 8px" }}>
                Move any control while it plays — you'll hear it instantly. The master chain is applied on Bounce.
              </div>
              <MixingDesk tracks={tracks} mix={mix} onChange={setMix} />
              <div className="et-actions">
                <button className="btn ghost" style={{ width: "auto" }} disabled={bouncing} onClick={bounce}>
                  {bouncing ? "Bouncing…" : "💾 Bounce to song"}
                </button>
              </div>
              {bounced != null && (
                <div className="gig-payout">Bounced · production <b>×{bounced.toFixed(2)}</b> saved to the song.</div>
              )}
            </>
          )}
      </div>
    </div>
  );
}
