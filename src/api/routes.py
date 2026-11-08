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
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse

from src.composition import instruments as instruments_mod
from src.daw_integration.generic import block_concat
from src.daw_integration.generic import block_versions
from src.daw_integration.generic import blocks as block_store
from src.daw_integration.generic import library as library_store
from src.daw_integration.generic import library_folders as folder_store
from src.daw_integration.generic import songs as song_store
from src.daw_integration.generic.styles import STYLES

from . import ai_requests, arrangement, service
from .jobs import registry
from .schemas import (
    AiAnswerRequest,
    BlockVersionRequest,
    DescribeRequest,
    EditBlockRequest,
    MixPreviewRequest,
    ProduceBlockRequest,
    ChristmasMixRequest,
    GenerateRequest,
    VideoScoreRequest,
    GeneratePartRequest,
    LibrarySaveRequest,
    FolderCreateRequest,
    FolderItemsRequest,
    FolderMoveRequest,
    FolderReorderRequest,
    FolderUpdateRequest,
    LyricsDraftRequest,
    ParsePromptRequest,
    PhoneticRequest,
    PreviewTakeRequest,
    ReviseRequest,
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
def _core_progression(prog, cap: int = 16) -> list[str]:
    """The genre's chord loop as roman-numeral strings, compressed to its
    smallest repeating unit (presets store the loop tiled across all bars)."""
    romans = [c[0] if isinstance(c, (list, tuple)) else c for c in (prog or [])]
    n = len(romans)
    if not n:
        return []
    for period in range(1, min(cap, n) + 1):
        if n % period == 0 and all(romans[i] == romans[i % period] for i in range(n)):
            return romans[:period]
    return romans[:cap]


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
            "progression": _core_progression(getattr(p, "progression", None)),
            # Per-role progression pools + song-level variants for the
            # section-by-section builder to offer as choices.
            "progressions": arrangement.available_progressions(key),
        })
    out.sort(key=lambda d: d["name"].lower())
    return out


@router.get("/genres")
def list_genres() -> dict:
    """Consolidated, de-duplicated genre catalog for the genre wheel: families
    (with colour + angle) each holding genres that resolve to a song preset +
    a per-section feel preset. Each genre also carries its section availability
    (so the form can seed the section chips)."""
    from src.composition.genres import genre_catalog
    cat = genre_catalog()
    # Attach the per-genre section roster (native arrangement) so the form can
    # seed chips without a second round-trip.
    for fam in cat:
        for g in fam["genres"]:
            g["sections"] = arrangement.available_sections(g["id"])
    return {"families": cat}


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
@router.post("/parse-prompt")
def parse_prompt_route(req: ParsePromptRequest) -> dict:
    """Parse a plain-English song description into a SongPlan (genre, per-section
    presets, key/scale/tempo/swing, instruments) that pre-fills the Generate
    form. Deterministic + rule-based — no model call."""
    from src.composition.nl_parser import parse_prompt
    return parse_prompt(req.prompt or "")


def _describe_job(fn, *args, wait: bool) -> dict:
    """Run an interpreter call inline (``wait``) or as a job the client polls
    at ``/jobs/{id}`` (it can take a while: Claude or a waking local model)."""
    if wait:
        return fn(*args)
    job = registry.create()
    registry.run(job, lambda progress: fn(*args, progress))
    return {"job_id": job.id}


@router.post("/describe")
def describe_route(req: DescribeRequest) -> dict:
    """Plain-English description → a song plan (a /generate body) plus a short
    "here's what I understood". Interpreted by Claude (AI request queue) when
    an answerer is listening, else the local model, else the rules; the
    response's ``interpreter`` says which (src/api/describe.py)."""
    from . import describe
    if not req.text.strip():
        raise HTTPException(400, "Describe the song first")
    return _describe_job(describe.describe, req.text, wait=req.wait)


@router.post("/revise")
def revise_route(req: ReviseRequest) -> dict:
    """The current song plan + plain-English feedback → a revised plan, a
    summary and the list of ``changes``."""
    from . import describe
    if not req.feedback.strip():
        raise HTTPException(400, "Say what should change")
    return _describe_job(describe.revise, req.plan, req.feedback, wait=req.wait)


@router.post("/transcribe")
async def transcribe_route(file: UploadFile = File(...)) -> dict:
    """A voice note → text (the gateway's speech-to-text), for the Create
    screen's describe / feedback box."""
    from . import describe
    data = await file.read()
    if not data:
        raise HTTPException(400, "The recording is empty")
    try:
        text = await asyncio.to_thread(describe.transcribe, data, file.filename or "note.webm")
    except OSError as exc:
        raise HTTPException(503, f"Speech-to-text is unavailable: {exc}")
    return {"text": text}


