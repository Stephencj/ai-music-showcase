"""Carol lyrics: public-domain texts in data files, aligned to the tunes.

The texts are not in the code. ``scripts/setup/fetch_carol_lyrics.py``
downloads each carol's public-domain text into ``data/lyrics/<carol>.txt``
(sources and why each is public domain: ``data/lyrics/SOURCES.md``). This
module reads those files, splits every line into syllables (character spans,
so nothing downstream copies the text) and lines the syllables up with the
carol's melody notes (src/composition/carols.py).

File format (``data/lyrics/<carol>.txt``):

- lines starting with ``#`` are comments (source, licence);
- a blank line separates stanzas;
- a stanza whose first line is ``[refrain]`` is the refrain (sung after each
  verse when the tune carries it; the marker line itself isn't sung).

Everything that points into a file uses its physical line numbers (0-based,
``text.splitlines()[line]``) and, for syllables, ``[start, end)`` character
offsets into that line.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Optional

from .carols import Tune, TuneNote

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LYRICS_DIR = PROJECT_ROOT / "data" / "lyrics"
REFRAIN_MARK = "[refrain]"

# Melisma rules: a line may hold at most this many more notes than syllables
# (one syllable over two or three notes) or more syllables than notes (a long
# note split for an extra syllable, as later verses do).
MAX_MELISMAS = 6
MAX_SPLITS = 3

# ---------------------------------------------------------------------------
# Syllables
# ---------------------------------------------------------------------------

_WORD = re.compile(r"[A-Za-zÀ-ɏ][A-Za-zÀ-ɏ'’]*|'[A-Za-z]+")
_VOWELS = set("aeiouyàáâäèéêëìíîïòóôöùúûü")
# Words the rules below count wrongly, by sung syllables.
_SPECIAL = {"deo": 2, "noel": 2, "noël": 2, "fuel": 2, "quiet": 2, "being": 2, "people": 2, "israel": 3,
            "poet": 2, "lion": 2, "ruin": 2, "jewel": 2, "cruel": 2, "doing": 2, "going": 2, "seeing": 2,
            "fleeing": 2, "lowly": 2, "heaven's": 2, "creation": 3, "alleluia": 4, "hallelujah": 4}


def _groups(w: str) -> list[list[int]]:
    """Vowel groups of a lowercase word as [start, end) index pairs."""
    out: list[list[int]] = []
    i = 0
    while i < len(w):
        c = w[i]
        vowel = c in _VOWELS and not (c == "y" and i == 0 and len(w) > 1 and w[1] in _VOWELS)
        if vowel:
            if out and out[-1][1] == i:
                out[-1][1] = i + 1
            else:
                out.append([i, i + 1])
        i += 1
    return out


def _split_hiatus(w: str, groups: list[list[int]]) -> list[list[int]]:
    """Split vowel groups that are two syllables (glo-ri-a, ly-ing)."""
    out = []
    for a, b in groups:
        g = w[a:b]
        cut = None
        for pair in ("ia", "io", "yi", "ae", "iu"):
            k = g.find(pair)
            if k < 0:
                continue
            before = w[a - 1] if a > 0 else ""
            # -tion, -sion, -cious, -tial stay one syllable; qu- glides.
            if pair in ("ia", "io", "iu") and (before in "tcsx" or w[max(0, a - 1):a + 1] == "qu"):
                continue
            cut = a + k + 1
            break
        if cut:
            out += [[a, cut], [cut, b]]
        else:
            out.append([a, b])
    return out


def word_syllables(word: str) -> list[tuple[int, int]]:
    """[start, end) spans of the sung syllables of one word (covering it)."""
    w = word.lower().replace("’", "'")
    n = len(w)
    groups = _split_hiatus(w, _groups(w))
    # An elided vowel (o'er, e'er) is one syllable.
    merged: list[list[int]] = []
    for g in groups:
        if merged and w[merged[-1][1]:g[0]] == "'":
            merged[-1][1] = g[1]
        else:
            merged.append(g)
    groups = merged
    if len(groups) > 1:
        last = groups[-1]
        # Silent final e (come, peace) but not a sung -le (gentle, little).
        if w.endswith("e") and last == [n - 1, n] and not (
                w.endswith("le") and n > 2 and w[-3] not in _VOWELS):
            groups.pop()
        # Silent -es / -ed (comes, loved) unless after a sibilant / t, d.
        elif w.endswith("es") and last == [n - 2, n - 1] and w[-3:-2] not in ("s", "x", "z", "c", "g") \
                and not w.endswith(("ches", "shes")):
            groups.pop()
        elif w.endswith("ed") and last == [n - 2, n - 1] and w[-3:-2] not in ("t", "d"):
            groups.pop()
        elif w.endswith("'d") or w.endswith("'s"):
            pass
    want = _SPECIAL.get(w.strip("'"))
    if want and want != len(groups):
        # Even spans for the few words the rules miss.
        step = n / want
        return [(int(round(i * step)), int(round((i + 1) * step)) if i < want - 1 else n) for i in range(want)]
    if not groups:
        return [(0, n)]
    spans = []
    start = 0
    for k in range(len(groups) - 1):
        end_v, next_v = groups[k][1], groups[k + 1][0]
        cons = next_v - end_v
        if cons <= 1:
            cut = end_v if cons == 1 else next_v
        elif k == len(groups) - 2 and w.endswith("le") and next_v == n - 1:
            cut = next_v - 2                       # ta-ble, peo-ple, lit-tle
        else:
            pair = w[end_v:end_v + 2]
            cut = end_v + (0 if pair in ("th", "ch", "sh", "ph", "wh", "gh") else 1)
        spans.append((start, cut))
        start = cut
    spans.append((start, n))
    return spans


def line_syllables(text: str) -> list[tuple[int, int]]:
    """[start, end) character spans of the syllables of a lyric line."""
    out = []
    for m in _WORD.finditer(text or ""):
        out += [(m.start() + a, m.start() + b) for a, b in word_syllables(m.group(0))]
    return out


def line_words(text: str) -> list[tuple[int, int, int]]:
    """(start, end, syllable count) of each word of a line."""
    return [(m.start(), m.end(), len(word_syllables(m.group(0)))) for m in _WORD.finditer(text or "")]


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Stanza:
    lines: tuple[int, ...]         # physical line numbers in the file
    refrain: bool = False


@dataclass(frozen=True)
class Lyrics:
    carol: str
    path: Path
    text_lines: tuple[str, ...]    # every physical line of the file
    stanzas: tuple[Stanza, ...]

    @property
    def verses(self) -> list[Stanza]:
        return [s for s in self.stanzas if not s.refrain]

    @property
    def refrain(self) -> Optional[Stanza]:
        return next((s for s in self.stanzas if s.refrain), None)

    def syllables(self, line: int) -> list[tuple[int, int]]:
        return line_syllables(self.text_lines[line])


def parse(text: str, carol: str = "", path: Optional[Path] = None) -> Lyrics:
    lines = text.splitlines()
    stanzas: list[Stanza] = []
    cur: list[int] = []
    refrain = False

    def flush():
        nonlocal cur, refrain
        if cur:
            stanzas.append(Stanza(tuple(cur), refrain))
        cur, refrain = [], False

    for i, ln in enumerate(lines):
        s = ln.strip()
        if s.startswith("#"):
            continue
        if not s:
            flush()
            continue
        if s.lower() == REFRAIN_MARK:
            flush()
            refrain = True
            continue
        cur.append(i)
    flush()
    return Lyrics(carol=carol, path=path or Path(), text_lines=tuple(lines), stanzas=tuple(stanzas))


def lyrics_path(carol_id: str) -> Path:
    return LYRICS_DIR / f"{carol_id}.txt"


@lru_cache(maxsize=32)
def _load_cached(carol_id: str, mtime: float) -> Optional[Lyrics]:
    p = lyrics_path(carol_id)
    lyr = parse(p.read_text(encoding="utf-8"), carol_id, p)
    return lyr if lyr.verses else None


def load(carol_id: str) -> Optional[Lyrics]:
    """The carol's lyrics, or None when there is no (usable) file."""
    p = lyrics_path(carol_id or "")
    if not carol_id or not p.is_file():
        return None
    return _load_cached(carol_id, p.stat().st_mtime)


