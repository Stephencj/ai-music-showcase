"""
MIDI generation and export utilities using pretty_midi.

Create MIDI files from note sequences, chord progressions, melodies,
and drum patterns for import into any DAW.
"""

import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Union

import numpy as np
import pretty_midi


# ---------------------------------------------------------------------------
# Music theory constants
# ---------------------------------------------------------------------------

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# Semitone intervals from root for common scales
SCALES = {
    "major":            [0, 2, 4, 5, 7, 9, 11],
    "minor":            [0, 2, 3, 5, 7, 8, 10],
    "harmonic_minor":   [0, 2, 3, 5, 7, 8, 11],
    "melodic_minor":    [0, 2, 3, 5, 7, 9, 11],
    "pentatonic_major": [0, 2, 4, 7, 9],
    "pentatonic_minor": [0, 3, 5, 7, 10],
    "blues":            [0, 3, 5, 6, 7, 10],
    # 9-note major/minor blend over dominant chords — the shared lead
    # vocabulary of blues, rock and country (mixolydian + blues scale).
    "mixolydian_blues": [0, 2, 3, 4, 5, 6, 7, 9, 10],
    "dorian":           [0, 2, 3, 5, 7, 9, 10],
    "phrygian":         [0, 1, 3, 5, 7, 8, 10],   # Spanish/flamenco color
    "lydian":           [0, 2, 4, 6, 7, 9, 11],   # major with #4 — Vai / dreamy
    "mixolydian":       [0, 2, 4, 5, 7, 9, 10],   # major with b7 — folk / blues
    "locrian":          [0, 1, 3, 5, 6, 8, 10],   # half-diminished — metal
    "phrygian_dominant": [0, 1, 4, 5, 7, 8, 10],  # flamenco/klezmer ("Spanish Phrygian")
    # Indian (Hindustani thaats)
    "raga_yaman":       [0, 2, 4, 6, 7, 9, 11],   # ~Lydian
    "raga_bhairav":     [0, 1, 4, 5, 7, 8, 11],   # double-harmonic-major sound
    "raga_bhairavi":    [0, 1, 3, 5, 7, 8, 10],   # ~Phrygian — soulful, evening
    # Middle Eastern (maqamat — equal-temperament approximations)
    "maqam_hijaz":      [0, 1, 4, 5, 7, 8, 10],   # iconic "Arab Phrygian" hijaz tetrachord
    "maqam_rast":       [0, 2, 4, 5, 7, 9, 10],   # major-ish with lowered 7
    "maqam_nahawand":   [0, 2, 3, 5, 7, 8, 10],   # ~natural minor
    # East/Southeast Asian
    "gamelan_slendro":  [0, 2, 5, 7, 10],         # 5-tone Indonesian gamelan (ET approx)
    "hirajoshi":        [0, 2, 3, 7, 8],          # Japanese pentatonic
    "in_sen":           [0, 1, 5, 7, 10],         # Japanese folk pentatonic
}

# Chord formulas as scale-degree offsets (0-indexed)
CHORD_FORMULAS = {
    "maj":   [0, 4, 7],
    "min":   [0, 3, 7],
    "dim":   [0, 3, 6],
    "aug":   [0, 4, 8],
    "7":     [0, 4, 7, 10],
    "maj7":  [0, 4, 7, 11],
    "min7":  [0, 3, 7, 10],
    "sus2":  [0, 2, 7],
    "sus4":  [0, 5, 7],
}

# General MIDI drum map (channel 9, note → sound)
GM_DRUMS = {
    "kick": 36, "snare": 38, "hihat_closed": 42, "hihat_open": 46,
    "tom_low": 45, "tom_mid": 47, "tom_high": 50,
    "crash": 49, "ride": 51, "ride_bell": 53, "clap": 39, "rim": 37,
    # Latin / hand percussion (standard GM percussion notes)
    "tambourine": 54, "cowbell": 56,
    "bongo_high": 60, "bongo_low": 61,
    "conga_mute": 62, "conga_open": 63, "conga_low": 64,
    "timbale_high": 65, "timbale_low": 66,
    "agogo_high": 67, "agogo_low": 68,
    "cabasa": 69, "maracas": 70,
    "guiro_short": 73, "guiro_long": 74, "clave": 75,
    "woodblock_high": 76, "woodblock_low": 77,
}

# Base roman numeral → scale-degree index (0-6). Matched longest-first.
_ROMAN_BASES = [
    ("VIII", 7), ("VII", 6), ("III", 2), ("IV", 3), ("VI", 5), ("II", 1), ("V", 4), ("I", 0),
    ("viii", 7), ("vii", 6), ("iii", 2), ("iv", 3), ("vi", 5), ("ii", 1), ("v", 4), ("i", 0),
]


FLAT_TO_SHARP = {
    "Db": "C#", "Eb": "D#", "Gb": "F#", "Ab": "G#", "Bb": "A#",
    "Cb": "B",  "Fb": "E",  # enharmonic edge cases
}


# Time-signature support
#
# Convention: pattern offsets and durations in STRUM_RHYTHMS / drum tables /
# bass-pattern code use COUNTED PULSES — quarter notes for 4/4 and 3/4,
# eighth notes for 6/8. Conversion to seconds uses ``pulse_unit`` (which is
# beat_duration in 4/4 + 3/4, beat_duration / 2 in 6/8).
#
# ``tempo`` itself is always quarter-notes-per-minute (pretty_midi convention).
# For 6/8 cues, set tempo to give the desired dotted-quarter felt-pulse:
# tempo=126 → 84 dotted-quarter pulses per minute (typical adventure feel).

def meter_info(time_sig: tuple[int, int]) -> dict:
    """Translate a (numerator, denominator) time signature to timing constants.

    Returns a dict with:
      - ``beats_per_bar``: counted pulses per bar (4 for 4/4, 3 for 3/4, 6 for 6/8).
      - ``pulse_unit_in_quarters``: how many quarter notes one counted pulse spans
        (1.0 for 4/4 or 3/4; 0.5 for 6/8).
      - ``bar_in_quarters``: bar length in quarter-note durations.
      - ``denominator``: pass-through.
      - ``strong_pulses``: tuple of counted-pulse offsets that count as strong
        beats (used by harmony/melody for accent placement).

    Strong-pulse choices: 4/4 → (0, 2); 3/4 → (0,); 6/8 → (0, 3) — counted in
    the meter's bottom unit.
    """
    num, den = time_sig
    pulse_unit_in_quarters = 4.0 / den
    if (num, den) == (4, 4):
        strong = (0, 2)
    elif (num, den) == (3, 4):
        strong = (0,)
    elif (num, den) == (6, 8):
        strong = (0, 3)
    elif (num, den) == (12, 8):
        # Felt-4 grouping (groups of 3 eighths).
        strong = (0, 3, 6, 9)
    elif (num, den) == (7, 8):
        # 4+3 split (the more common rock subdivision; Balkan 2+2+3
        # patterns express that grouping inside the pattern data itself).
        strong = (0, 4)
    elif (num, den) == (5, 4):
        # Brubeck 3+2 split.
        strong = (0, 3)
    else:
        # Fallback: just the downbeat
        strong = (0,)
    return {
        "beats_per_bar": num,
        "pulse_unit_in_quarters": pulse_unit_in_quarters,
        "bar_in_quarters": num * pulse_unit_in_quarters,
        "denominator": den,
        "strong_pulses": strong,
    }


def note_name_to_midi(name: str, octave: int = 4) -> int:
    """Convert note name + octave to MIDI number.  e.g. ('C', 4) → 60.

    Accepts sharp (C#) or flat (Db) spellings.
    """
    name = FLAT_TO_SHARP.get(name, name)
    return NOTE_NAMES.index(name) + 12 * (octave + 1)


def scale_notes(root: str, scale: str = "major", octave: int = 4) -> list[int]:
    """Return MIDI note numbers for a scale spanning one octave."""
    root_midi = note_name_to_midi(root, octave)
    intervals = SCALES.get(scale, SCALES["major"])
    return [root_midi + i for i in intervals]


def chord_notes(root: str, quality: str = "maj", octave: int = 4) -> list[int]:
    """Return MIDI note numbers for a chord."""
    root_midi = note_name_to_midi(root, octave)
    offsets = CHORD_FORMULAS.get(quality, CHORD_FORMULAS["maj"])
    return [root_midi + o for o in offsets]


def roman_to_semitone_offset(symbol: str, scale_type: str = "major") -> tuple[int, str]:
    """Parse a Roman-numeral chord symbol into (semitones_from_tonic, quality).

    Supports:
      - Case for default quality: ``I`` / ``i`` → major / minor.
      - Accidental prefixes: ``bII`` (♭2 Neapolitan), ``#IV`` (♯4 tritone), ``bVII``.
      - Quality suffixes: ``°``/``dim``, ``+``/``aug``, ``7``, ``maj7``, ``m7``, ``9``,
        ``sus2``, ``sus4``. Uppercase + ``7`` → dominant 7; lowercase + ``7`` → min7.
      - ``scale_type`` ∈ SCALES controls diatonic degree positions (e.g. ``minor``
        yields i-ii°-III-iv-v-VI-VII).

    Returns the semitone offset from the key tonic and the CHORD_FORMULAS quality key.
    Unknown symbols fall back to (0, "maj").
    """
    s = symbol.strip()

    accidental = 0
    while s and s[0] in ("b", "♭"):
        accidental -= 1
        s = s[1:]
    while s and s[0] in ("#", "♯"):
        accidental += 1
        s = s[1:]

    degree = None
    is_upper = False
    for base, d in _ROMAN_BASES:
        if s.startswith(base):
            degree = d
            is_upper = base[0].isupper()
            s = s[len(base):]
            break
    if degree is None:
        return (0, "maj")

    suffix = s.strip()
    if suffix in ("°", "dim", "o"):
        quality = "dim"
    elif suffix in ("+", "aug"):
        quality = "aug"
    elif suffix == "maj7":
        quality = "maj7"
    elif suffix in ("m7", "min7"):
        quality = "min7"
    elif suffix == "7":
        quality = "7" if is_upper else "min7"
    elif suffix == "9":
        quality = "7" if is_upper else "min7"  # 9th handled by voicing layer
    elif suffix == "sus2":
        quality = "sus2"
    elif suffix == "sus4":
        quality = "sus4"
    elif suffix == "":
        quality = "maj" if is_upper else "min"
    else:
        quality = "maj" if is_upper else "min"

    scale = SCALES.get(scale_type, SCALES["major"])
    if degree < len(scale):
        offset = scale[degree]
    else:
        offset = SCALES["major"][degree % 7]
    return (offset + accidental, quality)


def voice_chord(root_midi: int, quality: str = "maj", voicing: str = "triad",
                scale_degree_seventh: Optional[int] = None,
                scale_degree_ninth: Optional[int] = None) -> list[int]:
    """Return MIDI pitches for a chord with the given voicing.

    Voicings:
      - ``triad``: use CHORD_FORMULAS[quality] as-is.
      - ``seventh``: add the appropriate 7th if the quality doesn't already have one.
      - ``ninth``: add 7th + 9th.
      - ``sixth``: add the major 6th (no 7th). Motown/gospel.
      - ``add9``: add the 9th without the 7th. Airy pop.
      - ``sus2``: replace 3rd with 2nd — ambiguous, open.
      - ``sus4``: replace 3rd with 4th — suspended tension.
      - ``power``: root + fifth + octave root (ignores the third — rock/metal).
      - ``open5``: power chord pared down (root + fifth, no octave double).
      - ``drop2``: move the second-from-top voice down an octave (jazz comping).

    ``scale_degree_seventh`` / ``scale_degree_ninth`` let the caller
    override the 7th and 9th intervals from the chord root with values
    computed from the song's scale. Without them, plain-triad chords
    extended via ``ninth`` / ``seventh`` / ``rootless`` / ``shell`` /
    ``add9`` / ``sixth`` voicings default to major-7 + major-9, which
    is wrong in diatonic context (e.g. ``V`` in C major picks F# as
    its 7th instead of the correct F). ``add_chord_progression``
    computes these per chord from ``scale_name`` and the chord root's
    position in the scale, so callers using Roman-numeral progressions
    always land on diatonically-correct extensions.
    """
    if voicing == "power":
        return [root_midi, root_midi + 7, root_midi + 12]
    if voicing == "open5":
        return [root_midi, root_midi + 7]
    if voicing == "quartal":
        # Stacked perfect fourths — McCoy Tyner / modal-jazz colour, also the
        # backbone of many quartal raga string voicings.
        return [root_midi, root_midi + 5, root_midi + 10]
    if voicing == "quintal":
        # Stacked perfect fifths — open, ringing, gamelan/cinematic.
        return [root_midi, root_midi + 7, root_midi + 14]
    if voicing == "shell":
        # Jazz shell voicing — root + 3rd + 7th. Quality-aware + scale-aware:
        # when the caller passes a diatonic 7th (from add_chord_progression's
        # scale lookup) we use it, otherwise fall back to the quality-derived
        # default. Plain major triads in a major key without an override
        # would emit maj7 here, which is wrong for diatonic V/iii/vi.
        third = root_midi + (3 if quality in ("min", "dim", "min7") else 4)
        if scale_degree_seventh is not None:
            seventh = root_midi + scale_degree_seventh
        else:
            seventh = root_midi + (10 if quality in ("min", "dim", "min7", "7") else 11)
        return [root_midi, third, seventh]
    if voicing == "rootless":
        # Bill Evans-style rootless: 3rd, 5th, 7th, 9th (no root).
        third = root_midi + (3 if quality in ("min", "dim", "min7") else 4)
        fifth = root_midi + (6 if quality == "dim" else (8 if quality == "aug" else 7))
        if scale_degree_seventh is not None:
            seventh = root_midi + scale_degree_seventh
        else:
            seventh = root_midi + (10 if quality in ("min", "dim", "min7", "7") else 11)
        ninth = root_midi + (scale_degree_ninth if scale_degree_ninth is not None else 14)
        return [third, fifth, seventh, ninth]
    if voicing == "sus4_add9":
        # Bollywood/pop staple — suspended 4 with added 9.
        ninth_iv = root_midi + (scale_degree_ninth if scale_degree_ninth is not None else 14)
        return [root_midi, root_midi + 5, root_midi + 7, ninth_iv]

    offsets = list(CHORD_FORMULAS.get(quality, CHORD_FORMULAS["maj"]))
    has_seventh = any(o in (10, 11) for o in offsets)
    has_third = any(o in (3, 4) for o in offsets)

    # Suspended voicings: strip 3rd, add 2nd or 4th
    if voicing == "sus2":
        offsets = [o for o in offsets if o not in (3, 4)] + [2]
    elif voicing == "sus4":
        offsets = [o for o in offsets if o not in (3, 4)] + [5]

    # Extensions. When a scale-degree-aware 7th is supplied (from
    # add_chord_progression's scale lookup), use it — this is the
    # diatonic 7th of the chord built on the song's scale, which is
    # what listeners hear as "in key". Without the override, plain
    # triads were always extended with maj7, which produced the
    # leading-tone (F# in C major's V9) as a chord tone — sounding
    # explicitly out of key.
    if voicing in ("seventh", "ninth") and not has_seventh:
        if scale_degree_seventh is not None:
            seventh = scale_degree_seventh
        else:
            seventh = 11 if quality in ("maj", "aug") else 10
        offsets.append(seventh)

    ninth_iv = scale_degree_ninth if scale_degree_ninth is not None else 14
    if voicing == "ninth" and ninth_iv not in offsets:
        offsets.append(ninth_iv)

    if voicing == "add9" and ninth_iv not in offsets:
        offsets.append(ninth_iv)

    if voicing == "sixth" and 9 not in offsets:
        offsets.append(9)

    offsets = sorted(set(offsets))
    pitches = [root_midi + o for o in offsets]

    if voicing == "drop2" and len(pitches) >= 3:
        pitches[-2] -= 12
        pitches.sort()

    return pitches


# Chord-comping rhythms: each entry is a list of
#   (beat_offset_within_bar, duration_in_beats, velocity_multiplier)
# STRUM rhythms sound all chord pitches together at each hit; arpeggio rhythms
# (handled separately below) spread the pitches across hits.
STRUM_RHYTHMS: dict[str, list[tuple[float, float, float]]] = {
    "pad":           [(0.0, 4.0, 1.0)],
    "pulse_quarter": [(0.0, 0.9, 1.0), (1.0, 0.9, 0.85),
                      (2.0, 0.9, 0.95), (3.0, 0.9, 0.8)],
    "stabs_8th":     [(i * 0.5, 0.35, 1.0 if i % 2 == 0 else 0.78)
                      for i in range(8)],
    "charleston":    [(0.0, 1.2, 1.0), (1.5, 1.2, 0.85)],
    "funk_comp":     [(0.75, 0.25, 0.85), (1.0, 0.25, 1.0),
                      (2.5, 0.25, 0.95), (3.25, 0.25, 0.85),
                      (3.5, 0.25, 1.0)],
    "disco_stabs":   [(0.5, 0.3, 0.9), (1.5, 0.3, 0.9),
                      (2.5, 0.3, 0.9), (3.5, 0.3, 0.9)],
    "off_skank":     [(1.0, 0.4, 0.9), (3.0, 0.4, 0.9)],  # reggae/ska upstroke
    "dotted_8ths":   [(i * 0.75, 0.7, 1.0 if i == 0 else 0.85)
                      for i in range(6)],                 # driving 3-over-4
    "elton_octaves": [
        # Classic Elton piano comp: sustained chord on 1 and 3, "push" stab on
        # "and of 2", and a gospel triplet pickup (e-&-ah of 4) into the next
        # bar. Think "Tiny Dancer" / "Bennie and the Jets" piano feel.
        (0.0,   1.2, 1.0),                    # beat 1 — sustained chord
        (1.5,   0.4, 0.8),                    # "and of 2" push stab
        (2.0,   1.0, 0.95),                   # beat 3 — chord restrike
        (3.33,  0.22, 0.75),                  # triplet "e of 4"
        (3.66,  0.22, 0.85),                  # triplet "ah of 4" pickup
    ],
    "van_halen_chug": [                                   # palm-muted 8ths with accents
        (i * 0.5, 0.35, 1.0 if i % 2 == 0 else 0.75) for i in range(8)
    ],
    # ----- Latin / Caribbean / Spanish (4/4) -----
    # Tresillo — Afro-Cuban 3+3+2 cell on beats 1, "and of 2", 4.
    # Underpinning of son / salsa / reggaeton / many Latin-pop charts.
    "tresillo":       [(0.0, 0.7, 1.0), (1.5, 0.7, 0.9), (3.0, 0.9, 0.95)],
    # Son clave compressed to one bar (3-side cell): the dominant accent
    # cell of the 2-bar son clave, played every bar. For a true 2-bar clave
    # call, alternate ``clave_son_3side`` and ``clave_son_2side`` per bar.
    "clave_son_3side": [(0.0, 0.4, 1.0), (1.5, 0.4, 0.9), (3.0, 0.4, 0.95)],
    "clave_son_2side": [(1.0, 0.4, 0.85), (2.0, 0.4, 0.9)],
    "rumba_clave":    [(0.0, 0.4, 1.0), (1.75, 0.4, 0.9), (3.25, 0.4, 0.95)],
    # Bossa nova guitar comp: dotted-quarter then half-bar pickup.
    "bossa_comp":     [(0.0, 0.5, 1.0), (1.5, 0.5, 0.85),
                       (2.0, 0.5, 0.9), (3.5, 0.5, 0.85)],
    # Salsa piano montuno (one-bar 2-3 cell, syncopated upbeats).
    "montuno_2_3":    [(0.5, 0.3, 0.95), (1.0, 0.3, 0.85), (1.5, 0.3, 0.95),
                       (2.5, 0.3, 0.9),  (3.0, 0.3, 0.85), (3.5, 0.3, 0.95)],
    "flamenco_rasgueado": [
        # Triplet rasgueado across 2 beats, then sustained on 3 + accent on 4.
        (0.0, 0.18, 0.7), (0.33, 0.18, 0.9), (0.66, 0.18, 1.0),
        (1.0, 0.18, 0.7), (1.33, 0.18, 0.9), (1.66, 0.18, 1.0),
        (2.0, 1.0, 0.95), (3.0, 0.5, 0.9),
    ],
    # ----- Middle Eastern (offsets in 4-beat bar; iqa cells) -----
    "arab_maqsum":    [(0.0, 0.4, 1.0),  (1.0, 0.4, 0.8),   # DUM TAK
                       (1.5, 0.4, 0.85), (2.0, 0.4, 0.95),  # TAK DUM
                       (3.0, 0.4, 0.85)],                   # TAK
    "arab_baladi":    [(0.0, 0.4, 1.0),  (0.5, 0.4, 0.85),  # DUM-DUM
                       (1.5, 0.4, 0.8),  (2.5, 0.4, 0.9),
                       (3.0, 0.4, 0.85)],
    # ----- Indian (taala, offsets in 4-beat bar) -----
    "indian_teental_16": [
        # 16-beat teental compressed: vibhag accents on 1, 5, 9, 13.
        (0.0, 0.25, 1.0),   (0.25, 0.18, 0.7), (0.5, 0.18, 0.75), (0.75, 0.18, 0.7),
        (1.0, 0.25, 0.95),  (1.25, 0.18, 0.7), (1.5, 0.18, 0.75), (1.75, 0.18, 0.7),
        (2.0, 0.25, 0.85),  (2.25, 0.18, 0.7), (2.5, 0.18, 0.75), (2.75, 0.18, 0.7),
        (3.0, 0.25, 0.95),  (3.25, 0.18, 0.7), (3.5, 0.18, 0.75), (3.75, 0.18, 0.7),
    ],
    "indian_keherwa_8": [
        (0.0, 0.4, 1.0),  (0.5, 0.3, 0.75),
        (1.0, 0.4, 0.85), (1.5, 0.3, 0.75),
        (2.0, 0.4, 0.95), (2.5, 0.3, 0.75),
        (3.0, 0.4, 0.85), (3.5, 0.3, 0.75),
    ],
    # ----- East Asian (interlocking gamelan-style) -----
    "gamelan_kotekan": [
        # Interlocking 16ths — every other 16th sounded with a velocity weave.
        (i * 0.25, 0.18, 1.0 if i % 4 == 0 else (0.7 if i % 2 == 0 else 0.55))
        for i in range(16)
    ],
    # ----- 3/4 -----
    "waltz_strum":   [(0.0, 1.0, 1.0),       # downbeat (sustained chord)
                      (1.0, 0.9, 0.85),      # beat 2 (quieter)
                      (2.0, 0.9, 0.85)],     # beat 3 (quieter)
    # ----- 6/8 (offsets in counted eighths) -----
    # One sustained chord per bar — the felt-2 reading. For more rhythmic
    # 6/8 strumming, the arpeggio_16th pattern auto-scales nicely.
    "compound_6_8_strum": [(0.0, 6.0, 1.0)],
    # Flamenco bulería compás — 12-beat felt as (1) 2 (3) 4 (5) 6 7 (8) 9 (10) 11 12.
    # Offsets in counted eighths; use with a 12/8 meter.
    "bulería_12":     [(0.0, 0.45, 1.0),  (2.0, 0.45, 0.95),
                       (4.0, 0.45, 0.9),  (6.0, 0.45, 1.0),
                       (7.0, 0.45, 0.85), (9.0, 0.45, 0.95),
                       (11.0, 0.45, 0.9)],
    # ----- Section-aware patterns (4/4) -----
    # Workhorse big-band horn shout: driving 8th stabs with a 16th
    # pickup on "and-of-2" pulling into beat 3. Idiomatic under
    # Basie / Ellington / Tower of Power charts.
    "brass_shout":    [(0.0, 0.3, 1.0),  (0.5, 0.3, 0.85),
                       (1.0, 0.3, 1.0),  (1.75, 0.3, 0.9),
                       (2.0, 0.3, 1.0),  (2.5, 0.3, 0.85),
                       (3.5, 0.3, 0.95)],
    # Brass swell — long sustained crescendo arriving on beat 4.5.
    # Intro / fill / cinematic build. Two hits; the renderer's velocity
    # ramp on the long note approximates the crescendo.
    "brass_pad_swell": [(0.0, 3.5, 0.55), (3.5, 0.5, 1.0)],
    # Repeated 16ths with a per-beat accent — Herrmann / Reich /
    # film-tension ostinato. 16 hits per bar; accents on every
    # quarter-note pulse.
    "string_ostinato_16ths": [
        (i * 0.25, 0.22, 1.0 if i % 4 == 0 else 0.75) for i in range(16)
    ],
    # Pizz on every upbeat — sits cleanly under sustained brass/wind
    # pads. Light velocity, short durations.
    "pizz_alternating": [(0.5, 0.3, 0.9),  (1.5, 0.3, 0.85),
                         (2.5, 0.3, 0.95), (3.5, 0.3, 0.85)],
    # Tremolo: 32nd-note repetition across the bar. Accents on every
    # quarter to keep the pulse audible. Pair with strings/tremolo
    # patches (program 44) for the classic shimmer.
    "tremolo": [
        (i * 0.125, 0.12, 1.0 if i % 4 == 0 else 0.65) for i in range(32)
    ],
    # Heroic dotted-8th + 16th cell — Mahler / Strauss / John Williams
    # fanfare feel. Two compressed pickups followed by two whole-beat
    # sustains.
    "fanfare_dotted": [(0.0, 0.75, 1.0),  (0.75, 0.25, 0.9),
                       (1.0, 0.75, 1.0),  (1.75, 0.25, 0.9),
                       (2.0, 1.0, 1.0),   (3.0, 1.0, 0.95)],
}

