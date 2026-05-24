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


_HARM_HINTS = ("harmony", "backing", "choir", "ooh", "aah", "vocal")


def _score_vocal_instruments(pm) -> list:
    """Rank non-drum tracks by how vocal-like they are (highest first)."""
    scored = []
    for inst in pm.instruments:
        if inst.is_drum or not inst.notes:
            continue
        name = (inst.name or "").lower()
        score = float(np.mean([n.pitch for n in inst.notes]))
        if "lead" in name or "melody" in name:
            score += 2000.0                       # the true lead wins
        elif "vocal" in name:
            score += 400.0
        if any(h in name for h in ("harmony", "backing", "choir")):
            score -= 800.0                        # rank harmonies below the lead
        if _BASS_HINT in name:
            score -= 2000.0
        scored.append((score, inst, name))
    scored.sort(key=lambda x: -x[0])
    return scored


def select_vocal_instruments(pm):
    """The pretty_midi Instruments ``render_vocals`` would sing:
    ``(lead_instrument | None, [harmony_instruments])``. Same selection as
    :func:`select_vocal_tracks` but returns the track objects, so callers can
    exclude them from the instrumental backing (else the soundfont melody /
    harmony doubles the sung vocal)."""
    scored = _score_vocal_instruments(pm)
    if not scored:
        return None, []
    lead = scored[0][1]
    harms = [inst for _, inst, name in scored[1:] if any(h in name for h in _HARM_HINTS)]
    return lead, harms


def select_vocal_tracks(pm) -> tuple[list, list]:
    """Return ``(lead_notes, harmonies)`` where harmonies is a list of
    ``(track_name, notes)``. Lead = the best-scored melodic track; harmonies
    = other tracks named harmony/backing/vocal/choir (so we don't sing the
    bass or piano)."""
    lead, harms = select_vocal_instruments(pm)
    if lead is None:
        return [], []

    def notes_of(inst):
        return sorted([(int(n.pitch), float(n.start), float(n.end)) for n in inst.notes],
                      key=lambda x: x[1])

    return notes_of(lead), [(inst.name, notes_of(inst)) for inst in harms]


def monophonic_line(notes: list[tuple[int, float, float]], min_dur: float = 0.03
                    ) -> list[tuple[int, float, float]]:
    """Collapse possibly-overlapping notes into a non-overlapping, time-ordered
    line. A monophonic voice can only sing one pitch at a time, and the studio
    engine renders a line as one contiguous frame sequence — so overlapping
    notes (a chordal backing/pad) would otherwise be laid end-to-end and drift
    out of time. On overlap we keep the earlier (higher-pitch on ties) note and
    start the next when the previous ends, dropping anything with no room left."""
    out: list[tuple[int, float, float]] = []
    last_end = -1.0
    for p, s, e in sorted(notes, key=lambda x: (x[1], -x[0])):
        s2 = max(s, last_end)
        if e - s2 < min_dur:
            continue
        out.append((p, s2, e))
        last_end = e
    return out


_HARM_VOWEL = "ooh"


def harmony_vowel_segments(notes: list[tuple[int, float, float]],
                           vowel: str = _HARM_VOWEL) -> list[dict]:
    """Turn harmony/backing notes into wordless vowel segments ("ooh"),
    one per note, placed at the note's own start time. The notes share the
    lead's MIDI timeline, so the backing voices land *under* the lead at the
    right moments and pitches — no lyric re-distribution, no syllable
    mismatch. (We keep one segment per note rather than slurring a phrase so
    each ooh stays locked to its note; the render packs a group's notes
    contiguously, which would drift sustained groups off the beat.)"""
    return [{"text": vowel, "notes": [(p, max(0.05, e - s))], "start": s}
            for (p, s, e) in notes]


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
