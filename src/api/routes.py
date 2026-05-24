"""REST routes for the music engine. Mounted under ``/api`` on the existing
FastAPI app (so it inherits the token auth middleware).

Audio/MIDI/PDF artifacts are streamed with Starlette's ``FileResponse``,
which honours HTTP Range requests — that (plus the compact MP3 previews)
is what makes long songs play in the iPhone WebView."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from urllib.parse import quote

import pretty_midi
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, StreamingResponse

from src.composition import instruments as instruments_mod
from src.daw_integration.generic import block_concat
from src.daw_integration.generic import blocks as block_store
from src.daw_integration.generic import songs as song_store
from src.daw_integration.generic.styles import STYLES

from . import arrangement, service
from .jobs import registry
from .schemas import (
    EditBlockRequest,
    GenerateRequest,
    LyricsDraftRequest,
    RenameRequest,
    SaveBlockFromJobRequest,
    SetLyricsRequest,
    SongRenderRequest,
    SongSaveRequest,
    SplitRequest,
    TagsRequest,
    VocalsRequest,
)

logger = logging.getLogger("ai_music_studio.api.routes")

router = APIRouter(prefix="/api")


# --------------------------------------------------------------------------
# Catalog
# --------------------------------------------------------------------------
@router.get("/presets")
def list_presets() -> list[dict]:
    out = []
    for key, p in STYLES.items():
        out.append({
            "id": key,
            "name": getattr(p, "name", key),
            "tempo": getattr(p, "tempo", None),
            "key": getattr(p, "key", None),
            "scale": getattr(p, "scale", None),
            "time_signature": list(getattr(p, "time_signature", (4, 4))),
            "default_bars": getattr(p, "default_bars", None),
            "default_instruments": list(getattr(p, "default_instruments", []) or []),
            "sections": arrangement.available_sections(key),
        })
    out.sort(key=lambda d: d["name"].lower())
    return out


@router.get("/instruments")
def list_instruments() -> list[dict]:
    fams = []
    for fam in instruments_mod.FAMILIES:
        members = instruments_mod.instruments_for_family(fam)
        fams.append({
            "family": fam,
            "label": instruments_mod.FAMILY_LABELS.get(fam, fam),
            "instruments": [
                {"id": i.id, "label": i.label, "role": i.role,
                 "default": i.id in _DEFAULT_INSTRUMENT_IDS}
                for i in members
            ],
        })
    return fams


@router.get("/master-presets")
def list_master_presets() -> list[str]:
    from src.audio_processing.render import MASTER_PRESETS
    return list(MASTER_PRESETS.keys())


# A small, musical default tick-set for the UI (used to pre-check boxes).
_DEFAULT_INSTRUMENT_IDS = {"drum_kit", "electric_bass", "piano"}


# --------------------------------------------------------------------------
# Generation
# --------------------------------------------------------------------------
@router.post("/generate")
def generate(req: GenerateRequest) -> dict:
    if req.genre not in STYLES:
        raise HTTPException(404, f"Unknown genre {req.genre!r}")
    job = registry.create()
    registry.run(job, lambda progress: service.run_generation(req, progress, job.id))
    return {"job_id": job.id}


@router.get("/jobs/{job_id}")
def job_status(job_id: str) -> dict:
    job = registry.get(job_id)
    if job is None:
        raise HTTPException(404, "Unknown job")
    payload = {
        "id": job.id,
        "status": job.status,
        "progress": job.progress,
        "message": job.message,
        "error": job.error,
    }
    if job.status == "done":
        res = dict(job.result)
        paths = res.pop("_paths", {})
        res.pop("_split", None)
        res.pop("_spec", None)
        base = f"/api/jobs/{job.id}"
        res["urls"] = {
            "midi": f"{base}/midi" if paths.get("midi") else None,
            "audio": f"{base}/audio" if (paths.get("audio_mp3") or paths.get("audio_wav")) else None,
            "audio_hifi": f"{base}/audio.wav" if paths.get("audio_wav") else None,
            "pdf": f"{base}/pdf" if paths.get("pdf") else None,
            "vocal": f"{base}/vocal" if paths.get("vocal_mp3") else None,
        }
        payload["result"] = res
    return payload


@router.get("/jobs/{job_id}/events")
async def job_events(job_id: str) -> StreamingResponse:
    async def gen():
        while True:
            job = registry.get(job_id)
            if job is None:
                yield _sse({"error": "unknown job"})
                return
            yield _sse({"status": job.status, "progress": job.progress,
                        "message": job.message, "error": job.error})
            if job.status in ("done", "error"):
                return
            await asyncio.sleep(0.3)

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.get("/jobs/{job_id}/midi")
def job_midi(job_id: str) -> FileResponse:
    return _serve(_job_path(job_id, "midi"), "audio/midi", download=True)


@router.get("/jobs/{job_id}/audio")
def job_audio(job_id: str) -> FileResponse:
    p = _job_path(job_id, "audio_mp3", fallback="audio_wav")
    media = "audio/mpeg" if p.suffix == ".mp3" else "audio/wav"
    return _serve(p, media)


@router.get("/jobs/{job_id}/audio.wav")
def job_audio_hifi(job_id: str) -> FileResponse:
    return _serve(_job_path(job_id, "audio_wav"), "audio/wav")


@router.get("/jobs/{job_id}/pdf")
def job_pdf(job_id: str) -> FileResponse:
    return _serve(_job_path(job_id, "pdf"), "application/zip", download=True)


# --------------------------------------------------------------------------
# Blocks
# --------------------------------------------------------------------------
@router.get("/blocks")
def list_blocks() -> list[dict]:
    out = []
    for b in block_store.list_blocks():
        name = b.get("name")
        out.append({
            "name": name,
            "bars": b.get("bars"),
            "tempo": b.get("tempo"),
            "time_signature": b.get("time_signature"),
            "n_notes": b.get("n_notes"),
            "duration_seconds": b.get("duration_seconds"),
            "instruments": b.get("instruments"),
            "created": b.get("created"),
            "tags": b.get("tags", []),
            "spec": b.get("spec"),
            "lyrics": b.get("lyrics", ""),
            "vocal_takes": b.get("_vocal_takes", 0),
            "has_preview": bool(b.get("_preview_path") or b.get("_wav_path")),
            "audio_url": f"/api/blocks/{quote(name)}/audio",
        })
    return out


@router.get("/blocks/{name}/audio")
def block_audio(name: str) -> FileResponse:
    p = block_store.ensure_preview_audio(name)
    if not p:
        raise HTTPException(404, "No audio for block")
    media = "audio/mpeg" if Path(p).suffix == ".mp3" else "audio/wav"
    return _serve(Path(p), media)


@router.get("/blocks/{name}/midi")
def block_midi(name: str) -> FileResponse:
    p = block_store._midi_path(name)
    if not p.exists():
        raise HTTPException(404, "No MIDI for block")
    return _serve(p, "audio/midi", download=True)


@router.get("/blocks/{name}/wav")
def block_wav(name: str) -> FileResponse:
    p = block_store._wav_path(name)
    if not p.exists():
        raise HTTPException(404, "No WAV for block")
    return _serve(p, "audio/wav", download=True)


@router.get("/blocks/{name}/pdf")
def block_pdf(name: str) -> FileResponse:
    """Engrave the block to a PDF score (full score + parts), cached."""
    midi = block_store._midi_path(name)
    if not midi.exists():
        raise HTTPException(404, "No MIDI for block")
    from src.scoring.pdf_export import export_zip
    cache_dir = service.API_OUT / "_blocks"
    cache_dir.mkdir(parents=True, exist_ok=True)
    out = cache_dir / f"{block_store._safe_name(name)}.score.zip"
    if not out.exists():
        try:
            _, meta = block_store.load_block(name)
            export_zip(midi, out, tempo=meta.get("tempo"), title=name)
        except Exception as exc:  # noqa: BLE001 — LilyPond optional
            raise HTTPException(503, f"PDF engraving failed: {exc}")
    return _serve(out, "application/zip", download=True)


@router.get("/blocks/{name}/vocals")
def list_block_vocals(name: str) -> dict:
    """Saved sung takes for a block, newest first (id, created, engine,
    voice, harmonies, lyrics, files). The client builds artifact URLs from
    the ``files`` keys via ``/blocks/{name}/vocals/{id}/{role}``."""
    return {"takes": block_store.list_vocal_takes(name)}


@router.get("/blocks/{name}/vocals/{take_id}/{role}")
def block_vocal_take_file(name: str, take_id: str, role: str) -> FileResponse:
    p = block_store.vocal_take_file(name, take_id, role)
    if not p:
        raise HTTPException(404, "Take artifact not found")
    if role == "score":
        return _serve(p, "application/zip", download=True)
    media = "audio/wav" if p.suffix == ".wav" else "audio/mpeg"
    return _serve(p, media)


@router.delete("/blocks/{name}/vocals/{take_id}")
def delete_block_vocal_take(name: str, take_id: str) -> dict:
    if not block_store.delete_vocal_take(name, take_id):
        raise HTTPException(404, "Take not found")
    return {"ok": True}


@router.get("/blocks/{name}/stems")
def block_stems(name: str) -> FileResponse:
    """Re-render the block with per-instrument stems and zip them. Rendered
    on demand into a temp dir that's deleted after the response is sent."""
    import shutil
    import tempfile
    import zipfile
    from starlette.background import BackgroundTask
    from src.audio_processing.render.pipeline import render_to_audio

    midi = block_store._midi_path(name)
    if not midi.exists():
        raise HTTPException(404, "No MIDI for block")
    tmp = Path(tempfile.mkdtemp(prefix="blockstems_"))
    render = render_to_audio(midi=midi, output_dir=tmp / "r",
                             with_stems=True, master_preset="default")
    safe = block_store._safe_name(name)
    archive = tmp / f"{safe}_stems.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(render.mix_path, arcname="mix.wav")
        for track, p in (render.stem_paths or {}).items():
            try:
                zf.write(p, arcname=f"{track}.wav")
            except OSError:
                pass
    return FileResponse(
        str(archive), media_type="application/zip", filename=f"{safe}_stems.zip",
        background=BackgroundTask(shutil.rmtree, str(tmp), ignore_errors=True),
    )


