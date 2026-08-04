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

export default function Performance({ members, realSongs, set, onComplete, onSetComplete, onClose }: {
  members: Member[];
  realSongs?: RealSong[];
  set?: RealSong[];             // an ordered set — auto-advances through it
  onComplete?: () => void;
  onSetComplete?: () => void;
  onClose: () => void;
}) {
  const synthTracks: Track[] = SONGS.map((s) => ({ kind: "synth", song: s }));
  const audioTracks: Track[] = (realSongs || []).map((s) => ({ kind: "audio", song: s }));

  const [track, setTrack] = useState<Track>(synthTracks[0]);
  const [playing, setPlaying] = useState(false);
  const [beat, setBeat] = useState(-1);
  const [done, setDone] = useState(false);
  const [setPos, setSetPos] = useState(-1);       // index within `set`, -1 = not performing the set
  const [setFinished, setSetFinished] = useState(false);
  const bandRef = useRef<SynthBand | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const rafRef = useRef(0);
  const completedRef = useRef(false);
  const setPosRef = useRef(-1);                    // stable index for the audio onEnded callback

  const complete = () => {
    if (completedRef.current) return;
    completedRef.current = true; setDone(true); onComplete?.();
  };

  // Perform the ordered set: start song i, and when a song ends advance to the
  // next; after the last, the set is complete.
  const startSetAt = (i: number) => {
    if (!set || i < 0 || i >= set.length) return;
    setPosRef.current = i; setSetPos(i); setSetFinished(false);
    start({ kind: "audio", song: set[i] });
  };
  const songEnded = () => {
    const i = setPosRef.current;
    if (i >= 0 && set && i < set.length - 1) { startSetAt(i + 1); return; }
    if (i >= 0 && set) {                            // finished the final song of the set
      setPosRef.current = -1; setSetPos(-1);
      stop(); setSetFinished(true); setDone(true); onSetComplete?.();
      return;
    }
    complete();                                     // single-song path
  };
  const leaveSet = () => { setPosRef.current = -1; setSetPos(-1); };

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
      <audio ref={audioRef} onEnded={songEnded} style={{ display: "none" }} />

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
        <div className="show-complete" data-testid="show-complete">
          <div className="show-burst">🌟🎉⭐✨🎊</div>
          <h2>{setFinished ? "Set complete!" : "Amazing show!"}</h2>
          <p>{setFinished
            ? `Your band played all ${set?.length ?? 0} songs 🎤`
            : "You earned a ⭐"}</p>
          <div className="show-complete-actions">
            <button className="du-big-btn"
              onClick={() => (setFinished && set ? startSetAt(0) : start(track))}>
              ▶ {setFinished ? "Play the set again" : "Again"}
            </button>
            <button className="btn ghost" style={{ width: "auto" }} onClick={onClose}>Done</button>
          </div>
        </div>
      )}

      <div className="show-controls">
        {set && set.length > 0 && (
          <div className="show-set" data-testid="show-set">
            {setPos >= 0 ? (
              <div className="show-set-now" data-testid="show-set-now">
                🎤 Song {setPos + 1} of {set.length}: <b>{set[setPos].name}</b>
              </div>
            ) : (
              <div className="show-set-now">🎤 {set.length}-song set ready</div>
            )}
            <div className="show-set-btns">
              <button className="show-play" data-testid="play-set"
                onClick={() => startSetAt(0)}>
                {setPos >= 0 ? "↻ Restart set" : "▶ Play the set"}
              </button>
              {setPos >= 0 && (
                <button className="btn ghost sm" style={{ width: "auto" }}
                  data-testid="set-next" onClick={songEnded}>⏭ Next</button>
              )}
            </div>
          </div>
        )}
        <div className="show-songs">
          {synthTracks.map((t) => t.kind === "synth" && (
            <button key={t.song.id} className={"show-song" + (track.kind === "synth" && track.song.id === t.song.id ? " on" : "")}
              onClick={() => { leaveSet(); start(t); }}><span>{t.song.emoji}</span>{t.song.name}</button>
          ))}
          {audioTracks.length > 0 && <div className="show-song-div">Your songs</div>}
          {audioTracks.map((t) => t.kind === "audio" && (
            <button key={t.song.id} className={"show-song" + (track.kind === "audio" && track.song.id === t.song.id ? " on" : "")}
              onClick={() => { leaveSet(); start(t); }}><span>🎵</span>{t.song.name}</button>
          ))}
        </div>
        {!(set && set.length) && (
          <button className="show-play" onClick={() => (playing ? stop() : start(track))}>
            {playing ? "⏸ Stop" : "▶ Play the show"}
          </button>
        )}
      </div>
    </div>
  );
}
