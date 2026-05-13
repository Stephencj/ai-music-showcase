"""MIDI → engraved PDF sheet music via music21 + LilyPond.

The pipeline is:

    .mid  ──music21.converter──►  Score
       └──► inject key signature (MIDI exports omit this)
       └──► quantize fractional rhythms (4ths/8ths/triplet-8ths/16ths)
                                       │
              ┌────────────────────────┴──────────────────────────┐
              ▼                                                    ▼
       lily.pdf engraver                                  per-part lily.pdf
       (full conductor score)                             (single-stave PDFs)
              │                                                    │
              └─────────────────► ZIP file ◄───────────────────────┘

Public entry point is ``export_zip``.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


_LILYPOND_AVAILABLE: Optional[bool] = None


def is_lilypond_available() -> bool:
    """True iff the ``lilypond`` binary is callable on ``$PATH``.

    Result is cached so repeated UI calls don't fork a subprocess.
    """

    global _LILYPOND_AVAILABLE
    if _LILYPOND_AVAILABLE is not None:
        return _LILYPOND_AVAILABLE
    try:
        result = subprocess.run(
            ["lilypond", "--version"],
            capture_output=True, text=True, timeout=5,
        )
        _LILYPOND_AVAILABLE = result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        _LILYPOND_AVAILABLE = False
    return _LILYPOND_AVAILABLE


def _safe_filename(name: str) -> str:
    """Make a track name safe for the filesystem.

    "Melody Harm 1" → "Melody_Harm_1".  Empty / weird names → "Part".
    """

    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", (name or "").strip())
    cleaned = cleaned.strip("_")
    return cleaned or "Part"


# Map each General-MIDI percussion family to (treble pitch position,
# LilyPond drum-mode name, MusicXML notehead style). The pitch tells
# music21 where to draw the notehead on a treble staff; the drum-mode
# name maps to LilyPond's percussion glyph (used for the PDF DrumStaff
# post-process); the notehead style controls the symbol so the in-app
# AlphaTab playback and the PDF both draw X for cymbals/hat, circled-X
# for open hat, normal for kick/snare/toms.
#
# notehead values that music21 emits unchanged to MusicXML:
#   "normal" / "x" / "circle-x" / "diamond" / "slash" / "triangle"
_DRUM_INFO_BY_INSTRUMENT_NAME = {
    # name: (pitch, drum-mode, notehead)
    "Bass Drum":          ("F4", "bd",    "normal"),
    "Acoustic Bass Drum": ("F4", "bda",   "normal"),
    "Snare Drum":         ("C5", "sn",    "normal"),
    "Electric Snare":     ("C5", "sne",   "normal"),
    "Side Stick":         ("C5", "ss",    "x"),
    "Hi-Hat Cymbal":      ("G5", "hh",    "x"),
    "Open Hi-Hat Cymbal": ("G5", "hho",   "circle-x"),
    "Pedal Hi-Hat":       ("D4", "hhp",   "x"),
    "Low Tom":            ("A4", "tomfl", "normal"),
    "Low-Mid Tom":        ("B4", "toml",  "normal"),
    "Mid Tom":            ("B4", "tomml", "normal"),
    "Hi-Mid Tom":         ("D5", "tommh", "normal"),
    "High Tom":           ("E5", "tomh",  "normal"),
    "Crash Cymbals":      ("A5", "cymc",  "x"),
    "Ride Cymbals":       ("F5", "cymr",  "x"),
    "Ride Bell":          ("F5", "rb",    "diamond"),
    "Splash Cymbal":      ("A5", "cyms",  "x"),
    "China Cymbal":       ("A5", "cymch", "x"),
    "Tambourine":         ("E5", "tamb",  "x"),
    "Cowbell":            ("D5", "cb",    "triangle"),
}


_DRUM_DEFAULT = ("B4", "hh", "x")


def _drum_info_for(unpitched) -> tuple:
    """Return (pitch, drum-mode-name, notehead) for an Unpitched."""
    inst = getattr(unpitched, "storedInstrument", None)
    name = getattr(inst, "instrumentName", None) if inst else None
    return _DRUM_INFO_BY_INSTRUMENT_NAME.get(name or "", _DRUM_DEFAULT)


def _drum_pitch_for(unpitched) -> str:
    return _drum_info_for(unpitched)[0]


def _drum_lily_name_for(unpitched) -> str:
    return _drum_info_for(unpitched)[1]


def _drum_notehead_for(unpitched) -> str:
    return _drum_info_for(unpitched)[2]


def _ql_to_lily_duration(ql: float) -> str:
    """quarter-length → LilyPond duration token: 1.0 → "4", 0.5 → "8"…"""
    if ql >= 4.0:
        return "1"
    if ql >= 3.0:
        return "2."
    if ql >= 2.0:
        return "2"
    if ql >= 1.5:
        return "4."
    if ql >= 1.0:
        return "4"
    if ql >= 0.75:
        return "8."
    if ql >= 0.5:
        return "8"
    if ql >= 0.25:
        return "16"
    if ql >= 0.125:
        return "32"
    return "8"


def _drum_part_to_drummode(part) -> Optional[str]:
    """Build a LilyPond ``\\drummode`` body from a drum part.

    Walks the part's notes/chords/rests in order. Each note records
    the originating drum-mode name (``bd``, ``sn``, ``hh``, ``hho``,
    ``cymc`` …) on a custom attribute during ``_normalize_percussion``.
    The drum-mode body engraves with authentic drum-set noteheads —
    closed hi-hat as ``x``, open hi-hat with a circle around the
    ``x``, snare/kick/toms with normal noteheads, etc.

    Returns ``None`` if no drum data was captured (e.g. the part isn't
    actually a drum part).
    """
    import music21

    tokens: list = []
    found_any = False
    for el in part.recurse().notesAndRests:
        ql = el.duration.quarterLength
        if ql <= 0:
            continue
        dur = _ql_to_lily_duration(ql)
        if isinstance(el, music21.note.Rest):
            tokens.append(f"r{dur}")
            continue
        names: list = []
        if isinstance(el, music21.chord.Chord):
            names = list(getattr(el, "_drum_lily_names", None) or [])
        elif isinstance(el, music21.note.Note):
            single = getattr(el, "_drum_lily_name", None)
            if single:
                names = [single]
        if not names:
            # No drum-mode metadata — skip (not a drum-source note).
            continue
        found_any = True
        if len(names) == 1:
            tokens.append(f"{names[0]}{dur}")
        else:
            tokens.append("<" + " ".join(names) + ">" + dur)
    if not found_any:
        return None
    return " ".join(tokens)


def _force_binary_grid(part, grid: float = 0.25) -> None:
    """Snap every notesAndRest in ``part`` to a binary grid and strip
    any leftover tuplet markings.

    music21's ``quantize`` rounds offsets but keeps triplet groupings
    intact for notes whose original duration was 1/3 quarter etc.
    For drum charts the user wants standard binary rhythms (no
    triplet brackets) regardless of swing — this guarantees it.
    """
    import music21
    for el in list(part.recurse().notesAndRests):
        try:
            new_offset = round(el.offset / grid) * grid
            new_qlen = max(grid, round(el.duration.quarterLength / grid) * grid)
            el.offset = new_offset
            el.duration = music21.duration.Duration(new_qlen)
            # Wipe any tuplet markings the quantizer left behind.
            try:
                el.duration.tuplets = ()
            except Exception:
                pass
        except Exception:
            continue


def _normalize_percussion(score) -> int:
    """Convert music21's drum elements into engravable notes.

    MIDI drum tracks parse into a mix of:

    * ``Unpitched`` — one per real drum hit. Has a ``storedInstrument``
      (e.g. ``HiHatCymbal``, ``BassDrum``) but no real pitch.
    * ``PercussionChord`` — *container* for simultaneous drum hits
      (e.g. kick + hat on the downbeat). ``.pitches`` is empty because
      none of the contained drums are pitched; the actual children are
      ``.notes`` (each an Unpitched).

    music21's LilyPond translator drops both element types silently —
    drum staves come out as rests, and per-part exports crash with
    "zero-duration score". This pass rewrites each Unpitched as a
    pitched ``Note`` on a drum-shorthand staff position, and each
    PercussionChord as a ``Chord`` of those positions. Result: a
    readable single-staff drum chart on treble clef.

    Returns the number of elements converted (for logging).
    """
    import music21

    n = 0
    # Walk PercussionChord first so the nested Unpitched objects don't
    # get rewritten in-place (which would orphan them from their
    # container's activeSite).
    for el in list(
        score.recurse().getElementsByClass(music21.percussion.PercussionChord)
    ):
        site = el.activeSite
        if site is None:
            continue
        children = [c for c in (el.notes if hasattr(el, "notes") else [])
                    if isinstance(c, music21.note.Unpitched)]
        info = [_drum_info_for(c) for c in children]
        pitches = [music21.pitch.Pitch(p) for p, _, _ in info]
        drum_names = [d for _, d, _ in info]
        noteheads = [h for _, _, h in info]
        ql = el.duration.quarterLength
        if pitches:
            replacement = music21.chord.Chord(pitches, quarterLength=ql)
            # If every notehead in the chord agrees, set it on the chord
            # itself; otherwise apply per-pitch via notehead per-note.
            unique_heads = set(noteheads)
            if len(unique_heads) == 1:
                replacement.notehead = noteheads[0]
            else:
                for chord_note, head in zip(replacement.notes, noteheads):
                    chord_note.notehead = head
        else:
            replacement = music21.note.Note("B4", quarterLength=ql)
            replacement.notehead = "x"
            drum_names = ["hh"]
        replacement._drum_lily_names = drum_names
        site.replace(el, replacement)
        n += 1

    # Standalone Unpitched (off-beat hi-hats / cymbals / etc.).
    for el in list(score.recurse().getElementsByClass(music21.note.Unpitched)):
        site = el.activeSite
        if site is None:
            continue
        pitch_name, drum_name, notehead = _drum_info_for(el)
        new_note = music21.note.Note(pitch_name)
        new_note.duration = el.duration
        new_note.notehead = notehead
        new_note._drum_lily_name = drum_name
        site.replace(el, new_note)
        n += 1

    return n


def midi_to_score(
    midi_path: "Path | str",
    *,
    key: str = "C",
    scale: str = "major",
    tempo: Optional[float] = None,
    title: Optional[str] = None,
    swing: float = 0.0,
):
    """Load MIDI → music21 Score, patch in the key signature, quantize.

    When ``swing > 0`` the drum parts are snapped to a STRAIGHT 8th-note
    grid (not 16ths) and a "Swing" performance instruction is engraved
    above the top staff. That mirrors the standard jazz-chart
    convention: write straight 8ths on paper, let the player interpret
    them with swing. Otherwise the previous 16th-note binary grid is
    used for drums.
    """

    import music21

    score = music21.converter.parse(str(midi_path))

    converted = _normalize_percussion(score)
    if converted:
        logger.info("normalized %d percussion chords", converted)

    mode = "major" if (scale or "major").lower().startswith("maj") else "minor"
    try:
        ks = music21.key.Key(key, mode)
        score.insert(0, ks)
    except Exception:
        logger.warning("could not inject key %r %r — skipping", key, mode)

    # Quantize melodic parts with the triplet grid so swung 8ths
    # show as actual triplet 8ths; FORCE drum parts onto a straight
    # 16th-note grid so the engraved drum line stays the standard
    # "rock chart" eighth/sixteenth notation regardless of the
    # swing setting on the MIDI side. (Stephen: "the midi side is
    # perfect, we have a swing setting on the drums causing odd
    # notation instead of standard eighth-note notation.")
    def _is_drum_part(part) -> bool:
        name = str(getattr(part, "partName", "") or "")
        return "drum" in name.lower() or "perc" in name.lower()

    # When swing is on, snap drum offsets to STRAIGHT 8ths (grid=0.5).
    # Otherwise use 16ths (grid=0.25). The "Swing" instruction added
    # below tells the performer to interpret the 8ths with swing feel —
    # standard jazz-chart convention. Without this, swing-displaced
    # offsets read as dotted-8th-plus-16th pairs (ugly).
    swing_active = bool(swing and swing > 0.05)
    drum_grid = 0.5 if swing_active else 0.25

    for part in score.parts:
        try:
            if _is_drum_part(part):
                part.quantize(
                    [4, 8, 16],
                    processOffsets=True, processDurations=True, inPlace=True,
                )
                _force_binary_grid(part, grid=drum_grid)
            else:
                part.quantize(
                    [4, 8, 12, 16],
                    processOffsets=True, processDurations=True, inPlace=True,
                )
        except Exception:
            logger.exception(
                "quantize failed on part %r — engraving raw rhythms",
                getattr(part, "partName", "?"),
            )

    # Engrave a "Swing" performance instruction at the top of the score
    # so the player knows to swing the straight 8ths.
    if swing_active:
        try:
            top = score.parts[0] if list(score.parts) else None
            if top is not None:
                first_measure = top.recurse().getElementsByClass(
                    music21.stream.Measure,
                ).first()
                target = first_measure if first_measure is not None else top
                te = music21.expressions.TextExpression("Swing")
                te.placement = "above"
                # Push to position 0 of the first measure.
                target.insert(0, te)
        except Exception:
            logger.exception("could not add Swing annotation — continuing")

    md = music21.metadata.Metadata()
    md.title = title or "Composition"
    score.metadata = md
    return score


# LilyPond pitch-name conversion for chord-mode strings.
# Music21 spells pitches like "F#" / "Bb" / "C-"; LilyPond's chordmode
# wants "fis" / "bes" / "ces" (dutch note names).
_LILY_ACCIDENTAL_MAP = {"#": "is", "-": "es", "b": "es"}


def _to_lily_pitch(name: str) -> str:
    """``music21.pitch.Pitch.name`` → LilyPond chord-mode root token.

    Examples: ``"C"`` → ``"c"``, ``"F#"`` → ``"fis"``, ``"Bb"`` → ``"bes"``.
    """
    if not name:
        return "c"
    base = name[0].lower()
    tail = name[1:]
    for ch in tail:
        base += _LILY_ACCIDENTAL_MAP.get(ch, "")
    return base


# music21 RomanNumeral.commonName → LilyPond chord-mode quality suffix.
_LILY_QUALITY_BY_COMMON_NAME = {
    "major triad": "",
    "minor triad": ":m",
    "diminished triad": ":dim",
    "augmented triad": ":aug",
    "dominant seventh chord": ":7",
    "major seventh chord": ":maj7",
    "minor seventh chord": ":m7",
    "half-diminished seventh chord": ":m7.5-",
    "diminished seventh chord": ":dim7",
}


def _lily_duration_for_bars(bars: float) -> str:
    """Convert a bar-count to a LilyPond chord-mode duration token.

    1 bar → ``1`` (whole note), 2 bars → ``1*2``, 0.5 bar → ``2``
    (half note), etc.  Anything that doesn't fit a power-of-two grid
    falls back to ``1*<fraction>``.
    """
    if bars == 1.0:
        return "1"
    if bars == 0.5:
        return "2"
    if bars == 0.25:
        return "4"
    if bars == 2.0:
        return "1*2"
    if bars == 4.0:
        return "1*4"
    # Generic fallback: scaled whole notes.
    if bars == int(bars):
        return f"1*{int(bars)}"
    return f"1*{bars:.4f}"


def _progression_to_chordmode(
    progression: "list | None",
    key: str,
    total_bars: int,
) -> Optional[str]:
    """Build a LilyPond ``\\chordmode`` string from a progression list.

    Accepts either:

    - ``["I", "V", "vi", "IV"]`` — bare roman symbols, each 1 bar.
    - ``[("I", 1.0), ("V", 1.0), ("vi", 1.0), ("IV", 1.0)]`` — the
      ``(symbol, duration_in_bars)`` tuple format ``compose_midi``
      stashes into ``_state["compose_meta"]``.

    Loops the progression to fill ``total_bars``; truncates if longer.
    ``["I","V","vi","IV"]`` over 8 bars → ``"g1 d1 e1:m c1 g1 d1 e1:m c1"``.
    """
    if not progression or total_bars <= 0:
        return None
    try:
        import music21
        k = music21.key.Key(key)
    except Exception:
        logger.warning("could not parse key %r — skipping chord symbols", key)
        return None

    tokens: list = []
    used_bars = 0.0
    epsilon = 1e-6
    # Loop the progression to fill all bars so the chord-name layer
    # spans the full piece, not just the first cycle.
    while used_bars + epsilon < total_bars:
        any_appended = False
        for raw in progression:
            if used_bars + epsilon >= total_bars:
                break
            if isinstance(raw, (tuple, list)) and len(raw) >= 2:
                sym, dur_bars = raw[0], float(raw[1])
            else:
                sym, dur_bars = raw, 1.0
            try:
                rn = music21.roman.RomanNumeral(sym, k)
            except Exception:
                logger.warning("could not parse roman %r in key %r", sym, key)
                used_bars += dur_bars
                continue
            # Truncate the last chord's duration so the chordmode stops
            # exactly at total_bars (LilyPond errors if the ChordNames
            # context runs longer than the music staff).
            chord_dur = min(dur_bars, max(0.0, total_bars - used_bars))
            root = _to_lily_pitch(rn.root().name)
            suffix = _LILY_QUALITY_BY_COMMON_NAME.get(rn.commonName, "")
            tokens.append(f"{root}{_lily_duration_for_bars(chord_dur)}{suffix}")
            used_bars += chord_dur
            any_appended = True
        if not any_appended:
            break
    if not tokens:
        return None
    return " ".join(tokens)


def _postprocess_ly(
    ly_src: str,
    *,
    chordmode: Optional[str],
    instrument_names: "list[str] | None" = None,
    drum_indices_and_modes: "list[tuple[int, str]] | None" = None,
    suppress_tagline: bool = True,
) -> str:
    """Surgical edits on music21's emitted ``.ly`` source:

    1. Strip the ``\\include "lilypond-book-preamble.ly"`` line.
       music21 emits this for embedded-EPS book-mode rendering — it
       blows up the layout on a stand-alone page.
    2. Replace ``\\paper { }`` with ``\\paper { tagline = ##f }`` so
       LilyPond stops appending its "Music engraving by …" footer.
    3. Inject ``\\set Staff.instrumentName = "Foo"`` into each
       ``\\new Staff`` block, using ``instrument_names`` in part order.
       music21 doesn't emit instrument names for LilyPond, so the
       staves are otherwise anonymous.
    4. If ``chordmode`` is provided, inject a ``\\new ChordNames
       \\chordmode { ... }`` block at the top of the score's parallel
       ``<<`` expression so chord symbols engrave above the top staff.
    """
    out = ly_src
    out = re.sub(
        r'^\s*\\include\s+"lilypond-book-preamble\.ly".*?\n',
        "",
        out,
        flags=re.MULTILINE,
    )

    # Page setup goes in the `\paper { }` block music21 emits at the
    # bottom of the .ly. Both `set-paper-size` and `set-default-paper-size`
    # are silently ignored on bare-\score documents in LilyPond 2.26,
    # so we have to set paper-width/paper-height explicitly to get
    # landscape letter (11×8.5in).
    paper_directives: list = [
        "paper-width = 11\\in",
        "paper-height = 8.5\\in",
    ]
    if suppress_tagline:
        paper_directives.append("tagline = ##f")
    paper_block = "\\paper {\n  " + "\n  ".join(paper_directives) + "\n}"
    out = out.replace("\\paper { }", paper_block)

    if instrument_names:
        # Add an instrumentName setter into each ``\new Staff = X {``
        # opening, walking the list in part order.
        names_iter = iter(instrument_names)

        def _label_staff(match: re.Match) -> str:
            try:
                name = next(names_iter)
            except StopIteration:
                return match.group(0)
            safe = name.replace('"', "'")
            return (
                f'{match.group(1)}\\with {{ '
                f'instrumentName = #"{safe}" '
                f'shortInstrumentName = #"{safe[:4]}" '
                f'}} {{ {match.group(2)}'
            )

        out = re.sub(
            r"(\\new\s+Staff\s+=\s+\S+\s+)\{(\s*\\clef)",
            _label_staff,
            out,
        )

    if drum_indices_and_modes:
        # Walk staff blocks with brace counting so LilyPond ``%{ ... %}``
        # comments don't fool a non-greedy regex into closing early.
        staff_header_re = re.compile(
            r"\\new\s+Staff\s+=\s+\S+\s+"
            r"(?P<withclause>\\with\s*\{[^{}]*\}\s+)?"
            r"\{"
        )
        matches: list = []
        for hm in staff_header_re.finditer(out):
            body_start = hm.end()
            depth = 1
            i = body_start
            while i < len(out) and depth > 0:
                if out[i:i + 2] == "%{":
                    end = out.find("%}", i + 2)
                    i = end + 2 if end != -1 else len(out)
                    continue
                ch = out[i]
                if ch == "%":  # line comment
                    eol = out.find("\n", i)
                    i = eol + 1 if eol != -1 else len(out)
                    continue
                if ch == '"':
                    end = out.find('"', i + 1)
                    i = end + 1 if end != -1 else len(out)
                    continue
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                i += 1
            matches.append((hm.start(), i, hm.group("withclause") or ""))

        replacements: list = []
        for idx, drum_body in drum_indices_and_modes:
            if 0 <= idx < len(matches):
                start, end, with_clause = matches[idx]
                replacement = (
                    "\\new DrumStaff " + with_clause
                    + "{ \\drummode { " + drum_body + " } }"
                )
                replacements.append((start, end, replacement))
        for start, end, rep in sorted(replacements, key=lambda x: -x[0]):
            out = out[:start] + rep + out[end:]

    if chordmode:
        # The Score body starts with a ``<<`` opening the parallel music
        # expression. Inserting our ChordNames context immediately after
        # the ``<<`` puts the chord symbols on the top line of the system.
        chord_block = (
            "\n      \\new ChordNames "
            "{ \\set chordChanges = ##t \\chordmode { "
            f"{chordmode} "
            "} }\n"
        )
        # Match only the first ``<<`` inside ``\score {``.
        m = re.search(r"\\score\s*\{", out)
        if m:
            tail = out[m.end():]
            idx = tail.find("<<")
            if idx != -1:
                inject_at = m.end() + idx + len("<<")
                out = out[:inject_at] + chord_block + out[inject_at:]
    return out


def _staff_names_for(score) -> "list[str]":
    """Return the partName for each part, in order."""
    names: list = []
    for idx, part in enumerate(score.parts):
        name = (getattr(part, "partName", None)
                or getattr(part, "id", None)
                or f"Part {idx + 1}")
        names.append(str(name))
    return names


def _drum_indices_and_modes(score) -> "list[tuple[int, str]]":
    """For each part whose notes carry drum-mode metadata, return
    ``(part_index, drummode_body)``. Used to swap the regular Staff
    block for a DrumStaff in the .ly post-processor."""
    result: list = []
    for idx, part in enumerate(score.parts):
        body = _drum_part_to_drummode(part)
        if body:
            result.append((idx, body))
    return result


def score_to_full_pdf(
    score,
    out_path: "Path | str",
    *,
    chordmode: Optional[str] = None,
) -> Path:
    """Engrave ``score`` to a single PDF, optionally with a ChordNames
    layer above the top staff.

    We bypass ``Stream.write("lily.pdf")`` so we can:

    - Suppress LilyPond's default "Music engraving by LilyPond X.Y"
      tagline at the bottom.
    - Optionally inject a ``\\chordmode { ... }`` block for chord
      symbols.

    ``Stream.write("lily.ly", fp=X)`` writes only the source; we then
    edit it and call ``lilypond`` directly.
    """

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    # Write the raw LilyPond source.
    stem = str(out.with_suffix(""))
    ly_src_path = Path(str(score.write("lily.ly", fp=stem)))
    src = ly_src_path.read_text()
    src = _postprocess_ly(
        src, chordmode=chordmode,
        instrument_names=_staff_names_for(score),
        drum_indices_and_modes=_drum_indices_and_modes(score),
    )
    ly_src_path.write_text(src)

    # Run LilyPond ourselves. ``--output=<stem>`` makes lilypond write
    # to ``<stem>.pdf``; we then move that to the requested path.
    out_stem = str(out.with_suffix(""))
    result = subprocess.run(
        ["lilypond", "--silent", f"--output={out_stem}", str(ly_src_path)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "lilypond failed (exit %d):\n%s" % (result.returncode, result.stderr)
        )
    pdf_path = Path(out_stem + ".pdf")
    if pdf_path != out:
        try:
            shutil.move(str(pdf_path), str(out))
            pdf_path = out
        except Exception:
            logger.exception(
                "could not move %s → %s; using engraver output as-is",
                pdf_path, out,
            )
    return pdf_path


def score_to_part_pdfs(
    score,
    out_dir: "Path | str",
    *,
    chordmode: Optional[str] = None,
) -> dict:
    """Engrave one PDF per instrument part.

    When ``chordmode`` is provided, the chord-symbol block is added
    to every part PDF — so the bassist sees the same changes as the
    pianist.

    Returns a dict ``{part_name: pdf_path}``.
    """

    import music21

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    result: dict = {}
    title = ""
    try:
        if score.metadata and score.metadata.title:
            title = str(score.metadata.title)
    except Exception:
        pass

    used: set = set()
    for idx, part in enumerate(list(score.parts)):
        part_name = (getattr(part, "partName", None)
                     or getattr(part, "id", None)
                     or f"Part {idx + 1}")
        stem = _safe_filename(str(part_name))
        unique = stem
        suffix = 2
        while unique in used:
            unique = f"{stem}_{suffix}"
            suffix += 1
        used.add(unique)

        # Skip empty parts — LilyPond errors out on zero-duration scores.
        if not list(part.recurse().notesAndRests):
            logger.info("skipping empty part %r", part_name)
            continue

        single = music21.stream.Score()
        single_md = music21.metadata.Metadata()
        single_md.title = (f"{title} — {part_name}").strip(" —")
        single.metadata = single_md
        single.insert(0, part)

        try:
            pdf_path = score_to_full_pdf(
                single, out / f"{unique}.pdf", chordmode=chordmode,
            )
            result[str(part_name)] = pdf_path
        except Exception:
            logger.exception("failed to engrave part %r — skipping", part_name)
    return result


def export_zip(
    midi_path: "Path | str",
    out_zip_path: "Path | str",
    *,
    key: str = "C",
    scale: str = "major",
    tempo: Optional[float] = None,
    title: Optional[str] = None,
    progression: Optional[list] = None,
    bars: Optional[int] = None,
    swing: float = 0.0,
) -> Path:
    """End-to-end: MIDI → engraved PDFs → single ZIP file.

    The ZIP layout is::

        full_score.pdf
        parts/<TrackName>.pdf
        parts/<OtherTrack>.pdf
        ...

    When ``progression`` is provided (a list of roman numerals such as
    ``["I", "V", "vi", "IV"]``), chord-symbol markers (``G``, ``D``,
    ``Em``, ``C``) are engraved above the top staff of every PDF in
    the ZIP. ``bars`` controls how the progression is laid out — defaults
    to ``len(progression)`` so each chord gets one bar.

    Raises ``RuntimeError`` if LilyPond is not installed.
    """

    if not is_lilypond_available():
        raise RuntimeError(
            "LilyPond is not installed. Install it with "
            "`brew install lilypond` (Mac) or "
            "`apt-get install lilypond` (Linux) and try again."
        )

    out_zip = Path(out_zip_path)
    out_zip.parent.mkdir(parents=True, exist_ok=True)

    score = midi_to_score(
        midi_path, key=key, scale=scale, tempo=tempo, title=title,
        swing=swing,
    )

    chordmode = _progression_to_chordmode(
        progression, key, bars or (len(progression) if progression else 0),
    )

    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        full_pdf = score_to_full_pdf(
            score, td_path / "full_score.pdf", chordmode=chordmode,
        )
        parts = score_to_part_pdfs(
            score, td_path / "parts", chordmode=chordmode,
        )

        tmp_zip = td_path / "_export.zip"
        with zipfile.ZipFile(tmp_zip, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(full_pdf, arcname="full_score.pdf")
            for _, pdf_path in parts.items():
                zf.write(pdf_path, arcname=f"parts/{pdf_path.name}")
        shutil.move(str(tmp_zip), str(out_zip))

    return out_zip