@router.get("/blocks/{name}/peaks")
def block_peaks(name: str) -> dict:
    """Small normalized waveform-peak array for the card thumbnail."""
    peaks = block_store.block_peaks(name)
    if peaks is None:
        raise HTTPException(404, "No audio to derive peaks from")
    return {"peaks": peaks}


@router.post("/blocks/{name}/rename")
def rename_block(name: str, req: RenameRequest) -> dict:
    try:
        new_name = block_store.rename_block(name, req.new_name)
        return {"name": new_name}
    except FileExistsError as exc:
        raise HTTPException(409, str(exc))
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.post("/blocks/{name}/tags")
def set_block_tags(name: str, req: TagsRequest) -> dict:
    try:
        return {"tags": block_store.set_tags(name, req.tags)}
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc))


@router.post("/blocks/{name}/edit")
def edit_block(name: str, req: EditBlockRequest) -> dict:
    """Mute and/or regenerate specific instrument tracks of a block, saving
    over it (default) or as a new block (``save_as``)."""
    try:
        new_name = service.edit_block(
            name, mute=req.mute, regenerate=req.regenerate, save_as=req.save_as,
        )
        return {"name": new_name}
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.get("/voices")
def list_voices() -> dict:
    from src.models.vocals import studio_available
    studio = studio_available()
    engines = ["rough"] + (["studio"] if studio else [])
    studio_voices: list[str] = []
    if studio:
        from src.models.vocals.studio import list_speakers
        studio_voices = list_speakers()
    return {"voices": service.list_voices(), "engines": engines, "studio_voices": studio_voices}


