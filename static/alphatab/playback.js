/* AI Music Studio — Playback tab bridge for AlphaTab.
 *
 * Loaded from <head>. The Playback tab is rendered lazily by Gradio
 * (the #alphaTab div doesn't exist on initial page load — only when
 * the user switches to the Playback tab), so we use a MutationObserver
 * to wait for it to appear, then boot AlphaTab against it.
 *
 * The audio engine is the pre-rendered WAV that the compose / block /
 * song pipelines already produce. AlphaTab runs in
 * PlayerMode.EnabledExternalMedia: its cursor follows our <audio>
 * element's currentTime, but it does NOT synthesise any audio in
 * the browser. That single fix:
 *
 *   - kills the iOS playback latency / choppiness (no AudioWorklet),
 *   - makes drums sound right (real channel-10 FluidSynth samples
 *     instead of AlphaTab pitch-shifting our percussion rewrites).
 */
(function () {
  "use strict";

  function log() {
    try { console.log.apply(console, ["[playback]"].concat([].slice.call(arguments))); }
    catch (_) {}
  }

  function base64ToBytes(b64) {
    const binary = atob(b64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
    return bytes;
  }

  function $(id) { return document.getElementById(id); }

  function findHiddenInput(elemId) {
    const wrapper = document.getElementById(elemId);
    if (!wrapper) return null;
    if (wrapper.tagName === "TEXTAREA" || wrapper.tagName === "INPUT") return wrapper;
    return wrapper.querySelector("textarea, input");
  }

  function findGradioButton(elemId) {
    const wrapper = document.getElementById(elemId);
    if (!wrapper) return null;
    if (wrapper.tagName === "BUTTON") return wrapper;
    return wrapper.querySelector("button");
  }

  function setStatus(msg) {
    const el = $("pb-status");
    if (el) el.textContent = msg;
  }

  // ----- External-media handler -----------------------------------------
  // AlphaTab calls our handler's play/pause/seekTo, and we call its
  // output.updatePosition(ms) to advance the cursor.
  function makeExternalAudioHandler(audioEl, output) {
    function pushPosition() {
      if (audioEl && typeof output.updatePosition === "function") {
        output.updatePosition(audioEl.currentTime * 1000);
      }
    }
    audioEl.addEventListener("timeupdate", pushPosition);
    audioEl.addEventListener("seeked", pushPosition);
    audioEl.addEventListener("loadedmetadata", () => {
      // AlphaTab queries backingTrackDuration before play; fire once
      // so the cursor scale is correct from frame 1.
      pushPosition();
    });
    return {
      audioEl,
      get backingTrackDuration() {
        return (audioEl.duration && isFinite(audioEl.duration))
          ? audioEl.duration * 1000 : 0;
      },
      get playbackRate() { return audioEl.playbackRate || 1; },
      set playbackRate(v) { audioEl.playbackRate = v || 1; },
      get masterVolume() { return audioEl.volume; },
      set masterVolume(v) { audioEl.volume = v; },
      play() { audioEl.play().catch((e) => console.warn("[playback] audio.play() rejected:", e)); },
      pause() { audioEl.pause(); },
      seekTo(timeMs) { audioEl.currentTime = (timeMs || 0) / 1000; },
    };
  }

  let currentApi = null;
  let currentRoot = null;

  function bootAlphaTab(root) {
    if (!window.alphaTab || !window.alphaTab.AlphaTabApi) {
      log("alphaTab not yet loaded; retrying");
      return setTimeout(() => bootAlphaTab(root), 200);
    }
    if (currentApi && currentRoot === root) return currentApi;
    if (currentApi) {
      try { currentApi.destroy(); } catch (_) {}
      currentApi = null;
    }

    log("booting AlphaTab against", root);
    // PlayerMode.EnabledExternalMedia = 4 — we drive the cursor from
    // an <audio> element instead of AlphaTab's WebAudio synth.
    const settings = {
      core: {
        fontDirectory: "/static/alphatab/font/",
      },
      player: {
        enablePlayer: true,
        playerMode: 4,  // PlayerMode.EnabledExternalMedia
        enableCursor: true,
        scrollMode: 1,
        scrollElement: root,
      },
      display: {
        layoutMode: 0,  // page mode — lines wrap like sheet music
      },
    };

    let api;
    try {
      api = new window.alphaTab.AlphaTabApi(root, settings);
    } catch (e) {
      console.error("[playback] AlphaTabApi failed:", e);
      setStatus("error: " + (e && e.message ? e.message : String(e)));
      return null;
    }
    window.__aiMusicAlphaTab = api;
    currentApi = api;
    currentRoot = root;

    // Attach the external-media handler once the player is constructed.
    const audioEl = $("pb-audio");
    if (audioEl && api.player && api.player.output) {
      try {
        api.player.output.handler = makeExternalAudioHandler(audioEl, api.player.output);
        log("external media handler attached");
      } catch (e) {
        console.error("[playback] handler attach failed:", e);
      }
    }

    api.scoreLoaded.on((s) => {
      log("score loaded", s && s.title);
      setStatus("ready");
      // AlphaTab defaults to rendering only the first track. Force all
      // tracks so the user sees a real conductor score by default.
      try {
        if (s && s.tracks && s.tracks.length) {
          api.renderTracks(s.tracks);
          populateTrackSelector(api, s.tracks);
        }
      } catch (e) {
        console.warn("[playback] renderTracks failed:", e);
      }
    });
    api.error.on((err) => {
      console.error("[playback] alphaTab error:", err);
      setStatus("error: " + (err && err.message ? err.message : String(err)));
    });
    api.renderStarted.on(() => setStatus("rendering…"));
    api.renderFinished.on(() => setStatus("ready"));

    const initial = root.getAttribute("data-initial-midi") || "";
    if (initial) {
      try { api.load(base64ToBytes(initial)); }
      catch (e) { console.error("[playback] initial load failed:", e); }
    } else {
      setStatus("pick a source above");
    }

    wireControls(api);
    wireBridges(api);
    return api;
  }

  // ----- Track selector --------------------------------------------------

  function populateTrackSelector(api, tracks) {
    const sel = $("pb-track-select");
    if (!sel) return;
    // Wipe existing options (other than "all") and rebuild.
    sel.innerHTML = "";
    const allOpt = document.createElement("option");
    allOpt.value = "all";
    allOpt.textContent = `Full score (${tracks.length} parts)`;
    sel.appendChild(allOpt);
    tracks.forEach((t) => {
      const opt = document.createElement("option");
      opt.value = String(t.index);
      opt.textContent = t.name || `Part ${t.index + 1}`;
      sel.appendChild(opt);
    });
    if (!sel.__pbWired) {
      sel.addEventListener("change", () => {
        const v = sel.value;
        const score = api.score;
        if (!score) return;
        try {
          if (v === "all") {
            api.renderTracks(score.tracks);
          } else {
            const idx = parseInt(v, 10);
            const target = score.tracks.find((t) => t.index === idx);
            if (target) api.renderTracks([target]);
          }
        } catch (e) {
          console.warn("[playback] renderTracks (select) failed:", e);
        }
      });
      sel.__pbWired = true;
    }
  }

  // ----- Controls --------------------------------------------------------

  function wireControls(api) {
    const audioEl = $("pb-audio");
    const playBtn = $("pb-play");
    const pauseBtn = $("pb-pause");
    const stopBtn = $("pb-stop");

    if (playBtn && !playBtn.__pbWired) {
      playBtn.addEventListener("click", () => {
        // First-tap iOS unlock — call audio.play() from the user-gesture
        // turn so Safari's autoplay policy doesn't reject the call we
        // route through AlphaTab below.
        if (audioEl && audioEl.src) {
          audioEl.play().catch((e) =>
            console.warn("[playback] audio.play() rejected:", e));
        }
        try { api.play(); } catch (_) {}
      });
      playBtn.__pbWired = true;
    }
    if (pauseBtn && !pauseBtn.__pbWired) {
      pauseBtn.addEventListener("click", () => {
        try { api.pause(); } catch (_) {}
        if (audioEl) audioEl.pause();
      });
      pauseBtn.__pbWired = true;
    }
    if (stopBtn && !stopBtn.__pbWired) {
      stopBtn.addEventListener("click", () => {
        try { api.stop(); } catch (_) {}
        if (audioEl) { audioEl.pause(); audioEl.currentTime = 0; }
      });
      stopBtn.__pbWired = true;
    }

    const speedSlider = $("pb-tempo");
    const speedVal = $("pb-tempo-val");
    if (speedSlider && !speedSlider.__pbWired) {
      speedSlider.addEventListener("input", () => {
        const pct = parseInt(speedSlider.value, 10) || 100;
        if (speedVal) speedVal.textContent = String(pct);
        const rate = pct / 100;
        if (audioEl) {
          audioEl.playbackRate = rate;
          // preservesPitch keeps the pitch the same when speed changes.
          if ("preservesPitch" in audioEl) audioEl.preservesPitch = true;
        }
        try { api.playbackSpeed = rate; } catch (_) {}
      });
      speedSlider.__pbWired = true;
    }
  }

  // ----- Gradio↔JS bridges -----------------------------------------------

  function wireBridges(api) {
    const audioEl = $("pb-audio");

    // MIDI/MusicXML payload — server writes new bytes when source changes.
    const midiInput = findHiddenInput("pb_midi_payload");
    if (midiInput && !midiInput.__pbWired) {
      let last = midiInput.value;
      const reload = () => {
        const b64 = midiInput.value || "";
        if (!b64 || b64 === last) return;
        last = b64;
        try { api.load(base64ToBytes(b64)); setStatus("loading…"); }
        catch (e) { console.error("[playback] score reload failed:", e); }
      };
      midiInput.addEventListener("input", reload);
      setInterval(reload, 400);
      midiInput.__pbWired = true;
    }

    // Audio URL — server writes when source changes OR when an HQ render
    // finishes. We swap the <audio> element's src in-place.
    const audioInput = findHiddenInput("pb_audio_url");
    if (audioInput && audioEl && !audioInput.__pbWired) {
      let lastUrl = audioEl.src || audioInput.value;
      const onAudioUrl = () => {
        const url = audioInput.value || "";
        if (url === lastUrl) return;
        lastUrl = url;
        if (url) {
          const wasPlaying = !audioEl.paused;
          audioEl.src = url;
          audioEl.load();
          if (wasPlaying) audioEl.play().catch(() => {});
        }
      };
      audioInput.addEventListener("input", onAudioUrl);
      setInterval(onAudioUrl, 400);
      audioInput.__pbWired = true;
    }

    // Note clicks — push JSON into the hidden textbox, click trigger
    // button so the server-side handler fires immediately.
    const noteInput = findHiddenInput("pb_note_event");
    const noteBtn = findGradioButton("pb_note_trigger");
    api.noteMouseDown.on((note) => {
      try {
        const beat = note.beat;
        const bar = beat && beat.voice && beat.voice.bar;
        try { api.tickPosition = beat.absolutePlaybackStart; } catch (_) {}
        if (!noteInput || !noteBtn) return;
        const payload = {
          pitch: note.realValueAsString || "",
          midi: note.realValue || 0,
          octave: note.octave || 0,
          durQuarters: beat && beat.duration ? (4.0 / beat.duration) : 0,
          barIdx: (bar && bar.index !== undefined) ? bar.index : 0,
          beatIdx: (beat && beat.index !== undefined) ? beat.index : 0,
          trackName: (bar && bar.staff && bar.staff.track && bar.staff.track.name) || "",
          ts: Date.now(),
        };
        const proto = Object.getPrototypeOf(noteInput);
        const setter = Object.getOwnPropertyDescriptor(proto, "value").set;
        setter.call(noteInput, JSON.stringify(payload));
        noteInput.dispatchEvent(new Event("input", { bubbles: true }));
        noteBtn.click();
      } catch (e) {
        console.warn("[playback] noteMouseDown bridge:", e);
      }
    });
  }

  // ----- DOM-observer entry point ----------------------------------------

  function checkForRoot() {
    const root = $("alphaTab");
    if (root && root !== currentRoot) {
      bootAlphaTab(root);
    } else if (root && currentApi) {
      // Re-wire controls in case Gradio re-rendered the toolbar.
      wireControls(currentApi);
      wireBridges(currentApi);
    }
  }

  function start() {
    checkForRoot();
    const obs = new MutationObserver(() => checkForRoot());
    obs.observe(document.body, { childList: true, subtree: true });
    window.__aiMusicPlaybackBooted = true;
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
