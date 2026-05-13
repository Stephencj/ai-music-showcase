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


# Drum-kit shorthand: map each General-MIDI percussion family to a
# distinct staff position on a treble-clef "drum line". This is the
# convention most rock/pop charts follow — kick at the bottom space,
# snare on the middle line, hat above the staff, etc. music21 leaves
# every Unpitched at B4 by default, which would collapse all drums
# onto one line.
_DRUM_PITCH_BY_INSTRUMENT_NAME = {
    "Bass Drum": "F4",
    "Acoustic Bass Drum": "F4",
    "Snare Drum": "C5",
    "Electric Snare": "C5",
    "Side Stick": "C5",
    "Hi-Hat Cymbal": "G5",
    "Open Hi-Hat Cymbal": "G5",
    "Pedal Hi-Hat": "D4",
    "Low Tom": "A4",
    "Low-Mid Tom": "B4",
    "Mid Tom": "B4",
    "Hi-Mid Tom": "D5",
    "High Tom": "E5",
    "Crash Cymbals": "A5",
    "Ride Cymbals": "F5",
    "Ride Bell": "F5",
    "Splash Cymbal": "A5",
    "China Cymbal": "A5",
    "Tambourine": "E5",
    "Cowbell": "D5",
}


def _drum_pitch_for(unpitched) -> str:
    """Pick a staff position for a single Unpitched drum hit."""
    inst = getattr(unpitched, "storedInstrument", None)
    name = getattr(inst, "instrumentName", None) if inst else None
    return _DRUM_PITCH_BY_INSTRUMENT_NAME.get(name or "", "B4")


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
        children = list(el.notes) if hasattr(el, "notes") else []
        pitches = [
            music21.pitch.Pitch(_drum_pitch_for(c))
            for c in children
            if isinstance(c, music21.note.Unpitched)
        ]
        ql = el.duration.quarterLength
        if pitches:
            replacement = music21.chord.Chord(pitches, quarterLength=ql)
        else:
            # No drum-kit children — collapse to a single beat at B4.
            replacement = music21.note.Note("B4", quarterLength=ql)
        site.replace(el, replacement)
        n += 1

    # Standalone Unpitched (i.e. not inside a PercussionChord) — these
    # were the off-beat hi-hats etc. in the debug trace.
    for el in list(score.recurse().getElementsByClass(music21.note.Unpitched)):
        site = el.activeSite
        if site is None:
            continue
        new_note = music21.note.Note(_drum_pitch_for(el))
        new_note.duration = el.duration
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
):
    """Load MIDI → music21 Score, patch in the key signature, quantize."""

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

    try:
        score.quantize(
            [4, 8, 12, 16],
            processOffsets=True,
            processDurations=True,
            inPlace=True,
        )
    except Exception:
        logger.exception("quantize failed — score will engrave with raw rhythms")

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


def _progression_to_chordmode(
    progression: "list[str] | None",
    key: str,
    total_bars: int,
) -> Optional[str]:
    """Build a LilyPond ``\\chordmode`` string from a roman-numeral list.

    ``["I", "V", "vi", "IV"]`` in G major and ``total_bars=4`` →
    ``"g1 d1 e1:m c1"``.  When the progression is shorter than the
    bar count it loops; longer progressions are truncated.
    """
    if not progression:
        return None
    try:
        import music21
        k = music21.key.Key(key)
    except Exception:
        logger.warning("could not parse key %r — skipping chord symbols", key)
        return None

    tokens: list = []
    bars_per_chord = max(1, total_bars // max(1, len(progression)))
    # If progression is longer than total_bars, give each at least 1 bar.
    if len(progression) > total_bars:
        progression = progression[:total_bars]
        bars_per_chord = 1

    used_bars = 0
    for raw in progression:
        if used_bars >= total_bars:
            break
        # compose_midi stores progression as a list of (symbol, beats)
        # tuples; the public helper also accepts plain strings.
        sym = raw[0] if isinstance(raw, (tuple, list)) else raw
        try:
            rn = music21.roman.RomanNumeral(sym, k)
        except Exception:
            logger.warning("could not parse roman %r in key %r", sym, key)
            continue
        root = _to_lily_pitch(rn.root().name)
        suffix = _LILY_QUALITY_BY_COMMON_NAME.get(rn.commonName, "")
        # 1 bar at any time-signature == one whole note ("1") in chordmode;
        # LilyPond syncs the ChordNames context to the music staff length.
        tokens.append(f"{root}1{suffix}")
        used_bars += bars_per_chord
    if not tokens:
        return None
    return " ".join(tokens)


def _postprocess_ly(
    ly_src: str,
    *,
    chordmode: Optional[str],
    suppress_tagline: bool = True,
) -> str:
    """Surgical edits on music21's emitted ``.ly`` source:

    1. Replace ``\\paper { }`` with a paper block that disables the
       "Music engraving by LilyPond X.Y" tagline LilyPond appends by
       default.
    2. If ``chordmode`` is provided, inject a ``\\new ChordNames
       \\chordmode { ... }`` block at the top of the score's parallel
       ``<<`` expression so chord symbols engrave above the top staff.
    """
    out = ly_src
    if suppress_tagline:
        out = out.replace(
            "\\paper { }",
            "\\paper { tagline = ##f }",
        )

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
    src = _postprocess_ly(src, chordmode=chordmode)
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