@router.get("/blocks/{name}/melody")
def block_melody(name: str) -> dict:
    try:
        return service.melody_info(name)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(404, f"No melody: {exc}")


@router.post("/blocks/{name}/lyrics/draft")
def draft_block_lyrics(name: str, req: LyricsDraftRequest) -> dict:
    try:
        return {"lyrics": service.draft_lyrics(name, req.theme)}
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"Lyric draft failed: {exc}")


@router.post("/blocks/{name}/lyrics")
def set_block_lyrics(name: str, req: SetLyricsRequest) -> dict:
    try:
        block_store.set_lyrics(name, req.lyrics)
        return {"ok": True}
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc))


@router.post("/blocks/{name}/vocals")
def render_block_vocals(name: str, req: VocalsRequest) -> dict:
    if not block_store._midi_path(name).exists():
        raise HTTPException(404, "Block not found")
    if not req.lyrics.strip():
        raise HTTPException(400, "Lyrics are empty")
    job = registry.create()
    registry.run(job, lambda progress: service.run_block_vocals(
        name, req.lyrics, req.voice, req.engine, progress, job.id, req.harmonies))
    return {"job_id": job.id}


@router.get("/jobs/{job_id}/vocal")
def job_vocal_stem(job_id: str) -> FileResponse:
    p = _job_path(job_id, "vocal_mp3")
    return _serve(p, "audio/mpeg")


