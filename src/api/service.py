"""Generation orchestration — the thin layer that calls the SAME engine
functions the Gradio buttons call, with explicit parameters instead of a
shared global. Returns a result dict with server-side artifact paths under
``_paths`` (routes.py turns those into client URLs)."""

from __future__ import annotations

import logging
import random
from pathlib import Path

logger = logging.getLogger("ai_music_studio.api.service")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
API_OUT = PROJECT_ROOT / "data" / "outputs" / "api"

# Keep only the most-recent N job output dirs so renders don't grow
# unbounded and fill the disk (each HQ mix is several MB).
_KEEP_RECENT_JOBS = 30


def _prune_old_job_dirs(keep: int = _KEEP_RECENT_JOBS) -> None:
    try:
        dirs = [p for p in API_OUT.iterdir() if p.is_dir()]
    except FileNotFoundError:
        return
    if len(dirs) <= keep:
        return
    import shutil
    for old in sorted(dirs, key=lambda p: p.stat().st_mtime)[:-keep]:
        shutil.rmtree(old, ignore_errors=True)


def run_generation(req, progress, job_id: str) -> dict:
    """Compose → HQ render → (optional) PDF → (optional) save/split blocks.

    ``progress(message, frac)`` is the job's progress callback. ``req`` is a
    GenerateRequest. Raises on hard failures (unknown genre, render error);
    PDF failure is soft (LilyPond may be absent).
    """
    import pretty_midi

    from src.daw_integration.generic.styles import STYLES
    from src.composition.song_composer import compose_song
    from src.audio_processing.render.pipeline import render_to_audio
    from src.scoring.pdf_export import export_zip
    from src.daw_integration.generic import blocks as block_store
    from src.daw_integration.generic import block_concat
    from .arrangement import build_sections

    genre = req.genre
    preset = STYLES.get(genre)
    if preset is None:
        raise ValueError(f"Unknown genre {genre!r}")

    seed = int(req.seed) if req.seed else random.randint(1, 1_000_000)
    eff_key = req.key or preset.key
    eff_scale = req.scale or preset.scale
    eff_tempo = float(req.tempo) if req.tempo else float(preset.tempo)
    ts = (int(preset.time_signature[0]), int(preset.time_signature[1]))

    # Always a concrete section list so split-into-blocks uses the exact
    # boundaries compose_song laid the song down with.
    secs = build_sections(genre, req.sections)

    job_dir = API_OUT / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    _prune_old_job_dirs()

    progress("Composing arrangement…", 0.10)
    out = compose_song(
        genre=genre,
        sections=secs,
        seed=seed,
        enabled_instruments=tuple(req.instruments) or None,
        key=req.key, scale=req.scale, tempo=req.tempo,
        bars=req.bars, swing=req.swing,
        output_dir=job_dir,
        skip_audio=True,            # we render HQ below; skip the low-fi pass
    )
    midi_path = Path(out["midi_path"])
    # The section list we passed is authoritative for length — compose_song's
    # returned "bars" reflects the preset default, not the actual arrangement.
    total_bars = sum(s["end_bar"] - s["start_bar"] + 1 for s in secs)

    progress("Rendering high-quality audio…", 0.45)
    render = render_to_audio(
        midi=midi_path,
        output_dir=job_dir / "render",
        with_stems=bool(req.with_stems),
        master_preset=(req.master_preset or "default"),
        style_name=genre,
    )
    wav_path = Path(render.mix_path)
    mp3_path: Path | None = job_dir / "mix.mp3"
    if not block_store.write_preview_mp3(wav_path, mp3_path):
        mp3_path = None

    pdf_path: Path | None = None
    if req.with_pdf:
        progress("Engraving PDF score…", 0.80)
        try:
            pdf_path = export_zip(
                midi_path, job_dir / "score.zip",
                key=eff_key, scale=eff_scale, tempo=eff_tempo,
                title=f"{preset.name} ({seed})", bars=total_bars,
            )
        except Exception as exc:  # noqa: BLE001 — LilyPond optional
            logger.warning("PDF export failed for job %s: %s", job_id, exc)
            pdf_path = None

    saved_block: str | None = None
    section_blocks: list[str] = []
    if req.save_as_block or req.split_into_blocks:
        pm = pretty_midi.PrettyMIDI(str(midi_path))
        if req.save_as_block:
            progress("Saving block…", 0.92)
            saved_block = _save_unique_block(
                block_store, (req.block_name or preset.name).strip() or preset.name,
                pm, tempo=eff_tempo, time_signature=ts, bars=total_bars,
            )
        if req.split_into_blocks:
            progress("Splitting sections into blocks…", 0.96)
            section_blocks = block_concat.split_into_section_blocks(
                pm, secs, tempo=eff_tempo, time_signature=ts,
            )

    progress("Done.", 1.0)
    return {
        "seed": seed,
        "genre": genre,
        "bars": total_bars,
        "key": eff_key,
        "scale": eff_scale,
        "tempo": eff_tempo,
        "time_signature": list(ts),
        "summary": out.get("summary", ""),
        "sections": [
            {"label": s["label"], "role": s["role"],
             "bars": s["end_bar"] - s["start_bar"] + 1}
            for s in secs
        ],
        "saved_block": saved_block,
        "section_blocks": section_blocks,
        "_paths": {
            "midi": str(midi_path),
            "audio_mp3": str(mp3_path) if mp3_path else None,
            "audio_wav": str(wav_path),
            "pdf": str(pdf_path) if pdf_path else None,
        },
        # Context for post-hoc "save as block" / "split into sections" so the
        # UI can let the user decide after listening.
        "_split": {
            "tempo": eff_tempo,
            "time_signature": list(ts),
            "sections": [
                {"start_bar": s["start_bar"], "end_bar": s["end_bar"],
                 "label": s["label"], "role": s["role"]}
                for s in secs
            ],
        },
        # Generation provenance stored on saved blocks → enables
        # per-instrument regenerate and "Edit in Generate".
        "_spec": {
            "genre": genre,
            "key": eff_key,
            "scale": eff_scale,
            "tempo": eff_tempo,
            "time_signature": list(ts),
            "seed": seed,
            "swing": float(req.swing) if req.swing is not None else None,
            "instruments": list(req.instruments),
            "sections": [
                {"start_bar": s["start_bar"], "end_bar": s["end_bar"],
                 "label": s["label"], "role": s["role"]}
                for s in secs
            ],
            "section": None,
        },
    }


