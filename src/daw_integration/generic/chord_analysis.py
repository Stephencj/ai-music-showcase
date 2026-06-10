"""Chord / score-data extraction from a rendered (or imported) MIDI file.

The composer doesn't persist the literal per-bar chord symbols it rendered —
they fall out of a seeded progression run. Rather than try to re-derive that
(fragile, seed-dependent), we read the harmony back out of the MIDI that was
actually rendered. That reflects what's truly in the audio and works just as
well for *imported* MIDI later (Phase D: scan/listen → progression).

The public entry point is :func:`extract_score_data`, which returns a plain
dict (JSON-serialisable) consumed by the ``/api/blocks/{name}/score-data``
endpoint and, through it, the practice-mode chord chart and the piano/guitar
chord diagrams.
"""

from __future__ import annotations

from typing import Optional

from .midi_export import NOTE_NAMES, meter_info

# Chord templates as pitch-class offsets from the root. Ordered roughly from
# simplest to richest; detection scores each independently so order only acts
# as a tie-break (earlier = preferred when scores match).
_CHORD_TEMPLATES: list[tuple[str, tuple[int, ...]]] = [
    ("maj",   (0, 4, 7)),
    ("min",   (0, 3, 7)),
    ("dim",   (0, 3, 6)),
    ("aug",   (0, 4, 8)),
    ("sus2",  (0, 2, 7)),
    ("sus4",  (0, 5, 7)),
    ("6",     (0, 4, 7, 9)),
    ("min6",  (0, 3, 7, 9)),
    ("7",     (0, 4, 7, 10)),
    ("maj7",  (0, 4, 7, 11)),
    ("min7",  (0, 3, 7, 10)),
    ("dim7",  (0, 3, 6, 9)),
    ("m7b5",  (0, 3, 6, 10)),
]

# Display suffix per quality for the absolute chord symbol (e.g. "Gmaj" → "G").
_QUALITY_SUFFIX = {
    "maj": "", "min": "m", "dim": "°", "aug": "+",
    "sus2": "sus2", "sus4": "sus4", "6": "6", "min6": "m6",
    "7": "7", "maj7": "maj7", "min7": "m7", "dim7": "°7", "m7b5": "m7b5",
}

# Qualities whose Roman numeral is written lower-case (minor-flavoured).
_MINOR_QUALITIES = {"min", "min6", "min7", "dim", "dim7", "m7b5"}

# Roman-numeral suffix (case already conveys major/minor, so we only add the
# colour beyond the basic triad).
_ROMAN_SUFFIX = {
    "maj": "", "min": "", "dim": "°", "aug": "+",
    "sus2": "sus2", "sus4": "sus4", "6": "6", "min6": "6",
    "7": "7", "maj7": "maj7", "min7": "7", "dim7": "°7", "m7b5": "ø7",
}

_ROMAN_NUMERALS = ["I", "II", "III", "IV", "V", "VI", "VII"]

# semitone-from-tonic → (nashville degree number, accidental prefix)
_DEGREE_MAP = {
    0: ("1", ""), 1: ("2", "b"), 2: ("2", ""), 3: ("3", "b"), 4: ("3", ""),
    5: ("4", ""), 6: ("5", "b"), 7: ("5", ""), 8: ("6", "b"), 9: ("6", ""),
    10: ("7", "b"), 11: ("7", ""),
}

_FLAT_TO_SHARP = {
    "Db": "C#", "Eb": "D#", "Gb": "F#", "Ab": "G#", "Bb": "A#",
    "Cb": "B", "Fb": "E",
}


def _tonic_pc(key: str) -> int:
    k = _FLAT_TO_SHARP.get(key, key)
    try:
        return NOTE_NAMES.index(k)
    except ValueError:
        return 0