@router.post("/generate")
def generate(req: GenerateRequest) -> dict:
    if req.genre not in STYLES:
        raise HTTPException(404, f"Unknown genre {req.genre!r}")
    job = registry.create()
    registry.run(job, lambda progress: service.run_generation(req, progress, job.id))
    return {"job_id": job.id}


@router.post("/christmas-mix")
def christmas_mix(req: ChristmasMixRequest) -> dict:
    """Render a seamless mix of generated Christmas songs (one WAV/MP3 at a
    target loudness, with gentle crossfades and a tracklist)."""
    from src.composition import christmas
    bad = [s for s in req.styles if s not in christmas.STYLE_IDS]
    if bad:
        raise HTTPException(422, f"Unknown Christmas style(s) {bad}; use {list(christmas.STYLE_IDS)}")
    if req.count <= 0 and req.total_minutes <= 0:
        raise HTTPException(422, "Give count or total_minutes")
    job = registry.create()
    registry.run(job, lambda progress: service.run_christmas_mix(req, progress, job.id))
    return {"job_id": job.id}


@router.post("/score-video")
def score_video(req: VideoScoreRequest) -> dict:
    """Score a video chapter by chapter (src/api/video_score.py)."""
    if req.genre not in STYLES:
        raise HTTPException(404, f"Unknown genre {req.genre!r}")
    if not req.chapters or req.duration <= 0:
        raise HTTPException(422, "A video score needs a duration and at least one chapter")
    job = registry.create()
    registry.run(job, lambda progress: service.run_video_score(req, progress, job.id))
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


@router.get("/jobs/{job_id}/peaks")
def job_peaks(job_id: str, buckets: int = 400) -> dict:
    """The version's waveform peaks + section start times (Create timeline)."""
    job = registry.get(job_id)
    if job is None or job.status != "done":
        raise HTTPException(404, "Job not found or not finished")
    data = service.job_peaks(job.result, max(16, min(2000, buckets)))
    if data is None:
        raise HTTPException(404, "No audio to derive peaks from")
    return data


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
            "preview_take": b.get("preview_take"),
            # ?v= busts the browser cache when the play source (take vs
            # instrumental) changes, so the card's audio/waveform refresh.
            "audio_url": f"/api/blocks/{quote(name)}/audio?v={quote(str(b.get('preview_take') or 'i'))}",
        })
    return out


@router.get("/blocks/{name}/audio")
def block_audio(name: str) -> FileResponse:
    # Honors a chosen vocal take as the block's preview; else the instrumental.
    p = block_store.active_preview_audio(name)
    if not p:
        raise HTTPException(404, "No audio for block")
    media = "audio/mpeg" if Path(p).suffix == ".mp3" else "audio/wav"
    return _serve(Path(p), media)


@router.post("/blocks/{name}/preview-take")
def set_block_preview_take(name: str, req: PreviewTakeRequest) -> dict:
    """Choose which audio the block plays: a vocal take's mix, or the
    instrumental (``take_id: null``). Non-destructive and reversible."""
    try:
        block_store.set_preview_take(name, req.take_id)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc))
    return {"ok": True, "preview_take": req.take_id}


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


def _block_score_dir(name: str) -> Path:
    """Ensure the block's engraved score is available as loose PDFs and return
    the directory holding ``full_score.pdf`` + ``parts/<Track>.pdf``.

    Engraves once (via the cached score zip) and extracts it, so the full
    score and every instrument part are served from the same single render —
    the in-app viewer can switch tracks without re-engraving."""
    midi = block_store._midi_path(name)
    if not midi.exists():
        raise HTTPException(404, "No MIDI for block")
    safe = block_store._safe_name(name)
    cache_dir = service.API_OUT / "_blocks"
    out_dir = cache_dir / f"{safe}_score"
    if not (out_dir / "full_score.pdf").exists():
        import zipfile
        from src.scoring.pdf_export import export_zip
        zip_path = cache_dir / f"{safe}.score.zip"
        try:
            if not zip_path.exists():
                _, meta = block_store.load_block(name)
                # Chord symbols above the staff for quick reference — from the
                # block's detected per-bar chords (best-effort; export_zip
                # retries without them if they don't align).
                chordmode = None
                try:
                    from src.scoring.pdf_export import chordmode_from_bar_symbols
                    sd = service.score_data(name)
                    chordmode = chordmode_from_bar_symbols(
                        [c.get("symbol") for c in sd.get("chords", [])])
                except Exception:  # noqa: BLE001 — chords are optional
                    chordmode = None
                export_zip(midi, zip_path, tempo=meta.get("tempo"),
                           title=name, chordmode=chordmode)
            out_dir.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(zip_path) as zf:
                zf.extractall(out_dir)
        except Exception as exc:  # noqa: BLE001 — LilyPond optional
            raise HTTPException(503, f"PDF engraving failed: {exc}")
    return out_dir