# Arpeggio patterns: per-bar count of hits + direction.
# Hits cycle through the chord's voicing in the given direction.
# Registered themes / leitmotifs. Each entry is a list of
# (beat_offset_within_phrase, scale_degree, duration_beats). Scale degree
# is 1-indexed (1 = tonic, 3 = third, etc.). Phrase length is implicit from
# the maximum beat_offset + duration. add_theme() repeats the phrase to
# fill the requested bars.
THEMES: dict[str, list[tuple[float, int, float]]] = {
    "hit_the_sack": [
        # Bar 1: rising 1-3-5, step back
        (0.0,  1, 1.0), (1.0,  3, 1.0), (2.0,  5, 1.0), (3.0,  3, 1.0),
        # Bar 2: 5 held, 3 held — breath
        (4.0,  5, 2.0), (6.0,  3, 2.0),
        # Bar 3: color tone (6) + suspension (4)
        (8.0,  5, 1.0), (9.0,  6, 1.0), (10.0, 5, 1.0), (11.0, 4, 1.0),
        # Bar 4: descending resolution to tonic
        (12.0, 3, 2.0), (14.0, 1, 2.0),
    ],
}


ARPEGGIO_PATTERNS: dict[str, dict] = {
    "arpeggio_up":     {"hits": 4,  "direction": "up"},
    "arpeggio_down":   {"hits": 4,  "direction": "down"},
    "arpeggio_16th":   {"hits": 16, "direction": "updown"},
    "alberti":         {"hits": 8,  "direction": "alberti"},
    # Slow rising arp common in raga ālāp / Bollywood string lines.
    "arp_raga_ascend": {"hits": 8,  "direction": "up"},
    # Quick pentatonic cycle for koto / gamelan / chillout textures.
    "arp_pentatonic":  {"hits": 8,  "direction": "updown"},
    # Stacked-fourth arp — pairs naturally with the new "quartal" voicing.
    "arp_quartal":     {"hits": 8,  "direction": "alberti"},
}


# ---------------------------------------------------------------------------
# Music-theory primitives — catalogs that make melodies feel shaped, not random
# ---------------------------------------------------------------------------
#
# Catalog-first design: ship the data tables here, the generators
# (``add_melody``, ``add_harmony``) consume them, and the Melody Studio UI
# exposes them via dropdowns. Same pattern as STRUM_RHYTHMS and
# DRUM_PATTERNS — one source of truth, multiple consumers.

# Cadences — the resolution patterns that give phrases a sense of arrival.
# Each entry: (chord_motion_last_2_chords, (penult_scale_degree, final_scale_degree),
# emotion_tag). The generator forces the final melody note of a phrase to the
# ``melody[1]`` scale degree when this cadence is active.
CADENCES: dict[str, dict] = {
    "authentic_v_i":      {"chords": ["V", "I"],     "melody": (5, 1),
                            "emotion": "resolved"},
    "authentic_vii_i":    {"chords": ["VII", "I"],   "melody": (7, 1),
                            "emotion": "resolved_bright"},
    "plagal_iv_i":        {"chords": ["IV", "I"],    "melody": (4, 1),
                            "emotion": "resolved_warm"},
    "phrygian_bii_i":     {"chords": ["bII", "I"],   "melody": (2, 1),
                            "emotion": "resolved_dark"},
    "deceptive_v_vi":     {"chords": ["V", "vi"],    "melody": (5, 6),
                            "emotion": "surprised"},
    "half_iv_v":          {"chords": ["IV", "V"],    "melody": (4, 5),
                            "emotion": "questioning"},
    "half_i_v":           {"chords": ["I", "V"],     "melody": (1, 5),
                            "emotion": "questioning"},
    "imperfect_ii_v":     {"chords": ["ii", "V"],    "melody": (2, 5),
                            "emotion": "questioning"},
    "mediant_vi_iii":     {"chords": ["vi", "iii"],  "melody": (6, 3),
                            "emotion": "lifted"},
    "diminished_vii_i":   {"chords": ["vii°", "I"],  "melody": (7, 1),
                            "emotion": "resolved_dramatic"},
}


# Melodic licks — recognizable figures the user can drop into a bar.
# Same (beat_offset, scale_degree, duration) format as ``THEMES`` so
# ``MidiExporter.add_theme`` can render them with one line of dispatch.
# Scale degrees are 1-indexed in multi-octave space (8 = next octave's tonic).
MELODIC_LICKS: dict[str, dict] = {
    "pentatonic_descent_blues": {
        "events": [(0.0, 5, 0.5), (0.5, 4, 0.5),
                   (1.0, 3, 0.5), (1.5, 2, 0.5),
                   (2.0, 1, 1.0)],
        "genre": "blues", "emotion": "falling",
    },
    "country_walk_up_5_to_1": {
        "events": [(0.0, 5, 0.5), (0.5, 6, 0.5),
                   (1.0, 7, 0.5), (1.5, 8, 1.5)],
        "genre": "country", "emotion": "ascending",
    },
    "pop_anacrusis_2_3_5": {
        "events": [(0.0, 2, 0.25), (0.25, 3, 0.25), (0.5, 5, 1.0)],
        "genre": "pop", "emotion": "uplifting",
    },
    "classical_appoggiatura_4_3": {
        "events": [(0.0, 4, 0.25), (0.25, 3, 1.0), (1.25, 3, 0.5)],
        "genre": "classical", "emotion": "resolved",
    },
    "chromatic_enclosure_3": {
        # Approach the major 3rd from both sides (4 down, 2 up) before
        # landing. Chromatic flavour without leaving the scale.
        "events": [(0.0, 2, 0.3), (0.3, 4, 0.3),
                   (0.6, 2, 0.3), (0.9, 3, 1.2)],
        "genre": "jazz", "emotion": "chromatic_tension",
    },
    "mordent_5": {
        # Quick neighbour-tone ornament: hit, drop a step, return.
        "events": [(0.0, 5, 0.25), (0.25, 4, 0.15), (0.4, 5, 0.6)],
        "genre": "baroque", "emotion": "ornamental",
    },
    "turn_around_1_6_4_5": {
        "events": [(0.0, 1, 0.4), (0.4, 6, 0.4),
                   (0.8, 4, 0.4), (1.2, 5, 0.8)],
        "genre": "jazz_soul", "emotion": "tension_lift",
    },
    "gospel_melisma_5_to_1": {
        "events": [(0.0, 5, 0.2), (0.2, 4, 0.2),
                   (0.4, 3, 0.2), (0.6, 2, 0.2),
                   (0.8, 1, 1.2)],
        "genre": "gospel", "emotion": "resolving",
    },
    "indian_slide_6_to_5": {
        # Slow expressive slide — pairs with raga/maqam palettes.
        "events": [(0.0, 6, 0.5), (0.5, 5, 1.5)],
        "genre": "raga", "emotion": "ornamental_sliding",
    },
    "minor_pentatonic_run_1_to_5": {
        "events": [(0.0, 1, 0.3), (0.3, 3, 0.3),
                   (0.6, 4, 0.3), (0.9, 5, 0.9)],
        "genre": "rock", "emotion": "energetic",
    },
    "call_response_3_1": {
        "events": [(0.0, 3, 0.5), (0.5, 1, 0.5),
                   (1.0, 3, 0.5), (1.5, 1, 0.5)],
        "genre": "soul_rnb", "emotion": "conversational",
    },
    "arpeggio_climb_1_3_5_8": {
        "events": [(0.0, 1, 0.3), (0.3, 3, 0.3),
                   (0.6, 5, 0.3), (0.9, 8, 1.2)],
        "genre": "pop", "emotion": "ascending",
    },
}


# Melody articulation presets — depths for the expressive layer that
# ``add_melody(expression=...)`` applies via pitch bends. Each note gets at
# most one of {scoop into a strong note, vibrato on a sustain, fall off a
# phrase end} so the bend events never collide on a single-line melody.
MELODY_EXPRESSION: dict[str, dict] = {
    "light": {"scoop_prob": 0.22, "scoop_depth": 0.8, "vib_min_beats": 1.5,
              "vib_depth": 0.22, "vib_rate": 5.5, "fall_prob": 0.35, "fall_depth": 1.5},
    "full":  {"scoop_prob": 0.45, "scoop_depth": 1.0, "vib_min_beats": 1.0,
              "vib_depth": 0.4,  "vib_rate": 6.0, "fall_prob": 0.55, "fall_depth": 2.0},
    "vocal": {"scoop_prob": 0.5,  "scoop_depth": 1.2, "vib_min_beats": 1.0,
              "vib_depth": 0.45, "vib_rate": 5.5, "fall_prob": 0.5,  "fall_depth": 2.0},
}


def _resolve_expression(expression) -> Optional[dict]:
    """Normalise the ``expression`` arg to a depths dict (or None = off)."""
    if not expression:
        return None
    if isinstance(expression, str):
        return MELODY_EXPRESSION.get(expression, MELODY_EXPRESSION["light"])
    if isinstance(expression, dict):
        merged = dict(MELODY_EXPRESSION["light"])
        merged.update(expression)
        return merged
    return None


# Tension-building operators — transformations applied to an EXISTING melody bar.
# Stored as transformation recipes; the Melody Studio's SectionOverride
# carries a ``tension_op`` field that picks one by name.
TENSION_OPS: dict[str, dict] = {
    "suspension_4_3": {
        "type": "suspension", "hold_degree": 4, "resolve_degree": 3,
        "hold_duration": 0.5,
        "description": "Hold scale degree 4 then resolve to 3 — classic sus4 → maj3 tension",
    },
    "suspension_9_8": {
        "type": "suspension", "hold_degree": 9, "resolve_degree": 8,
        "hold_duration": 0.5,
        "description": "Hold 9 then resolve to 8 — airy pop suspension",
    },
    "suspension_7_6": {
        "type": "suspension", "hold_degree": 7, "resolve_degree": 6,
        "hold_duration": 0.5,
        "description": "Hold 7 then resolve to 6 — subtle minor-mode tension",
    },
    "pedal_tone": {
        "type": "pedal", "held_degree": 1,
        "description": "Anchor the melody on a held tonic while chords move underneath",
    },
    "anticipation": {
        "type": "anticipation", "early_beats": 0.5,
        "description": "Target chord tone arrives half a beat early — forward momentum",
    },
    "register_climb": {
        "type": "octave_shift", "shift_semitones": 12,
        "description": "Transpose the bar up an octave — sudden lift",
    },
    "rhythmic_acceleration": {
        "type": "density", "multiplier": 1.5,
        "description": "Subdivide each note ~1.5× shorter — increases urgency",
    },
    "chromatic_approach": {
        "type": "chromatic_neighbor", "approach_semitones": -1,
        "description": "Chromatic half-step below the target chord tone — bluesy tension",
    },
    "ghost_notes": {
        "type": "grace", "velocity_mult": 0.4, "duration": 0.15,
        "description": "Soft grace notes between main melody notes — jazzy texture",
    },
}


# Phrase forms — high-level shape templates that span 4 or 8 bars.
# The generator uses ``melody_shape`` to plan motivic development across bars.
PHRASE_FORMS: dict[str, dict] = {
    "antecedent_consequent": {
        "bars": 8, "structure": "4+4",
        "melody_shape": "a + a_prime",
        "description": "Question (weak ending) + answer (strong ending). Standard pop phrasing.",
    },
    "sentence": {
        "bars": 8, "structure": "1+1+2+4",
        "melody_shape": "a, a, a_dev, a_extended",
        "description": "Short motif, repeat, varied development, longer extension. Motif-driven.",
    },
    "period": {
        "bars": 8, "structure": "2+2+4",
        "melody_shape": "a, a, b",
        "description": "Two parallel questions + answer/resolution. Classical symmetry.",
    },
    "aaba": {
        "bars": 8, "structure": "2+2+2+2",
        "melody_shape": "a, a, b, a",
        "description": "Theme, repeat, bridge, return. Tin Pan Alley standard.",
    },
    "aba": {
        "bars": 6, "structure": "2+2+2",
        "melody_shape": "a, b, a",
        "description": "Theme, contrast, return. Simple ternary.",
    },
}


# Phrase-shape contours — pitch arc templates applied across a multi-bar phrase.
# Each is a function of phrase-position (0..1) → step bias. The generator
# samples bias at each event's position to pick the contour step instead of
# the legacy uniform ``rng.choice([-2,-1,1,2])``.
PHRASE_CONTOURS: list[str] = [
    "arc",            # rise → peak around 60% → fall (default)
    "rise",           # monotonically ascending
    "fall",           # monotonically descending
    "valley",         # fall → low around 50% → rise
    "plateau",        # mostly steady (small deviations)
    "call_response",  # rise in first half (call), fall in second (response)
]


# Motivic development operators — what the Nth motif-block does relative
# to the first (bar 0..motif_bars-1 is "a"; bar motif_bars..2*motif_bars-1
# is the result of applying op[1], etc.).
MOTIF_DEVELOPMENT_OPS: list[str] = [
    "repeat",         # a, a — direct restatement
    "sequence_up",    # a, a transposed up 1 scale step
    "sequence_down",  # a, a transposed down 1 scale step
    "inversion",      # a, a with contour direction flipped
    "retrograde",     # a, a played in reverse
    "augmentation",   # a, a with doubled note durations
    "cadence",        # a, then resolve to the active cadence's target degree
]


# Harmony voice-leading operators. ``add_harmony`` consumes via
# ``harmony_rule`` param. Each rule changes how consecutive harmony notes
# are chosen / filtered relative to the previous harmony pitch.
HARMONY_OPS: dict[str, dict] = {
    "voice_leading_smooth": {
        "description": "Each harmony note moves ≤2 semitones from the prior — Bach-style smoothness",
        "priority": 10,
    },
    "contrary_motion": {
        "description": "When melody ascends, harmony descends, and vice versa — independent voice",
        "priority": 6,
    },
    "common_tone": {
        "description": "Hold shared scale degrees between consecutive chords — anchor effect",
        "priority": 7,
    },
    "shell_voicing": {
        "description": "Harmony picks only 3rd and 7th — jazz-trio sparseness",
        "priority": 8,
    },
    "whisper_voicing": {
        "description": "Harmony stays >1 octave above melody at reduced velocity — backup-vocal feel",
        "priority": 5,
    },
    "parallel_thirds": {
        "description": "Harmony locks a third above the melody — doo-wop / classical",
        "priority": 4,
    },
}


# ---------------------------------------------------------------------------
# Drum pattern tables — keyed by meter
# ---------------------------------------------------------------------------
# Each entry is (list of (drum_name, list of (pulse_offset, velocity_mult)),
# grid_label). Pulse offsets are in counted units (quarters in 4/4 + 3/4,
# eighths in 6/8). The meter-keyed dispatch in add_drum_pattern looks up
# the right table; missing patterns raise ValueError.

_DRUM_V = 1.0
_DRUM_HH = 0.7
_DRUM_GHOST = 0.45


def _h(offs):
    """Helper: uniform-velocity hits → list[(off, 1.0)]."""
    return [(o, _DRUM_V) for o in offs]


def _hh(offs, mult=_DRUM_HH):
    return [(o, mult) for o in offs]


