"""Christmas styles (tag ``christmas``): background-friendly holiday music.

Six sub-styles, each a full-song preset (``christmas_*_full`` in styles.py):

- ``swing``: big-band crooner swing. Ride cymbal (or brushes), a walking
  upright bass (in two for the first chorus), piano comping, a sax section
  with the tune, muted trumpets and a French horn as soft pads.
- ``trio``: a cozy jazz trio. Piano with the tune over left-hand shells,
  upright bass, brushes, a rubato ending.
- ``orchestral``: warm film orchestra. Strings, French horn, flute and
  clarinet, harp, glockenspiel, sleigh bells. Ends on the strings.
- ``fireside``: acoustic. Nylon guitar fingerpicking, soft piano, cello,
  a light shaker.
- ``choir``: reverent carol. Choir "aah" chorale, quiet pipe organ, strings,
  a plagal "Amen" ending.
- ``pop``: a light pop anthem. Soft kit, bass, piano, acoustic guitar,
  strings, sleigh bells and glockenspiel, a clean guitar lead.

Every song plays a TUNE: a public-domain carol (src/composition/carols.py)
or an original Christmas-feel tune written here from the seed (AABA, with
ii-V turnarounds, secondary dominants, diminished passing chords, IV-iv-I
and suspensions). ``plan_song`` lays the form out (intro on the tune's last
phrase, a soft first pass, a fuller second pass with a countermelody, an
interlude, a final pass that may lift a half step, a tag and a held ending
with a ritardando) as ``compose_song`` sections; each section carries its
chords, its slice of the melody and which instrument has the melody in
``section["info"]``, and the techniques below read it.

Backing tracks (``backing_track`` / ``guide_melody``): the same arrangement
with the tune taken out (or kept very quiet as a guide) for people to sing or
play along: a one-bar count-in on a recorded hi-hat, one verse per pass of
the carol (as many passes as its lyric file has verses, up to four), and no
key change unless asked. src/composition/backing.py turns the plan into the
timing JSON a video renderer reads (bars, chords, sections, lyric lines).

Taste (from the producer's notes): background first, so gentle dynamics and
no harsh transients; no busy fills, no comic gestures, no fall-offs; strong,
held endings; never synthesised percussion (recorded kits, brushes, sleigh
bells and shaker only).
"""

from __future__ import annotations

import zlib
from functools import lru_cache
from typing import Optional

import numpy as np

from src.composition.techniques import TechniqueContext
from src.daw_integration.generic.midi_export import (
    NOTE_NAMES, FLAT_TO_SHARP, NoteEvent, roman_to_semitone_offset,
)

from .builtins import _register
from .carols import Tune, TuneChord, TuneNote, carol, parse_chords
from .fusion import (
    ALL_ROLES, CLOSED_HAT, CRASH, KICK, PEDAL_HAT, RIDE, SNARE, STICK,
    _Clock, _emit, _human,
)
from .funk_fusion import BRUSH_KIT, BRUSH_TRACK

TAG = "christmas"

STYLE_IDS: dict[str, str] = {
    "christmas_swing_full": "swing",
    "christmas_jazz_trio_full": "trio",
    "christmas_orchestral_full": "orchestral",
    "christmas_fireside_full": "fireside",
    "christmas_choir_full": "choir",
    "christmas_pop_full": "pop",
}
SUBSTYLES = tuple(STYLE_IDS.values())
JAZZ = ("swing", "trio")

# Every arrangement variant, in plain English (tools, describe/revise and the
# plan validator read this; a test keeps it in step with the code).
ARRANGEMENT_VARIANTS: dict[str, str] = {
    "sleigh_bells": "Add recorded sleigh bells, gentle: steady in lively tunes, a soft shake every other bar in "
                    "slow ones.",
    "brushes": "Drums with brushes (the recorded brush kit) instead of sticks: swing, trio and pop.",
    "less_busy": "Simpler, calmer parts for background: held chords instead of patterns, bass in two, no "
                 "countermelody, no glockenspiel doubling.",
    "warmer": "Warmer and darker: lower, softer voicings, no glockenspiel or celesta sparkle, rounder melody.",
    "celesta_ending": "End on the celesta (or glockenspiel): a soft rising arpeggio of the final chord over the held "
                      "chord.",
    "strings_ending": "End on a held string chord (the others drop out on the last chord).",
    "key_change": "Lift the last pass up a half step.",
    "no_key_change": "Stay in one key all the way through.",
    "plain_harmony": "Play the carol's chords as written (no jazz reharmonisation).",
    "rich_harmony": "Richer jazz harmony: ii-V approaches, secondary dominants, passing diminished chords, IV-iv-I.",
    "choir_pad": "Add a soft choir 'aah' pad under the last pass and the ending.",
    "backing_track": "A sing-along backing track: the full arrangement with no lead or melody instrument, a one-bar "
                     "count-in on a recorded hi-hat, a clear intro and held ending, one verse of the carol per pass "
                     "and no key change unless asked. Saves a timing JSON (bars, chords, sections, lyric lines).",
    "guide_melody": "A backing track (as backing_track) with the melody kept very quiet as a guide.",
}
# Variants that need instruments beyond the style's band.
ARRANGEMENT_INSTRUMENTS: dict[str, tuple[str, ...]] = {
    "sleigh_bells": ("sleigh_bells",),
    "strings_ending": ("string_section",),
    "celesta_ending": ("celesta",),
    "choir_pad": ("choir",),
}

# A Christmas song is delivered at a background-ready loudness unless the
# request says otherwise (YouTube normalises to about -14 LUFS).
DEFAULT_LUFS = -16.0
# The pop style's lead (a synth_lead track) is a clean electric guitar.
DEFAULT_LEAD_PATCH = "guitar_clean"

# Sub-style defaults: tempo range (BPM), keys to vary between, swing, form.
STYLE_DEFAULTS: dict[str, dict] = {
    "swing":      {"tempo": (118, 150), "keys": ("F", "Bb", "Eb", "G"), "swing": True, "lift": 0.6},
    "trio":       {"tempo": (96, 128), "keys": ("F", "Bb", "Eb", "C", "G"), "swing": True, "lift": 0.3},
    "orchestral": {"tempo": (72, 104), "keys": ("D", "Eb", "F", "G", "C"), "swing": False, "lift": 0.5},
    "fireside":   {"tempo": (76, 100), "keys": ("D", "G", "C", "A", "E"), "swing": False, "lift": 0.0},
    "choir":      {"tempo": (64, 84), "keys": ("D", "Eb", "F", "G"), "swing": False, "lift": 0.3},
    "pop":        {"tempo": (84, 112), "keys": ("C", "D", "E", "F", "G", "A"), "swing": False, "lift": 0.7},
}
# Slow ballad tempos for hymn-like carols in the jazz styles (a jazz waltz).
_BALLAD_TEMPO = {"swing": (88, 104), "trio": (66, 84)}

# Who has the melody, pass by pass (first available instrument wins), and the
# intro's instrument. "piano" in the trio plays the tune over its own shells.
LEADS: dict[str, dict[str, tuple[str, ...]]] = {
    "swing": {"intro": ("piano",), "pass1": ("sax_tenor", "sax_alto", "muted_trumpet", "piano"),
              "pass2": ("piano", "sax_alto", "sax_tenor"), "var": ("sax_alto", "piano", "sax_tenor"),
              "final": ("sax_alto", "sax_tenor", "muted_trumpet", "piano")},
    "trio": {"intro": ("piano",), "pass1": ("piano",), "pass2": ("piano",), "var": ("piano",), "final": ("piano",)},
    "orchestral": {"intro": ("flute", "clarinet", "oboe", "string_section"),
                   "pass1": ("flute", "clarinet", "oboe", "string_section"),
                   "pass2": ("string_section", "flute", "french_horn"),
                   "var": ("clarinet", "oboe", "flute", "string_section"),
                   "final": ("string_section", "flute")},
    "fireside": {"intro": ("nylon_guitar", "acoustic_guitar", "piano"), "pass1": ("piano", "nylon_guitar"),
                 "pass2": ("cello", "piano"), "var": ("nylon_guitar", "acoustic_guitar", "piano"),
                 "final": ("piano", "cello")},
    "choir": {"intro": ("organ_church", "string_section"), "pass1": ("organ_church", "string_section", "choir"),
              "pass2": ("choir", "string_section"), "var": ("string_section", "organ_church", "choir"),
              "final": ("choir", "string_section")},
    "pop": {"intro": ("piano",), "pass1": ("piano", "glockenspiel"), "pass2": ("synth_lead", "piano"),
            "var": ("synth_lead", "piano"), "final": ("synth_lead", "piano")},
}

# Instruments that, when not leading, play a countermelody in fuller passes.
_COUNTER = {
    "swing": ("french_horn",),
    "trio": (),
    "orchestral": ("french_horn", "clarinet", "cello"),
    "fireside": ("cello",),
    "choir": (),
    "pop": ("string_section",),
}

# Instrument registers (MIDI lo, hi) for the melody.
_RANGE = {
    "flute": (67, 93), "clarinet": (55, 84), "oboe": (62, 86), "sax_tenor": (52, 76), "sax_alto": (61, 84),
    "muted_trumpet": (58, 82), "string_section": (67, 91), "cello": (48, 72), "piano": (62, 86),
    "glockenspiel": (79, 103), "celesta": (72, 96), "choir": (62, 79), "organ_church": (62, 84),
    "synth_lead": (60, 84), "nylon_guitar": (55, 79), "acoustic_guitar": (55, 79), "french_horn": (53, 77),
    "harp": (60, 91), "violin": (67, 91), "trumpet": (58, 82),
}


# One line per style for menus, tools and the plan guide.
STYLE_INFO: dict[str, str] = {
    "christmas_swing_full": "Big-band crooner swing: ride cymbal or brushes, walking upright bass, piano, a sax "
                            "section with the tune, muted trumpets and French horn as soft pads.",
    "christmas_jazz_trio_full": "Cozy jazz trio: piano (the tune over left-hand shells), upright bass, brushes; "
                                "a rubato, held ending.",
    "christmas_orchestral_full": "Warm film orchestra: strings, French horn, flute and clarinet, harp, "
                                 "glockenspiel, sleigh bells. Ends on the strings.",
    "christmas_fireside_full": "Acoustic fireside: nylon guitar fingerpicking, soft piano, cello, a light shaker.",
    "christmas_choir_full": "Reverent carol: choir 'aah' chorale, quiet pipe organ, strings, an 'Amen' ending.",
    "christmas_pop_full": "Light pop anthem: soft kit, bass, piano, acoustic guitar, strings, sleigh bells, "
                          "glockenspiel, a clean guitar lead.",
}

# Words that pick a sub-style once a request is about Christmas.
_STYLE_WORDS: tuple[tuple[str, str], ...] = (
    (r"big[\s-]?band|swing|crooner|sinatra|rat pack", "christmas_swing_full"),
    (r"\btrio\b|jazz|lounge|cocktail", "christmas_jazz_trio_full"),
    (r"choir|chorale|hymn|church|organ|reverent|carol(?:l?ers| singers)|cathedral", "christmas_choir_full"),
    (r"orchestra|orchestral|film|cinematic|symphon|strings|harp|nutcracker", "christmas_orchestral_full"),
    (r"acoustic|fireside|fire\s*place|guitar|folk|cabin", "christmas_fireside_full"),
    (r"\bpop\b|rock|anthem|band", "christmas_pop_full"),
)
_CHRISTMAS_WORDS = r"christmas|xmas|x-mas|holiday|carol|noel|yule|festive|santa|sleigh|jingle|nativity|advent"


