import { useEffect, useRef } from "react";
import { mediaUrl } from "../api";

// Self-playing real sheet music: AlphaTab renders engraved notation and follows
// the practice <audio> element with its cursor (External Media mode = 4, the
// same setup the classic playback tab uses). The high-quality audio is the
// backend FluidSynth render; AlphaTab only draws notation + the moving cursor.
//
// When `trackIndex` is >= 0 the score is reduced to just that instrument's
// staff (so selecting a part isolates the sheet to that part).

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
  blockName, audioRef, trackIndex = -1,
}: {
  blockName: string;
  audioRef: React.RefObject<HTMLAudioElement | null>;
  trackIndex?: number;
}) {
  const hostRef = useRef<HTMLDivElement>(null);
  const statusRef = useRef<HTMLDivElement>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const apiRef = useRef<any>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const scoreRef = useRef<any>(null);

  // Pick the track(s) to render for a given selection.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const renderForIndex = (api: any, score: any, idx: number) => {
    if (!api || !score?.tracks?.length) return;
    const tracks = (idx != null && idx >= 0 && score.tracks[idx])
      ? [score.tracks[idx]] : score.tracks;
    try { api.renderTracks(tracks); } catch { /* */ }
  };

  // Init AlphaTab + load the score once per block.
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
      apiRef.current = api;

      // Bridge the practice <audio> to AlphaTab's external-media output. This
      // is what drives the cursor — but api.player.output isn't always ready
      // the instant after construction, so attach on playerReady (with a
      // retry fallback), not just synchronously.
      let attached = false;
      const attachBridge = () => {
        const audioEl = audioRef.current;
        if (attached || !audioEl || !api.player || !api.player.output) return;
        attached = true;
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
        // If audio is already rolling, get the cursor going immediately.
        push();
        if (!audioEl.paused) { try { api.play(); } catch { /* */ } }
      };
      attachBridge();                                  // try now
      try { api.playerReady.on(attachBridge); } catch { /* */ }
      // Fallback: poll briefly in case playerReady never fires (external media).
      for (let i = 1; i <= 10 && !attached; i++) setTimeout(attachBridge, i * 150);

      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      api.scoreLoaded.on((s: any) => {
        scoreRef.current = s;
        renderForIndex(api, s, trackIndex);
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
      apiRef.current = null;
      scoreRef.current = null;
    };
  }, [blockName, audioRef]);

  // Re-render only the selected instrument when the part changes (no re-fetch).
  useEffect(() => {
    renderForIndex(apiRef.current, scoreRef.current, trackIndex);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [trackIndex]);

  return (
    <div className="sheet-wrap">
      <div className="sheet-status" ref={statusRef} />
      <div className="sheet" ref={hostRef} />
    </div>
  );
}
