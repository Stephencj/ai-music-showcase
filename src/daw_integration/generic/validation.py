"""Key-safety / dissonance audit for generated melodies & arpeggios.

Walks every non-drum, non-chord track and classifies every note as one of:

  - ``chord_tone``   — sits on the active chord (always fine).
  - ``in_scale``     — diatonic to the key (fine).
  - ``approach_tone`` — chromatic neighbor of a chord/scale tone, on a weak
    beat and short (< 0.5 of a counted pulse). The pre-existing motif/arp
    generators emit these intentionally as passing tones; we flag them so
    the user can see them in the report but they're not "wrong".
  - ``out_of_key``   — chromatic, not classifiable as an approach tone. The
    audit surfaces these in the UI so Stephen can decide whether to keep
    the dissonance, snap to scale, or re-render the bar.

We also build a short list of in-scale alternatives near each flagged note
so the UI can offer a "snap to nearest" action without recomputing each
time the user clicks a row.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .midi_export import (
    NOTE_NAMES,
    SCALES,
    MidiExporter,
    Track,
    chord_at_position,
    expand_progression_plan,
    meter_info,
    note_name_to_midi,
    roman_to_semitone_offset,
    voice_chord,
)


@dataclass
class NoteIssue:
    """One flagged note in an audited track."""

    track_name: str
    bar_idx: int          # 0-based bar index
    beat: float           # fractional beat-in-bar (counted pulse)
    pitch: int            # MIDI note number
    pitch_name: str       # "C4" / "F#5" — human-readable
    status: str           # "approach_tone" | "out_of_key"
    chord_symbol: str     # active chord at this beat
    suggested_alternatives: list[int] = field(default_factory=list)

    def alt_names(self) -> list[str]:
        return [pitch_to_name(p) for p in self.suggested_alternatives]


def pitch_to_name(pitch: int) -> str:
    """Convert a MIDI pitch (0..127) to a scientific note name like ``C4``."""
    return f"{NOTE_NAMES[pitch % 12]}{pitch // 12 - 1}"


def _scale_pitch_classes(key: str, scale_name: str) -> set[int]:
    """Return the pitch-class set (0..11) of the diatonic scale."""
    root_pc = note_name_to_midi(key, 0) % 12
    intervals = SCALES.get(scale_name, SCALES["major"])
    return {(root_pc + i) % 12 for i in intervals}


def _chord_pitch_classes(chord_symbol: str, key: str, scale_name: str) -> set[int]:
    """Pitch-class set for the chord notes (root/3rd/5th/7th if present)."""
    offset, quality = roman_to_semitone_offset(chord_symbol, scale_name)
    root_midi = note_name_to_midi(key, 0) + offset
    pitches = voice_chord(root_midi, quality, "seventh")
    return {p % 12 for p in pitches}


def classify_note(
    pitch: int,
    chord_symbol: str,
    key: str,
    scale_name: str,
    duration_beats: float,
    is_strong_beat: bool,
) -> str:
    """Classify one note's relationship to the prevailing chord + scale."""
    pc = pitch % 12
    chord_pcs = _chord_pitch_classes(chord_symbol, key, scale_name)
    if pc in chord_pcs:
        return "chord_tone"
    scale_pcs = _scale_pitch_classes(key, scale_name)
    if pc in scale_pcs:
        return "in_scale"
    # Approach-tone heuristic: weak beat, short duration, ±1 semitone of any
    # chord or scale tone. This matches the existing motif-passing-tone logic.
    if not is_strong_beat and duration_beats < 0.5:
        neighbors = {(p + 1) % 12 for p in (chord_pcs | scale_pcs)} | \
                    {(p - 1) % 12 for p in (chord_pcs | scale_pcs)}
        if pc in neighbors:
            return "approach_tone"
    return "out_of_key"


def suggest_alternatives(
    pitch: int, key: str, scale_name: str, max_n: int = 5,
) -> list[int]:
    """Up to ``max_n`` nearest in-scale pitches within ±6 semitones."""
    scale_pcs = _scale_pitch_classes(key, scale_name)
    candidates = []
    for delta in range(-6, 7):
        cand = pitch + delta
        if cand == pitch:
            continue
        if cand < 0 or cand > 127:
            continue
        if cand % 12 in scale_pcs:
            candidates.append(cand)
    candidates.sort(key=lambda c: (abs(c - pitch), c))
    return candidates[:max_n]


