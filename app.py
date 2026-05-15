#!/usr/bin/env python3
"""
AI Music Studio — Gradio web interface.

Launch with:
    python app.py

Then open http://localhost:7860 in your browser.
"""

import atexit
import gc
import logging
import re
import shutil
import tempfile
from typing import Optional
import traceback
from pathlib import Path

import gradio as gr
import numpy as np
import soundfile as sf

from src.audio_processing.render import (
    MASTER_PRESETS, render_to_audio,
)
from src.audio_processing.render.soundfont_resolver import (
    download_default as download_default_soundfont,
)
from src.daw_integration.ardour.client import ArdourSessionBuilder
from src.daw_integration.logic import LogicSessionBundle
from src.daw_integration.generic.midi_export import (
    MidiExporter, SCALES, THEMES, ARPEGGIO_PATTERNS, STRUM_RHYTHMS,
    GRID_DRUM_ROWS, drum_pattern_to_grid, grid_step_labels,
    grid_subdivs_for_meter, note_name_to_midi,
    CADENCES, MELODIC_LICKS, TENSION_OPS, HARMONY_OPS,
    PHRASE_CONTOURS, MOTIF_DEVELOPMENT_OPS,
)
from src.daw_integration.generic.styles import STYLES, list_styles
from src.composition.instruments import (
    FAMILIES,
    FAMILY_LABELS,
    INSTRUMENT_REGISTRY,
    instruments_for_family,
)
from src.daw_integration.generic.song_spec import (
    Section, SongSpec, render as render_song_spec,
)
from src.daw_integration.generic import user_presets
from src.daw_integration.generic import blocks as block_store
from src.daw_integration.generic import block_concat
from src.daw_integration.generic import songs as song_store
from src.daw_integration.generic import validation as audit
from src.daw_integration.generic import melody_plan as mp
from src.models import ModelConfig, get_model
from src.scoring.pdf_export import (
    export_zip as _pdf_export_zip,
    is_lilypond_available,
)
from src.playback.playback_html import build_playback_html

# ---------------------------------------------------------------------------
# Logging — writes structured runtime events to logs/app.log so we can
# diagnose errors after the fact. (run.command also tees Terminal output
# to the same file for pre-Python launch errors.)
# ---------------------------------------------------------------------------
LOG_DIR = Path("logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "app.log"

logger = logging.getLogger("ai_music_studio")
if not logger.handlers:
    logger.setLevel(logging.INFO)
    _fh = logging.FileHandler(LOG_FILE)
    _fh.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    ))
    logger.addHandler(_fh)
    logger.propagate = False


def _logged_error(action: str, exc: Exception) -> gr.Error:
    """Log an unexpected exception with traceback and return a user-facing
    gr.Error pointing at the log file."""
    logger.error(
        "%s failed: %s: %s\n%s",
        action, type(exc).__name__, exc, traceback.format_exc(),
    )
    return gr.Error(f"{action} failed: {exc}. See logs/app.log for details.")


# ---------------------------------------------------------------------------
# Shared state — hold onto last-generated audio so Export tab can use them
# ---------------------------------------------------------------------------
_state = {
    "ai_wav_path": None,     # Path to last AI-generated .wav (re-read on demand)
    "midi_wav_path": None,   # Path to last MIDI preview .wav (re-read on demand)
    "midi_path": None,       # Path to .mid file
    "model": None,           # cached MusicGen model instance
}


def _shutdown():
    """Release the cached MusicGen model and clear state on app exit.
    Without this the MPS-resident model stays pinned until the OS reaps the
    process; on Ctrl-C in the launcher that's our only chance to free it."""
    m = _state.get("model")
    if m is not None:
        try:
            m.cleanup()
        except Exception:
            logger.exception("shutdown cleanup failed")
    _state.clear()
    gc.collect()


atexit.register(_shutdown)

OUTPUT_DIR = Path("data/outputs/app")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

logger.info("AI Music Studio starting up — log file: %s", LOG_FILE)


def _get_model(size: str):
    """Return a cached model, re-loading only if size changed."""
    current = _state.get("model")
    if current is not None and current.config.model_size == size:
        return current
    # Cleanup old model
    if current is not None:
        current.cleanup()
    config = ModelConfig(name="musicgen", model_size=size)
    model = get_model("musicgen", config=config)
    model.initialize()
    _state["model"] = model
    return model


# ===================================================================
# Tab 1 — Generate (MusicGen)
# ===================================================================

def generate_audio(prompt: str, size: str, duration: float, temperature: float,
                   progress=gr.Progress(track_tqdm=True)):
    if not prompt.strip():
        raise gr.Error("Please enter a text prompt.")

    try:
        logger.info("generate_audio: prompt=%r size=%s duration=%.1f temp=%.2f",
                    prompt, size, duration, temperature)
        progress(0, desc="Loading model...")
        model = _get_model(size)

        progress(0.1, desc=f"Generating ~{duration:.0f}s of audio...")
        result = model.generate(prompt, duration=duration, temperature=temperature)

        # Save to temp wav for Gradio audio player
        wav_path = OUTPUT_DIR / "last_ai_generation.wav"
        model.save_audio(result, wav_path)

        _state["ai_wav_path"] = wav_path
        info = f"Generated {result.duration:.1f}s at {result.sample_rate} Hz on {model.config.device}"
        del result
        gc.collect()

        return str(wav_path), info
    except gr.Error:
        raise
    except Exception as e:
        raise _logged_error("Generate audio", e) from e


# ===================================================================
# Tab 2 — Compose (MIDI)
# ===================================================================

def _parse_time_sig(label: str) -> tuple[int, int]:
    """Parse '4/4' / '3/4' / '6/8' to (num, den)."""
    num, den = label.split("/")
    return int(num), int(den)


def _progression_plan_to_text(plan) -> str:
    """Serialize a progression plan back to the textbox form.

    Inverse of ``_parse_progression_text``: ``[("I", 2.0), ("V", 1.0),
    "vi", ("IV", 0.5)]`` → ``"I:2 V vi IV:0.5"``. Bare 1.0 durations render
    as the symbol alone so the default form ``I V vi IV`` is preserved
    when serialising a single-bar-per-chord plan.
    """
    if not plan:
        return ""
    parts: list[str] = []
    for item in plan:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, (tuple, list)) and len(item) >= 2:
            symbol, dur = item[0], float(item[1])
            if abs(dur - 1.0) < 1e-6:
                parts.append(str(symbol))
            elif abs(dur - round(dur)) < 1e-6:
                parts.append(f"{symbol}:{int(round(dur))}")
            else:
                parts.append(f"{symbol}:{dur:g}")
        else:
            parts.append(str(item))
    return " ".join(parts)


_BRACKET_REPEAT_RE = re.compile(r"\[([^\[\]]+)\]\s*[xX]\s*(\d+)")
# Single-symbol repeat. Negative lookbehind for ":" so a paced token
# like "I:0.5 x4" doesn't get mis-grabbed as a symbol-repeat — paced
# tokens must wrap with brackets to repeat: "[I:0.5] x4".
_SYMBOL_REPEAT_RE = re.compile(
    r"(?<![:\w])"                       # not preceded by colon or word char
    r"([A-Za-z][A-Za-z0-9#°ø♭/\-]*)"    # roman symbol (no colon allowed)
    r"\s*[xX]\s*(\d+)\b"
)


def _expand_progression_shorthand(text: str) -> str:
    """Expand ``[X Y Z] xN`` and bare ``Symbol xN`` repeats into a flat
    space-separated token stream.

    Strict precedence so the two new forms don't collide with the
    legacy paced / sub-bar tokenizer:

    1. Brackets first — applied repeatedly so nested groups
       ``[I [V vi] x2 IV] x4`` resolve inside-out.
    2. Bare-symbol repeats — ``I x4`` → ``I I I I``. The negative-
       lookbehind on ``:`` keeps paced tokens (``I:2 x4`` is invalid
       shorthand; users wanting to repeat a paced token must wrap
       it: ``[I:2] x4``).

    Unmatched / malformed brackets pass through untouched — the
    downstream tokenizer logs a warning and falls back to 1-bar
    bare-symbol parsing, which is the safest user-visible behaviour.
    """
    if not text:
        return ""
    # Bracket pass — repeated until fixed-point. Cap iterations so a
    # pathological input can't hang the parser.
    for _ in range(16):
        new_text = _BRACKET_REPEAT_RE.sub(
            lambda m: (" " + m.group(1).strip() + " ") * int(m.group(2)),
            text,
        )
        if new_text == text:
            break
        text = new_text
    # Bare-symbol pass — single regex application is enough since
    # nested ``Symbol xN`` can't exist (only one symbol per match).
    text = _SYMBOL_REPEAT_RE.sub(
        lambda m: (" " + m.group(1) + " ") * int(m.group(2)),
        text,
    )
    return text


def _parse_progression_text(text: str) -> list[tuple[str, float]] | None:
    """Parse chord-progression text into a list of ``(symbol, bars)`` tuples.

    Two syntaxes both accepted; the colon-suffix form lets Stephen express
    pacing (how fast chords change) without typing duplicates:

      - Legacy:   ``"I V vi IV"``               → ``[("I",1.0), ("V",1.0),
                                                     ("vi",1.0), ("IV",1.0)]``
      - Paced:    ``"I:2 V:1 vi:1 IV:4"``       → ``[("I",2), ("V",1),
                                                     ("vi",1), ("IV",4)]``
      - Sub-bar:  ``"i:.5 VII:.5 VI:.5 VII:.5"`` → 4 half-bar chord changes
                                                   inside the first 2 bars.
      - Repeat:   ``"[ii V I] x2"``              → ``ii V I ii V I``
      - Vamp:     ``"i7 x4"``                    → ``i7 i7 i7 i7``

    The repeat / vamp forms are expanded by ``_expand_progression_shorthand``
    before tokenization; everything else is parsed as before.

    Bare tokens default to 1.0 bar. Any positive float duration is accepted;
    the MidiExporter generators consume the tuple list directly and render
    each chord segment in [start_bar, end_bar) with hits past the end
    truncated. Backward compat: ``MidiExporter.add_*`` methods still accept
    a plain ``list[str]`` from style presets and treat each as 1 bar.

    Returns ``None`` for empty input so callers fall back to the style preset.
    """
    if not text or not text.strip():
        return None
    text = _expand_progression_shorthand(text)
    out: list[tuple[str, float]] = []
    for raw in text.replace(",", " ").split():
        tok = raw.strip()
        if not tok:
            continue
        symbol, sep, dur_str = tok.partition(":")
        if not sep:
            out.append((symbol, 1.0))
            continue
        try:
            dur_f = float(dur_str)
        except ValueError:
            logger.warning(
                "progression: ignoring malformed duration in %r — using 1 bar",
                tok,
            )
            out.append((symbol, 1.0))
            continue
        if dur_f <= 0.0:
            logger.warning(
                "progression: %r has non-positive duration — using 1 bar",
                tok,
            )
            out.append((symbol, 1.0))
            continue
        out.append((symbol, dur_f))
    return out or None


def _render_extras(midi: MidiExporter, extras: list[dict], *,
                   key: str, scale: str, bars: int, swing: float,
                   progression: list[str] | None, seed: int | None) -> None:
    """Render the Extra Tracks list onto an existing MidiExporter. Each entry
    is a dict matching one of TRACK_TYPES; missing per-type params fall back
    to sensible defaults.

    Per-extra overrides (added 2026-05-10): ``swing``, ``seed``, and
    ``progression`` keys, when present and non-empty, override the global
    Compose values for THAT extra only. Stephen's previous workflow ran
    every extra against the global swing/seed and the global progression —
    perfectly fine for layered duplicates, but it meant adding a Latin
    percussion extra to a 4/4 rock piece forced the whole song to share
    one swing value. Per-extra overrides unlock proper layering.
    """
    for tr in extras or []:
        ttype = tr.get("type")
        name = tr.get("track_name") or ttype.title()

        # Resolve per-extra overrides — None / "" / not-present means inherit.
        sw_raw = tr.get("swing")
        eff_swing = float(sw_raw) if sw_raw not in (None, "") else swing
        seed_raw = tr.get("seed")
        try:
            eff_seed = int(seed_raw) if seed_raw not in (None, "", 0) else seed
        except (TypeError, ValueError):
            eff_seed = seed
        prog_raw = tr.get("progression")
        if prog_raw:
            eff_prog = _parse_progression_text(prog_raw) or progression
        else:
            eff_prog = progression

        if ttype == "chord":
            midi.add_chord_progression(
                key=key, progression=eff_prog, bars=bars,
                octave=int(tr.get("octave", 3)), scale_name=scale,
                voicing=tr.get("voicing", "triad"),
                program=int(tr.get("program", 0)),
                track_name=name,
                rhythm=tr.get("chord_rhythm", "pulse_quarter"),
                swing=eff_swing,
            )
        elif ttype == "bass":
            midi.add_bass_line(
                key=key, progression=eff_prog, bars=bars,
                pattern=tr.get("pattern", "root_fifth"),
                octave=int(tr.get("octave", 2)), scale_name=scale,
                swing=eff_swing, program=int(tr.get("program", 33)),
                track_name=name, seed=eff_seed,
            )
        elif ttype == "melody":
            midi.add_melody(
                key=key, scale_name=scale, bars=bars,
                octave=int(tr.get("octave", 5)),
                seed=eff_seed, swing=eff_swing,
                program=int(tr.get("program", 0)),
                track_name=name, progression=eff_prog,
                melody_style=tr.get("melody_style", "motif"),
                density=float(tr.get("density", 1.0)),
            )
        elif ttype == "drums":
            midi.add_drum_pattern(
                pattern=tr.get("pattern", "basic_rock"),
                bars=bars, swing=eff_swing,
                density=float(tr.get("density", 1.0)),
                track_name=name, seed=eff_seed,
            )
        elif ttype == "lead":
            midi.add_lead_line(
                key=key, progression=eff_prog, bars=bars,
                octave=int(tr.get("octave", 4)),
                pattern=tr.get("pattern", "clinton_synth"),
                scale_name=scale, swing=eff_swing,
                program=int(tr.get("program", 82)),
                track_name=name, seed=eff_seed,
                density=float(tr.get("density", 1.0)),
                follow_source=tr.get("follow_source") or None,
                follow_mode=tr.get("follow_mode") or "independent",
            )
        elif ttype == "theme":
            theme_name = tr.get("theme") or "hit_the_sack"
            midi.add_theme(
                theme_name=theme_name, key=key, scale_name=scale,
                bars=bars, octave=int(tr.get("octave", 5)),
                program=int(tr.get("program", 0)),
                track_name=name, swing=eff_swing,
            )
        elif ttype == "harmony":
            # Vocal-style harmony layered over the source track
            # (default Melody). The preset name flows through
            # add_harmony.style — the method internally maps it to
            # the right intervals_steps + follow/accents mode. Voices
            # truncates or pads the preset's natural voice count.
            # Each voice writes a separate track (``Melody Harm 1``,
            # ``Melody Harm 2``, …) so the user can mute / edit /
            # re-program each one independently.
            intervals_raw = (tr.get("intervals") or "").strip()
            intervals_override = None
            if intervals_raw:
                try:
                    intervals_override = [
                        int(x.strip()) for x in intervals_raw.split(",")
                        if x.strip()
                    ]
                except ValueError:
                    intervals_override = None
            midi.add_harmony(
                source_track=tr.get("source_track") or "Melody",
                intervals_steps=intervals_override,
                style=tr.get("preset", "queen"),
                voices=int(tr.get("voices", 2)),
                key=key, scale_name=scale,
                progression=eff_prog,
                harmony_rule=tr.get("harmony_rule") or "voice_leading_smooth",
                program=int(tr.get("program", 0)),
            )


# ===================================================================
# Drum grid editor helpers (Step 6)
# ===================================================================