# ---------------------------------------------------------------------------
# Alignment
# ---------------------------------------------------------------------------

@dataclass
class SyllableTime:
    index: int                     # syllable index in the line
    start: float                   # beats from the tune's first downbeat
    end: float
    notes: tuple[int, ...]         # melody note indices it is sung on


@dataclass
class LineTime:
    line: int                      # physical line in the file
    notes: tuple[int, int]         # melody note index range [a, b)
    syllables: list[SyllableTime] = field(default_factory=list)
    melismas: int = 0              # notes beyond one per syllable
    splits: int = 0                # syllables beyond one per note

    @property
    def start(self) -> float:
        return self.syllables[0].start

    @property
    def end(self) -> float:
        return self.syllables[-1].end


def _segment_cost(notes: list[TuneNote], a: int, b: int, syl: int, bar: float = 4.0) -> float:
    n = b - a
    d = n - syl
    # Spread melismas and splits over the lines rather than piling them on one.
    cost = d + 0.25 * d * d if d >= 0 else -1.6 * d + 0.8 * d * d
    if d > MAX_MELISMAS or -d > MAX_SPLITS:
        cost += 50.0
    last = notes[b - 1]
    gap = (notes[b].start - (last.start + last.dur)) if b < len(notes) else 2.0
    held = last.dur + max(0.0, gap)
    # A line ends on a held note (or before a rest): the longer the better.
    cost += 5.0 * max(0.0, 1.0 - held / bar)
    return cost


