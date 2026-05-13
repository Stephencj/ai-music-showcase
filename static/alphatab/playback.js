/* AI Music Studio — Playback tab bridge for AlphaTab.
 *
 * Responsibilities:
 *   1. Boot AlphaTab against `#alphaTab` with the vendored soundfont + font.
 *   2. Listen for new MIDI data on the hidden `#pb_midi_payload` textarea
 *      (Gradio updates it from the server) and re-load AlphaTab with the
 *      new bytes — no full re-init, soundfont stays cached.
 *   3. Listen for HQ-WAV URLs on `#pb_hq_wav_url`; when set + the
 *      "Use HQ mix" checkbox is on, mute AlphaTab's synth and play the
 *      WAV through an <audio> element while AlphaTab still drives the
 *      cursor (master clock).
 *   4. On note click in the score, write JSON into `#pb_note_event` and
 *      click the hidden `#pb_note_trigger` button so the server-side
 *      handler can format the pitch/duration/bar markdown.
 *   5. Gate the first `Play` tap behind `audioContext.resume()` so iOS
 *      Safari unlocks audio.
 */
(function () {
  "use strict";

  if (window.__aiMusicPlaybackBooted) {
    return;
  }
  window.__aiMusicPlaybackBooted = true;

  function base64ToBytes(b64) {
    const binary = atob(b64);
    const len = binary.length;
    const bytes = new Uint8Array(len);
    for (let i = 0; i < len; i++) bytes[i] = binary.charCodeAt(i);
    return bytes;
  }

  function $(id) { return document.getElementById(id); }

  function findHiddenInput(elemId) {
    // Gradio renders a hidden Textbox as a wrapping <div id="..."> with
    // a <textarea> inside. The elem_id we set lands on the wrapper.
    const wrapper = document.getElementById(elemId);
    if (!wrapper) return null;
    return wrapper.querySelector("textarea, input");
  }

  function findGradioButton(elemId) {
    const wrapper = document.getElementById(elemId);
    if (!wrapper) return null;
    return wrapper.querySelector("button");
  }

  function bootAlphaTab() {
    const root = $("alphaTab");
    if (!root || !window.alphaTab) {
      // alphaTab.min.js may still be loading; retry shortly.
      return setTimeout(bootAlphaTab, 80);
    }
    const initialB64 = root.getAttribute("data-initial-midi") || "";
    const settings = {
      core: {
        fontDirectory: "/static/alphatab/font/",
      },
      player: {
        enablePlayer: true,
        soundFont: "/static/alphatab/soundfont/sonivox.sf2",
        scrollMode: 1, // continuous auto-scroll
        scrollElement: root,
      },
      display: {
        layoutMode: 1, // horizontal — pages flow left→right (Guitar-Pro feel)
      },
    };
    const api = new window.alphaTab.AlphaTabApi(root, settings);
    window.__aiMusicAlphaTab = api;

    if (initialB64) {
      try { api.load(base64ToBytes(initialB64)); } catch (e) { console.error(e); }
    }

    wireControls(api);
    wireBridges(api);
    setStatus("ready");
  }

  function wireControls(api) {
    let audioUnlocked = false;
    $("pb-play").addEventListener("click", () => {
      if (!audioUnlocked) {
        try {
          const ctx = api.player && api.player.audioContext;
          if (ctx && ctx.state === "suspended") ctx.resume();
        } catch (e) { /* iOS quirk — ignore */ }
        audioUnlocked = true;
      }
      api.play();
    });
    $("pb-pause").addEventListener("click", () => api.pause());
    $("pb-stop").addEventListener("click", () => api.stop());

    const tempoSlider = $("pb-tempo");
    const tempoVal = $("pb-tempo-val");
    tempoSlider.addEventListener("input", () => {
      const bpm = parseInt(tempoSlider.value, 10);
      tempoVal.textContent = String(bpm);
      // playbackSpeed is a multiplier; reset and apply
      try {
        api.playbackSpeed = bpm / 120.0;
      } catch (e) { /* may not be ready yet */ }
    });

    const hqCheckbox = $("pb-use-hq");
    hqCheckbox.addEventListener("change", () => {
      const url = window.__aiMusicHqWavUrl || "";
      if (hqCheckbox.checked && url) {
        enableHqMix(api, url);
      } else {
        disableHqMix(api);
      }
    });
  }

  function setStatus(msg) {
    const el = $("pb-status");
    if (el) el.textContent = msg;
  }

  // ----- HQ-WAV master-clock sync -----------------------------------------
  // AlphaTab stays the master clock. We mute its synth and drive the
  // <audio> element's currentTime from its playerPositionChanged event
  // — within a 50 ms tolerance to avoid restart stutter.

  function enableHqMix(api, url) {
    const audio = $("pb-hq-audio");
    audio.src = url;
    audio.load();
    try { api.player.outputGain = 0; } catch (e) {}
    setStatus("HQ mix on");
    audio.play().catch(() => {});
  }
  function disableHqMix(api) {
    const audio = $("pb-hq-audio");
    audio.pause();
    audio.removeAttribute("src");
    try { api.player.outputGain = 1; } catch (e) {}
    setStatus("synth on");
  }

  function wireBridges(api) {
    // ----- Inbound: MIDI payload changes ---------------------------------
    const midiInput = findHiddenInput("pb_midi_payload");
    if (midiInput) {
      const reloadFromInput = () => {
        const b64 = midiInput.value || "";
        if (!b64) return;
        try { api.load(base64ToBytes(b64)); setStatus("loaded"); }
        catch (e) { console.error("midi load failed", e); }
      };
      midiInput.addEventListener("input", reloadFromInput);
      // Also poll a couple times in case Gradio updates without input event.
      let polled = midiInput.value;
      setInterval(() => {
        if (midiInput.value !== polled) {
          polled = midiInput.value;
          reloadFromInput();
        }
      }, 500);
    }

    // ----- Inbound: HQ-WAV URL changes -----------------------------------
    const hqInput = findHiddenInput("pb_hq_wav_url");
    const hqCheckbox = $("pb-use-hq");
    if (hqInput) {
      const onHqChange = () => {
        const url = hqInput.value || "";
        window.__aiMusicHqWavUrl = url;
        if (url) {
          hqCheckbox.disabled = false;
          setStatus("HQ ready");
        } else {
          hqCheckbox.disabled = true;
          hqCheckbox.checked = false;
          disableHqMix(api);
        }
      };
      hqInput.addEventListener("input", onHqChange);
      let pollHq = hqInput.value;
      setInterval(() => {
        if (hqInput.value !== pollHq) {
          pollHq = hqInput.value;
          onHqChange();
        }
      }, 500);
    }

    // ----- HQ-WAV master-clock tick --------------------------------------
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
      // AlphaTab states: 0=Paused, 1=Playing, 2=Stopped (approx).
      const audio = $("pb-hq-audio");
      if (!audio || !audio.src) return;
      if (args.state === 1) {
        audio.play().catch(() => {});
      } else {
        audio.pause();
      }
    });

    // ----- Outbound: note clicks → server handler ------------------------
    const noteInput = findHiddenInput("pb_note_event");
    const noteBtn = findGradioButton("pb_note_trigger");

    api.noteMouseDown.on((note) => {
      try {
        const beat = note.beat;
        const voice = beat.voice;
        const bar = voice.bar;
        // beat.absolutePlaybackStart is ticks-from-start
        try { api.tickPosition = beat.absolutePlaybackStart; } catch (e) {}
        if (!noteInput || !noteBtn) return;
        const payload = {
          pitch: note.realValueAsString || "",
          midi: note.realValue || 0,
          octave: note.octave || 0,
          durQuarters: beat.duration ? (4.0 / beat.duration) : 0,
          barIdx: bar.index !== undefined ? bar.index : 0,
          beatIdx: beat.index !== undefined ? beat.index : 0,
          trackName: (note.beat.voice.bar.staff.track.name) || "",
          ts: Date.now(),
        };
        noteInput.value = JSON.stringify(payload);
        noteInput.dispatchEvent(new Event("input", { bubbles: true }));
        // Click the hidden Gradio button so the server handler fires now.
        noteBtn.click();
      } catch (e) {
        console.warn("noteMouseDown bridge:", e);
      }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bootAlphaTab);
  } else {
    bootAlphaTab();
  }
})();