@router.get("/blocks/{name}/parts")
def block_parts(name: str) -> dict:
    """The score views the viewer can show: the full score plus one entry per
    instrument part. Each carries the inline-PDF URL to open."""
    d = _block_score_dir(name)
    q = quote(name)
    parts = [{"id": "full", "name": "Full score", "url": f"/api/blocks/{q}/pdf/full"}]
    parts_dir = d / "parts"
    if parts_dir.exists():
        for p in sorted(parts_dir.glob("*.pdf")):
            parts.append({
                "id": p.stem,
                "name": p.stem.replace("_", " ").strip(),
                "url": f"/api/blocks/{q}/pdf/part/{quote(p.stem)}",
            })
    return {"parts": parts}


@router.get("/blocks/{name}/pdf/full")
def block_pdf_full(name: str) -> FileResponse:
    """The full score, inline ``application/pdf`` for the in-app viewer."""
    return _serve(_block_score_dir(name) / "full_score.pdf", "application/pdf")


@router.get("/blocks/{name}/pdf/part/{part_id}")
def block_pdf_part(name: str, part_id: str) -> FileResponse:
    """One instrument part's sheet music, inline ``application/pdf``."""
    parts_dir = (_block_score_dir(name) / "parts").resolve()
    candidate = (parts_dir / f"{part_id}.pdf").resolve()
    # Resolve strictly within parts/ so a crafted part_id can't escape the dir.
    if parts_dir not in candidate.parents or not candidate.exists():
        raise HTTPException(404, "No such part")
    return _serve(candidate, "application/pdf")


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


# --------------------------------------------------------------------------
# Block version control — catalog generations/edits, restore any one
# --------------------------------------------------------------------------
@router.get("/blocks/{name}/history")
def block_history(name: str) -> dict:
    """Unified timeline for a block: versions + sung vocal takes, newest first."""
    return block_versions.history(name)


@router.get("/blocks/{name}/versions")
def list_block_versions(name: str) -> dict:
    """All saved versions of a block (newest first) + the active version id."""
    return block_versions.list_versions(name)


@router.post("/blocks/{name}/versions")
def snapshot_block_version(name: str, req: BlockVersionRequest) -> dict:
    """Snapshot the block's current state as a new version."""
    try:
        version = block_versions.snapshot_version(
            name, label=req.label, note=req.note, source="manual")
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc))
    return {"version": version}


@router.post("/blocks/{name}/versions/{version_id}/restore")
def restore_block_version(name: str, version_id: str) -> dict:
    """Make a version the live block (auto-snapshots the current state first)."""
    try:
        return block_versions.restore_version(name, version_id)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc))


@router.delete("/blocks/{name}/versions/{version_id}")
def delete_block_version(name: str, version_id: str) -> dict:
    if not block_versions.delete_version(name, version_id):
        raise HTTPException(404, "Version not found")
    return {"deleted": version_id}


@router.get("/blocks/{name}/versions/{version_id}/preview")
def block_version_preview(name: str, version_id: str) -> FileResponse:
    """The version's preview audio, for A/B listening before restoring."""
    p = block_versions.version_preview_path(name, version_id)
    if not p:
        raise HTTPException(404, "No preview for this version")
    return _serve(p, "audio/mpeg")


@router.get("/blocks/{name}/stems")
def block_stems(name: str) -> FileResponse:
    """Re-render the block with per-instrument stems and zip them. Rendered
    on demand into a temp dir that's deleted after the response is sent."""
    import shutil
    import tempfile
    import zipfile
    from starlette.background import BackgroundTask
    from src.audio_processing.render.pipeline import render_to_audio, style_render_args

    midi = block_store._midi_path(name)
    if not midi.exists():
        raise HTTPException(404, "No MIDI for block")
    tmp = Path(tempfile.mkdtemp(prefix="blockstems_"))
    render = render_to_audio(midi=midi, output_dir=tmp / "r", with_stems=True,
                             **style_render_args(block_store.block_spec(name)))
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