def style_word(text: str) -> Optional[str]:
    """The Christmas style a style word in ``text`` names ("orchestral",
    "big band", "choir"), or None."""
    import re
    low = (text or "").lower()
    for pattern, genre in _STYLE_WORDS:
        if re.search(pattern, low):
            return genre
    return None


def christmas_genre(text: str) -> Optional[str]:
    """The Christmas style a request asks for, or None when it isn't about
    Christmas. Mentioning a carol by name counts."""
    import re
    low = (text or "").lower()
    if not (re.search(_CHRISTMAS_WORDS, low) or tune_from_text(low)):
        return None
    return style_word(low) or "christmas_orchestral_full"


def tune_from_text(text: str) -> Optional[str]:
    """A carol named in ``text`` ("Silent Night", "greensleeves"), or
    "original" when an original tune is asked for."""
    import re
    from .carols import CAROLS, carol_catalog
    low = (text or "").lower()
    aliases = {"greensleeves": "what_child_is_this", "shchedryk": "carol_of_the_bells",
               "first nowell": "the_first_noel", "first noel": "the_first_noel",
               "deck the hall": "deck_the_halls",
               "angels we have heard": "angels_we_have_heard", "joy to the world": "joy_to_the_world"}
    for words, tid in aliases.items():
        if words in low:
            return tid
    for tid, info in carol_catalog().items():
        title = info["title"].lower().split(" (")[0]
        if title in low or tid.replace("_", " ") in low:
            return tid
    if re.search(r"\boriginal\b|\bnew (tune|melody|song)\b|own (tune|melody)", low):
        return "original"
    return None


def carol_title(tune_id: str) -> str:
    t = carol(tune_id)
    return t.title if t else tune_id


def denied_song(text: str) -> Optional[str]:
    """A copyrighted Christmas song named in ``text`` (from the denylist)."""
    from .carols import DENYLIST
    low = (text or "").lower()
    return next((d for d in DENYLIST if d in low), None)


def substyle(genre: str) -> str:
    return STYLE_IDS.get(genre, "orchestral")


def variants(ctx_or_text) -> set[str]:
    text = getattr(ctx_or_text, "arrangement", ctx_or_text) or ""
    return {a.strip() for a in str(text).replace("+", ",").split(",") if a.strip()}


_FLAT_NAMES = ("C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B")
_MINOR_NAMES = ("C", "C#", "D", "Eb", "E", "F", "F#", "G", "G#", "A", "Bb", "B")


def _key_name(pc: int) -> str:
    return _FLAT_NAMES[pc % 12]


def _tonic_pc(key: str) -> int:
    try:
        return NOTE_NAMES.index(FLAT_TO_SHARP.get(key, key)) % 12
    except ValueError:
        return 0


# ---------------------------------------------------------------------------
# Harmony helpers
# ---------------------------------------------------------------------------

_TRIAD = {"maj": (0, 4, 7), "min": (0, 3, 7), "7": (0, 4, 7, 10), "maj7": (0, 4, 7, 11), "min7": (0, 3, 7, 10),
          "dim": (0, 3, 6, 9), "aug": (0, 4, 8), "sus4": (0, 5, 7), "sus2": (0, 2, 7)}
# Tensions a sustained melody note may sit on over each quality (no rubs).
_TENSIONS = {"maj": (2, 9, 11), "maj7": (2, 9), "min": (2, 10, 5), "min7": (2, 5), "7": (2, 9),
             "dim": (2, 5, 8, 11), "aug": (2,), "sus4": (2, 10), "sus2": (5, 10)}
# Jazz voicings (above the root): rootless 9ths / 6-9s, the trio and swing sound.
_JAZZ_VOICING = {"maj": (4, 7, 9, 14), "maj7": (4, 7, 11, 14), "min": (3, 7, 10, 14), "min7": (3, 7, 10, 14),
                 "7": (4, 9, 10, 14), "dim": (3, 6, 9, 12), "aug": (4, 8, 10, 14), "sus4": (5, 7, 10, 14),
                 "sus2": (2, 7, 10, 14)}


def chord_pcs(root: int, quality: str) -> tuple[int, ...]:
    return tuple((root + i) % 12 for i in _TRIAD.get(quality, _TRIAD["maj"]))


def fits(pitch: int, root: int, quality: str) -> bool:
    """A melody note that sits well over the chord: a chord tone or a gentle
    tension, never a half step above or below a chord tone it would rub on."""
    pc = (pitch - root) % 12
    tones = _TRIAD.get(quality, _TRIAD["maj"])
    if pc in tones:
        return True
    if pc in _TENSIONS.get(quality, ()):
        return not any((pc - t) % 12 == 1 for t in tones)
    return False


class Chord:
    __slots__ = ("start", "dur", "symbol", "root", "quality")

    def __init__(self, start: float, dur: float, symbol: str, root: int, quality: str):
        self.start, self.dur, self.symbol, self.root, self.quality = start, dur, symbol, root, quality

    @property
    def end(self) -> float:
        return self.start + self.dur


def parse_symbol(symbol: str, tonic: int, scale: str) -> tuple[int, str]:
    off, quality = roman_to_semitone_offset(symbol, scale)
    if symbol.endswith("6") and quality in ("maj", "min"):
        quality = quality                      # a 6 chord voices like its triad + 6 (jazz voicing)
    return (tonic + off) % 12, quality


# ---------------------------------------------------------------------------
# Original Christmas-feel tunes
# ---------------------------------------------------------------------------

# 8-bar harmony templates in bars: (symbol, bars). Jazz symbols; plain styles
# simplify them (_plain_symbol).
_A_TEMPLATES = (
    # I-vi-ii-V with a iii-VI-ii-V turnaround.
    (("Imaj7", 1), ("vi7", 1), ("ii7", 1), ("V7", 1), ("iii7", .5), ("VI7", .5), ("ii7", .5), ("V7", .5),
     ("Imaj7", .5), ("VI7", .5), ("ii7", .5), ("V7", .5)),
    # Diminished passing chords up to iii, then VI7-ii-V.
    (("Imaj7", 1), ("#idim", 1), ("ii7", 1), ("#iidim", 1), ("iii7", 1), ("VI7", 1), ("ii7", 1), ("V7", 1)),
    # I-I7-IV-iv, the plagal Christmas colour, then home through VI7.
    (("Imaj7", 1), ("I7", 1), ("IVmaj7", 1), ("iv7", 1), ("iii7", 1), ("VI7", 1), ("ii7", .5), ("V7", .5),
     ("Imaj7", .5), ("V7", .5)),
    # Suspensions: Vsus4-V, vi, IV, ii, Vsus4-V7.
    (("Imaj7", 1), ("Vsus4", .5), ("V7", .5), ("vi7", 1), ("IVmaj7", 1), ("ii7", 1), ("Vsus4", .5), ("V7", .5),
     ("Imaj7", 1), ("VI7", .5), ("V7", .5)),
)
# The last A ends on the tonic (the second half of each template is replaced).
_A_ENDINGS = (
    (("ii7", 1), ("V7", 1), ("Imaj7", 2)),
    (("IVmaj7", .5), ("iv7", .5), ("iii7", .5), ("VI7", .5), ("ii7", .5), ("V7", .5), ("Imaj7", 1)),
    (("IV", 1), ("iv", 1), ("Imaj7", 2)),
)
_B_TEMPLATES = (
    (("I7", 1), ("I7", 1), ("IVmaj7", 1), ("IVmaj7", 1), ("II7", 1), ("II7", 1), ("ii7", 1), ("V7", 1)),
    (("iii7", 1), ("VI7", 1), ("ii7", 1), ("V7", 1), ("IVmaj7", 1), ("iv7", 1), ("ii7", 1), ("V7", 1)),
    (("IVmaj7", 1), ("iv7", 1), ("iii7", 1), ("VI7", 1), ("II7", 1), ("ii7", 1), ("Vsus4", 1), ("V7", 1)),
)

# Two-bar rhythm cells (beat offsets, durations in beats) per meter.
_CELLS = {
    4: (((0, 1), (1, 1), (2, 2), (4, 3), (7, 1)),
        ((0, 1.5), (1.5, .5), (2, 2), (4, 2), (6, 2)),
        ((0, 2), (2, 1), (3, 1), (4, 4)),
        ((1, 1), (2, 1), (3, 1), (4, 3), (7, 1)),
        ((0, 1), (1, 1), (2, 1), (3, 1), (4, 4))),
    3: (((0, 2), (2, 1), (3, 3)),
        ((0, 1), (1, 1), (2, 1), (3, 3)),
        ((0, 1.5), (1.5, .5), (2, 1), (3, 2), (5, 1)),
        ((0, 3), (3, 2), (5, 1))),
}
# Contours as scale-step moves between the notes of a cell.
_CONTOURS = ((1, 1, -1, -1, 1), (2, -1, -1, 2, -1), (-1, -1, 2, 1, -1), (1, 2, -1, -2, 1), (0, 1, 1, -2, -1))


def _plain_symbol(sym: str) -> str:
    """A jazz symbol as a plain carol chord: triads, dominant 7ths kept,
    diminished passing chords and sus4s kept."""
    for suffix in ("maj7", "m7", "min7", "6", "9"):
        if sym.endswith(suffix):
            return sym[: -len(suffix)]
    if sym.endswith("7") and sym[:1].islower():
        return sym[:-1]
    return sym


_TITLE_WORDS = (
    ("Snowlit", "Candlelight", "Evergreen", "Silver", "Starlit", "Frosted", "Winter", "Hearthside", "Midnight",
     "December", "Northern", "Hollyberry", "Lantern", "Firelight", "Velvet", "Snowfall"),
    ("Reverie", "Promenade", "Serenade", "Lights", "Morning", "Glow", "Stroll", "Carol", "Lullaby", "Evening",
     "Dream", "Hymn", "Homeward", "Window", "Embers", "Hush"),
)


def original_title(seed: int, beats: int = 4) -> str:
    """A cozy name for an original tune (stable per seed): "Starlit Reverie",
    and a waltz when it's in 3/4."""
    rng = np.random.default_rng(zlib.crc32(f"{seed}|title".encode()))
    a = _TITLE_WORDS[0][int(rng.integers(0, len(_TITLE_WORDS[0])))]
    b = "Waltz" if beats == 3 else _TITLE_WORDS[1][int(rng.integers(0, len(_TITLE_WORDS[1])))]
    return f"{a} {b}"