def _grid_to_dataframe(grid: dict[str, list[int]], time_sig: tuple[int, int],
                      bars: int) -> tuple[list[list], list[str]]:
    """Convert ``{drum: [levels]}`` to a 2D rows-list and matching headers."""
    first_row = next(iter(grid.values()), [])
    steps_per_bar = max(1, len(first_row) // max(1, bars))
    step_labels = grid_step_labels(time_sig, bars, steps_per_bar)
    headers = ["Drum", *step_labels]
    rows = [
        [drum, *grid.get(drum, [0] * len(step_labels))]
        for drum in GRID_DRUM_ROWS
    ]
    return rows, headers


def _dataframe_to_grid(rows) -> dict[str, list[int]]:
    """Inverse of _grid_to_dataframe. Coerces strings to ints, clamps to 0..3."""
    import pandas as pd  # gradio surfaces dataframes as pandas; tolerate list too
    if isinstance(rows, pd.DataFrame):
        rows = rows.values.tolist()
    elif rows is None:
        return {}
    grid: dict[str, list[int]] = {}
    for row in rows:
        if not row:
            continue
        drum_name = str(row[0])
        levels = []
        for cell in row[1:]:
            try:
                lvl = int(float(cell))
            except (TypeError, ValueError):
                lvl = 0
            levels.append(max(0, min(3, lvl)))
        grid[drum_name] = levels
    return grid


def load_drum_grid(pattern_name: str, time_sig: str, bars: int):
    """Build a fresh grid for the currently-selected drum pattern and
    meter. Returns ``(dataframe_value, drum_grid_state)`` where
    ``dataframe_value`` is a ``{headers, data}`` dict so the Dataframe
    component re-renders both columns and contents in a single update —
    sending headers as a separate ``gr.update`` retriggers Gradio's
    construct-time header/column-count validation and fails when bars or
    meter shrinks the grid.
    """
    ts = _parse_time_sig(time_sig)
    grid = drum_pattern_to_grid(pattern_name, ts, bars=max(1, int(bars)))
    rows, headers = _grid_to_dataframe(grid, ts, max(1, int(bars)))
    return {"headers": headers, "data": rows}, grid


# ===================================================================
# Key-safety audit helpers (Step 5)
# ===================================================================

AUDIT_COLUMNS = ["#", "Track", "Bar", "Beat", "Note", "Status",
                 "Chord", "Suggestions"]


def _audit_to_rows(issues) -> list[list]:
    """Convert NoteIssue list to a Dataframe-friendly 2D list."""
    return [
        [i + 1, iss.track_name, iss.bar_idx + 1, round(iss.beat, 2),
         iss.pitch_name, iss.status, iss.chord_symbol,
         ", ".join(iss.alt_names())]
        for i, iss in enumerate(issues)
    ]


def _suggestion_update_for_row(issues, row_idx):
    """Build a gr.Dropdown update with the alternatives for ``row_idx`` (1-based).
    Returns an update with empty choices when the row is out of range."""
    try:
        idx0 = int(row_idx) - 1
    except (TypeError, ValueError):
        return gr.update(choices=[], value=None)
    if not issues or idx0 < 0 or idx0 >= len(issues):
        return gr.update(choices=[], value=None)
    names = issues[idx0].alt_names()
    return gr.update(choices=names, value=(names[0] if names else None))


def play_flagged_bar(row_idx):
    """Render the bar containing the flagged note (plus one bar of context
    on each side) and return a wav path for Gradio to play. ``row_idx`` is
    1-based to match the column shown in the UI."""
    midi = _state.get("last_midi")
    issues = _state.get("audit_issues") or []
    if midi is None:
        raise gr.Error("Click **Compose** first — there's nothing to audit yet.")
    if not issues:
        raise gr.Error("No flagged notes — every note is already in key. 🎵")
    try:
        idx0 = int(row_idx) - 1
    except (TypeError, ValueError):
        raise gr.Error("Pick an issue row first (set its # in the input).")
    if idx0 < 0 or idx0 >= len(issues):
        raise gr.Error(
            f"No issue at row {row_idx} — pick a number between 1 and {len(issues)}."
        )
    iss = issues[idx0]
    try:
        from src.daw_integration.generic.midi_export import MidiExporter
        info = midi._meter
        beat_dur = 60.0 / midi.tempo
        pulse_unit = beat_dur * info["pulse_unit_in_quarters"]
        bar_dur = info["beats_per_bar"] * pulse_unit
        first = max(0, iss.bar_idx - 1)
        last = iss.bar_idx + 2
        window_start = first * bar_dur
        window_end = last * bar_dur
        # Build a thin MidiExporter copy with only notes in the window.
        window = MidiExporter(tempo=midi.tempo, time_signature=midi.time_signature)
        for t in midi.tracks:
            kept = [
                # rebase to window start so the preview begins at t=0
                type(n)(pitch=n.pitch,
                        start=n.start - window_start,
                        end=min(n.end, window_end) - window_start,
                        velocity=n.velocity)
                for n in t.notes
                if window_start <= n.start < window_end and n.end > window_start
            ]
            if not kept:
                continue
            window._track_for(t.name, program=t.program,
                              is_drum=t.is_drum, channel=t.channel)
            window.tracks[-1].notes.extend(kept)
        audio, sr = window.synthesize(sample_rate=44100)
        wav_path = OUTPUT_DIR / f"audit_bar_{iss.bar_idx + 1}.wav"
        sf.write(str(wav_path), audio, sr)
        del audio
        return str(wav_path)
    except Exception as e:
        raise _logged_error("Play flagged bar", e) from e


def apply_audit_suggestion(row_idx, suggestion_text):
    """Rewrite the flagged note to the chosen suggestion (a note name like
    'D4'), re-save the .mid and re-render the preview. Returns updated
    (wav_path, mid_path, info, audit_rows, suggestion_update).

    If ``suggestion_text`` is empty (the user clicked Apply before the
    dropdown auto-populated), we fall back to the first suggestion for
    the selected row — the most-common UX path produces the same outcome
    either way and the error message confused testers more than it helped.
    """
    midi = _state.get("last_midi")
    issues = _state.get("audit_issues") or []
    ctx = _state.get("audit_context") or {}
    if midi is None:
        raise gr.Error("Click **Compose** first — there's nothing to audit yet.")
    if not issues:
        raise gr.Error("No flagged notes — every note is already in key. 🎵")
    try:
        idx0 = int(row_idx) - 1
    except (TypeError, ValueError):
        raise gr.Error("Pick an issue row first.")
    if idx0 < 0 or idx0 >= len(issues):
        raise gr.Error(
            f"No issue at row {row_idx} — pick a number between 1 and {len(issues)}."
        )
    iss = issues[idx0]
    target_name = (suggestion_text or "").strip()
    if not target_name:
        # Fall back to the first suggestion so the user doesn't have to
        # remember to nudge the dropdown before clicking Apply.
        if iss.suggested_alternatives:
            target_name = iss.alt_names()[0]
        else:
            raise gr.Error("No suggestions available for this row.")
    # Map "D4" → MIDI pitch
    try:
        # Note name letters until digit, then octave
        i = 0
        while i < len(target_name) and not target_name[i].isdigit() and target_name[i] != "-":
            i += 1
        note = target_name[:i]
        octv = int(target_name[i:])
        from src.daw_integration.generic.midi_export import note_name_to_midi
        new_pitch = note_name_to_midi(note, octv)
    except Exception:
        raise gr.Error(f"Couldn't parse suggestion {target_name!r}.")
    try:
        ok = audit.apply_suggestion(midi, iss, new_pitch)
        if not ok:
            raise gr.Error("Couldn't find the flagged note in the track "
                           "(it may have shifted — try re-Composing).")
        # Re-save mid + preview wav and re-audit.
        mid_path = OUTPUT_DIR / "last_composition.mid"
        midi.save(mid_path)
        audio, sr = midi.synthesize(sample_rate=44100)
        wav_path = OUTPUT_DIR / "last_composition.wav"
        sf.write(str(wav_path), audio, sr)
        _state["midi_path"] = mid_path
        _state["midi_wav_path"] = wav_path
        del audio
        new_issues = audit.audit_midi(
            midi, ctx.get("progression"), ctx.get("scale", "major"),
            ctx.get("key", "C"),
        )
        _state["audit_issues"] = new_issues
        dur = midi.total_duration()
        info = (
            f"Patched {iss.pitch_name} → {target_name} on '{iss.track_name}' "
            f"bar {iss.bar_idx + 1}. {dur:.1f}s | "
            f"Audit now: {sum(1 for i in new_issues if i.status == 'out_of_key')} "
            f"out-of-key, "
            f"{sum(1 for i in new_issues if i.status == 'approach_tone')} approach"
        )
        # Reset the suggestion dropdown so the next issue's options are
        # ready to click without an extra interaction.
        next_sugg = _suggestion_update_for_row(new_issues, 1)
        return (str(wav_path), str(mid_path), info,
                _audit_to_rows(new_issues), next_sugg)
    except gr.Error:
        raise
    except Exception as e:
        raise _logged_error("Apply audit suggestion", e) from e


def get_suggestions_for_row(row_idx):
    """Return the suggestion alternatives for the row as a Gradio dropdown
    update with new choices. Used to populate the suggestion picker."""
    return _suggestion_update_for_row(_state.get("audit_issues") or [], row_idx)


# ---------------------------------------------------------------------------
# Per-instrument progression override helpers
# ---------------------------------------------------------------------------
# Each instrument carries a small ``{"text": str, "locked": bool}`` dict
# in its own gr.State. When ``locked`` is True (the default), the
# instrument follows the master textbox 1:1 — editing the master also
# updates this instrument's stored text. When the user toggles the
# lock open and types something different, this instrument is sealed
# from subsequent master changes until they lock it again.
#
# Same shape is used per-extra (the extras_state dicts gain
# ``progression`` + ``progression_locked`` keys, surfaced via the
# per-instrument panel).


def _default_instrument_progression_dict(master_text: str = "") -> dict:
    """Default state for a fresh instrument: locked to the master."""
    return {"text": master_text, "locked": True}


def _resolve_instrument_progression(
    override: dict | None, master_text: str,
):
    """Return the :data:`ProgressionPlan` this instrument should
    actually play.

    Locked OR missing override → master. Unlocked + filled → that text
    parsed as a progression. Unlocked + empty → master (graceful
    fallback so a user who unlocks-then-clears doesn't end up with
    a silent generator).
    """
    master_plan = _parse_progression_text(master_text)
    if not override or override.get("locked", True):
        return master_plan
    text = (override.get("text") or "").strip()
    if not text:
        return master_plan
    return _parse_progression_text(text) or master_plan


def _collect_instruments(*lists) -> list[str]:
    """Flatten 6 per-family CheckboxGroup selections into one ordered
    de-duplicated list of instrument ids, suitable for
    ``compose_midi(enabled_instruments=…)`` and
    ``compose_song(enabled_instruments=…)``.
    """
    out: list[str] = []
    for lst in lists:
        for item in (lst or []):
            if item not in out:
                out.append(item)
    return out


def compose_midi(
    style: str, key: str, scale: str, tempo: float, time_sig: str, bars: int,
    enable_chords: bool, enable_bass: bool, enable_melody: bool, enable_drums: bool,
    bass_pattern: str, drum_pattern: str, voicing: str, swing: float,
    chord_rhythm: str, melody_style: str,
    seed: int | None,
    progression_text: str = "",
    extras: list[dict] | None = None,
    chord_octave: int = 3,
    bass_octave: int = 2,
    melody_octave: int = 5,
    drum_grid_state: dict | None = None,
    random_variation: bool = False,
    chords_progression_override: dict | None = None,
    bass_progression_override: dict | None = None,
    melody_progression_override: dict | None = None,
    enable_harmony: bool = False,
    harmony_voices: int = 2,
    harmony_preset: str = "queen",
    harmony_rule: str = "voice_leading_smooth",
    rhythm_overrides: list[dict] | None = None,
    enabled_instruments: list[str] | None = None,
):
    # When the UI passes a non-empty ``enabled_instruments`` list, each
    # entry resolves to a concrete Instrument (program + track_name) and
    # we loop one add_* call per instrument. Empty / None falls back to
    # the legacy 4-boolean code path so MCP clients and tests that still
    # pass ``enable_chords=True`` etc. keep working.
    from src.composition.instruments import (
        INSTRUMENT_REGISTRY, expand_selection,
    )
    resolved_instruments = expand_selection(enabled_instruments or [])
    inst_by_role: dict[str, list] = {
        "chords": [], "bass": [], "melody": [], "drums": [],
    }
    for inst in resolved_instruments:
        inst_by_role.setdefault(inst.role, []).append(inst)
    use_instruments = bool(resolved_instruments)

    if not use_instruments and not any([
        enable_chords, enable_bass, enable_melody, enable_drums, enable_harmony,
    ]) and not (extras or []):
        raise gr.Error("Enable at least one track.")
    if use_instruments and not any([
        inst_by_role["chords"], inst_by_role["bass"],
        inst_by_role["melody"], inst_by_role["drums"],
        enable_harmony,
    ]) and not (extras or []):
        raise gr.Error("Pick at least one instrument.")

    try:
        logger.info(
            "compose_midi: style=%s key=%s scale=%s tempo=%s ts=%s bars=%s "
            "tracks=[c=%s b=%s m=%s d=%s] bass=%s drum=%s voicing=%s rhythm=%s "
            "extras=%d prog=%r",
            style, key, scale, tempo, time_sig, bars,
            enable_chords, enable_bass, enable_melody, enable_drums,
            bass_pattern, drum_pattern, voicing, chord_rhythm,
            len(extras or []), progression_text,
        )
        seed = seed if seed and seed > 0 else None

        ts = _parse_time_sig(time_sig)
        midi = MidiExporter(tempo=tempo, time_signature=ts)
        preset = STYLES.get(style)
        # Progression resolution order:
        #   1. random_variation=True + preset → pick a random variant from
        #      preset.progression_variants and IGNORE the textbox
        #   2. non-empty textbox → use it (lets user override the picker)
        #   3. fall back to preset default progression
        if random_variation and preset and preset.progression_variants:
            import random
            _vname, _vplan = random.choice(preset.progression_variants)
            progression = _vplan
            logger.info("compose_midi: random variation picked: %r", _vname)
        else:
            progression = (_parse_progression_text(progression_text)
                           or (preset.progression if preset else None))

        # Per-instrument overrides: each override is a tiny
        # {"text": str, "locked": bool} dict carried in a gr.State.
        # Locked or empty → inherit master. Unlocked + non-empty →
        # parse the instrument's text as a full progression and use
        # that. Falls back to the master if the text fails to parse,
        # so an in-progress edit never silently produces no chords.
        chords_progression = _resolve_instrument_progression(
            chords_progression_override, progression_text,
        ) or progression
        bass_progression = _resolve_instrument_progression(
            bass_progression_override, progression_text,
        ) or progression
        melody_progression = _resolve_instrument_progression(
            melody_progression_override, progression_text,
        ) or progression

        # Per-style idiom variants — flat dicts of {kwarg: value} that
        # each generator picks up. Loaded from the active StylePreset
        # if any. Empty dicts when the style declared no variants
        # (preserving today's behavior).
        chord_variant = (preset.chord_variant or {}) if preset else {}
        bass_variant = (preset.bass_variant or {}) if preset else {}
        melody_variant = (preset.melody_variant or {}) if preset else {}

        # Generation order: melody → chords → bass → drums. Putting the
        # melody first lets the chord generator read it (via
        # avoid_melody_track) for collision avoidance when a per-style
        # variant enables it.
        #
        # When ``enabled_instruments`` populated the registry-resolved
        # ``inst_by_role`` map, each role iterates its specific
        # Instrument list so that e.g. picking trumpet + tenor sax
        # produces two distinct MIDI tracks at the right GM patches.
        # Otherwise the legacy single-shot branch fires once per
        # enabled bool — keeps MCP / tests untouched.
        if use_instruments:
            for inst in inst_by_role["melody"]:
                midi.add_melody(
                    key=key, scale_name=scale, bars=bars,
                    octave=int(melody_octave),
                    seed=seed, swing=swing,
                    progression=melody_progression,
                    melody_style=melody_style,
                    program=inst.program, track_name=inst.track_name,
                    **melody_variant,
                )
            for inst in inst_by_role["chords"]:
                midi.add_chord_progression(
                    key=key, progression=chords_progression, bars=bars,
                    octave=int(chord_octave),
                    scale_name=scale, voicing=voicing,
                    rhythm=chord_rhythm, swing=swing,
                    rhythm_overrides=rhythm_overrides,
                    program=inst.program, track_name=inst.track_name,
                    **chord_variant,
                )
            for inst in inst_by_role["bass"]:
                midi.add_bass_line(
                    key=key, progression=bass_progression, bars=bars,
                    pattern=bass_pattern,
                    octave=int(bass_octave),
                    scale_name=scale, swing=swing, seed=seed,
                    pattern_overrides=rhythm_overrides,
                    program=inst.program, track_name=inst.track_name,
                    **bass_variant,
                )
            for inst in inst_by_role["drums"]:
                # Drum grid is the source of truth when populated; one
                # named pattern is reused across multiple drum-role
                # instruments (e.g. drum_kit + percussion) but each
                # lands on its own track_name.
                if drum_grid_state and any(
                    any(v for v in row) for row in drum_grid_state.values()
                ):
                    try:
                        midi.add_drum_grid(
                            drum_grid_state, bars=bars,
                            swing=swing, track_name=inst.track_name,
                        )
                    except Exception:
                        logger.exception(
                            "drum grid render failed — falling back to "
                            "preset %r",
                            drum_pattern,
                        )
                        midi.add_drum_pattern(drum_pattern, bars=bars,
                                              swing=swing, seed=seed,
                                              track_name=inst.track_name)
                else:
                    midi.add_drum_pattern(drum_pattern, bars=bars,
                                          swing=swing, seed=seed,
                                          track_name=inst.track_name)
        else:
            if enable_melody:
                midi.add_melody(
                    key=key, scale_name=scale, bars=bars,
                    octave=int(melody_octave),
                    seed=seed, swing=swing,
                    progression=melody_progression, melody_style=melody_style,
                    **melody_variant,
                )
            if enable_chords:
                midi.add_chord_progression(
                    key=key, progression=chords_progression, bars=bars,
                    octave=int(chord_octave),
                    scale_name=scale, voicing=voicing,
                    rhythm=chord_rhythm, swing=swing,
                    rhythm_overrides=rhythm_overrides,
                    **chord_variant,
                )
            if enable_bass:
                midi.add_bass_line(
                    key=key, progression=bass_progression, bars=bars,
                    pattern=bass_pattern,
                    octave=int(bass_octave),
                    scale_name=scale, swing=swing, seed=seed,
                    pattern_overrides=rhythm_overrides,
                    **bass_variant,
                )
            if enable_drums:
                if drum_grid_state and any(
                    any(v for v in row) for row in drum_grid_state.values()
                ):
                    try:
                        midi.add_drum_grid(
                            drum_grid_state, bars=bars,
                            swing=swing, track_name="Drums",
                        )
                    except Exception:
                        logger.exception(
                            "drum grid render failed — falling back to "
                            "preset %r",
                            drum_pattern,
                        )
                        midi.add_drum_pattern(drum_pattern, bars=bars,
                                              swing=swing, seed=seed)
                else:
                    midi.add_drum_pattern(drum_pattern, bars=bars,
                                          swing=swing, seed=seed)

        # Permanent harmony track (first-class alongside chords/bass/
        # melody/drums). Layered on top of the melody using the same
        # add_harmony engine the Studio's HarmonyTag system uses; each
        # voice writes a separate MIDI track ("Melody Harm 1", " Harm 2",
        # …) so they're independently editable in any DAW. Runs AFTER
        # the melody (which the dispatch order above guarantees) so
        # add_harmony can read the melody's notes.
        if enable_harmony:
            # Source the harmony from the first melody track that exists
            # — per-instrument routing means it may be "Trumpet" or
            # "Tenor Sax" rather than the legacy "Melody". Skip when no
            # melody source is present.
            harmony_source: str | None = None
            if use_instruments and inst_by_role["melody"]:
                harmony_source = inst_by_role["melody"][0].track_name
            elif not use_instruments and enable_melody:
                harmony_source = "Melody"
            if harmony_source:
                try:
                    midi.add_harmony(
                        source_track=harmony_source,
                        style=harmony_preset or "queen",
                        voices=int(harmony_voices) if harmony_voices else 2,
                        key=key, scale_name=scale,
                        progression=progression,
                        harmony_rule=harmony_rule or "voice_leading_smooth",
                    )
                except Exception:
                    logger.exception("harmony track render failed")

        # Extra freeform tracks
        _render_extras(midi, extras or [],
                       key=key, scale=scale, bars=bars, swing=swing,
                       progression=progression, seed=seed)

        # Save MIDI file
        mid_path = OUTPUT_DIR / "last_composition.mid"
        midi.save(mid_path)
        _state["midi_path"] = mid_path

        # Render to audio for preview
        audio, sr = midi.synthesize(sample_rate=44100)
        wav_path = OUTPUT_DIR / "last_composition.wav"
        sf.write(str(wav_path), audio, sr)
        _state["midi_wav_path"] = wav_path
        del audio

        # Stash metadata so the "Save as Block" button can use it.
        _state["last_compose_meta"] = {
            "tempo": float(tempo),
            "time_signature": (int(ts[0]), int(ts[1])),
            "bars": int(bars),
        }
        # PDF export needs key/scale/tempo/title to inject the key sig
        # and title the engraved score, plus the progression to print
        # chord-symbol markers above the top staff.
        _state["compose_meta"] = {
            "key": str(key),
            "scale": str(scale),
            "tempo": float(tempo),
            "title": f"{style.title()} in {key} {scale}",
            "progression": list(progression),
            "bars": int(bars),
            "swing": float(swing),
        }

        # Pin the live MidiExporter + audit issues so the Key-safety panel can
        # play individual bars and rewrite suggested notes without re-running
        # the entire compose. Cleared on _shutdown via _state.clear().
        _state["last_midi"] = midi
        _state["audit_context"] = {
            "key": key, "scale": scale, "progression": progression,
            "swing": float(swing),
        }
        issues = audit.audit_midi(midi, progression, scale, key)
        _state["audit_issues"] = issues
        audit_rows = _audit_to_rows(issues)

        dur = midi.total_duration()
        track_list = ", ".join(t.name for t in midi.tracks)
        info = (
            f"{dur:.1f}s | {tempo:.0f} BPM | {key} {scale} | "
            f"Tracks: {track_list} | "
            f"Audit: {sum(1 for i in issues if i.status == 'out_of_key')} "
            f"out-of-key, {sum(1 for i in issues if i.status == 'approach_tone')} "
            f"approach"
        )

        # Seed the suggestion dropdown with row 1's alternatives so clicking
        # Apply with the default row works without a manual interaction.
        suggestion_seed = _suggestion_update_for_row(issues, 1)

        return str(wav_path), str(mid_path), info, audit_rows, suggestion_seed
    except gr.Error:
        raise
    except Exception as e:
        raise _logged_error("Compose MIDI", e) from e


def render_high_quality(
    master_preset: str,
    with_stems: bool,
    soundfont_path: str,
    *,
    midi_path_override: Path | None = None,
    output_subdir: str = "render",
    progress=gr.Progress(track_tqdm=True),
):
    """Re-render the most recent MIDI through the high-quality audio pipeline.

    Pulls the last `.mid` from ``_state["midi_path"]`` (or
    ``midi_path_override``) and runs it through
    ``src.audio_processing.render.render_to_audio``. Returns
    ``(mix_wav_path, stems_zip_path, info_text)``.
    """
    midi_path = midi_path_override or _state.get("midi_path")
    if not midi_path or not Path(midi_path).exists():
        raise gr.Error(
            "No MIDI yet — Compose something first, then click Render."
        )

    sf_path = (soundfont_path or "").strip() or None
    if sf_path == "auto":
        sf_path = None

    try:
        progress(0.05, desc="Resolving soundfont…")
        out_dir = OUTPUT_DIR / output_subdir
        # Wipe stale stems so this render is self-contained.
        if out_dir.exists():
            shutil.rmtree(out_dir, ignore_errors=True)
        out_dir.mkdir(parents=True, exist_ok=True)

        progress(0.20, desc="Synthesizing per-track stems…")
        result = render_to_audio(
            midi_path,
            output_dir=out_dir,
            soundfont=sf_path,
            with_stems=with_stems,
            master_preset=master_preset,
        )
        progress(0.90, desc="Packaging output…")

        stems_zip: str | None = None
        if with_stems and result.stem_paths:
            zip_base = out_dir / "stems"
            stems_zip = shutil.make_archive(
                str(out_dir / "stems_bundle"), "zip", str(zip_base),
            )

        info = (
            f"{result.duration_seconds:.1f}s | master={master_preset} | "
            f"{len(result.stem_paths)} stems | "
            f"sf={Path(result.soundfont).name}"
        )
        _state["render_result"] = {
            "mix_path": result.mix_path,
            "stem_paths": result.stem_paths,
            "manifest_path": result.manifest_path,
            "soundfont": result.soundfont,
            "master_preset": master_preset,
        }
        progress(1.0)
        return str(result.mix_path), stems_zip, info
    except gr.Error:
        raise
    except FileNotFoundError as e:
        raise gr.Error(str(e))
    except Exception as e:
        raise _logged_error("Render to high-quality audio", e) from e


def download_soundfont():
    """Download MuseScore General SF3 into data/soundfonts/."""
    try:
        path = download_default_soundfont()
        return f"✓ Downloaded {path.name} ({path.stat().st_size / 1e6:.1f} MB) to {path.parent}"
    except Exception as e:
        raise _logged_error("Download soundfont", e) from e


def _generate_full_song(
    style_name: str,
    seed_in,
    rhythm_sel: list[str],
    bass_sel: list[str],
    chord_lead_sel: list[str],
    brass_sel: list[str],
    woodwind_sel: list[str],
    strings_sel: list[str],
) -> tuple:
    """Wire the 🎲 Generate full song button to the TechniqueBank.

    Returns updates for: audio preview / MIDI file / info textbox /
    summary markdown / rhythm_overrides_state / seed input (so a 0
    seed auto-bumps for next click).

    The six family CheckboxGroups flatten into one instrument-id list
    that ``compose_song`` walks one technique per cell — empty list
    means the user unchecked everything and we raise.
    """
    from src.composition.song_composer import compose_song
    seed = int(seed_in) if seed_in else 0
    if seed <= 0:
        import random as _r
        seed = _r.randint(1, 1_000_000)
    enabled = tuple(_collect_instruments(
        rhythm_sel, bass_sel, chord_lead_sel,
        brass_sel, woodwind_sel, strings_sel,
    ))
    if not enabled:
        raise gr.Error("Pick at least one instrument.")
    try:
        out = compose_song(
            genre=style_name, seed=seed,
            enabled_instruments=enabled,
        )
    except gr.Error:
        raise
    except Exception as e:
        raise _logged_error("Generate full song", e) from e

    _state["midi_path"] = Path(out["midi_path"])
    _state["midi_wav_path"] = (
        Path(out["wav_path"]) if out.get("wav_path") else None
    )
    info_line = f"Random song — {out['summary'].splitlines()[0]}"
    return (
        out["wav_path"] or None,
        out["midi_path"],
        info_line,
        "```\n" + out["summary"] + "\n```",
        out["rhythm_overrides"],
        seed,
    )


def _export_pdf_zip(
    midi_path: Path,
    out_zip: Path,
    *,
    key: str,
    scale: str,
    tempo: float,
    title: str,
    progression: list | None = None,
    bars: int | None = None,
    swing: float = 0.0,
) -> str:
    """All three Export-PDF buttons funnel through here so the
    LilyPond-missing error is uniform across MIDI Compose / Library /
    Compose Song."""
    if not is_lilypond_available():
        raise gr.Error(
            "LilyPond isn't installed. Run `brew install lilypond` on "
            "your Mac (one-time setup, ~50 MB) then click Export PDF again."
        )
    try:
        path = _pdf_export_zip(
            midi_path, out_zip,
            key=key, scale=scale, tempo=tempo, title=title,
            progression=progression, bars=bars, swing=swing,
        )
        return str(path)
    except gr.Error:
        raise
    except Exception as e:
        raise _logged_error("Export PDF", e) from e


def _pdf_preview_html(pdf_path: Path) -> str:
    """Embed a PDF inside the Gradio UI via an ``<iframe>`` with a
    base64 data-URI source.

    Going through Gradio's ``/gradio_api/file=`` route runs into the
    allowlist — only files Gradio handed out as component outputs in
    this session are servable. Embedding the bytes inline sidesteps
    that and also means the iPhone WKWebView gets the latest
    composition without a separate fetch.
    """
    import base64
    data = Path(pdf_path).read_bytes()
    b64 = base64.b64encode(data).decode()
    return (
        f'<iframe src="data:application/pdf;base64,{b64}#toolbar=0" '
        'style="width: 100%; height: 75vh; border: 1px solid #ccc;" '
        'title="Score preview"></iframe>'
    )


def _export_compose_pdf():
    """Wired to the Export PDF button on the MIDI Compose tab.

    Returns ``(zip_path, preview_html)``. The ZIP holds the full score
    plus per-instrument PDFs; the HTML iframe embeds the full score
    directly in the tab so the user doesn't have to download + open
    in a separate app.
    """
    mid_path = _state.get("midi_path")
    meta = _state.get("compose_meta") or {}
    if not mid_path or not Path(mid_path).exists():
        raise gr.Error("Compose something first, then click Export PDF.")
    out = OUTPUT_DIR / "compose_score.zip"
    zip_path = _export_pdf_zip(
        Path(mid_path), out,
        key=str(meta.get("key", "C")),
        scale=str(meta.get("scale", "major")),
        tempo=float(meta.get("tempo", 120.0)),
        title=str(meta.get("title", "Composition")),
        progression=meta.get("progression"),
        bars=meta.get("bars"),
        swing=float(meta.get("swing", 0.0) or 0.0),
    )
    # Pull the full_score.pdf out of the ZIP into a stable location
    # so we can iframe it.
    import zipfile as _zf
    preview_pdf = OUTPUT_DIR / "compose_score_preview.pdf"
    with _zf.ZipFile(zip_path) as zf:
        with zf.open("full_score.pdf") as src, open(preview_pdf, "wb") as dst:
            shutil.copyfileobj(src, dst)
    return zip_path, _pdf_preview_html(preview_pdf)


def _export_block_pdf(block_name: str) -> str:
    """Wired to every block-library card's PDF button. Reads the
    block's saved .mid + YAML metadata."""
    try:
        pm, meta = block_store.load_block(block_name)
    except Exception as e:
        raise _logged_error("Load block for PDF export", e) from e
    out = block_store.BLOCKS_DIR / f"{block_name}.zip"
    mid_path = block_store.BLOCKS_DIR / f"{block_name}.mid"
    if not mid_path.exists():
        with tempfile.NamedTemporaryFile(
            suffix=".mid", delete=False,
        ) as tf:
            mid_path = Path(tf.name)
        pm.write(str(mid_path))
    return _export_pdf_zip(
        Path(mid_path), out,
        key=str(meta.get("key", "C")),
        scale=str(meta.get("scale", "major")),
        tempo=float(meta.get("tempo", 120.0)),
        title=block_name,
    )


def _export_song_pdf(state: dict) -> str:
    """Wired to the Compose Song HQ render's Export PDF button.
    Re-runs concat_blocks on the live timeline (the same path the HQ
    render uses) so the score is always in sync with what was just
    rendered."""
    timeline = (state or {}).get("timeline") or []
    if not timeline:
        raise gr.Error("Add at least one block to the timeline first.")
    try:
        pm, _info = block_concat.concat_blocks(timeline)
    except Exception as e:
        raise _logged_error("Concat blocks for PDF export", e) from e
    title = str((state or {}).get("title") or "Song")
    mid_path = OUTPUT_DIR / "last_song.mid"
    pm.write(str(mid_path))
    # Best-effort: pull tempo/key from the first block on the timeline.
    first_name = timeline[0].get("block_name")
    key, scale, tempo = "C", "major", 120.0
    try:
        lib = {b["name"]: b for b in block_store.list_blocks()}
        first = lib.get(first_name, {})
        key = str(first.get("key", key))
        scale = str(first.get("scale", scale))
        tempo = float(first.get("tempo", tempo))
    except Exception:
        pass
    out = OUTPUT_DIR / "song_score.zip"
    return _export_pdf_zip(
        Path(mid_path), out,
        key=key, scale=scale, tempo=tempo, title=title,
    )


def _read_midi_b64(path: Path) -> str:
    """Read a MIDI file → base64 string for transport to the AlphaTab
    JS bridge."""
    import base64
    return base64.b64encode(Path(path).read_bytes()).decode()


def _midi_to_musicxml_b64(midi_path: Path) -> str:
    """Convert a MIDI file to base64-encoded MusicXML for AlphaTab.

    AlphaTab doesn't ship a MIDI importer — only Guitar Pro / MusicXML /
    Capella / AlphaTex. We route MIDI through music21 → MusicXML so the
    score still uses the latest compose's drum normalization + key sig
    injection (same pipeline ``pdf_export.midi_to_score`` uses).
    """
    import base64
    from src.scoring.pdf_export import midi_to_score
    meta = _state.get("compose_meta") or {}
    score = midi_to_score(
        midi_path,
        key=str(meta.get("key", "C")),
        scale=str(meta.get("scale", "major")),
        title=str(meta.get("title", "Composition")),
        swing=float(meta.get("swing", 0.0) or 0.0),
    )
    out_path = score.write("musicxml")
    return base64.b64encode(Path(str(out_path)).read_bytes()).decode()


def _list_playback_sources() -> list:
    """Build the Playback-tab source dropdown choices.

    Returns ``[(label, value), ...]`` pairs. ``value`` is a short ID
    the handlers parse: ``"compose"`` / ``"block:<name>"`` / ``"song"``.
    """
    out: list = []
    if _state.get("midi_path") and Path(_state["midi_path"]).exists():
        out.append(("Latest compose", "compose"))
    try:
        for blk in block_store.list_blocks():
            name = blk.get("name", "?")
            out.append((f"Block: {name}", f"block:{name}"))
    except Exception:
        logger.exception("Playback: list_blocks failed")
    song_path = OUTPUT_DIR / "last_song.mid"
    if song_path.exists():
        out.append(("Latest song render", "song"))
    return out


def _resolve_playback_source(source_id: str) -> Optional[Path]:
    """source_id → MIDI path. None if the source can't be resolved."""
    if not source_id:
        return None
    if source_id == "compose":
        p = _state.get("midi_path")
        return Path(p) if p and Path(p).exists() else None
    if source_id == "song":
        p = OUTPUT_DIR / "last_song.mid"
        return p if p.exists() else None
    if source_id.startswith("block:"):
        name = source_id.split(":", 1)[1]
        p = block_store.BLOCKS_DIR / f"{name}.mid"
        return p if p.exists() else None
    return None


def _resolve_playback_wav(source_id: str) -> Optional[Path]:
    """source_id → pre-rendered WAV path used as the AlphaTab external
    media source. Each MIDI source already has a paired WAV that the
    compose / block-save / song-render pipelines produce; this lets
    AlphaTab play real audio instead of synthesising in the browser
    (which is choppy on iOS and uses the wrong patch for drums)."""
    if not source_id:
        return None
    if source_id == "compose":
        p = _state.get("midi_wav_path")
        return Path(p) if p and Path(p).exists() else None
    if source_id == "song":
        p = OUTPUT_DIR / "last_song.wav"
        return p if p.exists() else None
    if source_id.startswith("block:"):
        name = source_id.split(":", 1)[1]
        p = block_store.BLOCKS_DIR / f"{name}.wav"
        return p if p.exists() else None
    return None


def _gradio_file_url(path: Path) -> str:
    """Build the URL Gradio serves a whitelisted file at."""
    return f"/gradio_api/file={Path(path).resolve()}"


def _load_midi_for_playback(source_id: str) -> str:
    """Resolve the source → return base64 MusicXML for the AlphaTab
    bridge. AlphaTab doesn't have a MIDI importer, so we convert via
    music21 first."""
    path = _resolve_playback_source(source_id)
    if not path:
        return ""
    try:
        return _midi_to_musicxml_b64(path)
    except Exception as e:
        raise _logged_error("Load score for playback", e) from e


def _load_audio_for_playback(source_id: str) -> str:
    """Resolve the source → return a Gradio-served URL for its
    pre-rendered WAV. Empty string when no WAV exists yet."""
    path = _resolve_playback_wav(source_id)
    return _gradio_file_url(path) if path else ""


def _render_hq_for_playback(source_id: str) -> str:
    """Kick off the FluidSynth HQ render for the current source and
    return a URL that the JS bridge can plug into the <audio> tag."""
    path = _resolve_playback_source(source_id)
    if not path:
        raise gr.Error("Pick a source first.")
    # render_high_quality reads from _state["midi_path"] by default;
    # swap it so the HQ render uses the playback source.
    prior = _state.get("midi_path")
    _state["midi_path"] = path
    try:
        wav_path, _stems, _info = render_high_quality(
            "default", False, "auto", output_subdir="playback_hq",
        )
    finally:
        _state["midi_path"] = prior
    # Gradio serves files under /gradio_api/file=<absolute_path>; that's
    # the URL the JS bridge points the <audio> tag at.
    return f"/gradio_api/file={Path(wav_path).resolve()}"


def _on_playback_note_event(note_json: str) -> str:
    """Format a note-click payload from the JS bridge as user-friendly
    markdown for the side panel."""
    import json
    if not note_json:
        return "Click a note in the score."
    try:
        d = json.loads(note_json)
    except Exception:
        return "Click a note in the score."
    pitch = str(d.get("pitch", ""))
    # `realValueAsString` from AlphaTab is like "G4"; if not present
    # synthesize from MIDI number.
    if not pitch and d.get("midi"):
        midi = int(d["midi"])
        names = ["C", "C#", "D", "D#", "E", "F",
                 "F#", "G", "G#", "A", "A#", "B"]
        pitch = f"{names[midi % 12]}{(midi // 12) - 1}"
    dur_q = float(d.get("durQuarters", 0))
    dur_label = {
        4.0: "whole", 2.0: "half", 1.5: "dotted quarter",
        1.0: "quarter", 0.75: "dotted 8th",
        0.5: "8th", 0.25: "16th", 0.125: "32nd",
    }.get(dur_q, f"{dur_q:.2f}-quarter" if dur_q else "?")
    bar = int(d.get("barIdx", 0)) + 1
    beat = float(d.get("beatIdx", 0)) + 1.0
    track = str(d.get("trackName") or "").strip()
    line = f"**{pitch or '?'}** · {dur_label} note · bar {bar} · beat {beat:g}"
    if track:
        line += f" · _{track}_"
    return line


def save_current_as_block(name: str):
    """Save the most-recent compose_midi result as a named block."""
    if not name or not name.strip():
        raise gr.Error("Enter a block name first.")
    mid_path = _state.get("midi_path")
    meta = _state.get("last_compose_meta")
    if not mid_path or not Path(mid_path).exists() or not meta:
        raise gr.Error("Compose something first, then click Save as Block.")
    try:
        import pretty_midi
        pm = pretty_midi.PrettyMIDI(str(mid_path))
        block_store.save_block(
            name.strip(), pm,
            tempo=meta["tempo"],
            time_signature=meta["time_signature"],
            bars=meta["bars"],
        )
        logger.info("Saved block %r from current MIDI compose", name.strip())
        return f"✓ Saved block '{name.strip()}'. Switch to Compose Song to use it."
    except FileExistsError as e:
        raise gr.Error(str(e))
    except Exception as e:
        raise _logged_error("Save as Block", e) from e


# ===================================================================
# Tab — Compose Song (multi-section, freeform tracks)
# ===================================================================

# Curated dropdown choices — match the option lists in the MIDI Compose tab
# so users get the same vocabulary across both editors.
KEYS = [
    "C", "C#", "Db", "D", "D#", "Eb", "E", "F", "F#", "Gb",
    "G", "G#", "Ab", "A", "A#", "Bb", "B",
]
TIME_SIGS = ["4/4", "3/4", "6/8", "12/8", "7/8", "5/4"]
VOICINGS = ["triad", "seventh", "ninth", "sixth", "add9",
            "sus2", "sus4", "power", "open5", "drop2",
            "quartal", "quintal", "shell", "rootless", "sus4_add9"]
CHORD_RHYTHMS = ["pad", "pulse_quarter", "stabs_8th", "charleston",
                 "funk_comp", "disco_stabs", "off_skank", "dotted_8ths",
                 "elton_octaves", "van_halen_chug",
                 "waltz_strum", "compound_6_8_strum",
                 # Latin / Caribbean / Spanish
                 "tresillo", "clave_son_3side", "clave_son_2side",
                 "rumba_clave", "bossa_comp", "montuno_2_3",
                 "flamenco_rasgueado", "bulería_12",
                 # Middle Eastern
                 "arab_maqsum", "arab_baladi",
                 # Indian
                 "indian_teental_16", "indian_keherwa_8",
                 # East/SE Asian
                 "gamelan_kotekan",
                 # Section / orchestral
                 "brass_shout", "brass_pad_swell",
                 "string_ostinato_16ths", "pizz_alternating",
                 "tremolo", "fanfare_dotted",
                 # Arpeggios
                 "arpeggio_up", "arpeggio_down", "arpeggio_16th", "alberti",
                 "arp_raga_ascend", "arp_pentatonic", "arp_quartal"]
BASS_PATTERNS = ["root", "root_fifth", "walking", "walking_swing",
                 "funk_16ths", "offbeat", "disco_octave", "palm_mute_8ths",
                 "flea_slap", "geddy_lee", "bootsy_slap",
                 "waltz_bass", "compound_6_8_bass",
                 # Cultural
                 "tumbao", "salsa_montuno_bass", "reggaeton_dembow_bass",
                 "samba_partido_alto", "arabic_iqa_baladi",
                 "indian_dhol_root", "gamelan_balungan"]
DRUM_PATTERNS = ["basic_rock", "four_on_floor", "halftime",
                 "funk", "dance_house", "disco",
                 "pop_disco", "pop_16ths",
                 "jazz_swing", "metal_gallop", "metal_blast",
                 "neil_peart", "chad_smith", "steve_smith",
                 "salsa", "reggaeton", "bossa_nova", "samba",
                 "merengue", "afrobeat",
                 "waltz_basic", "jazz_waltz",
                 "compound_6_8", "tarantella", "bulería", "afro_6_8",
                 "bembe", "son_clave_12_8",
                 "prog_7_8", "balkan_7_8",
                 "take_five_5_4", "odd_rock_5_4"]
MELODY_STYLES = ["motif", "riff", "chord_tone", "pentatonic", "blues",
                 "raga_yaman", "raga_bhairavi",
                 "maqam_hijaz", "maqam_rast",
                 "gamelan_slendro", "hirajoshi",
                 "random"]
LEAD_PATTERNS = ["clinton_synth", "van_halen_riff"]
TRACK_TYPES = ["chord", "bass", "melody", "drums", "lead", "theme", "harmony"]
FILL_AT_OPTIONS = ["none", "start", "end", "both"]
HARMONY_STYLES = ["follow", "accents", "oohs",
                  "abba", "queen", "boston", "journey", "elton", "chicago"]


_id_counter = {"n": 0}


def _genid(prefix: str) -> str:
    _id_counter["n"] += 1
    return f"{prefix}{_id_counter['n']}"


def _parse_ts(label: str) -> tuple[int, int]:
    n, d = label.split("/")
    return int(n), int(d)


# DAW-style state shape
# ---------------------------------------------------------------------------
# {
#   "title", "style", "key", "scale", "tempo", "time_signature",
#   "seed", "include_melody",
#   "tracks":   [{"id": "t1", "name": "Pad", "type": "chord", "defaults": {...}}],
#   "sections": [{"id": "s1", "name": "Intro", "bars": 4, "style": "pop",
#                 "progression": None, "key_override": None, "scale_override": None,
#                 "swing": None, "fill_at": "none", "accent_in": False, "fade": False,
#                 "harmony": 0, "harmony_style": "follow"}],
#   "clips":    {"t1:s1": {"active": True, "overrides": {"voicing": "ninth"}}, ...},
#   "selected": {"kind": "section"|"track"|"clip"|None, "id": str|None},
# }

def _default_song_state() -> dict:
    """Block-timeline state shape — matches data/songs/<title>.yaml format."""
    return {
        "title": "Untitled Song",
        "timeline": [],   # list of {block_name, repeat}
    }


def _default_track_for_type(ttype: str, preset_key: str = "pop") -> dict:
    """Return the per-type defaults dict (shape of a track's `defaults` field)
    seeded from a style preset. Doesn't include `track_name` / `type` / `id`."""
    preset = STYLES.get(preset_key, STYLES["pop"])
    if ttype == "chord":
        return {"voicing": preset.voicing, "chord_rhythm": preset.chord_rhythm,
                "octave": preset.chord_octave, "program": preset.chord_program}
    if ttype == "bass":
        return {"pattern": preset.bass_pattern,
                "octave": preset.bass_octave, "program": preset.bass_program}
    if ttype == "melody":
        return {"octave": preset.melody_octave, "program": preset.melody_program,
                "melody_style": preset.melody_style,
                "density": float(preset.melody_density)}
    if ttype == "drums":
        return {"pattern": preset.drum_pattern or "basic_rock"}
    if ttype == "lead":
        return {"pattern": "clinton_synth", "octave": 4, "program": 82, "density": 1.0}
    if ttype == "theme":
        first_theme = next(iter(THEMES.keys()), "hit_the_sack")
        return {"theme": first_theme,
                "octave": preset.melody_octave, "program": preset.melody_program}
    if ttype == "harmony":
        # Vocal-style harmony layered above the Melody track. Defaults
        # to 2-voice queen-style ([2,4] intervals above), smooth
        # voice-leading rule, no intervals override. The preset list
        # is the same one Melody Studio's HarmonyTag uses.
        return {
            "preset": "queen",
            "voices": 2,
            "harmony_rule": "voice_leading_smooth",
            "intervals": "",
            "source_track": "Melody",
            "program": int(preset.melody_program),
        }
    return {}


def _default_track(name: str, ttype: str, style_key: str = "pop") -> dict:
    return {
        "id": _genid("t"),
        "name": name or ttype.title(),
        "type": ttype,
        "defaults": _default_track_for_type(ttype, style_key),
    }


def _default_extra_track(ttype: str, name: str = "", style_key: str = "pop") -> dict:
    """Starter dict for the MIDI Compose Extra Tracks accordion. Flat shape:
    {type, track_name, ...per-type params}. Distinct from the song-level
    track shape used in Compose Song (which has nested `defaults`).

    Includes per-extra ``progression`` / ``progression_locked`` so the new
    consolidated "Per-instrument progressions" panel can manage this
    extra's chord progression alongside the fixed instruments."""
    base = {
        "type": ttype,
        "track_name": (name or ttype.title()).strip(),
        "progression": "",
        "progression_locked": True,
        # Counter-melody defaults — only used by lead extras today.
        # "independent" preserves the per-pattern riff behavior; the
        # other modes make the lead respond to the Melody track.
        "follow_source": "",
        "follow_mode": "independent",
    }
    base.update(_default_track_for_type(ttype, style_key))
    return base


def _render_extra_track_row(idx: int, tr: dict, extras_state: gr.State,
                            rerender_signal: "gr.Number | None" = None) -> None:
    """Render one row of the Extra Tracks accordion.

    The parent ``@gr.render`` is gated by an explicit ``triggers=`` list
    (add-button click + ``rerender_signal`` change) so field edits no
    longer trigger a rebuild. That eliminates the "fields are locked"
    symptom — widgets are STATIC during editing; only Add and Remove
    cause structural re-renders.

    Mutations to fields write back into ``extras_state`` but do NOT
    bump ``rerender_signal``, so the user can change any number of
    fields without disturbing the row layout. The Remove button bumps
    the signal so the row physically disappears.
    """
    ttype = tr.get("type", "lead")
    # A row-stable key prefix scopes every widget on this row by index.
    k = lambda field: f"extra_{idx}_{field}"
    with gr.Group():
        with gr.Row():
            gr.Markdown(f"**Extra {idx + 1}** &nbsp; `{ttype}`")
            name_in = gr.Textbox(value=tr.get("track_name", ""),
                                 label="Track name", scale=2,
                                 key=k("name"))
            remove_btn = gr.Button("⛌", size="sm", variant="stop", scale=0,
                                   key=k("remove"))

        def _set(state, **kv):
            out = list(state)
            out[idx] = {**out[idx], **kv}
            return out

        name_in.blur(lambda s, v: _set(s, track_name=v),
                     [extras_state, name_in], extras_state)

        with gr.Row():
            if ttype == "chord":
                voicing_dd = gr.Dropdown(VOICINGS, value=tr.get("voicing", "triad"),
                                         label="Voicing", key=k("voicing"),
                                         allow_custom_value=True)
                rhythm_dd = gr.Dropdown(CHORD_RHYTHMS,
                                        value=tr.get("chord_rhythm", "pulse_quarter"),
                                        label="Rhythm", key=k("rhythm"),
                                        allow_custom_value=True)
                octave_in = gr.Number(value=int(tr.get("octave", 3)),
                                      label="Octave", precision=0,
                                      key=k("octave"))
                program_in = gr.Number(value=int(tr.get("program", 0)),
                                       label="GM program", precision=0,
                                       key=k("program"))
                voicing_dd.change(lambda s, v: _set(s, voicing=v),
                                  [extras_state, voicing_dd], extras_state)
                rhythm_dd.change(lambda s, v: _set(s, chord_rhythm=v),
                                 [extras_state, rhythm_dd], extras_state)
                octave_in.change(lambda s, v: _set(s, octave=int(v)),
                                 [extras_state, octave_in], extras_state)
                program_in.change(lambda s, v: _set(s, program=int(v)),
                                  [extras_state, program_in], extras_state)
            elif ttype == "bass":
                pat_dd = gr.Dropdown(BASS_PATTERNS,
                                     value=tr.get("pattern", "root_fifth"),
                                     label="Pattern", key=k("pattern"),
                                     allow_custom_value=True)
                octave_in = gr.Number(value=int(tr.get("octave", 2)),
                                      label="Octave", precision=0,
                                      key=k("octave"))
                program_in = gr.Number(value=int(tr.get("program", 33)),
                                       label="GM program", precision=0,
                                       key=k("program"))
                pat_dd.change(lambda s, v: _set(s, pattern=v),
                              [extras_state, pat_dd], extras_state)
                octave_in.change(lambda s, v: _set(s, octave=int(v)),
                                 [extras_state, octave_in], extras_state)
                program_in.change(lambda s, v: _set(s, program=int(v)),
                                  [extras_state, program_in], extras_state)
            elif ttype == "melody":
                style_dd_m = gr.Dropdown(MELODY_STYLES,
                                         value=tr.get("melody_style", "motif"),
                                         label="Style", key=k("style"),
                                         allow_custom_value=True)
                octave_in = gr.Number(value=int(tr.get("octave", 5)),
                                      label="Octave", precision=0,
                                      key=k("octave"))
                program_in = gr.Number(value=int(tr.get("program", 0)),
                                       label="GM program", precision=0,
                                       key=k("program"))
                density_in = gr.Slider(0.0, 1.0,
                                       value=float(tr.get("density", 1.0)),
                                       step=0.05, label="Density",
                                       key=k("density"))
                style_dd_m.change(lambda s, v: _set(s, melody_style=v),
                                  [extras_state, style_dd_m], extras_state)
                octave_in.change(lambda s, v: _set(s, octave=int(v)),
                                 [extras_state, octave_in], extras_state)
                program_in.change(lambda s, v: _set(s, program=int(v)),
                                  [extras_state, program_in], extras_state)
                density_in.change(lambda s, v: _set(s, density=float(v)),
                                  [extras_state, density_in], extras_state)
            elif ttype == "drums":
                pat_dd = gr.Dropdown(DRUM_PATTERNS,
                                     value=tr.get("pattern", "basic_rock"),
                                     label="Pattern", key=k("pattern"),
                                     allow_custom_value=True)
                density_in = gr.Slider(0.0, 1.0,
                                       value=float(tr.get("density", 1.0)),
                                       step=0.05, label="Density",
                                       info="Thin out non-anchor hits.",
                                       key=k("density"))
                pat_dd.change(lambda s, v: _set(s, pattern=v),
                              [extras_state, pat_dd], extras_state)
                density_in.change(lambda s, v: _set(s, density=float(v)),
                                  [extras_state, density_in], extras_state)
            elif ttype == "lead":
                pat_dd = gr.Dropdown(LEAD_PATTERNS,
                                     value=tr.get("pattern", "clinton_synth"),
                                     label="Pattern", key=k("pattern"),
                                     allow_custom_value=True)
                octave_in = gr.Number(value=int(tr.get("octave", 4)),
                                      label="Octave", precision=0,
                                      key=k("octave"))
                program_in = gr.Number(value=int(tr.get("program", 82)),
                                       label="GM program", precision=0,
                                       key=k("program"))
                follow_dd = gr.Dropdown(
                    [
                        ("Independent line", "independent"),
                        ("Parallel 3rd above Melody", "parallel_third"),
                        ("Parallel 6th above Melody", "parallel_sixth"),
                        ("Contrary motion vs Melody", "contrary_motion"),
                        ("Call / response with Melody", "call_response"),
                    ],
                    value=tr.get("follow_mode", "independent"),
                    label="Follow primary",
                    info=("'Independent' uses the pattern above. Other "
                          "modes make this lead respond to the Melody track."),
                    key=k("follow_mode"),
                    allow_custom_value=True,
                )
                pat_dd.change(lambda s, v: _set(s, pattern=v),
                              [extras_state, pat_dd], extras_state)
                octave_in.change(lambda s, v: _set(s, octave=int(v)),
                                 [extras_state, octave_in], extras_state)
                program_in.change(lambda s, v: _set(s, program=int(v)),
                                  [extras_state, program_in], extras_state)

                def _on_follow_change(s, v):
                    # follow_source is implicitly "Melody" when the
                    # mode is anything other than "independent".
                    src = "Melody" if (v and v != "independent") else ""
                    return _set(s, follow_mode=v or "independent",
                                follow_source=src)

                follow_dd.change(_on_follow_change,
                                 [extras_state, follow_dd], extras_state)
            elif ttype == "theme":
                theme_dd = gr.Dropdown(list(THEMES.keys()) or ["hit_the_sack"],
                                       value=tr.get("theme", "hit_the_sack"),
                                       label="Theme", key=k("theme"),
                                       allow_custom_value=True)
                octave_in = gr.Number(value=int(tr.get("octave", 5)),
                                      label="Octave", precision=0,
                                      key=k("octave"))
                program_in = gr.Number(value=int(tr.get("program", 0)),
                                       label="GM program", precision=0,
                                       key=k("program"))
                theme_dd.change(lambda s, v: _set(s, theme=v),
                                [extras_state, theme_dd], extras_state)
                octave_in.change(lambda s, v: _set(s, octave=int(v)),
                                 [extras_state, octave_in], extras_state)
                program_in.change(lambda s, v: _set(s, program=int(v)),
                                  [extras_state, program_in], extras_state)
            elif ttype == "harmony":
                # Vocal-style harmony layered above (or below) the
                # Melody track. Preset picks the interval shape;
                # voices picks how many of those intervals to render.
                # Each voice lands on its own MIDI track ("Melody Harm
                # 1", "Melody Harm 2", …) so they're editable
                # independently in any DAW.
                voices_radio = gr.Radio(
                    [1, 2, 3],
                    value=int(tr.get("voices", 2)),
                    label="Voices",
                    info="How many harmony lines to layer.",
                    key=k("voices"),
                )
                preset_dd = gr.Dropdown(
                    HARMONY_PRESETS,
                    value=tr.get("preset", "queen"),
                    label="Preset",
                    info="Band-style interval shape.",
                    allow_custom_value=True,
                    key=k("preset"),
                )
                rule_dd = gr.Dropdown(
                    ["", *sorted(HARMONY_OPS)],
                    value=tr.get("harmony_rule", "voice_leading_smooth"),
                    label="Voice-leading rule",
                    info="Blank = smooth default.",
                    allow_custom_value=True,
                    key=k("harmony_rule"),
                )
                intervals_in = gr.Textbox(
                    value=tr.get("intervals", ""),
                    label="Intervals override (CSV)",
                    placeholder="Blank = use preset. e.g. '1,2,4'",
                    key=k("intervals"),
                )
                source_in = gr.Textbox(
                    value=tr.get("source_track", "Melody"),
                    label="Source track",
                    info="Track name to harmonise (default Melody).",
                    key=k("source"),
                )
                program_in = gr.Number(
                    value=int(tr.get("program", 0)), label="GM program",
                    precision=0, key=k("program"),
                )
                voices_radio.change(lambda s, v: _set(s, voices=int(v)),
                                    [extras_state, voices_radio], extras_state)
                preset_dd.change(lambda s, v: _set(s, preset=v or "queen"),
                                 [extras_state, preset_dd], extras_state)
                rule_dd.change(lambda s, v: _set(s, harmony_rule=v or ""),
                               [extras_state, rule_dd], extras_state)
                intervals_in.change(lambda s, v: _set(s, intervals=v or ""),
                                    [extras_state, intervals_in], extras_state)
                source_in.change(lambda s, v: _set(s, source_track=v or "Melody"),
                                 [extras_state, source_in], extras_state)
                program_in.change(lambda s, v: _set(s, program=int(v)),
                                  [extras_state, program_in], extras_state)

        # Shared override row: per-extra swing / seed. Blank = inherit from
        # the main Compose values. (Per-extra progression now lives in the
        # consolidated "Per-instrument progressions" panel above.)
        with gr.Row():
            swing_override = gr.Number(
                value=tr.get("swing", None), precision=2, minimum=0.0, maximum=0.5,
                label="Swing override", info="Blank = inherit main swing",
                key=k("swing_override"),
            )
            seed_override = gr.Number(
                value=tr.get("seed", None), precision=0, minimum=0, maximum=2**31 - 1,
                label="Seed override", info="Blank = inherit main seed",
                key=k("seed_override"),
            )
        swing_override.change(lambda s, v: _set(s, swing=v if v not in (None, "") else None),
                              [extras_state, swing_override], extras_state)
        seed_override.change(lambda s, v: _set(s, seed=v if v not in (None, "", 0) else None),
                             [extras_state, seed_override], extras_state)

        def _remove(state, sig):
            new = [t for i, t in enumerate(state) if i != idx]
            return new, int((sig or 0) + 1)

        if rerender_signal is not None:
            remove_btn.click(
                _remove,
                [extras_state, rerender_signal],
                [extras_state, rerender_signal],
            )
        else:
            # Back-compat: legacy callers without a signal still work
            # (no structural re-render after remove, but state is correct).
            remove_btn.click(
                lambda state: [t for i, t in enumerate(state) if i != idx],
                [extras_state], extras_state,
            )


def export_session(session_name: str, tempo: float,
                   include_ai: bool, include_midi: bool,
                   include_hq_stems: bool = False):
    """Bundle the latest AI audio + MIDI into an Ardour session zip."""
    if not session_name.strip():
        raise gr.Error("Enter a session name.")
    if not include_ai and not include_midi:
        raise gr.Error("Include at least one source.")
    if include_ai and _state["ai_wav_path"] is None:
        raise gr.Error("No AI audio yet — generate something in the Generate tab first.")
    if include_midi and _state["midi_wav_path"] is None:
        raise gr.Error("No MIDI composition yet — create something in the Compose tab first.")
    render_result = _state.get("render_result")
    if include_hq_stems and not (render_result and render_result.get("stem_paths")):
        raise gr.Error(
            "No high-quality stems yet — click 'Render to High-Quality Audio' "
            "in the Compose tab first."
        )

    try:
        logger.info("export_session: name=%s tempo=%s ai=%s midi=%s hq_stems=%s",
                    session_name, tempo, include_ai, include_midi, include_hq_stems)
        builder = ArdourSessionBuilder(session_name, tempo=tempo, sample_rate=44100)

        if include_midi and _state["midi_wav_path"] is not None:
            audio, sr = sf.read(str(_state["midi_wav_path"]))
            builder.add_audio_track("MIDI_Mix", audio, sr, color="#70ad47")
            del audio
        if include_midi and _state["midi_path"] is not None:
            builder.add_midi_file("Accompaniment", _state["midi_path"], color="#ffc000")
        if include_ai and _state["ai_wav_path"] is not None:
            audio, sr = sf.read(str(_state["ai_wav_path"]))
            builder.add_audio_track("AI_Lead", audio, sr, color="#5b9bd5")
            del audio
        if include_hq_stems and render_result:
            builder.add_rendered_stems(render_result["stem_paths"], color="#5b9bd5")

        sessions_dir = OUTPUT_DIR / "sessions"
        session_dir = builder.export(sessions_dir)
        zip_path = OUTPUT_DIR / f"{session_name.replace(' ', '_')}"
        shutil.make_archive(str(zip_path), "zip", str(session_dir))
        zip_file = str(zip_path) + ".zip"

        return zip_file, f"Exported {len(builder.tracks)} tracks to {session_dir.name}/"
    except gr.Error:
        raise
    except Exception as e:
        raise _logged_error("Export session", e) from e


def export_logic_bundle(bundle_name: str, tempo: float, time_sig: str,
                        include_hq_stems: bool):
    """Bundle the latest MIDI as a Logic-friendly drop-in folder zip."""
    if not bundle_name.strip():
        raise gr.Error("Enter a bundle name.")
    midi_path = _state.get("midi_path")
    if not midi_path or not Path(midi_path).exists():
        raise gr.Error("No MIDI yet — Compose something first.")

    render_result = _state.get("render_result") if include_hq_stems else None
    if include_hq_stems and not (render_result and render_result.get("stem_paths")):
        raise gr.Error(
            "Include stems checked but no high-quality render yet. "
            "Click 'Render to High-Quality Audio' first, or uncheck."
        )

    try:
        logger.info("export_logic_bundle: name=%s tempo=%s ts=%s stems=%s",
                    bundle_name, tempo, time_sig, include_hq_stems)
        # Reload the saved .mid into a MidiExporter so we get the right
        # track structure (programs, drum flags, names).
        from src.audio_processing.render.pipeline import _load_midi
        midi = _load_midi(midi_path)
        ts = _parse_time_sig(time_sig)
        midi.tempo = float(tempo)
        midi.time_signature = ts

        bundle = LogicSessionBundle.from_midi_exporter(
            bundle_name,
            midi,
            rendered_stems=(render_result["stem_paths"] if render_result else None),
        )
        bundles_dir = OUTPUT_DIR / "logic_bundles"
        bundle_dir = bundle.export(bundles_dir)

        zip_base = OUTPUT_DIR / f"{bundle_name.replace(' ', '_')}_logic"
        zip_path = shutil.make_archive(str(zip_base), "zip", str(bundle_dir))
        return zip_path, (
            f"Logic bundle: {len(bundle.tracks)} tracks, "
            f"stems={'yes' if include_hq_stems else 'no'} → {bundle_dir.name}/"
        )
    except gr.Error:
        raise
    except Exception as e:
        raise _logged_error("Export Logic bundle", e) from e


def render_song(state: dict):
    """Render the block-timeline state into a concatenated MIDI."""
    timeline = state.get("timeline", []) if state else []
    if not timeline:
        raise gr.Error("Add at least one block to the timeline.")
    try:
        logger.info("render_song: title=%s blocks=%s",
                    state.get("title"), [t.get("block_name") for t in timeline])
        pm, info = block_concat.concat_blocks(timeline)
        mid_path = OUTPUT_DIR / "last_song.mid"
        pm.write(str(mid_path))
        # Synth audio preview
        audio = pm.synthesize(fs=44100)
        wav_path = OUTPUT_DIR / "last_song.wav"
        sf.write(str(wav_path), audio, 44100)
        _state["midi_path"] = mid_path
        _state["midi_wav_path"] = wav_path
        del audio
        info_text = (f"{info['duration_seconds']:.1f}s | "
                     f"{info['n_instruments']} instruments | "
                     f"{info['n_notes']} notes | {info['summary']}")
        return str(wav_path), str(mid_path), info_text
    except gr.Error:
        raise
    except ValueError as e:
        raise gr.Error(str(e))
    except Exception as e:
        raise _logged_error("Render song", e) from e


def _build_playback_tab() -> None:
    """Guitar-Pro-style score viewer with a moving cursor.

    Layout:
      - Source dropdown (latest compose / saved block / latest song).
      - Reload + Render-HQ buttons.
      - AlphaTab score area (full-width SVG, auto-scrolling cursor).
      - Hidden bridges (textboxes + button) that wire the JS in
        ``static/alphatab/playback.js`` to the server handlers.
      - Note-info markdown that updates on note click.
    """
    gr.Markdown(
        "### Playback — score with moving cursor\n"
        "Pick a source, click ▶. The cursor sweeps across the staves "
        "as the audio plays. Tap any note to seek there and see its "
        "pitch / duration / bar in the panel below. Click **🎚 Render "
        "HQ mix** to swap AlphaTab's built-in synth for the FluidSynth "
        "mix (cursor stays beat-locked either way)."
    )

    initial_sources = _list_playback_sources()
    initial_value = initial_sources[0][1] if initial_sources else None

    with gr.Row():
        source_dd = gr.Dropdown(
            choices=initial_sources,
            value=initial_value,
            label="Source",
            scale=3,
        )
        reload_btn = gr.Button("🔄 Reload sources", scale=1)
        hq_render_btn = gr.Button("🎚 Render HQ mix", scale=1)

    hq_status = gr.Markdown("")

    # Initial base64 MIDI + audio URL (loads on tab build).
    initial_b64 = (
        _load_midi_for_playback(initial_value) if initial_value else ""
    )
    initial_audio = (
        _load_audio_for_playback(initial_value) if initial_value else ""
    )
    score_html = gr.HTML(value=build_playback_html(initial_b64, initial_audio))

    # ---- Gradio↔JS bridges (rendered but visually hidden) ----
    # JS polls these textboxes for new MIDI + audio URLs; JS writes
    # note-click JSON into pb_note_event and clicks pb_note_trigger.
    # `visible=False` removes them from the DOM entirely in Gradio 6,
    # so we render them visible and hide via CSS in the playback HTML.
    with gr.Row(elem_classes=["pb-hidden-bridges"]):
        midi_payload = gr.Textbox(
            value="", elem_id="pb_midi_payload", show_label=False,
        )
        audio_url = gr.Textbox(
            value="", elem_id="pb_audio_url", show_label=False,
        )
        note_event = gr.Textbox(
            value="", elem_id="pb_note_event", show_label=False,
        )
        note_trigger = gr.Button(
            "trigger", elem_id="pb_note_trigger",
        )

    note_info = gr.Markdown("Click a note in the score.")

    # Source change → push new MusicXML + WAV URL to the JS bridge.
    source_dd.change(_load_midi_for_playback, [source_dd], [midi_payload])
    source_dd.change(_load_audio_for_playback, [source_dd], [audio_url])

    def _reload_sources():
        choices = _list_playback_sources()
        val = choices[0][1] if choices else None
        return gr.update(choices=choices, value=val)
    reload_btn.click(_reload_sources, [], [source_dd])

    def _do_render_hq(source_id, progress=gr.Progress(track_tqdm=True)):
        try:
            url = _render_hq_for_playback(source_id)
            return url, "✓ HQ mix ready — playback now uses the FluidSynth mix."
        except gr.Error:
            raise
        except Exception as e:
            raise _logged_error("Render HQ for playback", e) from e

    # HQ render output goes to the SAME audio_url bridge — the JS just
    # swaps the <audio> source. No checkbox needed: AlphaTab is always
    # in external-media mode and follows whatever URL we set last.
    hq_render_btn.click(_do_render_hq, [source_dd], [audio_url, hq_status])

    note_trigger.click(_on_playback_note_event, [note_event], [note_info])


def _build_compose_song_tab(library_trigger: gr.State) -> None:
    """DAW-style block-timeline composer.

    Two sections:
      1. Block Library — cards for every saved block (rendered from MIDI
         Compose). Click "+ Timeline" on a card to append it to the timeline.
      2. Timeline — horizontal left-to-right row of block cards. Reorder via
         ←/→ buttons; remove via ⛌; per-block repeat count. Function-slot
         markers (▤) sit between consecutive blocks for future inter-block
         operations like Generate Fill.

    Render Song concatenates the timeline into one .mid via block_concat.

    ``library_trigger`` is a shared gr.State integer that gets bumped whenever
    a block is saved (from MIDI Compose) or deleted (from a card). The
    @gr.render below ignores its value and re-reads ``list_blocks()`` from
    disk each time the trigger ticks.
    """
    gr.Markdown(
        "### Compose Song — Block Timeline\n"
        "Render blocks in **MIDI Compose** (use the **Save as Block** button "
        "there), then arrange them on the timeline below. Each block keeps "
        "its own tempo and time signature; the rendered song will switch at "
        "block boundaries."
    )

    song_state = gr.State(_default_song_state())

    # ----- Top control row ----------------------------------------------
    with gr.Row():
        title_in = gr.Textbox(value="Untitled Song", label="Song title", scale=2)
        save_song_btn = gr.Button("💾 Save Song", scale=1)
        load_song_dd = gr.Dropdown(
            choices=song_store.list_song_timelines(),
            value=None, label="Load saved song", scale=2,
            allow_custom_value=False,
        )
        load_song_btn = gr.Button("📂 Load", scale=1)
        render_btn = gr.Button("▶ Render Song", variant="primary", scale=2)

    save_song_status = gr.Markdown("")

    title_in.change(lambda s, v: {**s, "title": v},
                    [song_state, title_in], song_state)

    # ----- Block library --------------------------------------------------
    gr.Markdown("---")
    with gr.Row():
        gr.Markdown("### 📚 Block Library")
        refresh_lib_btn = gr.Button("🔄 Refresh", scale=0)
        rerender_lib_btn = gr.Button("↻ Re-render all at HQ", scale=0,
                                     variant="secondary")
    rerender_status = gr.Markdown("")

    @gr.render(inputs=[library_trigger])
    def _render_library(_trigger):
        # Always read fresh from disk — `_trigger` is just a re-render signal.
        blocks_list = block_store.list_blocks()
        if not blocks_list:
            gr.Markdown(
                "_No blocks yet. Switch to **MIDI Compose**, render something, "
                "type a name, and click **💾 Save as Block** — it'll appear "
                "here._"
            )
            return
        per_row = 4
        for row_start in range(0, len(blocks_list), per_row):
            with gr.Row(equal_height=False):
                for blk in blocks_list[row_start:row_start + per_row]:
                    with gr.Column(scale=1, min_width=220):
                        _render_library_card(blk, song_state, library_trigger)

    refresh_lib_btn.click(lambda v: (v or 0) + 1,
                          [library_trigger], library_trigger)

    def _rerender_all_blocks(trigger, progress=gr.Progress()):
        """Walk the block library and re-render every preview WAV at
        44.1 kHz stereo via the HQ pipeline. Older blocks saved when
        the preview synth was 22 kHz mono catch up to today's
        standard."""
        names = [b["name"] for b in block_store.list_blocks()]
        if not names:
            return "_No blocks to re-render._", (trigger or 0) + 1
        progress(0, desc="Starting HQ re-render…")
        n_ok = 0
        n_fail = 0
        for i, name in enumerate(names):
            progress((i + 1) / len(names), desc=f"Rendering {name}…")
            try:
                if block_store.rerender_block_wav(name) is not None:
                    n_ok += 1
                else:
                    n_fail += 1
            except Exception:
                n_fail += 1
        msg = f"Re-rendered **{n_ok}** of {len(names)} blocks at 44.1 kHz stereo."
        if n_fail:
            msg += f" {n_fail} failed (see logs)."
        return msg, (trigger or 0) + 1

    rerender_lib_btn.click(
        _rerender_all_blocks,
        [library_trigger],
        [rerender_status, library_trigger],
    )

    # ----- Timeline -------------------------------------------------------
    gr.Markdown("---")
    with gr.Row():
        gr.Markdown("### 🎬 Timeline (left to right)")
        clear_tl_btn = gr.Button("Clear timeline", scale=0)

    @gr.render(inputs=[song_state])
    def _render_timeline(state):
        timeline = state.get("timeline", []) if state else []
        if not timeline:
            gr.Markdown(
                "_Empty timeline. Click **+ Timeline** on a block card above "
                "to add it._"
            )
            return
        # Compute total bars by summing each block's bars * repeat
        lib = {b["name"]: b for b in block_store.list_blocks()}
        total_bars = sum(int(lib.get(t["block_name"], {}).get("bars", 0)) * int(t.get("repeat", 1))
                         for t in timeline)
        total_secs = sum(float(lib.get(t["block_name"], {}).get("duration_seconds", 0)) * int(t.get("repeat", 1))
                         for t in timeline)
        gr.Markdown(
            f"**Total:** {total_bars} bars / {total_secs:.1f} s "
            f"&nbsp;·&nbsp; {len(timeline)} timeline entries"
        )
        with gr.Row(equal_height=False):
            for tl_idx, entry in enumerate(timeline):
                with gr.Column(scale=0, min_width=180):
                    _render_timeline_card(tl_idx, entry, len(timeline),
                                          lib, song_state)
                # Function-slot marker between consecutive blocks (NOT after the last).
                if tl_idx < len(timeline) - 1:
                    with gr.Column(scale=0, min_width=40):
                        gr.Markdown("&nbsp;")
                        slot_btn = gr.Button("▤", size="sm", interactive=False)
                        slot_btn.click(lambda: None, None, None)  # placeholder

    def _clear_timeline(state):
        return {**state, "timeline": []}

    clear_tl_btn.click(_clear_timeline, [song_state], song_state)

    # ----- Output panel ---------------------------------------------------
    gr.Markdown("---")
    with gr.Row():
        with gr.Column(scale=1):
            audio_out = gr.Audio(label="Rendered song (preview)", type="filepath")
        with gr.Column(scale=1):
            file_out = gr.File(label="Download .mid")
            info_out = gr.Textbox(label="Info", interactive=False)

    render_btn.click(render_song, [song_state],
                     [audio_out, file_out, info_out])

    # ----- High-quality render --------------------------------------------
    gr.Markdown("---\n### 🎚 Render to High-Quality Audio")
    with gr.Row():
        with gr.Column(scale=1):
            song_master_dd = gr.Dropdown(
                list(MASTER_PRESETS.keys()),
                value="default", label="Master preset",
            )
            song_stems_chk = gr.Checkbox(value=True, label="Export stems")
            song_soundfont_in = gr.Textbox(
                value="auto", label="Soundfont path",
                info="'auto' = use largest in data/soundfonts/.",
            )
            song_render_hq_btn = gr.Button(
                "🎚 Render Song to High-Quality Audio",
                variant="primary",
            )
        with gr.Column(scale=1):
            song_hq_audio = gr.Audio(label="High-quality mix", type="filepath")
            song_hq_stems = gr.File(label="Download stems (.zip)")
            song_hq_info = gr.Textbox(label="Render info", interactive=False)
            song_pdf_btn = gr.Button("🎼 Export PDF (full score + parts)",
                                     variant="secondary")
            song_pdf_file = gr.File(label="Download PDFs (.zip)")
            song_pdf_btn.click(_export_song_pdf, [song_state],
                               [song_pdf_file])

    def _render_song_hq(master, with_stems, sf_path):
        # Re-run the timeline render so _state["midi_path"] is up to date.
        # Then call the high-quality renderer with a song-specific subdir.
        return render_high_quality(
            master, with_stems, sf_path,
            output_subdir="render_song",
        )

    song_render_hq_btn.click(
        _render_song_hq,
        inputs=[song_master_dd, song_stems_chk, song_soundfont_in],
        outputs=[song_hq_audio, song_hq_stems, song_hq_info],
    )

    # ----- Save / Load handlers ------------------------------------------
    def _do_save_song(state, title):
        if not title or not title.strip():
            raise gr.Error("Enter a song title to save.")
        try:
            timeline = state.get("timeline", []) if state else []
            path = song_store.save_song_timeline(title.strip(), timeline)
            return f"✓ Saved song to {path}"
        except FileExistsError as e:
            raise gr.Error(str(e))
        except Exception as e:
            raise _logged_error("Save song", e) from e

    save_song_btn.click(_do_save_song, [song_state, title_in], save_song_status)

    def _do_load_song(state, title):
        if not title:
            raise gr.Error("Pick a saved song.")
        try:
            data = song_store.load_song_timeline(title)
            return {"title": data["title"], "timeline": list(data["timeline"])}
        except Exception as e:
            raise _logged_error("Load song", e) from e

    load_song_btn.click(_do_load_song, [song_state, load_song_dd], song_state)


def _render_library_card(blk: dict, song_state: gr.State,
                         library_trigger: gr.State) -> None:
    """One card in the Block Library.

    Every interactive widget carries a stable ``key=`` so Gradio's
    ``@gr.render`` reconciles the live component across re-renders
    (e.g. when ``library_trigger`` bumps after a save or delete). The
    same pattern keeps Extras-row / Override-row click handlers from
    being dropped mid-interaction; see ``_render_extra_track_row``.
    """
    name = blk.get("name", "?")
    ts = blk.get("time_signature", [4, 4])
    k = lambda field: f"lib_{name}_{field}"
    with gr.Group():
        gr.Markdown(
            f"**{name}**\n\n"
            f"{blk.get('bars', '?')} bars · {ts[0]}/{ts[1]} · "
            f"{blk.get('tempo', '?')} BPM\n\n"
            f"{len(blk.get('instruments', []))} instruments · "
            f"{blk.get('n_notes', '?')} notes"
        )
        wav_path = blk.get("_wav_path")
        if wav_path and Path(wav_path).exists():
            gr.Audio(value=wav_path, label="Preview", type="filepath",
                     interactive=False, key=k("audio"))
        else:
            preview_btn = gr.Button("▶ Generate preview", size="sm",
                                    key=k("preview"))

            def _gen_preview(name=name):
                p = block_store.ensure_preview_wav(name)
                if not p:
                    return None
                return str(p)

            preview_audio = gr.Audio(label="Preview", type="filepath",
                                     interactive=False, key=k("preview_audio"))
            preview_btn.click(_gen_preview, None, preview_audio)

        with gr.Row():
            add_btn = gr.Button("+ Timeline", size="sm",
                                variant="primary", scale=2, key=k("add"))
            pdf_btn = gr.Button("🎼 PDF", size="sm", scale=0,
                                key=k("pdf"))
            del_btn = gr.Button("⛌", size="sm", variant="stop", scale=0,
                                key=k("del"))
        pdf_file = gr.File(label="PDFs (.zip)", key=k("pdf_file"))

        def _add_to_timeline(state, name=name):
            timeline = list(state.get("timeline", []))
            timeline.append({"block_name": name, "repeat": 1})
            return {**state, "timeline": timeline}

        add_btn.click(_add_to_timeline, [song_state], song_state)

        def _block_pdf(name=name):
            return _export_block_pdf(name)

        pdf_btn.click(_block_pdf, None, pdf_file)

        def _delete_block(trigger, name=name):
            block_store.delete_block(name)
            return (trigger or 0) + 1

        del_btn.click(_delete_block, [library_trigger], library_trigger)


def _render_timeline_card(tl_idx: int, entry: dict, total: int,
                          lib: dict, song_state: gr.State) -> None:
    """One card on the Timeline. Stable keys per card so the timeline
    @gr.render doesn't race with widget clicks."""
    name = entry.get("block_name", "?")
    repeat = int(entry.get("repeat") or 1)
    blk = lib.get(name) or {}
    ts = blk.get("time_signature", [4, 4])
    k = lambda field: f"tl_{tl_idx}_{field}"
    with gr.Group():
        gr.Markdown(
            f"**{tl_idx + 1}. {name}**\n\n"
            f"{blk.get('bars', '?')} bars · {ts[0]}/{ts[1]} · "
            f"{blk.get('tempo', '?')} BPM"
            + ("\n\n_(missing — block deleted)_" if not blk else "")
        )
        repeat_in = gr.Number(value=repeat, label="Repeat",
                              precision=0, minimum=1, maximum=32,
                              key=k("repeat"))

        def _set_repeat(state, v, idx=tl_idx):
            timeline = list(state.get("timeline", []))
            if 0 <= idx < len(timeline):
                timeline[idx] = {**timeline[idx], "repeat": max(1, int(v))}
            return {**state, "timeline": timeline}

        repeat_in.change(_set_repeat, [song_state, repeat_in], song_state)

        with gr.Row():
            left_btn = gr.Button("←", size="sm",
                                 interactive=tl_idx > 0, key=k("left"))
            right_btn = gr.Button("→", size="sm",
                                  interactive=tl_idx < total - 1,
                                  key=k("right"))
            remove_btn = gr.Button("⛌", size="sm", variant="stop",
                                   key=k("remove"))

        def _move(state, delta, idx=tl_idx):
            timeline = list(state.get("timeline", []))
            j = idx + delta
            if 0 <= j < len(timeline):
                timeline[idx], timeline[j] = timeline[j], timeline[idx]
            return {**state, "timeline": timeline}

        left_btn.click(lambda s: _move(s, -1), [song_state], song_state)
        right_btn.click(lambda s: _move(s, +1), [song_state], song_state)

        def _remove(state, idx=tl_idx):
            timeline = list(state.get("timeline", []))
            if 0 <= idx < len(timeline):
                del timeline[idx]
            return {**state, "timeline": timeline}

        remove_btn.click(_remove, [song_state], song_state)


# ===================================================================
# Melody Studio — bar-by-bar editor for the melody track
# ===================================================================
#
# The Studio operates on a `melody_plan.MelodyPlan` pinned in `_state`.
# Three view modes share the same plan: Note List (one row per note),
# Scale-degree grid (rows = scale degrees 1..7 over two octaves, cols =
# 16th-note steps × bars), and Piano-roll (chromatic version of the
# grid). Per-bar SectionOverrides and per-range HarmonyTags live in
# editable dataframes alongside the editor. Render-preview and save-
# plan close the loop.

MELODY_VIEW_MODES = ["Note list", "Scale-degree grid", "Piano-roll"]
HARMONY_PRESETS = ["queen", "abba", "boston", "journey", "elton", "chicago"]
SECTION_MODES = ["stack", "replace", "decoration"]

# Combined rhythm catalogue for SectionOverride dropdowns. Includes a
# blank option (means "no rhythm override") plus all strum patterns and
# all arpeggios.
_RHYTHM_CHOICES = ["", *sorted(STRUM_RHYTHMS.keys()), *sorted(ARPEGGIO_PATTERNS.keys())]
_VOICING_CHOICES = ["", *VOICINGS]

NOTE_LIST_HEADERS = ["bar", "beat", "pitch", "duration", "velocity", "scale_deg"]
SECTION_HEADERS = ["start_bar", "end_bar", "voicing", "rhythm", "mode", "seed"]
HARMONY_HEADERS = ["start_bar", "end_bar", "preset", "intervals"]

# Scale-degree grid covers 2 octaves = 14 rows for a 7-note scale, fewer
# for pentatonic etc. Each row label is "1", "2", ..., "7", "1'", "2'", ...
# (with primes denoting the higher octave).
_GRID_LEVELS = {0: 0, 1: 45, 2: 90, 3: 115}     # cell value → velocity


def _level_for_velocity(vel: int) -> int:
    """Bucket a 1..127 velocity into the 4-level grid representation."""
    if vel <= 0:
        return 0
    if vel <= 55:
        return 1
    if vel <= 100:
        return 2
    return 3


def _pitch_to_scale_degree(pitch: int, key: str, scale_name: str) -> Optional[int]:
    """MIDI pitch → 1-indexed scale degree over multi-octave space.
    Returns None for chromatic pitches that don't fall on a scale tone."""
    intervals = SCALES.get(scale_name, SCALES["major"])
    root_pc = note_name_to_midi(key, 0) % 12
    relative_pc = (pitch - root_pc) % 12
    for idx, iv in enumerate(intervals):
        if iv == relative_pc:
            # Degree number in the multi-octave space. Choose octave so the
            # degree corresponds to the pitch.
            base = note_name_to_midi(key, 4) + iv
            octave_offset = (pitch - base) // 12
            return idx + 1 + octave_offset * len(intervals)
    return None


def _scale_degree_to_pitch(degree: int, key: str, scale_name: str,
                            base_octave: int = 4) -> int:
    """1-indexed multi-octave degree → MIDI pitch. degree=1 = key tonic at
    base_octave; degree=8 = next octave's tonic, etc."""
    intervals = SCALES.get(scale_name, SCALES["major"])
    if not intervals:
        return note_name_to_midi(key, base_octave)
    d = max(1, degree) - 1
    octave_offset, inner = divmod(d, len(intervals))
    return note_name_to_midi(key, base_octave) + intervals[inner] + 12 * octave_offset


# ---------- Plan ↔ Dataframe converters --------------------------------

def _plan_to_note_rows(plan: mp.MelodyPlan) -> list[list]:
    return [
        [n.bar, round(n.beat, 4), n.pitch,
         round(n.duration, 4), n.velocity,
         n.scale_degree if n.scale_degree is not None else ""]
        for n in sorted(plan.notes, key=lambda n: (n.bar, n.beat))
    ]


def _note_rows_to_plan(rows, plan: mp.MelodyPlan) -> mp.MelodyPlan:
    """Parse the Note-list dataframe back into the plan's note list."""
    import pandas as pd
    if isinstance(rows, pd.DataFrame):
        rows = rows.values.tolist()
    new_notes: list[mp.MelodyNote] = []
    for row in (rows or []):
        if not row or row[0] in (None, ""):
            continue
        try:
            bar = int(row[0])
            beat = float(row[1])
            pitch = int(row[2])
            duration = float(row[3])
            velocity = int(row[4])
        except (TypeError, ValueError):
            continue
        sd_raw = row[5] if len(row) > 5 else ""
        try:
            sd = int(sd_raw) if sd_raw not in (None, "", 0) else None
        except (TypeError, ValueError):
            sd = None
        new_notes.append(mp.MelodyNote(
            bar=bar, beat=beat, pitch=pitch,
            duration=duration, velocity=velocity, scale_degree=sd,
        ))
    return mp.MelodyPlan(
        bars=plan.bars, time_signature=plan.time_signature,
        key=plan.key, scale=plan.scale, tempo=plan.tempo,
        notes=new_notes,
        section_overrides=list(plan.section_overrides),
        harmonies=list(plan.harmonies),
        generation_seed=plan.generation_seed,
    )


def _plan_to_degree_grid(plan: mp.MelodyPlan) -> tuple[list[list], list[str]]:
    """Build the scale-degree grid: rows × (1 label col + N step cols)."""
    intervals = SCALES.get(plan.scale, SCALES["major"])
    deg_count = len(intervals)
    # Two octaves: degrees 1..2*deg_count
    row_labels = (
        [str(d) for d in range(1, deg_count + 1)]
        + [f"{d}'" for d in range(1, deg_count + 1)]
    )
    subdivs = grid_subdivs_for_meter(plan.time_signature)
    info = mp.meter_info(plan.time_signature)
    steps_per_bar = info["beats_per_bar"] * subdivs
    total_steps = steps_per_bar * plan.bars
    step_labels = grid_step_labels(plan.time_signature, plan.bars, steps_per_bar)
    headers = ["Degree", *step_labels]
    # Initialize empty grid
    grid: list[list] = [[label] + [0] * total_steps for label in row_labels]
    # Place each note
    for n in plan.notes:
        deg = n.scale_degree
        if deg is None:
            deg = _pitch_to_scale_degree(n.pitch, plan.key, plan.scale)
            if deg is None:
                continue  # chromatic, not representable in scale-degree grid
        if deg < 1 or deg > 2 * deg_count:
            continue
        row_idx = deg - 1
        # Step within bar from beat
        step_in_bar = int(round(n.beat * subdivs))
        step_idx = n.bar * steps_per_bar + step_in_bar
        if 0 <= step_idx < total_steps:
            grid[row_idx][1 + step_idx] = _level_for_velocity(n.velocity)
    return grid, headers


def _degree_grid_to_plan(rows, plan: mp.MelodyPlan) -> mp.MelodyPlan:
    """Inverse: convert the scale-degree grid back to plan notes. Notes
    placed by the user in the grid REPLACE the previous in-scale notes;
    chromatic notes (which the grid can't represent) are PRESERVED so
    the user doesn't lose them when toggling views."""
    import pandas as pd
    if isinstance(rows, pd.DataFrame):
        rows = rows.values.tolist()
    intervals = SCALES.get(plan.scale, SCALES["major"])
    deg_count = len(intervals)
    subdivs = grid_subdivs_for_meter(plan.time_signature)
    info = mp.meter_info(plan.time_signature)
    steps_per_bar = info["beats_per_bar"] * subdivs

    # Preserve chromatic notes that the grid can't render
    preserved = [
        n for n in plan.notes
        if (n.scale_degree is None
            and _pitch_to_scale_degree(n.pitch, plan.key, plan.scale) is None)
    ]
    new_notes: list[mp.MelodyNote] = list(preserved)
    for row in (rows or []):
        if not row or row[0] in (None, ""):
            continue
        try:
            deg_label = str(row[0])
            # Strip prime marker; second-octave rows have the "'" suffix
            primes = deg_label.count("'")
            base_str = deg_label.replace("'", "")
            base_deg = int(base_str)
            degree = base_deg + primes * deg_count
        except (TypeError, ValueError):
            continue
        for step_idx, cell in enumerate(row[1:]):
            try:
                level = int(float(cell)) if cell not in (None, "") else 0
            except (TypeError, ValueError):
                level = 0
            if level <= 0:
                continue
            level = max(0, min(3, level))
            velocity = _GRID_LEVELS[level]
            bar = step_idx // steps_per_bar
            sub_in_bar = step_idx % steps_per_bar
            beat = sub_in_bar / subdivs
            pitch = _scale_degree_to_pitch(degree, plan.key, plan.scale)
            new_notes.append(mp.MelodyNote(
                bar=bar, beat=beat, pitch=pitch,
                duration=1.0 / subdivs, velocity=velocity,
                scale_degree=degree,
            ))
    return mp.MelodyPlan(
        bars=plan.bars, time_signature=plan.time_signature,
        key=plan.key, scale=plan.scale, tempo=plan.tempo,
        notes=new_notes,
        section_overrides=list(plan.section_overrides),
        harmonies=list(plan.harmonies),
        generation_seed=plan.generation_seed,
    )


def _plan_to_pianoroll(plan: mp.MelodyPlan) -> tuple[list[list], list[str]]:
    """Chromatic piano-roll: 24 rows centred on the key tonic at octave 4."""
    tonic = note_name_to_midi(plan.key, 4)
    note_names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
    # Window: tonic-12 .. tonic+11 (2 octaves)
    rows_pitches = list(range(tonic - 12, tonic + 12))
    row_labels = [f"{note_names[p % 12]}{(p // 12) - 1}" for p in rows_pitches]
    subdivs = grid_subdivs_for_meter(plan.time_signature)
    info = mp.meter_info(plan.time_signature)
    steps_per_bar = info["beats_per_bar"] * subdivs
    total_steps = steps_per_bar * plan.bars
    step_labels = grid_step_labels(plan.time_signature, plan.bars, steps_per_bar)
    headers = ["Pitch", *step_labels]
    grid: list[list] = [[label] + [0] * total_steps for label in row_labels]
    for n in plan.notes:
        if n.pitch not in rows_pitches:
            continue
        row_idx = rows_pitches.index(n.pitch)
        step_in_bar = int(round(n.beat * subdivs))
        step_idx = n.bar * steps_per_bar + step_in_bar
        if 0 <= step_idx < total_steps:
            grid[row_idx][1 + step_idx] = _level_for_velocity(n.velocity)
    return grid, headers


def _pianoroll_to_plan(rows, plan: mp.MelodyPlan) -> mp.MelodyPlan:
    import pandas as pd
    if isinstance(rows, pd.DataFrame):
        rows = rows.values.tolist()
    tonic = note_name_to_midi(plan.key, 4)
    note_names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
    subdivs = grid_subdivs_for_meter(plan.time_signature)
    info = mp.meter_info(plan.time_signature)
    steps_per_bar = info["beats_per_bar"] * subdivs

    # Preserve notes outside the chromatic window so toggling views never
    # silently loses notes that live above/below ±1 octave from tonic.
    rows_pitches = list(range(tonic - 12, tonic + 12))
    preserved = [n for n in plan.notes if n.pitch not in rows_pitches]
    new_notes: list[mp.MelodyNote] = list(preserved)
    for row in (rows or []):
        if not row or row[0] in (None, ""):
            continue
        label = str(row[0])
        # Parse "C4" / "F#5" / "A#-1" → pitch
        try:
            i = 0
            while i < len(label) and not label[i].isdigit() and label[i] != "-":
                i += 1
            note = label[:i]
            octv = int(label[i:])
            pitch = note_names.index(note) + 12 * (octv + 1)
        except (ValueError, IndexError):
            continue
        for step_idx, cell in enumerate(row[1:]):
            try:
                level = int(float(cell)) if cell not in (None, "") else 0
            except (TypeError, ValueError):
                level = 0
            if level <= 0:
                continue
            level = max(0, min(3, level))
            bar = step_idx // steps_per_bar
            sub_in_bar = step_idx % steps_per_bar
            beat = sub_in_bar / subdivs
            new_notes.append(mp.MelodyNote(
                bar=bar, beat=beat, pitch=pitch,
                duration=1.0 / subdivs, velocity=_GRID_LEVELS[level],
                scale_degree=None,
            ))
    return mp.MelodyPlan(
        bars=plan.bars, time_signature=plan.time_signature,
        key=plan.key, scale=plan.scale, tempo=plan.tempo,
        notes=new_notes,
        section_overrides=list(plan.section_overrides),
        harmonies=list(plan.harmonies),
        generation_seed=plan.generation_seed,
    )


# ---------- SectionOverride / HarmonyTag rows --------------------------

def _override_to_dict(o: mp.SectionOverride) -> dict:
    return {
        "start_bar": o.start_bar, "end_bar": o.end_bar,
        "voicing": o.voicing or "", "rhythm": o.rhythm or "",
        "mode": o.mode, "seed": o.seed,
        "cadence": o.cadence or "",
        "lick": o.lick or "",
        "tension_op": o.tension_op or "",
    }


def _dict_to_override(d: dict) -> mp.SectionOverride:
    """Build a SectionOverride from the row's state-dict. Empty strings
    coalesce to None for voicing/rhythm/cadence/lick/tension_op; mode
    falls back to 'stack'."""
    try:
        start_bar = int(d.get("start_bar") or 0)
        end_bar = int(d.get("end_bar") or 1)
    except (TypeError, ValueError):
        start_bar, end_bar = 0, 1
    voicing = (d.get("voicing") or None)
    rhythm = (d.get("rhythm") or None)
    mode = d.get("mode") or "stack"
    if mode not in SECTION_MODES:
        mode = "stack"
    seed_raw = d.get("seed")
    try:
        seed = int(seed_raw) if seed_raw not in (None, "", 0) else None
    except (TypeError, ValueError):
        seed = None
    return mp.SectionOverride(
        start_bar=start_bar, end_bar=end_bar,
        voicing=voicing or None, rhythm=rhythm or None,
        mode=mode, seed=seed,
        cadence=(d.get("cadence") or None),
        lick=(d.get("lick") or None),
        tension_op=(d.get("tension_op") or None),
    )


def _harmony_to_dict(h: mp.HarmonyTag) -> dict:
    return {
        "start_bar": h.start_bar, "end_bar": h.end_bar,
        "preset": h.preset,
        "intervals": ",".join(str(x) for x in (h.intervals or [])),
        "harmony_rule": h.harmony_rule or "",
    }


def _dict_to_harmony(d: dict) -> mp.HarmonyTag:
    try:
        start_bar = int(d.get("start_bar") or 0)
        end_bar = int(d.get("end_bar") or 1)
    except (TypeError, ValueError):
        start_bar, end_bar = 0, 1
    preset = d.get("preset") or "queen"
    intervals_raw = d.get("intervals") or ""
    intervals: Optional[list[int]] = None
    if intervals_raw:
        try:
            intervals = [
                int(x.strip()) for x in str(intervals_raw).split(",")
                if x.strip()
            ]
        except ValueError:
            intervals = None
    return mp.HarmonyTag(
        start_bar=start_bar, end_bar=end_bar,
        preset=preset, intervals=intervals,
        harmony_rule=(d.get("harmony_rule") or None),
    )


def _default_override_dict() -> dict:
    return {
        "start_bar": 0, "end_bar": 1,
        "voicing": "", "rhythm": "", "mode": "stack", "seed": None,
        "cadence": "", "lick": "", "tension_op": "",
    }


def _default_harmony_dict() -> dict:
    return {
        "start_bar": 0, "end_bar": 1,
        "preset": "queen", "intervals": "",
        "harmony_rule": "",
    }


def _default_rhythm_override_row(start_bar: int = 0) -> dict:
    """Default shape for a new "Per-bar rhythm overrides" row."""
    return {
        "start_bar": int(start_bar),
        "end_bar":   int(start_bar),
        "label":     "",
        "chord_rhythm_h1": "",
        "chord_rhythm_h2": "",
        "bass_pattern":    "",
    }


def _render_rhythm_override_row(
    idx: int, ov: dict,
    override_state: gr.State,
    reorder_signal: gr.Number,
) -> None:
    """One row in the "Per-bar rhythm overrides" accordion.

    Mirrors :func:`_render_override_row` (Melody Studio section
    overrides) — same stable-key trick keeps the dropdowns alive
    across ``@gr.render`` rebuilds and lets the user edit fields
    without the parent re-rendering mid-interaction.
    """
    k = lambda field: f"rhythm_ov_{idx}_{field}"

    def _set(state, **kv):
        out = list(state)
        out[idx] = {**out[idx], **kv}
        return out

    def _remove(state):
        return [r for i, r in enumerate(state) if i != idx]

    def _move(state, direction: int):
        out = list(state)
        new_idx = idx + direction
        if 0 <= new_idx < len(out):
            out[idx], out[new_idx] = out[new_idx], out[idx]
        return out

    with gr.Group():
        with gr.Row():
            gr.Markdown(f"**{idx + 1}**")
            start_in = gr.Number(
                value=int(ov.get("start_bar", 0)), precision=0,
                label="Start bar", key=k("start"), scale=1,
            )
            end_in = gr.Number(
                value=int(ov.get("end_bar", 0)), precision=0,
                label="End bar", key=k("end"), scale=1,
            )
            label_in = gr.Textbox(
                value=str(ov.get("label", "")),
                label="Label", placeholder="Verse / Chorus / Fill",
                key=k("label"), scale=2,
            )
            up_btn = gr.Button("↑", size="sm", scale=0, key=k("up"))
            down_btn = gr.Button("↓", size="sm", scale=0, key=k("down"))
            remove_btn = gr.Button(
                "⛌", size="sm", variant="stop", scale=0, key=k("remove"),
            )

        with gr.Row():
            chord_h1_dd = gr.Dropdown(
                choices=["", *CHORD_RHYTHMS],
                value=ov.get("chord_rhythm_h1", ""),
                label="Chord rhythm — half 1 (beats 1-2)",
                allow_custom_value=True,
                key=k("chord_h1"), scale=2,
            )
            chord_h2_dd = gr.Dropdown(
                choices=["", *CHORD_RHYTHMS],
                value=ov.get("chord_rhythm_h2", ""),
                label="Chord rhythm — half 2 (beats 3-4, blank = same as half 1)",
                allow_custom_value=True,
                key=k("chord_h2"), scale=2,
            )
            bass_dd = gr.Dropdown(
                choices=["", *BASS_PATTERNS],
                value=ov.get("bass_pattern", ""),
                label="Bass pattern (whole bar)",
                allow_custom_value=True,
                key=k("bass"), scale=2,
            )

        start_in.change(lambda s, v: _set(s, start_bar=int(v or 0)),
                        [override_state, start_in], override_state)
        end_in.change(lambda s, v: _set(s, end_bar=int(v or 0)),
                      [override_state, end_in], override_state)
        label_in.change(lambda s, v: _set(s, label=str(v or "")),
                        [override_state, label_in], override_state)
        chord_h1_dd.change(lambda s, v: _set(s, chord_rhythm_h1=str(v or "")),
                           [override_state, chord_h1_dd], override_state)
        chord_h2_dd.change(lambda s, v: _set(s, chord_rhythm_h2=str(v or "")),
                           [override_state, chord_h2_dd], override_state)
        bass_dd.change(lambda s, v: _set(s, bass_pattern=str(v or "")),
                       [override_state, bass_dd], override_state)

        # Reorder + remove trigger a re-render via the signal. Without
        # the bumped signal, @gr.render would only fire on field-edit
        # changes (which we suppress via explicit triggers=...).
        up_btn.click(lambda s: _move(s, -1), [override_state], [override_state])
        down_btn.click(lambda s: _move(s, +1), [override_state], [override_state])
        up_btn.click(lambda v: (v or 0) + 1, [reorder_signal], [reorder_signal])
        down_btn.click(lambda v: (v or 0) + 1, [reorder_signal], [reorder_signal])
        remove_btn.click(_remove, [override_state], [override_state])
        remove_btn.click(lambda v: (v or 0) + 1, [reorder_signal], [reorder_signal])


def _render_override_row(idx: int, ov: dict, override_state: gr.State) -> None:
    """Render one Section Override row. Stable per-row keys keep the
    dropdowns alive across @gr.render rebuilds — same fix as the Extras
    row pattern. Each widget's .change writes back through the _set
    closure; the ⛌ button removes the row by index."""
    k = lambda field: f"override_{idx}_{field}"

    def _set(state, **kv):
        out = list(state)
        out[idx] = {**out[idx], **kv}
        return out

    def _remove(state):
        return [r for i, r in enumerate(state) if i != idx]

    with gr.Group():
        with gr.Row():
            gr.Markdown(f"**Override {idx + 1}**")
            start_in = gr.Number(
                value=int(ov.get("start_bar", 0)), precision=0,
                label="Start bar", key=k("start"), scale=1,
            )
            end_in = gr.Number(
                value=int(ov.get("end_bar", 1)), precision=0,
                label="End bar", key=k("end"), scale=1,
            )
            remove_btn = gr.Button(
                "⛌", size="sm", variant="stop", scale=0, key=k("remove"),
            )

        with gr.Row():
            voicing_dd = gr.Dropdown(
                choices=["", *VOICINGS],
                value=ov.get("voicing", ""),
                label="Voicing (type to filter)",
                allow_custom_value=True,
                key=k("voicing"), scale=1,
            )
            rhythm_dd = gr.Dropdown(
                choices=_RHYTHM_CHOICES,
                value=ov.get("rhythm", ""),
                label="Rhythm",
                allow_custom_value=True,
                key=k("rhythm"), scale=1,
            )
            mode_dd = gr.Dropdown(
                choices=SECTION_MODES,
                value=ov.get("mode", "stack"),
                label="Mode",
                # Match voicing/rhythm dropdowns above — keeps Gradio
                # from rejecting transient values during interaction.
                allow_custom_value=True,
                key=k("mode"), scale=1,
            )
            seed_in = gr.Number(
                value=ov.get("seed"), precision=0, minimum=0,
                label="Seed", key=k("seed"), scale=1,
            )

        with gr.Row():
            cadence_dd = gr.Dropdown(
                choices=["", *sorted(CADENCES.keys())],
                value=ov.get("cadence", ""),
                label="Cadence (force last note)",
                allow_custom_value=True,
                key=k("cadence"), scale=1,
            )
            lick_dd = gr.Dropdown(
                choices=["", *sorted(MELODIC_LICKS.keys())],
                value=ov.get("lick", ""),
                label="Lick (replaces range)",
                allow_custom_value=True,
                key=k("lick"), scale=1,
            )
            tension_op_dd = gr.Dropdown(
                choices=["", *sorted(TENSION_OPS.keys())],
                value=ov.get("tension_op", ""),
                label="Tension op",
                allow_custom_value=True,
                key=k("tension_op"), scale=1,
            )

        start_in.change(lambda s, v: _set(s, start_bar=int(v or 0)),
                        [override_state, start_in], override_state)
        end_in.change(lambda s, v: _set(s, end_bar=int(v or 0)),
                      [override_state, end_in], override_state)
        voicing_dd.change(lambda s, v: _set(s, voicing=v or ""),
                          [override_state, voicing_dd], override_state)
        rhythm_dd.change(lambda s, v: _set(s, rhythm=v or ""),
                         [override_state, rhythm_dd], override_state)
        mode_dd.change(lambda s, v: _set(s, mode=v or "stack"),
                       [override_state, mode_dd], override_state)
        seed_in.change(lambda s, v: _set(s, seed=int(v) if v else None),
                       [override_state, seed_in], override_state)
        cadence_dd.change(lambda s, v: _set(s, cadence=v or ""),
                          [override_state, cadence_dd], override_state)
        lick_dd.change(lambda s, v: _set(s, lick=v or ""),
                       [override_state, lick_dd], override_state)
        tension_op_dd.change(lambda s, v: _set(s, tension_op=v or ""),
                             [override_state, tension_op_dd], override_state)
        remove_btn.click(_remove, [override_state], override_state)


def _render_harmony_row(idx: int, hm: dict, harmony_state: gr.State) -> None:
    """Render one Harmony row. Same row-stable-key pattern as overrides."""
    k = lambda field: f"harmony_{idx}_{field}"

    def _set(state, **kv):
        out = list(state)
        out[idx] = {**out[idx], **kv}
        return out

    def _remove(state):
        return [r for i, r in enumerate(state) if i != idx]

    with gr.Group():
        with gr.Row():
            gr.Markdown(f"**Harmony {idx + 1}**")
            start_in = gr.Number(
                value=int(hm.get("start_bar", 0)), precision=0,
                label="Start bar", key=k("start"), scale=1,
            )
            end_in = gr.Number(
                value=int(hm.get("end_bar", 1)), precision=0,
                label="End bar", key=k("end"), scale=1,
            )
            preset_dd = gr.Dropdown(
                choices=HARMONY_PRESETS,
                value=hm.get("preset", "queen"),
                label="Preset (type to filter)",
                # allow_custom_value so Gradio doesn't reject the
                # value at preprocess time mid-interaction — same fix
                # the override voicing/rhythm dropdowns use, and the
                # one that closed the earlier audit-dropdown bug.
                allow_custom_value=True,
                key=k("preset"), scale=1,
            )
            remove_btn = gr.Button(
                "⛌", size="sm", variant="stop", scale=0, key=k("remove"),
            )

        intervals_in = gr.Textbox(
            value=hm.get("intervals", ""),
            label="Intervals (optional, e.g. '1,2,4')",
            placeholder="Blank = preset's defaults",
            key=k("intervals"),
        )

        with gr.Row():
            harmony_rule_dd = gr.Dropdown(
                choices=["", *sorted(HARMONY_OPS.keys())],
                value=hm.get("harmony_rule", ""),
                label="Voice-leading rule",
                allow_custom_value=True,
                key=k("harmony_rule"), scale=1,
            )

        start_in.change(lambda s, v: _set(s, start_bar=int(v or 0)),
                        [harmony_state, start_in], harmony_state)
        end_in.change(lambda s, v: _set(s, end_bar=int(v or 0)),
                      [harmony_state, end_in], harmony_state)
        preset_dd.change(lambda s, v: _set(s, preset=v or "queen"),
                         [harmony_state, preset_dd], harmony_state)
        intervals_in.change(lambda s, v: _set(s, intervals=v or ""),
                            [harmony_state, intervals_in], harmony_state)
        harmony_rule_dd.change(lambda s, v: _set(s, harmony_rule=v or ""),
                               [harmony_state, harmony_rule_dd], harmony_state)
        remove_btn.click(_remove, [harmony_state], harmony_state)


# ---------------------------------------------------------------------------
# Studio section timeline — visual bands for overrides + harmonies
# ---------------------------------------------------------------------------

def _section_timeline_html(
    overrides: list[dict] | None,
    harmonies: list[dict] | None,
    bars: int,
) -> str:
    """Return a Markdown string (with embedded HTML) showing horizontal
    coloured bands for each section override + harmony tag across the
    plan's bar count. Lightweight, no JS — just inline-styled <div>s.

    Empty plans render a one-line hint so the strip is never blank
    when the user hasn't tagged anything yet.
    """
    bars = max(1, int(bars or 8))
    overrides = list(overrides or [])
    harmonies = list(harmonies or [])
    if not overrides and not harmonies:
        return (
            "<div style='margin: 4px 0; color: var(--body-text-color-subdued, "
            "#888); font-size: 0.85em;'>"
            "<em>No sections or harmonies yet. Add them below to see bar "
            "ranges highlighted here.</em></div>"
        )

    def _label(ov: dict) -> str:
        parts = []
        for key in ("voicing", "rhythm", "cadence", "lick", "tension_op"):
            v = ov.get(key)
            if v:
                parts.append(f"{key}={v}")
        return ", ".join(parts) or (ov.get("mode") or "section")

    def _band(start_bar: int, end_bar: int, label: str, color: str,
              row_label: str) -> str:
        start_pct = max(0.0, min(100.0, (start_bar / bars) * 100.0))
        end_pct = max(0.0, min(100.0, (end_bar / bars) * 100.0))
        width = max(0.5, end_pct - start_pct)
        return (
            f"<div style='display: flex; align-items: center; "
            f"margin: 2px 0; font-size: 0.78em;'>"
            f"<span style='display: inline-block; width: 70px; "
            f"color: var(--body-text-color-subdued, #888);'>{row_label}</span>"
            f"<div style='flex: 1; position: relative; height: 14px; "
            f"background: var(--background-fill-secondary, #f0f0f0); "
            f"border-radius: 3px;'>"
            f"<div title='{label}' style='position: absolute; "
            f"left: {start_pct:.1f}%; width: {width:.1f}%; height: 100%; "
            f"background: {color}; border-radius: 3px; padding: 0 4px; "
            f"color: white; overflow: hidden; white-space: nowrap; "
            f"text-overflow: ellipsis; line-height: 14px;'>{label}</div>"
            f"</div></div>"
        )

    parts = [
        f"<div style='margin: 8px 0;'>"
        f"<div style='font-size: 0.8em; color: var(--body-text-color-subdued, "
        f"#888); margin-bottom: 4px;'>Bars 1 → {bars}</div>"
    ]
    # Sections first (orange), then harmonies (teal). Each gets its own row.
    for i, ov in enumerate(overrides):
        parts.append(_band(
            int(ov.get("start_bar", 0)),
            int(ov.get("end_bar", 1)),
            _label(ov), "#e07b3c",
            f"Section {i + 1}",
        ))
    for i, hm in enumerate(harmonies):
        label = hm.get("preset") or "queen"
        if hm.get("intervals"):
            label += f" ({hm['intervals']})"
        if hm.get("harmony_rule"):
            label += f" · {hm['harmony_rule']}"
        parts.append(_band(
            int(hm.get("start_bar", 0)),
            int(hm.get("end_bar", 1)),
            label, "#2e9b8f",
            f"Harmony {i + 1}",
        ))
    parts.append("</div>")
    return "".join(parts)


# ---------------------------------------------------------------------------
# Per-instrument progression panel — one textbox + lock per instrument
# ---------------------------------------------------------------------------

def _render_instrument_progression_row(
    *, label: str, state: gr.State, master_in: gr.Textbox,
    key_prefix: str,
) -> None:
    """Render one row of the per-instrument progression panel.

    Layout: ``[label] [🔒/🔓 lock toggle] [progression textbox]``.
    Locked = textbox value mirrors the master, greyed out. Unlocked
    = textbox is editable; subsequent master changes leave this row
    alone (until the user locks it again).
    """

    def _toggle_lock(s: dict, master_text: str) -> dict:
        s = dict(s or {})
        was_locked = bool(s.get("locked", True))
        new_locked = not was_locked
        # Closing the lock re-syncs from the master, so the field
        # immediately shows what the user is now following.
        if new_locked:
            s["text"] = master_text
        s["locked"] = new_locked
        return s

    def _set_text(s: dict, value: str) -> dict:
        s = dict(s or {})
        # Editing the textbox implicitly unlocks — the user is
        # asserting "I want this one specifically."
        s["text"] = value or ""
        s["locked"] = False
        return s

    with gr.Row():
        gr.Markdown(f"**{label}**")

        @gr.render(inputs=[state, master_in])
        def _row(st: dict, master_text: str):
            st = dict(st or {})
            locked = bool(st.get("locked", True))
            shown = (master_text if locked else st.get("text", "")) or ""
            with gr.Row():
                lock_btn = gr.Button(
                    "🔒" if locked else "🔓",
                    size="sm", scale=0,
                    key=f"{key_prefix}_lock",
                )
                tb = gr.Textbox(
                    value=shown,
                    show_label=False,
                    interactive=not locked,
                    placeholder=("Locked to master" if locked
                                 else "Customize this instrument's progression"),
                    scale=4,
                    key=f"{key_prefix}_text",
                )
                lock_btn.click(
                    _toggle_lock,
                    [state, master_in],
                    state,
                )
                tb.change(
                    _set_text,
                    [state, tb],
                    state,
                )


def _render_extras_progression_row(
    idx: int, tr: dict, master_text: str,
    extras_state: gr.State, master_in: gr.Textbox,
) -> None:
    """One per-instrument progression row for an Extra track.

    Mirrors the fixed-instrument row shape (label + lock + textbox)
    but writes back into the indexed entry of ``extras_state``. Each
    extra carries its own ``progression`` (text) and
    ``progression_locked`` (bool) — the same shape compose_midi's
    ``_resolve_instrument_progression`` expects.
    """
    locked = bool(tr.get("progression_locked", True))
    name = tr.get("track_name") or (tr.get("type") or "extra").title()
    text = tr.get("progression", "") or ""
    shown = master_text if locked else text

    def _toggle(state: list, master_text_now: str) -> list:
        out = list(state)
        e = dict(out[idx])
        was_locked = bool(e.get("progression_locked", True))
        new_locked = not was_locked
        if new_locked:
            e["progression"] = master_text_now
        e["progression_locked"] = new_locked
        out[idx] = e
        return out

    def _set_text(state: list, value: str) -> list:
        out = list(state)
        e = dict(out[idx])
        e["progression"] = value or ""
        e["progression_locked"] = False
        out[idx] = e
        return out

    with gr.Row():
        gr.Markdown(f"**{name}** &nbsp; `{tr.get('type', 'extra')}`")
        lock_btn = gr.Button(
            "🔒" if locked else "🔓",
            size="sm", scale=0,
            key=f"prog_extra_{idx}_lock",
        )
        tb = gr.Textbox(
            value=shown,
            show_label=False,
            interactive=not locked,
            placeholder=("Locked to master" if locked
                         else "Customize this extra's progression"),
            scale=4,
            key=f"prog_extra_{idx}_text",
        )
        lock_btn.click(_toggle, [extras_state, master_in], extras_state)
        tb.change(_set_text, [extras_state, tb], extras_state)


# ---------- Top-level Melody Studio handlers ---------------------------

def melody_load_from_compose() -> mp.MelodyPlan:
    """Convert the most-recent Compose result's Melody track into an
    editable plan. Raises if nothing has been composed yet."""
    midi = _state.get("last_midi")
    ctx = _state.get("audit_context") or {}
    if midi is None:
        raise gr.Error("Click **Compose** in the MIDI Compose tab first — "
                       "there's no melody to load yet.")
    mel_track = next(
        (t for t in midi.tracks
         if not t.is_drum and "melody" in t.name.lower()),
        None,
    )
    if mel_track is None:
        raise gr.Error("The latest Compose has no Melody track. Enable "
                       "Melody in the Compose tab and re-run.")
    bars = int(_state.get("last_compose_meta", {}).get("bars", 8))
    plan = mp.melody_plan_from_track(
        mel_track, key=ctx.get("key", "C"),
        scale=ctx.get("scale", "major"),
        time_signature=midi.time_signature, tempo=midi.tempo,
        bars=bars,
    )
    _state["melody_plan"] = plan
    # Stash the non-melody tracks as the accompaniment "bed" for preview.
    _state["melody_bed_tracks"] = [
        t for t in midi.tracks
        if not (("melody" in (t.name or "").lower()) and not t.is_drum)
    ]
    return plan


def melody_load_from_block(block_name: str) -> mp.MelodyPlan:
    """Load a saved block's melody track into a fresh plan. If a sibling
    `{block}_melody.yaml` already exists, restore the saved plan instead."""
    if not block_name:
        raise gr.Error("Pick a saved block first.")
    yaml_path = block_store.BLOCKS_DIR / f"{block_name}_melody.yaml"
    if yaml_path.exists():
        plan = mp.from_yaml(yaml_path)
        _state["melody_plan"] = plan
        return plan
    try:
        pm, meta = block_store.load_block(block_name)
    except FileNotFoundError as e:
        raise gr.Error(str(e))
    # Find the melody-like instrument in the block
    from src.daw_integration.generic.midi_export import Track, NoteEvent
    mel = next(
        (i for i in pm.instruments
         if not i.is_drum and "melody" in (i.name or "").lower()),
        None,
    )
    if mel is None:
        # Fall back to the first non-drum, polyphonic-on-single-note track
        mel = next((i for i in pm.instruments if not i.is_drum), None)
    if mel is None:
        raise gr.Error(f"Block {block_name!r} has no melody track.")
    track = Track(name="Melody", program=mel.program)
    for n in mel.notes:
        track.notes.append(NoteEvent(
            pitch=int(n.pitch), start=float(n.start),
            end=float(n.end), velocity=int(n.velocity),
        ))
    plan = mp.melody_plan_from_track(
        track, key="C", scale="major",
        time_signature=tuple(meta.get("time_signature", [4, 4])),
        tempo=float(meta.get("tempo", 120)),
        bars=int(meta.get("bars", 8)),
    )
    _state["melody_plan"] = plan
    # Stash bed = block's non-melody instruments (PrettyMIDI → Track list)
    _state["melody_bed_tracks"] = mp.pretty_midi_to_tracks(pm, skip_melody=True)
    return plan


def melody_get_blocks_dropdown() -> gr.update:
    """Refresh the saved-block dropdown choices."""
    blocks = block_store.list_blocks()
    names = [b["name"] for b in blocks if b.get("name")]
    return gr.update(choices=names, value=(names[0] if names else None))


def melody_render_views(plan: Optional[mp.MelodyPlan]):
    """Build all three editor views + header + override/harmony state
    lists for the given plan.

    Returns ``(header_text, note_rows, degree_df_value, pianoroll_df_value,
    override_state_list, harmony_state_list)`` — the last two are dict
    lists driving the @gr.render row UIs (not Dataframes anymore).
    """
    if plan is None:
        return (
            "_No plan loaded._",
            [], {"headers": ["Degree"], "data": []},
            {"headers": ["Pitch"], "data": []},
            [], [],
        )
    header = (f"**{plan.key} {plan.scale}** | "
              f"{plan.bars} bars | "
              f"{plan.time_signature[0]}/{plan.time_signature[1]} | "
              f"{plan.tempo:.0f} BPM | "
              f"{len(plan.notes)} notes")
    note_rows = _plan_to_note_rows(plan)
    deg_rows, deg_headers = _plan_to_degree_grid(plan)
    pr_rows, pr_headers = _plan_to_pianoroll(plan)
    override_dicts = [_override_to_dict(o) for o in plan.section_overrides]
    harmony_dicts = [_harmony_to_dict(h) for h in plan.harmonies]
    return (
        header,
        note_rows,
        {"headers": deg_headers, "data": deg_rows},
        {"headers": pr_headers, "data": pr_rows},
        override_dicts,
        harmony_dicts,
    )


def melody_regenerate(plan: Optional[mp.MelodyPlan],
                      bar_range: str, seed: int, style: str):
    """Re-roll notes per the bar range. ``bar_range`` accepts ``""`` (full
    regen), or ``"a:b"``. Returns updated views."""
    if plan is None:
        raise gr.Error("Load a melody first.")
    progression_text = (_state.get("audit_context") or {}).get("progression")
    progression = progression_text  # already a parsed plan
    seed_val = int(seed) if seed else None
    if bar_range.strip():
        try:
            a_str, b_str = bar_range.split(":")
            start = max(0, int(a_str))
            end = min(plan.bars, int(b_str))
        except (ValueError, AttributeError):
            raise gr.Error("Bar range must be 'start:end' (e.g. '0:4').")
    else:
        start, end = 0, plan.bars
    new_plan = mp.regenerate_bars(
        plan, start_bar=start, end_bar=end,
        melody_style=style, seed=seed_val, progression=progression,
    )
    _state["melody_plan"] = new_plan
    return new_plan


def melody_preview(plan: Optional[mp.MelodyPlan], with_bed: bool = False):
    """Render plan → wav and return file path. Uses MidiExporter +
    pretty_midi.synthesize for a quick sine preview.

    When ``with_bed`` is True and a bed has been pinned via the load
    handlers (``_state["melody_bed_tracks"]``), the block's non-melody
    instruments are layered under the rendered melody + harmony so
    Stephen can hear how the melody sits with chords/bass/drums.
    """
    if plan is None:
        raise gr.Error("Load a melody first.")
    progression = (_state.get("audit_context") or {}).get("progression") or ["I"]
    mel_track, harm_track = mp.render_melody_plan(plan, progression=progression)
    # Wrap into a MidiExporter for synthesize
    exporter = MidiExporter(tempo=plan.tempo, time_signature=plan.time_signature)
    exporter.tracks.append(mel_track)
    if harm_track and harm_track.notes:
        exporter.tracks.append(harm_track)
    if with_bed:
        for bed in _state.get("melody_bed_tracks") or []:
            exporter.tracks.append(bed)
    audio, sr = exporter.synthesize(sample_rate=44100)
    wav_path = OUTPUT_DIR / "melody_studio_preview.wav"
    sf.write(str(wav_path), audio, sr)
    del audio
    return str(wav_path)


def melody_save_plan(plan: Optional[mp.MelodyPlan], save_name: str):
    """Sidecar-only save: writes ``{name}_melody.yaml`` next to an
    existing block. Use this when you're attaching an edited melody to
    a block you already saved from MIDI Compose. For the more common
    case of creating a brand-new block from the Studio output, use
    :func:`melody_save_as_block`."""
    if plan is None:
        raise gr.Error("Load a melody first.")
    if not save_name or not save_name.strip():
        raise gr.Error("Pick a name for the saved plan (block name).")
    save_name = save_name.strip()
    yaml_path = block_store.BLOCKS_DIR / f"{save_name}_melody.yaml"
    mp.to_yaml(plan, yaml_path)
    return f"Saved sidecar → {yaml_path}"


def melody_save_as_block(plan: Optional[mp.MelodyPlan],
                          save_name: str,
                          library_trigger_val: int):
    """Bake the plan + bed into a complete block on disk.

    Writes ``data/blocks/{name}.mid`` + ``.yaml`` + ``.wav`` (the
    standard block trio) AND a sibling ``{name}_melody.yaml`` so the
    user can come back later and continue editing in Melody Studio.
    Bumps ``library_trigger`` so the Compose Song library refreshes
    without a manual click.

    Returns ``(status_md, bumped_trigger)``.
    """
    if plan is None:
        raise gr.Error("Load a melody first.")
    if not save_name or not save_name.strip():
        raise gr.Error("Pick a name for the new block.")
    save_name = save_name.strip()
    progression = (_state.get("audit_context") or {}).get("progression") or ["I"]
    bed_tracks = _state.get("melody_bed_tracks") or []
    try:
        pm = mp.bake_plan_to_pm(plan, bed_tracks=bed_tracks,
                                 progression=progression)
    except Exception as e:
        raise _logged_error("Bake melody plan to PrettyMIDI", e) from e
    try:
        block_store.save_block(
            name=save_name, pm=pm,
            tempo=plan.tempo, time_signature=plan.time_signature,
            bars=plan.bars, overwrite=True, write_wav=True,
        )
    except Exception as e:
        raise _logged_error("Save block from Studio", e) from e
    # Also persist the editable plan so opening this block in the
    # Studio later restores all section overrides + harmony tags.
    sidecar = block_store.BLOCKS_DIR / f"{save_name}_melody.yaml"
    mp.to_yaml(plan, sidecar)
    bumped = (library_trigger_val or 0) + 1
    return (
        f"💾 **Saved block** `{save_name}` "
        f"({len(pm.instruments)} tracks, {plan.bars} bars). "
        f"Switch to **Compose Song** — it's in the library.",
        bumped,
    )


def melody_apply_note_rows(plan, rows):
    if plan is None:
        return plan
    new_plan = _note_rows_to_plan(rows, plan)
    _state["melody_plan"] = new_plan
    return new_plan


def melody_apply_degree_grid(plan, rows):
    if plan is None:
        return plan
    new_plan = _degree_grid_to_plan(rows, plan)
    _state["melody_plan"] = new_plan
    return new_plan


def melody_apply_pianoroll(plan, rows):
    if plan is None:
        return plan
    new_plan = _pianoroll_to_plan(rows, plan)
    _state["melody_plan"] = new_plan
    return new_plan


def melody_sync_overrides(plan, override_dicts):
    """Sync the override row state into the plan. Called on every change
    of ``override_state`` (which fires for set / add / remove)."""
    if plan is None:
        return plan
    plan.section_overrides = [_dict_to_override(d) for d in (override_dicts or [])]
    _state["melody_plan"] = plan
    return plan


def melody_sync_harmonies(plan, harmony_dicts):
    """Sync the harmony row state into the plan. Same shape as
    ``melody_sync_overrides`` — driven by ``harmony_state.change``."""
    if plan is None:
        return plan
    plan.harmonies = [_dict_to_harmony(d) for d in (harmony_dicts or [])]
    _state["melody_plan"] = plan
    return plan


def melody_sync_plan_settings(plan, phrase_shape, default_cadence, motif_text):
    """Sync the plan-level settings (phrase shape / cadence / motif
    development) into the MelodyPlan. ``motif_text`` is a comma-separated
    list of MOTIF_DEVELOPMENT_OPS keys; blank → None (use generator default)."""
    if plan is None:
        return plan
    plan.phrase_shape = phrase_shape or "arc"
    plan.default_cadence = default_cadence or None
    if motif_text and motif_text.strip():
        plan.motif_development = [
            tok.strip() for tok in motif_text.split(",") if tok.strip()
        ]
    else:
        plan.motif_development = None
    _state["melody_plan"] = plan
    return plan


def _build_melody_studio_tab(library_trigger: gr.State) -> None:
    """Construct the Melody Studio tab. Called inside ``build_app``'s gr.Tab."""
    plan_state = gr.State(None)
    gr.Markdown(
        "### Melody Studio\n"
        "Pick a melody source, then edit bar-by-bar or note-by-note. "
        "Tag bar ranges with **Section overrides** (voicing + rhythm + "
        "stack/replace/decoration mode) or **Harmonies** (preset ABBA / "
        "Queen / Boston / Journey / Elton / Chicago). Preview, then save "
        "the plan to disk."
    )

    with gr.Row():
        block_picker = gr.Dropdown(
            choices=[b["name"] for b in block_store.list_blocks()],
            label="Saved block", scale=2,
            info="Picks the melody track from a saved Compose block.",
        )
        refresh_blocks_btn = gr.Button("↻ Refresh", scale=0)
        load_block_btn = gr.Button("📥 Load block", scale=1, variant="secondary")
        load_compose_btn = gr.Button("📥 Use latest Compose", scale=1,
                                     variant="primary")

    header_md = gr.Markdown("_No plan loaded._")

    override_state = gr.State([])
    harmony_state = gr.State([])
    # Plan-bars cache for the timeline strip (parsed once from plan_state).
    plan_bars_state = gr.State(8)

    # --- Visual timeline strip ----------------------------------------
    # @gr.render-driven Markdown showing colored bands for each section
    # override + harmony tag. Re-renders whenever the underlying state
    # changes — gives the user a glance-able map of "what affects what".
    @gr.render(inputs=[override_state, harmony_state, plan_bars_state])
    def _render_section_timeline(overrides, harmonies, bars):
        gr.Markdown(_section_timeline_html(overrides, harmonies, bars))

    # --- Primary view (Note list) -------------------------------------
    note_df = gr.Dataframe(
        headers=NOTE_LIST_HEADERS,
        datatype=["number", "number", "number", "number",
                  "number", "str"],
        value=[],
        interactive=True,
        row_count=(0, "dynamic"),
        column_count=(len(NOTE_LIST_HEADERS), "fixed"),
        label="Note list",
    )

    # --- Alternate views (collapsed) ----------------------------------
    with gr.Accordion("Advanced views (scale-degree grid + piano-roll)",
                      open=False):
        # The view radio survives so power users can still switch which
        # advanced dataframe is shown.
        view_radio = gr.Radio(
            MELODY_VIEW_MODES, value="Note list", label="Active view",
            info="Note list is always shown above. This toggle picks "
                 "which alternate editor is visible here.",
        )

        with gr.Group(visible=False) as note_view:
            # Note list also appears here for legacy wiring compat; only
            # the primary version above is interactive.
            pass

        with gr.Group(visible=False) as degree_view:
            gr.Markdown("**Scale-degree grid** — rows are 1..7 of the key's "
                        "scale plus a second octave (primes); cells 0..3 "
                        "= silent/ghost/normal/accent. Stays in-key by design.")
            degree_df = gr.Dataframe(
                headers=["Degree"],
                value=[],
                interactive=True,
                row_count=(0, "dynamic"),
                column_count=(1, "dynamic"),
            )

        with gr.Group(visible=False) as pianoroll_view:
            gr.Markdown("**Piano-roll** — chromatic, ±1 octave around the "
                        "key tonic. Use for deliberate dissonance / chromatic "
                        "moves outside the diatonic set.")
            pianoroll_df = gr.Dataframe(
                headers=["Pitch"],
                value=[],
                interactive=True,
                row_count=(0, "dynamic"),
                column_count=(1, "dynamic"),
            )

    # --- Editing accordion (Plan defaults + Sections + Harmonies) -----
    with gr.Accordion("Editing — plan defaults, sections, harmonies",
                      open=True):
        # Plan defaults ----------------------------------------------------
        gr.Markdown(
            "#### Plan defaults\n"
            "Phrase-wide melody shape. Per-section settings below override "
            "these for their bar range."
        )
        with gr.Row():
            phrase_shape_radio = gr.Radio(
                choices=PHRASE_CONTOURS,
                value="arc",
                label="Phrase shape",
                key="plan_phrase_shape",
            )
            default_cadence_dd = gr.Dropdown(
                choices=["", *sorted(CADENCES.keys())],
                value="authentic_v_i",
                label="Default cadence",
                allow_custom_value=True,
                key="plan_default_cadence",
            )
        motif_dev_in = gr.Textbox(
            value="",
            label="Motif development (comma-separated)",
            placeholder="repeat, sequence_up, inversion, restate",
            key="plan_motif_development",
        )

        gr.Markdown("---")

        # Section overrides ----------------------------------------------
        gr.Markdown(
            "#### Sections\n"
            "Per-bar-range overlays. **Voicing** / **Rhythm** filter as "
            "you type. **Mode**: `stack` (melody + voicing above), "
            "`replace` (chord stacks instead of melody), `decoration` "
            "(melody + grace notes between)."
        )

        @gr.render(inputs=[override_state])
        def _render_overrides_list(overrides):
            if not overrides:
                gr.Markdown("_No section overrides. Click **+ Add section** to add one._")
            else:
                for idx, ov in enumerate(overrides):
                    _render_override_row(idx, ov, override_state)

        add_override_btn = gr.Button(
            "+ Add section", variant="secondary", size="sm",
        )

        gr.Markdown("---")

        # Harmonies ------------------------------------------------------
        gr.Markdown(
            "#### Harmonies\n"
            "Per-bar-range harmony presets (queen / abba / boston / "
            "journey / elton / chicago). Leave `intervals` blank for the "
            "preset's defaults; otherwise comma-separated integers "
            "override."
        )

        @gr.render(inputs=[harmony_state])
        def _render_harmonies_list(harmonies):
            if not harmonies:
                gr.Markdown("_No harmonies. Click **+ Add harmony** to add one._")
            else:
                for idx, hm in enumerate(harmonies):
                    _render_harmony_row(idx, hm, harmony_state)

        add_harmony_btn = gr.Button(
            "+ Add harmony", variant="secondary", size="sm",
        )

        def _append_override(state):
            return list(state or []) + [_default_override_dict()]

        def _append_harmony(state):
            return list(state or []) + [_default_harmony_dict()]

        add_override_btn.click(_append_override, [override_state], override_state)
        add_harmony_btn.click(_append_harmony, [harmony_state], harmony_state)

    with gr.Row():
        regen_range_in = gr.Textbox(
            value="", label="Bar range",
            placeholder="e.g. 1:3 (blank = full)", scale=1,
        )
        regen_seed_in = gr.Number(
            value=0, precision=0, minimum=0, maximum=2**31 - 1,
            label="Seed", scale=0,
        )
        regen_style_dd = gr.Dropdown(
            MELODY_STYLES, value="motif", label="Style", scale=1,
        )
        regen_btn = gr.Button("🎲 Regenerate", variant="primary", scale=1)

    with gr.Row():
        bed_toggle = gr.Checkbox(
            value=False, label="🔊 Include accompaniment",
            info="When on, the block's chords/bass/drums play under the "
                 "melody so you can hear how it sits in context.",
            scale=1,
        )
        preview_btn = gr.Button("▶ Preview", variant="primary", scale=1)
        preview_audio = gr.Audio(
            label="Plan preview", type="filepath", scale=3,
        )

    gr.Markdown("---")
    with gr.Row():
        save_name_in = gr.Textbox(
            value="", label="Save as (block name)",
            placeholder="verse_polished", scale=2,
        )
        save_as_block_btn = gr.Button(
            "💾 Save as new block", variant="primary", scale=1,
        )
        save_status = gr.Markdown("")
    gr.Markdown(
        "_Saving as a new block bakes the melody + harmony + bed "
        "(chords / bass / drums) into a complete block that shows up "
        "in the **Compose Song** library._",
    )

    with gr.Accordion("Advanced save options…", open=False):
        gr.Markdown(
            "**Save plan only (sidecar)** writes just the melody-edit "
            "sidecar — use it when you're attaching an edited melody to "
            "a block you've already saved from MIDI Compose. The next "
            "**Load block** with the same name will pick up your edits."
        )
        save_btn = gr.Button(
            "💾 Save plan only (sidecar)", variant="secondary",
        )

    # ---------- Wiring ---------------------------------------------------

    def _on_view_change(view: str):
        # Note list lives at top level now — always visible. The radio
        # only toggles the two alternate views inside the Advanced
        # accordion.
        return (
            gr.update(visible=view == "Scale-degree grid"),
            gr.update(visible=view == "Piano-roll"),
        )

    view_radio.change(
        _on_view_change, [view_radio],
        [degree_view, pianoroll_view],
    )

    refresh_blocks_btn.click(
        melody_get_blocks_dropdown, outputs=[block_picker],
    )

    def _load_compose_and_render():
        plan = melody_load_from_compose()
        bars = int(plan.bars) if plan else 8
        return (plan, *melody_render_views(plan), bars)

    def _load_block_and_render(block_name):
        plan = melody_load_from_block(block_name)
        bars = int(plan.bars) if plan else 8
        return (plan, *melody_render_views(plan), bars)

    load_compose_btn.click(
        _load_compose_and_render,
        outputs=[plan_state, header_md, note_df, degree_df, pianoroll_df,
                 override_state, harmony_state, plan_bars_state],
    )
    load_block_btn.click(
        _load_block_and_render,
        inputs=[block_picker],
        outputs=[plan_state, header_md, note_df, degree_df, pianoroll_df,
                 override_state, harmony_state, plan_bars_state],
    )

    note_df.change(
        melody_apply_note_rows, [plan_state, note_df], [plan_state],
    )
    degree_df.change(
        melody_apply_degree_grid, [plan_state, degree_df], [plan_state],
    )
    pianoroll_df.change(
        melody_apply_pianoroll, [plan_state, pianoroll_df], [plan_state],
    )
    # Row-based override / harmony states (replaces the old Dataframes):
    # any per-row .change/.click bubbles up through the state, then we
    # sync to plan_state here.
    override_state.change(
        melody_sync_overrides, [plan_state, override_state], [plan_state],
    )

    def _sync_plan_settings(plan, ps, dc, mt):
        return melody_sync_plan_settings(plan, ps, dc, mt)

    phrase_shape_radio.change(
        _sync_plan_settings,
        [plan_state, phrase_shape_radio, default_cadence_dd, motif_dev_in],
        [plan_state],
    )
    default_cadence_dd.change(
        _sync_plan_settings,
        [plan_state, phrase_shape_radio, default_cadence_dd, motif_dev_in],
        [plan_state],
    )
    motif_dev_in.change(
        _sync_plan_settings,
        [plan_state, phrase_shape_radio, default_cadence_dd, motif_dev_in],
        [plan_state],
    )
    harmony_state.change(
        melody_sync_harmonies, [plan_state, harmony_state], [plan_state],
    )

    def _regen_and_render(plan, bar_range, seed, style):
        new_plan = melody_regenerate(plan, bar_range, seed, style)
        return (new_plan, *melody_render_views(new_plan))

    regen_btn.click(
        _regen_and_render,
        inputs=[plan_state, regen_range_in, regen_seed_in, regen_style_dd],
        outputs=[plan_state, header_md, note_df, degree_df, pianoroll_df,
                 override_state, harmony_state],
    )

    preview_btn.click(
        melody_preview, [plan_state, bed_toggle], [preview_audio],
    )

    save_btn.click(
        melody_save_plan, [plan_state, save_name_in], [save_status],
    )
    save_as_block_btn.click(
        melody_save_as_block,
        [plan_state, save_name_in, library_trigger],
        [save_status, library_trigger],
    )


def build_app() -> gr.Blocks:
    theme = gr.themes.Soft(primary_hue="blue", secondary_hue="emerald")
    with gr.Blocks(title="AI Music Studio", theme=theme) as app:
        gr.Markdown(
            "# AI Music Studio\n"
            "**Primary workflow: MIDI → DAW.** Use the **MIDI Compose** tab to "
            "generate chords / bass / melody / drums as a `.mid` file you can drag "
            "into Ardour. The **AI Audio** tab runs MusicGen for text-to-audio "
            "stems (optional, slower). Combine both on the **Export Session** tab."
        )

        # Shared trigger so MIDI Compose's "Save as Block" button can force
        # the Compose Song library to refresh. Each click bumps the integer;
        # Compose Song's @gr.render reads list_blocks() fresh on each tick.
        library_trigger = gr.State(0)

        # -- Tab 1: MIDI Compose (primary workflow) ------------------------
        with gr.Tab("MIDI Compose", id="compose"):
            gr.Markdown(
                "### MIDI Composer\n"
                "Pick a **Style** (auto-fills key/scale/tempo/patterns), hit "
                "**Compose**, then **Download MIDI** and drag the `.mid` into "
                "Ardour. Everything is editable after picking a style."
            )
            with gr.Row():
                with gr.Column(scale=2):
                    style_dd = gr.Dropdown(
                        ["custom"] + list_styles(),
                        value="pop", label="Style",
                        info="Pick a genre preset (populates key/scale/tempo/patterns) or 'custom' to tweak freely.",
                    )

                    with gr.Row(elem_classes=["compose-row-grid"]):
                        key = gr.Dropdown(
                            KEYS, value="C", label="Key",
                        )
                        scale = gr.Dropdown(
                            list(SCALES.keys()), value="major", label="Scale",
                        )
                        tempo_slider = gr.Slider(60, 200, value=118, step=1, label="Tempo (BPM)")
                        time_sig_dd = gr.Dropdown(
                            TIME_SIGS, value="4/4", label="Time signature",
                        )
                        bars_slider = gr.Slider(
                            2, 128, value=8, step=1, label="Bars",
                        )

                    gr.Markdown("**Instruments**")
                    # Six family accordions. Each is a CheckboxGroup of
                    # instruments from that family; the first three open
                    # by default with sensible single-instrument picks
                    # (drum_kit / electric_bass / piano). Picking a style
                    # preset auto-fills these via the preset's
                    # ``default_instruments`` list (see _apply_preset).
                    _OPEN_FAMILIES = {"rhythm", "bass", "chord_lead"}
                    _STARTER_DEFAULTS = {
                        "rhythm": ["drum_kit"],
                        "bass":   ["electric_bass"],
                        "chord_lead": ["piano"],
                        "brass": [], "woodwind": [], "strings": [],
                    }
                    family_selects: dict = {}
                    for _family in FAMILIES:
                        _choices = [
                            (inst.label, inst.id)
                            for inst in instruments_for_family(_family)
                        ]
                        with gr.Accordion(
                            FAMILY_LABELS[_family],
                            open=_family in _OPEN_FAMILIES,
                            elem_classes=["instrument-family"],
                        ):
                            family_selects[_family] = gr.CheckboxGroup(
                                choices=_choices,
                                value=_STARTER_DEFAULTS[_family],
                                show_label=False,
                                container=False,
                            )
                    rhythm_select     = family_selects["rhythm"]
                    bass_select       = family_selects["bass"]
                    chord_lead_select = family_selects["chord_lead"]
                    brass_select      = family_selects["brass"]
                    woodwind_select   = family_selects["woodwind"]
                    strings_select    = family_selects["strings"]
                    with gr.Row(elem_classes=["compose-row-grid"]):
                        harmony_on = gr.Checkbox(value=False, label="Stack harmony on melody")

                    # Harmony controls — only meaningful when harmony_on
                    # is checked. Same plumbing the harmony extras row
                    # uses; promoted up here so harmony is a first-class
                    # default track like chords / bass / melody / drums.
                    with gr.Row(elem_classes=["compose-row-grid"]):
                        harmony_voices = gr.Radio(
                            [1, 2, 3], value=2, label="Harmony voices",
                            info="How many harmony lines to stack on the melody.",
                        )
                        harmony_preset = gr.Dropdown(
                            HARMONY_PRESETS, value="queen",
                            label="Harmony preset",
                            info="queen / abba / boston / journey / elton / chicago.",
                            allow_custom_value=True,
                        )
                        harmony_rule_dd = gr.Dropdown(
                            ["", *sorted(HARMONY_OPS)],
                            value="voice_leading_smooth",
                            label="Voice-leading rule",
                            info="Blank = smooth default.",
                            allow_custom_value=True,
                        )

                    with gr.Row(elem_classes=["compose-row-grid"]):
                        voicing_dd = gr.Dropdown(
                            VOICINGS,
                            value="triad", label="Chord voicing",
                        )
                        chord_rhythm_dd = gr.Dropdown(
                            CHORD_RHYTHMS,
                            value="pulse_quarter", label="Chord rhythm",
                            info=("How the chords are comped. pad = sustained; "
                                  "stabs = rhythmic; tresillo/clave/montuno = Latin; "
                                  "arab_maqsum / indian_teental_16 = world."),
                        )
                        melody_style_dd = gr.Dropdown(
                            MELODY_STYLES,
                            value="motif", label="Melody style",
                            info=("motif/riff/chord_tone/pentatonic/blues — Western. "
                                  "raga_*/maqam_*/gamelan_slendro/hirajoshi — "
                                  "ethno-musicological palettes for weak-beat notes."),
                        )

                    with gr.Row(elem_classes=["compose-row-grid"]):
                        bass_pat = gr.Dropdown(
                            BASS_PATTERNS,
                            value="root_fifth", label="Bass pattern",
                        )
                        drum_pat = gr.Dropdown(
                            DRUM_PATTERNS,
                            value="basic_rock", label="Drum pattern",
                        )
                        swing_slider = gr.Slider(0.0, 0.5, value=0.0, step=0.01,
                                                 label="Swing", info="0 = straight, ~0.33 = triplet feel")

                    with gr.Row():
                        chord_octave_in = gr.Number(value=3, precision=0, minimum=1, maximum=6,
                                                    label="Chord octave",
                                                    info="MIDI octave for the chord root (3 = bass-clef range).")
                        bass_octave_in = gr.Number(value=2, precision=0, minimum=0, maximum=5,
                                                   label="Bass octave",
                                                   info="MIDI octave for the bass root (2 = E2 register).")
                        melody_octave_in = gr.Number(value=5, precision=0, minimum=3, maximum=7,
                                                     label="Melody octave",
                                                     info="MIDI octave the melody's tonic anchor sits in (5 = C5).")

                    # Seed the grid state with the default-pattern hits so
                    # Compose works on first click even before the user
                    # touches any control. Subsequent changes to drum_pat /
                    # time_sig / bars re-load this state automatically.
                    _initial_grid = drum_pattern_to_grid("basic_rock", (4, 4), bars=8)
                    drum_grid_state = gr.State(_initial_grid)
                    with gr.Accordion("🥁 Drum grid editor", open=False):
                        gr.Markdown(
                            "Always shows the currently-selected drum pattern "
                            "on a 16th-note grid (eighth-relative for compound "
                            "meters like 6/8). Edit cells to tweak what gets "
                            "rendered — values: **0** silent / **1** ghost / "
                            "**2** normal / **3** accent. Changing the Drum "
                            "pattern dropdown, Time signature, or Bars reloads "
                            "the grid; **🔄 Reset to pattern** undoes manual "
                            "edits without changing meter."
                        )
                        with gr.Row():
                            drum_grid_load_btn = gr.Button(
                                "🔄 Reset to pattern", size="sm",
                            )
                        _initial_rows, _initial_headers = _grid_to_dataframe(
                            _initial_grid, (4, 4), 8,
                        )
                        # column_count must be dynamic so the grid can resize
                        # when meter or bar count changes (each meter has a
                        # different step count). Row count stays fixed at the
                        # canonical drum-row list.
                        drum_grid_df = gr.Dataframe(
                            headers=_initial_headers,
                            value=_initial_rows,
                            interactive=True,
                            row_count=(len(GRID_DRUM_ROWS), "fixed"),
                            column_count=(len(_initial_headers), "dynamic"),
                            datatype=["str"] + ["number"] * (len(_initial_headers) - 1),
                        )

                    # Chord progression: pre-loads from style preset; editable.
                    # The variant dropdown lets the user pick among the
                    # style's curated progressions (different lengths /
                    # pacing); the random toggle re-rolls on each Compose.
                    _pop_variants = STYLES["pop"].progression_variants
                    with gr.Row():
                        progression_variant_dd = gr.Dropdown(
                            choices=[v[0] for v in _pop_variants],
                            value=_pop_variants[0][0],
                            label="Preset variation",
                            info="Genre-idiomatic alternatives — switching "
                                 "rewrites the textbox below.",
                            scale=1,
                        )
                        random_variation_chk = gr.Checkbox(
                            value=False,
                            label="🎲 Random on Compose",
                            info="When on, ignore textbox and pick a random "
                                 "variation each Compose.",
                            scale=1,
                        )
                    with gr.Row():
                        progression_in = gr.Textbox(
                            value=_progression_plan_to_text(STYLES["pop"].progression),
                            label="Chord progression",
                            info=("Space-separated roman numerals. Add ':<bars>' "
                                  "to control pacing: 'I:2 V:1 vi:1 IV:4' = I for "
                                  "2 bars, V for 1, vi for 1, IV for 4. Bare tokens "
                                  "= 1 bar each. Empty = use style preset."),
                            placeholder="I V vi IV    or    I:2 V:1 vi:1 IV:4",
                            scale=4,
                        )
                        progression_refresh = gr.Button("🔄 Refresh from style", scale=1)

                    # Declared early so the per-instrument accordion
                    # below can render a row per extra. Populated by
                    # the Extra Tracks accordion further down.
                    extras_state = gr.State([])

                    # Per-instrument progression overrides — one textbox
                    # per instrument with a single lock toggle. Locked
                    # (🔒) means follow the master 1:1; unlocked (🔓)
                    # means the user has typed a progression for THIS
                    # instrument that differs from the master and
                    # subsequent master edits should not overwrite it.
                    _initial_master_text = _progression_plan_to_text(
                        STYLES["pop"].progression,
                    )
                    chords_prog_state = gr.State(
                        _default_instrument_progression_dict(_initial_master_text),
                    )
                    bass_prog_state = gr.State(
                        _default_instrument_progression_dict(_initial_master_text),
                    )
                    melody_prog_state = gr.State(
                        _default_instrument_progression_dict(_initial_master_text),
                    )

                    with gr.Accordion("Per-instrument progressions", open=False):
                        gr.Markdown(
                            "Each instrument can either follow the master "
                            "progression above (🔒) or carry its own. "
                            "Tap the lock to customise — useful for "
                            "walking bass lines, counter-melodies, "
                            "extended/altered chord pads, etc."
                        )
                        _render_instrument_progression_row(
                            label="Chords",
                            state=chords_prog_state,
                            master_in=progression_in,
                            key_prefix="prog_chords",
                        )
                        _render_instrument_progression_row(
                            label="Bass",
                            state=bass_prog_state,
                            master_in=progression_in,
                            key_prefix="prog_bass",
                        )
                        _render_instrument_progression_row(
                            label="Melody",
                            state=melody_prog_state,
                            master_in=progression_in,
                            key_prefix="prog_melody",
                        )

                        # One row per extra, rendered dynamically when
                        # the user adds Extra tracks below. Same lock +
                        # textbox shape — the state is the existing
                        # `progression` + `progression_locked` keys on
                        # each extras_state entry.
                        @gr.render(inputs=[extras_state, progression_in])
                        def _render_extras_progressions(extras, master_text):
                            if not extras:
                                return
                            gr.Markdown("---")
                            gr.Markdown("**Extras**")
                            for idx, tr in enumerate(extras):
                                _render_extras_progression_row(
                                    idx, tr, master_text,
                                    extras_state, progression_in,
                                )

                    # -------------------------------------------------
                    # Per-bar rhythm overrides
                    # -------------------------------------------------
                    rhythm_overrides_state = gr.State([])
                    rhythm_overrides_stash = gr.State([])
                    rhythm_reorder_signal = gr.Number(
                        value=0, visible=False,
                    )

                    with gr.Accordion("Per-bar rhythm overrides", open=False):
                        gr.Markdown(
                            "Override the chord rhythm and bass pattern "
                            "for specific bars or ranges. Each row covers "
                            "``[start, end]`` (inclusive). Earlier rows "
                            "win on overlap — use the ↑ / ↓ buttons to "
                            "set precedence. Empty field = inherit the "
                            "master dropdown above. Chord rhythm splits "
                            "the bar in half so you can comp differently "
                            "on beats 3-4."
                        )

                        with gr.Row(elem_classes=["compose-row-grid"]):
                            rhythm_variant_dd = gr.Dropdown(
                                choices=[""],
                                value="",
                                label="Apply variant from style",
                                scale=2,
                            )
                            rhythm_apply_btn = gr.Button(
                                "Apply", scale=1, variant="secondary",
                            )
                            rhythm_undo_btn = gr.Button(
                                "↶ Undo apply", scale=1,
                            )
                            rhythm_split_btn = gr.Button(
                                "+ Split rows per bar", scale=1,
                            )
                            rhythm_add_btn = gr.Button(
                                "+ Add range", scale=1, variant="primary",
                            )

                        @gr.render(
                            inputs=[rhythm_overrides_state],
                            triggers=[
                                rhythm_add_btn.click,
                                rhythm_reorder_signal.change,
                                rhythm_apply_btn.click,
                                rhythm_undo_btn.click,
                                rhythm_split_btn.click,
                            ],
                        )
                        def _render_rhythm_overrides(overrides):
                            if not overrides:
                                gr.Markdown(
                                    "_No overrides — the master rhythm "
                                    "and bass pattern apply to every bar._"
                                )
                                return
                            for idx, ov in enumerate(overrides):
                                _render_rhythm_override_row(
                                    idx, ov,
                                    rhythm_overrides_state,
                                    rhythm_reorder_signal,
                                )

                        # Wire toolbar actions.
                        rhythm_add_btn.click(
                            lambda s: list(s) + [_default_rhythm_override_row(
                                start_bar=(s[-1]["end_bar"] + 1) if s else 0,
                            )],
                            [rhythm_overrides_state],
                            [rhythm_overrides_state],
                        )

                        def _refresh_variant_choices(style_name):
                            try:
                                from src.daw_integration.generic.styles import STYLES
                                preset = STYLES.get(style_name)
                                names = list((preset.rhythm_variants or {}).keys()) \
                                        if preset else []
                            except Exception:
                                names = []
                            value = names[0] if names else ""
                            return gr.update(
                                choices=[""] + names, value=value,
                            )

                        rhythm_apply_btn.click(
                            lambda s: list(s),
                            [rhythm_overrides_state],
                            [rhythm_overrides_stash],
                        )

                        def _apply_variant(style_name, variant_name, current):
                            if not variant_name:
                                return list(current)
                            try:
                                from src.daw_integration.generic.styles import STYLES
                                preset = STYLES.get(style_name)
                                if not preset:
                                    return list(current)
                                rows = preset.rhythm_variants.get(variant_name) or []
                                return [dict(r) for r in rows]
                            except Exception:
                                return list(current)

                        rhythm_apply_btn.click(
                            _apply_variant,
                            # `style_dd` is the master style dropdown
                            # built earlier in this tab.
                            [style_dd, rhythm_variant_dd,
                             rhythm_overrides_state],
                            [rhythm_overrides_state],
                        )

                        rhythm_undo_btn.click(
                            lambda stashed: list(stashed),
                            [rhythm_overrides_stash],
                            [rhythm_overrides_state],
                        )

                        def _split_per_bar(overrides):
                            out = []
                            for ov in overrides:
                                s = int(ov.get("start_bar", 0))
                                e = int(ov.get("end_bar", 0))
                                if e < s:
                                    s, e = e, s
                                if s == e:
                                    out.append(dict(ov))
                                    continue
                                for b in range(s, e + 1):
                                    out.append({
                                        **ov, "start_bar": b, "end_bar": b,
                                    })
                            return out

                        rhythm_split_btn.click(
                            _split_per_bar,
                            [rhythm_overrides_state],
                            [rhythm_overrides_state],
                        )

                        # Keep the variant dropdown in sync with the
                        # currently selected style (different presets
                        # offer different rhythm_variants).
                        style_dd.change(
                            _refresh_variant_choices,
                            [style_dd], [rhythm_variant_dd],
                        )

                    # Extra Tracks — dynamic list of additional tracks beyond the 4.
                    # extras_state was declared earlier so the per-instrument
                    # progression panel can render a row per extra.
                    with gr.Accordion("Extra tracks (optional)", open=False):
                        with gr.Row():
                            new_extra_type = gr.Dropdown(
                                TRACK_TYPES, value="lead", label="Type", scale=1,
                            )
                            new_extra_name = gr.Textbox(
                                value="", label="Name (optional)",
                                placeholder="e.g. Synth Lead", scale=2,
                            )
                            add_extra_btn = gr.Button("+ Add extra track", scale=1)

                        # Re-render signal. The @gr.render below uses
                        # explicit ``triggers=`` so field edits inside a
                        # row don't tear down + rebuild the row's
                        # widgets — that's the lock-on-edit symptom
                        # users were hitting. Only Add (this button) and
                        # Remove (per-row, which bumps the signal) cause
                        # a structural rebuild.
                        extras_render_signal = gr.Number(
                            value=0, visible=False, label="_extras_signal",
                        )

                        @gr.render(
                            inputs=[extras_state],
                            triggers=[
                                add_extra_btn.click,
                                extras_render_signal.change,
                            ],
                        )
                        def _render_extras_list(extras):
                            if not extras:
                                gr.Markdown(
                                    "_No extra tracks. The 4 primary tracks above "
                                    "render unchanged. Add an extra (lead, second "
                                    "bass, theme, etc.) below._"
                                )
                                return
                            for tr_idx, tr in enumerate(extras):
                                _render_extra_track_row(
                                    tr_idx, tr, extras_state,
                                    rerender_signal=extras_render_signal,
                                )

                        def _add_extra(state, ttype, name):
                            if len(state) >= 6:
                                raise gr.Error("Max 6 extra tracks. Remove one to add more.")
                            new_tr = _default_extra_track(ttype, name)
                            return list(state) + [new_tr]

                        add_extra_btn.click(_add_extra,
                                            [extras_state, new_extra_type, new_extra_name],
                                            extras_state)

                    seed_input = gr.Number(value=0, label="Seed (0 = random)", precision=0)

                    compose_btn = gr.Button("Compose", variant="primary", size="lg")

                with gr.Column(scale=1):
                    midi_file = gr.File(label="Download .mid (drag into Ardour)")
                    compose_info = gr.Textbox(label="Info", interactive=False)
                    midi_audio = gr.Audio(label="Preview (synth render)", type="filepath")

                    with gr.Row(elem_classes=["compose-row-grid"]):
                        random_song_btn = gr.Button(
                            "🎲 Generate full song (random)",
                            variant="primary", scale=2,
                        )
                        random_song_seed = gr.Number(
                            value=0, precision=0, label="Seed (0 = auto)",
                            scale=1,
                        )
                    random_song_summary = gr.Markdown(
                        value="_The TechniqueBank picks one technique per "
                              "(instrument, section). Same seed = same song; "
                              "bump the seed for variation._",
                    )

                    random_song_btn.click(
                        _generate_full_song,
                        inputs=[style_dd, random_song_seed,
                                rhythm_select, bass_select, chord_lead_select,
                                brass_select, woodwind_select, strings_select],
                        outputs=[midi_audio, midi_file, compose_info,
                                 random_song_summary,
                                 rhythm_overrides_state,
                                 random_song_seed],
                    )

                    with gr.Row():
                        compose_pdf_btn = gr.Button(
                            "🎼 Export PDF (full score + parts)",
                            variant="secondary",
                        )
                    compose_pdf_file = gr.File(label="Download PDFs (.zip)")
                    compose_pdf_preview = gr.HTML(
                        label="Score preview",
                        value="",
                    )
                    compose_pdf_btn.click(
                        _export_compose_pdf, [],
                        [compose_pdf_file, compose_pdf_preview],
                    )

                    with gr.Accordion("🎯 Key-safety audit", open=False):
                        gr.Markdown(
                            "Flagged notes after each Compose. `out_of_key` "
                            "= chromatic and likely accidental. `approach_tone` "
                            "= short weak-beat neighbour, usually intentional "
                            "passing tone. Use # to play that bar or apply an "
                            "in-scale suggestion."
                        )
                        audit_df = gr.Dataframe(
                            headers=AUDIT_COLUMNS,
                            datatype=["number", "str", "number", "number",
                                      "str", "str", "str", "str"],
                            value=[],
                            interactive=False,
                            row_count=(0, "dynamic"),
                            column_count=(len(AUDIT_COLUMNS), "fixed"),
                        )
                        with gr.Row():
                            audit_row_in = gr.Number(
                                value=1, precision=0, minimum=1,
                                label="# to act on",
                            )
                            audit_play_btn = gr.Button("▶ Play this bar",
                                                       size="sm")
                            audit_suggestion_dd = gr.Dropdown(
                                choices=[], value=None,
                                label="Suggestion",
                                # allow_custom_value=True so a stale dropdown
                                # doesn't reject the Apply click before our
                                # validation logic gets to run; we fall back
                                # to "first suggestion of the selected row"
                                # in apply_audit_suggestion when blank.
                                allow_custom_value=True,
                            )
                            audit_apply_btn = gr.Button("Apply suggestion",
                                                        variant="primary",
                                                        size="sm")
                        audit_play_audio = gr.Audio(
                            label="Flagged bar preview", type="filepath",
                        )

                    gr.Markdown(
                        "---\n**Render to High-Quality Audio**\n"
                        "Per-track FluidSynth render → effects → mix → master. "
                        "Drop a `.sf2`/`.sf3` into `data/soundfonts/` "
                        "(or click **Download MuseScore SF3**) for the best quality."
                    )
                    with gr.Row():
                        master_preset_dd = gr.Dropdown(
                            list(MASTER_PRESETS.keys()),
                            value="default", label="Master preset",
                            info="default | loud | cinematic | transparent",
                        )
                        stems_chk = gr.Checkbox(value=True, label="Export stems")
                    soundfont_in = gr.Textbox(
                        value="auto", label="Soundfont path",
                        info="'auto' = use largest in data/soundfonts/, then bundled fallback.",
                    )
                    with gr.Row():
                        render_hq_btn = gr.Button(
                            "🎚 Render to High-Quality Audio",
                            variant="primary", scale=2,
                        )
                        download_sf_btn = gr.Button(
                            "⬇ Download MuseScore SF3", scale=1,
                        )
                    render_hq_audio = gr.Audio(
                        label="High-quality mix", type="filepath",
                    )
                    render_hq_stems = gr.File(label="Download stems (.zip)")
                    render_hq_info = gr.Textbox(label="Render info", interactive=False)
                    download_sf_status = gr.Markdown("")

                    render_hq_btn.click(
                        render_high_quality,
                        inputs=[master_preset_dd, stems_chk, soundfont_in],
                        outputs=[render_hq_audio, render_hq_stems, render_hq_info],
                    )
                    download_sf_btn.click(
                        download_soundfont,
                        outputs=[download_sf_status],
                    )

                    # Save-as-Block: send what was just composed to the
                    # Compose Song library.
                    gr.Markdown("---\n**Save as Block** for the Compose Song timeline:")
                    block_name_in = gr.Textbox(value="", label="Block name",
                                               placeholder="verse_1, chorus, …")
                    save_block_btn = gr.Button("💾 Save as Block", variant="secondary")
                    save_block_status = gr.Markdown("")

                    def _save_and_bump(name, trigger):
                        status = save_current_as_block(name)
                        return status, (trigger or 0) + 1

                    save_block_btn.click(
                        _save_and_bump,
                        [block_name_in, library_trigger],
                        [save_block_status, library_trigger],
                    )

            def _apply_preset(style_name: str):
                """Auto-seed the compose form from the selected style.

                Returns 23 ``gr.update()`` objects. Order matches the
                wiring's ``outputs=`` list below. The 6 family
                CheckboxGroup updates auto-fill from
                ``preset.default_instruments`` (empty list for the
                cultural-genre presets that don't override). The
                ``drums_on`` checkbox went away with the 5-checkbox
                row swap; drum kit presence is now expressed by the
                rhythm-family CheckboxGroup containing ``drum_kit``.
                """
                if style_name == "custom" or style_name not in STYLES:
                    return (gr.update(),) * 23
                p = STYLES[style_name]
                ts_label = f"{p.time_signature[0]}/{p.time_signature[1]}"
                drum_update = gr.update() if not p.drum_pattern else gr.update(value=p.drum_pattern)
                variant_names = [v[0] for v in p.progression_variants]
                default_plan = p.progression_variants[0][1]
                rhythm_rows: list = []
                if p.rhythm_variants:
                    first_variant_name = next(iter(p.rhythm_variants))
                    rhythm_rows = [
                        dict(r) for r in p.rhythm_variants[first_variant_name]
                    ]
                # Bucket default_instruments by family for the 6
                # CheckboxGroups. Presets without an explicit
                # default_instruments list leave the user's existing
                # selection untouched (per-family gr.update() pass-through).
                family_updates: dict[str, object] = {f: gr.update() for f in FAMILIES}
                if p.default_instruments:
                    family_buckets: dict[str, list[str]] = {f: [] for f in FAMILIES}
                    for inst_id in p.default_instruments:
                        inst = INSTRUMENT_REGISTRY.get(inst_id)
                        if inst is not None:
                            family_buckets[inst.family].append(inst_id)
                    for f in FAMILIES:
                        family_updates[f] = gr.update(value=family_buckets[f])
                return (
                    gr.update(value=p.key),
                    gr.update(value=p.scale),
                    gr.update(value=p.tempo),
                    gr.update(value=ts_label),
                    gr.update(value=p.voicing),
                    gr.update(value=p.bass_pattern),
                    drum_update,
                    gr.update(value=p.swing),
                    gr.update(value=p.chord_rhythm),
                    gr.update(value=p.melody_style),
                    gr.update(value=_progression_plan_to_text(default_plan)),
                    gr.update(value=p.chord_octave),
                    gr.update(value=p.bass_octave),
                    gr.update(value=p.melody_octave),
                    gr.update(choices=variant_names, value=variant_names[0]),
                    gr.update(value=int(p.default_bars)),
                    rhythm_rows,
                    family_updates["rhythm"],
                    family_updates["bass"],
                    family_updates["chord_lead"],
                    family_updates["brass"],
                    family_updates["woodwind"],
                    family_updates["strings"],
                )

            style_dd.change(
                _apply_preset,
                inputs=[style_dd],
                outputs=[key, scale, tempo_slider, time_sig_dd, voicing_dd,
                         bass_pat, drum_pat, swing_slider,
                         chord_rhythm_dd, melody_style_dd, progression_in,
                         chord_octave_in, bass_octave_in, melody_octave_in,
                         progression_variant_dd,
                         bars_slider, rhythm_overrides_state,
                         rhythm_select, bass_select, chord_lead_select,
                         brass_select, woodwind_select, strings_select],
            )

            def _refresh_progression(style_name):
                p = STYLES.get(style_name)
                if not p:
                    return gr.update()
                return gr.update(value=_progression_plan_to_text(p.progression))

            progression_refresh.click(_refresh_progression,
                                      [style_dd], [progression_in])

            def _switch_variation(style_name: str, variant_name: str):
                """Populate the progression textbox from the picked variation."""
                p = STYLES.get(style_name)
                if not p:
                    return gr.update()
                for vname, plan in p.progression_variants:
                    if vname == variant_name:
                        return gr.update(value=_progression_plan_to_text(plan))
                return gr.update()

            progression_variant_dd.change(
                _switch_variation,
                [style_dd, progression_variant_dd],
                [progression_in],
            )

            def _on_master_progression_change(text, chords_st, bass_st, melody_st, extras_st):
                """When the master textbox changes, sync the stored
                ``text`` of any *locked* instrument (and locked extra)
                to the new master. Unlocked rows are sealed — they
                keep their own text until the user re-locks them.
                """
                def _sync_simple(state):
                    s = dict(state or {})
                    if s.get("locked", True):
                        s["text"] = text or ""
                    return s

                def _sync_extras(extras):
                    out = []
                    for e in extras or []:
                        e2 = dict(e)
                        if e2.get("progression_locked", True):
                            e2["progression"] = text or ""
                        out.append(e2)
                    return out

                return (
                    _sync_simple(chords_st),
                    _sync_simple(bass_st),
                    _sync_simple(melody_st),
                    _sync_extras(extras_st),
                )

            progression_in.change(
                _on_master_progression_change,
                [progression_in, chords_prog_state, bass_prog_state,
                 melody_prog_state, extras_state],
                [chords_prog_state, bass_prog_state, melody_prog_state, extras_state],
            )

            def _compose_with_families(
                style, key_, scale_, tempo_, time_sig_, bars_,
                rhythm_sel, bass_sel, chord_lead_sel,
                brass_sel, woodwind_sel, strings_sel,
                bass_pattern_, drum_pattern_, voicing_, swing_,
                chord_rhythm_, melody_style_, seed_,
                progression_text_, extras_,
                chord_octave_, bass_octave_, melody_octave_,
                drum_grid_state_, random_variation_,
                chords_prog_, bass_prog_, melody_prog_,
                enable_harmony_, harmony_voices_, harmony_preset_,
                harmony_rule_, rhythm_overrides_,
            ):
                """Flatten the 6 family CheckboxGroups into one
                ``enabled_instruments`` list and call ``compose_midi``.
                Passes the four legacy enable booleans as ``False`` so
                the empty-selection path raises rather than silently
                falling back to the legacy default tracks."""
                instruments = _collect_instruments(
                    rhythm_sel, bass_sel, chord_lead_sel,
                    brass_sel, woodwind_sel, strings_sel,
                )
                return compose_midi(
                    style=style, key=key_, scale=scale_, tempo=tempo_,
                    time_sig=time_sig_, bars=bars_,
                    enable_chords=False, enable_bass=False,
                    enable_melody=False, enable_drums=False,
                    bass_pattern=bass_pattern_, drum_pattern=drum_pattern_,
                    voicing=voicing_, swing=swing_,
                    chord_rhythm=chord_rhythm_, melody_style=melody_style_,
                    seed=seed_, progression_text=progression_text_,
                    extras=extras_,
                    chord_octave=chord_octave_, bass_octave=bass_octave_,
                    melody_octave=melody_octave_,
                    drum_grid_state=drum_grid_state_,
                    random_variation=random_variation_,
                    chords_progression_override=chords_prog_,
                    bass_progression_override=bass_prog_,
                    melody_progression_override=melody_prog_,
                    enable_harmony=enable_harmony_,
                    harmony_voices=harmony_voices_,
                    harmony_preset=harmony_preset_,
                    harmony_rule=harmony_rule_,
                    rhythm_overrides=rhythm_overrides_,
                    enabled_instruments=instruments,
                )

            compose_btn.click(
                _compose_with_families,
                inputs=[style_dd, key, scale, tempo_slider, time_sig_dd, bars_slider,
                        rhythm_select, bass_select, chord_lead_select,
                        brass_select, woodwind_select, strings_select,
                        bass_pat, drum_pat, voicing_dd, swing_slider,
                        chord_rhythm_dd, melody_style_dd, seed_input,
                        progression_in, extras_state,
                        chord_octave_in, bass_octave_in, melody_octave_in,
                        drum_grid_state, random_variation_chk,
                        chords_prog_state, bass_prog_state, melody_prog_state,
                        harmony_on, harmony_voices, harmony_preset,
                        harmony_rule_dd, rhythm_overrides_state],
                outputs=[midi_audio, midi_file, compose_info, audit_df,
                         audit_suggestion_dd],
            )

            # Key-safety audit wiring
            audit_row_in.change(get_suggestions_for_row,
                                [audit_row_in], [audit_suggestion_dd])
            audit_play_btn.click(play_flagged_bar,
                                 [audit_row_in], [audit_play_audio])
            audit_apply_btn.click(
                apply_audit_suggestion,
                [audit_row_in, audit_suggestion_dd],
                [midi_audio, midi_file, compose_info, audit_df,
                 audit_suggestion_dd],
            )

            # Drum grid auto-sync — keep the grid surface in lock-step with
            # the drum-pattern dropdown / time signature / bar count so the
            # user always edits the currently-active pattern. Each change
            # reloads from the named preset; user edits are lost on these
            # transitions (the "Reset to pattern" button is the explicit
            # undo affordance when they want to clear edits without
            # changing meter).
            for trigger in (drum_pat, time_sig_dd, bars_slider):
                trigger.change(
                    load_drum_grid,
                    [drum_pat, time_sig_dd, bars_slider],
                    [drum_grid_df, drum_grid_state],
                )
            drum_grid_load_btn.click(
                load_drum_grid,
                [drum_pat, time_sig_dd, bars_slider],
                [drum_grid_df, drum_grid_state],
            )
            # Mirror dataframe edits back into the state so Compose sees them.
            drum_grid_df.change(
                _dataframe_to_grid,
                [drum_grid_df],
                [drum_grid_state],
            )

        # -- Tab: Compose Song (multi-section, freeform tracks) ------------
        with gr.Tab("Compose Song", id="song"):
            _build_compose_song_tab(library_trigger)

        # -- Tab: Playback (Guitar-Pro style score + cursor) ---------------
        with gr.Tab("Playback", id="playback"):
            _build_playback_tab()

        # -- Tab: Melody Studio --------------------------------------------
        with gr.Tab("Melody Studio", id="melody"):
            _build_melody_studio_tab(library_trigger)

        # -- Tab 2: AI Audio (MusicGen) ------------------------------------
        with gr.Tab("AI Audio", id="generate"):
            gr.Markdown(
                "### Text-to-Audio with MusicGen\n"
                "Optional / slower path. Generates a waveform (not MIDI) from a "
                "text prompt. First run downloads ~300 MB."
            )
            with gr.Row():
                with gr.Column(scale=2):
                    prompt = gr.Textbox(
                        label="Prompt",
                        placeholder="e.g. a chill lo-fi hip hop beat with soft piano and vinyl crackle",
                        lines=2,
                    )
                    with gr.Row():
                        model_size = gr.Dropdown(
                            ["small", "medium", "large"], value="small",
                            label="Model size",
                            info="small ~300M (fast) | medium ~1.5B | large ~3.3B (slow, needs RAM)",
                        )
                        duration = gr.Slider(3, 30, value=10, step=1, label="Duration (seconds)")
                        temperature = gr.Slider(0.5, 1.5, value=1.0, step=0.05, label="Temperature",
                                                info="Higher = more creative / chaotic")
                    gen_btn = gr.Button("Generate audio", variant="primary", size="lg")
                with gr.Column(scale=1):
                    gen_audio = gr.Audio(label="Generated audio", type="filepath")
                    gen_info = gr.Textbox(label="Info", interactive=False)

            gen_btn.click(
                generate_audio,
                inputs=[prompt, model_size, duration, temperature],
                outputs=[gen_audio, gen_info],
            )

            gr.Examples(
                examples=[
                    ["a chill lo-fi hip hop beat with soft piano and vinyl crackle", "small", 10, 1.0],
                    ["epic orchestral cinematic trailer music with timpani and brass", "small", 15, 1.0],
                    ["funky bass guitar groove with wah pedal", "small", 8, 1.1],
                    ["ambient electronic soundscape with reverb pads", "small", 12, 0.9],
                    ["acoustic folk fingerpicking guitar", "small", 10, 1.0],
                ],
                inputs=[prompt, model_size, duration, temperature],
            )

        # -- Tab 3: Export -------------------------------------------------
        with gr.Tab("Export Session", id="export"):
            gr.Markdown(
                "### Export for Ardour or Logic Pro\n"
                "Bundle your composition for finishing in a DAW.\n\n"
                "- **Ardour** path: drag-import a session folder containing "
                "MIDI + audio.\n"
                "- **Logic** path: drag the per-track `.mid` files onto a "
                "fresh project (no public CLI render — manual finishing). "
                "Includes a recommended-instrument map per track."
            )
            with gr.Row():
                with gr.Column():
                    gr.Markdown("**Ardour session**")
                    session_name = gr.Textbox(label="Session name", value="My_AI_Session")
                    export_tempo = gr.Slider(60, 200, value=120, step=1, label="Session tempo (BPM)")
                    with gr.Row():
                        inc_ai = gr.Checkbox(value=True, label="Include AI audio")
                        inc_midi = gr.Checkbox(value=True, label="Include MIDI composition")
                        inc_hq_stems_ardour = gr.Checkbox(
                            value=False,
                            label="Include high-quality stems",
                        )
                    export_btn = gr.Button("Export Ardour Session",
                                           variant="primary", size="lg")
                    export_file = gr.File(label="Download Ardour session (.zip)")
                    export_info = gr.Textbox(label="Info", interactive=False)

                with gr.Column():
                    gr.Markdown("**Logic Pro bundle**")
                    logic_bundle_name = gr.Textbox(
                        label="Bundle name", value="My_AI_LogicBundle",
                    )
                    logic_tempo = gr.Slider(60, 200, value=120, step=1,
                                            label="Bundle tempo (BPM)")
                    logic_time_sig = gr.Dropdown(
                        ["4/4", "3/4", "6/8"], value="4/4",
                        label="Time signature",
                    )
                    inc_hq_stems_logic = gr.Checkbox(
                        value=False,
                        label="Include high-quality stems",
                    )
                    logic_export_btn = gr.Button("Export Logic Bundle",
                                                 variant="primary", size="lg")
                    logic_export_file = gr.File(
                        label="Download Logic bundle (.zip)",
                    )
                    logic_export_info = gr.Textbox(
                        label="Info", interactive=False,
                    )

            export_btn.click(
                export_session,
                inputs=[session_name, export_tempo, inc_ai, inc_midi,
                        inc_hq_stems_ardour],
                outputs=[export_file, export_info],
            )
            logic_export_btn.click(
                export_logic_bundle,
                inputs=[logic_bundle_name, logic_tempo, logic_time_sig,
                        inc_hq_stems_logic],
                outputs=[logic_export_file, logic_export_info],
            )

    return app


if __name__ == "__main__":
    from src.serve.launcher import launch as _serve_launch

    app = build_app()
    _serve_launch(app, on_shutdown=_shutdown)
