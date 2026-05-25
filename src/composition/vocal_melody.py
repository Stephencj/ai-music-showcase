"""Compose a sung vocal melody **from lyrics** — the third step of the song
workflow (generate instrumental → write lyrics to the structure → write the
melody to the lyrics).

The input is the lyric already split into lines with a syllable count per line
(the app's ``melody_request_params``), plus the song's sections, per-bar
chords, key/scale and tempo. The output is the note-plan ``apply_melody_plan``
consumes: ``{"tempo", "lead": [[midi, start_beat, dur_beat], …], "harmony": …}``.

How we create the melody (deterministic, musical, syllable-driven):
  * **one note per syllable**, walked in lyric order so the words line up.
  * each line is a **phrase** — its notes are evenly spaced across the slice of
    its section's bars proportional to the line's syllables, with a short rest
    at the end for a breath.
  * pitches come from the **key/scale**, following a per-section contour —
    verses sit low and stepwise, choruses ride a higher repeated **motif** (so
    both choruses share a hook), the bridge contrasts.
  * the **first note of each phrase is snapped to the bar's chord root** so
    phrases land consonant on the harmony.
  * choruses get a **diatonic third below** stacked as harmony.

Pitches stay in a singable, clarity-friendly band (tonic ~F#3-class up to ~a
tenth), so the result reads well and doesn't trip the clarity register-cap.
"""
from __future__ import annotations

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

# Per-section melodic contour as scale-degree indices (0 = tonic). Choruses ride
# a higher motif (reused → hook); verses sit low; the bridge contrasts.
_CONTOURS = {
    "intro": (4, 3, 4, 5),
    "verse": (3, 4, 5, 4, 2, 3, 5, 4, 2, 3),
    "prechorus": (3, 4, 5, 6, 7, 6),
    "chorus": (7, 7, 8, 7, 5, 7, 9, 8, 6, 7),
    "bridge": (2, 4, 3, 5, 3, 1, 2, 4),
    "outro": (5, 4, 3, 2, 1, 0, 2, 1),
}


def _pc(name: str) -> int:
    return _NAME2PC.get((name or "C").strip().upper(), 0)


def build_scale(key: str, scale: str, *, lo: int = 53, span: int = 18) -> list[int]:
    """Ascending MIDI notes of ``key``/``scale`` from the lowest tonic ≥ ``lo``
    up ``span`` semitones — a singable ~1.5-octave ladder (index = scale degree
    from the tonic)."""
    steps = _SCALE_STEPS.get((scale or "major").lower(), _SCALE_STEPS["major"])
    pc = _pc(key)
    tonic = pc
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


def _role_contour(role: str) -> tuple[int, ...]:
    return _CONTOURS.get(role, _CONTOURS["verse"])


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
) -> dict:
    """Build a ``{tempo, lead, harmony}`` note-plan that sings ``lines`` across
    ``sections``. ``sections`` are ``{role, start_bar, end_bar}`` (inclusive
    end bar). Lines are assigned to sections in order, proportionally to each
    section's bar length, so note order matches lyric order (what the renderer
    aligns words against)."""
    scale_notes = build_scale(key, scale)
    chords = chords_per_bar or []
    n_lines = min(len(lines), len(syllables_per_line))
    syls = [max(0, int(syllables_per_line[i])) for i in range(n_lines)]

    def degree_midi(d: int) -> int:
        return scale_notes[max(0, min(len(scale_notes) - 1, d))]

    def chord_root_near(bar: int, around: int) -> int:
        if not chords or bar < 0 or bar >= len(chords):
            return around
        pc = _pc(chords[bar])
        cands = [m for m in scale_notes if m % 12 == pc]
        return min(cands, key=lambda m: abs(m - around)) if cands else around

    # --- assign lines to sections (in order, ~proportional to bars) ---------
    secs = [s for s in sections if s.get("end_bar") is not None] or sections
    if not secs:
        secs = [{"role": "verse", "start_bar": 0,
                 "end_bar": max(0, (sum(syls) // beats_per_bar) or 1)}]
    bar_weights = [max(1, int(s["end_bar"]) - int(s["start_bar"]) + 1) for s in secs]
    total_w = sum(bar_weights)
    # how many lines each section carries (proportional, every section ≥0, sum exact)
    counts = [0] * len(secs)
    acc = 0.0
    assigned = 0
    for i, w in enumerate(bar_weights):
        if i == len(secs) - 1:
            counts[i] = n_lines - assigned
        else:
            acc += n_lines * (w / total_w)
            take = int(round(acc)) - assigned
            take = max(0, min(take, n_lines - assigned))
            counts[i] = take
            assigned += take
    # any leftover (rounding) to the last non-empty section
    drift = n_lines - sum(counts)
    if drift:
        counts[-1] += drift

    lead: list[list] = []
    harmony: list[list] = []
    line_idx = 0
    for si, sec in enumerate(secs):
        role = str(sec.get("role") or "verse")
        contour = _role_contour(role)
        is_chorus = role == "chorus"
        sb, eb = int(sec["start_bar"]), int(sec["end_bar"])
        sec_start = sb * beats_per_bar
        sec_beats = (eb - sb + 1) * beats_per_bar
        my = list(range(line_idx, line_idx + counts[si]))
        line_idx += counts[si]
        sec_syl = sum(syls[i] for i in my) or 1
        cursor = float(sec_start)
        ci = 0
        last = -1.0
        for li in my:
            n = syls[li]
            if n <= 0:
                continue
            line_beats = sec_beats * (n / sec_syl)
            sing = line_beats * 0.80                 # ~20% rest for a breath
            step = sing / n
            dur = max(0.25, min(1.0, step))
            for k in range(n):
                start = round((cursor + k * step) / 0.25) * 0.25
                if start <= last:
                    start = last + 0.25
                bar = min(len(chords) - 1, int(start // beats_per_bar)) if chords else -1
                deg = contour[ci % len(contour)]
                midi = chord_root_near(bar, degree_midi(deg)) if k == 0 else degree_midi(deg)
                lead.append([midi, round(start, 3), round(dur, 3)])
                if is_chorus:
                    harmony.append([degree_midi(max(0, deg - 2)), round(start, 3), round(dur, 3)])
                last = start
                ci += 1
            cursor += line_beats

    return {"tempo": float(tempo), "lead": lead, "harmony": harmony}