DRUM_PATTERNS_4_4: dict[str, tuple[list, str]] = {
    "basic_rock": ([
        ("kick",         _h([0, 2])),
        ("snare",        _h([1, 3])),
        ("hihat_closed", _hh([i * 0.5 for i in range(8)])),
    ], "8th"),
    # Train beat — steady 16th-note snare "pistons" (brush-style) with
    # accents on the backbeats; a country/blues staple. Kick on 1 & 3.
    "train_beat": ([
        ("kick",         _h([0, 2])),
        ("snare",        [(i * 0.25, 1.0 if i in (4, 12) else 0.4)
                          for i in range(16)]),
        ("hihat_closed", _hh([i * 0.5 for i in range(8)], mult=0.7)),
    ], "16th"),
    "four_on_floor": ([
        ("kick",         _h([0, 1, 2, 3])),
        ("snare",        _h([1, 3])),
        ("hihat_closed", _hh([i * 0.5 for i in range(8)])),
        ("hihat_open",   _h([3.5])),
    ], "8th"),
    "halftime": ([
        ("kick",         _h([0])),
        ("snare",        _h([2])),
        ("hihat_closed", _hh([i * 0.5 for i in range(8)])),
    ], "8th"),
    "funk": ([
        ("kick",         _h([0, 0.75, 2.5, 3.25])),
        ("snare",        [(1, _DRUM_V), (1.75, _DRUM_GHOST), (3, _DRUM_V), (3.5, _DRUM_GHOST)]),
        ("hihat_closed", _hh([i * 0.25 for i in range(16)])),
        ("hihat_open",   _h([1.5])),
    ], "16th"),
    "dance_house": ([
        ("kick",         _h([0, 1, 2, 3])),
        ("clap",         _h([1, 3])),
        ("hihat_closed", _hh([0.5, 1.5, 2.5, 3.5])),
        ("hihat_open",   _h([3.5])),
    ], "8th"),
    "disco": ([
        ("kick",         _h([0, 1, 2, 3])),
        ("snare",        _h([1, 3])),
        ("clap",         [(1, 0.8), (3, 0.8)]),
        ("hihat_open",   _hh([0.5, 1.5, 2.5, 3.5], mult=0.85)),
    ], "8th"),
    "jazz_swing": ([
        ("ride",         _hh([0, 1, 1.5, 2, 3, 3.5], mult=0.85)),
        ("hihat_closed", _hh([1, 3], mult=0.75)),
        ("snare",        [(2.5, _DRUM_GHOST)]),
    ], "8th"),
    "metal_gallop": ([
        ("kick",         _h([0, 0.75, 1, 2, 2.75, 3])),
        ("snare",        _h([1, 3])),
        ("crash",        [(0, 1.0)]),
    ], "16th"),
    "metal_blast": ([
        ("kick",         _h([i * 0.5 for i in range(8)])),
        ("snare",        _h([0.25 + i * 0.5 for i in range(8)])),
        ("crash",        [(0, 1.0)]),
    ], "16th"),
    "pop_disco": ([
        ("kick",         _h([0, 2])),
        ("snare",        _h([1, 3])),
        ("hihat_closed", _hh([i * 0.25 for i in range(16)
                              if abs((i * 0.25) % 1 - 0.5) > 1e-6])),
        ("hihat_open",   _hh([0.5, 1.5, 2.5, 3.5], mult=0.9)),
    ], "16th"),
    "pop_16ths": ([
        ("kick",         _h([0, 2])),
        ("snare",        _h([1, 3])),
        ("hihat_closed", _hh([i * 0.25 for i in range(16)])),
        ("hihat_open",   [(3.5, 0.95)]),
    ], "16th"),
    "neil_peart": ([
        ("kick",         _h([0, 0.75, 1.5, 2, 2.75, 3.5])),
        ("snare",        [(1, _DRUM_V), (2.5, _DRUM_GHOST), (3, _DRUM_V)]),
        ("tom_high",     [(3.75, 0.8)]),
        ("tom_mid",      [(1.75, 0.7)]),
        ("hihat_closed", _hh([i * 0.25 for i in range(16)])),
        ("crash",        [(0, 1.0)]),
    ], "16th"),
    "chad_smith": ([
        ("kick",         _h([0, 1.75, 2, 3.75])),
        ("snare",        [(1, _DRUM_V), (1.5, _DRUM_GHOST), (3, _DRUM_V), (3.25, _DRUM_GHOST)]),
        ("hihat_closed", _hh([i * 0.25 for i in range(16)])),
        ("hihat_open",   [(2.5, 0.8)]),
    ], "16th"),
    "steve_smith": ([
        ("kick",         _h([0, 1.5, 2, 3.5])),
        ("snare",        _h([1, 3])),
        ("ride",         _hh([0, 1, 2, 3], mult=0.9)),
        ("hihat_closed", _hh([0.5, 1.5, 2.5, 3.5])),
        ("crash",        [(0, 0.9)]),
    ], "8th"),
    # ----- Latin / Caribbean -----
    "salsa": ([
        # Cáscara on ride, conga-substitute on hi-hat, clave-driven snare.
        ("ride",         _hh([0, 0.5, 1, 1.5, 2, 2.5, 3, 3.5], mult=0.8)),
        ("snare",        [(0, 0.75), (1.5, 0.85), (3, 0.85)]),   # 3-2 son clave skeleton
        ("kick",         _h([0, 2])),
        ("clap",         [(1, 0.7), (3, 0.7)]),
    ], "16th"),
    "reggaeton": ([
        # Classic dembow: kick 1, kick 1.75, snare 2, kick 3, snare 3.5.
        ("kick",         _h([0, 1.75, 3])),
        ("snare",        _h([1, 3.5])),
        ("hihat_closed", _hh([i * 0.25 for i in range(16)])),
    ], "16th"),
    "bossa_nova": ([
        # Bossa: kick on 1 + "and of 2", rim/side-stick on the 3-2 clave.
        ("kick",         _h([0, 1.5, 2, 3.5])),
        ("rim",          [(0, 0.85), (1.5, 0.85), (3, 0.85), (4, 0.0)][:3]),  # 3-side
        ("hihat_closed", _hh([i * 0.25 for i in range(16)], mult=0.6)),
    ], "16th"),
    "samba": ([
        # Surdo on 2 & 4 (the "heart"), tamborim on 16ths, ago-go on offbeats.
        ("kick",         _h([1, 3])),
        ("snare",        [(0.75, _DRUM_GHOST), (1.5, _DRUM_V),
                          (2.75, _DRUM_GHOST), (3.5, _DRUM_V)]),
        ("hihat_closed", _hh([i * 0.25 for i in range(16)])),
    ], "16th"),
    "merengue": ([
        # Merengue tambora pattern compressed: snare 4-on-floor with kick 1/3.
        ("kick",         _h([0, 2])),
        ("snare",        _h([0.5, 1.5, 2.5, 3.5])),
        ("hihat_closed", _hh([i * 0.5 for i in range(8)])),
    ], "8th"),
    "afrobeat": ([
        # Tony Allen-inspired: syncopated kick, snare rim on 2 & 4, busy hat.
        ("kick",         _h([0, 0.75, 2.5])),
        ("snare",        [(1, _DRUM_V), (1.5, _DRUM_GHOST), (3, _DRUM_V)]),
        ("hihat_closed", _hh([i * 0.25 for i in range(16)])),
        ("hihat_open",   [(0.5, 0.85), (2.5, 0.85)]),
    ], "16th"),
    # ----- Hip-hop layered "DJ blend" grooves -----
    # A drum entry may carry an optional third value, a *layer shift* in
    # beats: the whole layer is nudged off the grid so two complementary
    # loops sit slightly apart in time, producing the flam / comb-filter
    # width a DJ gets when blending two records that aren't phase-locked.
    # Positive = laid back (late), negative = pushed (early).
    "hiphop_dj_layered": ([
        # Deck A — tight boom-bap kit, dead on the grid.
        ("kick",         _h([0, 0.75, 2.5]), 0.0),
        ("snare",        [(1, _DRUM_V), (3, _DRUM_V)], 0.0),
        ("hihat_closed", _hh([i * 0.5 for i in range(8)]), 0.0),
        # Deck B — same pocket, nudged ~late for the blended-loop flam.
        ("hihat_open",   [(1.5, 0.7), (3.5, 0.7)], 0.045),
        ("cabasa",       _hh([i * 0.25 for i in range(16)], mult=0.4), 0.06),
        # Hand-clap doubling the snare, pushed slightly early — stereo-ish width.
        ("clap",         [(1, 0.6), (3, 0.6)], -0.035),
    ], "16th"),
    "trap_dj_layered": ([
        # 808 + clap core on the grid.
        ("kick",         _h([0, 1.5, 2.75]), 0.0),
        ("snare",        [(2, _DRUM_V)], 0.0),
        ("clap",         [(2, 0.8)], 0.02),
        ("hihat_closed", _hh([i * 0.25 for i in range(16)]), 0.0),
        # Second hat layer — roll subdivisions, nudged late behind the main hats.
        ("hihat_closed", _hh([0.5, 1.0, 1.25, 3.0, 3.5, 3.75], mult=0.55), 0.05),
        ("hihat_open",   [(1.5, 0.7)], 0.03),
    ], "16th"),
    # ----- Latin hand-percussion sets -----
    "latin_mambo": ([
        ("clave",        [(0, 0.9), (1.5, 0.9), (3, 0.9)]),   # 3-side son clave
        ("conga_open",   _hh([1.5, 3.5], mult=0.85)),
        ("conga_mute",   _hh([0.75, 1.0, 2.75, 3.0], mult=0.55)),
        ("conga_low",    _h([2])),
        ("timbale_high", _hh([0.5, 2.5], mult=0.7)),
        ("cowbell",      _hh([0, 1, 2, 3], mult=0.7)),
        ("kick",         _h([0, 1.5, 2, 3.5])),               # tumbao anchor
    ], "16th"),
    "latin_cumbia": ([
        ("guiro_long",   _hh([0, 1, 2, 3], mult=0.7)),
        ("guiro_short",  _hh([0.5, 1.5, 2.5, 3.5], mult=0.5)),
        ("conga_open",   _h([1, 3])),
        ("conga_mute",   _hh([0.5, 1.5, 2.5, 3.5], mult=0.5)),
        ("cowbell",      _hh([0, 2], mult=0.7)),
        ("kick",         _h([0, 2])),
    ], "16th"),
    "latin_percussion": ([
        # Pure hand-percussion bed — congas/bongos/clave/shakers, no kit.
        ("clave",        [(0, 0.85), (1.5, 0.85), (3, 0.85)]),
        ("conga_open",   _hh([1.5, 3.5], mult=0.85)),
        ("conga_mute",   _hh([0.75, 2.75], mult=0.6)),
        ("bongo_high",   _hh([0.5, 1.0, 2.5, 3.0], mult=0.6)),
        ("bongo_low",    _h([0, 2])),
        ("maracas",      _hh([i * 0.25 for i in range(16)], mult=0.4)),
        ("cowbell",      _hh([0, 1, 2, 3], mult=0.55)),
    ], "16th"),
    # ----- Add-on percussion LAYERS (no kick/snare) — sit alongside a main kit
    # without competing, for the selectable "extra percussion" instruments.
    "latin_perc_layer": ([
        ("clave",        [(0, 0.8), (1.5, 0.8), (3, 0.8)]),      # 3-side son clave
        ("conga_open",   _hh([1.5, 3.5], mult=0.8)),
        ("conga_mute",   _hh([0.75, 2.75], mult=0.55)),
        ("bongo_high",   _hh([0.5, 2.5], mult=0.55)),
        ("maracas",      _hh([i * 0.25 for i in range(16)], mult=0.35)),
    ], "16th"),
    "hiphop_perc_layer": ([
        # Hip-hop layer that sits WITH the kit via placement/velocity, not by
        # being empty: sparse syncopated 808 sub-kick drops (off the main
        # downbeat), a backbeat clap doubling the snare, soft ghost-note snare
        # 16ths for texture, plus an off-grid shaker/open-hat DJ top.
        ("kick",         [(2.5, 0.7), (3.75, 0.55)]),                    # 808 drops, off-beat
        ("clap",         [(1, 0.65), (3, 0.65)], -0.03),                 # backbeat clap, pushed
        ("snare",        [(0.75, 0.26), (1.75, 0.3), (2.75, 0.26), (3.5, 0.32)]),  # ghost notes
        ("cabasa",       _hh([i * 0.25 for i in range(16)], mult=0.32), 0.05),     # off-grid shaker
        ("hihat_open",   [(1.5, 0.5), (3.5, 0.5)], 0.045),              # off-beat open hat, late
    ], "16th"),
}

DRUM_PATTERNS_3_4: dict[str, tuple[list, str]] = {
    "waltz_basic": ([
        # Classical waltz feel: kick on 1, snare on 2, hat on every beat.
        ("kick",         _h([0])),
        ("snare",        _h([1])),
        ("hihat_closed", _hh([0, 1, 2])),
    ], "8th"),
    "jazz_waltz": ([
        # Jazz waltz ride: 1, 2-and, 3 — the classic Coltrane / Evans feel.
        ("ride",         _hh([0, 1, 1.5, 2], mult=0.85)),
        ("hihat_closed", _hh([1, 2], mult=0.75)),  # foot on 2/3
    ], "8th"),
}

DRUM_PATTERNS_6_8: dict[str, tuple[list, str]] = {
    "compound_6_8": ([
        # Counted in eighths: kick on 1 and 4 (the two felt-pulses),
        # snare on 4, hat on every eighth.
        ("kick",         _h([0, 3])),
        ("snare",        _h([3])),
        ("hihat_closed", _hh([0, 1, 2, 3, 4, 5])),
    ], "8th"),
    "tarantella": ([
        # Italian folk feel — kick + snare alternating, busy hat.
        ("kick",         _h([0, 2, 4])),
        ("snare",        _h([3])),
        ("hihat_closed", _hh([0, 1, 2, 3, 4, 5])),
    ], "8th"),
    "bulería": ([
        # Flamenco bulería compás: accents on 1, 3, 5, 7, 8, 10. Cajón-style.
        ("kick",         _h([0, 4])),
        ("clap",         [(2, 0.85), (6, 1.0), (7, 0.85), (9, 0.95)]),
        ("hihat_closed", _hh([1, 3, 5])),
    ], "8th"),
    "afro_6_8": ([
        # Afro-Cuban bell 6/8: bell on 1, 2 (and), 4, 5 (and).
        ("ride_bell",    [(0, _DRUM_V), (1.5, 0.85), (3, _DRUM_V), (4.5, 0.85)]),
        ("kick",         _h([0, 3])),
        ("clap",         [(2, 0.8), (5, 0.8)]),
    ], "8th"),
}

# ----- 12/8 (counted twelfths) -----
DRUM_PATTERNS_12_8: dict[str, tuple[list, str]] = {
    "bembe": ([
        # Bembe bell pattern (the African 6/8 bell, common across diaspora).
        ("ride_bell",    [(0, _DRUM_V), (2, 0.8), (3, 0.95),
                          (5, 0.8), (7, _DRUM_V), (9, 0.8), (10, 0.95)]),
        ("kick",         _h([0, 6])),
        ("clap",         [(3, 0.85), (9, 0.85)]),
    ], "8th"),
    "son_clave_12_8": ([
        # 2-bar son clave compressed into a 12/8 bar (3-side cell).
        ("rim",          [(0, _DRUM_V), (3, 0.95), (6, _DRUM_V)]),
        ("kick",         _h([0, 6])),
        ("hihat_closed", _hh([0, 2, 4, 6, 8, 10])),
    ], "8th"),
}

# ----- 7/8 (counted eighths) -----
DRUM_PATTERNS_7_8: dict[str, tuple[list, str]] = {
    "prog_7_8": ([
        # Standard 4+3 split: kick on 1 + 4 + 6.
        ("kick",         _h([0, 3, 5])),
        ("snare",        _h([2, 6])),
        ("hihat_closed", _hh([i for i in range(7)])),
    ], "8th"),
    "balkan_7_8": ([
        # Balkan 2+2+3 split.
        ("kick",         _h([0, 2, 4])),
        ("snare",        _h([1, 3, 5])),
        ("hihat_closed", _hh([i * 0.5 for i in range(14)])),
    ], "16th"),
}

# ----- 5/4 (counted quarters) -----
DRUM_PATTERNS_5_4: dict[str, tuple[list, str]] = {
    "take_five_5_4": ([
        # Brubeck "Take Five" feel — 3+2 split with the famous hat ride.
        ("kick",         _h([0, 3])),
        ("snare",        _h([2, 4])),
        ("hihat_closed", _hh([i * 0.5 for i in range(10)])),
    ], "8th"),
    "odd_rock_5_4": ([
        # Generic 5/4 rock: 3+2 with crash on 1.
        ("kick",         _h([0, 1.5, 3])),
        ("snare",        _h([1, 4])),
        ("crash",        [(0, 0.95)]),
        ("hihat_closed", _hh([i for i in range(5)])),
    ], "8th"),
}

DRUM_PATTERNS_BY_METER: dict[tuple[int, int], dict[str, tuple[list, str]]] = {
    (4, 4): DRUM_PATTERNS_4_4,
    (3, 4): DRUM_PATTERNS_3_4,
    (6, 8): DRUM_PATTERNS_6_8,
    (12, 8): DRUM_PATTERNS_12_8,
    (7, 8): DRUM_PATTERNS_7_8,
    (5, 4): DRUM_PATTERNS_5_4,
}


# ---------------------------------------------------------------------------
# Drum grid helpers (for the clickable editor in app.py)
# ---------------------------------------------------------------------------
# Fixed row order so the UI dataframe column layout is stable across reloads.
GRID_DRUM_ROWS: list[str] = [
    "kick", "snare", "clap", "rim",
    "hihat_closed", "hihat_open",
    "ride", "ride_bell", "crash",
    "tom_low", "tom_mid", "tom_high",
]


def _vel_mult_to_level(vel_mult: float) -> int:
    """Bucket a velocity multiplier (0..1.2-ish) into a 4-level grid value:
    0=silent / 1=ghost / 2=normal / 3=accent. Inverse of the table in
    :meth:`MidiExporter.add_drum_grid`. The thresholds match the velocity
    constants ``_DRUM_GHOST`` and ``_DRUM_V`` used by the built-in patterns."""
    if vel_mult <= 0.0:
        return 0
    if vel_mult <= 0.5:
        return 1
    if vel_mult <= 0.85:
        return 2
    return 3


def grid_subdivs_for_meter(time_sig: tuple[int, int]) -> int:
    """Steps-per-counted-pulse for the grid editor's fixed 16th-resolution.

    Counted pulses are quarter notes for x/4 meters and eighth notes for
    x/8 meters (see :func:`meter_info`). The grid always shows the
    finest practical subdivision so the user can edit any hit a built-in
    pattern emits — even patterns the catalog stores at the coarser
    ``"8th"`` resolution.

      - x/4 meters (4/4, 3/4, 5/4): 4 sixteenths per quarter pulse
      - x/8 meters (6/8, 12/8, 7/8): 2 sixteenths per eighth pulse

    Both branches resolve to 16th-note cells in absolute terms; the math
    differs because the pulse unit differs.
    """
    _, den = time_sig
    return 4 if den == 4 else 2


def drum_pattern_to_grid(
    pattern_name: Optional[str],
    time_sig: tuple[int, int],
    *,
    bars: int = 1,
) -> dict[str, list[int]]:
    """Return a ``{drum_name: [level for each step]}`` grid seeded from the
    named preset in :data:`DRUM_PATTERNS_BY_METER` for ``time_sig``.

    The grid always uses the finest practical subdivision (see
    :func:`grid_subdivs_for_meter`) so it doubles as an edit surface for
    the underlying generated pattern: every hit a catalog pattern places
    has a corresponding editable cell, even when the pattern's native
    grid_label is ``"8th"``. All :data:`GRID_DRUM_ROWS` are always
    present (zero-filled rows where the pattern doesn't touch the drum)
    so the UI's row layout stays stable. When ``pattern_name`` is
    missing / unknown for ``time_sig``, returns a blank template the
    user can build from scratch.
    """
    info = meter_info(time_sig)
    bpb = info["beats_per_bar"]
    subdivs = grid_subdivs_for_meter(time_sig)
    steps_per_bar = bpb * subdivs
    total_steps = max(steps_per_bar * bars, steps_per_bar)
    grid = {d: [0] * total_steps for d in GRID_DRUM_ROWS}

    meter_table = DRUM_PATTERNS_BY_METER.get(time_sig, {})
    pattern = meter_table.get(pattern_name) if pattern_name else None
    if pattern is None:
        return grid

    hits, _ = pattern
    # The stored pattern's beat offsets are in COUNTED PULSES, so the
    # per-pulse subdivision count is what we multiply by to land on a step.
    for drum_name, offset_vels in hits:
        if drum_name not in grid:
            continue
        for beat_offset, vel_mult in offset_vels:
            step_idx_in_bar = int(round(beat_offset * subdivs))
            level = _vel_mult_to_level(vel_mult)
            for bar in range(bars):
                idx = bar * steps_per_bar + step_idx_in_bar
                if 0 <= idx < total_steps:
                    grid[drum_name][idx] = level
    return grid


