"""Render the HTML scaffold for the Playback tab.

The HTML is emitted ONCE when the tab is built. It wires up:

* ``<div id="alphaTab">`` — AlphaTab attaches its score viewer + cursor here.
* Two Gradio hidden-textbox bridges (``pb_midi_payload``, ``pb_hq_wav_url``)
  that ``playback.js`` polls via ``MutationObserver`` to receive new MIDI
  data and HQ-WAV URLs without re-rendering the whole HTML.
* The note-click bridge: ``playback.js`` writes JSON into ``pb_note_event``
  and clicks ``pb_note_trigger`` to fire the server-side handler.

Keeping the HTML stable means AlphaTab never re-initialises — the ~3 MB
soundfont stays cached and switching sources only re-runs the engraver.
"""

from __future__ import annotations


def build_playback_html(initial_b64_midi: str = "") -> str:
    """Return the static HTML payload for the Playback tab.

    ``initial_b64_midi`` is base64-encoded MIDI bytes. Empty string is
    valid (the tab will sit waiting for the first source-dropdown
    selection).
    """
    return f"""
<link rel="stylesheet" href="/static/alphatab/alphaTab.min.css">
<style>
  #alphaTab {{
    width: 100%;
    min-height: 50vh;
    max-height: 75vh;
    overflow: auto;
    border: 1px solid #ccc;
    background: #fafafa;
  }}
  #pb-toolbar {{
    display: flex; align-items: center; gap: 0.5rem;
    margin: 0.5rem 0;
  }}
  #pb-toolbar button {{
    padding: 0.4rem 0.8rem;
    border: 1px solid #888;
    border-radius: 4px;
    background: #fff;
    cursor: pointer;
  }}
  #pb-toolbar button:hover {{ background: #eef; }}
  #pb-toolbar button:disabled {{ opacity: 0.5; cursor: not-allowed; }}
  #pb-toolbar .pb-tempo {{ display: flex; align-items: center; gap: 0.25rem; }}
  #pb-status {{ font-family: monospace; color: #666; font-size: 0.9em; }}
</style>

<div id="pb-toolbar">
  <button id="pb-play">▶ Play</button>
  <button id="pb-pause">⏸ Pause</button>
  <button id="pb-stop">⏹ Stop</button>
  <span class="pb-tempo">
    Tempo:
    <input id="pb-tempo" type="range" min="40" max="220" value="120" step="1">
    <span id="pb-tempo-val">120</span> BPM
  </span>
  <label style="margin-left:1rem;">
    <input id="pb-use-hq" type="checkbox" disabled> Use HQ mix
  </label>
  <span id="pb-status">loading…</span>
</div>

<div id="alphaTab" data-initial-midi="{initial_b64_midi}"></div>
<audio id="pb-hq-audio" preload="auto" style="display:none;"></audio>

<script src="/static/alphatab/alphaTab.min.js"></script>
<script src="/static/alphatab/playback.js"></script>
"""
