// The show — your dressed band performs on a lit stage, bobbing and playing in
// time. Two song sources: built-in SYNTH tunes (offline, no files) and, when
// provided (band app, online), your real generated songs played from audio +
// their tempo. Watching a song through completes the show (a star / fans).
import { useEffect, useRef, useState } from "react";
import Figure from "./Figure";
import { type Member, PART_ICON } from "./wardrobe";
import { SynthBand, SONGS, type Song } from "./music";

const SHOW_BEATS = 32;   // ~one full synth song before the payoff

export interface RealSong { id: string; name: string; url: string; bpm: number; }
type Track = { kind: "synth"; song: Song } | { kind: "audio"; song: RealSong };

export default function Performance({ members, realSongs, onComplete, onClose }: {
  members: Member[];
  realSongs?: RealSong[];
  onComplete?: () => void;
  onClose: () => void;
}) {
  const synthTracks: Track[] = SONGS.map((s) => ({ kind: "synth", song: s }));
  const audioTracks: Track[] = (realSongs || []).map((s) => ({ kind: "audio", song: s }));

  const [track, setTrack] = useState<Track>(synthTracks[0]);
  const [playing, setPlaying] = useState(false);
  const [beat, setBeat] = useState(-1);
  const [done, setDone] = useState(false);
  const bandRef = useRef<SynthBand | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const rafRef = useRef(0);
  const completedRef = useRef(false);

  const complete = () => {
    if (completedRef.current) return;
    completedRef.current = true; setDone(true); onComplete?.();
  };

  useEffect(() => {
    bandRef.current = new SynthBand((b) => {
      setBeat(b);
      if (b >= SHOW_BEATS) complete();
    });
    return () => { bandRef.current?.dispose(); cancelAnimationFrame(rafRef.current); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const stop = () => {
    bandRef.current?.stop();
    cancelAnimationFrame(rafRef.current);
    const a = audioRef.current; if (a) { a.pause(); }
    setPlaying(false);
  };

  const audioTick = (bpm: number) => {
    const a = audioRef.current; if (!a) return;
    setBeat(Math.floor(a.currentTime * (bpm / 60)));
    rafRef.current = requestAnimationFrame(() => audioTick(bpm));
  };

  const start = async (t: Track) => {
    stop();
    setTrack(t); setDone(false); completedRef.current = false; setBeat(-1);
    if (t.kind === "synth") {
      await bandRef.current!.play(t.song);
    } else {
      const a = audioRef.current!;
      a.src = t.song.url; a.currentTime = 0;
      try { await a.play(); } catch { /* autoplay blocked → user taps again */ }
      cancelAnimationFrame(rafRef.current);
      audioTick(t.song.bpm);
    }
    setPlaying(true);
  };

  const downbeat = beat >= 0 && beat % 2 === 0;
  const mood = track.kind === "synth" ? track.song.color : "#7c3aed";
  const lineup = members.length ? members : [];

  return (
    <div className="show-screen" style={{ ["--mood" as string]: mood }}>
      <button className="du-x show-x" onClick={() => { stop(); onClose(); }}>✕</button>
      <audio ref={audioRef} onEnded={complete} style={{ display: "none" }} />

      <div className="show-lights"><i /><i /><i /></div>

      <div className="show-stage">
        <div className="show-band">
          {lineup.map((m, i) => (
            <div key={m.id} className={"show-member" + (playing ? " live" : "")}
              style={{
                animationDelay: `${(i % 3) * 0.12}s`,
                transform: playing ? `translateY(${(beat + i) % 2 === 0 ? -10 : 0}px)` : "none",
              }}>
              <Figure member={m} size={120} />
              <span className="show-part">{PART_ICON[m.part]}</span>
            </div>
          ))}
        </div>
        <div className={"show-floor" + (downbeat ? " pulse" : "")} />
      </div>

      {done && (
        <div className="show-complete">
          <div className="show-burst">🌟🎉⭐✨🎊</div>
          <h2>Amazing show!</h2>
          <p>You earned a ⭐</p>
          <div className="show-complete-actions">
            <button className="du-big-btn" onClick={() => start(track)}>▶ Again</button>
            <button className="btn ghost" style={{ width: "auto" }} onClick={onClose}>Done</button>
          </div>
        </div>
      )}

      <div className="show-controls">
        <div className="show-songs">
          {synthTracks.map((t) => t.kind === "synth" && (
            <button key={t.song.id} className={"show-song" + (track.kind === "synth" && track.song.id === t.song.id ? " on" : "")}
              onClick={() => start(t)}><span>{t.song.emoji}</span>{t.song.name}</button>
          ))}
          {audioTracks.length > 0 && <div className="show-song-div">Your songs</div>}
          {audioTracks.map((t) => t.kind === "audio" && (
            <button key={t.song.id} className={"show-song" + (track.kind === "audio" && track.song.id === t.song.id ? " on" : "")}
              onClick={() => start(t)}><span>🎵</span>{t.song.name}</button>
          ))}
        </div>
        <button className="show-play" onClick={() => (playing ? stop() : start(track))}>
          {playing ? "⏸ Stop" : "▶ Play the show"}
        </button>
      </div>
    </div>
  );
}
