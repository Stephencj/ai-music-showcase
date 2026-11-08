"""Carol backing tracks in several keys at once.

One carol, one Christmas style, a list of keys (default C, D, F, G, Bb plus
the "low voice" and "high voice" presets; src/composition/backing.py): each
key is generated through the normal pipeline (``service.run_generation``)
with the ``backing_track`` (and/or ``guide_melody``) variant, and its MP3 and
timing JSON are kept in ``data/outputs/backing/<carol>/``:

    silent_night_trio_G.mp3          the backing track
    silent_night_trio_G.json         its timing (docs/backing_tracks.md)
    silent_night_trio_G_guide.mp3    with the quiet guide melody (guide_melody / both)
    silent_night_trio_keys.json      the index: every key and voice preset → its files

The same seed is used for every key, so tempo and arrangement match from key
to key. Each render's working folder (WAVs, MIDI) is deleted once its MP3 and
timing are copied out, so only MP3s and JSON stay on disk.
"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUT = PROJECT_ROOT / "data" / "outputs" / "backing"


def _safe(s: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in s)


def render_keys(tune: str, *, genre: str = "christmas_orchestral_full", keys: Optional[list[str]] = None,
                tempo: Optional[float] = None, seed: int = 1, guide_melody: bool = False, both: bool = False,
                length_seconds: Optional[float] = None, arrangement: str = "", target_lufs: float = -16.0,
                out_dir: Optional[Path] = None,
                progress: Optional[Callable[[str, float], None]] = None) -> dict:
    """Render ``tune`` as a backing track in every key of ``keys``.

    Returns {"tune", "style", "out_dir", "renders": [{label, key, variant,
    mp3, timing, seconds, tempo, lyrics}], "index", "files"}. A voice preset
    that lands on a key already rendered points at that key's files.
    """
    from src.api import service
    from src.api.schemas import GenerateRequest
    from src.composition import backing, christmas
    from src.composition.carols import carol

    t = carol(tune)
    if t is None:
        raise ValueError(f"Unknown carol {tune!r}")
    if genre not in christmas.STYLE_IDS:
        raise ValueError(f"Unknown Christmas style {genre!r}")
    progress = progress or (lambda msg, frac: None)
    style = christmas.substyle(genre)
    out = Path(out_dir or DEFAULT_OUT / t.id)
    out.mkdir(parents=True, exist_ok=True)
    others = [v for v in christmas.variants(arrangement) if v not in backing.BACKING_VARIANTS]
    kinds = ["backing_track", "guide_melody"] if both else ["guide_melody" if guide_melody else "backing_track"]
    wanted = backing.resolve_keys(t, list(keys or []))
    tonics = list(dict.fromkeys(tonic for _label, tonic in wanted))
    minor = "minor" in t.scale
    done: dict[tuple[str, str], dict] = {}
    steps = len(tonics) * len(kinds)
    n = 0
    for tonic in tonics:
        for kind in kinds:
            progress(f"{t.title} in {tonic}{' minor' if minor else ''}"
                     f"{' (guide)' if kind == 'guide_melody' else ''}…", n / max(1, steps))
            name = _safe(f"{t.id}_{style}_{tonic}{'m' if minor else ''}{'_guide' if kind == 'guide_melody' else ''}")
            job_id = f"backing-{name}"
            req = GenerateRequest(genre=genre, seed=int(seed), tune=t.id, key=tonic, tempo=tempo,
                                  length_seconds=length_seconds, arrangement=",".join(others + [kind]),
                                  with_pdf=False, with_stems=False, target_lufs=target_lufs)
            try:
                res = service.run_generation(req, lambda *a, **k: None, job_id)
                paths = res["_paths"]
                mp3 = out / f"{name}.mp3"
                shutil.copyfile(paths["audio_mp3"], mp3)
                timing = json.loads(Path(paths["timing"]).read_text())
                timing["audio"] = mp3.name
                tpath = out / f"{name}.json"
                backing.write_timing(timing, tpath)
            finally:
                shutil.rmtree(service.API_OUT / job_id, ignore_errors=True)   # WAVs, MIDI: keep MP3 + JSON only
            done[(tonic, kind)] = {"key": tonic + ("m" if minor else ""), "variant": kind, "mp3": str(mp3),
                                   "timing": str(tpath), "seconds": timing["duration"], "tempo": res["tempo"],
                                   "lyrics": timing["lyrics"]["available"]}
            n += 1
    renders = []
    for label, tonic in wanted:
        for kind in kinds:
            renders.append({"label": label, **done[(tonic, kind)]})
    index = out / f"{_safe(t.id)}_{style}_keys.json"
    result = {"tune": t.id, "title": t.title, "style": style, "genre": genre, "seed": int(seed),
              "out_dir": str(out), "renders": renders}
    index.write_text(json.dumps(result, indent=1))
    result["index"] = str(index)
    result["files"] = sorted({r["mp3"] for r in renders} | {r["timing"] for r in renders})
    progress("Done.", 1.0)
    return result
