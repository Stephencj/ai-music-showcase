// Tiny offline music engine for the band's show — a few cheerful preset songs
// synthesized live with Web Audio (chords + bass + a bouncy melody + a simple
// beat). No audio files, so it works fully offline in the standalone app. Calls
// onBeat(beat) every quarter-note so the stage can animate in time.

export interface Song {
  id: string; name: string; emoji: string; bpm: number;
  root: number;            // root MIDI note
  scale: number[];         // semitone offsets (major / minor pentatonic etc.)
  chords: number[];        // chord-root scale degrees per bar (loop)
  color: string;           // stage mood colour
}

export const SONGS: Song[] = [
  { id: "bounce", name: "Bouncy", emoji: "🦘", bpm: 120, root: 60, scale: [0, 2, 4, 5, 7, 9, 11], chords: [0, 4, 5, 3], color: "#7c3aed" },
  { id: "sparkle", name: "Sparkle Pop", emoji: "✨", bpm: 132, root: 64, scale: [0, 2, 4, 7, 9], chords: [0, 5, 3, 4], color: "#db2777" },
  { id: "parade", name: "Parade", emoji: "🎉", bpm: 108, root: 62, scale: [0, 2, 4, 5, 7, 9], chords: [0, 3, 4, 0], color: "#0ea5e9" },
  { id: "starlight", name: "Starlight", emoji: "🌟", bpm: 96, root: 57, scale: [0, 3, 5, 7, 10], chords: [0, 5, 3, 4], color: "#0f766e" },
];

const mtof = (m: number) => 440 * Math.pow(2, (m - 69) / 12);

export class SynthBand {
  private ctx: AudioContext | null = null;
  private master: GainNode | null = null;
  private timer: number | null = null;
  private nextNoteTime = 0;
  private beat = 0;
  private song: Song = SONGS[0];
  private onBeat: (b: number) => void;
  playing = false;

  constructor(onBeat: (b: number) => void) { this.onBeat = onBeat; }

  private osc(type: OscillatorType, freq: number, t: number, dur: number, gain: number, dest: AudioNode) {
    const o = this.ctx!.createOscillator(); const g = this.ctx!.createGain();
    o.type = type; o.frequency.value = freq;
    g.gain.setValueAtTime(0, t);
    g.gain.linearRampToValueAtTime(gain, t + 0.015);
    g.gain.exponentialRampToValueAtTime(0.0008, t + dur);
    o.connect(g); g.connect(dest); o.start(t); o.stop(t + dur + 0.02);
  }

  private noise(t: number, dur: number, gain: number, hp: number) {
    const ctx = this.ctx!; const n = Math.floor(ctx.sampleRate * dur);
    const buf = ctx.createBuffer(1, n, ctx.sampleRate); const d = buf.getChannelData(0);
    for (let i = 0; i < n; i++) d[i] = Math.random() * 2 - 1;
    const src = ctx.createBufferSource(); src.buffer = buf;
    const f = ctx.createBiquadFilter(); f.type = "highpass"; f.frequency.value = hp;
    const g = ctx.createGain(); g.gain.setValueAtTime(gain, t); g.gain.exponentialRampToValueAtTime(0.0008, t + dur);
    src.connect(f); f.connect(g); g.connect(this.master!); src.start(t); src.stop(t + dur);
  }

  private kick(t: number) {
    const o = this.ctx!.createOscillator(); const g = this.ctx!.createGain();
    o.frequency.setValueAtTime(140, t); o.frequency.exponentialRampToValueAtTime(45, t + 0.12);
    g.gain.setValueAtTime(0.9, t); g.gain.exponentialRampToValueAtTime(0.001, t + 0.16);
    o.connect(g); g.connect(this.master!); o.start(t); o.stop(t + 0.18);
  }

  private degToMidi(deg: number, oct = 0) {
    const s = this.song.scale; const i = ((deg % s.length) + s.length) % s.length;
    const octShift = Math.floor(deg / s.length) + oct;
    return this.song.root + s[i] + 12 * octShift;
  }

  private scheduleBeat(beat: number, t: number) {
    const spb = 60 / this.song.bpm;
    const bar = Math.floor(beat / 4) % this.song.chords.length;
    const beatInBar = beat % 4;
    const chordDeg = this.song.chords[bar];

    // Chord pad on the downbeat (triad from the scale).
    if (beatInBar === 0) {
      for (const d of [0, 2, 4]) this.osc("triangle", mtof(this.degToMidi(chordDeg + d, 0)), t, spb * 3.6, 0.07, this.master!);
    }
    // Bass on every beat.
    this.osc("sine", mtof(this.degToMidi(chordDeg, -1)), t, spb * 0.9, 0.18, this.master!);
    // Bouncy melody — a couple of eighth notes per beat from the chord/scale.
    const motif = [0, 2, 4, 2, 1, 3, 4, 5];
    for (const e of [0, 1]) {
      const idx = (beat * 2 + e) % motif.length;
      const note = this.degToMidi(chordDeg + motif[idx], 1);
      this.osc("square", mtof(note), t + e * spb / 2, spb * 0.42, 0.05, this.master!);
    }
    // Beat: kick on 0 & 2, snare on 1 & 3, hats on every eighth.
    if (beatInBar % 2 === 0) this.kick(t);
    if (beatInBar % 2 === 1) this.noise(t, 0.18, 0.25, 1800);
    this.noise(t, 0.04, 0.06, 7000);
    this.noise(t + spb / 2, 0.04, 0.05, 7000);

    this.onBeat(beat);
  }

  private loop = () => {
    const spb = 60 / this.song.bpm;
    while (this.nextNoteTime < this.ctx!.currentTime + 0.12) {
      this.scheduleBeat(this.beat, this.nextNoteTime);
      this.nextNoteTime += spb;
      this.beat++;
    }
    this.timer = window.setTimeout(this.loop, 25);
  };

  async play(song: Song) {
    this.song = song;
    if (!this.ctx) {
      this.ctx = new (window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext)();
      this.master = this.ctx.createGain(); this.master.gain.value = 0.5; this.master.connect(this.ctx.destination);
    }
    if (this.ctx.state === "suspended") await this.ctx.resume();
    this.stopTimer();
    this.beat = 0;
    this.nextNoteTime = this.ctx.currentTime + 0.06;
    this.playing = true;
    this.loop();
  }

  private stopTimer() { if (this.timer != null) { clearTimeout(this.timer); this.timer = null; } }

  stop() { this.stopTimer(); this.playing = false; }

  dispose() { this.stop(); try { this.ctx?.close(); } catch { /* closed */ } this.ctx = null; }

  get beatsPerBar() { return 4; }
}