def _label_chord(root_pc: int, quality: str, tonic_pc: int) -> dict:
    """Build absolute symbol + Roman numeral + Nashville number for a chord."""
    root_name = NOTE_NAMES[root_pc % 12]
    symbol = root_name + _QUALITY_SUFFIX.get(quality, "")

    rel = (root_pc - tonic_pc) % 12
    num, acc = _DEGREE_MAP[rel]
    base = _ROMAN_NUMERALS[int(num) - 1]
    roman_base = base.lower() if quality in _MINOR_QUALITIES else base
    roman = acc + roman_base + _ROMAN_SUFFIX.get(quality, "")

    # Nashville: degree number + minor/dim mark + colour, accidental prefixed.
    nash_quality = ""
    if quality in _MINOR_QUALITIES and quality not in ("dim", "dim7", "m7b5"):
        nash_quality = "m"
    elif quality in ("dim", "dim7", "m7b5"):
        nash_quality = "°"
    elif quality == "aug":
        nash_quality = "+"
    nash_colour = ""
    if quality in ("7", "maj7", "min7"):
        nash_colour = "7"
    elif quality in ("6", "min6"):
        nash_colour = "6"
    elif quality in ("sus2", "sus4"):
        nash_colour = quality
    nashville = acc + num + nash_quality + nash_colour

    return {
        "root": root_name,
        "quality": quality,
        "symbol": symbol,
        "roman": roman,
        "nashville": nashville,
    }


def _detect_chord(
    chroma: list[float], bass_pc: Optional[int]
) -> Optional[tuple[int, str]]:
    """Pick the best (root_pc, quality) for a 12-bin pitch-class weight vector.

    Template matching: score = (weight on chord tones) / sqrt(#chord tones),
    with a small bonus when the root matches the sounding bass note. Returns
    None for an effectively empty bar (no chord / N.C.).
    """
    total = sum(chroma)
    if total <= 1e-9:
        return None
    c = [w / total for w in chroma]

    best = None
    best_score = -1.0
    for root in range(12):
        for quality, offsets in _CHORD_TEMPLATES:
            tones = [(root + o) % 12 for o in offsets]
            on = sum(c[pc] for pc in tones)
            off = sum(c[pc] for pc in range(12) if pc not in tones)
            score = on / (len(tones) ** 0.5) - 0.35 * off
            if bass_pc is not None and root == bass_pc:
                score += 0.18
            if score > best_score:
                best_score = score
                best = (root, quality)
    return best


def _chords_from_progression(stored: list, bars: int, bar_seconds: float,
                             tonic_pc: int) -> list[dict]:
    """Build per-bar chord entries from the composer's stored realized
    progression. Each bar shows the chord active at its downbeat (sub-bar
    changes collapse to one chord per bar, like the detection path)."""
    per_bar: list[dict] = []
    for bar in range(bars):
        t0 = bar * bar_seconds
        entry = {"bar": bar, "start_time": round(t0, 4),
                 "end_time": round(t0 + bar_seconds, 4)}
        chord = None
        for c in stored:
            if float(c["start_bar"]) <= bar + 1e-6 < float(c["end_bar"]):
                chord = c
                break
        if chord is None:
            entry.update({"root": None, "quality": None, "symbol": "N.C.",
                          "roman": "", "nashville": ""})
        else:
            entry.update(_label_chord(int(chord["root_pc"]) % 12,
                                      str(chord["quality"]), tonic_pc))
        per_bar.append(entry)
    return per_bar


