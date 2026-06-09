import { useEffect, useRef } from "react";
import { mediaUrl } from "../api";

// Self-playing real sheet music: AlphaTab renders engraved notation and follows
// the practice <audio> element with its cursor (External Media mode = 4, the
// same setup the classic playback tab uses). The high-quality audio is the
// backend FluidSynth render; AlphaTab only draws notation + the moving cursor.

let atLoad: Promise<void> | null = null;
function loadAlphaTab(): Promise<void> {
  const w = window as unknown as { alphaTab?: { AlphaTabApi: unknown } };
  if (w.alphaTab?.AlphaTabApi) return Promise.resolve();
  if (atLoad) return atLoad;
  atLoad = new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = mediaUrl("/static/alphatab/alphaTab.js");  // full build (has MusicXML importer)
    s.onload = () => resolve();
    s.onerror = () => reject(new Error("alphaTab.js failed to load"));
    document.head.appendChild(s);
  });
  return atLoad;
}

export default function SheetMusic({
  blockName, audioRef,
}: {
  blockName: string;
  audioRef: React.RefObject<HTMLAudioElement | null>;
}) {
  const hostRef = useRef<HTMLDivElement>(null);
  const statusRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    let api: any = null;
    let removeListeners = () => {};
    const setStatus = (m: string) => { if (statusRef.current) statusRef.current.textContent = m; };

    setStatus("Loading sheet music…");
    loadAlphaTab().then(() => {
      if (cancelled || !hostRef.current) return;
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const AT = (window as any).alphaTab;
      api = new AT.AlphaTabApi(hostRef.current, {
        core: { fontDirectory: mediaUrl("/static/alphatab/font/") },
        player: {
          enablePlayer: true,
          playerMode: 4,            // EnabledExternalMedia — follow our <audio>
          enableCursor: true,
          enableElementHighlighting: true,
          scrollMode: 3,            // smooth
          scrollSpeed: 300,
          scrollOffsetY: -100,
          scrollElement: hostRef.current,
        },
        display: { layoutMode: 0 }, // page mode — wraps like sheet music
      });

      // Drive the cursor from the practice audio element. AlphaTab only shows
      // and scrolls the cursor while its OWN player state is Playing, so we
      // mirror the audio's play/pause into api.play()/api.pause() — otherwise
      // the cursor stays parked even as updatePosition arrives.
      const audioEl = audioRef.current;
      if (audioEl && api.player && api.player.output) {
        const push = () => {
          try { api.player.output.updatePosition(audioEl.currentTime * 1000); } catch { /* */ }
        };
        const onPlay = () => { try { api.play(); } catch { /* */ } };
        const onPause = () => { try { api.pause(); } catch { /* */ } };
        audioEl.addEventListener("timeupdate", push);
        audioEl.addEventListener("seeked", push);
        audioEl.addEventListener("loadedmetadata", push);
        audioEl.addEventListener("play", onPlay);
        audioEl.addEventListener("pause", onPause);
        removeListeners = () => {
          audioEl.removeEventListener("timeupdate", push);
          audioEl.removeEventListener("seeked", push);
          audioEl.removeEventListener("loadedmetadata", push);
          audioEl.removeEventListener("play", onPlay);
          audioEl.removeEventListener("pause", onPause);
        };
        api.player.output.handler = {
          get backingTrackDuration() {
            return (audioEl.duration && isFinite(audioEl.duration)) ? audioEl.duration * 1000 : 0;
          },
          get playbackRate() { return audioEl.playbackRate || 1; },
          set playbackRate(v: number) { audioEl.playbackRate = v || 1; },
          get masterVolume() { return audioEl.volume; },
          set masterVolume(v: number) { audioEl.volume = v; },
          play() { audioEl.play().catch(() => {}); },
          pause() { audioEl.pause(); },
          seekTo(ms: number) { audioEl.currentTime = (ms || 0) / 1000; },
        };
      }

      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      api.scoreLoaded.on((s: any) => {
        try { if (s?.tracks?.length) api.renderTracks(s.tracks); } catch { /* */ }
      });
      api.renderFinished.on(() => {
        setStatus("");
        const a = audioRef.current;
        if (a) {
          try { api.player?.output?.updatePosition(a.currentTime * 1000); } catch { /* */ }
          if (!a.paused) { try { api.play(); } catch { /* */ } }
        }
      });
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      api.error.on((e: any) => setStatus("Couldn't render: " + (e?.message || e)));

      fetch(mediaUrl(`/api/blocks/${encodeURIComponent(blockName)}/musicxml`))
        .then((r) => { if (!r.ok) throw new Error("score not available"); return r.arrayBuffer(); })
        .then((buf) => { if (!cancelled) { setStatus("Engraving…"); api.load(new Uint8Array(buf)); } })
        .catch((e) => setStatus("Couldn't load score: " + e));
    }).catch((e) => setStatus(String(e)));

    return () => {
      cancelled = true;
      removeListeners();
      try { api?.destroy?.(); } catch { /* */ }
    };
  }, [blockName, audioRef]);

  return (
    <div className="sheet-wrap">
      <div className="sheet-status" ref={statusRef} />
      <div className="sheet" ref={hostRef} />
    </div>
  );
}
