"""Compose a sung vocal melody **from lyrics** — step 3 of the song workflow
(generate instrumental → write lyrics to the structure → write the melody to
the lyrics).

The melody is created with the composition **engine** (``compose_song`` ->
``MidiExporter.add_melody``), which gives motif development, chord-tone
anchoring, phrase shapes and a clean rhythm — the same way every other line in
the project is written ("how we create melodies"). We then **refit** each
section's engine notes to that section's lyric **syllable count** (merge the
shortest notes into neighbours / split the longest), so the result keeps the
engine's pitches, phrasing and grid rhythm while staying exactly one note per
syllable (what the word-aligner needs).

Input is the lyric split into lines with a syllable count per line plus the
song's sections / key / scale / tempo / genre (the app's
``melody_request_params``). Output is the note-plan ``apply_melody_plan``
consumes: ``{"tempo", "lead": [[midi, start_beat, dur_beat], …], "harmony": …}``.
"""
from __future__ import annotations

import logging
import tempfile
from pathlib import Path

logger = logging.getLogger("ai_music_studio.composition.vocal_melody")

_NAME2PC = {"C": 0, "C#": 1, "DB": 1, "D": 2, "D#": 3, "EB": 3, "E": 4,
            "F": 5, "F#": 6, "GB": 6, "G": 7, "G#": 8, "AB": 8, "A": 9,
            "A#": 10, "BB": 10, "B": 11}

_SCALE_STEPS = {
    "major": (0, 2, 4, 5, 7, 9, 11),
    "minor": (0, 2, 3, 5, 7, 8, 10),
    "natural_minor": (0, 2, 3, 5, 7, 8, 10),
    "dorian": (0, 2, 3, 5, 7, 9, 10),
    "mixolydian": (0, 2, 4, 5, 7, 9, 10),
}

# Fallback grid contour (only used when the engine path is unavailable).
_CONTOURS = {
    "intro": (4, 3, 4, 5), "verse": (3, 4, 5, 4, 2, 3, 5, 4),
    "prechorus": (3, 4, 5, 6, 7, 6), "chorus": (7, 7, 8, 7, 5, 7, 9, 7),
    "bridge": (2, 4, 3, 5, 3, 2), "outro": (5, 4, 3, 2, 1, 0),
}


def _pc(name: str) -> int:
    return _NAME2PC.get((name or "C").strip().upper(), 0)


def build_scale(key: str, scale: str, *, lo: int = 53, span: int = 18) -> list[int]:
    """Ascending MIDI notes of ``key``/``scale`` from the lowest tonic ≥ ``lo``
    up ``span`` semitones (index = scale degree). Used for harmony + fallback."""
    steps = _SCALE_STEPS.get((scale or "major").lower(), _SCALE_STEPS["major"])
    tonic = _pc(key)
    while tonic < lo:
        tonic += 12
    out: list[int] = []
    octave = 0
    while True:
        for st in steps:
            m = tonic + 12 * octave + st
            if m > tonic + span:
                return out
            out.append(m)
        octave += 1


def _third_below(key: str, scale: str, pitch: int) -> int:
    """A diatonic third below ``pitch`` in ``key``/``scale`` (for harmony)."""
    steps = _SCALE_STEPS.get((scale or "major").lower(), _SCALE_STEPS["major"])
    pcs = {(_pc(key) + s) % 12 for s in steps}
    for drop in (3, 4, 2):                       # m3, M3, then a 2nd as a fallback
        if (pitch - drop) % 12 in pcs:
            return pitch - drop
    return pitch - 3


def _assign_lines_to_sections(n_lines: int, secs: list[dict], beats_per_bar: int) -> list[int]:
    """How many lyric lines each section carries — proportional to its bars, in
    order (so note order matches lyric order). Returns a per-section count."""
    weights = [max(1, int(s["end_bar"]) - int(s["start_bar"]) + 1) for s in secs]
    total = sum(weights) or 1
    counts = [0] * len(secs)
    assigned = 0
    acc = 0.0
    for i, w in enumerate(weights):
        if i == len(secs) - 1:
            counts[i] = n_lines - assigned
        else:
            acc += n_lines * (w / total)
            take = max(0, min(int(round(acc)) - assigned, n_lines - assigned))
            counts[i] = take
            assigned += take
    if n_lines - sum(counts):
        counts[-1] += n_lines - sum(counts)
    return counts


def _refit(notes: list[list], target: int) -> list[list]:
    """Adjust a time-ordered ``[pitch, start_beat, dur_beat]`` list to exactly
    ``target`` notes, preserving pitches and the span's timing: merge the
    shortest note into a neighbour (the kept note sustains over it) when too
    many; split the longest note in half (repeat the pitch) when too few."""
    out = [list(n) for n in notes]
    if target <= 0 or not out:
        return []
    while len(out) > target:
        i = min(range(len(out)), key=lambda j: out[j][2])
        if i == 0:
            end1 = out[1][1] + out[1][2]
            out[1][1] = out[0][1]
            out[1][2] = end1 - out[0][1]
        else:
            end_i = out[i][1] + out[i][2]
            out[i - 1][2] = end_i - out[i - 1][1]
        del out[i]
    while len(out) < target:
        i = max(range(len(out)), key=lambda j: out[j][2])
        p, s, d = out[i]
        h = round(d / 2.0, 4)
        out[i] = [p, s, h]
        out.insert(i + 1, [p, round(s + h, 4), round(d - h, 4)])
    return out


