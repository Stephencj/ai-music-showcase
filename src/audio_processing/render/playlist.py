"""Seamless playlist mixes: N generated songs crossfaded into one file.

Built for long background videos (an hour of Christmas ambience): each song
is generated through the normal pipeline (``service.run_generation``),
levelled to the same loudness (render/loudness.py, BS.1770), and joined with
gentle equal-power crossfades into one WAV and/or MP3 at the target loudness
(YouTube normalises to about -14 LUFS; -16 suits background listening). A
tracklist with start times comes back too (handy as video chapters).

``plan_mix`` varies the songs so a long mix doesn't repeat itself: styles
rotate (never the same style twice in a row), keys differ from the previous
song, carols aren't repeated until every one has played, original tunes are
mixed in, and every song gets its own seed (so its own tempo and arrangement).

The mix is streamed to disk song by song (only the crossfade tail stays in
memory), so an hour-long mix doesn't need gigabytes of RAM; each song's own
render folder is deleted once it's in the mix.
"""

from __future__ import annotations

import json
import logging
import shutil
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from .loudness import integrated_lufs, level

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUT = PROJECT_ROOT / "data" / "outputs" / "playlists"
SAMPLE_RATE = 44100


@dataclass
class MixTrack:
    genre: str
    seed: int
    tune: str = "original"
    key: Optional[str] = None
    length_seconds: float = 180.0
    arrangement: str = ""

    def request(self) -> dict:
        return {"genre": self.genre, "seed": self.seed, "tune": self.tune, "key": self.key,
                "length_seconds": self.length_seconds, "arrangement": self.arrangement or None}


@dataclass
class MixResult:
    files: dict = field(default_factory=dict)
    tracks: list = field(default_factory=list)       # [{title, genre, start, seconds, ...}]
    seconds: float = 0.0
    lufs: float = 0.0


def plan_mix(*, total_minutes: float = 0.0, count: int = 0, styles: Optional[list[str]] = None,
             tunes: Optional[list[str]] = None, originals: float = 0.4, track_seconds: tuple = (150, 240),
             seed: int = 1, arrangement: str = "") -> list[MixTrack]:
    """A varied running order. Give ``count`` songs or ``total_minutes``.

    ``styles``: Christmas style ids to rotate (default all six). ``tunes``:
    carol ids to draw from (default every carol); ``originals`` is the share
    of original tunes. ``track_seconds``: (shortest, longest) song length.
    """
    from src.composition import christmas
    from src.composition.carols import CAROLS

    rng = np.random.default_rng(zlib.crc32(f"{seed}|christmas mix".encode()))
    styles = [s for s in (styles or list(christmas.STYLE_IDS)) if s in christmas.STYLE_IDS] \
        or list(christmas.STYLE_IDS)
    pool = [t for t in (tunes or list(CAROLS)) if t in CAROLS]
    lo, hi = float(min(track_seconds)), float(max(track_seconds))
    if count <= 0:
        minutes = total_minutes if total_minutes > 0 else 30.0
        count = max(1, int(round(minutes * 60.0 / ((lo + hi) / 2))))
    out: list[MixTrack] = []
    bag: list[str] = []
    order: list[str] = []
    prev_key = None
    for i in range(count):
        if not order:
            order = list(rng.permutation(styles))
            if out and len(order) > 1 and order[0] == out[-1].genre:
                order.append(order.pop(0))              # never the same style twice in a row
        genre = str(order.pop(0))
        if pool and rng.random() >= originals:
            if not bag:
                bag = list(rng.permutation(pool))
            tune = str(bag.pop(0))
        else:
            tune = "original"
        song_seed = int(rng.integers(1, 1_000_000))
        keys = christmas.STYLE_DEFAULTS[christmas.substyle(genre)]["keys"]
        key = str(rng.choice([k for k in keys if k != prev_key] or list(keys)))
        prev_key = key
        out.append(MixTrack(genre=genre, seed=song_seed, tune=tune, key=key,
                            length_seconds=float(round(lo + (hi - lo) * rng.random())), arrangement=arrangement))
    return out


def _fades(n: int) -> tuple[np.ndarray, np.ndarray]:
    """Equal-power fade-out / fade-in curves of ``n`` samples."""
    x = np.linspace(0.0, np.pi / 2, n, dtype=np.float32)
    return np.cos(x), np.sin(x)


def _ceiling(audio: np.ndarray, ceiling_db: float = -1.0) -> np.ndarray:
    peak = float(np.abs(audio).max()) if audio.size else 0.0
    lim = 10 ** (ceiling_db / 20)
    return audio * (lim / peak) if peak > lim else audio


