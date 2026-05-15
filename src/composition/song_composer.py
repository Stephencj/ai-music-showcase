"""``compose_song()`` — high-level random song generator.

Given a genre (style preset) and a master seed, picks one technique
per ``(instrument, section)`` cell from :data:`src.composition.BANK`
and applies them in order over the right bar range. Same seed →
same song; bump the seed → related variation.

Used by:

- The Gradio "🎲 Generate full song" button (writes selections back
  into the rhythm-overrides accordion).
- The MCP ``compose_song`` tool (exposes the same pipeline to an LLM).
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Optional

import numpy as np
import soundfile as sf

from src.composition import BANK, role_for_label
from src.composition.techniques import TechniqueContext
from src.daw_integration.generic.midi_export import MidiExporter
from src.daw_integration.generic.styles import STYLES


logger = logging.getLogger(__name__)

# Default output paths — same locations the Gradio MIDI Compose tab writes
# to so the Playback tab can pick up the new piece on its next reload.
DEFAULT_OUTPUT_DIR = Path("data/outputs/app")
DEFAULT_MIDI_NAME = "last_composition.mid"
DEFAULT_WAV_NAME = "last_composition.wav"


# Order matters — chords land first, bass second, then drums and
# melody. Some techniques (riff_pass) read the bass track that's
# already in place.
_INSTRUMENT_ORDER: tuple[str, ...] = ("chords", "bass", "drums", "melody")


# Preset name → preferred technique-bank tags. The bank stores each
# genre family's techniques tagged with a short token (``"pop"``,
# ``"rock"``, ``"funk_rock"``, …); :func:`TechniqueBank.pick` doubles
# the weight of any candidate carrying one of these tags so picking
# ``rock_anthem_full`` actually pulls rock idioms rather than the
# cross-genre baseline.
_GENRE_TAG_MAP: dict[str, tuple[str, ...]] = {
    # Pop / rock family.
    "pop":               ("pop",),
    "pop_full_song":     ("pop",),
    "pop_dynamic":       ("pop",),
    "rock":              ("rock",),
    "rock_anthem_full":  ("rock",),
    "rock_buildup":      ("rock",),
    # Funk.
    "funk":              ("funk_rock",),
    "funk_full_song":    ("funk_rock", "funk"),
    "funk_dynamic":      ("funk_rock", "funk"),
    # Jazz / blues.
    "jazz":              ("jazz",),
    "jazz_aaba_full":    ("jazz",),
    "jazz_trade_fours":  ("jazz",),
    "blues_12bar_full":  ("blues",),
    # Ballad.
    "ballad":            ("ballad",),
    "ballad_full":       ("ballad",),
    # Electronic.
    "edm":               ("edm",),
    "edm_full_song":     ("edm",),
    # Hip-hop / metal (the two new presets shipped this round).
    "hip_hop_full":      ("hip_hop",),
    "metal_full":        ("metal",),
    # Newer genre packs.
    "country_full":      ("country",),
    "reggae_full":       ("reggae",),
    "disco_full":        ("disco",),
    "soul_motown_full":  ("soul",),
    # Jazz sub-styles — preferred_tags stacks: a bossa_jazz technique
    # tagged ("jazz", "bossa_jazz") under preferred_tags=("jazz",
    # "bossa_jazz") gets 5×5 = 25× boost vs. a plain "jazz" tech.
    "jazz_bossa_full":     ("jazz", "bossa_jazz"),
    "jazz_hard_bop_full":  ("jazz", "hard_bop"),
    "jazz_modal_full":     ("jazz", "modal_jazz"),
    "jazz_ballad_full":    ("jazz", "ballad_jazz"),
    "jazz_blues_full":     ("jazz", "blues", "jazz_blues"),
    "jazz_bebop_full":     ("jazz", "bebop"),
    "jazz_piano_full":     ("jazz", "piano"),
}


# ---------------------------------------------------------------------------
# Section spec helpers
# ---------------------------------------------------------------------------

def _default_sections_for(genre: str) -> list[dict]:
    """Pull section list from the genre's "Full song" rhythm_variant.

    Falls back to a generic 4-section template if the preset has no
    rhythm_variants — keeps callers honest without a hard requirement.
    """
    preset = STYLES.get(genre)
    if preset and preset.rhythm_variants:
        variant_name = next(iter(preset.rhythm_variants))
        rows = preset.rhythm_variants[variant_name]
        out: list[dict] = []
        for row in rows:
            s = int(row.get("start_bar", 0))
            e = int(row.get("end_bar", s))
            label = row.get("label", "") or f"Section {len(out) + 1}"
            out.append({
                "start_bar": s, "end_bar": e,
                "label": label, "role": role_for_label(label),
            })
        return out
    # Generic fallback — 32-bar four-section sketch.
    return [
        {"start_bar": 0,  "end_bar": 3,  "label": "Intro",  "role": "intro"},
        {"start_bar": 4,  "end_bar": 19, "label": "Verse",  "role": "verse"},
        {"start_bar": 20, "end_bar": 27, "label": "Chorus", "role": "chorus"},
        {"start_bar": 28, "end_bar": 31, "label": "Outro",  "role": "outro"},
    ]


def _sub_seed(master: int, *parts) -> int:
    """Derive a stable sub-seed from the master + arbitrary labels.

    Hash-based so the resulting seeds aren't trivially correlated with
    each other (no "+ 1" colocation effect across cells).
    """
    h = hashlib.blake2b(digest_size=4)
    h.update(str(int(master)).encode())
    for p in parts:
        h.update(b"\0")
        h.update(str(p).encode())
    return int.from_bytes(h.digest(), "big") & 0x7FFFFFFF


def _slice_progression(progression: list, total_bars: int,
                       start_bar: int, end_bar: int) -> list:
    """Return the chord cells active in ``[start_bar, end_bar]``.

    Accepts either ``["I", "V", …]`` (legacy bare strings = 1 bar each)
    or ``[("I", 2.0), …]`` (paced tuples). Loops the cycle if shorter
    than the requested span; truncates the tail to fit.
    """
    if not progression:
        return progression
    # Normalise to tuples first so the loop below has one shape.
    normalised: list = []
    for entry in progression:
        if isinstance(entry, (tuple, list)) and len(entry) >= 2:
            normalised.append((entry[0], float(entry[1])))
        else:
            normalised.append((str(entry), 1.0))

    out: list = []
    bar_cursor = 0.0
    span = float(end_bar + 1 - start_bar)
    # Cap iterations defensively in case a 0-duration tuple sneaks in.
    for _ in range(max(1, int(span * 4))):
        if bar_cursor >= span - 1e-9:
            break
        for sym, dur in normalised:
            if bar_cursor >= span - 1e-9:
                break
            remaining = span - bar_cursor
            out.append((sym, min(dur, remaining)))
            bar_cursor += dur
    return out


# ---------------------------------------------------------------------------
# Compose
# ---------------------------------------------------------------------------

def compose_song(
    *,
    genre: str = "pop",
    sections: Optional[list[dict]] = None,
    seed: int = 0,
    technique_overrides: Optional[dict[str, str]] = None,
    enabled_instruments: Optional[tuple] = None,
    key: Optional[str] = None,
    scale: Optional[str] = None,
    tempo: Optional[float] = None,
    bars: Optional[int] = None,
    swing: Optional[float] = None,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    output_midi: str = DEFAULT_MIDI_NAME,
    output_wav: str = DEFAULT_WAV_NAME,
    skip_audio: bool = False,
) -> dict:
    """Generate a full song by picking techniques per (instrument, section).

    Parameters mirror ``compose_midi`` for the basics; the technique
    picks come from :data:`src.composition.BANK`. Same ``seed`` ⇒
    identical song. ``technique_overrides`` pins specific cells with
    keys ``"{role}:{instrument}"`` or ``"{section_label}:{instrument}"``.

    Returns a dict with paths + summary + selections + an editable
    ``rhythm_overrides`` list shaped like the Gradio accordion expects.
    """
    preset = STYLES.get(genre)
    if preset is None:
        raise ValueError(f"unknown genre {genre!r}")

    # Resolve defaults from the preset.
    eff_key = key or preset.key
    eff_scale = scale or preset.scale
    eff_tempo = float(tempo if tempo is not None else preset.tempo)
    eff_swing = float(swing if swing is not None else preset.swing)
    eff_bars = int(bars if bars is not None else preset.default_bars)
    progression = list(preset.progression)
    technique_overrides = technique_overrides or {}

    # Sections — caller-provided or derived from the preset variant.
    if sections is None:
        sections = _default_sections_for(genre)

    # Build exporter.
    midi = MidiExporter(
        tempo=eff_tempo,
        time_signature=preset.time_signature,
    )

    # Respect the user's track-enable checkboxes. Default is every
    # built-in instrument (preserves the original behaviour).
    if enabled_instruments is None:
        active_instruments: tuple = _INSTRUMENT_ORDER
    else:
        active_instruments = tuple(
            inst for inst in _INSTRUMENT_ORDER if inst in enabled_instruments
        )

    selections: list[dict] = []
    rhythm_overrides_out: list[dict] = []
    # Map the genre key to the technique-bank tag family. Adding a new
    # full-song preset means adding a row here so its techniques get
    # the +weight boost from preferred_tags. Unmapped presets get no
    # bias and fall back to the cross-genre baseline.
    preferred_tags = _GENRE_TAG_MAP.get(genre, ())

    for sec_idx, section in enumerate(sections):
        s, e = int(section["start_bar"]), int(section["end_bar"])
        label = section.get("label", f"Section {sec_idx + 1}")
        role = section.get("role") or role_for_label(label)
        section_prog = _slice_progression(progression, eff_bars, s, e)

        row = {
            "start_bar": s, "end_bar": e, "label": label, "role": role,
            "chord_rhythm_h1": "", "chord_rhythm_h2": "",
            "bass_pattern": "",
        }

        for instrument in active_instruments:
            override_key = f"{role}:{instrument}"
            label_key = f"{label}:{instrument}"
            forced_name = (
                technique_overrides.get(label_key)
                or technique_overrides.get(override_key)
            )
            technique = (
                BANK.get(forced_name) if forced_name else None
            )
            if technique is None:
                sub = _sub_seed(seed, label, instrument)
                rng = np.random.default_rng(sub)
                technique = BANK.pick(
                    instrument, role, rng,
                    preferred_tags=preferred_tags,
                )
            if technique is None:
                logger.info(
                    "compose_song: no technique for (%s, %s) — skipping",
                    instrument, role,
                )
                continue

            ctx = TechniqueContext(
                start_bar=s, end_bar=e,
                section_role=role, section_label=label,
                instrument=instrument,
                key=eff_key, scale=eff_scale,
                tempo=eff_tempo,
                time_signature=preset.time_signature,
                progression=section_prog,
                swing=eff_swing,
                rng=np.random.default_rng(_sub_seed(
                    seed, label, instrument, "inner",
                )),
            )
            try:
                technique.apply(midi, ctx)
            except Exception:
                logger.exception(
                    "compose_song: technique %r raised on (%s, %s) — "
                    "section will be incomplete",
                    technique.name, instrument, role,
                )

            selections.append({
                "section_label": label,
                "section_role":  role,
                "instrument":    instrument,
                "technique":     technique.name,
                "technique_label": technique.label,
                "start_bar": s, "end_bar": e,
            })

            # Surface the technique's nominal rhythm into the editable
            # accordion. We can't always know the rhythm name (custom
            # techniques may compose multiple sub-rhythms), so we just
            # record the technique name in the label so the user sees
            # what fired.
            if instrument == "chords":
                row["chord_rhythm_h1"] = technique.name
            elif instrument == "bass":
                row["bass_pattern"] = technique.name

        rhythm_overrides_out.append(row)

    # Save MIDI + WAV.
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    midi_path = output_dir / output_midi
    midi.save(midi_path)

    wav_path: Optional[Path] = output_dir / output_wav
    if not skip_audio:
        try:
            audio, sr = midi.synthesize(sample_rate=44100)
            sf.write(str(wav_path), audio, sr)
        except Exception:
            logger.exception("compose_song: preview synthesis failed")
            wav_path = None

    # Human-readable summary.
    summary_lines = [
        f"{preset.name} — seed {seed} — {eff_bars} bars",
    ]
    by_section: dict[str, list[dict]] = {}
    for sel in selections:
        by_section.setdefault(sel["section_label"], []).append(sel)
    for label, items in by_section.items():
        span = items[0]
        line = (
            f"  {label} (bars {span['start_bar'] + 1}-{span['end_bar'] + 1}):  "
            + " · ".join(
                f"{it['instrument']}={it['technique']}" for it in items
            )
        )
        summary_lines.append(line)
    summary = "\n".join(summary_lines)

    return {
        "midi_path": str(midi_path),
        "wav_path":  str(wav_path) if wav_path else "",
        "summary":   summary,
        "selections": selections,
        "rhythm_overrides": rhythm_overrides_out,
        "genre": genre,
        "seed": int(seed),
        "bars": eff_bars,
    }