def _segments(notes: list[TuneNote], counts: list[list[int]], bar: float = 4.0) -> list[tuple[int, int]]:
    """Split the notes into one contiguous run per line, the same for every
    verse in ``counts`` (syllables per line, one list per verse): the
    music's phrases, found from all the verses at once (fewest melismas and
    splits, lines ending on held notes)."""
    L, N = len(counts[0]), len(notes)
    inf = float("inf")
    # Hymn lines are usually a whole number of bars each (two or four): line
    # i starts on its bar line, or up to a beat and a half before it as a
    # pickup. Tunes whose lines don't divide into bars skip this.
    bars = (notes[-1].start + notes[-1].dur) / bar
    per_line = round(bars / L)
    grid_on = per_line >= 1 and abs(bars / L - per_line) <= 0.2
    best = [[inf] * (N + 1) for _ in range(L + 1)]
    back = [[0] * (N + 1) for _ in range(L + 1)]
    best[0][0] = 0.0
    for i in range(1, L + 1):
        for b in range(i, N - (L - i) + 1):
            for a in range(i - 1, b):
                if best[i - 1][a] == inf:
                    continue
                dev = notes[a].start - (i - 1) * per_line * bar if (i > 1 and grid_on) else 0.0
                grid = 8.0 * (max(0.0, dev) + max(0.0, -dev - 1.5)) / bar
                c = best[i - 1][a] + grid + sum(_segment_cost(notes, a, b, v[i - 1], bar) for v in counts) / len(counts)
                if c < best[i][b]:
                    best[i][b], back[i][b] = c, a
    out = []
    b = N
    for i in range(L, 0, -1):
        a = back[i][b]
        out.append((a, b))
        b = a
    return out[::-1]


