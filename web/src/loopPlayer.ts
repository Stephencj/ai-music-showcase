// Seamless, pitch-preserved section-loop player built on Web Audio +
// SoundTouchJS. The native <audio> element can change speed without pitch
// (preservesPitch), but seeking an encoded stream back to a loop start always
// leaves a decoder priming gap — you hear a hiccup at the seam. This engine
// decodes the whole clip into an in-memory AudioBuffer ONCE, then loops by
// resetting SoundTouch's source sample position, which is instantaneous: no
// re-decode, no gap. Pitch is locked (pitch = 1.0) while `tempo` does the
// time-stretch, so any practice speed keeps the original key.
//
// Used by PracticeScreen for the section-loop case only; ordinary playback
// stays on the native element.
import { PitchShifter } from "soundtouchjs";

const BUFFER_SIZE = 4096;

export class LoopPlayer {
  private ctx: AudioContext;
  private buffer: AudioBuffer | null = null;
  private shifter: PitchShifter | null = null;
  private url = "";
  private _tempo = 1;
  private loopStart = 0;
  private loopEnd = 0; // 0 ⇒ no loop (play straight through)
  playing = false;

  // Clock: SoundTouch reports `timePlayed`, but that's the source position the
  // pipeline has *consumed* (extracted), which runs AHEAD of what you actually
  // hear by the SoundTouch lookahead + the output-buffer queue. `lead` (output
  // seconds) is that gap: we subtract it to get the AUDIBLE position, and both
  // the smooth 60fps clock and the loop wrap key off the audible position so a
  // section plays in full before it restarts. Tunable — larger = wraps later.
  private anchorSrc = 0;
  private anchorCtx = 0;
  lead = 0.22;

  constructor() {
    const AC: typeof AudioContext =
      window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
    this.ctx = new AC();
  }

  get duration(): number {
    return this.buffer ? this.buffer.duration : 0;
  }

  /** Decode a clip into memory. No-op if the same URL is already loaded. */
  async load(url: string): Promise<void> {
    if (url === this.url && this.buffer) return;
    const res = await fetch(url);
    const arr = await res.arrayBuffer();
    this.buffer = await this.ctx.decodeAudioData(arr);
    this.url = url;
  }

  setTempo(tempo: number): void {
    if (this.playing) this._reanchor(); // freeze current interpolated time first
    this._tempo = tempo;
    if (this.shifter) this.shifter.tempo = tempo;
  }

  setLoop(start: number, end: number): void {
    this.loopStart = start;
    this.loopEnd = end;
  }

  clearLoop(): void {
    this.loopStart = 0;
    this.loopEnd = 0;
  }

  /** Start (or restart) playback. `fromSec` defaults to the current position. */
  async play(fromSec?: number): Promise<void> {
    if (!this.buffer) return;
    if (this.ctx.state === "suspended") await this.ctx.resume();
    let off = fromSec != null ? fromSec : this.getTime();
    // Keep the start inside the active loop region (a stale/odd resume point
    // would otherwise trigger an immediate wrap or play the wrong spot).
    if (this.loopEnd > 0 && (off < this.loopStart || off >= this.loopEnd)) {
      off = this.loopStart;
    }
    this._build(off);
    this.playing = true;
  }

  pause(): void {
    this.anchorSrc = this.getTime(); // freeze the clock where we stopped
    this.anchorCtx = this.ctx.currentTime;
    if (this.shifter) {
      try { this.shifter.disconnect(); } catch { /* already gone */ }
      this.shifter = null;
    }
    this.playing = false;
  }

  seek(sec: number): void {
    this.anchorSrc = sec;
    this.anchorCtx = this.ctx.currentTime;
    if (this.playing) this.play(sec);
  }

  /** Interpolated source-time position, in seconds. */
  getTime(): number {
    if (!this.playing) return this.anchorSrc;
    let tt = this.anchorSrc + (this.ctx.currentTime - this.anchorCtx) * this._tempo;
    if (this.loopEnd > 0) {
      const span = this.loopEnd - this.loopStart;
      if (span > 0 && tt >= this.loopEnd) tt = this.loopStart + ((tt - this.loopStart) % span);
    }
    return tt;
  }

  destroy(): void {
    this.pause();
    try { this.ctx.close(); } catch { /* ignore */ }
  }

  private _reanchor(): void {
    this.anchorSrc = this.getTime();
    this.anchorCtx = this.ctx.currentTime;
  }

  private _build(offsetSec: number): void {
    if (!this.buffer) return;
    if (this.shifter) {
      try { this.shifter.disconnect(); } catch { /* ignore */ }
      this.shifter = null;
    }
    const sh = new PitchShifter(this.ctx, this.buffer, BUFFER_SIZE);
    sh.tempo = this._tempo;
    sh.pitch = 1.0;
    sh.percentagePlayed = (offsetSec / this.duration) * 100;
    this.anchorSrc = offsetSec;
    this.anchorCtx = this.ctx.currentTime;
    sh.on("play", (detail) => {
      // Work in AUDIBLE source seconds: `timePlayed` is the extract position,
      // which leads what's playing by ~`lead` output-seconds (scaled by tempo
      // into source-seconds). Loop only once the *audible* head reaches the
      // section end, so the tail isn't cut off and it doesn't restart early.
      const audible = detail.timePlayed - this.lead * this._tempo;
      if (this.loopEnd > 0 && audible >= this.loopEnd) {
        // In-memory pointer reset → no decode, no gap at the seam.
        sh.percentagePlayed = (this.loopStart / this.duration) * 100;
        this.anchorSrc = this.loopStart;
        this.anchorCtx = this.ctx.currentTime;
        return;
      }
      this.anchorSrc = Math.max(0, audible);
      this.anchorCtx = this.ctx.currentTime;
    });
    sh.connect(this.ctx.destination);
    this.shifter = sh;
  }
}
