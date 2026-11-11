"""Public-domain Christmas carol melodies, encoded as note data.

Every tune here is in the US public domain: melody AND words were published
before 1929 (most long before). The note data was written out for this
project from the traditional tunes; the arrangements built on it
(src/composition/christmas.py) are original. Carol of the Bells is
Leontovych's 1916 "Shchedryk" melody only (instrumental: the familiar
English words are a later, copyrighted lyric).

``DENYLIST`` names modern, copyrighted Christmas songs that must never be
added here; a unit test fails if one appears as a tune id or title.

Format: each tune is written in C major (or A minor) as space-separated
``NOTE:beats`` tokens (``R`` is a rest, beats are quarter notes, ``|`` bar
lines are for reading and are checked by the tests). The melody starts with
its pickup (``pickup`` beats before the first downbeat); ``chords`` start on
the first downbeat as ``SYMBOL:beats`` roman numerals in the tune's scale
(natural minor for minor tunes, with an explicit major ``V``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

# Modern, copyrighted Christmas songs (title words, lowercase). Never add a
# tune whose id or title matches one of these.
DENYLIST: tuple[str, ...] = (
    "all i want for christmas",
    "let it snow",
    "have yourself a merry little christmas",
    "white christmas",
    "rudolph",
    "frosty",
    "sleigh ride",
    "christmas time is here",
    "the christmas song",
    "chestnuts roasting",
    "winter wonderland",
    "it's beginning to look a lot like christmas",
    "beginning to look",
    "holly jolly",
    "rockin' around the christmas tree",
    "rocking around the christmas tree",
    "jingle bell rock",
    "silver bells",
    "santa claus is comin",
    "santa claus is coming",
    "here comes santa",
    "last christmas",
    "feliz navidad",
    "do you hear what i hear",
    "little drummer boy",
    "mary, did you know",
    "mary did you know",
    "blue christmas",
    "i'll be home for christmas",
    "home for christmas",
    "it's the most wonderful time",
    "most wonderful time of the year",
    "you're a mean one",
    "grinch",
    "wonderful christmastime",
    "happy xmas",
    "do they know it's christmas",
    "underneath the tree",
    "carol of the bells (wilhousky)",
    "hark how the bells",
    "christmas canon",
    "feliz",
    "baby it's cold outside",
    "marshmallow world",
    "a holly jolly christmas",
    "there's no place like home for the holidays",
    "home for the holidays",
    "santa baby",
)

_NOTE = re.compile(r"^([A-G])([#b]?)(-?\d)$")
_PC = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


@dataclass(frozen=True)
class TuneNote:
    start: float        # beats from the first downbeat (pickup notes are negative)
    dur: float          # beats
    pitch: int          # MIDI note as written (C major / A minor)


@dataclass(frozen=True)
class TuneChord:
    start: float        # beats from the first downbeat
    dur: float
    symbol: str         # roman numeral in the tune's scale


@dataclass(frozen=True)
class Tune:
    id: str
    title: str
    source: str                  # provenance (why it's public domain)
    beats: int                   # beats per bar (3 or 4)
    pickup: float                # beats before the first downbeat
    scale: str                   # "major" or "minor" (written in C / A; V stays major in minor tunes)
    melody: tuple[TuneNote, ...]
    chords: tuple[TuneChord, ...]
    phrase_bars: int = 4         # bars per phrase (arrangement breathing)
    tempo: tuple[float, float] = (72.0, 120.0)   # comfortable BPM range
    lively: bool = False         # a bright, bouncing tune (Jingle Bells), not a hymn

    @property
    def bars(self) -> int:
        return int(round(sum(c.dur for c in self.chords) / self.beats))

    @property
    def tonic_pc(self) -> int:
        return 9 if "minor" in self.scale else 0

    def notes_between(self, start_beat: float, end_beat: float) -> list[TuneNote]:
        return [n for n in self.melody if start_beat - 1e-6 <= n.start < end_beat - 1e-6]

    def chord_at(self, beat: float) -> TuneChord:
        for c in self.chords:
            if c.start - 1e-6 <= beat < c.start + c.dur - 1e-6:
                return c
        return self.chords[-1] if beat >= 0 else self.chords[0]


def note_to_midi(token: str) -> int:
    m = _NOTE.match(token)
    if not m:
        raise ValueError(f"bad note {token!r}")
    acc = {"#": 1, "b": -1, "": 0}[m.group(2)]
    return 12 * (int(m.group(3)) + 1) + _PC[m.group(1)] + acc


def parse_melody(text: str, pickup: float) -> tuple[TuneNote, ...]:
    out: list[TuneNote] = []
    t = -pickup
    for tok in text.replace("|", " ").split():
        name, dur = tok.split(":")
        d = float(dur)
        if name != "R":
            out.append(TuneNote(start=round(t, 4), dur=d, pitch=note_to_midi(name)))
        t += d
    return tuple(out)


def parse_chords(text: str) -> tuple[TuneChord, ...]:
    out: list[TuneChord] = []
    t = 0.0
    for tok in text.replace("|", " ").split():
        sym, dur = tok.rsplit(":", 1)
        out.append(TuneChord(start=round(t, 4), dur=float(dur), symbol=sym))
        t += float(dur)
    return tuple(out)


def bar_sums(text: str) -> list[float]:
    """Beats in each ``|``-separated bar of a melody or chord string (tests)."""
    return [sum(float(tok.rsplit(":", 1)[1]) for tok in bar.split()) for bar in text.split("|") if bar.strip()]


# ---------------------------------------------------------------------------
# The carols (melody text, chords text). All written in C major / A minor.
# ---------------------------------------------------------------------------

_RAW: dict[str, dict] = {
    "silent_night": dict(
        title="Silent Night",
        source="Franz Xaver Gruber, 1818 (words Joseph Mohr). Public domain.",
        beats=3, pickup=0, scale="major", tempo=(60, 76),
        melody="G4:1.5 A4:.5 G4:1 | E4:3 | G4:1.5 A4:.5 G4:1 | E4:3 | D5:2 D5:1 | B4:3 | C5:2 C5:1 | G4:3 | "
               "A4:2 A4:1 | C5:1.5 B4:.5 A4:1 | G4:1.5 A4:.5 G4:1 | E4:3 | A4:2 A4:1 | C5:1.5 B4:.5 A4:1 | "
               "G4:1.5 A4:.5 G4:1 | E4:3 | D5:2 D5:1 | F5:1.5 D5:.5 B4:1 | C5:3 | E5:3 | "
               "C5:1.5 G4:.5 E4:1 | G4:1.5 F4:.5 D4:1 | C4:3 | C4:3",
        chords="I:3 | I:3 | I:3 | I:3 | V7:3 | V7:3 | I:3 | I:3 | IV:3 | IV:3 | I:3 | I:3 | IV:3 | IV:3 | "
               "I:3 | I:3 | V7:3 | V7:3 | I:3 | I:3 | I:3 | V7:3 | I:3 | I:3",
    ),
    "jingle_bells": dict(
        title="Jingle Bells",
        source="James Lord Pierpont, 1857. Public domain.",
        beats=4, pickup=0, scale="major", tempo=(112, 160), lively=True,
        melody="G4:1 E5:1 D5:1 C5:1 | G4:3 G4:.5 G4:.5 | G4:1 E5:1 D5:1 C5:1 | A4:4 | "
               "A4:1 F5:1 E5:1 D5:1 | B4:4 | G5:1 G5:1 F5:1 D5:1 | E5:4 | "
               "G4:1 E5:1 D5:1 C5:1 | G4:4 | G4:1 E5:1 D5:1 C5:1 | A4:3 A4:1 | "
               "A4:1 F5:1 E5:1 D5:1 | G5:1 G5:1 G5:1 G5:1 | A5:1 G5:1 F5:1 D5:1 | C5:4 | "
               "E5:1 E5:1 E5:2 | E5:1 E5:1 E5:2 | E5:1 G5:1 C5:1.5 D5:.5 | E5:4 | "
               "F5:1 F5:1 F5:1.5 F5:.5 | F5:1 E5:1 E5:1 E5:.5 E5:.5 | E5:1 D5:1 D5:1 E5:1 | D5:2 G5:2 | "
               "E5:1 E5:1 E5:2 | E5:1 E5:1 E5:2 | E5:1 G5:1 C5:1.5 D5:.5 | E5:4 | "
               "F5:1 F5:1 F5:1.5 F5:.5 | F5:1 E5:1 E5:1 E5:.5 E5:.5 | G5:1 G5:1 F5:1 D5:1 | C5:4",
        chords="I:4 | I:4 | I:4 | IV:4 | ii:4 | V7:4 | V7:4 | I:4 | I:4 | I:4 | I:4 | IV:4 | ii:4 | V7:4 | "
               "V7:4 | I:4 | I:4 | I:4 | I:4 | I:4 | IV:4 | IV:1 I:3 | II7:4 | V7:4 | I:4 | I:4 | I:4 | I:4 | "
               "IV:4 | IV:1 I:3 | V7:4 | I:4",
    ),
    "deck_the_halls": dict(
        title="Deck the Halls",
        source="Traditional Welsh (Nos Galan); English words Thomas Oliphant, 1862. Public domain.",
        beats=4, pickup=0, scale="major", tempo=(96, 132), lively=True,
        melody="G4:1.5 F4:.5 E4:1 D4:1 | C4:1 D4:1 E4:1 C4:1 | D4:.5 E4:.5 F4:.5 D4:.5 E4:1.5 D4:.5 | "
               "C4:1 B3:1 C4:2 | G4:1.5 F4:.5 E4:1 D4:1 | C4:1 D4:1 E4:1 C4:1 | "
               "D4:.5 E4:.5 F4:.5 D4:.5 E4:1.5 D4:.5 | C4:1 B3:1 C4:2 | D4:1.5 E4:.5 F4:1 D4:1 | "
               "E4:1.5 F4:.5 G4:1 D4:1 | E4:.5 F#4:.5 G4:1 A4:.5 B4:.5 C5:1 | B4:1 A4:1 G4:2 | "
               "G4:1.5 F4:.5 E4:1 D4:1 | C4:1 D4:1 E4:1 C4:1 | A4:.5 A4:.5 A4:.5 A4:.5 G4:1.5 F4:.5 | "
               "E4:1 D4:1 C4:2",
        chords="I:4 | I:4 | V7:2 I:2 | I:1 V7:1 I:2 | I:4 | I:4 | V7:2 I:2 | I:1 V7:1 I:2 | V7:4 | I:4 | "
               "II7:2 V:2 | V:4 | I:4 | I:4 | IV:2 V7:2 | I:1 V7:1 I:2",
    ),
    "good_king_wenceslas": dict(
        title="Good King Wenceslas",
        source="Tune 'Tempus adest floridum' (Piae Cantiones, 1582); words John Mason Neale, 1853. "
               "Public domain.",
        beats=4, pickup=0, scale="major", tempo=(84, 112),
        melody="C5:1 C5:1 C5:1 D5:1 | C5:1 C5:1 G4:2 | A4:1 G4:1 A4:1 B4:1 | C5:2 C5:2 | "
               "C5:1 C5:1 C5:1 D5:1 | C5:1 C5:1 G4:2 | A4:1 G4:1 A4:1 B4:1 | C5:2 C5:2 | "
               "G5:1 F5:1 E5:1 D5:1 | E5:1 D5:1 C5:2 | A4:1 G4:1 A4:1 B4:1 | C5:2 C5:2 | "
               "G4:1 G4:1 A4:1 B4:1 | C5:1 C5:1 D5:2 | G5:1 F5:1 E5:1 D5:1 | C5:2 F5:2 | C5:4",
        chords="I:4 | I:2 V:2 | IV:2 V:2 | I:4 | I:4 | I:2 V:2 | IV:2 V:2 | I:4 | V7:2 I:2 | ii:1 V7:1 I:2 | "
               "IV:2 V:2 | I:4 | I:2 V:2 | I:2 V:2 | V7:2 I:2 | I:2 IV:2 | I:4",
    ),
    "joy_to_the_world": dict(
        title="Joy to the World",
        source="Tune 'Antioch', arr. Lowell Mason, 1839; words Isaac Watts, 1719. Public domain.",
        beats=4, pickup=0, scale="major", tempo=(84, 112),
        melody="C5:1 B4:.75 A4:.25 G4:1.5 F4:.5 | E4:1 D4:1 C4:1.5 G4:.5 | A4:1.5 A4:.5 B4:1.5 B4:.5 | "
               "C5:3 C5:1 | C5:.5 B4:.5 A4:.5 G4:.5 G4:.75 F4:.25 E4:1 | C5:.5 C5:.5 B4:.5 A4:.5 G4:.75 F4:.25 E4:1 | "
               "E4:.5 E4:.5 E4:.5 E4:.25 F4:.25 G4:2 | F4:.25 E4:.25 D4:.5 D4:.5 D4:.5 D4:.25 E4:.25 F4:1.5 | "
               "E4:.25 D4:.25 C4:.5 C5:1 A4:.5 G4:.75 F4:.25 E4:.5 | F4:.5 E4:1 D4:1 C4:1.5",
        chords="I:2 IV:1 V7:1 | I:1 V7:1 I:2 | IV:2 V:2 | I:4 | I:2 V7:1 I:1 | I:2 V7:1 I:1 | I:4 | V7:4 | "
               "I:2 IV:1 I:1 | IV:.5 I:1 V7:1 I:1.5",
    ),
    "angels_we_have_heard": dict(
        title="Angels We Have Heard on High",
        source="French carol 'Les Anges dans nos campagnes' (1855 arr.); English words James Chadwick, 1862. "
               "Public domain.",
        beats=4, pickup=0, scale="major", tempo=(88, 116),
        melody="E5:1 E5:1 E5:1 G5:1 | G5:1.5 F5:.5 E5:2 | E5:1 D5:1 E5:1 G5:1 | E5:1.5 D5:.5 C5:2 | "
               "E5:1 E5:1 E5:1 G5:1 | G5:1.5 F5:.5 E5:2 | E5:1 D5:1 E5:1 G5:1 | E5:1.5 D5:.5 C5:2 | "
               "G5:2 A5:.5 G5:.5 F5:.5 E5:.5 | F5:2 G5:.5 F5:.5 E5:.5 D5:.5 | E5:2 F5:.5 E5:.5 D5:.5 C5:.5 | "
               "D5:3 G4:1 | C5:1 D5:1 E5:1 F5:1 | E5:2 D5:2 | C5:4 | "
               "G5:2 A5:.5 G5:.5 F5:.5 E5:.5 | F5:2 G5:.5 F5:.5 E5:.5 D5:.5 | E5:2 F5:.5 E5:.5 D5:.5 C5:.5 | "
               "D5:3 G4:1 | C5:1 D5:1 E5:1 F5:1 | E5:2 D5:2 | C5:4",
        chords="I:4 | V7:2 I:2 | I:2 V:2 | I:1 V7:1 I:2 | I:4 | V7:2 I:2 | I:2 V:2 | I:1 V7:1 I:2 | "
               "I:2 vi:2 | ii:2 V:2 | I:2 IV:2 | V:4 | I:2 IV:2 | I:2 V7:2 | I:4 | "
               "I:2 vi:2 | ii:2 V:2 | I:2 IV:2 | V:4 | I:2 IV:2 | I:2 V7:2 | I:4",
    ),
    "what_child_is_this": dict(
        title="What Child Is This (Greensleeves)",
        source="Tune 'Greensleeves' (English, 16th c.); words William Chatterton Dix, 1865. Public domain.",
        beats=3, pickup=1, scale="minor", tempo=(66, 96),
        melody="A4:1 | C5:2 D5:1 | E5:1.5 F5:.5 E5:1 | D5:2 B4:1 | G4:1.5 A4:.5 B4:1 | C5:2 A4:1 | "
               "A4:1.5 G#4:.5 A4:1 | B4:2 G#4:1 | E4:2 A4:1 | C5:2 D5:1 | E5:1.5 F5:.5 E5:1 | D5:2 B4:1 | "
               "G4:1.5 A4:.5 B4:1 | C5:1.5 B4:.5 A4:1 | G#4:1.5 F#4:.5 G#4:1 | A4:3 | A4:3 | "
               "G5:3 | G5:1.5 F#5:.5 E5:1 | D5:2 B4:1 | G4:1.5 A4:.5 B4:1 | C5:2 A4:1 | A4:1.5 G#4:.5 A4:1 | "
               "B4:2 G#4:1 | E4:3 | G5:3 | G5:1.5 F#5:.5 E5:1 | D5:2 B4:1 | G4:1.5 A4:.5 B4:1 | "
               "C5:1.5 B4:.5 A4:1 | G#4:1.5 F#4:.5 G#4:1 | A4:3 | A4:3",
        chords="i:3 | III:3 | VII:3 | v:3 | i:3 | iv:3 | V:3 | V:3 | i:3 | III:3 | VII:3 | v:3 | i:3 | V:3 | "
               "i:3 | i:3 | III:3 | v:3 | VII:3 | v:3 | i:3 | iv:3 | V:3 | V:3 | III:3 | v:3 | VII:3 | v:3 | "
               "i:3 | V:3 | i:3 | i:3",
    ),
    "the_first_noel": dict(
        title="The First Noel",
        source="Traditional English (Cornish), published by William Sandys, 1833. Public domain.",
        beats=3, pickup=1, scale="major", tempo=(72, 100),
        melody="E4:.5 D4:.5 | C4:1.5 D4:.5 E4:.5 F4:.5 | G4:2 A4:.5 B4:.5 | C5:1 B4:1 A4:1 | G4:2 A4:.5 B4:.5 | "
               "C5:1 B4:1 A4:1 | G4:1 A4:1 B4:1 | C5:1 G4:1 F4:1 | E4:2 E4:.5 D4:.5 | "
               "C4:1.5 D4:.5 E4:.5 F4:.5 | G4:2 A4:.5 B4:.5 | C5:1 B4:1 A4:1 | G4:2 A4:.5 B4:.5 | "
               "C5:1 B4:1 A4:1 | G4:1 A4:1 B4:1 | C5:1 G4:1 F4:1 | E4:2 E4:.5 D4:.5 | "
               "C4:1.5 D4:.5 E4:.5 F4:.5 | G4:2 C5:.5 B4:.5 | A4:2 A4:1 | G4:2 A4:.5 B4:.5 | "
               "C5:1 B4:1 A4:1 | G4:1 A4:1 B4:1 | C5:1 G4:1 F4:1 | E4:3",
        chords="I:3 | I:2 V:1 | IV:3 | I:2 V:1 | IV:3 | I:2 V:1 | IV:1 V7:2 | I:3 | I:3 | I:2 V:1 | IV:3 | "
               "I:2 V:1 | IV:3 | I:2 V:1 | IV:1 V7:2 | I:3 | I:3 | I:2 V:1 | IV:3 | I:2 V:1 | IV:3 | I:2 V:1 | "
               "IV:1 V7:2 | I:3",
    ),
    "carol_of_the_bells": dict(
        title="Carol of the Bells (Shchedryk)",
        source="Mykola Leontovych, 'Shchedryk', 1916 (melody only; instrumental). Public domain.",
        beats=3, pickup=0, scale="minor", tempo=(96, 132),
        melody=" | ".join(["C5:1 B4:.5 C5:.5 A4:1"] * 8 + ["E5:1 D5:.5 E5:.5 C5:1"] * 4
                          + ["C5:1 B4:.5 C5:.5 A4:1"] * 4),
        chords="i:3 | i:3 | i:3 | i:3 | VI:3 | VI:3 | iv:3 | iv:3 | i:3 | i:3 | VI:3 | VI:3 | "
               "iv:3 | iv:3 | i:3 | i:3",
    ),
}


class TuneBook:
    """A collection of tunes written in the text format above (the carols
    here, the Thanksgiving hymns in hymns.py): build, look up by id or title,
    list for menus."""

    def __init__(self, raw: dict[str, dict]):
        self._raw = raw
        self.ids: tuple[str, ...] = tuple(raw)
        self._cache: dict[str, Tune] = {}

    def build(self, tune_id: str) -> Tune:
        if tune_id not in self._cache:
            raw = self._raw[tune_id]
            self._cache[tune_id] = Tune(
                id=tune_id, title=raw["title"], source=raw["source"], beats=raw["beats"],
                pickup=float(raw["pickup"]), scale=raw["scale"],
                melody=parse_melody(raw["melody"], float(raw["pickup"])),
                chords=parse_chords(raw["chords"]),
                tempo=tuple(float(x) for x in raw.get("tempo", (72, 120))),
                lively=bool(raw.get("lively", False)),
            )
        return self._cache[tune_id]

    def get(self, tune_id: str) -> Optional[Tune]:
        """The tune ``tune_id`` (also accepts its title, any case), or None."""
        key = (tune_id or "").strip().lower().replace("-", "_").replace(" ", "_")
        if key in self._raw:
            return self.build(key)
        text = (tune_id or "").strip().lower()
        for tid, raw in self._raw.items():
            if text and raw["title"].lower().startswith(text):
                return self.build(tid)
        return None

    def catalog(self) -> dict[str, dict]:
        """Id → title, meter and source, for menus and tools."""
        out = {}
        for tid in self.ids:
            t = self.build(tid)
            out[tid] = {"title": t.title, "meter": f"{t.beats}/4", "bars": t.bars, "source": t.source,
                        "lively": t.lively}
        return out

    def raw_text(self, tune_id: str) -> dict:
        """The encoded strings (tests check bar lengths)."""
        return dict(self._raw[tune_id])


BOOK = TuneBook(_RAW)
CAROLS: tuple[str, ...] = BOOK.ids


def _build(tune_id: str) -> Tune:
    return BOOK.build(tune_id)


def carol(tune_id: str) -> Optional[Tune]:
    """The carol ``tune_id`` (also accepts its title, any case), or None."""
    return BOOK.get(tune_id)


def carol_catalog() -> dict[str, dict]:
    """Id → title, meter and source, for menus and tools."""
    return BOOK.catalog()


def raw_text(tune_id: str) -> dict:
    """The encoded strings (tests check bar lengths)."""
    return BOOK.raw_text(tune_id)