@router.post("/blocks/from-job")
def save_block_from_job(req: SaveBlockFromJobRequest) -> dict:
    job = registry.get(req.job_id)
    if job is None or job.status != "done":
        raise HTTPException(404, "Job not found or not finished")
    paths = job.result.get("_paths", {})
    midi = paths.get("midi")
    if not midi or not Path(midi).exists():
        raise HTTPException(400, "Job has no MIDI to save")
    pm = pretty_midi.PrettyMIDI(str(midi))
    res = job.result
    ts = res.get("time_signature", [4, 4])
    spec = res.get("_spec")
    name = service._save_unique_block(
        block_store, req.name.strip(), pm,
        tempo=res.get("tempo", 120.0),
        time_signature=(int(ts[0]), int(ts[1])),
        bars=res.get("bars", 0), spec=spec,
    ) if not req.overwrite else _overwrite_block(req.name.strip(), pm, res, ts, spec)
    return {"name": name}


@router.post("/jobs/{job_id}/split")
def split_job_into_blocks(job_id: str, req: SplitRequest | None = None) -> dict:
    """Carve a finished generation into one block per section (mix & match).
    The sections are auto-tagged (collection) with ``tag`` or, by default,
    the generation's ``genre seed`` so they group together in the library."""
    job = registry.get(job_id)
    if job is None or job.status != "done":
        raise HTTPException(404, "Job not found or not finished")
    midi = job.result.get("_paths", {}).get("midi")
    ctx = job.result.get("_split")
    if not midi or not Path(midi).exists() or not ctx:
        raise HTTPException(400, "Job has no splittable MIDI")
    res = job.result
    tag = (req.tag if req and req.tag else None) or (
        f"{res.get('genre')} {res.get('seed')}" if res.get("genre") and res.get("seed") else None
    )
    pm = pretty_midi.PrettyMIDI(str(midi))
    ts = ctx["time_signature"]
    names = block_concat.split_into_section_blocks(
        pm, ctx["sections"], tempo=ctx["tempo"],
        time_signature=(int(ts[0]), int(ts[1])), tag=tag,
        spec_base=res.get("_spec"),
    )
    return {"section_blocks": names, "tag": tag}


@router.delete("/blocks/{name}")
def delete_block(name: str) -> dict:
    block_store.delete_block(name)
    return {"deleted": name}


# --------------------------------------------------------------------------
# Songs (timelines of blocks)
# --------------------------------------------------------------------------
@router.get("/songs")
def list_songs() -> dict:
    return {"songs": song_store.list_song_timelines()}


@router.get("/songs/{title}")
def load_song(title: str) -> dict:
    try:
        return song_store.load_song_timeline(title)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(404, f"Song not found: {exc}")


@router.post("/songs")
def save_song(req: SongSaveRequest) -> dict:
    try:
        path = song_store.save_song_timeline(req.title, req.timeline, overwrite=req.overwrite)
        return {"saved": req.title, "path": str(path)}
    except FileExistsError as exc:
        raise HTTPException(409, str(exc))


@router.post("/songs/render")
def render_song(req: SongRenderRequest) -> dict:
    """Render the timeline into the full deliverable set (HQ audio + MIDI +
    PDF) as a background job — same shape as /generate, so the /jobs/{id}
    status + artifact endpoints serve it identically."""
    if not req.timeline:
        raise HTTPException(400, "Timeline is empty")
    job = registry.create()
    registry.run(job, lambda progress: service.run_song_render(
        req.timeline, req.with_pdf, progress, job.id))
    return {"job_id": job.id}


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def _sse(obj: dict) -> str:
    return f"data: {json.dumps(obj)}\n\n"


def _job_path(job_id: str, key: str, fallback: str | None = None) -> Path:
    job = registry.get(job_id)
    if job is None or job.status != "done":
        raise HTTPException(404, "Job not found or not finished")
    paths = job.result.get("_paths", {})
    p = paths.get(key) or (paths.get(fallback) if fallback else None)
    if not p or not Path(p).exists():
        raise HTTPException(404, f"Artifact {key!r} not available")
    return Path(p)


def _serve(path: Path, media_type: str, *, download: bool = False) -> FileResponse:
    headers = None
    if download:
        headers = {"Content-Disposition": f'attachment; filename="{path.name}"'}
    return FileResponse(str(path), media_type=media_type, headers=headers)


def _overwrite_block(name: str, pm, res: dict, ts, spec: dict | None = None) -> str:
    block_store.save_block(
        name, pm, tempo=res.get("tempo", 120.0),
        time_signature=(int(ts[0]), int(ts[1])),
        bars=res.get("bars", 0), overwrite=True, spec=spec,
    )
    return name