@router.post("/blocks/{name}/mix-preview")
def block_mix_preview(name: str, req: MixPreviewRequest) -> dict:
    """Render a block with a per-track mix + master to a throwaway preview (for
    A/B'ing a mix without saving). Returns the preview audio URL."""
    try:
        key = service.mix_preview(name, track_mix=req.track_mix, master_preset=req.master_preset)
        return {"url": f"/api/mix-previews/{key}"}
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc))


@router.get("/mix-previews/{key}")
def serve_mix_preview(key: str) -> FileResponse:
    return _serve(service.mix_preview_path(key), "audio/mpeg")


@router.get("/blocks/{name}/live-stems")
def block_live_stems(name: str) -> dict:
    """Per-track baseline stems for browser Web Audio live mixing. Returns
    ``{key, duration, tracks:[{name, url}]}`` — each url serves a WAV stem."""
    try:
        d = service.live_stems(name)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc))
    return {
        "key": d["key"], "duration": d["duration"],
        "tracks": [{"name": t["name"],
                    "url": f"/api/live-stems/{d['key']}/{t['file']}"}
                   for t in d["tracks"]],
    }


@router.get("/live-stems/{key}/{track_file:path}")
def serve_live_stem(key: str, track_file: str) -> FileResponse:
    try:
        path = service.live_stem_path(key, track_file)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc))
    mt = "audio/mpeg" if path.suffix == ".mp3" else "audio/wav"
    return _serve(path, mt)


@router.post("/blocks/{name}/produce")
def produce_block(name: str, req: ProduceBlockRequest) -> dict:
    """Producer move: arrange (mute/regenerate) + re-master a block, re-render
    its preview, and return a production score."""
    try:
        return service.produce_block(
            name, mute=req.mute, regenerate=req.regenerate,
            master_preset=req.master_preset, track_mix=req.track_mix, save_as=req.save_as)
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


@router.post("/scan/sheet")
async def scan_sheet_music(file: UploadFile = File(...)) -> dict:
    """Scan a sheet-music image (PNG/JPG photo or scan) → MIDI, saved as a
    block. OMR is slow, so this returns a ``job_id`` to poll like /generate;
    the finished job's ``saved_block`` opens in practice mode / Compose."""
    data = await file.read()
    fname = file.filename or "score.png"
    job = registry.create()
    registry.run(job, lambda progress: service.run_sheet_scan(data, fname, progress, job.id))
    return {"job_id": job.id}


@router.post("/analyze/audio")
async def analyze_audio_upload(file: UploadFile = File(...)) -> dict:
    """Listen to an uploaded song and break down its progression: returns the
    same score-data shape as a block (key, scale, tempo, chord chart) so the
    practice chart + diagrams render it directly, plus a Roman-numeral
    ``progression`` for the 'generate similar' button."""
    data = await file.read()
    try:
        return service.analyze_audio_file(data, filename=file.filename or "song")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"Could not analyze audio: {exc}")


@router.get("/blocks/{name}/notes")
def block_notes_route(name: str) -> dict:
    """A block's notes per track (arrangement format) for loading into the
    workstation's piano-roll editor."""
    try:
        return service.block_notes(name)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(404, f"No notes: {exc}")


@router.get("/blocks/{name}/musicxml")
def block_musicxml_route(name: str) -> FileResponse:
    """Engraved MusicXML for a block — for AlphaTab to render as self-playing
    sheet music."""
    try:
        return _serve(Path(service.block_musicxml(name)),
                      "application/vnd.recordare.musicxml+xml")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(404, f"No musicxml: {exc}")


@router.get("/blocks/{name}/part-audio/{track_index}")
def block_part_audio_route(name: str, track_index: int) -> FileResponse:
    """Isolated (solo) audio for one track of a block, for part playthrough."""
    try:
        return _serve(Path(service.block_part_audio(name, track_index)), "audio/mpeg")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(404, f"No part audio: {exc}")


@router.get("/blocks/{name}/karaoke")
def block_karaoke(name: str) -> dict:
    """Karaoke payload: lead-vocal melody notes (pitch+timing) + lyrics aligned
    to those notes (per-word start/end), for the full-screen karaoke view."""
    try:
        return service.karaoke_data(name)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(404, f"No karaoke data: {exc}")


@router.get("/blocks/{name}/vocal-guide-audio")
def block_vocal_guide_audio(name: str) -> FileResponse:
    """The block's Lead Vocal track rendered alone — the guide melody to sing
    along to in karaoke."""
    try:
        return _serve(Path(service.vocal_guide_audio(name)), "audio/mpeg")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(404, f"No vocal guide audio: {exc}")