def run_song_render(timeline: list[dict], with_pdf: bool,
                    progress, job_id: str) -> dict:
    """Render a Compose-Song timeline into the FULL deliverable set — the
    same one-shot the Generate/block flow produces: concatenated MIDI, HQ
    FluidSynth audio (+ MP3 preview) and a PDF score. Mirrors
    run_generation so the /jobs/{id} status + artifact endpoints serve it
    identically."""
    from src.daw_integration.generic import block_concat
    from src.daw_integration.generic import blocks as block_store
    from src.audio_processing.render.pipeline import render_to_audio
    from src.scoring.pdf_export import export_zip

    if not timeline:
        raise ValueError("Timeline is empty")

    progress("Assembling timeline…", 0.10)
    pm, info = block_concat.concat_blocks(timeline)

    job_dir = API_OUT / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    _prune_old_job_dirs()
    midi_path = job_dir / "song.mid"
    pm.write(str(midi_path))

    progress("Rendering high-quality audio…", 0.45)
    render = render_to_audio(
        midi=midi_path, output_dir=job_dir / "render",
        with_stems=False, master_preset="default",
    )
    wav_path = Path(render.mix_path)
    mp3_path: Path | None = job_dir / "song.mp3"
    if not block_store.write_preview_mp3(wav_path, mp3_path):
        mp3_path = None

    pdf_path: Path | None = None
    if with_pdf:
        progress("Engraving PDF score…", 0.80)
        try:
            pdf_path = export_zip(
                midi_path, job_dir / "score.zip",
                tempo=_first_block_tempo(timeline), title="Song",
            )
        except Exception as exc:  # noqa: BLE001 — LilyPond optional
            logger.warning("song PDF export failed for %s: %s", job_id, exc)
            pdf_path = None

    progress("Done.", 1.0)
    return {
        "kind": "song",
        "info": {
            "duration_seconds": info.get("duration_seconds"),
            "n_instruments": info.get("n_instruments"),
            "n_notes": info.get("n_notes"),
            "summary": info.get("summary", ""),
        },
        "_paths": {
            "midi": str(midi_path),
            "audio_mp3": str(mp3_path) if mp3_path else None,
            "audio_wav": str(wav_path),
            "pdf": str(pdf_path) if pdf_path else None,
        },
    }