def extract_score_data(pm, meta: dict) -> dict:
    """Read per-bar chords + bar timings out of a rendered MIDI.

    Args:
        pm: a ``pretty_midi.PrettyMIDI`` instance.
        meta: block metadata (``spec`` holds key/scale/tempo/sections).

    Returns a JSON-serialisable dict — see module docstring for consumers.
    """
    # Lazy import so callers that never touch vocals don't pay for it.
    from src.models.vocals.lyrics import select_vocal_tracks

    spec = meta.get("spec") or {}
    key = spec.get("key") or meta.get("key") or "C"
    scale = spec.get("scale") or meta.get("scale") or "major"
    ts = meta.get("time_signature") or spec.get("time_signature") or [4, 4]
    ts = [int(ts[0]), int(ts[1])]
    tempo = float(spec.get("tempo") or meta.get("tempo") or 120.0)
    bars = int(meta.get("bars") or spec.get("bars") or 0)

    mi = meter_info((ts[0], ts[1]))
    quarter = 60.0 / tempo
    bar_seconds = mi["bar_in_quarters"] * quarter

    # Identify the lead/melody so we don't fold it into harmony detection.
    try:
        lead, _harms = select_vocal_tracks(pm)
    except Exception:
        lead = None

    harmony_insts = [
        inst for inst in pm.instruments
        if not inst.is_drum and inst is not lead
    ]
    # If excluding the lead left nothing (rare instrumental edge), fall back to
    # every pitched track.
    if not harmony_insts:
        harmony_insts = [inst for inst in pm.instruments if not inst.is_drum]

    if bar_seconds > 0:
        end = max((n.end for inst in pm.instruments for n in inst.notes),
                  default=0.0)
        content_bars = round(end / bar_seconds)
        # Cover the whole recording. Scanned/imported MIDI can have measures
        # that don't sum to the meter, so the audio runs longer than the measure
        # count implies — without this the chart/cursor stop early and drift
        # behind the audio. Generated songs are uniform, so content_bars matches
        # the measure count and this changes nothing for them.
        bars = max(bars, content_bars, 1)

    tonic = _tonic_pc(key)

    # Prefer the composer's stored realized progression (exact intended chords)
    # over re-detecting from the audio — better for the teaching chart. Stored
    # as [{root_pc, quality, start_bar, end_bar}, …] covering the song's bars.
    stored = spec.get("progression")
    if stored:
        per_bar = _chords_from_progression(stored, bars, bar_seconds, tonic)
    else:
        per_bar = []
        for bar in range(bars):
            t0 = bar * bar_seconds
            t1 = t0 + bar_seconds
            chroma = [0.0] * 12
            lowest_pitch = None
            lowest_w = 0.0
            for inst in harmony_insts:
                for n in inst.notes:
                    ov = min(n.end, t1) - max(n.start, t0)
                    if ov <= 0:
                        continue
                    chroma[n.pitch % 12] += ov
                    if lowest_pitch is None or n.pitch < lowest_pitch:
                        lowest_pitch = n.pitch
                        lowest_w = ov
            bass_pc = lowest_pitch % 12 if lowest_pitch is not None else None
            detected = _detect_chord(chroma, bass_pc)
            entry = {"bar": bar, "start_time": round(t0, 4), "end_time": round(t1, 4)}
            if detected is None:
                entry.update({"root": None, "quality": None, "symbol": "N.C.",
                              "roman": "", "nashville": ""})
            else:
                entry.update(_label_chord(detected[0], detected[1], tonic))
            per_bar.append(entry)

    # Merge consecutive identical chords into spans for chart display.
    spans: list[dict] = []
    for e in per_bar:
        if spans and spans[-1]["symbol"] == e["symbol"]:
            spans[-1]["end_bar"] = e["bar"]
            spans[-1]["end_time"] = e["end_time"]
        else:
            spans.append({
                "start_bar": e["bar"], "end_bar": e["bar"],
                "start_time": e["start_time"], "end_time": e["end_time"],
                "root": e["root"], "quality": e["quality"],
                "symbol": e["symbol"], "roman": e["roman"],
                "nashville": e["nashville"],
            })

    sections = []
    for s in (spec.get("sections") or []):
        sb = int(s.get("start_bar") or 0)
        eb = int(s.get("end_bar") or sb)
        sections.append({
            "label": s.get("label") or s.get("role") or "Section",
            "role": s.get("role") or "verse",
            "start_bar": sb, "end_bar": eb,
            "start_time": round(sb * bar_seconds, 4),
            "end_time": round((eb + 1) * bar_seconds, 4),
        })

    return {
        "key": key,
        "scale": scale,
        "tempo": tempo,
        "time_signature": ts,
        "bars": bars,
        "bar_seconds": round(bar_seconds, 4),
        "beats_per_bar": mi["beats_per_bar"],
        "sections": sections,
        "chords": per_bar,
        "chord_spans": spans,
    }
