"""Melody plan — the editable representation for the Melody Studio tab.

A ``MelodyPlan`` carries the melody notes Stephen wants for a block, plus
per-bar-range overrides (apply this voicing + rhythm to bars 4..7), plus
per-bar-range harmony tags (apply Queen-style 3-part harmony to bars 8..15).

This module is the headless layer:

  - ``MelodyNote`` / ``SectionOverride`` / ``HarmonyTag`` / ``MelodyPlan``:
    dataclasses representing the edit state.
  - YAML I/O (``to_yaml``, ``from_yaml``) so plans round-trip to disk
    alongside their parent block (`data/blocks/{name}_melody.yaml`).
  - ``render_melody_plan``: turn a plan into ``Track``s (one melody, one
    optional harmony) by applying the section overrides and harmony tags.
  - ``melody_plan_from_track``: convert a generated melody track into an
    editable plan (used when opening Melody Studio with an existing
    Compose result or a saved block).
  - ``regenerate_bars``: re-roll just the notes inside a bar range, using
    surrounding bars as anchor context.

Reuses (no duplication of music theory):

  - ``voice_chord`` for SectionOverride voicing stacks
  - ``STRUM_RHYTHMS`` + ``ARPEGGIO_PATTERNS`` for SectionOverride rhythm
  - ``expand_progression_plan`` + ``chord_at_position`` for sub-bar chord
    lookups when fitting overrides to a chord progression
  - ``MidiExporter.add_harmony`` (called via a transient exporter) for the
    HarmonyTag preset stack (ABBA / Queen / Boston / Journey / Elton / Chicago)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional, Union

import yaml

logger = logging.getLogger(__name__)

from .midi_export import (
    ARPEGGIO_PATTERNS,
    CADENCES,
    HARMONY_OPS,
    MELODIC_LICKS,
    MidiExporter,
    NoteEvent,
    SCALES,
    STRUM_RHYTHMS,
    Track,
    apply_swing,
    chord_at_position,
    expand_progression_plan,
    meter_info,
    note_name_to_midi,
    roman_to_semitone_offset,
    voice_chord,
)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class MelodyNote:
    """One note in the plan.

    Coordinates are bar-relative so the plan stays meter- and tempo-
    independent: ``bar`` is the 0-indexed bar; ``beat`` is the fractional
    position in counted pulses within that bar; ``duration`` is in pulses.

    ``scale_degree`` is set when the note was placed via the scale-degree
    grid view (1..7 = diatonic, 8..14 = next octave, etc.). It lets us
    re-key the plan without rewriting absolute pitches.
    """
    bar: int
    beat: float
    pitch: int
    duration: float = 0.5
    velocity: int = 90
    scale_degree: Optional[int] = None


@dataclass
class SectionOverride:
    """Per-bar-range overlay applying a chord-style voicing and/or rhythm
    to the melody. ``mode`` controls how the override interacts with the
    underlying melody notes:

      - ``"stack"``: melody note becomes the BASS of a voiced chord, the
        rhythm controls when stacks fire. Polyphonic — like comping FROM
        the melody.
      - ``"replace"``: discard the bar's melody, fire the rhythm with
        voicings over the chord-progression's active chord.
      - ``"decoration"``: keep melody, sprinkle voicing pitches as grace
        notes between consecutive melody notes.

    Music-theory catalog fields (Track A from the melody-quality plan):

      - ``cadence``: name from :data:`CADENCES`. When set, the LAST melody
        note in this bar range snaps to the cadence's target scale degree,
        giving the section a sense of arrival.
      - ``lick``: name from :data:`MELODIC_LICKS`. When set, the bar
        range's melody is REPLACED with the lick's events placed at the
        section start (single-shot — multi-bar overrides aren't tiled).
      - ``tension_op``: name from :data:`TENSION_OPS`. Round-trips today;
        full rendering is a follow-up.
    """
    start_bar: int
    end_bar: int                   # exclusive
    voicing: Optional[str] = None  # any VOICINGS key
    rhythm: Optional[str] = None   # any STRUM_RHYTHMS or ARPEGGIO_PATTERNS key
    mode: str = "stack"            # "stack" | "replace" | "decoration"
    seed: Optional[int] = None
    cadence: Optional[str] = None      # CADENCES key
    lick: Optional[str] = None         # MELODIC_LICKS key
    tension_op: Optional[str] = None   # TENSION_OPS key


@dataclass
class HarmonyTag:
    """Per-bar-range harmony preset (uses the existing add_harmony engine).

    ``intervals`` overrides the preset's interval stack when set; otherwise
    the preset's defaults apply. ``harmony_rule`` picks a voice-leading
    rule from :data:`HARMONY_OPS` (``voice_leading_smooth``,
    ``contrary_motion``, ...) — defaults to the smooth-Bach baseline when
    ``None``.
    """
    start_bar: int
    end_bar: int
    preset: str                          # "abba"|"queen"|"boston"|"journey"|"elton"|"chicago"
    intervals: Optional[list[int]] = None
    harmony_rule: Optional[str] = None   # HARMONY_OPS key (None = "voice_leading_smooth")


@dataclass
class MelodyPlan:
    """Top-level container for a block's editable melody.

    Plan-level shape controls feed back into :func:`regenerate_bars` so
    re-rolling produces output consistent with the section's intended
    arc — phrase shape, default cadence, and motivic development plan
    travel with the plan.
    """
    bars: int
    time_signature: tuple[int, int] = (4, 4)
    key: str = "C"
    scale: str = "major"
    tempo: float = 120.0
    notes: list[MelodyNote] = field(default_factory=list)
    section_overrides: list[SectionOverride] = field(default_factory=list)
    harmonies: list[HarmonyTag] = field(default_factory=list)
    generation_seed: Optional[int] = None
    phrase_shape: str = "arc"
    default_cadence: Optional[str] = "authentic_v_i"
    motif_development: Optional[list[str]] = None


# ---------------------------------------------------------------------------
# YAML I/O
# ---------------------------------------------------------------------------

def to_yaml(plan: MelodyPlan, path: Union[str, Path]) -> Path:
    data = asdict(plan)
    data["time_signature"] = list(plan.time_signature)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(data, sort_keys=False))
    return p


def from_yaml(path: Union[str, Path]) -> MelodyPlan:
    data = yaml.safe_load(Path(path).read_text())
    ts = tuple(data.get("time_signature", [4, 4]))
    notes = [MelodyNote(**n) for n in data.get("notes", [])]
    # SectionOverride / HarmonyTag gained fields recently — filter unknown
    # keys defensively so older sidecar files keep loading.
    def _drop_unknown(d, cls):
        valid = {f.name for f in cls.__dataclass_fields__.values()}
        return {k: v for k, v in d.items() if k in valid}
    overrides = [SectionOverride(**_drop_unknown(s, SectionOverride))
                 for s in data.get("section_overrides", [])]
    harmonies = [HarmonyTag(**_drop_unknown(h, HarmonyTag))
                 for h in data.get("harmonies", [])]
    return MelodyPlan(
        bars=int(data["bars"]),
        time_signature=ts,
        key=data.get("key", "C"),
        scale=data.get("scale", "major"),
        tempo=float(data.get("tempo", 120.0)),
        notes=notes,
        section_overrides=overrides,
        harmonies=harmonies,
        generation_seed=data.get("generation_seed"),
        phrase_shape=data.get("phrase_shape", "arc"),
        default_cadence=data.get("default_cadence", "authentic_v_i"),
        motif_development=data.get("motif_development"),
    )


# ---------------------------------------------------------------------------
# Conversion helpers
# ---------------------------------------------------------------------------

def pretty_midi_to_tracks(pm, *, skip_melody: bool = True) -> list[Track]:
    """Convert a ``pretty_midi.PrettyMIDI`` to ``MidiExporter.Track``s.

    ``skip_melody`` filters out any instrument whose name contains
    "melody" (case-insensitive) — the Studio uses this to extract the
    accompaniment "bed" from a loaded block so it can be layered under
    the plan's melody during preview without re-rendering the block's
    own melody.
    """
    out: list[Track] = []
    for inst in pm.instruments:
        if skip_melody and "melody" in (inst.name or "").lower():
            continue
        t = Track(
            name=inst.name or "unnamed",
            program=int(inst.program),
            is_drum=bool(inst.is_drum),
            channel=(9 if inst.is_drum else 0),
        )
        for n in inst.notes:
            t.notes.append(NoteEvent(
                pitch=int(n.pitch), start=float(n.start),
                end=float(n.end), velocity=int(n.velocity),
            ))
        out.append(t)
    return out


def bake_plan_to_pm(
    plan: MelodyPlan,
    *,
    bed_tracks: Optional[list] = None,
    progression: Optional[list] = None,
):
    """Render a plan into a complete ``pretty_midi.PrettyMIDI``.

    Combines the rendered melody + (optional) harmony with the
    accompaniment bed (chords / bass / drums) so the returned PrettyMIDI
    is a self-contained block ready for ``block_store.save_block``.

    Used by the Studio's "Save as new block" workflow — the user picks
    a melody source, polishes it, and bakes the whole arrangement to
    disk in one click. The Compose Song library then picks the block up
    via the normal flow (no sibling-melody-yaml indirection required).
    """
    import pretty_midi

    mel_track, harm_track = render_melody_plan(plan, progression=progression)
    exporter = MidiExporter(
        tempo=plan.tempo, time_signature=plan.time_signature,
    )
    exporter.tracks.append(mel_track)
    if harm_track is not None and harm_track.notes:
        exporter.tracks.append(harm_track)
    if bed_tracks:
        exporter.tracks.extend(bed_tracks)
    return exporter.build()


def melody_plan_from_track(
    track: Track,
    *,
    key: str,
    scale: str,
    time_signature: tuple[int, int],
    tempo: float,
    bars: Optional[int] = None,
    seed: Optional[int] = None,
) -> MelodyPlan:
    """Convert a freshly-generated melody ``Track`` to an editable plan.

    Bar/beat coordinates are derived from the meter so the plan stays
    portable across tempo changes. Notes outside ``bars`` (if supplied)
    are trimmed.
    """
    info = meter_info(time_signature)
    beat_dur = 60.0 / tempo
    pulse_unit = beat_dur * info["pulse_unit_in_quarters"]
    bar_dur = info["beats_per_bar"] * pulse_unit

    notes: list[MelodyNote] = []
    for n in track.notes:
        if bar_dur <= 0:
            continue
        bar_idx = int(n.start // bar_dur + 1e-9)
        beat_in_bar = (n.start - bar_idx * bar_dur) / pulse_unit
        dur_beats = (n.end - n.start) / pulse_unit
        # Cast every numeric to plain python primitives — round() and
        # the integer division above preserve numpy types when the source
        # track came from a numpy-driven generator, and pyyaml refuses to
        # serialise np.int64 / np.float64. Be defensive at the boundary.
        notes.append(MelodyNote(
            bar=int(bar_idx),
            beat=float(round(beat_in_bar, 4)),
            pitch=int(n.pitch),
            duration=float(round(dur_beats, 4)),
            velocity=int(n.velocity),
        ))

    if bars is None:
        bars = (max(n.bar for n in notes) + 1) if notes else 4
    else:
        notes = [n for n in notes if n.bar < bars]

    return MelodyPlan(
        bars=bars, time_signature=time_signature, key=key, scale=scale,
        tempo=tempo, notes=notes, generation_seed=seed,
    )


# ---------------------------------------------------------------------------
# Section-override lookup
# ---------------------------------------------------------------------------

def _override_for_bar(
    overrides: list[SectionOverride], bar_idx: int,
) -> Optional[SectionOverride]:
    """First override covering ``bar_idx`` (or None). Earlier-declared
    overrides win on overlap so users can tag a base range and patch a
    sub-range on top by listing the patch first."""
    for ov in overrides:
        if ov.start_bar <= bar_idx < ov.end_bar:
            return ov
    return None


# ---------------------------------------------------------------------------
# Render helpers
# ---------------------------------------------------------------------------

def _resolve_voicing_pitches(
    bass_pitch: int, chord_root_midi: int, quality: str, voicing_name: str,
) -> list[int]:
    """For STACK mode: the melody pitch is the bass; we build the voicing
    above it using the active chord's quality. For REPLACE mode: pass the
    chord root as bass_pitch == chord_root_midi.

    Returns a list of MIDI pitches sorted ascending. Always includes the
    bass pitch as the first element.
    """
    voicing_pitches = voice_chord(chord_root_midi, quality, voicing_name)
    # Transpose stack ABOVE bass_pitch
    if voicing_pitches:
        lowest = min(voicing_pitches)
        # If bass is below the voicing's lowest, no transposition needed.
        # If bass overlaps the voicing, push voicing up so it sits above.
        if bass_pitch >= lowest:
            shift = ((bass_pitch - lowest) // 12 + 1) * 12
            voicing_pitches = [p + shift for p in voicing_pitches]
    return sorted(set([bass_pitch] + voicing_pitches))


def _rhythm_hits(
    rhythm_name: Optional[str], beats_per_bar: int,
) -> list[tuple[float, float, float]]:
    """Resolve a rhythm name to (beat_offset, duration_beats, vel_mult)
    hits. Falls back to a single sustained hit when ``rhythm_name`` is
    missing or unknown (matches the chord-progression pad behavior)."""
    if rhythm_name and rhythm_name in STRUM_RHYTHMS:
        return list(STRUM_RHYTHMS[rhythm_name])
    if rhythm_name and rhythm_name in ARPEGGIO_PATTERNS:
        arp = ARPEGGIO_PATTERNS[rhythm_name]
        hit_dur = beats_per_bar / arp["hits"]
        return [(i * hit_dur, hit_dur * 0.9, 1.0) for i in range(arp["hits"])]
    return [(0.0, float(beats_per_bar), 1.0)]   # pad fallback


# ---------------------------------------------------------------------------
# Top-level render
# ---------------------------------------------------------------------------

def _scale_degree_to_pitch_in_plan(
    degree: int, plan: MelodyPlan, base_octave: int = 4,
) -> int:
    """1-indexed multi-octave scale degree → MIDI pitch in the plan's key."""
    intervals = SCALES.get(plan.scale, SCALES["major"])
    if not intervals:
        return note_name_to_midi(plan.key, base_octave)
    d = max(1, degree) - 1
    octave_offset, inner = divmod(d, len(intervals))
    return (note_name_to_midi(plan.key, base_octave)
            + intervals[inner] + 12 * octave_offset)


def _emit_lick_notes(
    melody_track: Track, lick_name: str, start_bar: int,
    bar_start_time: float, pulse_unit: float, plan: MelodyPlan,
) -> None:
    """Stamp a named lick from :data:`MELODIC_LICKS` at the section's start.
    Single-shot — multi-bar overrides don't tile the lick across bars."""
    spec = MELODIC_LICKS.get(lick_name)
    if not spec:
        return
    for beat_off, degree, dur in spec["events"]:
        t = bar_start_time + beat_off * pulse_unit
        end = t + max(0.05, dur * pulse_unit)
        pitch = _scale_degree_to_pitch_in_plan(int(degree), plan)
        melody_track.notes.append(NoteEvent(pitch, t, end, 95))


def _apply_cadence_to_last_in_range(
    melody_track: Track, cadence_name: str,
    bar_start_time: float, bar_end_time: float, plan: MelodyPlan,
) -> None:
    """Snap the LAST note in ``[bar_start_time, bar_end_time)`` to the
    cadence's target scale-degree pitch class. No-op if the cadence name
    is unknown or no notes fall in the range."""
    spec = CADENCES.get(cadence_name)
    if not spec:
        return
    target_degree = spec["melody"][1]
    intervals = SCALES.get(plan.scale, SCALES["major"])
    if not (1 <= target_degree <= len(intervals)):
        return
    target_pc = (note_name_to_midi(plan.key, 0)
                 + intervals[target_degree - 1]) % 12
    in_range = [n for n in melody_track.notes
                if bar_start_time <= n.start < bar_end_time]
    if not in_range:
        return
    last = max(in_range, key=lambda n: n.start)
    candidates = [
        p for p in range(last.pitch - 12, last.pitch + 13)
        if p % 12 == target_pc
    ]
    if candidates:
        last.pitch = min(candidates, key=lambda p: abs(p - last.pitch))


def render_melody_plan(
    plan: MelodyPlan,
    *,
    progression: Optional[list] = None,
    base_t: float = 0.0,
) -> tuple[Track, Optional[Track]]:
    """Render the plan into (melody_track, harmony_track | None).

    ``progression`` lets the caller override the chord progression used
    for chord-aware section overrides; when omitted, falls back to a
    constant tonic chord (still produces a useful render for plans that
    don't use stack/replace mode).
    """
    info = meter_info(plan.time_signature)
    beats_per_bar = info["beats_per_bar"]
    beat_dur = 60.0 / plan.tempo
    pulse_unit = beat_dur * info["pulse_unit_in_quarters"]
    bar_dur = beats_per_bar * pulse_unit

    melody_track = Track(name="Melody", program=0)
    events = expand_progression_plan(progression or ["I"], plan.bars)

    # Group plan notes by bar
    bar_notes: dict[int, list[MelodyNote]] = {}
    for n in plan.notes:
        bar_notes.setdefault(n.bar, []).append(n)

    for bar_idx in range(plan.bars):
        bar_start_time = base_t + bar_idx * bar_dur
        notes_in_bar = sorted(bar_notes.get(bar_idx, []), key=lambda n: n.beat)
        override = _override_for_bar(plan.section_overrides, bar_idx)

        # No override → straight melody pass-through
        if override is None:
            for n in notes_in_bar:
                t = bar_start_time + n.beat * pulse_unit
                end = t + max(0.05, n.duration * pulse_unit)
                melody_track.notes.append(
                    NoteEvent(int(n.pitch), t, end, int(n.velocity))
                )
            continue

        # Lick override — single-shot stamp at the section's start bar.
        # Subsequent bars in the same override emit nothing so the lick
        # has space; the user can shrink the override range to leave more
        # of the original melody in place.
        if override.lick:
            if bar_idx == override.start_bar:
                _emit_lick_notes(
                    melody_track, override.lick, bar_idx,
                    bar_start_time, pulse_unit, plan,
                )
            continue

        symbol = chord_at_position(events, bar_idx + 0.0001) or "I"
        offset, quality = roman_to_semitone_offset(symbol, plan.scale)
        chord_root_midi = note_name_to_midi(plan.key, 4) + offset
        rhythm_hits = _rhythm_hits(override.rhythm, beats_per_bar)
        is_arp = override.rhythm in ARPEGGIO_PATTERNS

        if override.mode == "replace":
            # Discard melody notes; fire rhythm with chord voicing.
            # Replace mode uses the voicing as-is (no bass-stacking shift).
            voicing = override.voicing or "triad"
            stack = sorted(set(voice_chord(chord_root_midi, quality, voicing)))
            for i, (beat_off, dur_beats, vel_mult) in enumerate(rhythm_hits):
                swung = apply_swing(beat_off, 0.0, grid="8th")
                t = bar_start_time + swung * pulse_unit
                end = t + dur_beats * pulse_unit
                vel = max(1, min(127, int(90 * vel_mult)))
                if is_arp:
                    # Cycle through stack pitches
                    pitch = stack[i % len(stack)]
                    melody_track.notes.append(NoteEvent(pitch, t, end, vel))
                else:
                    for pitch in stack:
                        melody_track.notes.append(NoteEvent(pitch, t, end, vel))

        elif override.mode == "stack":
            # Each melody note triggers a stack at the note's start; the
            # rhythm controls re-strike density within the note's lifetime.
            # Simplified v1: re-strike at each rhythm hit using the
            # melody-note pitch as bass and the voicing above.
            voicing = override.voicing or "triad"
            for n in notes_in_bar:
                stack = _resolve_voicing_pitches(
                    int(n.pitch), chord_root_midi, quality, voicing,
                )
                # Filter rhythm hits to those inside [n.beat, n.beat+n.duration]
                note_start = n.beat
                note_end = n.beat + max(n.duration, 0.1)
                for beat_off, dur_beats, vel_mult in rhythm_hits:
                    if beat_off < note_start - 1e-6:
                        continue
                    if beat_off >= note_end - 1e-6:
                        break
                    swung = apply_swing(beat_off, 0.0, grid="8th")
                    t = bar_start_time + swung * pulse_unit
                    end = min(t + dur_beats * pulse_unit,
                              bar_start_time + note_end * pulse_unit)
                    vel = max(1, min(127, int(n.velocity * vel_mult)))
                    for pitch in stack:
                        melody_track.notes.append(NoteEvent(pitch, t, end, vel))

        else:  # decoration
            # Emit melody, then add light grace notes from the voicing
            # between consecutive melody notes.
            voicing = override.voicing or "triad"
            for n in notes_in_bar:
                t = bar_start_time + n.beat * pulse_unit
                end = t + max(0.05, n.duration * pulse_unit)
                melody_track.notes.append(
                    NoteEvent(int(n.pitch), t, end, int(n.velocity))
                )
            # Ornament: scatter rhythm-hit-derived grace notes ABOVE the
            # melody pitch in the chord stack
            for n in notes_in_bar:
                stack = _resolve_voicing_pitches(
                    int(n.pitch), chord_root_midi, quality, voicing,
                )
                next_beat = n.beat + max(n.duration, 0.1)
                for beat_off, dur_beats, vel_mult in rhythm_hits:
                    if beat_off < n.beat + 0.1:
                        continue
                    if beat_off >= next_beat - 0.05:
                        break
                    t = bar_start_time + beat_off * pulse_unit
                    end = t + min(0.15, dur_beats * pulse_unit) * 0.5
                    # Pick a non-bass pitch from the stack (ornament)
                    pitch = stack[-1] if len(stack) > 1 else stack[0]
                    vel = max(1, min(127, int(n.velocity * 0.6 * vel_mult)))
                    melody_track.notes.append(NoteEvent(pitch, t, end, vel))

    # Per-override cadence forcing — after all notes are emitted, snap
    # the final note inside each override's range to the cadence target.
    # Runs AFTER the bar loop so it sees the actual rendered notes
    # (including lick / stack / replace / decoration output).
    for ov in plan.section_overrides:
        if not ov.cadence:
            continue
        seg_start = base_t + ov.start_bar * bar_dur
        seg_end = base_t + ov.end_bar * bar_dur
        _apply_cadence_to_last_in_range(
            melody_track, ov.cadence, seg_start, seg_end, plan,
        )

    # Harmonies — delegate to MidiExporter.add_harmony per HarmonyTag
    harmony_track: Optional[Track] = None
    if plan.harmonies:
        harmony_track = _render_harmonies(
            plan, melody_track, progression=progression,
            base_t=base_t,
        )

    return melody_track, harmony_track


def _render_harmonies(
    plan: MelodyPlan,
    melody_track: Track,
    *,
    progression: Optional[list],
    base_t: float,
) -> Optional[Track]:
    """Render every HarmonyTag in the plan via MidiExporter.add_harmony,
    splicing each tag's output into one accumulated harmony track. Returns
    ``None`` when no harmony notes were produced so callers can cleanly
    skip appending an empty instrument."""
    accum = Track(name="Harmony", program=0)
    for tag in plan.harmonies:
        exporter = MidiExporter(tempo=plan.tempo, time_signature=plan.time_signature)
        exporter.tracks.append(melody_track)
        # Per-tag voice-leading rule. Default rule is
        # ``voice_leading_smooth`` (Bach baseline); explicit ``None`` on
        # the tag means "use add_harmony's default rule", which today is
        # the same thing — so this also future-proofs against the
        # default flipping.
        rule = tag.harmony_rule or "voice_leading_smooth"
        try:
            exporter.add_harmony(
                source_track=melody_track.name,
                key=plan.key, scale_name=plan.scale,
                bar_start=tag.start_bar, bar_end=tag.end_bar,
                progression=(progression or ["I"]),
                style=tag.preset,
                intervals_steps=tag.intervals,
                harmony_rule=rule,
            )
        except Exception:
            # Log instead of swallow — silent dropouts here masked the
            # progression-tuple regression that took out harmony rendering
            # for paced compositions.
            logger.exception(
                "render_harmony: tag %r failed to render", tag,
            )
            continue
        for t in exporter.tracks:
            if t.name != melody_track.name:
                accum.notes.extend(t.notes)
    return accum if accum.notes else None


# ---------------------------------------------------------------------------
# Selective regeneration
# ---------------------------------------------------------------------------

def regenerate_bars(
    plan: MelodyPlan,
    start_bar: int,
    end_bar: int,
    *,
    melody_style: str = "motif",
    seed: Optional[int] = None,
    progression: Optional[list] = None,
) -> MelodyPlan:
    """Re-roll the notes in ``[start_bar, end_bar)`` and return a NEW plan
    with those notes replaced. Notes outside the range are preserved
    verbatim. The new bars come from ``MidiExporter.add_melody`` using
    the plan's key/scale/tempo/time_signature as context."""
    bars = max(1, end_bar - start_bar)
    exporter = MidiExporter(
        tempo=plan.tempo, time_signature=plan.time_signature,
    )
    # Thread the plan-level shape controls into the regenerator so the
    # re-rolled bars match the section's intended arc — same phrase
    # shape, default cadence, and motivic development plan that the
    # Studio sidebar pinned.
    exporter.add_melody(
        key=plan.key, scale_name=plan.scale, bars=bars,
        octave=4, seed=seed,
        progression=(progression or ["I"]),
        melody_style=melody_style,
        track_name="MelodyRegen",
        bar_offset=0,
        phrase_shape=plan.phrase_shape or "arc",
        cadence=plan.default_cadence,
        motif_development=plan.motif_development,
    )
    regen_track = next(
        (t for t in exporter.tracks if t.name == "MelodyRegen"), None,
    )
    if regen_track is None:
        return plan
    regen_plan = melody_plan_from_track(
        regen_track, key=plan.key, scale=plan.scale,
        time_signature=plan.time_signature, tempo=plan.tempo,
        bars=bars,
    )
    # Shift the new notes from local bars 0..bars-1 to start_bar..end_bar-1
    shifted = [
        MelodyNote(
            bar=n.bar + start_bar, beat=n.beat, pitch=n.pitch,
            duration=n.duration, velocity=n.velocity,
            scale_degree=n.scale_degree,
        )
        for n in regen_plan.notes
    ]
    # Keep notes from the original plan outside the regen range
    kept = [n for n in plan.notes
            if n.bar < start_bar or n.bar >= end_bar]

    return MelodyPlan(
        bars=plan.bars, time_signature=plan.time_signature,
        key=plan.key, scale=plan.scale, tempo=plan.tempo,
        notes=kept + shifted,
        section_overrides=list(plan.section_overrides),
        harmonies=list(plan.harmonies),
        generation_seed=plan.generation_seed,
        phrase_shape=plan.phrase_shape,
        default_cadence=plan.default_cadence,
        motif_development=(
            list(plan.motif_development)
            if plan.motif_development is not None
            else None
        ),
    )
