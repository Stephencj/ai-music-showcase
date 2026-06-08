"""Optical Music Recognition: a sheet-music image/PDF → MIDI.

Wraps the `oemer` deep-learning OMR engine (onnxruntime backend — the same
runtime the vocal SVS uses, so no new runtime). oemer turns a score image into
MusicXML; music21 then renders that to MIDI and gives us key / tempo / bar
counts so the result can be saved as a normal block and opened in practice
mode like anything else.

First run downloads oemer's model checkpoints (~100 MB) into the package dir;
subsequent runs are offline.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger("ai_music_studio.omr")

# oemer 0.1.5 still uses NumPy aliases (np.int, np.float, …) that were removed
# in NumPy 2.x, which the rest of the project requires. Rather than edit the
# installed package (fragile — regenerated on reinstall), we launch oemer in a
# subprocess whose startup restores those aliases, then hand off to its CLI.
# Robust across reinstalls and keeps OMR isolated from the API process.
_OEMER_RUNNER = (
    "import numpy as np\n"
    "for _a, _t in {'int': int, 'float': float, 'bool': bool,"
    " 'object': object, 'str': str, 'complex': complex}.items():\n"
    "    if not hasattr(np, _a): setattr(np, _a, _t)\n"
    "import sys\n"
    "sys.argv = ['oemer'] + sys.argv[1:]\n"
    "from oemer.ete import main\n"
    "main()\n"
)


def _oemer_cmd(image: Path, out_dir: Path, deskew: bool) -> list[str]:
    # oemer defaults to onnxruntime (no --use-tf). Deskew is oemer's own
    # rotation-correction step — helpful for phone photos, but it can misfire
    # on perfectly-axis-aligned digital renders, hence the --without-deskew
    # fallback strategy below.
    cmd = [sys.executable, "-c", _OEMER_RUNNER, str(image), "-o", str(out_dir)]
    if not deskew:
        cmd.append("--without-deskew")
    return cmd


def _run_oemer(image: Path, out_dir: Path, deskew: bool, timeout: int):
    """One oemer attempt into its own dir. Returns the MusicXML path or None.

    Each attempt gets a fresh output dir so a stale .musicxml from a prior
    attempt can't be mistaken for this one's success.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        proc = subprocess.run(
            _oemer_cmd(image, out_dir, deskew),
            capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return None, "timed out"
    xmls = list(out_dir.glob("*.musicxml"))
    if xmls:
        return xmls[0], ""
    return None, (proc.stderr or proc.stdout or "")[-300:]


def _gentle_clean(image_path: str, dest: Path) -> Optional[str]:
    """Last-resort rescue: even out glare + knock down moiré WITHOUT hard
    binarising (which breaks oemer's staff detection). Only used when oemer
    fails on the raw image — e.g. a very dark / low-contrast photo. Returns the
    cleaned PNG path, or None if OpenCV/PIL isn't usable."""
    try:
        import cv2
        import numpy as np
        from PIL import Image, ImageOps
        im = ImageOps.exif_transpose(Image.open(image_path)).convert("L")
        g = np.array(im)
        g = cv2.bilateralFilter(g, 9, 75, 75)
        g = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(g)
        cv2.imwrite(str(dest), g)
        return str(dest)
    except Exception as exc:  # noqa: BLE001
        logger.warning("OMR gentle-clean failed: %s", exc)
        return None


def scan_to_musicxml(image_path: str, out_dir: Path, timeout: int = 600) -> Path:
    """Recognise a score image → MusicXML, trying oemer-native strategies in
    order and stopping at the first that yields output.

    Empirically oemer recognises the *raw* image best — pre-cleaning (binarise
    / threshold) tends to break its internal staff detection — so cleanup is a
    last resort only. Order: deskew-on (phone photos), then deskew-off (clean
    digital renders), then a gently-cleaned rescue for low-contrast captures.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    raw = image_path
    cleaned = _gentle_clean(image_path, out_dir / "cleaned.png")
    attempts = [
        ("raw + deskew", raw, True),
        ("raw, no deskew", raw, False),
    ]
    if cleaned:
        attempts.append(("cleaned rescue", cleaned, False))

    errors = []
    for i, (label, img, deskew) in enumerate(attempts):
        xml, err = _run_oemer(Path(img), out_dir / f"try{i}", deskew, timeout)
        if xml is not None:
            logger.info("OMR succeeded via strategy %r", label)
            return xml
        logger.info("OMR strategy %r produced nothing", label)
        errors.append(f"[{label}] {err}")

    raise RuntimeError(
        "oemer produced no MusicXML after all strategies.\n" + "\n".join(errors)
    )


def scan_to_midi(image_path: str, out_dir: Path, timeout: int = 600) -> dict:
    """Scan a sheet-music image → MIDI + basic musical metadata.

    Returns ``{midi_path, key, scale, tempo, bars, time_signature}``.
    """
    import music21 as m21
    import pretty_midi

    xml = scan_to_musicxml(image_path, out_dir, timeout=timeout)
    score = m21.converter.parse(str(xml))

    midi_path = out_dir / f"{Path(image_path).stem}.mid"
    score.write("midi", fp=str(midi_path))

    # Key (music21's analysis), tempo, bar count, time signature.
    key_name, scale_name = "C", "major"
    try:
        k = score.analyze("key")
        key_name = k.tonic.name.replace("-", "b")
        scale_name = "minor" if k.mode == "minor" else "major"
    except Exception:
        pass

    # Tempo MUST match the written MIDI's embedded tempo: the block preview is
    # rendered straight from this MIDI (note times already baked at that tempo),
    # while the practice chart derives bar timings from the block's tempo field.
    # If they disagree the play-along cursor drifts. Read it back from the MIDI
    # so the two are always consistent (music21 uses the score's metronome mark
    # if present, else 120).
    tempo: Optional[float] = None
    try:
        _pm = pretty_midi.PrettyMIDI(str(midi_path))
        _tempos = _pm.get_tempo_changes()[1]
        if len(_tempos):
            tempo = float(_tempos[0])
    except Exception:
        pass

    ts = [4, 4]
    tss = score.recurse().getElementsByClass("TimeSignature")
    if tss:
        ts = [int(tss[0].numerator), int(tss[0].denominator)]

    try:
        parts = score.parts
        bars = len(parts[0].getElementsByClass("Measure")) if parts else 0
    except Exception:
        bars = 0

    return {
        "midi_path": str(midi_path),
        "musicxml_path": str(xml),
        "key": key_name,
        "scale": scale_name,
        "tempo": tempo or 100.0,
        "bars": bars,
        "time_signature": ts,
    }