def grid_step_labels(
    time_sig: tuple[int, int], bars: int, steps_per_bar: int,
) -> list[str]:
    """Return human-friendly headers for the dataframe columns.

    16th-note grid (subdivs=4): ``1 e & a 2 e & a 3 e & a 4 e & a`` repeated
    per bar with the bar number prefix. 8th-note grid (subdivs=2): ``1 & 2
    & ...``.
    """
    info = meter_info(time_sig)
    bpb = info["beats_per_bar"]
    subdivs = max(1, steps_per_bar // bpb)
    SIXTEENTH = ["", "e", "&", "a"]
    EIGHTH = ["", "&"]
    template = SIXTEENTH if subdivs == 4 else EIGHTH
    labels: list[str] = []
    for bar in range(bars):
        for beat in range(bpb):
            for sub in range(subdivs):
                if sub == 0:
                    labels.append(f"{bar + 1}.{beat + 1}")
                else:
                    labels.append(template[sub] if sub < len(template) else "")
    return labels


def _arp_pitch_sequence(n_tones: int, hits: int, direction: str) -> list[int]:
    """Return ``hits`` indices (0..n_tones-1) cycling per the direction.

    - ``up``: 0, 1, 2, 3, 0, 1, ...
    - ``down``: n-1, n-2, ..., 0, n-1, ...
    - ``updown``: 0, 1, 2, 3, 2, 1, 0, 1, ... (mirror)
    - ``alberti``: classical pattern [0, n-1, 1, n-1] (low-high-mid-high)
    """
    if n_tones <= 0:
        return []
    if direction == "up":
        return [i % n_tones for i in range(hits)]
    if direction == "down":
        return [(n_tones - 1 - i) % n_tones for i in range(hits)]
    if direction == "updown":
        period = max(2, 2 * (n_tones - 1))
        out = []
        for i in range(hits):
            p = i % period
            out.append(p if p < n_tones else period - p)
        return out
    if direction == "alberti":
        if n_tones < 2:
            return [0] * hits
        pattern = [0, n_tones - 1, min(1, n_tones - 1), n_tones - 1]
        return [pattern[i % 4] for i in range(hits)]
    return [i % n_tones for i in range(hits)]


_MOTIF_WEAK_BY_METER = {
    (4, 4): (1, 1.5, 2.5, 3, 3.5),
    (3, 4): (1, 1.5, 2, 2.5),
    (6, 8): (1, 2, 4, 5),
}


# Pre-baked rhythm templates keyed by genre/idiom. Each entry is a list
# of (beat_offset, duration, accent) tuples covering a 2-bar motif in
# counted-pulse units (quarters for 4/4, eighths for 6/8). Beats not
# listed are silence (real rests, not just zero-velocity notes), which
# is the key audible difference vs the procedural generator's
# wall-to-wall coverage.
#
# Used by ``add_melody`` when ``rhythm_motif`` is named (typically via a
# per-style ``melody_variant``). When ``rhythm_motif`` is None the
# generator falls back to ``_generate_rhythm_motif``'s probabilistic
# template (today's behavior, bit-identical).
RHYTHM_MOTIFS: dict[str, list[tuple[float, float, bool]]] = {
    # Pop: clean quarter + 8th anacrusis, soft mid-phrase breath.
    "pop_anacrusis": [
        (0.0, 1.0, True),
        (1.0, 0.5, False),
        (1.5, 0.5, False),
        (2.0, 1.0, True),
        (3.0, 1.0, False),
        # short rest 4.0–4.5
        (4.5, 1.5, True),
        (6.0, 1.0, False),
        (7.0, 0.5, False),
    ],
    # Jazz charleston: dotted quarter + 8th, sets up that iconic accent.
    "jazz_charleston": [
        (0.0, 1.5, True),
        (1.5, 0.5, False),
        (2.5, 0.5, False),
        (3.5, 0.5, False),
        (4.0, 1.5, True),
        (5.5, 0.5, False),
        (6.5, 0.5, False),
        (7.5, 0.5, False),
    ],
    # Funk 16ths with syncopated and-of-1 and and-of-3.
    "funk_16th_synco": [
        (0.0, 0.25, True),
        (0.5, 0.25, False),
        (0.75, 0.25, False),
        (1.5, 0.25, False),
        (1.75, 0.25, False),
        (2.0, 0.5, True),
        (2.75, 0.25, False),
        (3.0, 0.5, False),
        (3.5, 0.5, False),
        (4.0, 0.25, True),
        (4.5, 0.25, False),
        (4.75, 0.25, False),
        (5.5, 0.25, False),
        (6.0, 0.5, True),
        (6.75, 0.25, False),
        (7.0, 0.5, False),
    ],
    # Blues shuffle triplet feel — long-short-long-short.
    "blues_shuffle": [
        (0.0, 0.667, True),
        (0.667, 0.333, False),
        (1.0, 0.667, False),
        (1.667, 0.333, False),
        (2.0, 0.667, True),
        (2.667, 0.333, False),
        (3.0, 0.667, False),
        (4.0, 0.667, True),
        (4.667, 0.333, False),
        (5.0, 1.0, False),
        (6.0, 1.5, True),
    ],
    # Bossa nova partido alto 3-3-2 over 8th-note grid.
    "bossa_partido": [
        (0.0, 0.75, True),
        (0.75, 0.75, False),
        (1.5, 0.5, False),
        (2.0, 0.75, True),
        (2.75, 0.75, False),
        (3.5, 0.5, False),
        (4.0, 0.75, True),
        (4.75, 0.75, False),
        (5.5, 0.5, False),
        (6.0, 1.0, True),
        (7.0, 1.0, False),
    ],
    # Country long-short with downbeat emphasis.
    "country_long_short": [
        (0.0, 0.75, True),
        (0.75, 0.25, False),
        (1.0, 0.75, False),
        (1.75, 0.25, False),
        (2.0, 1.0, True),
        (3.0, 1.0, False),
        (4.0, 0.75, True),
        (4.75, 0.25, False),
        (5.0, 0.75, False),
        (5.75, 0.25, False),
        (6.0, 1.0, True),
    ],
    # Latin son clave 3-2 (1 - and-of-2 - 3 - rest - and-of-4).
    "latin_clave_son": [
        (0.0, 0.5, True),
        (1.5, 0.5, False),
        (2.5, 0.5, False),
        (4.0, 0.5, True),
        (5.5, 0.5, False),
        (6.5, 0.5, False),
    ],
}


def _generate_rhythm_motif(rng, motif_bars: int = 2, density: float = 0.7,
                           swing: float = 0.0,
                           beats_per_bar: int = 4,
                           strong_pulses: tuple = (0, 2),
                           time_signature: tuple = (4, 4),
                           rhythm_motif: Optional[str] = None) -> list[dict]:
    """Sample a rhythmic skeleton for a melodic motif.

    Returns a list of events, each a dict:
      - ``beat``:     pulse offset from start of motif (in counted units —
                      quarter notes for 4/4 + 3/4, eighth notes for 6/8)
      - ``duration``: in pulses
      - ``accent``:   True on strong beats (per ``strong_pulses``)

    Strong beats are always kept so phrasing has a reliable pulse. Weak
    subdivisions are kept probabilistically per ``density``. The FINAL
    portion of each motif gets a lower keep-probability so phrases have
    breathing room. Swing applies to 8th subdivisions.

    ``rhythm_motif`` (Optional[str]): When set to a key in
    :data:`RHYTHM_MOTIFS`, the procedural template is replaced by the
    pre-baked catalog entry. This is how per-style melody variants
    swap in genre-idiomatic rhythms (jazz charleston, funk 16th
    syncopation, etc.) without growing branches in this function.
    Unknown names fall through to the procedural path.
    """
    events: list[dict] = []
    total_beats = motif_bars * beats_per_bar

    # Catalog path: return the named motif's events directly, truncating
    # to ``motif_bars`` and applying swing the same way the procedural
    # path does.
    if rhythm_motif and rhythm_motif in RHYTHM_MOTIFS:
        template = RHYTHM_MOTIFS[rhythm_motif]
        for beat_off, dur, accent in template:
            if beat_off >= total_beats:
                continue   # truncate to requested motif_bars
            # Cap duration so we don't bleed past the motif end.
            dur_cap = min(dur, total_beats - beat_off)
            swung = apply_swing(beat_off % beats_per_bar, swing, grid="8th") \
                + (int(beat_off) // beats_per_bar) * beats_per_bar
            events.append({
                "beat": swung,
                "duration": max(0.125, dur_cap),
                "accent": bool(accent),
            })
        return events

    # Strong beats — always kept
    strong_full = {bar * beats_per_bar + b
                   for bar in range(motif_bars)
                   for b in strong_pulses}
    # For multi-bar motifs, drop the last bar's last-strong-beat half the
    # time so phrases have a natural breath. 1-bar "riff" motifs keep both
    # strong beats (they repeat too fast to need a long tail rest).
    if motif_bars >= 2 and len(strong_pulses) > 1:
        last_strong = (motif_bars - 1) * beats_per_bar + max(strong_pulses)
        if rng.random() > 0.5:
            strong_full.discard(last_strong)
    strong = strong_full

    # Candidate weak subdivisions — meter-specific.
    weak_subs = _MOTIF_WEAK_BY_METER.get(time_signature, (1, 1.5, 2.5, 3, 3.5))
    weak: list[float] = []
    breath_window_start = total_beats - (1.5 if motif_bars >= 2 else 0.5)
    breath_mult = 0.4 if motif_bars >= 2 else 0.6
    for bar in range(motif_bars):
        for sub in weak_subs:
            weak.append(bar * beats_per_bar + sub)

    chosen = sorted(strong)
    for w in weak:
        local_density = density * (breath_mult if w >= breath_window_start else 1.0)
        if rng.random() < local_density:
            chosen.append(w)
    chosen = sorted(set(chosen))

    # Assign durations based on gap to next event
    for i, beat_off in enumerate(chosen):
        next_off = chosen[i + 1] if i + 1 < len(chosen) else total_beats
        dur = max(0.25, min(1.5, next_off - beat_off))
        swung = apply_swing(beat_off % beats_per_bar, swing, grid="8th") \
            + (beat_off // beats_per_bar) * beats_per_bar
        events.append({
            "beat": swung,
            "duration": dur,
            "accent": beat_off in strong,
        })
    return events


def _rhythm_override_at(
    overrides: Optional[list], bar_idx: int,
) -> Optional[dict]:
    """First override covering ``bar_idx`` (or None).

    Mirrors ``melody_plan._override_for_bar``'s first-match-wins
    convention so chord-rhythm / bass-pattern overrides resolve the
    same way melody section overrides do — earlier-declared overrides
    win on overlap.

    Defined locally here (not imported from melody_plan) because
    melody_plan already imports from this module, and the lookup is
    too small to be worth resolving via a third helper file.
    """
    if not overrides:
        return None
    for ov in overrides:
        try:
            s = int(ov.get("start_bar", 0))
            e = int(ov.get("end_bar", 0))
        except (TypeError, ValueError, AttributeError):
            continue
        if s <= bar_idx <= e:
            return ov
    return None


def _resolve_chord_rhythm(
    overrides: Optional[list],
    master_rhythm: str,
    bar_idx: int,
    half: int,
) -> str:
    """Pick the chord rhythm name for a (bar, half) — inherit chain.

    Order: override.chord_rhythm_h2 (if half==1 and set) →
           override.chord_rhythm_h1 (if set) → master_rhythm.
    """
    ov = _rhythm_override_at(overrides, bar_idx)
    if ov is None:
        return master_rhythm
    h1 = (ov.get("chord_rhythm_h1") or "").strip()
    h2 = (ov.get("chord_rhythm_h2") or "").strip()
    if half == 1 and h2:
        return h2
    if h1:
        return h1
    return master_rhythm


def _resolve_bass_pattern(
    overrides: Optional[list], master_pattern: str, bar_idx: int,
) -> str:
    """Pick the bass pattern name for a bar — inherit chain."""
    ov = _rhythm_override_at(overrides, bar_idx)
    if ov is None:
        return master_pattern
    bp = (ov.get("bass_pattern") or "").strip()
    return bp or master_pattern


def apply_swing(offset_in_beats: float, swing: float, grid: str = "8th") -> float:
    """Delay off-beat positions by ``swing * subdivision_duration`` (in beats).

    ``grid="8th"`` swings the "ands" (0.5, 1.5, 2.5, 3.5 of the bar).
    ``grid="16th"`` swings the "e"/"a" 16ths (every odd 16th subdivision).
    ``swing=0`` is straight; ``swing≈0.33`` ≈ full triplet swing.
    """
    if swing == 0.0:
        return offset_in_beats
    subdivision = 0.5 if grid == "8th" else 0.25 if grid == "16th" else None
    if subdivision is None:
        return offset_in_beats
    sub_count = offset_in_beats / subdivision
    nearest = round(sub_count)
    if abs(sub_count - nearest) < 1e-6 and nearest % 2 == 1:
        return offset_in_beats + swing * subdivision
    return offset_in_beats


# ---------------------------------------------------------------------------
# Chord progression pacing
# ---------------------------------------------------------------------------
# A "progression plan" is the user-facing chord sequence with per-chord
# durations expressed in BARS (floats). Bare strings are still accepted
# for backward compat — they're coerced to duration=1.0 bars.
#
# Internally, ``expand_progression_plan`` tiles the requested bar count
# with this plan and returns a flat list of ``ChordEvent`` records (start
# bar, end bar, symbol). Each generator (``add_chord_progression``,
# ``add_bass_line``, ``add_melody``, ``add_lead_line``) walks those
# events and renders each segment's rhythm hits in [start, end) — so
# sub-bar chord changes are real, not rounded up to a full bar.

ProgressionPlan = list[tuple[str, float] | str]


@dataclass
class ChordEvent:
    """A chord segment placed at a fractional bar range.

    ``start_bar`` and ``end_bar`` are 0-indexed positions in *bars*
    (so a half-bar chord on bar 2 spans 2.0..2.5).
    """
    start_bar: float
    end_bar: float
    symbol: str

    @property
    def duration_bars(self) -> float:
        return self.end_bar - self.start_bar


def coerce_progression_plan(
    progression: Optional[ProgressionPlan],
) -> list[tuple[str, float]]:
    """Normalize a mixed ``list[str | (str, float)]`` to ``list[(str, float)]``.

    Bare strings carry the legacy "1 bar per chord" semantics. ``None`` and
    empty inputs fall back to a single tonic chord. Float durations are
    clamped to a small positive number to avoid degenerate zero-length
    segments breaking the tile loop.
    """
    if not progression:
        return [("I", 1.0)]
    out: list[tuple[str, float]] = []
    for item in progression:
        if isinstance(item, str):
            out.append((item, 1.0))
        elif isinstance(item, (tuple, list)) and len(item) >= 2:
            sym = str(item[0])
            try:
                dur = max(1e-6, float(item[1]))
            except (TypeError, ValueError):
                dur = 1.0
            out.append((sym, dur))
        else:
            out.append((str(item), 1.0))
    return out


def expand_progression_plan(
    progression: Optional[ProgressionPlan], bars: float,
) -> list[ChordEvent]:
    """Tile ``[0, bars)`` with the progression plan, looping the cell as
    needed. Returns an in-order list of :class:`ChordEvent`s whose
    durations sum to exactly ``bars``.
    """
    plan = coerce_progression_plan(progression)
    events: list[ChordEvent] = []
    if bars <= 0:
        return events
    t = 0.0
    eps = 1e-9
    # Guard against pathological plans (all zero durations) by capping.
    safety = max(1, int(bars * 64) + len(plan) * 4)
    while t < bars - eps and safety > 0:
        for symbol, dur in plan:
            if t >= bars - eps:
                break
            end = min(t + dur, bars)
            if end - t < eps:
                continue
            events.append(ChordEvent(start_bar=t, end_bar=end, symbol=symbol))
            t = end
            safety -= 1
        if not plan:
            break
    return events


def chord_at_position(
    events: list[ChordEvent], bar_position: float,
) -> Optional[str]:
    """Return the chord symbol active at the given fractional bar position,
    or ``None`` if outside any event. Useful for rhythm patterns that
    decide per-hit which chord they're sounding."""
    for ev in events:
        if ev.start_bar - 1e-9 <= bar_position < ev.end_bar - 1e-9:
            return ev.symbol
    # Boundary case: position exactly at the final event's end → use final
    if events and abs(bar_position - events[-1].end_bar) < 1e-6:
        return events[-1].symbol
    return None


def _voicing_with_minimal_motion(
    candidate: list[int], previous: list[int],
) -> list[int]:
    """Return a re-spelling of ``candidate`` that minimises total
    semitone motion from ``previous``. Used for chord voice leading
    so successive chords share common tones / move smoothly rather
    than respawning fresh each time.

    Candidates: the natural voicing plus four octave-related variants
    (whole voicing +12, whole -12, top voice -12, bottom voice +12).
    Each scored by ``sum(min(|p - q| for q in previous))`` across the
    candidate's pitches. Lowest score wins.
    """
    if not previous or not candidate:
        return candidate

    base = list(candidate)
    variants: list[list[int]] = [base]
    variants.append([p + 12 for p in base])
    variants.append([p - 12 for p in base])
    if len(base) >= 2:
        variants.append(sorted(base[:-1] + [base[-1] - 12]))
        variants.append(sorted([base[0] + 12] + base[1:]))

    def motion(voicing: list[int]) -> int:
        return sum(min(abs(p - q) for q in previous) for p in voicing)

    return min(variants, key=motion)


def _melody_pitches_in_window(
    melody_track, start_t: float, end_t: float,
) -> set:
    """Pitches the melody plays at any point overlapping
    ``[start_t, end_t)``. Used for chord-melody collision avoidance."""
    out: set = set()
    for n in melody_track.notes:
        if n.end <= start_t + 1e-9:
            continue
        if n.start >= end_t - 1e-9:
            continue
        out.add(n.pitch)
    return out


def _velocity_for_position(
    pos: float, shape: str, vmin: int, vmax: int,
) -> int:
    """Return a velocity value sampled from a phrase-shape contour.

    ``pos`` is the note's position in the phrase in [0, 1]. ``shape``
    matches one of the :data:`PHRASE_CONTOURS` values. Output sits
    between ``vmin`` and ``vmax``. Callers typically add small per-note
    jitter on top to keep the curve sounding human.

    Curves:
      - ``arc``: soft start, peak at ~50%, soft end (half-sine).
      - ``rise``: linear vmin → vmax.
      - ``fall``: linear vmax → vmin.
      - ``valley``: peak at start and end, dip in the middle.
      - ``call_response``: peaks twice (alternating halves at vmax).
      - ``plateau``: flat at the midpoint.
    """
    import math

    pos = max(0.0, min(1.0, float(pos)))
    span = max(0, int(vmax) - int(vmin))
    base = int(vmin)
    s = (shape or "arc").lower()
    # Accept both the bare PHRASE_CONTOURS keys ("arc") and the
    # "phrase_<name>" prefix that callers use to flag this as a curve
    # mode (vs the "flat" default).
    if s.startswith("phrase_"):
        s = s[len("phrase_"):]

    if s == "rise":
        return base + int(round(span * pos))
    if s == "fall":
        return base + int(round(span * (1.0 - pos)))
    if s == "arc":
        # Half-sine peaks at pos=0.5.
        return base + int(round(span * math.sin(pos * math.pi)))
    if s == "valley":
        # Inverted half-sine — high at both ends.
        return base + int(round(span * (1.0 - math.sin(pos * math.pi))))
    if s == "call_response":
        # Two peaks (each half of the phrase has its own arc).
        local = (pos * 2.0) % 1.0
        return base + int(round(span * math.sin(local * math.pi)))
    # plateau and unknowns → midpoint
    return base + span // 2


def _avoid_collisions(
    chord_pitches: list[int], collisions: set,
    root: int, quality: str,
) -> list[int]:
    """For each pitch in ``chord_pitches`` that overlaps the melody at
    this segment, swap to the nearest chord tone of the same chord
    that doesn't collide. If every nearby chord tone is colliding,
    drop the pitch. Input is not mutated.
    """
    if not collisions:
        return list(chord_pitches)
    third = 4 if quality not in ("min", "dim", "min7") else 3
    intervals = [0, third, 7]
    if quality in ("dom7", "maj7", "min7"):
        intervals.append(11 if quality == "maj7" else 10)

    out: list[int] = []
    for p in chord_pitches:
        if p not in collisions:
            out.append(p)
            continue
        # Find the nearest non-colliding chord tone in any octave
        # within ±18 semitones of the original.
        candidates = []
        for oct_shift in (0, -12, 12, -24, 24):
            for i in intervals:
                cand = root + i + oct_shift
                if abs(cand - p) > 18:
                    continue
                if cand in collisions:
                    continue
                candidates.append(cand)
        if candidates:
            out.append(min(candidates, key=lambda c: abs(c - p)))
        # else: drop the pitch — every nearby chord tone collides.
    return out


# ---------------------------------------------------------------------------
# Per-instrument progression overrides
# ---------------------------------------------------------------------------
#
# The MIDI Compose tab keeps one *master* progression that all three
# instrument generators read. ``InstrumentProgression`` is a slim layer
# on top of the master: one cell per :class:`ChordEvent` in the
# master's expansion, with a parallel `manual` flag per cell. When the
# user locks a cell (``manual[i] = True``) it survives subsequent
# master edits; cells with ``manual[i] = False`` re-sync from the
# master automatically.
#
# ``resolve_instrument_plan`` bakes the override + master durations
# back into a :data:`ProgressionPlan` that any of the existing
# generators (``add_chord_progression``, ``add_bass_line``,
# ``add_melody``) can consume without changes.


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class NoteEvent:
    """A single MIDI note."""
    pitch: int          # MIDI note number (0-127)
    start: float        # Start time in seconds
    end: float          # End time in seconds
    velocity: int = 80  # MIDI velocity (0-127)


@dataclass
class BendEvent:
    """A pitch-bend breakpoint, stored in *semitones* (range-independent).

    Converted to pretty_midi's 14-bit value at build time using the
    owning track's ``bend_range_st`` so callers never juggle 14-bit math.
    """
    time: float          # Seconds
    semitones: float     # Offset from concert pitch (+up / -down)


@dataclass
class CCEvent:
    """A MIDI control-change event (also used to carry RPN bend-range setup)."""
    time: float
    number: int          # CC controller number
    value: int           # 0-127


@dataclass
class Track:
    """A collection of notes assigned to an instrument."""
    name: str
    program: int = 0        # General MIDI program number
    channel: int = 0
    notes: list[NoteEvent] = field(default_factory=list)
    is_drum: bool = False   # If True, uses channel 9
    # Expressive articulation, emitted alongside notes at build time.
    bends: list[BendEvent] = field(default_factory=list)
    ccs: list[CCEvent] = field(default_factory=list)
    # FluidSynth's default pitch-bend range is +/-2 semitones; widen it
    # (via an RPN CC sequence) for bends beyond a whole tone.
    bend_range_st: float = 2.0


# ---------------------------------------------------------------------------
# MidiExporter
# ---------------------------------------------------------------------------

class MidiExporter:
    """Build and export MIDI files from musical ideas.

    Example usage::

        midi = MidiExporter(tempo=120)
        midi.add_chord_progression("C", ["I", "V", "vi", "IV"], bars=4, octave=3)
        midi.add_melody("C", "pentatonic_minor", bars=4, octave=5)
        midi.add_drum_pattern("basic_rock", bars=4)
        midi.save("data/outputs/my_song.mid")
    """

    def __init__(self, tempo: float = 120.0,
                 time_signature: tuple[int, int] = (4, 4)):
        self.tempo = tempo
        self.time_signature = time_signature
        self._meter = meter_info(time_signature)
        self.beats_per_bar = self._meter["beats_per_bar"]
        self.tracks: list[Track] = []

    @property
    def beat_duration(self) -> float:
        """Duration of one quarter note in seconds.

        Always quarter-note-based (pretty_midi convention) regardless of meter.
        For converting pattern offsets, use ``pulse_unit`` instead.
        """
        return 60.0 / self.tempo

    @property
    def pulse_unit(self) -> float:
        """Duration of one counted pulse in seconds.

        Equals ``beat_duration`` for 4/4 and 3/4; equals ``beat_duration / 2``
        for 6/8. Pattern tables (drum / strum / bass) use counted pulses for
        their offsets and durations, so this is what we multiply by.
        """
        return self.beat_duration * self._meter["pulse_unit_in_quarters"]

    @property
    def bar_duration(self) -> float:
        """Duration of one bar in seconds."""
        return self.pulse_unit * self.beats_per_bar

    def _track_for(
        self,
        name: str,
        program: int = 0,
        is_drum: bool = False,
        channel: int = 0,
    ) -> Track:
        """Return an existing track by name, or create and append a new one.

        This lets section-based renderers call add_* repeatedly for the same
        logical track (e.g. "Bass" across intro/verse/chorus) and have the
        notes merge into a single MIDI instrument.
        """
        for t in self.tracks:
            if t.name == name:
                return t
        track = Track(name=name, program=program, is_drum=is_drum, channel=channel)
        self.tracks.append(track)
        return track

    # -- high-level builders ------------------------------------------------

    def add_chord_progression(
        self,
        key: str = "C",
        progression: Optional[ProgressionPlan] = None,
        bars: int = 4,
        octave: int = 3,
        velocity: int = 70,
        track_name: str = "Chords",
        program: int = 0,  # Acoustic Grand Piano
        scale_name: str = "major",
        voicing: str = "triad",
        bar_offset: int = 0,
        rhythm: str = "pad",
        swing: float = 0.0,
        voice_leading: str = "fresh",
        avoid_melody_track: Optional[str] = None,
        rhythm_overrides: Optional[list[dict]] = None,
    ) -> "MidiExporter":
        """Add a chord progression using Roman numerals.

        ``progression`` accepts two shapes:

        - ``["I", "V", "vi", "IV"]`` — bare strings, one bar each (legacy).
        - ``[("I", 0.5), ("V", 0.5), ("vi", 1.0), "IV", ("ii", 0.25)]`` —
          mixed tuples and bare strings, where the second element of each
          tuple is the chord's duration in bars (any positive float). Bare
          strings still default to 1.0 bar.

        Sub-bar durations split a single bar into multiple chord segments;
        each segment renders the rhythm pattern (``pad`` / ``pulse_quarter``
        / arpeggio / ...) starting fresh at the segment's start, with
        hits past the segment end truncated. Long durations loop the bar's
        worth of hits within the segment. The progression as a whole tiles
        ``bars``, looping the input cell as needed.
        """
        if progression is None:
            progression = ["I", "V", "vi", "IV"]

        root_midi = note_name_to_midi(key, octave)
        track = self._track_for(track_name, program=program)
        beat = self.pulse_unit
        bpb = self.beats_per_bar
        base_t = bar_offset * self.bar_duration

        is_arpeggio = rhythm in ARPEGGIO_PATTERNS
        strum_hits = self._resolve_strum_hits(rhythm)

        events = expand_progression_plan(progression, bars)
        prev_voicing: Optional[list[int]] = None
        # Pre-load melody track pitches (per overlap window) if we're
        # asked to avoid collisions. Cached once because the melody
        # track is immutable by the time we run.
        melody_track: Optional[Track] = None
        if avoid_melody_track:
            for t in self.tracks:
                if t.name == avoid_melody_track:
                    melody_track = t
                    break
        # Resolve the song's scale once — we use it to compute the
        # diatonic 7th and 9th above each chord root so extensions
        # land in-key (the renderer's fallback was always maj7+9,
        # which sounded explicitly chromatic for V/iii/vi chords in
        # a major-keyed song).
        scale_intervals = SCALES.get(scale_name, SCALES["major"])
        for event in events:
            offset, quality = roman_to_semitone_offset(event.symbol, scale_name)
            root = root_midi + offset
            # Locate the chord root within the song's scale. When the
            # chord is non-diatonic (e.g. secondary dominants like II7
            # in C major), the lookup fails and we fall back to the
            # quality-based defaults inside ``voice_chord``.
            scale_seventh = None
            scale_ninth = None
            try:
                root_degree = scale_intervals.index(offset % 12)
            except ValueError:
                root_degree = None
            if root_degree is not None:
                n = len(scale_intervals)
                seventh_pc = scale_intervals[(root_degree + 6) % n]
                ninth_pc = scale_intervals[(root_degree + 1) % n]
                scale_seventh = (seventh_pc - (offset % 12)) % 12
                scale_ninth = ((ninth_pc - (offset % 12)) % 12) + 12
            pitches = voice_chord(
                root, quality, voicing,
                scale_degree_seventh=scale_seventh,
                scale_degree_ninth=scale_ninth,
            )
            seg_start_time = base_t + event.start_bar * self.bar_duration
            seg_end_time = base_t + event.end_bar * self.bar_duration
            seg_duration_beats = event.duration_bars * bpb

            # Voice leading: pick the closest re-spelling of this chord
            # to the previous one. Tries the natural voicing plus a few
            # octave-shifted candidates; the root stays put (lowest
            # voice = chord root), the upper voices may invert.
            if voice_leading == "common_tone" and prev_voicing:
                pitches = _voicing_with_minimal_motion(pitches, prev_voicing)
            prev_voicing = list(pitches)

            # Collision avoidance: if any chord pitch matches a melody
            # pitch active during this segment, substitute the nearest
            # chord tone that doesn't collide.
            if melody_track is not None:
                colliding = _melody_pitches_in_window(
                    melody_track, seg_start_time, seg_end_time,
                )
                if colliding:
                    pitches = _avoid_collisions(pitches, colliding, root, quality)

            if is_arpeggio:
                arp = ARPEGGIO_PATTERNS[rhythm]
                seq = _arp_pitch_sequence(len(pitches), arp["hits"], arp["direction"])
                hit_dur_beats = bpb / arp["hits"]
                grid = "16th" if arp["hits"] >= 12 else "8th"
                # The arp pattern spans 1 bar; for super-bar segments we
                # loop, for sub-bar segments we truncate.
                num_loops = max(1, int(event.duration_bars + 1e-9))
                for loop in range(num_loops):
                    loop_start = seg_start_time + loop * self.bar_duration
                    for i, pitch_idx in enumerate(seq):
                        beat_off = i * hit_dur_beats
                        swung = apply_swing(beat_off, swing, grid=grid)
                        start = loop_start + swung * beat
                        if start >= seg_end_time - 1e-9:
                            break
                        end = min(start + hit_dur_beats * beat * 0.9,
                                  seg_end_time)
                        if end - start < 1e-6:
                            continue
                        track.notes.append(NoteEvent(
                            pitches[pitch_idx], start, end, velocity
                        ))
            elif strum_hits is not None:
                grid = "16th" if any(
                    abs((h[0] / 0.25) - round(h[0] / 0.25)) < 1e-6
                    and abs((h[0] / 0.5) - round(h[0] / 0.5)) > 1e-6
                    for h in strum_hits
                ) else "8th"
                num_loops = max(1, int(event.duration_bars + 1e-9))

                def _emit_hits(loop_start: float, hits, hit_off_in_bar: float = 0.0):
                    """Inner: emit a list of hits relative to ``loop_start``,
                    shifting their beat offsets by ``hit_off_in_bar``."""
                    for beat_off, dur_beats, vel_mult in hits:
                        actual_off = beat_off + hit_off_in_bar
                        swung = apply_swing(actual_off, swing, grid=grid)
                        start = loop_start + swung * beat
                        if start >= seg_end_time - 1e-9:
                            break
                        end = min(start + dur_beats * beat, seg_end_time)
                        if end - start < 1e-6:
                            continue
                        vel = int(velocity * vel_mult)
                        for pitch in pitches:
                            track.notes.append(NoteEvent(pitch, start, end, vel))

                for loop in range(num_loops):
                    loop_start = seg_start_time + loop * self.bar_duration
                    abs_bar = int(event.start_bar) + loop
                    # Per-bar / per-half-bar override path. Falls through
                    # to the master rhythm if no override fires for this
                    # bar's halves.
                    eff_h1 = _resolve_chord_rhythm(
                        rhythm_overrides, rhythm, abs_bar, 0,
                    )
                    eff_h2 = _resolve_chord_rhythm(
                        rhythm_overrides, rhythm, abs_bar, 1,
                    )
                    if eff_h1 == rhythm and eff_h2 == rhythm:
                        # Fast path — uniform bar matches the global
                        # rhythm. Use the pre-computed strum_hits.
                        _emit_hits(loop_start, strum_hits)
                        continue
                    if eff_h1 == eff_h2:
                        bar_hits = self._resolve_strum_hits(eff_h1)
                        if bar_hits is None:
                            _emit_hits(loop_start, strum_hits)
                        else:
                            _emit_hits(loop_start, bar_hits)
                        continue
                    # Half-bar split: each half gets its own compressed
                    # rhythm cell.
                    half_target = bpb / 2.0
                    h1_hits = self._resolve_strum_hits(
                        eff_h1, half_beats=half_target,
                    ) or []
                    h2_hits = self._resolve_strum_hits(
                        eff_h2, half_beats=half_target,
                    ) or []
                    _emit_hits(loop_start, h1_hits)
                    _emit_hits(loop_start, h2_hits, hit_off_in_bar=half_target)
            else:
                # Unknown rhythm → fall back to pad-style sustained chord
                # spanning the whole segment.
                for pitch in pitches:
                    track.notes.append(NoteEvent(
                        pitch, seg_start_time, seg_end_time, velocity
                    ))

        return self

    def _resolve_strum_hits(
        self, rhythm: str, half_beats: Optional[float] = None,
    ):
        """Look up strum-rhythm hit table, generating meter-aware versions for
        auto-scaling rhythms (pad, pulse_quarter, stabs_8th).

        When ``half_beats`` is provided, the rhythm is compressed into a
        half-bar slot of that many beats — used by
        :meth:`add_chord_progression` when a per-half-bar override fires
        a different rhythm on beats [bpb/2, bpb). The pattern's relative
        shape is preserved (tresillo on half 2 still sounds like
        tresillo, just inside a 2-beat cell). Hits whose scaled offset
        exceeds ``half_beats`` are dropped.

        Returns a list of (beat_off, dur_beats, vel_mult) tuples or ``None``.
        """
        bpb = self.beats_per_bar
        target = float(half_beats) if half_beats is not None else float(bpb)
        if rhythm == "pad":
            return [(0.0, target, 1.0)]
        if rhythm == "pulse_quarter":
            base_vels = [1.0, 0.85, 0.95, 0.8]
            n_quarters = max(1, int(round(target)))
            return [(float(b), 0.9, base_vels[b % 4]) for b in range(n_quarters)]
        if rhythm == "stabs_8th":
            n_eighths = max(1, int(round(target * 2)))
            return [(i * 0.5, 0.35, 1.0 if i % 2 == 0 else 0.78)
                    for i in range(n_eighths)]
        base = STRUM_RHYTHMS.get(rhythm)
        if base is None or half_beats is None:
            return base
        # Compress the bar-relative pattern into the half-bar cell.
        scale = target / float(bpb)
        compressed: list = []
        for off, dur, vel in base:
            new_off = off * scale
            new_dur = dur * scale
            if new_off + 1e-6 >= target:
                continue
            # Clamp the tail of the last hit so it doesn't bleed past
            # the cell boundary.
            new_dur = min(new_dur, target - new_off)
            compressed.append((new_off, new_dur, vel))
        return compressed

    def add_melody(
        self,
        key: str = "C",
        scale_name: str = "major",
        bars: int = 4,
        octave: int = 5,
        note_density: float = 0.6,
        velocity_range: tuple[int, int] = (65, 100),
        track_name: str = "Melody",
        program: int = 0,
        seed: Optional[int] = None,
        swing: float = 0.0,
        bar_offset: int = 0,
        density: float = 1.0,
        progression: Optional[list[str]] = None,
        melody_style: str = "motif",
        phrase_shape: str = "arc",
        cadence: Optional[str] = "authentic_v_i",
        motif_development: Optional[list[str]] = None,
        rhythm_motif: Optional[str] = None,
        velocity_curve: str = "flat",
        lick_pool: Optional[list[str]] = None,
        expression: Optional[Union[str, dict]] = None,
    ) -> "MidiExporter":
        """Generate a melody.

        ``expression`` adds human articulation to the melody via pitch
        bends (scoop into strong notes, vibrato on sustains, fall off
        phrase ends). ``None`` (default) = plain notes, byte-identical to
        the legacy output. Pass a preset name (``"light"`` / ``"full"`` /
        ``"vocal"``) or a dict of depths (see ``MELODY_EXPRESSION``). Only
        audible on instrument-rendered melodies (FluidSynth honours pitch
        bends); sung vocals ignore them, so leave it off for vocal tracks.

        ``melody_style``:
          - ``random``: scale-constrained random walk (legacy behavior).
          - ``motif``: 2-bar rhythm motif; strong beats prefer chord tones,
            weak beats step through the diatonic scale.
          - ``riff``: 1-bar motif (Fame-style repetition).
          - ``chord_tone``: pure-arpeggio walk — both strong and weak beats
            land on chord tones, with ~15% diatonic passing tones for
            variety. Best for pop / R&B / synthpop / chiptune leads.
          - ``pentatonic``: strong beats are chord tones, weak beats step
            through the **pentatonic** scale of the key (major-pent for
            major-keyed sections, minor-pent for minor). No half-steps so
            every weak beat sits "safe" — best for rock / metal / country.
          - ``blues``: like ``pentatonic`` but the weak-beat palette is the
            **blues scale** (includes the ♭5 blue note). Best for blues,
            saloon piano, 90s hip-hop sample beds.

        When ``progression`` is provided, the melody follows the chord
        changes bar-by-bar regardless of style.

        **Melody-shape parameters** (Track A from the melody-quality plan):

          - ``phrase_shape``: position-weighted contour bias across the full
            phrase. ``arc`` (default) rises into a peak around 60% of the
            phrase and falls; ``rise`` ascends monotonically; ``fall``
            descends; ``valley`` does the inverse of arc; ``plateau`` stays
            flat; ``call_response`` rises in the first half, falls in the
            second. The old uniform ``rng.choice([-2,-1,1,2])`` per-note
            random walk is the ``plateau`` shape with extra jitter.
          - ``cadence``: forces the final melody note of the phrase to land
            on the cadence's target scale degree. Key to giving the phrase
            a sense of arrival. See :data:`CADENCES`. Pass ``None`` to
            disable (legacy behaviour).
          - ``motif_development``: list of per-block transformation ops
            chosen from :data:`MOTIF_DEVELOPMENT_OPS`. The 1st block emits
            the rhythm pattern as-is; the Nth block applies op N-1.
            Defaults to a tasteful 4-block plan (``["repeat", "sequence_up",
            "repeat", "cadence"]``) that gives "theme, lift, theme, resolve"
            without configuration.
        """
        rng = np.random.default_rng(seed)
        expr = _resolve_expression(expression)
        # Articulation uses its OWN rng so turning expression on/off never
        # changes the generated notes — it only adds bends on top.
        expr_rng = np.random.default_rng((seed or 0) + 999983) if expr else None
        scale_ints = SCALES.get(scale_name, SCALES["major"])
        root_midi = note_name_to_midi(key, octave)
        # Vocal-range palette: one octave from key root — caps top at the
        # octave above. Singers need headroom, so the anchor can still land
        # on chord tones inside this octave.
        scale_pitches = sorted({
            root_midi + iv for iv in scale_ints
        } | {root_midi + 12})  # add the octave as a reachable high point

        # Per-style weak-beat palette. ``palette_pitches`` is what
        # ``_step_through_palette`` walks for non-chord-tone-styled events.
        # For ``chord_tone`` style we use chord pitches per-bar instead, so
        # ``palette_pitches`` doubles as the passing-tone (diatonic) source.
        _MINOR_FLAVOR = {"minor", "harmonic_minor", "melodic_minor",
                         "dorian", "phrygian", "pentatonic_minor", "blues"}
        if melody_style == "pentatonic":
            pent_name = "pentatonic_minor" if scale_name in _MINOR_FLAVOR else "pentatonic_major"
            palette_intervals = SCALES[pent_name]
        elif melody_style == "blues":
            palette_intervals = SCALES["blues"]
        elif melody_style == "raga_yaman":
            palette_intervals = SCALES["raga_yaman"]
        elif melody_style == "raga_bhairavi":
            palette_intervals = SCALES["raga_bhairavi"]
        elif melody_style == "maqam_hijaz":
            palette_intervals = SCALES["maqam_hijaz"]
        elif melody_style == "maqam_rast":
            palette_intervals = SCALES["maqam_rast"]
        elif melody_style == "gamelan_slendro":
            palette_intervals = SCALES["gamelan_slendro"]
        elif melody_style == "hirajoshi":
            palette_intervals = SCALES["hirajoshi"]
        else:
            palette_intervals = scale_ints

        palette_pitches = sorted({
            root_midi + iv for iv in palette_intervals
        } | {root_midi + 12})

        track = self._track_for(track_name, program=program)
        beat = self.pulse_unit
        effective_density = note_density * max(0.0, min(1.0, density))
        base_t = bar_offset * self.bar_duration
        vmin, vmax = velocity_range

        if progression is None or melody_style == "random":
            return self._add_melody_random(
                rng, track, scale_pitches, bars, beat, base_t, swing,
                effective_density, vmin, vmax,
            )

        # Motif-based generation ------------------------------------------
        motif_bars = 1 if melody_style == "riff" else 2

        # A rhythm template is a list of (beat_offset_within_motif, duration_beats, is_accent)
        # Generated once per section, then applied to each (motif_bars)-bar group.
        rhythm = _generate_rhythm_motif(
            rng, motif_bars=motif_bars, density=effective_density, swing=swing,
            beats_per_bar=self.beats_per_bar,
            strong_pulses=self._meter["strong_pulses"],
            time_signature=self.time_signature,
            rhythm_motif=rhythm_motif,
        )

        # Contour template: small integer offsets (in scale steps) from the
        # chord-tone anchor. Accent positions are forced to 0 (chord tone);
        # others step up or down by 1-2 scale degrees.
        contour = [
            0 if ev["accent"] else int(rng.choice([-2, -1, 1, 2]))
            for ev in rhythm
        ]

        def _nearest_chord_tone(target_pitch: int, chord_pitches: list[int]) -> int:
            # Look for chord-tone pitches inside the vocal palette only, so the
            # anchor can't drift into high octaves.
            pcs = {p % 12 for p in chord_pitches}
            options = [p for p in scale_pitches if p % 12 in pcs]
            if not options:
                return chord_pitches[0]
            return min(options, key=lambda p: abs(p - target_pitch))

        def _nearest_scale_pitch(target: int) -> int:
            return min(scale_pitches, key=lambda p: abs(p - target))

        anchor = root_midi  # start at the key tonic (vocal range)
        total_motifs = bars // motif_bars
        extra_bars = bars - total_motifs * motif_bars  # leftover if bars odd

        # ----- Phrase-shape contour bias -------------------------------
        # Maps block index (0..total_motifs-1) to an extra scale-step
        # shift so the whole phrase traces an arc / rise / fall / etc.
        # Replaces the legacy cosmetic ``[0, 0, 1, 0, -1, 0, 2, 0]``
        # variation pattern with position-aware shaping.
        def _phrase_shift(block_idx: int) -> int:
            if total_motifs <= 1:
                return 0
            pos = block_idx / max(1, total_motifs - 1)   # 0..1
            shape = (phrase_shape or "arc").lower()
            if shape == "rise":
                return int(round(-2 + 4 * pos))                 # -2..+2
            if shape == "fall":
                return int(round(2 - 4 * pos))                  # +2..-2
            if shape == "arc":
                # Triangle peaking at pos=0.6
                peak = 0.6
                if pos <= peak:
                    return int(round(-2 + 4 * (pos / peak)))
                return int(round(2 - 4 * ((pos - peak) / (1 - peak))))
            if shape == "valley":
                low = 0.5
                if pos <= low:
                    return int(round(2 - 4 * (pos / low)))
                return int(round(-2 + 4 * ((pos - low) / (1 - low))))
            if shape == "call_response":
                if pos <= 0.5:
                    return int(round(-1 + 4 * (pos / 0.5)))       # -1..+3
                return int(round(3 - 4 * ((pos - 0.5) / 0.5)))    # +3..-1
            return 0  # plateau

        # ----- Motif-development plan ----------------------------------
        # Per-block op list. Defaults to a tasteful 4-step plan that fits
        # a typical 8-bar / 2-bar-motif phrase. Repeats fill if there are
        # more blocks than ops. "restate" returns to block 0's contour
        # at phrase end — gives every melody a sense of thematic return
        # instead of the cadence op's bare final-note snap.
        _DEFAULT_MOTIF_PLAN = ["repeat", "sequence_up", "repeat", "restate"]
        dev_plan = list(motif_development or _DEFAULT_MOTIF_PLAN)

        def _dev_op_for_block(block_idx: int) -> str:
            return dev_plan[block_idx % len(dev_plan)] if dev_plan else "repeat"

        def _dev_step_shift(op: str) -> int:
            """Extra scale-step shift introduced by the motif-development op.

            Only the sequence ops carry a pure step-shift. Other ops
            (inversion, retrograde, augmentation) reshape the motif's
            rhythm + contour rather than transposing it — those are
            applied via :func:`_apply_motif_op` below."""
            if op == "sequence_up":
                return 2     # up one diatonic step (~2 semitones)
            if op == "sequence_down":
                return -2
            return 0

        # Captured on the first call to _apply_motif_op so the
        # "restate" op can return block 0's contour at phrase end. We
        # store a copy so subsequent mutations don't pollute it.
        base_contour_ref: list[list[int]] = []

        def _apply_motif_op(rh, cn, op: str):
            """Reshape the per-event ``rhythm`` and ``contour`` lists
            according to the motif-development operator.

            - ``inversion``: mirror the contour around 0 — each up-step
              becomes a down-step. Pitches now move opposite to the
              base motif.
            - ``retrograde``: play the motif's events back-to-front.
            - ``augmentation``: take every other event and double its
              duration — same total bar length, half as many notes,
              twice as long each (slower, more deliberate feel).
            - ``restate``: return the OPENING motif's contour over the
              current chord — gives the phrase a sense of thematic
              return rather than ending on a bare cadence snap. The
              base contour is captured from the very first block.
            - everything else (``repeat`` / ``sequence_up/down`` /
              ``cadence``): no rhythmic or contour reshape.

            Returns ``(rhythm', contour')`` — both fresh lists, never
            mutates the input.
            """
            # Capture base contour on first call so "restate" later
            # has something to reach back for.
            if not base_contour_ref:
                base_contour_ref.append(list(cn))
            if op == "inversion":
                return list(rh), [-s for s in cn]
            if op == "retrograde":
                return list(reversed(rh)), list(reversed(cn))
            if op == "augmentation":
                # Halve event density, double each survivor's duration.
                new_rh = []
                for ev in rh[::2]:
                    new_rh.append({**ev, "duration": ev["duration"] * 2.0})
                return new_rh, list(cn[:len(new_rh)])
            if op == "restate":
                # Reach back for the opening motif's contour. Fall
                # through to "repeat" semantics if we somehow got
                # called before block 0 captured (defensive).
                base = base_contour_ref[0] if base_contour_ref else cn
                return list(rh), list(base)
            return list(rh), list(cn)

        # Expand the progression plan once so each melody note can look up
        # the chord at its exact fractional bar position. Sub-bar chord
        # changes therefore affect strong-beat anchor selection naturally.
        _events = expand_progression_plan(progression, bars)

        def _intra_note_bias(note_pos: float, shape: str) -> int:
            """Small ±1 nudge added to the per-note random step so the
            contour reads as that shape WITHIN each block, not just
            block-to-block. ``note_pos`` is the note's position in
            [0, 1] across the whole phrase.
            """
            s = (shape or "arc").lower()
            if s == "rise":
                return 1 if note_pos > 0.4 else 0
            if s == "fall":
                return -1 if note_pos > 0.4 else 0
            if s == "arc":
                if 0.3 < note_pos < 0.7:
                    return 1
                if note_pos >= 0.7:
                    return -1
                return 0
            if s == "valley":
                if 0.3 < note_pos < 0.7:
                    return -1
                if note_pos >= 0.7:
                    return 1
                return 0
            if s == "call_response":
                # Alternating high/low halves within each block.
                return 1 if (note_pos * 4) % 1 < 0.5 else -1
            return 0  # plateau

        def _emit_block(block_bar_idx: int, variation: int, local_bars: int,
                        block_idx: int = 0,
                        block_rhythm: Optional[list] = None,
                        block_contour: Optional[list[int]] = None):
            """Emit one motif block starting at bar block_bar_idx.

            ``block_rhythm`` / ``block_contour`` override the outer
            ``rhythm`` / ``contour`` lists when a motif-development op
            (inversion / retrograde / augmentation) has reshaped them
            for this block. Default = outer lists (no-op for ``repeat``)."""
            nonlocal anchor
            rh = block_rhythm if block_rhythm is not None else rhythm
            cn = block_contour if block_contour is not None else contour
            denom = max(1, total_motifs * len(rh))
            for i, ev in enumerate(rh):
                # Which bar within the block this event falls in
                bar_within = min(local_bars - 1, int(ev["beat"] // self.beats_per_bar))
                beat_in_bar = ev["beat"] - self.beats_per_bar * bar_within
                world_bar = block_bar_idx + bar_within
                if world_bar >= bars:
                    return
                # Chord at the event's fractional bar position so sub-bar
                # chord changes pick up the right anchor.
                position_bars = world_bar + (beat_in_bar / self.beats_per_bar)
                symbol = chord_at_position(_events, position_bars) or (
                    _events[0].symbol if _events else "I"
                )
                chord_off, quality = roman_to_semitone_offset(symbol, scale_name)
                chord_root = root_midi + chord_off  # stay in the melody's vocal octave
                chord_pitches = voice_chord(chord_root, quality, "triad")

                step = cn[i] if i < len(cn) else 0
                # Subtle variation across motif repeats (transpose contour ±1 step)
                step += variation
                # Intra-block phrase-shape bias: nudge each note in the
                # direction the macro contour expects at this position
                # in the phrase. Arc peaks mid-phrase, rise climbs, etc.
                note_pos = (block_idx * len(rh) + i) / denom
                step += _intra_note_bias(note_pos, phrase_shape)

                if ev["accent"]:
                    # Strong beat → chord tone near the anchor
                    anchor = _nearest_chord_tone(anchor, chord_pitches)
                    pitch = anchor
                elif melody_style == "chord_tone":
                    # Weak beat → walk through chord tones (arpeggio).
                    # Build chord-tone palette in vocal range from the current
                    # bar's chord pitch-classes, then step by `step` indices.
                    chord_pcs = {p % 12 for p in chord_pitches}
                    ct_palette = [p for p in scale_pitches if p % 12 in chord_pcs]
                    if not ct_palette:
                        ct_palette = list(chord_pitches)
                    nearest = min(ct_palette, key=lambda p: abs(p - anchor))
                    ct_idx = ct_palette.index(nearest)
                    ct_idx = max(0, min(len(ct_palette) - 1, ct_idx + step))
                    pitch = ct_palette[ct_idx]
                    # ~15% passing tone: pick a diatonic scale tone that's
                    # NOT a chord tone, near the would-be chord tone.
                    if rng.random() < 0.15:
                        non_chord = [p for p in scale_pitches if p % 12 not in chord_pcs]
                        if non_chord:
                            pitch = min(non_chord, key=lambda p: abs(p - pitch))
                    anchor = pitch
                else:
                    # Weak beat → step through the per-style palette.
                    # motif/riff: full diatonic scale (legacy behavior).
                    # pentatonic: pentatonic_major or _minor palette.
                    # blues: blues-scale palette (includes the ♭5 blue note).
                    nearest = min(palette_pitches, key=lambda p: abs(p - anchor))
                    pp_idx = palette_pitches.index(nearest)
                    pp_idx = max(0, min(len(palette_pitches) - 1, pp_idx + step))
                    pitch = palette_pitches[pp_idx]
                    anchor = pitch

                vel_accent_boost = 10 if ev["accent"] else 0
                if velocity_curve and velocity_curve != "flat":
                    base = _velocity_for_position(
                        note_pos, velocity_curve, vmin, vmax,
                    )
                    # Light per-note jitter so the curve sounds human,
                    # not a pure sinusoid.
                    vel = base + int(rng.integers(-5, 6)) + vel_accent_boost
                else:
                    vel = int(rng.integers(vmin, vmax + 1)) + vel_accent_boost
                vel = max(1, min(127, vel))

                t = base_t + world_bar * self.bar_duration + beat_in_bar * beat
                dur = ev["duration"] * beat * 0.95
                track.notes.append(NoteEvent(pitch, t, t + dur, vel))
                if expr is not None:
                    self._articulate_melody_note(
                        track, t, dur, bool(ev["accent"]), note_pos,
                        float(ev["duration"]), expr, expr_rng,
                    )

        # Walk the section in motif-length blocks.
        # Each block's variation is the SUM of the phrase-shape bias and
        # the motif-development op's step shift — so an "arc" with a
        # "sequence_up" mid-phrase gets a noticeable lift right at the
        # apex, and the same arc with "repeat" stays smoother.
        for block in range(total_motifs):
            op = _dev_op_for_block(block)
            variation = _phrase_shift(block) + _dev_step_shift(op)
            block_rh, block_cn = _apply_motif_op(rhythm, contour, op)
            _emit_block(block * motif_bars, variation, motif_bars,
                        block_idx=block,
                        block_rhythm=block_rh, block_contour=block_cn)

        # Handle odd leftover (e.g. 7 bars with motif_bars=2)
        if extra_bars > 0:
            _emit_block(total_motifs * motif_bars, 0, extra_bars,
                        block_idx=total_motifs)

        # ----- Lick injection (auto-fire from style variant pool) -----
        # When ``lick_pool`` names one or more MELODIC_LICKS keys, pick
        # one deterministically per phrase and stamp it over the chosen
        # bar — replacing the walker's notes in that bar with the lick.
        # 60% land on the final bar (recognisable "tag"), 40% on the
        # penultimate bar (anacrusis-ish setup).
        if lick_pool and bars >= 1:
            valid_pool = [n for n in lick_pool if n in MELODIC_LICKS]
            if valid_pool:
                rng_lick = np.random.default_rng((seed or 0) + 1337)
                lick_name = valid_pool[int(rng_lick.integers(0, len(valid_pool)))]
                use_final = rng_lick.random() < 0.6
                target_bar = (bars - 1) if use_final else max(0, bars - 2)

                bar_start_t = base_t + target_bar * self.bar_duration
                bar_end_t = bar_start_t + self.bar_duration
                # Drop walker notes that fall inside the target bar.
                track.notes = [
                    n for n in track.notes
                    if not (bar_start_t - 1e-6 <= n.start < bar_end_t - 1e-6)
                ]
                # Stamp the lick's events.
                spec = MELODIC_LICKS[lick_name]
                scale_for_lick = SCALES.get(scale_name, SCALES["major"])
                for beat_off, degree, dur in spec["events"]:
                    t = bar_start_t + float(beat_off) * beat
                    if t >= bar_end_t:
                        continue
                    end = min(
                        t + max(0.05, float(dur) * beat),
                        bar_end_t,
                    )
                    d = max(1, int(degree)) - 1
                    octave_offset, inner = divmod(d, len(scale_for_lick))
                    pitch = (
                        root_midi
                        + scale_for_lick[inner]
                        + 12 * octave_offset
                    )
                    track.notes.append(NoteEvent(pitch, t, end, 95))
                # Re-sort by start so downstream readers (cadence,
                # harmony, follow_line) see notes in time order.
                track.notes.sort(key=lambda n: n.start)

        # ----- Cadence resolution -------------------------------------
        # Replace the no-op phrase-resolution loop that used to live here.
        # When a cadence is named, snap the FINAL emitted note in the
        # melody to the cadence's target scale degree relative to the
        # tonic — giving the phrase a sense of arrival rather than
        # whatever pitch the random walk happened to land on.
        if cadence and track.notes and cadence in CADENCES:
            target_degree = CADENCES[cadence]["melody"][1]   # 1-indexed
            # Pick the in-scale pitch closest to the existing final note
            # but locked to the target degree's pitch class.
            intervals = SCALES.get(scale_name, SCALES["major"])
            if 1 <= target_degree <= len(intervals):
                target_pc = (root_midi + intervals[target_degree - 1]) % 12
                last = track.notes[-1]
                # Search ±12 semitones from the current pitch for the
                # nearest matching pitch-class.
                candidates = [
                    p for p in range(last.pitch - 12, last.pitch + 13)
                    if p % 12 == target_pc
                ]
                if candidates:
                    last.pitch = min(candidates, key=lambda p: abs(p - last.pitch))

        return self

    def _add_melody_random(
        self, rng, track, scale_pitches, bars, beat, base_t, swing,
        effective_density, vmin, vmax,
    ) -> "MidiExporter":
        """Legacy random-walk melody — kept for melody_style='random'."""
        subdivision = beat / 2
        bpb = self.beats_per_bar
        subs_per_bar = bpb * 2  # 8th-note grid
        total_subdivisions = int(bars * subs_per_bar)
        # Start at the bottom of the palette (vocal-range root) rather than
        # the middle, which would be an octave up.
        prev_idx = max(0, len(scale_pitches) // 4)

        for i in range(total_subdivisions):
            beat_offset = (i % subs_per_bar) * 0.5
            swung_beat = apply_swing(beat_offset, swing, grid="8th")
            bar_start = base_t + (i // subs_per_bar) * self.bar_duration
            t = bar_start + swung_beat * beat

            if rng.random() < effective_density:
                step = rng.choice([-2, -1, -1, 0, 1, 1, 2])
                idx = max(0, min(len(scale_pitches) - 1, prev_idx + step))
                prev_idx = idx
                vel = rng.integers(vmin, vmax + 1)
                dur = subdivision * rng.choice([1, 1, 2])
                track.notes.append(NoteEvent(
                    pitch=scale_pitches[idx],
                    start=t,
                    end=t + dur,
                    velocity=int(vel),
                ))
        return self

    def add_bass_line(
        self,
        key: str = "C",
        progression: Optional[list[str]] = None,
        bars: int = 4,
        octave: int = 2,
        pattern: str = "root_fifth",
        velocity: int = 85,
        track_name: str = "Bass",
        program: int = 33,  # Electric Bass (finger)
        scale_name: str = "major",
        swing: float = 0.0,
        bar_offset: int = 0,
        density: float = 1.0,
        seed: Optional[int] = None,
        approach_tones: bool = False,
        pattern_overrides: Optional[list[dict]] = None,
    ) -> "MidiExporter":
        """Add a bass line that follows the chord progression.

        Patterns:
          - ``root`` — whole-note roots
          - ``root_fifth`` — root then fifth, each for two beats
          - ``walking`` — root / third / fifth / passing (quarter notes)
          - ``walking_swing`` — walking but with 8th-note swing
          - ``funk_16ths`` — syncopated 16th-note funk bass
          - ``offbeat`` — 8ths on the "ands" (house feel)
          - ``disco_octave`` — alternating root / root+octave 8ths
          - ``palm_mute_8ths`` — short root 8ths (metal chug)
          - ``flea_slap`` — Flea-style: thumb slaps + octave pops + ghost notes
          - ``geddy_lee`` — Geddy Lee-style: melodic chord-tone 8ths + 16th-note runs

        ``approach_tones=True`` (walking / walking_swing only): on the
        last beat of a bar that's the last bar of a chord segment, the
        chromatic-passing-tone-within-current-chord (``root + 5``) is
        replaced by a chromatic neighbour of the NEXT segment's root.
        Picks the leading-tone (half-step below) by default — the
        classic jazz walking-bass setup that pulls strongly into the
        new chord. No effect on the final segment (there's no "next").
        """
        if progression is None:
            progression = ["I", "V", "vi", "IV"]

        root_midi = note_name_to_midi(key, octave)
        track = self._track_for(track_name, program=program)
        beat = self.pulse_unit
        bpb = self.beats_per_bar
        rng = np.random.default_rng(seed)
        density = max(0.0, min(1.0, density))

        # Build the list of bar-loop tasks from the (possibly fractional)
        # progression plan: one task per bar-length cycle of the pattern,
        # carrying the chord symbol and a hard cutoff for truncation. A
        # 2-bar chord generates 2 tasks; a 0.5-bar chord generates 1 task
        # with seg_end_time at the half-bar mark (the post-iter truncation
        # drops hits past it). Legacy 1-bar-per-chord callers hit the same
        # codepath byte-identically (num_loops=1, no truncation needed).
        import math
        events = expand_progression_plan(progression, bars)
        loop_tasks: list[tuple[float, str, float]] = []
        for event in events:
            num_loops = max(1, math.ceil(event.duration_bars - 1e-9))
            seg_end_time = (bar_offset + event.end_bar) * self.bar_duration
            for li in range(num_loops):
                bar_loop_start = (bar_offset + event.start_bar + li) * self.bar_duration
                loop_tasks.append((bar_loop_start, event.symbol, seg_end_time))

        # Cache the user's master pattern (the kwarg) so per-bar
        # overrides resolve against the original each iteration —
        # otherwise the first override would stick.
        master_pattern = pattern

        for bar_idx, (bar_start, symbol, _seg_end_time) in enumerate(loop_tasks):
            offset, _ = roman_to_semitone_offset(symbol, scale_name)
            root = root_midi + offset
            fifth = root + 7
            _notes_before = len(track.notes)

            # Per-bar pattern override (whole-bar; bass patterns plan
            # walking steps with full-bar knowledge so we don't split).
            pattern = _resolve_bass_pattern(
                pattern_overrides, master_pattern, bar_idx,
            )
            # Walking → non-walking transitions sound abrupt without a
            # leading-tone setup; force approach_tones on for the bar
            # that walks INTO a different pattern.
            bar_approach = approach_tones
            if pattern in ("walking", "walking_swing"):
                if bar_idx + 1 < len(loop_tasks):
                    next_pat = _resolve_bass_pattern(
                        pattern_overrides, master_pattern, bar_idx + 1,
                    )
                    if next_pat not in ("walking", "walking_swing"):
                        bar_approach = True

            if pattern == "root":
                track.notes.append(NoteEvent(root, bar_start,
                                             bar_start + self.bar_duration, velocity))

            elif pattern == "root_fifth":
                # Half-bar root then half-bar fifth, scaled to meter.
                half = bpb / 2
                track.notes.append(NoteEvent(root, bar_start,
                                             bar_start + beat * half, velocity))
                track.notes.append(NoteEvent(fifth, bar_start + beat * half,
                                             bar_start + beat * bpb, velocity))

            elif pattern in ("eight_oh_eight", "sub_octave", "sub_onedrop", "sub_root"):
                # Low sub-bass family (808 + genre subs). Mono root in a low
                # octave — sub tones can't stack or they phase-cancel. Each
                # candidate note is guarded to a minimum length so degenerate
                # chord segments (from pacing) can't leave zero-length clicks.
                bar_end = min(bar_start + self.bar_duration, _seg_end_time)

                def _sub(p, st, en, v=velocity):
                    if en - st > 0.04:
                        track.notes.append(NoteEvent(p, st, min(en, _seg_end_time), v))

                if pattern == "eight_oh_eight":
                    # Trap 808: low root sustained/ringing across each chord
                    # (mono). The syncopated trap bounce comes from the kick +
                    # the hip-hop percussion layer; the 808 just locks the sub
                    # to the chord roots underneath.
                    _sub(root, bar_start, bar_end)

                elif pattern == "sub_octave":
                    # House/disco/funk octave pulse: root / root+octave 8ths.
                    j = 0
                    while bar_start + j * (beat / 2) < bar_end - 0.04:
                        start = bar_start + j * (beat / 2)
                        _sub(root if j % 2 == 0 else root + 12, start, start + beat / 2)
                        j += 1

                elif pattern == "sub_onedrop":
                    # Reggae/dub: root on beat 3 (the "one drop"), held.
                    three_t = bar_start + min(2.0, bpb - 1) * beat
                    _sub(root, three_t if three_t < bar_end - 0.04 else bar_start, bar_end)

                else:  # sub_root — sustained root per bar (techno/prog/default)
                    _sub(root, bar_start, bar_end)

            elif pattern == "waltz_bass":
                # 3/4 waltz: root on 1, fifth on 2, fifth on 3.
                track.notes.append(NoteEvent(root, bar_start,
                                             bar_start + beat, velocity))
                track.notes.append(NoteEvent(fifth, bar_start + beat,
                                             bar_start + beat * 2, velocity - 6))
                track.notes.append(NoteEvent(fifth, bar_start + beat * 2,
                                             bar_start + beat * 3, velocity - 6))

            elif pattern == "compound_6_8_bass":
                # 6/8 ostinato: root on counted-eighth 1, root on counted-eighth 4
                # (the two felt-pulses). Cinematic adventure feel.
                track.notes.append(NoteEvent(root, bar_start,
                                             bar_start + beat * 3, velocity))
                track.notes.append(NoteEvent(root, bar_start + beat * 3,
                                             bar_start + beat * 6, velocity - 4))

            elif pattern in ("walking", "walking_swing"):
                sw = swing if pattern == "walking_swing" else 0.0
                _, quality = roman_to_semitone_offset(symbol, scale_name)
                third = root + (3 if quality in ("min", "dim", "min7") else 4)
                # Quarter-note walk: root, 3rd, 5th, chromatic passing tone.
                # With approach_tones=True, the 4th beat targets the NEXT
                # segment's root via a leading-tone (half-step below) when
                # this is the final bar of the current chord segment.
                approach_note = root + 5
                if bar_approach:
                    # Find the next chord whose symbol differs from this one.
                    next_root: Optional[int] = None
                    for nxt_idx in range(bar_idx + 1, len(loop_tasks)):
                        _, nxt_symbol, _ = loop_tasks[nxt_idx]
                        if nxt_symbol != symbol:
                            nxt_offset, _ = roman_to_semitone_offset(
                                nxt_symbol, scale_name,
                            )
                            next_root = root_midi + nxt_offset
                            break
                    # Only swap when the NEXT bar is a different chord —
                    # mid-segment beats keep the safe within-chord
                    # passing tone, which sounds more natural than
                    # constantly reaching forward.
                    is_last_in_segment = (
                        next_root is not None
                        and bar_idx + 1 < len(loop_tasks)
                        and loop_tasks[bar_idx + 1][1] != symbol
                    )
                    if is_last_in_segment:
                        approach_note = next_root - 1  # leading tone
                walk = [root, third, fifth, approach_note]
                for i, note in enumerate(walk):
                    if i > 0 and rng.random() > density:
                        continue  # thin passing tones first
                    nudge = sw * beat * 0.05 if i in (1, 3) else 0.0
                    start = bar_start + beat * i + nudge
                    track.notes.append(NoteEvent(note, start, start + beat, velocity))

            elif pattern == "funk_16ths":
                hits = [
                    (0.00,  root,       velocity),
                    (0.75,  root,       velocity - 10),
                    (1.50,  fifth,      velocity),
                    (2.00,  root,       velocity),
                    (2.75,  root + 12,  velocity - 5),
                    (3.50,  fifth,      velocity - 5),
                ]
                for i, (beat_off, pitch, vel) in enumerate(hits):
                    if i > 0 and i != 3 and rng.random() > density:
                        continue  # keep downbeat and beat-3 anchor
                    swung = apply_swing(beat_off, swing, grid="16th")
                    start = bar_start + swung * beat
                    track.notes.append(NoteEvent(pitch, start, start + beat * 0.25, int(vel)))

            elif pattern == "offbeat":
                for b in range(bpb):
                    if rng.random() > density:
                        continue
                    start = bar_start + (b + 0.5) * beat
                    track.notes.append(NoteEvent(root, start, start + beat * 0.5, velocity))

            elif pattern == "disco_octave":
                for i in range(bpb * 2):
                    if i > 0 and rng.random() > density:
                        continue
                    pitch = root if i % 2 == 0 else root + 12
                    start = bar_start + i * 0.5 * beat
                    track.notes.append(NoteEvent(pitch, start, start + beat * 0.5, velocity))

            elif pattern == "palm_mute_8ths":
                gate = beat * 0.3
                for i in range(bpb * 2):
                    if i > 0 and rng.random() > density:
                        continue
                    start = bar_start + i * 0.5 * beat
                    track.notes.append(NoteEvent(root, start, start + gate, velocity + 5))

            elif pattern == "flea_slap":
                # Flea-style slap funk: thumb slaps on 1/3, octave pops on
                # syncopated 16ths, ghost-note fills between. Root/5th/octave.
                _, quality = roman_to_semitone_offset(symbol, scale_name)
                min_3 = root + 3 if quality in ("min", "dim", "min7") else root + 4
                # (beat_offset, pitch, velocity_delta, gate_fraction_of_beat)
                hits = [
                    (0.00, root,       0,    0.3),    # thumb slap beat 1
                    (0.75, root,      -45,   0.1),    # ghost note
                    (1.25, root + 7,  -10,   0.25),   # fifth on the "e" of 2
                    (1.50, root + 12, -5,    0.3),    # octave pop "and" of 2
                    (2.00, root,       0,    0.3),    # thumb slap beat 3
                    (2.75, min_3,     -20,   0.1),    # ghost / chromatic
                    (3.25, root + 7,  -8,    0.25),   # fifth
                    (3.50, root + 12, -5,    0.3),    # octave pop on "and" of 4
                ]
                for i, (beat_off, pitch, vdelta, gate) in enumerate(hits):
                    if i > 0 and rng.random() > density:
                        continue
                    swung = apply_swing(beat_off, swing, grid="16th")
                    start = bar_start + swung * beat
                    vel = max(1, min(127, velocity + vdelta))
                    track.notes.append(NoteEvent(pitch, start, start + beat * gate, vel))

            elif pattern == "bootsy_slap":
                # Bootsy Collins-style: bouncier, ghost-note-heavy, chromatic
                # approach tones, heavier syncopation than Flea.
                _, quality = roman_to_semitone_offset(symbol, scale_name)
                min_3 = 3 if quality in ("min", "dim", "min7") else 4
                # (beat_offset, pitch_semitones_from_root, velocity_delta, gate)
                hits = [
                    (0.00, 0,        0,    0.3),    # thumb slap beat 1
                    (0.25, 0,      -45,    0.08),   # ghost "e"
                    (0.50, -2,     -30,    0.12),   # chromatic down
                    (0.75, 0,      -20,    0.12),   # pickup back to root
                    (1.00, 12,      -5,    0.25),   # octave pop beat 2
                    (1.50, 7,      -10,    0.2),    # 5th
                    (1.75, 10,     -20,    0.15),   # b7 chromatic
                    (2.00, 0,        0,    0.3),    # thumb slap beat 3
                    (2.50, 12,      -5,    0.25),   # octave pop
                    (2.75, min_3,  -35,    0.1),    # 3rd ghost
                    (3.25, 7,      -10,    0.2),    # 5th pickup
                    (3.50, 12,      -5,    0.25),   # octave pop
                    (3.75, 0,      -25,    0.1),    # ghost return
                ]
                for i, (beat_off, semi, vdelta, gate) in enumerate(hits):
                    if i > 0 and rng.random() > density:
                        continue
                    swung = apply_swing(beat_off, swing, grid="16th")
                    start = bar_start + swung * beat
                    vel = max(1, min(127, velocity + vdelta))
                    track.notes.append(NoteEvent(root + semi, start, start + beat * gate, vel))

            elif pattern == "geddy_lee":
                # Geddy Lee-style prog bass: melodic 8ths through chord tones
                # with a 16th-note run at the end of each bar.
                _, quality = roman_to_semitone_offset(symbol, scale_name)
                min_chord = quality in ("min", "dim", "min7")
                third = root + (3 if min_chord else 4)
                seventh = root + (10 if (min_chord or quality == "7") else 11)
                octave_up = root + 12
                # (beat_offset, pitch, velocity_delta, gate)
                hits = [
                    (0.00, root,       0,    0.45),   # downbeat root
                    (0.50, fifth,     -8,    0.45),   # 5th
                    (1.00, third,     -4,    0.45),   # 3rd (chord color)
                    (1.50, root,      -6,    0.45),   # back to root
                    (2.00, fifth,     -4,    0.45),   # 5th
                    (2.50, octave_up, -2,    0.45),   # octave lift
                    (3.00, seventh,   -6,    0.45),   # 7th
                    # 16th run into next bar (beat 3.5 + 3.75)
                    (3.50, fifth,     -10,   0.22),
                    (3.75, seventh,   -12,   0.22),
                ]
                for i, (beat_off, pitch, vdelta, gate) in enumerate(hits):
                    if i > 0 and rng.random() > density:
                        continue
                    swung = apply_swing(beat_off, swing, grid="8th")
                    start = bar_start + swung * beat
                    vel = max(1, min(127, velocity + vdelta))
                    track.notes.append(NoteEvent(pitch, start, start + beat * gate, vel))

            elif pattern == "tumbao":
                # Cuban tumbao: anticipated bombo on "and of 2", root on 4,
                # tied across the barline (gate = full beat).
                hits = [
                    (1.5, root,  velocity,      0.5),
                    (3.0, fifth, velocity - 4,  0.5),
                    (3.5, root,  velocity,      0.5),
                ]
                for i, (off, pitch, vel, gate) in enumerate(hits):
                    if i > 0 and rng.random() > density:
                        continue
                    swung = apply_swing(off, swing, grid="8th")
                    start = bar_start + swung * beat
                    track.notes.append(
                        NoteEvent(pitch, start, start + beat * gate, int(vel))
                    )

            elif pattern == "salsa_montuno_bass":
                # Salsa 2-3 montuno bass — anticipations on the "and of 2" and "4".
                hits = [
                    (1.5, root,  velocity,     0.45),
                    (2.0, fifth, velocity - 6, 0.45),
                    (3.5, root,  velocity,     0.5),
                ]
                for i, (off, pitch, vel, gate) in enumerate(hits):
                    if i > 0 and rng.random() > density:
                        continue
                    swung = apply_swing(off, swing, grid="8th")
                    start = bar_start + swung * beat
                    track.notes.append(
                        NoteEvent(pitch, start, start + beat * gate, int(vel))
                    )

            elif pattern == "reggaeton_dembow_bass":
                # Reggaeton dembow root pulse: 1, 1.75, 3, 3.5 (tresillo-derived).
                hits = [
                    (0.0,  root, velocity,     0.5),
                    (1.75, root, velocity - 5, 0.4),
                    (3.0,  root, velocity,     0.5),
                    (3.5,  fifth, velocity - 8, 0.4),
                ]
                for i, (off, pitch, vel, gate) in enumerate(hits):
                    if i > 0 and rng.random() > density:
                        continue
                    swung = apply_swing(off, swing, grid="16th")
                    start = bar_start + swung * beat
                    track.notes.append(
                        NoteEvent(pitch, start, start + beat * gate, int(vel))
                    )

            elif pattern == "samba_partido_alto":
                # Samba partido-alto bass: anticipated bombo + walking surdo feel.
                hits = [
                    (0.0,  root,  velocity,     0.45),
                    (1.5,  fifth, velocity - 4, 0.4),
                    (2.0,  root,  velocity,     0.45),
                    (3.5,  fifth, velocity - 6, 0.4),
                ]
                for i, (off, pitch, vel, gate) in enumerate(hits):
                    if i > 0 and rng.random() > density:
                        continue
                    swung = apply_swing(off, swing, grid="16th")
                    start = bar_start + swung * beat
                    track.notes.append(
                        NoteEvent(pitch, start, start + beat * gate, int(vel))
                    )

            elif pattern == "arabic_iqa_baladi":
                # Iqa baladi-derived bass pulse: DUM-DUM-tek-DUM feel.
                hits = [
                    (0.0,  root,       velocity,     0.45),
                    (0.5,  root,       velocity - 8, 0.3),
                    (2.0,  root + 7,   velocity - 4, 0.4),  # 5th colour
                    (3.0,  root,       velocity,     0.5),
                ]
                for i, (off, pitch, vel, gate) in enumerate(hits):
                    if i > 0 and rng.random() > density:
                        continue
                    swung = apply_swing(off, swing, grid="8th")
                    start = bar_start + swung * beat
                    track.notes.append(
                        NoteEvent(pitch, start, start + beat * gate, int(vel))
                    )

            elif pattern == "indian_dhol_root":
                # Dhol-style steady root pulses with tabla accent on "ti".
                hits = [
                    (0.0,  root, velocity,     0.4),
                    (1.0,  root, velocity - 6, 0.35),
                    (2.0,  root, velocity,     0.4),
                    (2.75, root, velocity - 10, 0.25),  # "ti" accent
                    (3.0,  root, velocity - 4, 0.4),
                ]
                for i, (off, pitch, vel, gate) in enumerate(hits):
                    if i > 0 and rng.random() > density:
                        continue
                    swung = apply_swing(off, swing, grid="8th")
                    start = bar_start + swung * beat
                    track.notes.append(
                        NoteEvent(pitch, start, start + beat * gate, int(vel))
                    )

            elif pattern == "gamelan_balungan":
                # Gamelan balungan core melody — slow root drone with octave
                # lift on beat 3 (the seleh, structural accent).
                track.notes.append(NoteEvent(
                    root, bar_start, bar_start + beat * 2, velocity
                ))
                track.notes.append(NoteEvent(
                    root + 12, bar_start + beat * 2,
                    bar_start + beat * bpb, velocity - 4
                ))

            else:
                track.notes.append(NoteEvent(root, bar_start,
                                             bar_start + self.bar_duration, velocity))

            # Truncate any notes this iteration emitted that bleed past
            # the chord-segment boundary (only matters for sub-bar segments
            # or for the last loop of a non-integer-bar segment; legacy
            # 1-bar chords don't trigger any truncation).
            _seg_end = _seg_end_time
            if track.notes[_notes_before:]:
                trimmed: list[NoteEvent] = []
                for n in track.notes[_notes_before:]:
                    if n.start >= _seg_end - 1e-9:
                        continue
                    if n.end > _seg_end:
                        n = NoteEvent(n.pitch, n.start, _seg_end, n.velocity)
                    trimmed.append(n)
                track.notes[_notes_before:] = trimmed

        return self

    def add_drum_pattern(
        self,
        pattern: str = "basic_rock",
        bars: int = 4,
        velocity: int = 90,
        track_name: str = "Drums",
        swing: float = 0.0,
        bar_offset: int = 0,
        density: float = 1.0,
        seed: Optional[int] = None,
    ) -> "MidiExporter":
        """Add a drum pattern.

        Built-in patterns (all 1 bar of 4/4, velocity is the base — accents
        and ghosts scale off of it):

        - ``basic_rock`` — kick 1/3, snare 2/4, 8th hats
        - ``four_on_floor`` — kick every beat, snare 2/4, 8th hats
        - ``halftime`` — kick 1, snare 3, 8th hats
        - ``funk`` — syncopated kick, snare 2/4 + ghost, 16th hats, open hat on "and of 2"
        - ``dance_house`` — 4-on-floor, clap 2/4, offbeat closed hats, open hat on "and of 4"
        - ``disco`` — 4-on-floor, snare+clap 2/4, open hat on every "and"
        - ``jazz_swing`` — ride spang-a-lang, hats on 2/4 (foot), sparse ghost snare
        - ``metal_gallop`` — 8-16-16 kick gallop, snare 2/4, crash on 1
        - ``metal_blast`` — alternating 16th kick/snare, crash on 1

        Args:
            pattern: Pattern name.
            bars: Number of bars.
            velocity: Base MIDI velocity.
            track_name: Track label.
            swing: Swing amount applied on the native grid (16ths for funk,
                8ths elsewhere). 0 straight, ~0.33 full triplet.
        """
        beat = self.pulse_unit
        eighth = beat / 2
        sixteenth = beat / 4

        meter_table = DRUM_PATTERNS_BY_METER.get(self.time_signature, {})
        hits_and_grid = meter_table.get(pattern)
        if hits_and_grid is None:
            available = sorted(meter_table.keys())
            if not available:
                # No drum patterns defined for this meter at all.
                hits_and_grid = ([], "8th")
            else:
                # Requested pattern isn't defined for this meter (e.g. a
                # 4/4 groove picked for a 6/8 song, or compound_6_8 in
                # 4/4). Fall back to a meter-appropriate default so drums
                # still render instead of dropping out / crashing the
                # whole generation.
                _METER_DEFAULT = {
                    (4, 4): "basic_rock", (3, 4): "waltz_basic",
                    (6, 8): "compound_6_8", (12, 8): "bembe",
                    (7, 8): "prog_7_8", (5, 4): "take_five_5_4",
                }
                fallback = _METER_DEFAULT.get(self.time_signature)
                if fallback not in meter_table:
                    fallback = available[0]
                logging.getLogger("ai_music_studio.midi_export").warning(
                    "drum pattern %r not available in %d/%d — using %r",
                    pattern, self.time_signature[0],
                    self.time_signature[1], fallback,
                )
                hits_and_grid = meter_table[fallback]
        hits, grid = hits_and_grid

        track = self._track_for(track_name, is_drum=True, channel=9)
        gate = sixteenth if grid == "16th" else eighth
        rng = np.random.default_rng(seed)
        density = max(0.0, min(1.0, density))
        # Primary hits — never thinned out even at low density
        primary = {"kick", "snare"}

        for bar in range(bars):
            bar_start = (bar_offset + bar) * self.bar_duration
            for entry in hits:
                # A layer is (drum_name, [(offset, vel_mult), ...]) with an
                # optional trailing layer-shift in beats for DJ-blend grooves.
                if len(entry) == 3:
                    drum_name, offset_vels, layer_shift = entry
                else:
                    drum_name, offset_vels = entry
                    layer_shift = 0.0
                midi_note = GM_DRUMS.get(drum_name, 36)
                for beat_offset, vel_mult in offset_vels:
                    if drum_name not in primary and rng.random() > density:
                        continue
                    swung = apply_swing(beat_offset, swing, grid=grid)
                    t = bar_start + (swung + layer_shift) * beat
                    if t < 0.0:
                        t = 0.0  # never push a hit before the song start
                    vel = int(velocity * vel_mult)
                    track.notes.append(NoteEvent(midi_note, t, t + gate, vel))

        return self

    # -- drum grid editor support ------------------------------------------
    #
    # The grid editor surfaces a 12-row × N-step boolean-with-velocity grid
    # so Stephen can hand-tweak generated drum patterns without leaving the
    # Compose tab. Velocity is collapsed to 4 levels (0=silent, 1=ghost,
    # 2=normal, 3=accent) to keep the click target meaningful — a continuous
    # 0-127 widget per cell was rejected as a v2 enhancement.

    def add_drum_grid(
        self,
        grid: dict[str, list[int]],
        *,
        bars: int = 1,
        base_velocity: int = 90,
        track_name: str = "Drums",
        swing: float = 0.0,
        bar_offset: int = 0,
    ) -> "MidiExporter":
        """Append drum events from a ``(drum_name → list[level])`` grid.

        ``level`` is one of: 0 silent, 1 ghost, 2 normal, 3 accent. The grid
        width must be ``bars × steps_per_bar`` where ``steps_per_bar`` is
        inferred from the row length and the current meter (16ths or 8ths).

        Use :func:`drum_pattern_to_grid` to seed a starting grid from a
        named preset, mutate it, then feed it back here.
        """
        info = self._meter
        bpb = info["beats_per_bar"]
        beat = self.pulse_unit

        first_row = next(iter(grid.values()), [])
        if not first_row or bars <= 0:
            return self
        steps_per_bar = max(1, len(first_row) // bars)
        subdivs = max(1, steps_per_bar // bpb)
        grid_label = "16th" if subdivs >= 4 else "8th"
        gate = beat / max(1, subdivs)

        LEVEL_TO_MULT = {0: 0.0, 1: 0.45, 2: 1.0, 3: 1.15}

        track = self._track_for(track_name, is_drum=True, channel=9)
        for drum_name, levels in grid.items():
            midi_note = GM_DRUMS.get(drum_name)
            if midi_note is None:
                continue
            for step_idx, level in enumerate(levels):
                try:
                    level_int = int(level)
                except (TypeError, ValueError):
                    continue
                if level_int <= 0:
                    continue
                vel_mult = LEVEL_TO_MULT.get(level_int, 1.0)
                # Convert step → bar + beat-within-bar (counted pulses).
                beat_offset_total = step_idx / subdivs
                bar_idx = int(beat_offset_total // bpb)
                beat_in_bar = beat_offset_total - bar_idx * bpb
                swung = apply_swing(beat_in_bar, swing, grid=grid_label)
                t = (bar_offset + bar_idx) * self.bar_duration + swung * beat
                vel = max(1, min(127, int(base_velocity * vel_mult)))
                track.notes.append(NoteEvent(midi_note, t, t + gate, vel))
        return self

    # -- section-level layering ---------------------------------------------

    def add_accent_hit(
        self,
        bar_offset: int,
        track_name: str = "Drums",
        velocity: int = 115,
    ) -> "MidiExporter":
        """Plant a crash + kick + snare stack on the downbeat at ``bar_offset``.

        Use this to make a section entry (verse/chorus/bridge) really hit —
        typically alongside ``fill_at: end`` on the previous section.
        """
        track = self._track_for(track_name, is_drum=True, channel=9)
        t = bar_offset * self.bar_duration
        beat = self.beat_duration
        track.notes.append(NoteEvent(GM_DRUMS["crash"], t, t + beat, velocity))
        track.notes.append(NoteEvent(GM_DRUMS["kick"],  t, t + beat * 0.25, velocity))
        track.notes.append(NoteEvent(GM_DRUMS["snare"], t, t + beat * 0.25,
                                     max(1, min(127, velocity - 5))))
        return self

    def add_lead_line(
        self,
        key: str = "C",
        progression: Optional[list[str]] = None,
        bars: int = 4,
        octave: int = 4,
        pattern: str = "clinton_synth",
        velocity: int = 85,
        scale_name: str = "major",
        track_name: str = "Lead",
        program: int = 81,  # GM Lead 2 (sawtooth) — classic Moog-style lead
        bar_offset: int = 0,
        density: float = 1.0,
        seed: Optional[int] = None,
        swing: float = 0.0,
        follow_source: Optional[str] = None,
        follow_mode: str = "independent",
    ) -> "MidiExporter":
        """Add a lead-instrument line (guitar/synth) playing a stylized riff.

        Patterns (used when ``follow_mode == "independent"``):
          - ``clinton_synth`` — bubbly syncopated 16ths, octave jumps + b7
            (George Clinton / P-Funk synth lead vibe).
          - ``van_halen_riff`` — palm-muted 8ths on power-chord pitches +
            bend-like chromatic lift at the end of every 2 bars.

        Counter-melody modes (require ``follow_source``, the name of an
        existing track to read — typically ``"Melody"``):
          - ``parallel_third`` / ``parallel_sixth``: emit a harmony note
            a scale-step third / sixth above each source note.
          - ``contrary_motion``: when source ascends, the lead descends
            (mirror around source's first-note pitch).
          - ``call_response``: only play during source's rests
            (gaps > 0.5 beats). Emits chord-tone hits in those gaps.

        When ``follow_source`` is set, the pattern dispatch is bypassed
        and the lead becomes a deliberate counter-line responding to
        the source.

        The independent line follows the chord progression, emphasizing
        chord tones on strong beats. Default GM program is Synth Lead;
        set ``program`` to 29/30 for distorted guitar.
        """
        if progression is None:
            progression = ["I", "V", "vi", "IV"]

        root_midi = note_name_to_midi(key, octave)
        track = self._track_for(track_name, program=program)
        beat = self.pulse_unit

        # Counter-melody mode short-circuits the pattern dispatch. The
        # follower reads ``follow_source`` and emits a responsive line
        # rather than its own riff.
        if follow_source and follow_mode and follow_mode != "independent":
            self._emit_follow_line(
                target=track, source_name=follow_source, mode=follow_mode,
                key=key, scale_name=scale_name,
                progression=progression, bars=bars, bar_offset=bar_offset,
                octave=octave, velocity=velocity,
            )
            return self

        rng = np.random.default_rng(seed)

        # Event-driven task list — see add_bass_line for the same pattern.
        import math
        _events = expand_progression_plan(progression, bars)
        _loop_tasks: list[tuple[float, str, float]] = []
        for _event in _events:
            _num_loops = max(1, math.ceil(_event.duration_bars - 1e-9))
            _seg_end = (bar_offset + _event.end_bar) * self.bar_duration
            for _li in range(_num_loops):
                _bar_start = (bar_offset + _event.start_bar + _li) * self.bar_duration
                _loop_tasks.append((_bar_start, _event.symbol, _seg_end))

        for bar_idx, (bar_start, symbol, _seg_end_time) in enumerate(_loop_tasks):
            chord_off, quality = roman_to_semitone_offset(symbol, scale_name)
            root = root_midi + chord_off
            fifth = root + 7
            octave_up = root + 12
            seventh = root + (10 if quality in ("min", "dim", "min7", "7") else 11)
            third = root + (3 if quality in ("min", "dim", "min7") else 4)
            _notes_before = len(track.notes)

            if pattern == "clinton_synth":
                # Leaner P-Funk bubble: starts off-beat, rests on the downbeats,
                # octave pops on "and of 2" and "and of 4". Think Bernie
                # Worrell — the synth leaves space for the groove.
                hits = [
                    (0.50, root,      velocity,       0.18),  # "and of 1" pickup
                    (1.00, root,      velocity - 12,  0.12),  # quick ghost
                    (1.50, octave_up, velocity - 3,   0.22),  # octave pop "and of 2"
                    (2.50, seventh,   velocity - 5,   0.22),  # b7 color "and of 3"
                    (3.00, fifth,     velocity - 8,   0.15),
                    (3.50, octave_up, velocity,       0.22),  # big pop "and of 4"
                ]
                grid = "16th"
            elif pattern == "van_halen_riff":
                # Power-chord palm-muted 8ths with bend-lift on last beat
                hits = [
                    (i * 0.5, root, velocity - (0 if i % 2 == 0 else 8), 0.18)
                    for i in range(6)
                ]
                # 8th-note "hammer" at the end (3.5 + 3.75)
                hits += [
                    (3.00, fifth, velocity - 4, 0.15),
                    (3.5,  root + (14 if bar_idx % 2 == 1 else 12),
                     velocity - 2, 0.18),
                    (3.75, root + 12, velocity, 0.2),
                ]
                grid = "8th"
            else:
                hits = [(0.0, root, velocity, 1.0)]
                grid = "8th"

            for i, (beat_off, pitch, vel, gate) in enumerate(hits):
                if i > 0 and rng.random() > density:
                    continue
                swung = apply_swing(beat_off, swing, grid=grid)
                start = bar_start + swung * beat
                track.notes.append(NoteEvent(
                    pitch, start, start + beat * gate,
                    max(1, min(127, int(vel)))
                ))

            # Truncate notes that crossed the chord-segment boundary.
            _seg_end = _seg_end_time
            if track.notes[_notes_before:]:
                _trimmed: list[NoteEvent] = []
                for n in track.notes[_notes_before:]:
                    if n.start >= _seg_end - 1e-9:
                        continue
                    if n.end > _seg_end:
                        n = NoteEvent(n.pitch, n.start, _seg_end, n.velocity)
                    _trimmed.append(n)
                track.notes[_notes_before:] = _trimmed
        return self

    def add_theme(
        self,
        theme_name: str,
        key: str = "C",
        scale_name: str = "major",
        bars: int = 4,
        octave: int = 5,
        bar_offset: int = 0,
        velocity: int = 90,
        track_name: str = "Theme",
        program: int = 0,
        swing: float = 0.0,
    ) -> "MidiExporter":
        """Emit a registered theme melody (from ``THEMES``).

        The theme is defined as scale degrees, so the same melody renders in
        any key/mode. The phrase repeats to fill ``bars``. The phrase length
        is inferred from the theme data (last note's start + duration).

        Args:
            theme_name: Key into ``THEMES`` (e.g. "hit_the_sack").
            key / scale_name: Where to anchor scale degree 1.
            bars: Total bars to fill (phrase repeats).
            octave: Octave for scale degree 1 (the tonic).
            bar_offset: Section placement.
            velocity: Base MIDI velocity.
            track_name: MIDI track label (default "Theme" — distinct from "Melody").
            program: GM program for the theme track.
            swing: 8th-note swing applied within the phrase.
        """
        if theme_name not in THEMES:
            raise ValueError(f"Unknown theme '{theme_name}'. Choose from: {list(THEMES)}")
        events = THEMES[theme_name]
        if not events:
            return self

        # Phrase length in beats (last event's end)
        bpb = self.beats_per_bar
        phrase_beats = max(beat_off + dur for beat_off, _, dur in events)
        phrase_bars = max(1, int(round(phrase_beats / bpb)))

        scale_ints = SCALES.get(scale_name, SCALES["major"])
        # Map scale degree (1-indexed) to semitone offset from tonic.
        # Wraps for degrees > scale length: degree 8 = tonic + octave, etc.
        def scale_degree_to_semis(deg: int) -> int:
            d = deg - 1  # 0-indexed
            octave_shift = d // len(scale_ints)
            return scale_ints[d % len(scale_ints)] + 12 * octave_shift

        root_midi = note_name_to_midi(key, octave)
        track = self._track_for(track_name, program=program)
        beat = self.pulse_unit

        # Repeat phrase to fill bars
        repetitions = max(1, bars // phrase_bars)
        for rep in range(repetitions):
            rep_offset_beats = rep * phrase_bars * bpb
            for beat_off, degree, dur in events:
                world_beat = rep_offset_beats + beat_off
                if world_beat >= bars * bpb:
                    break
                # Apply swing on the 8th grid within the bar
                bar_idx = int(world_beat // bpb)
                beat_in_bar = world_beat - bar_idx * bpb
                swung_in_bar = apply_swing(beat_in_bar, swing, grid="8th")
                t = (bar_offset + bar_idx) * self.bar_duration + swung_in_bar * beat
                pitch = root_midi + scale_degree_to_semis(degree)
                track.notes.append(NoteEvent(
                    pitch, t, t + dur * beat * 0.95,
                    max(1, min(127, velocity))
                ))
        return self

    def add_drum_fill(
        self,
        bar_offset: int,
        length_bars: float = 1.0,
        intensity: float = 1.0,
        track_name: str = "Drums",
        velocity: int = 95,
        style: str = "simple",
    ) -> "MidiExporter":
        """Lay a drum fill on top of the drum track.

        Styles:
          - ``simple`` (default): 1-2 snare pickups + crash on next downbeat.
            Open and clean — lets the section transition breathe.
          - ``tom_roll``: descending tom roll (high→mid→low) in 16th notes
            with a crescendo + crash. Busier, for big energy hits.

        Args:
            bar_offset: Bar position of the START of the fill.
            length_bars: 0.5 = half-bar pickup (most natural), 1.0 = full bar.
            intensity: Velocity scale (0-1.5). 1.0 = normal, 1.2 = hot.
            track_name: Merge fill into this existing drum track.
            velocity: Base velocity before intensity scaling.
            style: ``simple`` or ``tom_roll``.
        """
        track = self._track_for(track_name, is_drum=True, channel=9)
        beat = self.beat_duration
        start_t = bar_offset * self.bar_duration
        fill_dur = length_bars * self.bar_duration

        if style == "tom_roll":
            sixteenth = beat / 4
            roll = ["tom_high", "tom_mid", "tom_low", "snare"]
            n_hits = int(fill_dur / sixteenth)
            for i in range(n_hits):
                drum = roll[i % len(roll)]
                t = start_t + i * sixteenth
                ramp = 0.7 + 0.3 * (i / max(1, n_hits - 1))
                vel = int(velocity * intensity * ramp)
                track.notes.append(NoteEvent(
                    GM_DRUMS.get(drum, 38), t, t + sixteenth, max(1, min(127, vel))
                ))
        else:
            # Simple: 1 snare hit at the midpoint of the fill, + accented
            # snare just before the next section (the "and" of the last beat).
            snare_vel = int(velocity * intensity * 0.9)
            # Single snare at the midpoint of the fill region
            mid_t = start_t + fill_dur * 0.5
            track.notes.append(NoteEvent(
                GM_DRUMS["snare"], mid_t, mid_t + beat * 0.25,
                max(1, min(127, snare_vel))
            ))
            # One more snare just before the crash (a half-beat pickup)
            pickup_t = start_t + fill_dur - beat * 0.5
            track.notes.append(NoteEvent(
                GM_DRUMS["snare"], pickup_t, pickup_t + beat * 0.25,
                max(1, min(127, snare_vel + 5))
            ))

        # Crash on the downbeat of the next bar
        crash_t = start_t + fill_dur
        crash_vel = int(velocity * intensity * 1.05)
        track.notes.append(NoteEvent(
            GM_DRUMS["crash"], crash_t, crash_t + beat,
            max(1, min(127, crash_vel))
        ))
        return self

    def _emit_follow_line(
        self,
        *,
        target: "Track",
        source_name: str,
        mode: str,
        key: str,
        scale_name: str,
        progression: Optional[list[str]],
        bars: int,
        bar_offset: int,
        octave: int,
        velocity: int,
    ) -> None:
        """Emit a counter-line onto ``target`` that responds to the
        notes of an existing source track. Used by :meth:`add_lead_line`
        when ``follow_mode`` is something other than ``"independent"``.

        ``mode``:
          - ``parallel_third`` / ``parallel_sixth``: scale-step third
            (or sixth) above each source note.
          - ``contrary_motion``: when source rises, target falls; when
            source falls, target rises. Mirror around the source's
            first-note pitch.
          - ``call_response``: emit chord-tone hits only during
            source's rests (gaps > 0.5 beats long).

        Bails silently when the source track is missing or empty —
        keeps the run clean if the user enables follow_mode before
        the source track exists.
        """
        source: Optional[Track] = next(
            (t for t in self.tracks if t.name == source_name), None,
        )
        if source is None or not source.notes:
            return

        root_midi = note_name_to_midi(key, octave)
        scale_ints = SCALES.get(scale_name, SCALES["major"])
        scale_pitches = sorted({
            root_midi + iv + 12 * o
            for iv in scale_ints
            for o in range(-1, 3)
        })

        def _scale_step_above(p: int, steps: int) -> int:
            """Return the in-scale pitch ``steps`` scale-degrees above
            ``p``. Falls back to chromatic shift if ``p`` isn't in the
            scale."""
            nearest = min(scale_pitches, key=lambda q: abs(q - p))
            idx = scale_pitches.index(nearest)
            idx = min(len(scale_pitches) - 1, max(0, idx + steps))
            return scale_pitches[idx]

        sorted_src = sorted(source.notes, key=lambda n: n.start)

        if mode == "parallel_third":
            for n in sorted_src:
                target.notes.append(NoteEvent(
                    pitch=_scale_step_above(n.pitch, 2),
                    start=n.start, end=n.end,
                    velocity=max(1, min(127, int(velocity * 0.85))),
                ))
            return

        if mode == "parallel_sixth":
            for n in sorted_src:
                target.notes.append(NoteEvent(
                    pitch=_scale_step_above(n.pitch, 5),
                    start=n.start, end=n.end,
                    velocity=max(1, min(127, int(velocity * 0.85))),
                ))
            return

        if mode == "contrary_motion":
            if not sorted_src:
                return
            mirror = sorted_src[0].pitch
            for n in sorted_src:
                # Reflect around the first source pitch: new = mirror - (n - mirror)
                target_pitch = mirror - (n.pitch - mirror)
                # Snap to nearest scale tone so it stays in key.
                target.notes.append(NoteEvent(
                    pitch=min(scale_pitches, key=lambda p: abs(p - target_pitch)),
                    start=n.start, end=n.end,
                    velocity=max(1, min(127, int(velocity * 0.85))),
                ))
            return

        if mode == "call_response":
            # Build the list of "rest windows" — gaps between
            # consecutive source notes longer than 0.5 beats.
            if progression:
                events = expand_progression_plan(progression, bars)
            else:
                events = []
            beat = self.pulse_unit
            min_gap = 0.5 * beat
            base_t = bar_offset * self.bar_duration
            end_t = base_t + bars * self.bar_duration
            gaps: list[tuple[float, float]] = []
            prev_end = base_t
            for n in sorted_src:
                if n.start - prev_end > min_gap:
                    gaps.append((prev_end, n.start))
                prev_end = max(prev_end, n.end)
            if end_t - prev_end > min_gap:
                gaps.append((prev_end, end_t))

            for gap_start, gap_end in gaps:
                # Pick the chord active at gap_start; emit a chord-tone
                # note covering most of the gap (leaves room for the
                # next source note's onset).
                bar_pos = gap_start / self.bar_duration
                symbol = chord_at_position(events, bar_pos) or "I"
                chord_off, quality = roman_to_semitone_offset(
                    symbol, scale_name,
                )
                chord_root = root_midi + chord_off
                # Use the chord's 3rd as a sweet-spot pitch (lead-line
                # ear-friendly default).
                third = 4 if quality not in ("min", "dim", "min7") else 3
                pitch = chord_root + third
                target.notes.append(NoteEvent(
                    pitch=pitch, start=gap_start,
                    end=min(gap_start + (gap_end - gap_start) * 0.85, gap_end),
                    velocity=max(1, min(127, int(velocity * 0.85))),
                ))
            return

    def add_harmony(
        self,
        source_track: str = "Melody",
        intervals_steps: Optional[list[int]] = None,
        key: str = "C",
        scale_name: str = "major",
        bar_start: Optional[int] = None,
        bar_end: Optional[int] = None,
        velocity_scale: float = 0.72,
        program: Optional[int] = None,
        style: str = "follow",
        progression: Optional[list[str]] = None,
        harmony_rule: Optional[str] = "voice_leading_smooth",
        voices: Optional[int] = None,
    ) -> "MidiExporter":
        """Layer parallel CHORD-TONE harmony lines on top of an existing melody.

        Each harmony voice stacks the next chord tone(s) above each melody
        note — this keeps the harmony *in chord* even when the chord contains
        non-diatonic notes (e.g. V's G# in A minor). Using scale-step stacking
        instead would produce half-step clashes on those chord tones.

        ``style``:
          - ``follow``: every melody note gets harmonized.
          - ``accents``: only melody notes on a strong beat (1 or 3 of the
            bar) get harmonized — harmonies punctuate instead of double.
          - ``oohs``: independent of the melody — each harmony holds ONE
            chord tone per bar. Requires ``progression``.

        Band-style presets (override ``intervals_steps``):
          - ``abba``:    [1, 2] on accents — tight trio stack on strong beats
          - ``queen``:   [2, 4] on follow — wide stacked 2-voice, every note
          - ``boston``:  [1, 2, 3] on follow — 4-part close stack through octave
          - ``journey``: [1] on follow — simple 2-part duet (+3rd)
          - ``elton``:   [-1] on follow — harmony BELOW (low backing voice)
          - ``chicago``: [1, 2] on follow — close-voiced horn-style every note

        Args:
            intervals_steps: Chord-tone indices relative to melody's nearest
                chord tone. Positive = above, negative = below. ``[1]`` =
                next chord tone up (≈3rd above for a triad).
        """
        _HARMONY_PRESETS = {
            "abba":    ([1, 2],    "accents"),
            "queen":   ([2, 4],    "follow"),
            "boston":  ([1, 2, 3], "follow"),
            "journey": ([1],       "follow"),
            "elton":   ([-1],      "follow"),
            "chicago": ([1, 2],    "follow"),
        }
        if style in _HARMONY_PRESETS:
            intervals_steps, style = _HARMONY_PRESETS[style]
        elif intervals_steps is None:
            intervals_steps = [1]

        # Voices control — truncate or pad the resolved interval stack
        # to match the caller's 1/2/3 selection. Lets the new "harmony"
        # extras track type dial voice count independently of the
        # preset's natural size (queen=2, boston=3, journey=1, …).
        if voices is not None and voices >= 1 and intervals_steps:
            if voices <= len(intervals_steps):
                intervals_steps = list(intervals_steps[:voices])
            else:
                # Pad upward from the top voice — most preset shapes
                # extend up (queen 2,4 → 2,4,5; journey 1 → 1,2,3).
                top = max(intervals_steps)
                extras = [top + i for i in range(1, voices - len(intervals_steps) + 1)]
                intervals_steps = list(intervals_steps) + extras

        if style == "oohs":
            return self._add_harmony_oohs(
                intervals_steps=intervals_steps,
                key=key, scale_name=scale_name,
                bar_start=bar_start, bar_end=bar_end,
                program=program, progression=progression,
            )

        src = next((t for t in self.tracks if t.name == source_track), None)
        if src is None or not src.notes:
            return self

        bar_start_t = (bar_start * self.bar_duration) if bar_start is not None else None
        bar_end_t = (bar_end * self.bar_duration) if bar_end is not None else None
        src_program = src.program if program is None else program
        beat = self.beat_duration
        root_midi = note_name_to_midi(key, 4)  # vocal octave for building chord tones

        # Cover all source-note positions, plus the explicit bar_end if set.
        # Reusing the same expand/lookup helpers as add_melody / add_bass_line
        # so progressions with sub-bar pacing (``list[tuple[str, float]]``)
        # work here too — pre-pacing this method indexed ``progression[idx]``
        # directly, which silently returned tuples and made every harmony
        # render no-op for paced sessions.
        span_bars = max(
            int(max(n.end for n in src.notes) / self.bar_duration) + 1,
            (bar_end or 0) + 1,
            1,
        )
        events = expand_progression_plan(progression or ["I"], span_bars)

        def _chord_tones_at(n_start: float) -> list[int]:
            """Absolute pitches of the chord playing at time n_start, across
            several octaves so we can find one close to any melody pitch."""
            bar_pos = n_start / self.bar_duration
            symbol = chord_at_position(events, bar_pos) or "I"
            chord_off, quality = roman_to_semitone_offset(symbol, scale_name)
            chord_root = root_midi + chord_off
            tones = voice_chord(chord_root, quality, "triad")
            # Expand across ±2 octaves for nearest-neighbor lookup
            extended = sorted({t + 12 * o for t in tones for o in range(-2, 3)})
            return extended

        def _chord_root_quality_at(n_start: float) -> tuple[int, str]:
            """Root MIDI pitch + chord-quality string ('maj' / 'min' /
            'maj7' / 'dom7' / 'min7' / 'dim') at time n_start. Used by
            the shell-voicing harmony rule to pick the 3rd and 7th."""
            bar_pos = n_start / self.bar_duration
            symbol = chord_at_position(events, bar_pos) or "I"
            chord_off, quality = roman_to_semitone_offset(symbol, scale_name)
            return root_midi + chord_off, quality

        # Diatonic scale pitches across a ~3-octave window for the
        # parallel_thirds rule (lookup is by nearest absolute pitch).
        scale_ints_local = SCALES.get(scale_name, SCALES["major"])
        scale_pitches = sorted({
            root_midi + iv + 12 * o
            for iv in scale_ints_local
            for o in range(-1, 3)
        })

        # Voice-leading smoothing is on by default — Bach-level baseline.
        # When the naive parallel-chord-tone pick would move >2 semitones
        # from the previous harmony pitch, search the chord-tone palette
        # for a closer alternative that preserves the role above/below.
        smooth_vl = (harmony_rule == "voice_leading_smooth")
        contrary = (harmony_rule == "contrary_motion")
        rule_common_tone = (harmony_rule == "common_tone")
        rule_shell = (harmony_rule == "shell_voicing")
        rule_whisper = (harmony_rule == "whisper_voicing")
        rule_parallel_thirds = (harmony_rule == "parallel_thirds")

        def _shell_filter(chord_tones: list[int],
                          chord_root: int, quality: str) -> list[int]:
            """Keep only 3rd and 7th of the chord — the "shell" voicing
            that jazz pianists use for comping. Filters by pitch class so
            it works across octave-spread chord-tone palettes."""
            third = 4 if quality not in ("min", "dim", "min7") else 3
            seventh = 11 if quality == "maj7" else 10
            keep_pcs = {(chord_root + third) % 12, (chord_root + seventh) % 12}
            shell = [p for p in chord_tones if p % 12 in keep_pcs]
            return shell or chord_tones   # fall back if filter empties

        for i, steps in enumerate(intervals_steps):
            harm_name = f"{source_track} Harm {i + 1}"
            harm_track = self._track_for(harm_name, program=src_program)
            prev_harm_pitch: Optional[int] = None
            prev_mel_pitch: Optional[int] = None
            for n in src.notes:
                if bar_start_t is not None and n.start < bar_start_t:
                    continue
                if bar_end_t is not None and n.start >= bar_end_t:
                    continue
                if style == "accents":
                    pulse_pos = (n.start / self.pulse_unit) % self.beats_per_bar
                    is_strong = any(
                        abs(pulse_pos - sp) < 0.25
                        for sp in self._meter["strong_pulses"]
                    )
                    if not is_strong:
                        continue
                chord_tones = _chord_tones_at(n.start)

                # ----- parallel_thirds: lock to a scale-third above ----
                if rule_parallel_thirds:
                    # Find the scale-step a third above the melody pitch.
                    nearest_scale = min(scale_pitches,
                                        key=lambda p: abs(p - n.pitch))
                    s_idx = scale_pitches.index(nearest_scale)
                    s_idx = min(len(scale_pitches) - 1, s_idx + 2)
                    harm_pitch = scale_pitches[s_idx]
                else:
                    # ----- shell_voicing: pre-filter chord tones -------
                    if rule_shell:
                        chord_root, _ct_quality = _chord_root_quality_at(n.start)
                        chord_tones = _shell_filter(
                            chord_tones, chord_root, _ct_quality,
                        )

                    # Nearest chord tone to the melody note
                    nearest = min(chord_tones, key=lambda p: abs(p - n.pitch))
                    idx = chord_tones.index(nearest)
                    harm_idx = idx + steps  # steps can be negative for below-melody
                    harm_idx = max(0, min(len(chord_tones) - 1, harm_idx))
                    harm_pitch = chord_tones[harm_idx]

                    # ----- common_tone: hold over from prior when avail -
                    if rule_common_tone and prev_harm_pitch is not None:
                        if prev_harm_pitch in chord_tones:
                            harm_pitch = prev_harm_pitch

                    # ----- whisper_voicing: push above melody octave ---
                    if rule_whisper:
                        # Stay strictly above the melody by at least an
                        # octave so it sits as a glow rather than
                        # collision with the lead voice.
                        while harm_pitch <= n.pitch + 11:
                            harm_pitch += 12

                # ----- harmony_rule smoothing pass --------------------
                if smooth_vl and prev_harm_pitch is not None:
                    leap = abs(harm_pitch - prev_harm_pitch)
                    if leap > 2:
                        # Prefer chord tones within ±2 semitones of the
                        # prior harmony note AND on the correct side
                        # (above/below the melody) for the requested
                        # ``steps``. If no candidate satisfies both, fall
                        # back to the closest chord tone to the prior
                        # harmony — getting a smooth voice always wins
                        # over preserving the above/below role.
                        wanted_above = steps > 0
                        wanted_below = steps < 0
                        on_side = []
                        nearby = []
                        for ct in chord_tones:
                            if abs(ct - prev_harm_pitch) > 4:
                                continue
                            nearby.append(ct)
                            if wanted_above and ct <= n.pitch:
                                continue
                            if wanted_below and ct >= n.pitch:
                                continue
                            on_side.append(ct)
                        pool = on_side or nearby
                        if pool:
                            harm_pitch = min(
                                pool,
                                key=lambda p: abs(p - prev_harm_pitch),
                            )
                elif contrary and prev_harm_pitch is not None and prev_mel_pitch is not None:
                    # Choose the chord tone whose motion direction is the
                    # OPPOSITE of the melody's. If melody ascends, harmony
                    # picks a lower chord tone (still adjacent to prior),
                    # and vice versa.
                    mel_dir = (n.pitch - prev_mel_pitch)
                    if mel_dir != 0:
                        wanted_dir = -1 if mel_dir > 0 else 1
                        candidates = [
                            ct for ct in chord_tones
                            if abs(ct - prev_harm_pitch) <= 4
                            and (ct - prev_harm_pitch) * wanted_dir >= 0
                        ]
                        if candidates:
                            harm_pitch = min(
                                candidates,
                                key=lambda p: abs(p - prev_harm_pitch),
                            )

                harm_vel = max(1, min(127, int(n.velocity * velocity_scale)))
                if rule_whisper:
                    # Whisper sits as a glow under the melody — reduce
                    # velocity further so it never competes for focus.
                    harm_vel = max(1, int(harm_vel * 0.5))
                harm_track.notes.append(NoteEvent(
                    pitch=harm_pitch, start=n.start, end=n.end, velocity=harm_vel,
                ))
                prev_harm_pitch = harm_pitch
                prev_mel_pitch = n.pitch
        return self

    def _add_harmony_oohs(
        self,
        intervals_steps: list[int],
        key: str,
        scale_name: str,
        bar_start: Optional[int],
        bar_end: Optional[int],
        program: Optional[int],
        progression: Optional[list[str]],
    ) -> "MidiExporter":
        """Sustained chord-tone backing — one held note per harmony voice per bar."""
        if bar_start is None or bar_end is None or progression is None:
            return self

        root_midi = note_name_to_midi(key, 4)  # vocal octave
        fixed_vel = 72

        for i, steps in enumerate(intervals_steps):
            harm_name = f"Oohs {i + 1}"
            harm_track = self._track_for(
                harm_name, program=(program if program is not None else 52),  # Choir Aahs
            )
            for bar in range(bar_start, bar_end):
                symbol = progression[(bar - bar_start) % len(progression)]
                chord_off, quality = roman_to_semitone_offset(symbol, scale_name)
                chord_root = root_midi + chord_off
                chord_pitches = voice_chord(chord_root, quality, "triad")
                # Pick the chord tone corresponding to the harmony interval:
                #   +3rd (steps=2) → voice the chord's 3rd (index 1)
                #   +5th (steps=4) → voice the chord's 5th (index 2)
                idx = min(len(chord_pitches) - 1, 1 if steps == 2 else 2)
                harm_pitch = chord_pitches[idx]
                start = bar * self.bar_duration
                dur = self.bar_duration * 0.95  # tie through the bar
                harm_track.notes.append(NoteEvent(
                    harm_pitch, start, start + dur, fixed_vel,
                ))
        return self

    def fade_out(
        self,
        from_bar: int,
        to_bar: int,
        min_scale: float = 0.15,
        track_filter: Optional[list[str]] = None,
    ) -> "MidiExporter":
        """Linearly taper note velocities across a bar range.

        Args:
            from_bar: Bar where the fade starts (velocity still 1.0).
            to_bar: Bar where the fade ends (velocity reaches ``min_scale``).
            min_scale: Floor for velocity scaling (0 would mute entirely).
            track_filter: If given, only these track names are faded; else all.
        """
        start = from_bar * self.bar_duration
        end = to_bar * self.bar_duration
        span = max(1e-6, end - start)

        for track in self.tracks:
            if track_filter is not None and track.name not in track_filter:
                continue
            for n in track.notes:
                if n.start < start:
                    continue
                if n.start >= end:
                    n.velocity = max(1, int(n.velocity * min_scale))
                    continue
                frac = (n.start - start) / span
                scale = 1.0 + (min_scale - 1.0) * frac
                n.velocity = max(1, int(n.velocity * scale))
        return self

    def add_notes(
        self,
        notes: list[NoteEvent],
        track_name: str = "Custom",
        program: int = 0,
        is_drum: bool = False,
    ) -> "MidiExporter":
        """Add arbitrary note events as a track."""
        track = Track(name=track_name, program=program, is_drum=is_drum)
        track.notes = list(notes)
        self.tracks.append(track)
        return self

    # -- articulation (bends / vibrato / legato) ----------------------------
    #
    # Guitar lead playing *is* articulation — bends, slides, vibrato and
    # legato. These primitives store pitch motion in semitones on the
    # Track; ``build()`` converts to pretty_midi pitch-bend events. A
    # render spike confirmed FluidSynth honours pretty_midi ``pitch_bends``
    # through the per-track stem path, so no renderer-level work is needed.

    def _ensure_bend_range(self, track: Track, needed_st: float) -> None:
        """Widen the track's pitch-bend range if a bend exceeds it.

        FluidSynth defaults to +/-2 semitones (one whole tone) — enough for
        the common half/full bend. Bigger bends raise the range, emitted as
        an RPN sequence at build time.
        """
        need = int(math.ceil(abs(needed_st)))
        if need > int(round(track.bend_range_st)):
            track.bend_range_st = float(need)

    def _emit_bend(
        self,
        track: Track,
        start: float,
        dur: float,
        from_st: float,
        to_st: float,
        curve: str = "ease_out",
        steps: int = 10,
    ) -> None:
        """Append a pitch-bend ramp from ``from_st`` to ``to_st`` semitones.

        ``ease_out`` (default) rises fast then settles, like a real finger
        bend; ``ease_in`` is the inverse; ``linear`` is a straight ramp.
        Pre-bend (bent before the pick) vs bend-and-release is just the
        caller's choice of ``from``/``to``.
        """
        self._ensure_bend_range(track, max(abs(from_st), abs(to_st)))
        dur = max(dur, 1e-3)
        for i in range(steps + 1):
            p = i / steps
            if curve == "ease_out":
                shaped = 1.0 - (1.0 - p) ** 2
            elif curve == "ease_in":
                shaped = p * p
            else:
                shaped = p
            val = from_st + (to_st - from_st) * shaped
            track.bends.append(BendEvent(time=start + p * dur, semitones=val))

    def _emit_vibrato(
        self,
        track: Track,
        start: float,
        dur: float,
        depth_st: float = 0.3,
        rate_hz: float = 5.5,
        delay: float = 0.08,
        steps_per_cycle: int = 8,
    ) -> None:
        """Append a sinusoidal pitch-bend LFO (vibrato) after a short delay."""
        self._ensure_bend_range(track, depth_st)
        end = start + max(dur, 1e-3)
        t = start + delay
        if t >= end:
            return
        period = 1.0 / max(rate_hz, 0.1)
        step = max(period / max(steps_per_cycle, 1), 1e-3)
        while t < end:
            phase = (t - start - delay) * rate_hz * 2.0 * math.pi
            track.bends.append(BendEvent(time=t, semitones=depth_st * math.sin(phase)))
            t += step

    def _articulate_melody_note(
        self, track: Track, t: float, dur: float, accent: bool,
        note_pos: float, dur_beats: float, p: dict, rng,
    ) -> None:
        """Add at most one expressive gesture to a just-appended melody note.

        Mutually exclusive per note so the pitch-bend events never collide:
        a scoop INTO a strong note (head), then either a vibrato on a held
        note or a fall OFF a phrase-end note (tail). The wheel resets to 0
        in the inter-note gap so the next note rings true.
        """
        sw = min(0.12, dur * 0.35)        # scoop window (seconds)
        scooped = False
        if accent and rng.random() < p["scoop_prob"]:
            self._emit_bend(track, t, sw, -p["scoop_depth"], 0.0,
                            curve="ease_out", steps=5)
            scooped = True

        is_end = note_pos >= 0.9
        if is_end and dur_beats >= 1.0 and rng.random() < p["fall_prob"]:
            # Fall/doit off the tail, reset in the gap after the note.
            self._emit_bend(track, t + dur * 0.55, dur * 0.45, 0.0,
                            -p["fall_depth"], curve="ease_in", steps=6)
            track.bends.append(BendEvent(time=t + dur + 0.01, semitones=0.0))
        elif dur_beats >= p["vib_min_beats"]:
            start = t + (sw if scooped else 0.0) + 0.05
            length = (t + dur) - start
            if length > 0.1:
                self._emit_vibrato(track, start, length,
                                   depth_st=p["vib_depth"], rate_hz=p["vib_rate"],
                                   delay=0.0)
                track.bends.append(BendEvent(time=t + dur + 0.01, semitones=0.0))
        elif scooped:
            # Plain scoop already ends at 0; nothing more to reset.
            pass

    def add_articulated_note(
        self,
        track_name: str,
        pitch: int,
        start: float,
        dur: float,
        *,
        velocity: int = 90,
        program: int = 0,
        is_drum: bool = False,
        bend: Optional[tuple[float, float]] = None,
        bend_curve: str = "ease_out",
        vibrato: Optional[Union[bool, dict]] = None,
        reset_after: bool = True,
    ) -> Track:
        """Add a note plus optional pitch articulation.

        ``bend`` is a ``(from_st, to_st)`` semitone ramp over the note —
        e.g. ``(0, 1)`` bends up a semitone, ``(2, 0)`` is a pre-bend
        released down a whole tone. ``vibrato=True`` (or a kwargs dict)
        adds a vibrato LFO. After articulation the wheel is reset to 0 at
        the note boundary so the next note rings true. Legato (hammer-on /
        pull-off) needs no flag here — just overlap two notes' times.
        """
        track = self._track_for(track_name, program=program, is_drum=is_drum)
        end = start + max(dur, 1e-3)
        track.notes.append(NoteEvent(pitch=pitch, start=start, end=end, velocity=velocity))
        articulated = False
        if bend is not None:
            self._emit_bend(track, start, dur, bend[0], bend[1], curve=bend_curve)
            articulated = True
        if vibrato:
            opts = vibrato if isinstance(vibrato, dict) else {}
            self._emit_vibrato(track, start, dur, **opts)
            articulated = True
        if articulated and reset_after:
            track.bends.append(BendEvent(time=end, semitones=0.0))
        return track

    def _apply_articulation(
        self, instrument: "pretty_midi.Instrument", track: Track
    ) -> None:
        """Emit a track's bends/CCs onto a built pretty_midi Instrument."""
        range_st = float(int(round(track.bend_range_st))) or 2.0
        # Widen FluidSynth's pitch-bend range via RPN 0 when above the
        # +/-2 semitone default (CC101/100 select RPN, CC6/38 = data).
        if range_st > 2.0:
            for num, val in ((101, 0), (100, 0), (6, int(range_st)), (38, 0)):
                instrument.control_changes.append(
                    pretty_midi.ControlChange(number=num, value=val, time=0.0)
                )
        for cc in track.ccs:
            instrument.control_changes.append(
                pretty_midi.ControlChange(number=cc.number, value=cc.value, time=cc.time)
            )
        for b in track.bends:
            val14 = int(round(b.semitones / range_st * 8192))
            val14 = max(-8192, min(8191, val14))
            instrument.pitch_bends.append(
                pretty_midi.PitchBend(pitch=val14, time=b.time)
            )

    # -- export -------------------------------------------------------------

    def build(self) -> pretty_midi.PrettyMIDI:
        """Build and return a pretty_midi.PrettyMIDI object."""
        pm = pretty_midi.PrettyMIDI(initial_tempo=self.tempo)

        num, den = self.time_signature
        pm.time_signature_changes.append(
            pretty_midi.TimeSignature(num, den, 0.0)
        )

        for track in self.tracks:
            instrument = pretty_midi.Instrument(
                program=track.program,
                is_drum=track.is_drum,
                name=track.name,
            )
            for n in track.notes:
                instrument.notes.append(pretty_midi.Note(
                    velocity=n.velocity,
                    pitch=n.pitch,
                    start=n.start,
                    end=n.end,
                ))
            self._apply_articulation(instrument, track)
            pm.instruments.append(instrument)

        return pm

    def save(self, path: str | Path) -> Path:
        """Write MIDI file to disk.

        Args:
            path: Output .mid file path.

        Returns:
            Resolved Path to the written file.
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        pm = self.build()
        pm.write(str(path))
        print(f"MIDI saved: {path}")
        return path

    def synthesize(self, sample_rate: int = 44100) -> tuple[np.ndarray, int]:
        """Render MIDI to audio using pretty_midi's built-in FluidSynth.

        Returns:
            (audio_array, sample_rate)
        """
        pm = self.build()
        audio = pm.synthesize(fs=sample_rate)
        return audio, sample_rate

    def iter_single_track_pms(self):
        """Yield ``(track_name, PrettyMIDI)`` pairs — one PrettyMIDI per track.

        Each yielded PrettyMIDI contains a single Instrument with the track's
        program/drum/notes preserved, plus the same tempo and time-signature
        metadata as ``build()``. Used by the audio render pipeline to
        synthesize per-track stems.
        """
        num, den = self.time_signature
        for track in self.tracks:
            pm = pretty_midi.PrettyMIDI(initial_tempo=self.tempo)
            pm.time_signature_changes.append(
                pretty_midi.TimeSignature(num, den, 0.0)
            )
            instrument = pretty_midi.Instrument(
                program=track.program,
                is_drum=track.is_drum,
                name=track.name,
            )
            for n in track.notes:
                instrument.notes.append(pretty_midi.Note(
                    velocity=n.velocity,
                    pitch=n.pitch,
                    start=n.start,
                    end=n.end,
                ))
            self._apply_articulation(instrument, track)
            pm.instruments.append(instrument)
            yield track.name, pm

    def total_duration(self) -> float:
        """Total duration in seconds across all tracks."""
        if not self.tracks:
            return 0.0
        return max(n.end for t in self.tracks for n in t.notes) if any(t.notes for t in self.tracks) else 0.0
