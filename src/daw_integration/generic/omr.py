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

import subprocess
import sys
from pathlib import Path
from typing import Optional

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


def _oemer_cmd(image: Path, out_dir: Path) -> list[str]:
    # oemer defaults to onnxruntime (no --use-tf); --without-deskew is faster
    # and avoids a deskew failure mode on clean digital renders.
    return [
        sys.executable, "-c", _OEMER_RUNNER,
        str(image), "-o", str(out_dir), "--without-deskew",
    ]


def scan_to_musicxml(image_path: str, out_dir: Path, timeout: int = 600) -> Path:
    """Run oemer on an image and return the produced MusicXML path."""
    out_dir.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        _oemer_cmd(Path(image_path), out_dir),
        capture_output=True, text=True, timeout=timeout,
    )
    # oemer writes <stem>.musicxml into out_dir (or alongside the image).
    stem = Path(image_path).stem
    candidates = [
        out_dir / f"{stem}.musicxml",
        Path(image_path).with_suffix(".musicxml"),
        *out_dir.glob("*.musicxml"),
    ]
    for c in candidates:
        if c.exists():
            return c
    raise RuntimeError(
        "oemer produced no MusicXML.\n"
        f"stdout: {proc.stdout[-500:]}\nstderr: {proc.stderr[-500:]}"
    )


def scan_to_midi(image_path: str, out_dir: Path, timeout: int = 600) -> dict:
    """Scan a sheet-music image → MIDI + basic musical metadata.

    Returns ``{midi_path, key, scale, tempo, bars, time_signature}``.
    """
    import music21 as m21

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

    tempo: Optional[float] = None
    for mm in score.recurse().getElementsByClass("MetronomeMark"):
        if mm.number:
            tempo = float(mm.number)
            break

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