def render_mix(tracks: list[MixTrack], *, name: str = "christmas-mix", out_dir: Optional[Path] = None,
               crossfade: float = 4.0, target_lufs: float = -16.0, formats: tuple = ("mp3",),
               progress: Optional[Callable[[str, float], None]] = None) -> MixResult:
    """Generate every track and join them with crossfades into one file.

    Each song is levelled to ``target_lufs`` before joining (so the mix holds
    one loudness from end to end), then the crossfades are kept under a
    -1 dBFS ceiling. ``formats``: "mp3" (320 kbps) and/or "wav" (24-bit).
    """
    import soundfile as sf

    from src.api import service
    from src.api.schemas import GenerateRequest
    from src.daw_integration.generic import blocks as block_store

    progress = progress or (lambda msg, frac: None)
    out_dir = Path(out_dir or DEFAULT_OUT)
    out_dir.mkdir(parents=True, exist_ok=True)
    safe = "".join(c if c.isalnum() or c in "-_ " else "_" for c in name).strip() or "christmas-mix"
    wav_path = out_dir / f"{safe}.wav"
    xf = int(round(max(0.0, crossfade) * SAMPLE_RATE))
    result = MixResult()
    tail: Optional[np.ndarray] = None
    written = 0
    energy = 0.0                                     # Σ duration × 10^(LUFS/10), for the mix's loudness
    with sf.SoundFile(str(wav_path), "w", samplerate=SAMPLE_RATE, channels=2, subtype="PCM_24") as out:
        for i, tr in enumerate(tracks):
            progress(f"Song {i + 1} of {len(tracks)}…", i / max(1, len(tracks)))
            job_id = f"mix-{safe}-{i + 1}"
            req = GenerateRequest(**{k: v for k, v in tr.request().items() if v is not None},
                                  with_pdf=False, with_stems=False, target_lufs=target_lufs)
            res = service.run_generation(req, lambda *a, **k: None, job_id)
            audio, sr = sf.read(res["_paths"]["audio_wav"], always_2d=True)
            shutil.rmtree(service.API_OUT / job_id, ignore_errors=True)    # keep only the mix
            audio = audio.T.astype(np.float32)
            if sr != SAMPLE_RATE:
                import librosa
                audio = librosa.resample(audio, orig_sr=sr, target_sr=SAMPLE_RATE)
            audio, _ = level(audio, SAMPLE_RATE, target_lufs)
            # Trim the ring-out's silent tail so songs flow into each other.
            env = np.abs(audio).max(axis=0)
            nz = np.nonzero(env > 10 ** (-60 / 20))[0]
            if nz.size:
                audio = audio[:, : nz[-1] + 1]
            length = audio.shape[1]
            lufs = integrated_lufs(audio, SAMPLE_RATE) if length > SAMPLE_RATE else target_lufs
            energy += length * 10 ** (lufs / 10)
            start = written
            if tail is not None and xf:
                n = min(tail.shape[1], audio.shape[1] // 2)
                fo, fi = _fades(n)
                head = _ceiling(tail[:, tail.shape[1] - n:] * fo + audio[:, :n] * fi)
                out.write(np.concatenate([tail[:, : tail.shape[1] - n], head], axis=1).T)
                written += tail.shape[1]
                audio = audio[:, n:]
                start = written - n
            keep = min(xf, audio.shape[1] // 2) if i < len(tracks) - 1 else 0
            body = audio[:, : audio.shape[1] - keep]
            out.write(_ceiling(body).T)
            written += body.shape[1]
            tail = audio[:, audio.shape[1] - keep:] if keep else None
            result.tracks.append({
                "n": i + 1, "start": round(max(0, start) / SAMPLE_RATE, 1), "title": res.get("tune_title") or "",
                "genre": tr.genre, "key": res.get("key"), "tempo": res.get("tempo"), "seed": res.get("seed"),
                "tune": res.get("tune"), "seconds": round(length / SAMPLE_RATE, 1),
            })
        if tail is not None:
            out.write(_ceiling(tail).T)
            written += tail.shape[1]
    progress("Encoding…", 0.97)
    # Every song was levelled to the target, so the mix's loudness is their
    # duration-weighted energy average (no need to read an hour back in).
    total = sum(t["seconds"] for t in result.tracks) * SAMPLE_RATE
    result.lufs = round(10 * np.log10(energy / total), 1) if total else target_lufs
    result.seconds = round(written / SAMPLE_RATE, 1)
    if "mp3" in formats:
        mp3 = out_dir / f"{safe}.mp3"
        if block_store.write_preview_mp3(wav_path, mp3, bitrate="320k"):
            result.files["mp3"] = str(mp3)
    if "wav" in formats:
        result.files["wav"] = str(wav_path)
    else:
        wav_path.unlink(missing_ok=True)
    listing = out_dir / f"{safe}.json"
    listing.write_text(json.dumps({"tracks": result.tracks, "seconds": result.seconds, "lufs": result.lufs,
                                   "crossfade": crossfade}, indent=2))
    result.files["tracklist"] = str(listing)
    progress("Done.", 1.0)
    return result


def chapters(tracks: list[dict]) -> str:
    """YouTube-style chapter lines ("0:00 Silent Night")."""
    lines = []
    for t in tracks:
        s = int(t["start"])
        stamp = f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"
        lines.append(f"{stamp} {t['title'] or t['genre']}")
    return "\n".join(lines)