@router.get("/blocks/{name}/explain")
def block_explain(name: str) -> dict:
    """'Show under the hood': a teaching breakdown of a block — key/mode and how
    each section relates to it, the chords with their harmonic function, named
    progressions/devices, and why the arrangement does what it does."""
    from src.composition.explain import explain_block
    try:
        return explain_block(name)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(404, f"Can't explain {name!r}: {exc}")


@router.get("/blocks/{name}/score-data")
def block_score_data(name: str) -> dict:
    """Per-bar chords (symbol / Roman / Nashville) + bar timings for the
    practice-mode chord chart and the piano/guitar chord diagrams. Chords are
    detected from the rendered harmony tracks."""
    try:
        return service.score_data(name)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(404, f"No score data: {exc}")


@router.post("/blocks/{name}/lyrics/draft")
def draft_block_lyrics(name: str, req: LyricsDraftRequest) -> dict:
    """Enqueue a lyric-draft request for a Claude Code watch-loop to answer
    (no API key). Returns ``{request_id}``; the client polls
    ``/ai/requests/{id}`` until it's answered.

    Lyrics are written to the song's **structure** (its sections and their bar
    lengths), NOT fitted to a melody — generation is instrumental and the vocal
    melody is composed from the lyrics afterwards (workflow: generate
    instrumental → write lyrics → write the melody to the lyrics)."""
    if not block_store._midi_path(name).exists():
        raise HTTPException(404, "Block not found")
    try:
        _, meta = block_store.load_block(name)
    except Exception:  # noqa: BLE001
        meta = {}
    spec = meta.get("spec") or {}
    ts = meta.get("time_signature") or [4, 4]
    sections = [
        {"role": s.get("role"), "label": s.get("label"),
         "bars": int(s.get("end_bar") or 0) - int(s.get("start_bar") or 0) + 1}
        for s in (spec.get("sections") or [])
    ]
    params = {
        "theme": req.theme or "",
        "genre": spec.get("genre"),
        "key": spec.get("key"),
        "scale": spec.get("scale"),
        "tempo": spec.get("tempo") or meta.get("tempo"),
        "time_signature": [int(ts[0]), int(ts[1])],
        "bars": int(meta.get("bars") or 0),
        # Write the lyric to THIS structure (role + bar length per section). No
        # syllable target — the melody is composed to the lyric afterwards.
        "sections": sections,
        "current_lyrics": meta.get("lyrics") or "",
    }
    rec = ai_requests.enqueue("lyrics", name, params)
    return {"request_id": rec["id"]}


@router.post("/blocks/{name}/melody/compose")
def compose_block_melody(name: str, req: SetLyricsRequest) -> dict:
    """Enqueue a 'compose a vocal melody for these lyrics' request for a
    Claude Code watch-loop. Replaces any existing vocal tracks when applied
    (so it doubles as 'regenerate melody from edited lyrics'). Returns
    ``{request_id}``; poll ``/ai/requests/{id}``."""
    if not block_store._midi_path(name).exists():
        raise HTTPException(404, "Block not found")
    if not req.lyrics.strip():
        raise HTTPException(400, "Lyrics are empty")
    params = service.melody_request_params(name, req.lyrics)
    rec = ai_requests.enqueue("melody", name, params)
    return {"request_id": rec["id"]}


# --- AI request queue (answered by a Claude Code watch-loop) --------------
@router.get("/ai/requests")
def list_ai_requests(status: str | None = None, kind: str | None = None,
                     answerer: str | None = None) -> dict:
    """Pending/answered AI requests. A Claude Code session polls
    ``?status=pending`` (optionally ``&kind=describe,revise&answerer=<name>``),
    composes each answer, and POSTs it back. Polling for pending work is the
    answerer's heartbeat (see ``ai_requests.answerer_alive``)."""
    kinds = {k.strip() for k in (kind or "").split(",") if k.strip()} or None
    if status == "pending":
        ai_requests.beat(answerer or "anon", kinds)
    return {"requests": ai_requests.list_requests(status, kinds)}


@router.post("/ai/requests/{rid}/claim")
def claim_ai_request(rid: str, answerer: str | None = None) -> dict:
    """An answerer takes a pending request before working on it. 409 when it
    is gone or already taken (the app may have fallen back and withdrawn it)."""
    rec = ai_requests.claim(rid, answerer or "")
    if rec is None:
        raise HTTPException(409, "Request is not pending")
    return rec


@router.get("/ai/requests/{rid}")
def get_ai_request(rid: str) -> dict:
    rec = ai_requests.get(rid)
    if rec is None:
        raise HTTPException(404, "Unknown request")
    return rec


