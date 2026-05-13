"""Render the HTML scaffold for the Playback tab.

Two pieces:

* ``build_playback_head()`` — returns ``<script>`` tags that load AlphaTab
  + ``playback.js`` from ``/static/alphatab/``. This is plugged into the
  page's ``<head>`` via ``mount_gradio_app(head=...)``. Scripts inserted
  via ``innerHTML`` (what ``gr.HTML`` ends up doing) are ignored by the
  browser per spec, so the scripts MUST land in ``<head>``; otherwise
  ``window.alphaTab`` is undefined and the Playback tab is a blank pane.

* ``build_playback_html()`` — returns the markup (toolbar buttons,
  ``#alphaTab`` mount point, hidden Gradio↔JS bridge inputs). No
  ``<script>`` tags here — they wouldn't execute.

The toolbar uses Gradio's CSS custom properties so light/dark mode are
both readable.
"""

from __future__ import annotations


def build_playback_head() -> str:
    """``<script>`` tags for the page ``<head>``.

    Loads AlphaTab once globally and the playback bridge. The bridge
    uses a MutationObserver to wait for ``#alphaTab`` to appear (the
    div lives inside the Playback tab and only renders when the user
    switches to it), then boots AlphaTab against it.
    """
    return (
        # Use the full alphaTab.js bundle (not .min.js) — the minified
        # release strips every importer except AlphaTex, but we need
        # MusicXmlImporter to load the converted score.
        '<script src="/static/alphatab/alphaTab.js" defer></script>'
        '<script src="/static/alphatab/playback.js" defer></script>'
    )


def build_playback_html(initial_b64_midi: str = "") -> str:
    """Markup for the Playback tab.

    Uses Gradio CSS custom properties (e.g. ``--button-secondary-background-fill``,
    ``--body-text-color``) so the toolbar matches whatever theme is
    active. The dark-mode bug in the first attempt was a forest of
    hardcoded ``#fff`` / ``#000``.
    """
    return f"""
<style>
  #pb-toolbar {{
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.5rem;
    margin: 0.5rem 0;
    color: var(--body-text-color, inherit);
  }}
  #pb-toolbar button {{
    padding: 0.4rem 0.9rem;
    border: 1px solid var(--border-color-primary, #888);
    border-radius: 6px;
    background: var(--button-secondary-background-fill, transparent);
    color: var(--button-secondary-text-color, var(--body-text-color, inherit));
    cursor: pointer;
    font-size: 0.95rem;
  }}
  #pb-toolbar button:hover {{
    background: var(--button-secondary-background-fill-hover, var(--background-fill-secondary, rgba(127,127,127,0.1)));
  }}
  #pb-toolbar button:disabled {{ opacity: 0.5; cursor: not-allowed; }}
  #pb-toolbar .pb-tempo {{
    display: flex; align-items: center; gap: 0.3rem;
    color: var(--body-text-color, inherit);
  }}
  #pb-toolbar #pb-tempo-val {{ min-width: 2.5em; text-align: right; font-variant-numeric: tabular-nums; }}
  #pb-toolbar label.pb-hq {{
    display: flex; align-items: center; gap: 0.3rem;
    color: var(--body-text-color, inherit);
  }}
  #pb-status {{
    font-family: var(--font-mono, monospace);
    color: var(--body-text-color-subdued, #888);
    font-size: 0.85rem;
    margin-left: auto;
  }}
  /* The score area always stays white — engraved notation is black on
     white paper, and the Gradio dark theme would otherwise wash out
     stems / accidentals against a dark background. */
  #alphaTab {{
    width: 100%;
    min-height: 55vh;
    max-height: 78vh;
    overflow: auto;
    border: 1px solid var(--border-color-primary, #888);
    border-radius: 6px;
    background: #ffffff;
    color: #111;
  }}
  /* Force AlphaTab's own SVG/canvas styling to render dark on white
     regardless of the user's theme. */
  #alphaTab svg, #alphaTab .at-surface {{ background: #ffffff; }}
  #alphaTab .at-cursor-bar {{
    background: rgba(0, 122, 255, 0.15);
  }}
  #alphaTab .at-cursor-beat {{
    background: rgba(0, 122, 255, 0.55);
    width: 3px;
  }}
  /* Hide the JS↔Gradio bridge row. We can't use `visible=False` on
     the textbox components themselves because that strips them from
     the DOM in Gradio 6 and the JS bridge has nothing to attach to. */
  .pb-hidden-bridges {{
    position: absolute !important;
    width: 1px !important;
    height: 1px !important;
    overflow: hidden !important;
    clip: rect(0 0 0 0) !important;
    margin: -1px !important;
  }}
</style>

<div id="pb-toolbar">
  <button id="pb-play" type="button">▶ Play</button>
  <button id="pb-pause" type="button">⏸ Pause</button>
  <button id="pb-stop" type="button">⏹ Stop</button>
  <span class="pb-tempo">
    Tempo:
    <input id="pb-tempo" type="range" min="40" max="220" value="120" step="1">
    <span id="pb-tempo-val">120</span> BPM
  </span>
  <label class="pb-hq">
    <input id="pb-use-hq" type="checkbox" disabled> Use HQ mix
  </label>
  <span id="pb-status">loading…</span>
</div>

<div id="alphaTab" data-initial-midi="{initial_b64_midi}"></div>
<audio id="pb-hq-audio" preload="auto" style="display:none;"></audio>
"""
