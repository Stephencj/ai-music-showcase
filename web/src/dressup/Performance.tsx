// The show — your dressed band performs on a lit stage, bobbing and playing in
// time to a song. Music is synthesized live (offline, SynthBand). Watching a
// song through completes the show and earns a star. Self-contained: no backend.
import { useEffect, useRef, useState } from "react";
import Figure from "./Figure";
import { type Member, PART_ICON } from "./wardrobe";
import { SynthBand, SONGS, type Song } from "./music";

const SHOW_BEATS = 32;   // ~one full song before the "show complete" payoff

export default function Performance({ members, onComplete, onClose }: {
  members: Member[];
  onComplete?: () => void;
  onClose: () => void;
}) {
  const [song, setSong] = useState<Song>(SONGS[0]);
  const [playing, setPlaying] = useState(false);
  const [beat, setBeat] = useState(-1);
  const [done, setDone] = useState(false);
  const bandRef = useRef<SynthBand | null>(null);
  const completedRef = useRef(false);

  useEffect(() => {
    const band = new SynthBand((b) => {
      setBeat(b);
      if (b >= SHOW_BEATS && !completedRef.current) {
        completedRef.current = true;
        setDone(true);
        onComplete?.();
      }
    });
    bandRef.current = band;
    return () => band.dispose();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const start = async (s: Song) => {
    setSong(s); setDone(false); completedRef.current = false; setBeat(-1);
    await bandRef.current!.play(s);
    setPlaying(true);
  };
  const stop = () => { bandRef.current!.stop(); setPlaying(false); };

  const downbeat = beat >= 0 && beat % 2 === 0;
  const lineup = members.length ? members : [];

  return (
    <div className="show-screen" style={{ ["--mood" as string]: song.color }}>
      <button className="du-x show-x" onClick={() => { stop(); onClose(); }}>✕</button>

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
            <button className="du-big-btn" onClick={() => start(song)}>▶ Again</button>
            <button className="btn ghost" style={{ width: "auto" }} onClick={onClose}>Done</button>
          </div>
        </div>
      )}

      <div className="show-controls">
        <div className="show-songs">
          {SONGS.map((s) => (
            <button key={s.id} className={"show-song" + (song.id === s.id ? " on" : "")} onClick={() => start(s)}>
              <span>{s.emoji}</span>{s.name}
            </button>
          ))}
        </div>
        <button className="show-play" onClick={() => (playing ? stop() : start(song))}>
          {playing ? "⏸ Stop" : "▶ Play the show"}
        </button>
      </div>
    </div>
  );
}
