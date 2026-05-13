/* AI Music Studio — Playback tab bridge for AlphaTab.
 *
 * Loaded once from <head>. The Playback tab is built lazily by Gradio
 * (the #alphaTab div doesn't exist on initial page load — only when the
 * user switches to the Playback tab), so we use a MutationObserver to
 * wait for it to appear and then boot AlphaTab against it.
 *
 * Responsibilities:
 *   1. Boot AlphaTab against `#alphaTab` with the vendored soundfont + font.
 *   2. Watch the hidden `#pb_midi_payload` textarea (Gradio writes to it
 *      from the server) and re-load AlphaTab with the new MIDI bytes —
 *      no full re-init, soundfont stays cached.
 *   3. Watch `#pb_hq_wav_url`; when set + the "Use HQ mix" checkbox is
 *      on, mute AlphaTab's synth and play the WAV through a hidden
 *      <audio> element while AlphaTab still drives the cursor (master
 *      clock, no drift).
 *   4. On note click, write JSON into `#pb_note_event` and click the
 *      hidden `#pb_note_trigger` button so the server-side handler can
 *      format the pitch/duration/bar markdown.
 *   5. Gate the first Play tap behind `audioContext.resume()` so iOS
 *      Safari unlocks audio.
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
    // Gradio renders a hidden Textbox as a wrapping element with elem_id
    // on the wrapper; the actual <textarea> is inside.
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

  // Track the currently-booted AlphaTab so re-boots can dispose old.
  let currentApi = null;
  let currentRoot = null;

  function bootAlphaTab(root) {
    if (!window.alphaTab || !window.alphaTab.AlphaTabApi) {
      log("alphaTab not yet loaded; retrying");
      return setTimeout(() => bootAlphaTab(root), 200);
    }
    if (currentApi && currentRoot === root) {
      return currentApi;
    }
    if (currentApi) {
      try { currentApi.destroy(); } catch (_) {}
      currentApi = null;
    }

    log("booting AlphaTab against", root);
    const settings = {
      core: {
        fontDirectory: "/static/alphatab/font/",
      },
      player: {
        enablePlayer: true,
        soundFont: "/static/alphatab/soundfont/sonivox.sf2",
        scrollMode: 1,           // 0=off, 1=continuous, 2=offscreen-only
        scrollElement: root,
      },
      display: {
        layoutMode: 1,           // 0=page, 1=horizontal (Guitar-Pro feel)
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

    api.scoreLoaded.on((score) => {
      log("score loaded", score && score.title);
      setStatus("ready");
    });
    api.error.on((err) => {
      console.error("[playback] alphaTab error:", err);
      setStatus("error: " + (err && err.message ? err.message : String(err)));
    });
    api.renderStarted.on(() => setStatus("rendering…"));
    api.renderFinished.on(() => setStatus("ready"));

    const initial = root.getAttribute("data-initial-midi") || "";
    if (initial) {
      try {
        api.load(base64ToBytes(initial));
      } catch (e) {
        console.error("[playback] initial load failed:", e);
      }
    } else {
      setStatus("pick a source above");
    }

    wireControls(api);
    wireBridges(api);
    return api;
  }

  // ----- Controls --------------------------------------------------------

  function wireControls(api) {
    let unlocked = false;
    function unlock() {
      if (unlocked) return;
      try {
        const ctx = api.player && api.player.audioContext;
        if (ctx && ctx.state === "suspended") ctx.resume();
      } catch (_) {}
      unlocked = true;
    }

    const playBtn = $("pb-play");
    const pauseBtn = $("pb-pause");
    const stopBtn = $("pb-stop");
    if (playBtn && !playBtn.__pbWired) {
      playBtn.addEventListener("click", () => { unlock(); api.play(); });
      playBtn.__pbWired = true;
    }
    if (pauseBtn && !pauseBtn.__pbWired) {
      pauseBtn.addEventListener("click", () => api.pause());
      pauseBtn.__pbWired = true;
    }
    if (stopBtn && !stopBtn.__pbWired) {
      stopBtn.addEventListener("click", () => api.stop());
      stopBtn.__pbWired = true;
    }

    const tempoSlider = $("pb-tempo");
    const tempoVal = $("pb-tempo-val");
    if (tempoSlider && !tempoSlider.__pbWired) {
      tempoSlider.addEventListener("input", () => {
        const bpm = parseInt(tempoSlider.value, 10) || 120;
        if (tempoVal) tempoVal.textContent = String(bpm);
        try { api.playbackSpeed = bpm / 120.0; } catch (_) {}
      });
      tempoSlider.__pbWired = true;
    }

    const hqCheckbox = $("pb-use-hq");
    if (hqCheckbox && !hqCheckbox.__pbWired) {
      hqCheckbox.addEventListener("change", () => {
        const url = window.__aiMusicHqWavUrl || "";
        if (hqCheckbox.checked && url) enableHqMix(api, url);
        else disableHqMix(api);
      });
      hqCheckbox.__pbWired = true;
    }
  }

  // ----- HQ-WAV master-clock sync ---------------------------------------

  function enableHqMix(api, url) {
    const audio = $("pb-hq-audio");
    if (!audio) return;
    audio.src = url;
    audio.load();
    try { api.player.outputGain = 0; } catch (_) {}
    setStatus("HQ mix on");
    audio.play().catch(() => {});
  }
  function disableHqMix(api) {
    const audio = $("pb-hq-audio");
    if (audio) {
      audio.pause();
      audio.removeAttribute("src");
    }
    try { api.player.outputGain = 1; } catch (_) {}
    setStatus("synth on");
  }

  // ----- Gradio↔JS bridges -----------------------------------------------

  function wireBridges(api) {
    // MIDI payload — server writes new base64 MIDI when source changes.
    const midiInput = findHiddenInput("pb_midi_payload");
    if (midiInput && !midiInput.__pbWired) {
      let last = midiInput.value;
      const reload = () => {
        const b64 = midiInput.value || "";
        if (!b64 || b64 === last) return;
        last = b64;
        try { api.load(base64ToBytes(b64)); setStatus("loading…"); }
        catch (e) { console.error("[playback] reload failed:", e); }
      };
      midiInput.addEventListener("input", reload);
      // Poll because Gradio updates the value without firing input.
      setInterval(reload, 400);
      midiInput.__pbWired = true;
    }

    // HQ-WAV URL — server writes when the HQ render finishes.
    const hqInput = findHiddenInput("pb_hq_wav_url");
    const hqCheckbox = $("pb-use-hq");
    if (hqInput && !hqInput.__pbWired) {
      let lastUrl = hqInput.value;
      const onHqChange = () => {
        const url = hqInput.value || "";
        if (url === lastUrl) return;
        lastUrl = url;
        window.__aiMusicHqWavUrl = url;
        if (!hqCheckbox) return;
        if (url) {
          hqCheckbox.disabled = false;
          setStatus("HQ ready — toggle to use");
        } else {
          hqCheckbox.disabled = true;
          hqCheckbox.checked = false;
          disableHqMix(api);
        }
      };
      hqInput.addEventListener("input", onHqChange);
      setInterval(onHqChange, 400);
      hqInput.__pbWired = true;
    }

    // HQ-WAV clock-sync: AlphaTab is master; we nudge audio.currentTime
    // only when it drifts > 50 ms.
    api.playerPositionChanged.on((args) => {
      if (!hqCheckbox || !hqCheckbox.checked) return;
      const audio = $("pb-hq-audio");
      if (!audio || !audio.src) return;
      const target = args.currentTime / 1000.0;
      if (Math.abs(audio.currentTime - target) > 0.05) {
        audio.currentTime = target;
      }
    });
    api.playerStateChanged.on((args) => {
      if (!hqCheckbox || !hqCheckbox.checked) return;
      const audio = $("pb-hq-audio");
      if (!audio || !audio.src) return;
      const playing = args.state === 1;
      if (playing) audio.play().catch(() => {});
      else audio.pause();
    });

    // Note clicks — push JSON into the hidden textbox, click trigger.
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
        // Use the React/Svelte-aware value setter so the framework sees
        // the change.
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
      // tab just rendered — boot or rebind
      bootAlphaTab(root);
    } else if (root && currentApi) {
      // root re-rendered but we already have an api — re-wire controls.
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