@router.post("/ai/requests/{rid}/answer")
def answer_ai_request(rid: str, req: AiAnswerRequest) -> dict:
    rec = ai_requests.get(rid)
    if rec is None:
        raise HTTPException(404, "Unknown request")
    applied = None
    # A "melody" answer is a note plan — apply it straight into the block
    # (write the Lead Vocal / Backing Vocals tracks + re-render).
    if rec.get("kind") == "melody" and req.answer and not req.error:
        try:
            applied = service.apply_melody_plan(
                rec["block"], req.answer, lyrics=rec.get("params", {}).get("lyrics", ""))
        except Exception as exc:  # noqa: BLE001
            ai_requests.answer(rid, None, error=f"melody apply failed: {exc}")
            raise HTTPException(500, f"melody apply failed: {exc}")
    ai_requests.answer(rid, req.answer, error=req.error)
    return {"ok": True, "applied": applied}


@router.post("/clientlog")
def client_log(entry: dict) -> dict:
    """Sink for client-side diagnostics (the Android app POSTs its WebView
    console / fetch errors + apiBase here) so they're readable server-side
    at data/outputs/clientlog.jsonl — no need to be the user's eyes."""
    import json as _json
    import time as _time
    try:
        p = service.API_OUT.parent / "clientlog.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        rec = {"ts": _time.strftime("%Y-%m-%d %H:%M:%S"), **entry}
        with open(p, "a") as f:
            f.write(_json.dumps(rec)[:4000] + "\n")
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True}


@router.get("/app/android")
def download_android_apk() -> FileResponse:
    """Serve the Android APK with the correct package MIME so the tablet's
    installer recognizes it (a bare .apk URL downloads as a generic zip)."""
    apk = service.API_OUT.parent / "AiMusic.apk"
    if not apk.exists():
        raise HTTPException(404, "APK not available")
    return FileResponse(
        str(apk),
        media_type="application/vnd.android.package-archive",
        filename="AiMusic.apk",
    )


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
    section_engines = [se.model_dump() for se in req.section_engines]
    registry.run(job, lambda progress: service.run_block_vocals(
        name, req.lyrics, req.voice, req.engine, progress, job.id,
        req.harmonies, req.clarity, req.phonetic, section_engines))
    return {"job_id": job.id}


@router.get("/blocks/{name}/vocal-guide.mid")
def block_vocal_guide(name: str) -> FileResponse:
    """Download the block's composed vocal melody as a MIDI guide — point your
    DAW's Auto-Tune/Melodyne at it to tune a real take onto the composed line."""
    if not block_store._midi_path(name).exists():
        raise HTTPException(404, "Block not found")
    p = service.vocal_guide_midi(name)
    if p is None:
        raise HTTPException(404, "No composed vocal melody yet — compose a melody first")
    return _serve(p, "audio/midi", download=True)


@router.get("/blocks/{name}/section-voices")
def block_section_voices(name: str) -> dict:
    """Per-section voice info for the per-section engine picker: each section
    with its vocal-line density and a suggested engine (rough for rap-like
    sections). Empty list when the block has no section structure."""
    if not block_store._midi_path(name).exists():
        raise HTTPException(404, "Block not found")
    return {"sections": service.section_voices(name)}


@router.post("/blocks/{name}/autotune")
async def autotune_block(
    name: str,
    file: UploadFile = File(...),
    mode: str = Form("natural"),        # "natural" (correct toward) | "hard" (snap)
    strength: float = Form(0.85),       # natural-mode amount, 0–1
    to_key: bool = Form(False),         # tune to key/scale instead of the melody
) -> dict:
    """Pitch-correct an uploaded/recorded vocal onto the block's composed
    melody (or its key/scale). Returns a job id; poll like a vocal render."""
    import os
    import tempfile
    if not block_store._midi_path(name).exists():
        raise HTTPException(404, "Block not found")
    data = await file.read()
    if not data:
        raise HTTPException(400, "Empty audio upload")
    suffix = os.path.splitext(file.filename or "")[1] or ".wav"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp.write(data)
    tmp.close()
    job = registry.create()
    registry.run(job, lambda progress: service.run_autotune(
        name, tmp.name, progress, job.id, mode=mode, strength=strength, to_key=to_key))
    return {"job_id": job.id}