@lru_cache(maxsize=64)
def original_tune(seed: int, beats: int = 4, plain: bool = False) -> Tune:
    """An original 32-bar AABA tune with Christmas harmony, from the seed."""
    rng = np.random.default_rng(zlib.crc32(f"{seed}|christmas original|{beats}".encode()))
    a = _A_TEMPLATES[int(rng.integers(0, len(_A_TEMPLATES)))]
    b = _B_TEMPLATES[int(rng.integers(0, len(_B_TEMPLATES)))]
    end = _A_ENDINGS[int(rng.integers(0, len(_A_ENDINGS)))]

    def first_half(t):
        out, acc = [], 0.0
        for sym, bars in t:
            if acc >= 4 - 1e-6:
                break
            out.append((sym, bars))
            acc += bars
        return out

    last_a = first_half(a) + list(end)
    form = list(a) + list(a) + list(b) + last_a
    chords = []
    t = 0.0
    for sym, bars in form:
        s = _plain_symbol(sym) if plain else sym
        dur = bars * beats
        if beats == 3 and bars == .5:
            dur = 2.0 if abs(t % 3) < 1e-6 else 1.0          # 2 + 1 beats in a waltz bar
        chords.append(TuneChord(start=round(t, 4), dur=dur, symbol=s))
        t += dur
    # Melody: one A phrase (8 bars) written once and repeated, a B phrase,
    # the last A with a cadence home.
    scale = (0, 2, 4, 5, 7, 9, 11)
    pool = [p for p in range(55, 82) if p % 12 in scale]

    def chord_at(beat: float) -> tuple[int, str]:
        for c in chords:
            if c.start - 1e-6 <= beat < c.start + c.dur - 1e-6:
                return parse_symbol(c.symbol, 0, "major")
        return 0, "maj"

    def nearest_fit(p: int, beat: float, prefer: int) -> int:
        root, q = chord_at(beat)
        cands = [x for x in pool if fits(x, root, q)] or pool
        tones = [x for x in cands if (x - root) % 12 in _TRIAD.get(q, (0, 4, 7))]
        use = tones or cands
        return min(use, key=lambda x: (abs(x - p), (x - p) * prefer < 0))

    def phrase(start_bar: int, bars: int, centre: int, cadence: Optional[int], cells) -> list[TuneNote]:
        notes: list[TuneNote] = []
        cur = centre
        for k in range(0, bars, 2):
            cell = cells[(k // 2) % len(cells)]
            contour = _CONTOURS[int(rng.integers(0, len(_CONTOURS)))]
            for i, (off, dur) in enumerate(cell):
                beat = (start_bar + k) * beats + off
                if beat >= (start_bar + bars) * beats:
                    break
                if i:
                    step = contour[(i - 1) % len(contour)]
                    idx = min(range(len(pool)), key=lambda j: abs(pool[j] - cur))
                    cur = pool[int(np.clip(idx + step, 0, len(pool) - 1))]
                strong = off % beats == 0 or dur >= 2
                p = nearest_fit(cur, beat, 1) if strong else cur
                root, q = chord_at(beat)
                if not fits(p, root, q):
                    p = nearest_fit(p, beat, 1)
                cur = p
                notes.append(TuneNote(start=float(beat), dur=float(dur), pitch=int(p)))
        if cadence is not None and notes:
            last = notes[-1]
            notes[-1] = TuneNote(start=last.start, dur=(start_bar + bars) * beats - last.start,
                                 pitch=nearest_fit(cadence, last.start, -1))
        return notes

    cells_all = _CELLS.get(beats, _CELLS[4])
    pick = [cells_all[int(i)] for i in rng.choice(len(cells_all), size=2, replace=False)]
    a_notes = phrase(0, 8, 67, 62, pick)                      # ends on the 2nd (a half cadence)
    # The A melody returns note for note; the B rises; the last A cadences home.
    melody = list(a_notes) + [TuneNote(n.start + 8 * beats, n.dur, n.pitch) for n in a_notes]
    b_cells = [cells_all[int(rng.integers(0, len(cells_all)))]]
    melody += phrase(16, 8, 72, 67, b_cells)
    last = [TuneNote(n.start + 24 * beats, n.dur, n.pitch) for n in a_notes if n.start < 4 * beats]
    last += phrase(28, 4, last[-1].pitch if last else 64, 60, pick[1:])
    melody += last
    return Tune(id="original", title=original_title(seed, beats), source="Original (generated).",
                beats=beats, pickup=0.0, scale="major", melody=tuple(melody), chords=tuple(chords),
                tempo=(72.0, 140.0))


# ---------------------------------------------------------------------------
# Reharmonisation (jazz styles) and cadence colour
# ---------------------------------------------------------------------------

def _notes_in(tune_notes: list[TuneNote], a: float, b: float) -> list[TuneNote]:
    return [n for n in tune_notes if a - 1e-6 <= n.start < b - 1e-6 or (n.start < a < n.start + n.dur)]


def _all_fit(notes: list[TuneNote], symbol: str, scale: str, tonic: int) -> bool:
    root, q = parse_symbol(symbol, tonic, scale)
    return all(fits(n.pitch, root, q) or n.dur < 0.75 for n in notes)


def reharmonize(tune: Tune, style: str, rich: bool, plain: bool) -> list[TuneChord]:
    """The tune's chords for a style. Jazz styles add 7ths/6ths, ii-V
    approaches, VI7 turnarounds and passing diminished chords wherever the
    melody allows; plain styles add a suspension before cadences. Every new
    chord is checked against the melody notes it sits under."""
    chords = list(tune.chords)
    tonic, scale = tune.tonic_pc, tune.scale
    if plain or (style not in JAZZ and not rich):
        return _suspend_cadences(chords, tune) if style in ("orchestral", "choir") else chords
    out: list[TuneChord] = []
    seventh = {"I": "Imaj7", "IV": "IVmaj7", "ii": "ii7", "iii": "iii7", "vi": "vi7", "V": "V7", "i": "i7",
               "iv": "iv7", "v": "v7", "III": "IIImaj7", "VI": "VImaj7", "VII": "VII7"}
    for i, c in enumerate(chords):
        sym = seventh.get(c.symbol, c.symbol)
        notes = _notes_in(list(tune.melody), c.start, c.start + c.dur)
        if not _all_fit(notes, sym, scale, tonic):
            sym = c.symbol
        nxt = chords[i + 1] if i + 1 < len(chords) else None
        # ii-V: a dominant lasting 2+ beats gets its ii in the first half.
        if sym.startswith("V7") and c.dur >= 2 * (tune.beats // 2 or 1) and c.dur >= 2:
            half = c.dur / 2 if tune.beats == 4 else (2.0 if c.dur >= 3 else c.dur)
            ii = "ii7" if scale == "major" else "iiø"
            if ii != "iiø" and _all_fit(_notes_in(list(tune.melody), c.start, c.start + half), ii, scale, tonic) \
                    and half < c.dur:
                out.append(TuneChord(c.start, half, ii))
                out.append(TuneChord(c.start + half, c.dur - half, sym))
                continue
        # A long tonic before ii/IV gets a VI7 (V7/ii) in its last part.
        if (rich or style == "swing") and c.symbol == "I" and nxt is not None and nxt.symbol in ("ii", "ii7") \
                and c.dur >= 2 * tune.beats:
            cut = c.dur - tune.beats
            if _all_fit(_notes_in(list(tune.melody), c.start + cut, c.start + c.dur), "VI7", scale, tonic):
                out.append(TuneChord(c.start, cut, sym))
                out.append(TuneChord(c.start + cut, tune.beats, "VI7"))
                continue
        # A passing diminished chord between I and ii (#idim) when I holds a bar.
        if rich and c.symbol == "I" and nxt is not None and nxt.symbol in ("ii", "ii7") and c.dur >= tune.beats:
            half = tune.beats / 2 if tune.beats == 4 else 1.0
            if _all_fit(_notes_in(list(tune.melody), c.start + c.dur - half, c.start + c.dur), "#idim",
                        scale, tonic):
                out.append(TuneChord(c.start, c.dur - half, sym))
                out.append(TuneChord(c.start + c.dur - half, half, "#idim"))
                continue
        out.append(TuneChord(c.start, c.dur, sym))
    return out


def _suspend_cadences(chords: list[TuneChord], tune: Tune) -> list[TuneChord]:
    """V lasting a full bar before I becomes Vsus4 -> V when the melody
    doesn't sit on the 3rd of V in its first half."""
    out = []
    for i, c in enumerate(chords):
        nxt = chords[i + 1] if i + 1 < len(chords) else None
        if c.symbol in ("V", "V7") and nxt is not None and nxt.symbol in ("I", "i") and c.dur >= tune.beats:
            half = c.dur / 2 if tune.beats == 4 else 2.0
            if _all_fit(_notes_in(list(tune.melody), c.start, c.start + half), "Vsus4", tune.scale, tune.tonic_pc):
                out.append(TuneChord(c.start, half, "Vsus4"))
                out.append(TuneChord(c.start + half, c.dur - half, c.symbol))
                continue
        out.append(c)
    return out


# ---------------------------------------------------------------------------
# Planning the form
# ---------------------------------------------------------------------------

def resolve_tune(tune_id: Optional[str], seed: int, style: str) -> Tune:
    t = carol(tune_id) if tune_id and tune_id not in ("original", "") else None
    if t is not None:
        return t
    beats = 3 if (np.random.default_rng(zlib.crc32(f"{seed}|meter".encode())).random() < 0.3
                  and style in ("trio", "fireside", "choir", "orchestral")) else 4
    return original_tune(int(seed), beats, plain=style not in JAZZ)


def _first_available(names: tuple[str, ...], band: list[str]) -> str:
    for n in names:
        if n in band:
            return n
    for n in band:                                        # any melody-capable instrument
        if n in _RANGE:
            return n
    return band[0] if band else "piano"


def _slice(tune_notes, chords, a_beat: float, b_beat: float, pickup_into: float = 0.0):
    """Melody notes and chords of tune beats [a, b), section-relative. Notes
    of the next pass's pickup (``pickup_into`` beats before b) are left out."""
    mel = []
    for n in tune_notes:
        if a_beat - 1e-6 <= n.start < b_beat - pickup_into - 1e-6:
            end = min(n.start + n.dur, b_beat - pickup_into)
            mel.append([round(n.start - a_beat, 4), round(end - n.start, 4), n.pitch])
    ch = []
    for c in chords:
        s, e = max(c.start, a_beat), min(c.start + c.dur, b_beat)
        if e - s > 1e-6:
            ch.append([c.symbol, round(s - a_beat, 4), round(e - s, 4)])
    return mel, ch


def _pivot(sec: dict, symbol: str, beats: int) -> None:
    """End a section on the dominant of the key a half step up (bVI7 in
    major, VI7 in minor): the lift into the last pass, so its pickup doesn't
    land on the old tonic."""
    total = (sec["end_bar"] - sec["start_bar"] + 1) * beats
    cut = total - beats
    chords = [[s, st, d] for s, st, d in sec["info"]["chords"] if st < cut - 1e-6]
    if chords and chords[-1][1] + chords[-1][2] > cut:
        chords[-1][2] = round(cut - chords[-1][1], 4)
    chords.append([symbol, cut, beats])
    sec["info"]["chords"] = chords
    sec["progression"] = [(s, d / beats) for s, _st, d in chords]


def plan_song(genre: str, *, seed: int, tune: Optional[str] = None, key: Optional[str] = None,
              tempo: Optional[float] = None, length_seconds: Optional[float] = None,
              arrangement: str = "", instruments: Optional[list[str]] = None) -> dict:
    """Lay out a Christmas song: sections for ``compose_song`` plus the song's
    key, scale, tempo and meter. Same inputs, same plan."""
    from src.daw_integration.generic.styles import STYLES
    style = substyle(genre)
    preset = STYLES[genre]
    rng = np.random.default_rng(zlib.crc32(f"{seed}|christmas plan|{genre}".encode()))
    var = variants(arrangement)
    band = list(instruments or preset.default_instruments)
    t = resolve_tune(tune, seed, style)
    backing = "backing_track" in var or "guide_melody" in var
    # A backing track sings one verse per pass: as many passes as the carol
    # has verses (up to four) unless a length is asked for.
    from .lyrics import verse_count
    verses = verse_count(t.id) if backing and t.id != "original" else 0
    defaults = STYLE_DEFAULTS[style]
    # Key and tempo: explicit wins; otherwise vary between the style's keys
    # (a minor tune picks the relative minor) and a tempo that suits the tune.
    if key:
        song_key = key
    else:
        k = defaults["keys"][int(rng.integers(0, len(defaults["keys"])))]
        song_key = _MINOR_NAMES[(_tonic_pc(k) + 9) % 12] if "minor" in t.scale else k
    lo, hi = defaults["tempo"]
    if style in _BALLAD_TEMPO and not t.lively and (t.beats == 3 or t.tempo[1] <= 100):
        lo, hi = _BALLAD_TEMPO[style]
    if t.id != "original":
        lo, hi = max(lo, t.tempo[0] * 0.85), min(hi, t.tempo[1] * 1.15)
        if lo > hi:
            lo = hi = (lo + hi) / 2
    bpm = float(tempo) if tempo else float(round(lo + (hi - lo) * rng.random()))
    beats = t.beats
    bar_s = beats * 60.0 / bpm
    rich = "rich_harmony" in var or (style in JAZZ and "plain_harmony" not in var)
    chords = reharmonize(t, style, rich="rich_harmony" in var, plain="plain_harmony" in var or not rich)
    # One pass = the tune once (twice when the tune is short).
    times = 2 if (t.bars * bar_s < 36 and not verses) else 1
    pass_bars = t.bars * times
    notes = list(t.melody)
    if times == 2:
        span = t.bars * beats
        # The repeat's pickup cuts the first time's last note short.
        notes = [TuneNote(n.start, min(n.dur, span - t.pickup - n.start), n.pitch) for n in notes]
        notes = notes + [TuneNote(n.start + span, n.dur, n.pitch) for n in t.melody]
        chords = chords + [TuneChord(c.start + span, c.dur, c.symbol) for c in chords]
    target = float(length_seconds) if length_seconds else 150.0
    target = max(30.0, min(600.0, target))
    fixed = (4 + 3 + (4 if style in JAZZ or style == "pop" else 0)) * bar_s
    n_pass = int(np.clip(round((target - fixed) / (pass_bars * bar_s)), 1, 8))
    interlude = n_pass >= 3
    if interlude:
        n_pass_left = target - fixed - 4 * bar_s
        n_pass = int(np.clip(round(n_pass_left / (pass_bars * bar_s)), 2, 8))
    if verses and not length_seconds:
        n_pass = min(verses, 4)
        interlude = n_pass >= 3
    lift_p = defaults["lift"] if "key_change" not in var else 1.0
    lift = "no_key_change" not in var and n_pass >= 2 and rng.random() < lift_p
    if backing and "key_change" not in var:
        lift = False                                # singers keep one key unless asked
    final_key = ((_MINOR_NAMES if "minor" in t.scale else _FLAT_NAMES)[(_tonic_pc(song_key) + 1) % 12]
                 if lift else song_key)

    sections: list[dict] = []
    bar = 0
    total_beats = pass_bars * beats
    tail = t.bars * beats

    def add(label, role, bars, info, energy, sec_key=None, tempo_points=None):
        nonlocal bar
        prog = [(s, d / beats) for s, _st, d in info["chords"]]
        sec = {"start_bar": bar, "end_bar": bar + bars - 1, "label": label, "role": role,
               "progression": prog, "progression_exact": True, "energy": energy, "info": info}
        if sec_key:
            sec["key"] = sec_key
        if tempo_points:
            sec["tempo_points"] = tempo_points
        sections.append(sec)
        bar += bars

    common = {"style": style, "tune": t.id, "tune_title": t.title, "tune_tonic": t.tonic_pc, "scale": t.scale,
              "tune_range": [min(n.pitch for n in t.melody), max(n.pitch for n in t.melody)],
              "phrase_beats": t.phrase_bars * beats, "beats": beats, "lively": t.lively,
              "passes": n_pass, "band": band, "times": times,
              **({"backing": True, "guide": "guide_melody" in var} if backing else {})}
    if backing:
        # A one-bar count-in on a recorded hi-hat (played by the band's first
        # member's part, so every style has one).
        tonic = "i" if "minor" in t.scale else "I"
        add("Count-in", "intro", 1, {**common, "kind": "count_in", "lead": "", "melody": [],
                                     "chords": [[tonic, 0, beats]], "count_in_by": band[0] if band else "piano",
                                     "next_pickup": 0.0}, 0.5)
    # Intro: the tune's last phrase.
    mel, ch = _slice(notes, chords, tail - 4 * beats, tail, pickup_into=t.pickup)
    lead = _first_available(LEADS[style]["intro"], band)
    add("Intro", "intro", 4, {**common, "kind": "intro", "lead": lead, "melody": mel, "chords": ch,
                              "next_pickup": t.pickup}, 0.62)
    kinds = ["pass1", "pass2"] + ["var"] * max(0, n_pass - 3) + (["final"] if n_pass >= 3 else [])
    if n_pass <= 2:
        kinds = ["pass1", "final"][2 - n_pass:]
    for i, kind in enumerate(kinds):
        last = i == len(kinds) - 1
        sec_key = final_key if (last and lift) else None
        if last and lift and not interlude and sections:
            _pivot(sections[-1], "VI7" if "minor" in t.scale else "bVI7", beats)
        if last and interlude:
            # A short interlude before the last pass: IV - iv - I - V7 (of the new key).
            il = [["IVmaj7" if style in JAZZ else "IV", 0, beats], ["iv7" if style in JAZZ else "iv", beats, beats],
                  ["Imaj7" if style in JAZZ else "I", 2 * beats, beats],
                  ["V7", 3 * beats, beats] if not lift else ["bVI7", 3 * beats, beats]]
            if "minor" in t.scale:
                il = [["iv", 0, beats], ["VI", beats, beats], ["ii", 2 * beats, beats],
                      ["V7", 3 * beats, beats] if not lift else ["VI7", 3 * beats, beats]]
            add("Interlude", "bridge", 4, {**common, "kind": "interlude", "lead": "", "melody": [], "chords": il,
                                          "next_pickup": t.pickup}, 0.72)
        lead = _first_available(LEADS[style][kind], band)
        mel, ch = _slice(notes, chords, 0, total_beats, pickup_into=0.0 if last else t.pickup)
        # The pickup of this pass sounds at the end of the previous section.
        pick = [[round(n.start, 4), n.dur, n.pitch] for n in notes if n.start < 0]
        energy = {"pass1": 0.74, "pass2": 0.86, "var": 0.82, "final": 0.92}[kind]
        role = {"pass1": "verse", "pass2": "chorus", "var": "bridge", "final": "chorus"}[kind]
        add(f"{'Verse' if kind == 'pass1' else 'Final' if kind == 'final' else 'Chorus'} {i + 1}", role,
            pass_bars, {**common, "kind": kind, "pass": i + 1, "lead": lead, "melody": pick + mel, "chords": ch,
                        "final": last, "next_pickup": 0.0 if last else t.pickup}, energy, sec_key)
    # Ending: the last phrase again (tag), then a plagal cadence held with a
    # ritardando. Choir ends on an "Amen" (IV - I).
    end_key = final_key
    tag_mel, tag_ch = _slice(notes, chords, tail - 4 * beats, tail - beats)
    jazz = style in JAZZ
    if "minor" in t.scale:
        cad = [["iv", 0, beats], ["V7", beats, beats], ["i", 2 * beats, 2 * beats]]
    elif style == "choir":
        cad = [["IV", 0, beats], ["IV", beats, beats], ["I", 2 * beats, 2 * beats]]
    else:
        cad = [["IVmaj7" if jazz else "IV", 0, beats], ["iv6" if jazz else "iv", beats, beats],
               ["Imaj7" if jazz else "I", 2 * beats, 2 * beats]]
    outro_chords = tag_ch + [[s, st + 3 * beats, d] for s, st, d in cad]
    # The melody holds the tonic through the plagal cadence (the 5th over iv-V
    # in a minor tune) and rings on the final chord.
    home = t.melody[-1].pitch
    if "minor" in t.scale:
        final_note = [[3 * beats, 2 * beats, home - 5], [5 * beats, 2 * beats, home]]
    else:
        final_note = [[3 * beats, 4 * beats, home]]
    outro_mel = tag_mel + final_note
    tp = [(3 + 2, bpm * 0.9), (3 + 2.5, bpm * 0.8), (3 + 3, bpm * 0.68)]
    add("Outro", "outro", 7, {**common, "kind": "outro", "lead": _first_available(LEADS[style]["final"], band),
                              "melody": outro_mel, "chords": outro_chords, "hold_from": 5 * beats,
                              "final": True, "next_pickup": 0.0}, 0.8, end_key if lift else None, tp)
    # Each section knows the next one's pickup (it sounds over this one's end).
    for a, b in zip(sections, sections[1:]):
        pick = [[round(st + (a["end_bar"] - a["start_bar"] + 1) * beats, 4), d, p]
                for st, d, p in b["info"]["melody"] if st < 0]
        if pick:
            a["info"]["tail_melody"] = pick
            a["info"]["tail_lead"] = b["info"]["lead"]
            a["info"]["tail_shift"] = (_tonic_pc(b.get("key") or song_key) - _tonic_pc(a.get("key") or song_key)) % 12
    return {
        "sections": sections, "key": song_key, "final_key": final_key, "scale": t.scale, "tempo": bpm,
        "time_signature": (beats, 4), "tune": t.id, "tune_title": t.title, "style": style,
        "backing": backing, "guide": backing and "guide_melody" in var, "times": times,
        "bars": bar, "seconds": round(sum((s["end_bar"] - s["start_bar"] + 1) for s in sections) * bar_s, 1),
    }


def band_for(band: list[str], arrangement: str) -> list[str]:
    """The band plus any players the arrangement variants need."""
    out = list(band)
    for v in variants(arrangement):
        out += [i for i in ARRANGEMENT_INSTRUMENTS.get(v, ()) if i not in out]
    return out


def apply_overrides(sections: list[dict], overrides: Optional[dict]) -> list[dict]:
    """Per-role overrides from a request (energy, arrangement, instruments)
    on planned sections. Bars, keys and chords stay the plan's."""
    out = []
    for sec in sections:
        o = (overrides or {}).get(sec["role"]) or {}
        sec = dict(sec)
        if o.get("energy") is not None:
            sec["energy"] = float(o["energy"])
        if o.get("arrangement") is not None:
            sec["arrangement"] = o["arrangement"]
        if o.get("instruments"):
            sec["instruments"] = list(o["instruments"])
        out.append(sec)
    return out


# ---------------------------------------------------------------------------
# Section view used by every part
# ---------------------------------------------------------------------------

class _Sec:
    def __init__(self, ctx: TechniqueContext):
        self.ctx = ctx
        self.info = dict(ctx.section_info or {})
        self.style = self.info.get("style") or substyle(ctx.genre)
        self.kind = self.info.get("kind", "pass1")
        self.beats = int(ctx.time_signature[0])
        self.clock = _Clock(ctx)
        self.tonic = _tonic_pc(ctx.key)
        self.scale = self.info.get("scale", "major")
        self.var = variants(ctx)
        self.swing = STYLE_DEFAULTS[self.style]["swing"]
        self.rng = ctx.rng
        self.total = ctx.bar_count * self.beats
        self.chords = [Chord(st, d, s, *parse_symbol(s, self.tonic, self.scale))
                       for s, st, d in self.info.get("chords", [])]
        if not self.chords:                                # ran without a plan: one bar of tonic
            self.chords = [Chord(0.0, float(self.total), "I", self.tonic, "maj")]
        tt = int(self.info.get("tune_tonic", 0))
        self.shift = (self.tonic - tt) % 12
        if self.shift > 6:
            self.shift -= 12
        self.melody = [(float(s), float(d), int(p) + self.shift) for s, d, p in self.info.get("melody", [])]
        lo, hi = self.info.get("tune_range", [60, 76])
        self.range = (lo + self.shift, hi + self.shift)
        self.final = bool(self.info.get("final"))
        self.hold_from = self.info.get("hold_from")

    def played(self, inst: Optional[str] = None) -> list[tuple[float, float, int]]:
        """The melody as the lead instrument plays it (embellished on jazz and
        pop restatements). Seeded by the section, so every part sees the
        same notes."""
        inst = inst or self.info.get("lead") or ""
        _v, _l, emb = _MELODY_STYLE.get(inst, (72, 0.96, False))
        if not (emb and self.kind in ("pass2", "var") and self.style in JAZZ + ("pop",)) or self.calm:
            return self.melody
        rng = np.random.default_rng(zlib.crc32(f"{self.ctx.song_seed}|{self.ctx.section_label}|embellish".encode()))
        return _embellish(self, self.melody, rng)

    # Time ----------------------------------------------------------------
    def sw(self, beat: float) -> float:
        """Swing an off-beat 8th to the last triplet 8th."""
        if not self.swing:
            return beat
        whole = np.floor(beat + 1e-9)
        frac = beat - whole
        if abs(frac - 0.5) < 1e-6:
            return whole + 2.0 / 3.0
        return beat

    def t(self, beat: float) -> float:
        return self.clock.t(0, self.sw(beat) * 4.0)

    def note(self, out: list, pitch: int, beat: float, dur: float, vel: float, *, ms: float = 6.0,
             jitter: float = 4.0, legato: float = 0.95, delay: float = 0.0) -> None:
        start = self.t(beat)
        end = self.t(beat + dur)
        s, v = _human(self.rng, start + delay, vel, ms=ms, vel_jitter=jitter)
        out.append(NoteEvent(pitch=int(pitch), start=s, end=max(s + 0.04, start + (end - start) * legato),
                             velocity=v))

    def chord_at(self, beat: float) -> Chord:
        for c in self.chords:
            if c.start - 1e-6 <= beat < c.end - 1e-6:
                return c
        return self.chords[-1] if beat >= 0 else self.chords[0]

    def octave_for(self, inst: str, lo_hi: Optional[tuple[int, int]] = None) -> int:
        """Semitones (multiple of 12) that put the tune in the instrument's range."""
        lo, hi = lo_hi or _RANGE.get(inst, (60, 84))
        mid = (lo + hi) / 2
        cur = (self.range[0] + self.range[1]) / 2
        return int(12 * round((mid - cur) / 12))

    @property
    def strings_end(self) -> bool:
        """The final chord is the strings' alone (the orchestral style's
        default ending; anywhere with "strings_ending"); a harp roll may ring
        under it."""
        return "string_section" in self.info.get("band", ("string_section",)) and (
            "strings_ending" in self.var or (self.style == "orchestral" and "celesta_ending" not in self.var))

    @property
    def calm(self) -> bool:
        return "less_busy" in self.var

    @property
    def warm(self) -> bool:
        return "warmer" in self.var


def _voice_near(pcs: tuple[int, ...], lo: int, hi: int, target: float, previous: Optional[list[int]] = None,
                count: int = 4) -> list[int]:
    """Close voicing of the pitch classes in [lo, hi], voice-led from the
    previous chord or centred on ``target``."""
    cands = sorted(p for p in range(lo, hi + 1) if p % 12 in pcs)
    best: Optional[list[int]] = None
    best_cost = 1e9
    for i in range(len(cands)):
        v = []
        for p in cands[i:]:
            if p % 12 not in {x % 12 for x in v}:
                v.append(p)
            if len(v) == min(count, len(set(pcs))):
                break
        if len(v) < min(count, len(set(pcs))):
            continue
        if previous:
            cost = sum(min(abs(p - q) for q in previous) for p in v)
        else:
            cost = abs(sum(v) / len(v) - target) * 2
        if v[-1] - v[0] > 12:
            cost += 6
        if cost < best_cost:
            best, best_cost = v, cost
    return best or [int(target)]


def _jazz_voicing(c: Chord, previous: Optional[list[int]], lo: int = 50, hi: int = 76) -> list[int]:
    shape = _JAZZ_VOICING.get(c.quality, _JAZZ_VOICING["maj"])
    if c.symbol.endswith("6") and c.quality == "min":
        shape = (3, 7, 9, 14)
    cands = []
    for base in range(lo - 12, hi):
        if base % 12 != c.root:
            continue
        ch = sorted(base + iv for iv in shape)
        for inv in range(len(ch)):
            v = sorted(ch[inv:] + [p + 12 for p in ch[:inv]])
            if lo <= v[0] and v[-1] <= hi:
                cands.append(v)
    if not cands:
        return _voice_near(chord_pcs(c.root, c.quality), lo, hi, (lo + hi) / 2)
    if previous is None:
        return min(cands, key=lambda v: abs(sum(v) / len(v) - (lo + hi) / 2))
    return min(cands, key=lambda v: sum(min(abs(p - q) for q in previous) for p in v))


def _below_melody(sec: _Sec, beat: float, default_top: int) -> int:
    """Highest pitch accompaniment may reach at ``beat``: under the melody
    as the lead instrument sounds it."""
    lead = sec.info.get("lead")
    if not lead:
        return default_top
    shift = sec.octave_for(lead)
    sounding = [p + shift for s, d, p in sec.played() if s - 1e-6 <= beat < s + d]
    return min(default_top, min(sounding) - 2) if sounding else default_top


# ---------------------------------------------------------------------------
# Parts
# ---------------------------------------------------------------------------

def _melody(sec: _Sec, inst: str, *, vel: float = 76, legato: float = 0.97,
            octave: Optional[int] = None, double_8vb: bool = False) -> list[NoteEvent]:
    out: list[NoteEvent] = []
    shift = sec.octave_for(inst) if octave is None else octave
    mel = sec.played(inst)
    phrase = float(sec.info.get("phrase_beats") or 4 * sec.beats)
    lo, hi = sec.range
    for i, (s, d, p) in enumerate(mel):
        pos = (s % phrase) / phrase                      # shape each phrase: rise, then relax
        arc = 1.0 - abs(pos - 0.55) * 0.5
        height = (p - lo) / max(1, hi - lo)
        v = vel * (0.86 + 0.12 * arc + 0.08 * height)
        if sec.hold_from is not None and s >= sec.hold_from - 1e-6:
            d = max(d, sec.total - s)
            v *= 0.9
        nxt = mel[i + 1][0] if i + 1 < len(mel) else None
        dur = d if nxt is None else min(d, nxt - s)
        sec.note(out, p + shift, s, dur, v, ms=7.0, jitter=3.0, legato=legato)
        if double_8vb:
            sec.note(out, p + shift - 12, s, dur, v * 0.8, ms=7.0, jitter=3.0, legato=legato)
    return out


def _embellish(sec: _Sec, mel: list, rng: np.random.Generator) -> list:
    """A jazz player's restatement: long notes get a neighbour-tone turn,
    some downbeats are anticipated by an 8th (only where the note also fits
    the chord it now starts over), leaps get a passing tone."""
    out = []
    for i, (s, d, p) in enumerate(mel):
        c = sec.chord_at(s)
        if d >= 2 and rng.random() < 0.5:
            up = p + 2 if fits(p + 2, c.root, c.quality) else p + 1
            if fits(up, c.root, c.quality) or (up - p) == 2:
                out += [(s, 0.5, p), (s + 0.5, 0.5, up), (s + 1.0, d - 1.0, p)]
                continue
        early = sec.chord_at(s - 0.5) if s >= 0.5 else c
        if i and d >= 1 and abs(s - round(s)) < 1e-6 and s >= 1 and rng.random() < 0.25 \
                and fits(p, early.root, early.quality):
            ps, pd, pp = out[-1]
            if pd > 0.5 and abs((ps + pd) - s) < 1e-6:
                out[-1] = (ps, pd - 0.5, pp)
                out.append((s - 0.5, d + 0.5, p))
                continue
        if i and abs(p - out[-1][2]) in (3, 4) and out[-1][1] >= 1 and rng.random() < 0.4:
            ps, pd, pp = out[-1]
            mid = (pp + p) // 2
            if fits(mid, sec.chord_at(ps + pd - 0.5).root, sec.chord_at(ps + pd - 0.5).quality):
                out[-1] = (ps, pd - 0.5, pp)
                out.append((ps + pd - 0.5, 0.5, mid))
        out.append((s, d, p))
    return out


def _harmony_voice(sec: _Sec, inst: str, *, below: int = 1, vel: float = 64) -> list[NoteEvent]:
    """A second voice under the tune (sax soli, choir alto): the nearest
    chord tone a 3rd-6th below each melody note."""
    out: list[NoteEvent] = []
    shift = sec.octave_for(inst, _RANGE.get("sax_alto"))
    for s, d, p in sec.melody:
        if s < 0:
            continue
        c = sec.chord_at(s)
        target = p + shift - (4 if below == 1 else 8)
        pcs = chord_pcs(c.root, c.quality)
        cands = [q for q in range(target - 5, target + 4) if q % 12 in pcs and q < p + shift - 2]
        if not cands:
            continue
        h = min(cands, key=lambda q: abs(q - target))
        sec.note(out, h, s, d, vel, ms=7.0, jitter=3.0, legato=0.96)
    return out


def _counter(sec: _Sec, inst: str, *, vel: float = 56) -> list[NoteEvent]:
    """A slow countermelody: guide tones (3rds and 7ths) moving by step,
    one per chord, filling under the tune; it answers where the melody holds."""
    out: list[NoteEvent] = []
    lo, hi = _RANGE.get(inst, (55, 72))
    lo, hi = max(lo, 52), min(hi, 74)
    prev: Optional[int] = None
    for c in sec.chords:
        guide = [(c.root + 4) % 12 if c.quality in ("maj", "maj7", "7", "aug") else (c.root + 3) % 12]
        if c.quality in ("7", "min7", "maj7", "dim"):
            guide.append((c.root + _TRIAD[c.quality][-1]) % 12)
        cands = [p for p in range(lo, hi + 1) if p % 12 in guide]
        if not cands:
            continue
        top = _below_melody(sec, c.start, hi)
        cands = [p for p in cands if p <= top] or cands
        p = min(cands, key=lambda x: abs(x - (prev if prev is not None else (lo + hi) // 2)))
        prev = p
        sec.note(out, p, c.start, c.dur, vel, ms=10.0, jitter=3.0, legato=1.0)
    return out


def _pad(sec: _Sec, *, lo: int = 52, hi: int = 76, vel: float = 52, count: int = 4, swell: bool = False,
         jazz: bool = False, legato: float = 1.02) -> list[NoteEvent]:
    out: list[NoteEvent] = []
    prev: Optional[list[int]] = None
    n = len(sec.chords)
    for k, c in enumerate(sec.chords):
        top = min(hi, _below_melody(sec, c.start, hi))
        if jazz:
            v = _jazz_voicing(c, prev, lo, max(lo + 9, top))
        else:
            v = _voice_near(chord_pcs(c.root, c.quality), lo, max(lo + 9, top), (lo + top) / 2, prev, count)
        prev = v
        level = vel * (0.85 + 0.25 * k / max(1, n - 1)) if swell else vel
        dur = c.dur
        if sec.hold_from is not None and c.start >= sec.hold_from - 1e-6:
            dur = sec.total - c.start
        for p in v:
            sec.note(out, p, c.start, dur, level, ms=12.0, jitter=3.0, legato=legato)
    return out


def _bass_line(sec: _Sec, mode: str, *, vel: float = 74, lo: int = 28, hi: int = 50) -> list[NoteEvent]:
    """Bass: 'walk' (4 a bar, chromatic approaches), 'two' (half notes),
    'root' (one per chord, held), 'pop' (root, octave, fifth)."""
    out: list[NoteEvent] = []
    b = sec.beats
    rng = sec.rng

    def root_of(c: Chord) -> int:
        p = c.root + 36
        while p < lo:
            p += 12
        while p > lo + 11:
            p -= 12
        return p

    prev = None
    for k, c in enumerate(sec.chords):
        nxt = sec.chords[k + 1] if k + 1 < len(sec.chords) else None
        r = root_of(c)
        held = sec.hold_from is not None and c.start >= sec.hold_from - 1e-6
        if held or mode == "root":
            dur = (sec.total - c.start) if held else c.dur
            sec.note(out, r, c.start, dur, vel, ms=6.0, legato=0.98)
            prev = r
            continue
        beats = np.arange(c.start, c.end - 1e-6, 1.0)
        if mode == "two":
            step = 2.0 if b == 4 else 3.0
            for i, bt in enumerate(np.arange(c.start, c.end - 1e-6, step)):
                p = r if i % 2 == 0 else r + (7 if r + 7 <= hi else -5)
                sec.note(out, p, bt, min(step, c.end - bt), vel - (4 if i % 2 else 0), ms=6.0, legato=0.92)
            continue
        if mode == "pop":
            for bt in beats:
                rel = (bt - c.start) % b
                p = r if rel == 0 else (r + 12 if rel == 2 and r + 12 <= hi + 7 else r + 7 if rel == 3 else None)
                if p is None:
                    continue
                sec.note(out, p, bt, 1.0 if rel else 1.5, vel - (8 if rel else 0), ms=5.0, legato=0.85)
            continue
        # Walking: root on the chord's first beat, chord tones / scale steps,
        # a half-step approach into the next root.
        tones = chord_pcs(c.root, c.quality)
        target = root_of(nxt) if nxt is not None else r
        cur = r
        for i, bt in enumerate(beats):
            last = i == len(beats) - 1
            if i == 0:
                p = r if prev is None or abs(r - prev) <= 7 else (r + 12 if r + 12 <= hi else r)
            elif last and nxt is not None:
                p = target + (1 if rng.random() < 0.5 and target + 1 <= hi else -1)
            else:
                opts = [q for q in range(cur - 5, cur + 6) if q % 12 in tones and lo <= q <= hi and q != cur]
                p = min(opts, key=lambda q: abs(q - (cur + (target - cur) / max(1, len(beats) - i)))) if opts else cur
            sec.note(out, p, bt, 1.0, vel - (0 if i == 0 else 6), ms=5.0, legato=0.9)
            cur = prev = p
    return out


def _piano_trio(sec: _Sec, lead: bool) -> list[NoteEvent]:
    """Trio / swing piano. Leading: the tune in the right hand (embellished
    on a restatement) over left-hand shells on each change. Comping: rootless
    voicings in a Charleston rhythm (calmer: one held chord per change)."""
    out: list[NoteEvent] = []
    prev = None
    if lead:
        for c in sec.chords:
            v = _jazz_voicing(c, prev, 48, min(66, _below_melody(sec, c.start, 66)))
            prev = v
            dur = (sec.total - c.start) if (sec.hold_from is not None and c.start >= sec.hold_from) else c.dur
            for i, p in enumerate(v[:3]):
                sec.note(out, p, c.start, dur, 50, ms=8.0, jitter=3.0, legato=0.96, delay=0.012 * i)
        return out
    b = sec.beats
    for c in sec.chords:
        v = _jazz_voicing(c, prev, 50, 74)
        prev = v
        held = sec.hold_from is not None and c.start >= sec.hold_from - 1e-6
        if sec.calm or held or sec.kind in ("intro", "interlude"):
            hits = [(c.start, (sec.total - c.start) if held else c.dur, 54)]
        elif b == 3:
            hits = [(bt + 1, 1.5, 50) for bt in np.arange(c.start, c.end - 1e-6, 3.0)]   # waltz: 2 and 3
        else:
            hits = []
            for bt in np.arange(c.start, c.end - 1e-6, 4.0 if c.dur >= 4 else c.dur):
                hits.append((bt, 1.2, 56))
                if bt + 1.5 < c.end:
                    hits.append((bt + 1.5, 0.5, 48))                                # Charleston
        for st, d, vel in hits:
            for i, p in enumerate(v):
                sec.note(out, p, st, d, vel, ms=8.0, jitter=3.0, legato=0.9, delay=0.008 * i)
    return out


def _piano_ballad(sec: _Sec, lead: bool) -> list[NoteEvent]:
    """Soft piano: rolled chords (left-hand root and fifth, right-hand
    chord), flowing 8ths in fuller passes; the tune on top when leading."""
    out: list[NoteEvent] = []
    prev = None
    b = sec.beats
    flowing = sec.kind in ("pass2", "final", "var") and not sec.calm
    for c in sec.chords:
        held = sec.hold_from is not None and c.start >= sec.hold_from - 1e-6
        dur = (sec.total - c.start) if held else c.dur
        root = c.root + 36
        while root < 36:
            root += 12
        top = min(74 if not lead else 70, _below_melody(sec, c.start, 74))
        v = _voice_near(chord_pcs(c.root, c.quality), 55, max(64, top), 62, prev, 3)
        prev = v
        sec.note(out, root, c.start, dur, 56, ms=6.0, legato=1.0)
        if flowing and not held and not lead:
            pattern = [0, 1, 2, 1, 2, 1, 2, 1] if b == 4 else [0, 1, 2, 1, 2, 1]
            for bt in np.arange(c.start, c.end - 1e-6, b):
                for i, idx in enumerate(pattern):
                    step = bt + i * 0.5
                    if step >= c.end - 1e-6:
                        break
                    pool = [root + 7, root + 12] + v
                    sec.note(out, pool[min(idx + (i % 3), len(pool) - 1)], step, 0.5, 46, ms=6.0, legato=1.6)
        else:
            for i, p in enumerate(v):
                sec.note(out, p, c.start, dur, 50, ms=6.0, legato=1.0, delay=0.03 + 0.02 * i)
    return out


def _arpeggio(sec: _Sec, *, lo: int = 48, hi: int = 79, vel: float = 52, pattern: str = "harp") -> list[NoteEvent]:
    """Harp / guitar arpeggios: a rising, ringing figure through each chord
    (harp), or a fingerpicked pattern with the bass on the beat (guitar)."""
    out: list[NoteEvent] = []
    b = sec.beats
    for c in sec.chords:
        held = sec.hold_from is not None and c.start >= sec.hold_from - 1e-6
        pcs = chord_pcs(c.root, c.quality)
        bass = c.root + 36
        while bass < lo:
            bass += 12
        up = [p for p in range(bass, hi + 1) if p % 12 in pcs]
        if held:
            for i, p in enumerate(up[:6]):                                  # one soft roll to end
                sec.note(out, p, c.start, sec.total - c.start, vel * 0.9, ms=4.0, legato=1.0, delay=0.06 * i)
            continue
        if pattern == "harp":
            notes = up[:6] if b == 3 else up[:8]
            for bt in np.arange(c.start, c.end - 1e-6, b):
                for i, p in enumerate(notes):
                    st = bt + i * 0.5
                    if st >= c.end - 1e-6:
                        break
                    sec.note(out, p, st, 1.5, vel - 4 * (i % 2), ms=4.0, legato=1.0)
        else:
            treble = [p for p in up if p >= bass + 10][:3] or up[1:4]
            figure = ([0, 2, 1, 2, 0, 2, 1, 2] if b == 4 else [0, 2, 1, 2, 1, 2])
            for bt in np.arange(c.start, c.end - 1e-6, b):
                for i, f in enumerate(figure):
                    st = bt + i * 0.5
                    if st >= c.end - 1e-6:
                        break
                    if f == 0:
                        p = bass if (i // 4) % 2 == 0 or b == 3 else bass + 7
                        sec.note(out, p, st, 1.0, vel + 4, ms=5.0, legato=1.4)
                    else:
                        p = treble[(i + f) % len(treble)]
                        sec.note(out, p, st, 0.5, vel - 6, ms=5.0, legato=1.8)
    return out


def _strum(sec: _Sec, *, vel: float = 48) -> list[NoteEvent]:
    """Soft acoustic strums: down on the beat, up on the 'and' (lighter)."""
    out: list[NoteEvent] = []
    b = sec.beats
    pattern = [(0, 1.0), (1, .8), (1.5, .55), (2.5, .55), (3, .8), (3.5, .55)] if b == 4 else \
        [(0, 1.0), (1, .7), (2, .7)]
    for c in sec.chords:
        pcs = chord_pcs(c.root, c.quality)
        shape = [p for p in range(c.root + 40 if c.root + 40 >= 40 else c.root + 52, 72) if p % 12 in pcs][:5]
        held = sec.hold_from is not None and c.start >= sec.hold_from - 1e-6
        if held:
            for i, p in enumerate(shape):
                sec.note(out, p, c.start, sec.total - c.start, vel, ms=3.0, legato=1.0, delay=0.02 * i)
            continue
        for bt in np.arange(c.start, c.end - 1e-6, b):
            for off, f in pattern:
                st = bt + off
                if st >= c.end - 1e-6:
                    break
                order = shape if off == int(off) else list(reversed(shape[-3:]))
                for i, p in enumerate(order):
                    sec.note(out, p, st, 0.5, vel * f, ms=3.0, jitter=3.0, legato=1.2, delay=0.012 * i)
    return out


def _choir(sec: _Sec, lead: bool) -> list[NoteEvent]:
    """Choir 'aahs'. Leading: a chorale, the tune on top with three voices
    under it changing with the harmony. Otherwise a soft sustained pad."""
    if not lead:
        return _pad(sec, lo=55, hi=74, vel=48, count=3, swell=True)
    out: list[NoteEvent] = []
    prev = None
    for c in sec.chords:
        top = _below_melody(sec, c.start, 72)
        v = _voice_near(chord_pcs(c.root, c.quality), 48, max(57, top), 58, prev, 3)
        prev = v
        dur = (sec.total - c.start) if (sec.hold_from is not None and c.start >= sec.hold_from) else c.dur
        for p in v:
            sec.note(out, p, c.start, dur, 58, ms=12.0, jitter=3.0, legato=1.02)
    return out


def _organ(sec: _Sec, lead: bool) -> tuple[list[NoteEvent], list[NoteEvent]]:
    """Quiet pipe organ: hymn chords (the tune on top when leading) and a
    pedal line on the roots. Returns (manual, pedal)."""
    manual = _pad(sec, lo=50, hi=72 if lead else 76, vel=50, count=3)
    pedal = _bass_line(sec, "root", vel=56, lo=31, hi=48)
    return manual, pedal


def _brass_pad(sec: _Sec, *, vel: float = 46) -> list[NoteEvent]:
    """Muted trumpets: close, soft voicings held on the changes (3rd, 7th,
    9th), entering on phrase starts."""
    return _pad(sec, lo=58, hi=77, vel=vel, count=3, jazz=True)


def _sax_section(sec: _Sec, inst: str, lead: bool) -> list[NoteEvent]:
    if lead:
        return []
    if sec.kind == "final" and inst == "sax_tenor":
        return _harmony_voice(sec, inst, below=1, vel=62)      # soli: tenor a 3rd-6th under the alto
    if sec.kind in ("pass2", "var") and not sec.calm:
        return _pad(sec, lo=55 if inst == "sax_tenor" else 60, hi=72 if inst == "sax_tenor" else 79,
                    vel=44, count=2, jazz=True)
    return []


def _strings(sec: _Sec, lead: bool) -> list[NoteEvent]:
    """String section: the tune (violins, cellos an octave below in the
    final pass) or a warm pad that swells across fuller passes."""
    out: list[NoteEvent] = []
    if lead:
        return _pad(sec, lo=43, hi=64, vel=50, count=3)
    hi = 74 if sec.warm else 79
    swell = sec.kind in ("pass2", "final")
    out += _pad(sec, lo=43, hi=hi, vel=48 if sec.kind in ("pass1", "intro") else 54, count=4, swell=swell)
    if sec.style in ("orchestral", "choir") and not any(i in _BASSES or i == "cello" for i in sec.info.get("band", ())):
        out += _bass_line(sec, "root", vel=50, lo=36, hi=47)          # the cellos' low root: warmth underneath
    return out


# ---------------------------------------------------------------------------
# Percussion (recorded kits only)
# ---------------------------------------------------------------------------

def _swing_kit(sec: _Sec, brushes: bool) -> list[NoteEvent]:
    """Swing time, quietly: ride 'ding, ding-a', hi-hat foot on 2 and 4,
    a feathered kick; or brushes: taps on 2 and 4 with soft swung ghosts.
    No fills, a soft crash only where the final pass starts."""
    out: list[NoteEvent] = []
    b = sec.beats
    if sec.kind == "intro":
        return out
    for bar in range(sec.ctx.bar_count):
        t0 = bar * b
        held = sec.hold_from is not None and t0 >= sec.hold_from - 1e-6
        if held:
            if t0 == sec.hold_from:
                sec.note(out, RIDE if not brushes else CRASH, t0, 4, 40, ms=3.0)
                sec.note(out, KICK, t0, 1, 34, ms=3.0)
            continue
        if brushes:
            for beat in range(b):
                if (b == 4 and beat in (1, 3)) or (b == 3 and beat in (1, 2)):
                    sec.note(out, SNARE, t0 + beat, 0.5, 44, ms=4.0, jitter=3.0)
                else:
                    sec.note(out, SNARE, t0 + beat, 0.5, 30, ms=6.0, jitter=3.0)
                if beat in (1, 3) and b == 4 or (b == 3 and beat == 2):
                    sec.note(out, SNARE, t0 + beat + 0.5, 0.25, 24, ms=6.0, jitter=2.0)
                if (b == 4 and beat in (1, 3)) or (b == 3 and beat in (1, 2)):
                    sec.note(out, PEDAL_HAT, t0 + beat, 0.5, 34, ms=4.0)
            sec.note(out, KICK, t0, 1, 28, ms=4.0)
            continue
        ride = [(0, 52), (1, 46), (1.5, 34), (2, 48), (3, 46), (3.5, 34)] if b == 4 else \
            [(0, 52), (1, 44), (1.5, 32), (2, 44)]
        for off, v in ride:
            sec.note(out, RIDE, t0 + off, 1, v, ms=4.0, jitter=3.0)
        for beat in ((1, 3) if b == 4 else (1, 2)):
            sec.note(out, PEDAL_HAT, t0 + beat, 0.5, 40, ms=4.0)
        for beat in range(b):
            sec.note(out, KICK, t0 + beat, 0.5, 24, ms=6.0, jitter=2.0)      # feathered
        if sec.kind != "pass1" and bar % 4 == 3 and not sec.calm:
            sec.note(out, SNARE, t0 + b - 0.5, 0.25, 30, ms=5.0)             # one ghost into the phrase
    if sec.kind == "final" and not brushes:
        sec.note(out, CRASH, 0, 4, 46, ms=3.0)
    return out


def _pop_kit(sec: _Sec, brushes: bool) -> list[NoteEvent]:
    """A soft pop kit: cross-stick in the first pass, a light snare after,
    8th hats, kick on 1 and 3. A crash only where the final pass starts."""
    out: list[NoteEvent] = []
    b = sec.beats
    if sec.kind in ("intro",):
        return out
    for bar in range(sec.ctx.bar_count):
        t0 = bar * b
        held = sec.hold_from is not None and t0 >= sec.hold_from - 1e-6
        if held:
            if t0 == sec.hold_from:
                sec.note(out, CRASH, t0, 4, 44, ms=3.0)
                sec.note(out, KICK, t0, 1, 50, ms=3.0)
            continue
        if sec.kind == "interlude":
            sec.note(out, KICK, t0, 1, 44, ms=4.0)
            continue
        back = STICK if sec.kind == "pass1" or sec.calm else SNARE
        for i in range(b * 2):
            sec.note(out, CLOSED_HAT, t0 + i * 0.5, 0.5, (46 if i % 2 == 0 else 34), ms=4.0, jitter=3.0)
        for beat in ((1, 3) if b == 4 else (1, 2)):
            sec.note(out, back, t0 + beat, 0.5, 56 if back == SNARE else 50, ms=4.0, jitter=3.0)
        for beat in ((0, 2) if b == 4 else (0,)):
            sec.note(out, KICK, t0 + beat, 0.5, 58, ms=4.0, jitter=3.0)
        if b == 4 and bar % 2 == 1 and sec.kind != "pass1":
            sec.note(out, KICK, t0 + 2.5, 0.5, 44, ms=4.0)
    if sec.kind == "final":
        sec.note(out, CRASH, 0, 4, 48, ms=3.0)
    if brushes:
        from .funk_fusion import _brushify
        out = _brushify(out, sec.clock)
    return out


def _sleigh(sec: _Sec) -> list[NoteEvent]:
    """Recorded sleigh bells (VCSL), gentle. Keys: 60 hit, 61 loud hit,
    62 shake, 63 long shake. Lively tunes: 8th hits (quarters in the first
    pass), a shake on every 4th bar. Slow tunes: a long, soft shake every
    other bar. Rest in intros and on the held final chord (one last shake)."""
    out: list[NoteEvent] = []
    b = sec.beats
    lively = bool(sec.info.get("lively")) or sec.style == "pop"
    if sec.kind == "intro":
        return out
    for bar in range(sec.ctx.bar_count):
        t0 = bar * b
        if sec.hold_from is not None and t0 >= sec.hold_from - 1e-6:
            if t0 == sec.hold_from:
                sec.note(out, 63, t0, 2, 50, ms=3.0)
            continue
        if sec.kind == "interlude":
            continue
        if lively and not sec.calm:
            step = 1.0 if sec.kind == "pass1" else 0.5
            for i, off in enumerate(np.arange(0, b, step)):
                accent = abs(off - round(off)) < 1e-6
                sec.note(out, 60, t0 + off, 0.5, (52 if off == 0 else 44 if accent else 34), ms=5.0, jitter=3.0)
            if bar % 4 == 3:
                sec.note(out, 62, t0 + b - 1, 1, 40, ms=4.0)
        elif bar % 2 == 0 and sec.kind != "pass1":
            sec.note(out, 63, t0, b, 38, ms=4.0)
    return out


def _shaker(sec: _Sec) -> list[NoteEvent]:
    """Soft shaker 8ths (forward on the beat, back on the 'and')."""
    out: list[NoteEvent] = []
    b = sec.beats
    if sec.kind in ("intro", "interlude") or sec.calm:
        return out
    for bar in range(sec.ctx.bar_count):
        t0 = bar * b
        if sec.hold_from is not None and t0 >= sec.hold_from - 1e-6:
            continue
        for i in range(b * 2):
            sec.note(out, 60 if i % 2 == 0 else 61, t0 + i * 0.5, 0.5, 40 if i % 2 == 0 else 30, ms=6.0, jitter=3.0)
    return out


def _bells(sec: _Sec, inst: str) -> list[NoteEvent]:
    """Glockenspiel / celesta: doubles the tune an octave up on the phrase
    starts of fuller passes (sparkle, not a lead), and the celesta ending
    when asked. Never in 'warmer' arrangements."""
    out: list[NoteEvent] = []
    if sec.warm:
        return out
    end = sec.hold_from is not None and (("celesta_ending" in sec.var and inst == "celesta")
                                         or ("celesta_ending" in sec.var and inst == "glockenspiel"
                                             and "celesta" not in sec.info.get("band", ())))
    if end:
        c = sec.chord_at(sec.hold_from)
        pcs = chord_pcs(c.root, c.quality)
        lo = 72 if inst == "celesta" else 79
        ups = [p for p in range(lo, lo + 20) if p % 12 in pcs][:6]
        for i, p in enumerate(ups):
            sec.note(out, p, sec.hold_from + 0.5 * i, 2.0, 46, ms=3.0, legato=1.0)
        return out
    if sec.calm or sec.kind not in ("pass2", "final"):
        return out
    phrase = float(sec.info.get("phrase_beats") or 4 * sec.beats)
    shift = sec.octave_for(inst)
    for s, d, p in sec.melody:
        if s < 0 or (s % phrase) >= sec.beats * 2 - 1e-6:
            continue
        if (s // phrase) % 2 == 1:
            continue
        sec.note(out, p + shift, s, min(d, 1.0), 48, ms=3.0, jitter=2.0, legato=1.0)
    return out


# ---------------------------------------------------------------------------
# No half-step rubs against the tune
# ---------------------------------------------------------------------------

def _melody_spans(sec: _Sec) -> list[tuple[float, float, int]]:
    """Sounding (start s, end s, pitch) of the tune's held notes (3/4 of a
    beat or longer; quick passing notes may rub, held ones may not),
    including the next section's pickup that sounds at this one's end."""
    out = []
    lead = sec.info.get("lead")
    if lead:
        shift = sec.octave_for(lead)
        out += [(sec.t(s), sec.t(s + d), p + shift) for s, d, p in sec.played() if d >= 0.75]
    tail_lead = sec.info.get("tail_lead")
    if tail_lead:
        shift = sec.octave_for(tail_lead) + int(sec.info.get("tail_shift", 0))
        out += [(sec.t(s), sec.t(s + d), int(p) + sec.shift + shift) for s, d, p in sec.info.get("tail_melody", [])
                if d >= 0.75]
    return out


def _chord_end_s(sec: _Sec, start_s: float) -> float:
    beat_s = 60.0 / sec.ctx.tempo
    c = sec.chord_at(max(0.0, (start_s - sec.t(0)) / beat_s))
    return sec.t(c.end)


def _declash(sec: _Sec, notes: list[NoteEvent], *, keep_roots: bool = False) -> list[NoteEvent]:
    """Move any accompaniment note that would sit a half step (or a major
    7th / minor 9th) from a held melody note to the nearest chord tone that
    doesn't; drop it when there is none. ``keep_roots`` leaves chord roots
    alone (a bass line keeps its roots; only its passing notes move)."""
    if not notes:
        return notes
    # Nothing rings on into the next chord (a harp arpeggio's last notes
    # would sound against the next chord's melody), except the held ending.
    hold_s = sec.t(sec.hold_from) if sec.hold_from is not None else None
    clipped = []
    for n in notes:
        if hold_s is None or n.start < hold_s - 0.05:
            end = min(n.end, _chord_end_s(sec, n.start) + 0.08)
            if end - n.start > 0.03:
                n = NoteEvent(pitch=n.pitch, start=n.start, end=end, velocity=n.velocity)
        clipped.append(n)
    notes = clipped
    spans = _melody_spans(sec)
    if not spans:
        return notes
    beat_s = 60.0 / sec.ctx.tempo
    sec_start = sec.t(0)
    out = []
    for n in notes:
        hits = [p for a, b, p in spans if a < n.end - 0.05 and b > n.start + 0.05
                and min(b, n.end) - max(a, n.start) >= 0.35 * beat_s]
        if not hits or not any((n.pitch - m) % 12 in (1, 11) for m in hits):
            out.append(n)
            continue
        c = sec.chord_at(max(0.0, (n.start - sec_start) / beat_s))
        if keep_roots and n.pitch % 12 == c.root:
            out.append(n)
            continue
        pcs = set(chord_pcs(c.root, c.quality)) | {(c.root + 9) % 12 if c.quality in ("maj", "maj7") else c.root}
        best = None
        for d in (-1, 1, -2, 2, -3, 3, -4, 4, -5, 5):
            q = n.pitch + d
            if q % 12 in pcs and not any((q - m) % 12 in (1, 11) for m in hits) \
                    and not any(h - 2 < q < h + 2 for h in hits):
                best = q
                break
        if best is not None:
            out.append(NoteEvent(pitch=best, start=n.start, end=n.end, velocity=n.velocity))
    return out


# ---------------------------------------------------------------------------
# Dispatch: one technique per instrument
# ---------------------------------------------------------------------------

def _emit_named(midi, notes: list[NoteEvent], name: str, program: int, is_drum: bool = False) -> None:
    if not notes:
        return
    for track in midi.tracks:
        if track.name == name and track.is_drum == is_drum:
            track.notes.extend(notes)
            return
    midi.add_notes(notes, track_name=name, program=program, is_drum=is_drum)


# How each instrument states the tune: (velocity, legato, embellish on restatements).
_MELODY_STYLE = {
    "piano": (76, 0.92, True), "glockenspiel": (58, 0.6, False), "celesta": (60, 0.7, False),
    "nylon_guitar": (70, 0.9, False), "acoustic_guitar": (70, 0.9, False), "choir": (70, 1.0, False),
    "organ_church": (62, 1.0, False), "string_section": (72, 1.0, False), "sax_tenor": (76, 0.96, True),
    "sax_alto": (76, 0.96, True), "muted_trumpet": (70, 0.95, True), "french_horn": (70, 0.98, False),
    "cello": (70, 1.0, False), "synth_lead": (78, 0.97, True), "flute": (72, 0.97, False),
    "clarinet": (72, 0.97, False), "oboe": (70, 0.97, False),
}


def _emit_melody(midi, ctx: TechniqueContext, sec: _Sec, inst: str, guide: bool = False) -> None:
    """The tune, on its own "<instrument> Melody" track (so the mix can sit
    it forward of the instrument's own accompaniment). ``guide``: a backing
    track's very quiet guide ("Guide Melody (<instrument>)", levelled well
    under the band by the Christmas mix profile)."""
    vel, legato, _emb = _MELODY_STYLE.get(inst, (72, 0.96, False))
    if sec.kind == "final":
        vel += 4
    if guide:
        vel = vel * 0.7
    notes = _melody(sec, inst, vel=vel, legato=legato,
                    double_8vb=(inst == "string_section" and sec.final and not sec.warm))
    label = getattr(ctx.instrument_obj, "label", None) or inst.replace("_", " ").title()
    program = getattr(ctx.instrument_obj, "program", 0)
    if sec.strings_end and sec.kind == "outro" and inst != "string_section" and sec.hold_from:
        cut = sec.t(sec.hold_from)
        notes = [NoteEvent(n.pitch, n.start, min(n.end, cut + 0.3), n.velocity) for n in notes if n.start < cut - 0.05]
    _emit_named(midi, notes, f"Guide Melody ({label})" if guide else f"{label} Melody", program)


COUNT_IN_TRACK = "Count-in"
COUNT_IN_KEY = CLOSED_HAT                  # a recorded closed hi-hat (GM key 42), never a synth click


def _count_in(sec: _Sec) -> list[NoteEvent]:
    """One bar of closed hi-hat on every beat, the first a little louder,
    exactly on the beat (no humanising: it's the singers' cue)."""
    out = []
    for b in range(sec.beats):
        s = sec.t(float(b))
        out.append(NoteEvent(pitch=COUNT_IN_KEY, start=max(0.0, s), end=max(0.0, s) + 0.12,
                             velocity=84 if b == 0 else 70))
    return out


def _plays(sec: _Sec, inst: str) -> bool:
    """Who sits out where: drums and bass wait for the first pass, colour
    instruments come in for fuller passes; the interlude is quiet."""
    k = sec.kind
    if k == "count_in":
        return inst == sec.info.get("count_in_by")
    if k == "intro":
        intro = {"swing": ("piano",), "trio": ("piano",), "orchestral": ("string_section", "harp", sec.info["lead"]),
                 "fireside": ("nylon_guitar", "acoustic_guitar"), "choir": ("organ_church", sec.info["lead"]),
                 "pop": ("piano",)}[sec.style]
        return inst in intro
    if k == "interlude":
        return inst not in ("glockenspiel", "celesta", "sleigh_bells", "shaker") or sec.style == "pop"
    if k == "pass1":
        return inst not in ("french_horn", "glockenspiel", "celesta", "choir") or inst == sec.info.get("lead")
    if inst == "choir" and sec.style != "choir":
        return "choir_pad" in sec.var and k in ("final", "outro")
    return True


_BASSES = ("upright_bass", "electric_bass", "contrabass", "bassoon")


def play(midi, ctx: TechniqueContext, inst: str) -> None:
    sec = _Sec(ctx)
    if not sec.info:
        sec.info = {"kind": "pass1", "lead": inst, "style": sec.style}
    if not _plays(sec, inst):
        return
    lead = sec.info.get("lead") == inst
    style = sec.style
    k = sec.kind
    if k == "count_in":
        _emit_named(midi, _count_in(sec), COUNT_IN_TRACK, 0, is_drum=True)
        return
    if lead:
        if not sec.info.get("backing"):
            _emit_melody(midi, ctx, sec, inst)
        elif sec.info.get("guide"):
            _emit_melody(midi, ctx, sec, inst, guide=True)
        # A backing track has no lead: the instrument plays its part instead.
        lead = not sec.info.get("backing")
    notes: list[NoteEvent] = []
    if inst == "piano":
        notes = _piano_trio(sec, lead) if style in JAZZ else _piano_ballad(sec, lead)
    elif inst in _BASSES:
        if style in JAZZ:
            mode = "two" if (k in ("pass1", "interlude") or sec.calm) else "walk"
            mode = "root" if k == "intro" else mode
        elif style == "pop":
            mode = "root" if (k in ("pass1", "interlude") or sec.calm) else "pop"
        else:
            mode = "root"
        notes = _bass_line(sec, mode, vel=74 if style in JAZZ else 66)
    elif inst == "drum_kit":
        brushes = "brushes" in sec.var or style == "trio"
        notes = _swing_kit(sec, brushes) if style in JAZZ else _pop_kit(sec, brushes)
        if brushes:
            _emit_named(midi, notes, BRUSH_TRACK, BRUSH_KIT, is_drum=True)
            return
        _emit(midi, ctx, notes, name="Drums", program=0, is_drum=True)
        return
    elif inst == "sleigh_bells":
        notes = _sleigh(sec)
    elif inst == "shaker":
        notes = _shaker(sec)
    elif inst in ("glockenspiel", "celesta"):
        notes = [] if lead else _bells(sec, inst)
    elif inst == "harp":
        notes = _arpeggio(sec, lo=43, hi=84, vel=48 if k != "pass1" else 44, pattern="harp")
    elif inst in ("nylon_guitar", "acoustic_guitar"):
        if lead:
            notes = _arpeggio(sec, lo=40, hi=64, vel=40, pattern="pick")
        elif style == "pop" and inst == "acoustic_guitar":
            notes = _strum(sec, vel=42 if k == "pass1" else 48)
        else:
            notes = _arpeggio(sec, lo=40, hi=72, vel=46, pattern="pick")
    elif inst == "choir":
        notes = _choir(sec, lead)
    elif inst == "organ_church":
        manual, pedal = _organ(sec, lead)
        _emit(midi, ctx, _declash(sec, manual), name="Organ", program=19)
        _emit_named(midi, _declash(sec, pedal, keep_roots=True), "Organ Pedal Bass", 19)
        return
    elif inst == "string_section":
        notes = _strings(sec, lead)
    elif inst in ("sax_alto", "sax_tenor"):
        notes = _sax_section(sec, inst, lead)
    elif inst == "muted_trumpet":
        notes = [] if lead else \
            (_brass_pad(sec) if k in ("pass2", "final", "outro", "var") and sec.hold_from is None else [])
    elif inst == "french_horn":
        if lead:
            notes = []
        elif k == "outro" and sec.strings_end:
            notes = []
        elif inst in _COUNTER.get(style, ()) and not sec.calm and k in ("pass2", "final", "var"):
            notes = _counter(sec, inst, vel=54)
        else:
            notes = _pad(sec, lo=53, hi=67, vel=44, count=2) if k != "pass1" else []
    elif inst in ("cello",):
        if lead:
            notes = []
        elif inst in _COUNTER.get(style, ()) and not sec.calm and k in ("final", "var"):
            notes = _counter(sec, inst, vel=56)
        else:
            notes = _bass_line(sec, "root", vel=54, lo=36, hi=55)
    elif inst in ("flute", "clarinet", "oboe", "violin", "trumpet", "synth_lead", "sax_baritone", "trombone"):
        if lead:
            notes = []
        elif inst in _COUNTER.get(style, ()) and not sec.calm and k in ("pass2", "final", "var"):
            notes = _counter(sec, inst, vel=52)
        elif k in ("final", "outro") and inst in ("flute", "clarinet", "oboe") and not sec.calm:
            notes = _pad(sec, lo=62, hi=81, vel=40, count=1)
    else:
        # Any other instrument in the band: by its role.
        from src.composition.instruments import INSTRUMENT_REGISTRY
        role = getattr(INSTRUMENT_REGISTRY.get(inst), "role", "chords")
        if lead:
            notes = []
        elif role == "bass":
            notes = _bass_line(sec, "root")
        elif role == "chords":
            notes = _pad(sec, vel=46)
        elif role == "melody" and k in ("pass2", "final"):
            notes = _counter(sec, inst, vel=50)
    # The final chord belongs to the strings when asked (no brass or reeds).
    if sec.strings_end and k == "outro" and inst not in ("string_section", "harp") and sec.hold_from:
        cut = sec.t(sec.hold_from)
        notes = [n for n in notes if n.start < cut - 0.05]
        notes = [NoteEvent(n.pitch, n.start, min(n.end, cut + 0.3), n.velocity) for n in notes]
    if notes and inst not in ("sleigh_bells", "shaker"):
        notes = _declash(sec, notes, keep_roots=inst in _BASSES or inst == "cello")
    if notes:
        prog = {"sleigh_bells": 112, "shaker": 113}.get(inst, 0)
        _emit(midi, ctx, notes, name=inst.replace("_", " ").title(), program=prog)


# Instruments the Christmas styles arrange for (others fall to their role).
_INSTRUMENTS = ("piano", "upright_bass", "electric_bass", "drum_kit", "sleigh_bells", "shaker", "glockenspiel",
                "celesta", "harp", "nylon_guitar", "acoustic_guitar", "choir", "organ_church", "string_section",
                "sax_alto", "sax_tenor", "muted_trumpet", "french_horn", "cello", "flute", "clarinet", "oboe",
                "violin", "trumpet", "synth_lead", "contrabass", "bassoon", "sax_baritone", "trombone")

for _inst in _INSTRUMENTS:
    _register(name=f"christmas_{_inst}", label=f"Christmas {_inst.replace('_', ' ')}",
              description="Christmas arrangement part for this instrument (melody, countermelody, pad, "
                          "comping, bass or percussion by pass), read from the song plan.",
              instruments=(_inst,), roles=ALL_ROLES, weight=4, tags=(TAG,),
              apply=lambda midi, ctx, _i=_inst: play(midi, ctx, _i))
for _role in ("chords", "bass", "melody", "drums"):
    _register(name=f"christmas_role_{_role}", label=f"Christmas {_role}",
              description="Christmas part for any instrument in this role.",
              instruments=(_role,), roles=ALL_ROLES, weight=4, tags=(TAG,),
              apply=lambda midi, ctx, _r=_role: play(midi, ctx, getattr(ctx.instrument_obj, "id", _r) or _r))
