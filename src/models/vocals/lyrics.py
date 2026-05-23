"""Lyrics ↔ melody alignment for vocal synthesis.

Extract the lead melody from a block's MIDI, count syllables (heuristic,
no dictionary), and map words onto consecutive notes so each word is sung
across the notes its syllables occupy. Leftover notes become "ah" melisma;
leftover words are dropped (the UI's syllable helper nudges the user to
match counts).
"""

from __future__ import annotations

import re

import numpy as np

_LEAD_HINTS = ("vocal", "lead", "melody")
_BASS_HINT = "bass"
_VOWELS = "aeiouy"


def extract_lead_notes(pm) -> list[tuple[int, float, float]]:
    """Pick the lead/melody track and return its notes as (pitch, start,
    end), time-sorted. Prefers tracks named vocal/lead/melody, otherwise
    the highest-register non-drum, non-bass track."""
    best = None
    best_score = -1e9
    for inst in pm.instruments:
        if inst.is_drum or not inst.notes:
            continue
        name = (inst.name or "").lower()
        score = float(np.mean([n.pitch for n in inst.notes]))
        if any(h in name for h in _LEAD_HINTS):
            score += 1000.0
        if _BASS_HINT in name:
            score -= 1000.0
        if score > best_score:
            best_score, best = score, inst
    if best is None:
        return []
    return sorted([(int(n.pitch), float(n.start), float(n.end)) for n in best.notes],
                  key=lambda x: x[1])


def count_syllables(word: str) -> int:
    """Heuristic English syllable count (vowel groups, minus silent-e)."""
    w = re.sub(r"[^a-z]", "", word.lower())
    if not w:
        return 0
    groups = re.findall(r"[aeiouy]+", w)
    n = len(groups)
    if w.endswith("e") and n > 1 and not w.endswith("le"):
        n -= 1
    return max(1, n)


def phrase_notes(notes: list[tuple[int, float, float]], gap: float = 0.35
                 ) -> list[list[tuple[int, float, float]]]:
    """Group notes into phrases split on rests longer than ``gap`` seconds
    (drives the per-line syllable helper in the UI)."""
    phrases: list[list] = []
    cur: list = []
    for p, s, e in notes:
        if cur and s - cur[-1][2] > gap:
            phrases.append(cur)
            cur = []
        cur.append((p, s, e))
    if cur:
        phrases.append(cur)
    return phrases


def phrase_syllable_counts(notes: list[tuple[int, float, float]], gap: float = 0.35) -> list[int]:
    """How many syllables each phrase wants (= note count per phrase)."""
    return [len(p) for p in phrase_notes(notes, gap=gap)]


def align_words_to_notes(text: str, notes: list[tuple[int, float, float]]) -> list[dict]:
    """Map words to consecutive notes by syllable count.

    Returns segments ``{text, notes: [(midi, dur_seconds)], start}`` — one
    per word, sung across the notes its syllables occupy. If the lyric runs
    out before the notes do, it loops from the top (so the line keeps
    singing real words rather than collapsing to "ah"). When the lyric is
    matched to the melody's syllable count (the UI's job), there's no loop.
    """
    words = re.findall(r"[A-Za-z']+", text or "")
    if not words:
        return []
    segs: list[dict] = []
    i = 0
    wi = 0
    n = len(notes)
    while i < n:
        w = words[wi % len(words)]
        syl = count_syllables(w)
        grp = notes[i:i + syl]
        if not grp:
            break
        segs.append({
            "text": w,
            "notes": [(p, max(0.05, e - s)) for (p, s, e) in grp],
            "start": grp[0][1],
        })
        i += len(grp)
        wi += 1
    return segs