def _engine_lead(genre, sections, key, scale, tempo, seed) -> list[list]:
    """Engine vocal melody as time-ordered ``[pitch, start_beat, dur_beat]``."""
    import pretty_midi
    from src.composition.song_composer import compose_song
    from src.models.vocals.lyrics import monophonic_line, select_vocal_tracks

    out = compose_song(
        genre=genre, sections=[dict(s) for s in sections], seed=seed,
        enabled_instruments=("drum_kit", "electric_bass", "piano", "vocal_lead"),
        key=key, scale=scale, tempo=tempo, skip_audio=True,
        output_dir=Path(tempfile.mkdtemp(prefix="vmel_")))
    pm = pretty_midi.PrettyMIDI(out["midi_path"])
    lead, _ = select_vocal_tracks(pm)
    lead = monophonic_line(lead)
    spb = 60.0 / float(tempo)
    return [[int(p), s / spb, max(0.05, e - s) / spb] for (p, s, e) in lead]


def _grid_phrase(scale_notes, role, t0, t1, n, beats_per_bar) -> list[list]:
    """Fallback: ``n`` clean-grid notes in ``[t0, t1)`` on a role contour."""
    if n <= 0 or not scale_notes:
        return []
    contour = _CONTOURS.get(role, _CONTOURS["verse"])
    span = (t1 - t0) * 0.85
    step = max(0.25, round((span / n) / 0.25) * 0.25)
    out = []
    t = float(t0)
    for k in range(n):
        deg = contour[k % len(contour)]
        out.append([scale_notes[max(0, min(len(scale_notes) - 1, deg))], round(t, 3), step])
        t += step
    return out


def melody_plan_from_lyrics(
    *,
    lines: list[str],
    syllables_per_line: list[int],
    sections: list[dict],
    chords_per_bar: list[str] | None = None,
    key: str = "C",
    scale: str = "major",
    tempo: float = 120.0,
    beats_per_bar: int = 4,
    genre: str | None = None,
    seed: int = 7,
) -> dict:
    """Compose a ``{tempo, lead, harmony}`` note-plan from the lyric. Uses the
    composition engine's melody (per the song's ``genre``) refitted to the
    lyric's syllables; falls back to a clean-grid contour if the engine path is
    unavailable (e.g. unknown genre)."""
    n_lines = min(len(lines), len(syllables_per_line))
    syls = [max(0, int(syllables_per_line[i])) for i in range(n_lines)]
    secs = [s for s in sections
            if s.get("start_bar") is not None and s.get("end_bar") is not None]
    if not secs:
        end = max(1, sum(syls) // max(1, beats_per_bar))
        secs = [{"role": "verse", "start_bar": 0, "end_bar": end}]

    counts = _assign_lines_to_sections(n_lines, secs, beats_per_bar)
    line_at = 0
    sec_target = []
    for c in counts:
        sec_target.append(sum(syls[line_at:line_at + c]))
        line_at += c

    # Engine melody (the quality path); fall back to a clean grid on failure.
    engine: list[list] = []
    if genre:
        try:
            engine = _engine_lead(genre, secs, key, scale, tempo, seed)
        except Exception as exc:  # noqa: BLE001
            logger.warning("engine melody unavailable (%s) — grid fallback", exc)
            engine = []

    scale_notes = build_scale(key, scale)
    lead: list[list] = []
    harmony: list[list] = []
    for si, sec in enumerate(secs):
        target = sec_target[si]
        if target <= 0:
            continue
        sb, eb = int(sec["start_bar"]), int(sec["end_bar"])
        t0, t1 = sb * beats_per_bar, (eb + 1) * beats_per_bar
        role = str(sec.get("role") or "verse")
        span = [n for n in engine if t0 <= n[1] < t1]
        fitted = _refit(span, target) if span else _grid_phrase(
            scale_notes, role, t0, t1, target, beats_per_bar)
        for p, s, d in fitted:
            lead.append([int(p), round(float(s), 3), round(max(0.1, float(d)), 3)])
            if role == "chorus":
                harmony.append([_third_below(key, scale, int(p)),
                                round(float(s), 3), round(max(0.1, float(d)), 3)])

    # Normalise into a singable register — the engine writes around octave 5;
    # shift the whole line (harmony with it, to keep the interval) by octaves so
    # the median sits ~C4, so the stored melody reads sensibly and barely needs
    # the render's transpose.
    if lead:
        import statistics
        med = statistics.median(p for p, _, _ in lead)
        shift = 0
        while med + shift > 67:
            shift -= 12
        while med + shift < 55:
            shift += 12
        if shift:
            lead = [[p + shift, s, d] for p, s, d in lead]
            harmony = [[p + shift, s, d] for p, s, d in harmony]

    lead.sort(key=lambda x: x[1])
    harmony.sort(key=lambda x: x[1])
    return {"tempo": float(tempo), "lead": lead, "harmony": harmony}