def _fit_line(notes: list[TuneNote], a: int, b: int, syl: int) -> tuple[list[SyllableTime], int, int]:
    """Syllable times for ``syl`` syllables over notes [a, b)."""
    slots = [(n.start, n.start + n.dur, (a + k,)) for k, n in enumerate(notes[a:b])]
    melismas = splits = 0
    if syl <= 0 or not slots:
        return [], 0, 0
    # More syllables than notes: split the longest notes.
    while len(slots) < syl:
        k = max(range(len(slots)), key=lambda j: (slots[j][1] - slots[j][0], -j))
        s, e, ids = slots[k]
        mid = s + (e - s) / 2
        slots[k:k + 1] = [(s, mid, ids), (mid, e, ids)]
        splits += 1
    # More notes than syllables: slur a note into the previous syllable,
    # quick stepwise passing notes on weak beats first.
    while len(slots) > syl:
        def score(j: int) -> float:
            s, e, ids = slots[j]
            ps = slots[j - 1]
            step = abs(notes[ids[0]].pitch - notes[ps[2][-1]].pitch)
            weak = 0.0 if abs(s - round(s)) > 1e-6 else 0.5
            return (e - s) + (0 if step <= 2 else 1.0) + weak + 0.01 * j
        k = min(range(1, len(slots)), key=score)
        s, e, ids = slots[k]
        ps, _pe, pids = slots[k - 1]
        slots[k - 1:k + 1] = [(ps, e, tuple(dict.fromkeys(pids + ids)))]
        melismas += 1
    return [SyllableTime(i, round(s, 4), round(e, 4), ids) for i, (s, e, ids) in enumerate(slots)], melismas, splits


def align_lines(tune: Tune, lyr: Lyrics, lines: list[int],
                segments: Optional[list[tuple[int, int]]] = None) -> list[LineTime]:
    """Line up ``lines`` (one pass of the tune) with the tune's melody."""
    notes = list(tune.melody)
    counts = [len(lyr.syllables(ln)) for ln in lines]
    if not lines or len(lines) > len(notes):
        return []
    segments = segments or _segments(notes, [counts], tune.beats)
    out = []
    for ln, (a, b), syl in zip(lines, segments, counts):
        sy, mel, spl = _fit_line(notes, a, b, syl)
        out.append(LineTime(line=ln, notes=(a, b), syllables=sy, melismas=mel, splits=spl))
    return out


def align_passes(tune: Tune, lyr: Lyrics) -> list[list[LineTime]]:
    """Every pass's lines lined up with the melody. Verses with the same
    number of lines share their phrase boundaries (the music's phrases)."""
    passes = pass_lines(tune, lyr)
    notes = list(tune.melody)
    shared: dict[int, list[tuple[int, int]]] = {}
    for n in {len(p) for p in passes}:
        group = [[len(lyr.syllables(ln)) for ln in p] for p in passes if len(p) == n]
        if 0 < n <= len(notes):
            shared[n] = _segments(notes, group, tune.beats)
    return [align_lines(tune, lyr, p, shared.get(len(p))) for p in passes]


def pass_lines(tune: Tune, lyr: Lyrics) -> list[list[int]]:
    """The lines sung on each pass of the tune: one verse per pass, plus the
    refrain when the tune carries it (the alignment fits better with it)."""
    ref = lyr.refrain
    out = []
    for v in lyr.verses:
        lines = list(v.lines)
        if ref is not None:
            with_ref = lines + list(ref.lines)
            if alignment_cost(tune, lyr, with_ref) <= alignment_cost(tune, lyr, lines):
                lines = with_ref
        out.append(lines)
    return out


def alignment_cost(tune: Tune, lyr: Lyrics, lines: list[int]) -> float:
    notes = list(tune.melody)
    counts = [len(lyr.syllables(ln)) for ln in lines]
    if not lines or len(lines) > len(notes):
        return float("inf")
    return sum(_segment_cost(notes, a, b, c, tune.beats)
               for (a, b), c in zip(_segments(notes, [counts], tune.beats), counts))


def verse_count(carol_id: str) -> int:
    lyr = load(carol_id)
    return len(lyr.verses) if lyr else 0
