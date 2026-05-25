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


def align_words_to_notes(text: str, notes: list[tuple[int, float, float]],
                         pron: "list[list[str]] | None" = None) -> list[dict]:
    """Map words to consecutive notes by syllable count.

    Returns segments ``{text, notes: [(midi, dur_seconds)], start}`` — one
    per word, sung across the notes its syllables occupy. If the lyric runs
    out before the notes do, it loops from the top (so the line keeps
    singing real words rather than collapsing to "ah"). When the lyric is
    matched to the melody's syllable count (the UI's job), there's no loop.

    ``pron`` is an optional **pronunciation layer**: a positional list of
    per-word phoneme lists (ARPABET, lowercase) aligned to the words of
    ``text``. When given, each segment carries ``phonemes`` so the engine
    sings those instead of running g2p on the spelling — this is the editable
    "phonetic version" of the lyric (see :func:`to_phonetic`). Note counts
    still come from the *displayed* word's syllables, so a phoneme edit can't
    desync the melody.
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
        seg = {
            "text": w,
            "notes": [(p, max(0.05, e - s)) for (p, s, e) in grp],
            "start": grp[0][1],
        }
        if pron and len(pron) == len(words):
            phs = pron[wi % len(pron)]
            if phs:
                seg["phonemes"] = list(phs)
        segs.append(seg)
        i += len(grp)
        wi += 1
    return segs


def _fold_below(midi: int, ceiling: int) -> int:
    """Drop ``midi`` by whole octaves until it sits at/under ``ceiling``."""
    while midi > ceiling:
        midi -= 12
    return midi


def apply_clarity(segments: list[dict], *, ceiling: int = 71,
                  register: str = "fold", min_word_gap: float = 0.10,
                  demelisma: bool = True, max_trim_frac: float = 0.35,
                  min_sustain: float = 0.18) -> list[dict]:
    """Render-time **clarity transform** on aligned word segments — trade a
    little melodic faithfulness for ASR-measurable intelligibility *without*
    moving any word onset, so the vocal stays locked to the backing track.

    Levers (each independently controllable, all measured against
    :mod:`intelligibility`):

    * **register cap** — high, bright notes are the worst case for the SVS's
      diction (the fast, repeated-C#5 chorus). ``register="fold"`` drops only
      the notes above ``ceiling`` MIDI by whole octaves; ``"shift"`` moves the
      *whole* line down by octave steps until its loudest peak sits at/under
      ``ceiling`` (keeps the melodic contour intact); ``"off"`` leaves pitch
      alone.
    * **de-melisma** — merge consecutive same-pitch notes inside one word into
      a single sustained note. (:func:`align_words_to_notes` is one note per
      syllable, so this merges *same-pitch adjacent syllables*; empirically it
      reads clearer on sung lines — fewer re-attacks on words like "ba-by" held
      on one pitch — so it's on by default. The density guard below disables it
      on fast lines, where merging would slur syllables.)

    **Density guard** (``min_sustain``): clarity's gap + de-melisma assume
    sustained, *sung* notes. On a fast/dense line (rap, 16th-notes) they gut
    the words — and rap wants the rough/TTS engine, not clarity — so when the
    line's median note is shorter than ``min_sustain`` we keep only the
    (harmless) register cap. Clarity is a sung-line tool; this stops the
    UI toggle from wrecking a dense line.
    * **inter-word gap** — trim the tail of each word's last note so there is
      at least ``min_word_gap`` seconds of silence before the next word's
      onset. The studio engine renders that as a short rest (an ``SP`` token),
      separating words that otherwise run together. Onsets never move (the
      note is only shortened, and never below 0.08 s), so timing is preserved.
      ``max_trim_frac`` caps how much of a note the gap may eat (default 35 %),
      so dense/fast lines (rap, 16th-notes) degrade gracefully instead of being
      gutted — clarity is a *sung*-line tool; rap wants the rough/TTS engine.

    Returns a new segment list; the input is not mutated.
    """
    if not segments:
        return segments

    # --- density guard: on a fast/dense line, keep only the register cap ---
    durs = sorted(d for seg in segments for _, d in seg["notes"])
    if durs:
        median = durs[len(durs) // 2]
        if median < min_sustain:
            min_word_gap, demelisma = 0.0, False

    # --- register cap -----------------------------------------------------
    shift = 0
    if register == "shift":
        peak = max((m for seg in segments for m, _ in seg["notes"]), default=0)
        while peak + shift > ceiling:
            shift -= 12

    out: list[dict] = []
    for seg in segments:
        notes = list(seg["notes"])
        if register == "shift" and shift:
            notes = [(m + shift, d) for m, d in notes]
        elif register == "fold":
            notes = [(_fold_below(m, ceiling), d) for m, d in notes]
        if demelisma:
            merged: list[tuple[int, float]] = []
            for m, d in notes:
                if merged and merged[-1][0] == m:
                    pm, pd = merged[-1]
                    merged[-1] = (pm, pd + d)
                else:
                    merged.append((m, d))
            notes = merged
        out.append({**seg, "notes": notes})

    # --- inter-word gap (trim the previous word's tail) -------------------
    if min_word_gap > 0:
        for cur, nxt in zip(out, out[1:]):
            if not cur["notes"]:
                continue
            end = cur["start"] + sum(d for _, d in cur["notes"])
            deficit = min_word_gap - (nxt["start"] - end)
            if deficit <= 0:
                continue
            m, d = cur["notes"][-1]
            # never shorten below 80 ms, nor eat more than max_trim_frac of the
            # note (so fast/dense lines aren't gutted into choppy fragments)
            trim = min(deficit, d - 0.08, max_trim_frac * d)
            if trim > 0:
                cur["notes"][-1] = (m, d - trim)
    return out


_G2P_SINGLETON = None


def _g2p_arpabet(word: str) -> list[str]:
    """ARPABET phonemes for a word (lowercased, stress digits stripped)."""
    global _G2P_SINGLETON
    if _G2P_SINGLETON is None:
        import nltk
        for res in ("averaged_perceptron_tagger_eng", "cmudict"):
            try:
                nltk.download(res, quiet=True)
            except Exception:  # noqa: BLE001
                pass
        from g2p_en import G2p
        _G2P_SINGLETON = G2p()
    out = []
    for tok in _G2P_SINGLETON(word):
        t = "".join(c for c in tok if c.isalpha()).lower()
        if t:
            out.append(t)
    return out


def to_phonetic(text: str) -> str:
    """Convert normal lyrics to an editable **phonetic version**: each word
    becomes a bracketed ARPABET group, line breaks preserved. e.g.
    ``"forever"`` → ``"[f er eh v er]"``. This is the auto-generated layer the
    user can then tweak per word to fix the SVS's diction; feed it back through
    :func:`parse_phonetic` + ``align_words_to_notes(pron=...)``."""
    lines_out = []
    for line in (text or "").splitlines():
        words = re.findall(r"[A-Za-z']+", line)
        groups = [f"[{' '.join(_g2p_arpabet(w))}]" for w in words]
        lines_out.append(" ".join(groups))
    return "\n".join(lines_out)


def parse_phonetic(phonetic: str) -> list[list[str]]:
    """Parse a phonetic version (``[f er]  [s eh d]`` …) into a positional
    list of per-word phoneme lists, across all lines — the ``pron`` argument
    for :func:`align_words_to_notes`."""
    out: list[list[str]] = []
    for m in re.findall(r"\[([^\]]*)\]", phonetic or ""):
        out.append([p for p in m.lower().split() if p])
    return out