@router.post("/generate-part")
def generate_part_route(req: GeneratePartRequest) -> dict:
    """Generate ONE DAW-channel part (MIDI note-list + optional rendered WAV)
    that fits the given musical context. Host-agnostic — the VST/DAW bridges
    (Reaper/Ableton/VST3) all call this."""
    try:
        return service.generate_part(req)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.post("/generate-arrangement")
def generate_arrangement_route(req: GeneratePartRequest) -> dict:
    """Generate a full arrangement as ONE multi-track MIDI (a track per part) +
    a rendered mix — import once to lay out every part on its own DAW track."""
    try:
        return service.generate_arrangement(req)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.get("/part-options")
def part_options_route() -> dict:
    """Valid per-part modifier choices (voicing/rhythm/pattern/style/phrase) for
    the plugin's smart dropdown — keyed by target, each with options + default."""
    return service.part_options()


@router.get("/parts/{part_id}/{filename}")
def get_part_file(part_id: str, filename: str) -> FileResponse:
    p = service.part_file(part_id, filename)
    if p is None:
        raise HTTPException(404, "Part artifact not found")
    media = ("audio/midi" if filename.endswith(".mid")
             else "audio/mpeg" if filename.endswith(".mp3") else "audio/wav")
    return _serve(p, media, download=filename.endswith(".mid"))


@router.post("/phonetic")
def make_phonetic(req: PhoneticRequest) -> dict:
    """Auto-generate the editable ARPABET version of a lyric (one bracketed
    group per word) so the user can tweak per-word diction before re-singing."""
    return {"phonetic": service.phonetic_for_lyrics(req.lyrics)}


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
    # Keep the job's real mix (sampled instruments, mix, loudness) as the
    # block's audio instead of a General MIDI re-render of the MIDI.
    audio = paths.get("audio_wav") or paths.get("audio_mp3")
    name = service._save_unique_block(
        block_store, req.name.strip(), pm,
        tempo=res.get("tempo", 120.0),
        time_signature=(int(ts[0]), int(ts[1])),
        bars=res.get("bars", 0), spec=spec, audio_source=audio,
    ) if not req.overwrite else _overwrite_block(req.name.strip(), pm, res, ts, spec, audio)
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


@router.get("/songs/{title}/score-data")
def song_score_data_route(title: str) -> dict:
    """Practice chord chart for a saved song (its blocks concatenated)."""
    try:
        return service.song_score_data(title)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(404, f"No song score data: {exc}")


@router.get("/songs/{title}/audio")
def song_audio_route(title: str) -> FileResponse:
    """Rendered (cached) audio for a saved song, for practice playback."""
    try:
        return _serve(Path(service.ensure_song_preview(title)), "audio/mpeg")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(404, f"No song audio: {exc}")


@router.get("/songs/{title}/audio.wav")
def song_audio_wav_route(title: str) -> FileResponse:
    """Cached WAV for a saved song — used for clean section looping."""
    try:
        return _serve(Path(service.ensure_song_wav(title)), "audio/wav")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(404, f"No song wav: {exc}")


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
# Sheet-music library (saved pieces + their assets)
# --------------------------------------------------------------------------
def _library_entry_urls(entry: dict) -> dict:
    """Enrich a stored entry with the asset URLs the Library screen consumes
    (all resolve to the referenced block's existing endpoints)."""
    name = entry.get("block_name", "")
    q = quote(name)
    return {
        **entry,
        "pdf_url": f"/api/blocks/{q}/pdf/full",
        "pdf_zip_url": f"/api/blocks/{q}/pdf",
        "parts_url": f"/api/blocks/{q}/parts",
        "audio_url": f"/api/blocks/{q}/audio",
        "notes_url": f"/api/blocks/{q}/notes",
        "musicxml_url": f"/api/blocks/{q}/musicxml",
        "score_data_url": f"/api/blocks/{q}/score-data",
    }


@router.get("/library")
def list_library() -> dict:
    """Every entry, each with ``folders`` ([{id, path}]) it's filed in."""
    by_entry = folder_store.folders_by_entry()
    return {"library": [{**_library_entry_urls(e), "folders": by_entry.get(e["id"], [])}
                        for e in library_store.list_entries()]}


@router.post("/library")
def add_to_library(req: LibrarySaveRequest) -> dict:
    if not block_store._midi_path(req.block_name).exists():
        raise HTTPException(404, f"No such block: {req.block_name}")
    try:
        # Check the folder before adding anything; "unfiled" just means none.
        folder = folder_store.get_folder(req.folder)["id"] if req.folder else folder_store.UNFILED
        entry = library_store.add_entry(
            req.block_name, title=req.title,
            collection=req.collection, note=req.note)
        if folder != folder_store.UNFILED:
            folder_store.add_items(folder, [entry["id"]])
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    folders = folder_store.folders_by_entry().get(entry["id"], [])
    return {"saved": entry["id"], "entry": {**_library_entry_urls(entry), "folders": folders}}