def _first_block_tempo(timeline: list[dict]):
    """Tempo to engrave the score at — the first block's (concat's seed
    tempo). None lets export_zip fall back."""
    from src.daw_integration.generic import blocks as block_store
    for t in timeline:
        name = t.get("block_name")
        if not name:
            continue
        try:
            _, meta = block_store.load_block(name)
            return float(meta["tempo"]) if meta.get("tempo") else None
        except Exception:  # noqa: BLE001
            return None
    return None


def _regenerate_pm(spec: dict):
    """Re-run the generation at a fresh seed (same preset/key/scale/tempo/
    sections, so harmonically compatible) and return the PrettyMIDI — sliced
    to the block's section when it was a split part."""
    import random
    import pretty_midi
    from src.composition.song_composer import compose_song
    from src.daw_integration.generic import block_concat

    out = compose_song(
        genre=spec["genre"],
        sections=spec.get("sections"),
        seed=random.randint(1, 1_000_000),
        enabled_instruments=tuple(spec.get("instruments") or ()) or None,
        key=spec.get("key"), scale=spec.get("scale"), tempo=spec.get("tempo"),
        swing=spec.get("swing"),
        output_dir=API_OUT / "_regen",
        skip_audio=True,
    )
    pm = pretty_midi.PrettyMIDI(str(out["midi_path"]))
    sec = spec.get("section")
    if sec:
        ts = spec.get("time_signature") or [4, 4]
        pm = block_concat.slice_pm_by_bars(
            pm, int(sec["start_bar"]), int(sec["end_bar"]),
            float(spec["tempo"]), (int(ts[0]), int(ts[1])),
        )
    return pm


def edit_block(name: str, *, mute=None, regenerate=None, save_as=None) -> str:
    """Apply an edit to a block: drop muted instrument tracks and/or
    re-roll specific instrument tracks (regenerate, needs provenance).
    Saves over the original (default) or as a new block when ``save_as`` is
    given. Returns the resulting block name."""
    import pretty_midi
    from src.daw_integration.generic import blocks as block_store

    mute_set = set(mute or [])
    regen_set = set(regenerate or [])
    pm, meta = block_store.load_block(name)
    spec = meta.get("spec")

    regen_tracks: dict[str, object] = {}
    if regen_set:
        if not spec:
            raise ValueError("Block has no generation info to regenerate from.")
        new_pm = _regenerate_pm(spec)
        for inst in new_pm.instruments:
            regen_tracks.setdefault(inst.name, inst)

    ts = meta.get("time_signature") or [4, 4]
    out = pretty_midi.PrettyMIDI(initial_tempo=float(meta.get("tempo") or 120.0))
    out.time_signature_changes = [pretty_midi.TimeSignature(int(ts[0]), int(ts[1]), 0.0)]
    for inst in pm.instruments:
        if inst.name in mute_set:
            continue
        src = regen_tracks[inst.name] if (inst.name in regen_set and inst.name in regen_tracks) else inst
        ni = pretty_midi.Instrument(program=int(src.program), is_drum=bool(src.is_drum), name=src.name)
        ni.notes = [pretty_midi.Note(velocity=int(n.velocity), pitch=int(n.pitch),
                                     start=float(n.start), end=float(n.end)) for n in src.notes]
        out.instruments.append(ni)

    if sum(len(i.notes) for i in out.instruments) == 0:
        raise ValueError("That edit would leave the block empty.")

    if save_as and save_as.strip():
        target = _unique_block_name(block_store, save_as.strip())
    else:
        target = name
    block_store.save_block(
        target, out, tempo=float(meta.get("tempo") or 120.0),
        time_signature=(int(ts[0]), int(ts[1])), bars=int(meta.get("bars") or 0),
        overwrite=True, spec=spec, tags=meta.get("tags"),
    )
    return target


def _unique_block_name(block_store, base: str) -> str:
    existing = {b.get("name") for b in block_store.list_blocks()}
    name, n = base, 1
    while name in existing:
        n += 1
        name = f"{base} {n}"
    return name


def _save_unique_block(block_store, base_name: str, pm, *,
                       tempo: float, time_signature, bars: int,
                       spec: dict | None = None) -> str:
    name = _unique_block_name(block_store, base_name)
    block_store.save_block(name, pm, tempo=float(tempo),
                           time_signature=time_signature, bars=int(bars),
                           overwrite=False, spec=spec)
    return name