def _track_is_chord_like(track: Track) -> bool:
    """Heuristic — chord tracks emit only chord tones by construction, so
    auditing them adds noise. Recognise by name, drum flag, or note density
    (multiple simultaneous notes per onset)."""
    if track.is_drum:
        return True
    name_lc = track.name.lower()
    if "chord" in name_lc or "pad" in name_lc:
        return True
    # Detect polyphonic stacks at the same start time (chord block).
    starts = {}
    for n in track.notes:
        starts.setdefault(round(n.start, 4), 0)
        starts[round(n.start, 4)] += 1
    if starts and (sum(c >= 3 for c in starts.values()) / len(starts)) > 0.4:
        return True
    return False


def audit_track(
    track: Track,
    progression,
    scale_name: str,
    key: str,
    tempo: float,
    time_sig: tuple[int, int],
) -> list[NoteIssue]:
    """Audit one track. Returns issues for ``approach_tone`` and ``out_of_key``
    notes only (chord and in-scale notes are silently OK).

    ``progression`` accepts the same shapes the generators do: ``list[str]``,
    ``list[tuple[str, float]]``, or ``None``. We expand it once via
    :func:`expand_progression_plan` so each note's chord lookup honours
    sub-bar pacing (a half-bar chord change moves which chord a note is
    evaluated against, which matters for melodies that target chord tones).
    """
    if _track_is_chord_like(track):
        return []
    info = meter_info(time_sig)
    beat_dur = 60.0 / tempo
    pulse_unit = beat_dur * info["pulse_unit_in_quarters"]
    bar_dur = info["beats_per_bar"] * pulse_unit
    strong_pulses = set(info["strong_pulses"])

    # Find the largest end_bar so we expand to cover every note's position.
    max_note_end = max((n.end for n in track.notes), default=0.0)
    span_bars = max(1, int(max_note_end / bar_dur) + 2) if bar_dur > 0 else 1
    events = expand_progression_plan(progression, span_bars)

    issues: list[NoteIssue] = []
    for note in track.notes:
        if bar_dur <= 0:
            continue
        bar_idx = int(note.start // bar_dur)
        beat_in_bar = (note.start - bar_idx * bar_dur) / pulse_unit
        position_bars = bar_idx + (beat_in_bar / info["beats_per_bar"])
        chord_symbol = chord_at_position(events, position_bars) or (
            events[0].symbol if events else "I"
        )
        pulse_idx = int(beat_in_bar)
        is_strong = pulse_idx in strong_pulses
        dur_beats = (note.end - note.start) / pulse_unit
        status = classify_note(
            note.pitch, chord_symbol, key, scale_name,
            dur_beats, is_strong,
        )
        if status in ("approach_tone", "out_of_key"):
            issues.append(NoteIssue(
                track_name=track.name,
                bar_idx=bar_idx,
                beat=beat_in_bar,
                pitch=note.pitch,
                pitch_name=pitch_to_name(note.pitch),
                status=status,
                chord_symbol=chord_symbol,
                suggested_alternatives=suggest_alternatives(
                    note.pitch, key, scale_name,
                ),
            ))
    return issues


def audit_midi(
    midi: MidiExporter,
    progression: Optional[list[str]],
    scale_name: str,
    key: str,
) -> list[NoteIssue]:
    """Audit every melodic track in the MidiExporter. Skips drums + chord pads."""
    progression = progression or ["I"]
    all_issues: list[NoteIssue] = []
    for track in midi.tracks:
        all_issues.extend(audit_track(
            track, progression, scale_name, key,
            midi.tempo, midi.time_signature,
        ))
    return all_issues


def apply_suggestion(
    midi: MidiExporter, issue: NoteIssue, new_pitch: int,
) -> bool:
    """Mutate the MidiExporter so the note flagged in ``issue`` becomes
    ``new_pitch``. Returns True if a note was rewritten.

    Matches by (track_name, pitch, bar_idx, fractional beat). If the user
    has run the audit twice and the underlying track shifted, this may
    silently no-op — the UI should re-run the audit after each apply.
    """
    target_track = next(
        (t for t in midi.tracks if t.name == issue.track_name), None,
    )
    if target_track is None:
        return False
    info = meter_info(midi.time_signature)
    beat_dur = 60.0 / midi.tempo
    pulse_unit = beat_dur * info["pulse_unit_in_quarters"]
    bar_dur = info["beats_per_bar"] * pulse_unit
    target_start = issue.bar_idx * bar_dur + issue.beat * pulse_unit
    for n in target_track.notes:
        if (n.pitch == issue.pitch
                and abs(n.start - target_start) < 1e-3):
            n.pitch = new_pitch
            return True
    return False