# --- Library folders (one per video; membership links, ordered) -----------
def _folder_call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except folder_store.FolderError as exc:
        raise HTTPException(404 if str(exc).startswith(("No folder", "No library entry", "No parent"))
                            else 400, str(exc))


@router.get("/library/folders")
def list_library_folders() -> dict:
    """All folders with item counts (subfolders follow their parent), plus
    the virtual ``unfiled`` folder."""
    return _folder_call(folder_store.list_folders)


@router.post("/library/folders")
def create_library_folder(req: FolderCreateRequest) -> dict:
    return {"folder": _folder_call(folder_store.create_folder, req.name, req.parent, req.description)}


@router.get("/library/folders/{folder_id}")
def get_library_folder(folder_id: str) -> dict:
    """A folder with its entries in track order (``unfiled`` works too)."""
    f = _folder_call(folder_store.get_folder, folder_id)
    by_entry = folder_store.folders_by_entry()
    return {"folder": {**f, "items": [{**_library_entry_urls(e), "folders": by_entry.get(e["id"], [])}
                                      for e in f["items"]]}}


@router.patch("/library/folders/{folder_id}")
def update_library_folder(folder_id: str, req: FolderUpdateRequest) -> dict:
    return {"folder": _folder_call(folder_store.update_folder, folder_id, name=req.name,
                                   description=req.description, parent=req.parent)}


@router.delete("/library/folders/{folder_id}")
def delete_library_folder(folder_id: str) -> dict:
    """Delete a folder; its songs stay in the library (→ Unfiled if in no
    other folder) and its subfolders move to the top level."""
    return _folder_call(folder_store.delete_folder, folder_id)


@router.post("/library/folders/{folder_id}/items")
def add_library_folder_items(folder_id: str, req: FolderItemsRequest) -> dict:
    if not req.entry_ids and not req.block_names:
        raise HTTPException(400, "Give entry_ids and/or block_names.")
    _folder_call(folder_store.get_folder, folder_id)
    ids = list(req.entry_ids)
    for name in req.block_names:
        ids.append(_library_entry_for_block(name))
    return {"folder": _folder_call(folder_store.add_items, folder_id, ids, req.position)}


def _library_entry_for_block(name: str) -> str:
    """The library entry id for a block, adding the block to the library if
    it isn't there yet."""
    try:
        return library_store.get_entry(name)["id"]
    except FileNotFoundError:
        pass
    if not block_store._midi_path(name).exists():
        raise HTTPException(404, f"No such block or library entry: {name}")
    return library_store.add_entry(name)["id"]


@router.delete("/library/folders/{folder_id}/items/{entry_id}")
def remove_library_folder_item(folder_id: str, entry_id: str) -> dict:
    return {"folder": _folder_call(folder_store.remove_item, folder_id, entry_id)}


@router.put("/library/folders/{folder_id}/order")
def reorder_library_folder(folder_id: str, req: FolderReorderRequest) -> dict:
    return {"folder": _folder_call(folder_store.reorder, folder_id, req.entry_ids)}


@router.post("/library/move")
def move_library_entry(req: FolderMoveRequest) -> dict:
    """Move an entry into a folder (out of ``from_folder``, or out of every
    other folder when it's empty); ``to_folder: "unfiled"`` takes it out."""
    return _folder_call(folder_store.move_item, req.entry_id, req.to_folder,
                        req.from_folder, req.position)


@router.post("/library/{entry_id}/favorite")
def library_set_favorite(entry_id: str, favorite: bool = True) -> dict:
    """Set (default) or clear an entry's favorite flag: ?favorite=false."""
    try:
        return {"entry": _library_entry_urls(library_store.set_favorite(entry_id, favorite))}
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc))


@router.delete("/library/{entry_id}")
def delete_library_entry(entry_id: str) -> dict:
    if not library_store.delete_entry(entry_id):
        raise HTTPException(404, "Library entry not found")
    return {"deleted": entry_id}


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


def _overwrite_block(name: str, pm, res: dict, ts, spec: dict | None = None, audio_source=None) -> str:
    block_store.save_block(
        name, pm, tempo=res.get("tempo", 120.0),
        time_signature=(int(ts[0]), int(ts[1])),
        bars=res.get("bars", 0), overwrite=True, spec=spec, audio_source=audio_source,
    )
    return name
