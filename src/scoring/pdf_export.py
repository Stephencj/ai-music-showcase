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


def _normalize_percussion(score) -> int:
    """Rewrite ``PercussionChord`` elements as regular ``Chord`` notes.

    music21's LilyPond translator silently drops ``PercussionChord``
    when emitting ``.ly`` source — drum staves end up with bar lines
    and no notes, and LilyPond then skips the "zero-duration score"
    so no PDF is produced. Converting each PercussionChord into a
    pitched Chord (same pitches, same duration) makes drums render
    as a rhythmic notation on a treble staff. Not authentic drum-set
    notation, but readable and consistent with the rest of the score.

    Returns the number of elements converted (for logging).
    """
    import music21
    n = 0
    for el in list(
        score.recurse().getElementsByClass(music21.percussion.PercussionChord)
    ):
        pitches = list(el.pitches)
        ql = el.duration.quarterLength
        replacement = (
            music21.chord.Chord(pitches, quarterLength=ql)
            if pitches else music21.note.Rest(quarterLength=ql)
        )
        site = el.activeSite
        if site is not None:
            site.replace(el, replacement)
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


def score_to_full_pdf(score, out_path: "Path | str") -> Path:
    """Render the multi-stave conductor score to a single PDF.

    ``music21.Stream.write("lily.pdf", fp=X)`` writes the LilyPond
    source to ``X`` and then engraves the actual PDF at ``X + ".pdf"``,
    returning that path. To get a clean ``foo.pdf`` we pass the *stem*
    (no extension) and trust the return value.
    """

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    stem = str(out.with_suffix(""))
    actual = score.write("lily.pdf", fp=stem)
    pdf_path = Path(str(actual))
    # If the stem already had ".pdf" stripped, the returned file is the
    # canonical PDF. Move it to the caller's requested path so the .ly
    # intermediate is the only leftover next to it.
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


def score_to_part_pdfs(score, out_dir: "Path | str") -> dict:
    """Engrave one PDF per instrument part.

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
            pdf_path = score_to_full_pdf(single, out / f"{unique}.pdf")
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
) -> Path:
    """End-to-end: MIDI → engraved PDFs → single ZIP file.

    The ZIP layout is::

        full_score.pdf
        parts/<TrackName>.pdf
        parts/<OtherTrack>.pdf
        ...

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

    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        full_pdf = score_to_full_pdf(score, td_path / "full_score.pdf")
        parts = score_to_part_pdfs(score, td_path / "parts")

        tmp_zip = td_path / "_export.zip"
        with zipfile.ZipFile(tmp_zip, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(full_pdf, arcname="full_score.pdf")
            for _, pdf_path in parts.items():
                zf.write(pdf_path, arcname=f"parts/{pdf_path.name}")
        shutil.move(str(tmp_zip), str(out_zip))

    return out_zip
