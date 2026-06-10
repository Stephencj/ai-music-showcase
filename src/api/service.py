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


def _instrumental_only(ids, fallback=None):
    """Drop vocal-family instruments. Song generation is **instrumental-first**:
    a generated song carries no vocal line — the sung melody is composed later
    from the lyrics (workflow: generate instrumental → write lyrics → write the
    melody to the lyrics). Returns a tuple of ids, or ``None`` to defer to the
    composer's defaults. When stripping empties the selection, falls back to
    ``fallback`` (also de-vocalised)."""
    from src.composition.instruments import INSTRUMENT_REGISTRY

    def is_vocal(i):
        inst = INSTRUMENT_REGISTRY.get(i)
        return inst is not None and getattr(inst, "family", None) == "vocal"

    kept = [i for i in (ids or []) if not is_vocal(i)]
    if kept:
        return tuple(kept)
    fb = [i for i in (fallback or []) if not is_vocal(i)]
    return tuple(fb) or None


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
    # boundaries compose_song laid the song down with. Per-role preset overrides
    # (multi-preset songs) are attached here as section["preset_id"].
    secs = build_sections(genre, req.sections, getattr(req, "section_presets", None))

    job_dir = API_OUT / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    _prune_old_job_dirs()

    progress("Composing arrangement…", 0.10)
    out = compose_song(
        genre=genre,
        sections=secs,
        seed=seed,
        # instrumental-first: never bake in a vocal track (added later from lyrics)
        enabled_instruments=_instrumental_only(req.instruments, preset.default_instruments),
        key=req.key, scale=req.scale, tempo=req.tempo,
        bars=req.bars, swing=req.swing,
        progression=(list(req.progression) or None),
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

    # Generation provenance (also persisted on the saved block) → per-instrument
    # regenerate, "Edit in Generate", and the exact realized chord progression
    # for the Practice chart.
    block_spec = {
        "genre": genre,
        "key": eff_key,
        "scale": eff_scale,
        "tempo": eff_tempo,
        "time_signature": list(ts),
        "seed": seed,
        "swing": float(req.swing) if req.swing is not None else None,
        "instruments": list(req.instruments),
        "section_presets": dict(getattr(req, "section_presets", None) or {}),
        "sections": [
            {"start_bar": s["start_bar"], "end_bar": s["end_bar"],
             "label": s["label"], "role": s["role"],
             **({"preset_id": s["preset_id"]} if s.get("preset_id") else {})}
            for s in secs
        ],
        "progression": out.get("progression") or [],
        "section": None,
    }

    saved_block: str | None = None
    section_blocks: list[str] = []
    if req.save_as_block or req.split_into_blocks:
        pm = pretty_midi.PrettyMIDI(str(midi_path))
        if req.save_as_block:
            progress("Saving block…", 0.92)
            saved_block = _save_unique_block(
                block_store, (req.block_name or preset.name).strip() or preset.name,
                pm, tempo=eff_tempo, time_signature=ts, bars=total_bars,
                spec=block_spec,
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
        # per-instrument regenerate, "Edit in Generate", and the realized
        # chord progression for the Practice chart.
        "_spec": block_spec,
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


# ---------------------------------------------------------------------------
# Vocals
# ---------------------------------------------------------------------------
def melody_info(name: str) -> dict:
    """Syllable-helper data for a block: notes per phrase + total. Uses the
    SAME lead-selection + monophonic reduction as the vocal render
    (select_vocal_tracks → monophonic_line), so the phrase syllable counts
    match the melody that actually gets sung — lyrics fitted to them line up."""
    import pretty_midi
    from src.daw_integration.generic import blocks as block_store
    from src.models.vocals.lyrics import (
        monophonic_line, phrase_syllable_counts, select_vocal_tracks,
    )
    pm = pretty_midi.PrettyMIDI(str(block_store._midi_path(name)))
    lead, _harms = select_vocal_tracks(pm)
    notes = monophonic_line(lead)
    return {
        "total_notes": len(notes),
        "phrase_syllables": phrase_syllable_counts(notes),
        "has_lead": bool(notes),
    }


def _normalize_scan_image(data: bytes, filename: str) -> str:
    """Save uploaded sheet-music bytes as a PNG for oemer, preserving the image
    as much as possible. We *only* normalise the container format and correct
    EXIF rotation (phone photos) — resizing, bordering or thresholding a clean
    scan was observed to break oemer's staff detection, so we don't touch the
    pixels otherwise. Returns the temp path."""
    import tempfile
    import io
    from PIL import Image, ImageOps

    try:
        im = Image.open(io.BytesIO(data))
        im.load()
    except Exception as exc:
        raise ValueError(
            f"Couldn't read {filename!r} as an image. Upload a PNG or JPG photo "
            f"or scan of the score (PDF/HEIC aren't supported yet). ({exc})"
        )
    im = ImageOps.exif_transpose(im)
    if im.mode not in ("RGB", "L"):
        im = im.convert("RGB")
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
    im.save(tmp.name)
    tmp.close()
    return tmp.name


def run_sheet_scan(data: bytes, filename: str, progress, job_id: str) -> dict:
    """Background job: scan a sheet-music image → MIDI → saved block.

    Saves the recognised score as a normal block (so it opens in practice mode
    and Compose like anything else). Returns the block name + detected key/tempo.
    OMR is slow (~1–2 min) and input-sensitive; failures surface as job errors.
    """
    import os
    import tempfile
    from pathlib import Path
    import pretty_midi
    from src.daw_integration.generic import blocks as block_store
    from src.daw_integration.generic.omr import scan_to_midi

    progress("Preparing image…", 0.05)
    img_path = _normalize_scan_image(data, filename)
    out_dir = Path(tempfile.mkdtemp())
    try:
        progress("Reading the score — this can take a minute…", 0.15)
        meta = scan_to_midi(img_path, out_dir)

        progress("Building MIDI block…", 0.75)
        pm = pretty_midi.PrettyMIDI(meta["midi_path"])
        ts = meta["time_signature"]
        spec = {
            "source": "omr",
            "key": meta["key"], "scale": meta["scale"],
            "tempo": meta["tempo"], "time_signature": ts,
            "sections": [],
        }
        # Prefer the OCR'd title for the block name; fall back to the filename.
        title = (meta.get("title") or "").strip()
        base = title or os.path.splitext(os.path.basename(filename))[0] or "Scanned score"
        block_name = base if title else f"Scan {base}"
        name = _save_unique_block(
            block_store, block_name, pm,
            tempo=meta["tempo"], time_signature=ts, bars=meta["bars"], spec=spec,
        )

        progress("Rendering preview…", 0.9)
        try:
            block_store.ensure_preview_audio(name)
        except Exception as exc:  # noqa: BLE001 — block still usable without preview
            logger.warning("scan preview render failed for %s: %s", name, exc)

        progress("Done.", 1.0)
        return {
            "saved_block": name,
            "key": meta["key"], "scale": meta["scale"],
            "tempo": meta["tempo"], "bars": meta["bars"],
            "n_notes": sum(len(i.notes) for i in pm.instruments),
        }
    finally:
        for p in (img_path,):
            try:
                os.unlink(p)
            except OSError:
                pass


def analyze_audio_file(data: bytes, filename: str = "song") -> dict:
    """Analyze raw uploaded audio bytes into score-data (key/tempo/chords) plus
    a Roman-numeral ``progression`` for 'generate similar'. Writes to a temp
    file because librosa/audioread decode from a path."""
    import os
    import tempfile
    from src.daw_integration.generic.audio_analysis import (
        analyze_audio, progression_romans,
    )

    suffix = os.path.splitext(filename)[1] or ".wav"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        tmp.write(data)
        tmp.flush()
        tmp.close()
        score = analyze_audio(tmp.name)
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
    score["progression"] = progression_romans(score)
    return score


def block_notes(name: str) -> dict:
    """A block's notes per track in the workstation's arrangement format
    (notes as [pitch, start_beat, dur_beat], beats = quarter notes), so the
    DAW can load a scanned/saved block into editable MIDI clips for the
    piano-roll editor — same shape as /api/generate-arrangement."""
    from src.daw_integration.generic import blocks as block_store

    pm, meta = block_store.load_block(name)
    spec = meta.get("spec") or {}
    tempo = float(spec.get("tempo") or meta.get("tempo") or 120.0)
    ts = meta.get("time_signature") or spec.get("time_signature") or [4, 4]
    spb = 60.0 / tempo  # seconds per quarter-note beat
    tracks = []
    for inst in pm.instruments:
        notes = [
            [int(n.pitch), round(n.start / spb, 4), round((n.end - n.start) / spb, 4)]
            for n in inst.notes
        ]
        tracks.append({
            "track": inst.name or ("Drums" if inst.is_drum else "Track"),
            "is_drum": bool(inst.is_drum),
            "notes": notes,
        })
    return {
        "tempo": tempo,
        "bars": int(meta.get("bars") or spec.get("bars") or 0),
        "time_signature": [int(ts[0]), int(ts[1])],
        "key": spec.get("key") or meta.get("key") or "C",
        "scale": spec.get("scale") or meta.get("scale") or "major",
        "tracks": tracks,
    }


def score_data(name: str) -> dict:
    """Per-bar chord chart + bar timings for a block. Chords are detected from
    the rendered harmony tracks (see chord_analysis.extract_score_data) so the
    chart reflects what's actually in the audio. Consumed by practice mode and
    the piano/guitar chord diagrams."""
    from src.daw_integration.generic import blocks as block_store
    from src.daw_integration.generic.chord_analysis import extract_score_data

    pm, meta = block_store.load_block(name)
    return extract_score_data(pm, meta)


def block_musicxml(name: str) -> str:
    """Engraved-quality MusicXML for a block (cached), for AlphaTab to render as
    real, self-playing sheet music. Uses the same MIDI→score conversion (key
    signature + quantization) the PDFs use."""
    from src.daw_integration.generic import blocks as block_store
    from src.scoring.pdf_export import midi_to_score

    midi = block_store._midi_path(name)
    if not midi.exists():
        raise ValueError("no MIDI for block")
    cache = block_store.BLOCKS_DIR / f"{block_store._safe_name(name)}.musicxml"
    if cache.exists() and cache.stat().st_mtime >= midi.stat().st_mtime:
        return str(cache)

    _pm, meta = block_store.load_block(name)
    spec = meta.get("spec") or {}
    score = midi_to_score(
        midi,
        key=spec.get("key") or meta.get("key") or "C",
        scale=spec.get("scale") or meta.get("scale") or "major",
        tempo=float(spec.get("tempo") or meta.get("tempo") or 120.0),
        title=name,
    )
    score.write("musicxml", fp=str(cache))
    return str(cache)


def block_part_audio(name: str, track_index: int) -> str:
    """Render (and cache) a single track of a block in isolation, so a part can
    be played through on its own in practice mode. Returns the MP3 path."""
    import tempfile
    import pretty_midi
    from src.daw_integration.generic import blocks as block_store
    from src.audio_processing.render.pipeline import render_to_audio

    midi_src = block_store._midi_path(name)
    pm, _meta = block_store.load_block(name)
    if track_index < 0 or track_index >= len(pm.instruments):
        raise ValueError(f"track {track_index} out of range")

    cache = block_store.BLOCKS_DIR / f"{block_store._safe_name(name)}.part{track_index}.mp3"
    if cache.exists() and (not midi_src.exists()
                           or cache.stat().st_mtime >= midi_src.stat().st_mtime):
        return str(cache)

    # Single-instrument MIDI (absolute note times carry the timing).
    solo = pretty_midi.PrettyMIDI()
    solo.instruments.append(pm.instruments[track_index])
    tmp = Path(tempfile.mkdtemp())
    midi_path = tmp / "part.mid"
    solo.write(str(midi_path))
    render = render_to_audio(midi=midi_path, output_dir=tmp / "render",
                             with_stems=False, master_preset="default")
    if not block_store.write_preview_mp3(Path(render.mix_path), cache):
        raise RuntimeError("could not render part preview")
    return str(cache)


def karaoke_data(name: str) -> dict:
    """Karaoke payload for a block: the lead-vocal melody (pitch + timing) and
    the lyrics aligned to those notes (per-word start/end seconds), for the
    full-screen karaoke view's highlighted lyrics + scrolling pitch lane."""
    from src.daw_integration.generic import blocks as block_store
    from src.models.vocals.lyrics import (
        align_words_to_notes, monophonic_line, select_vocal_tracks,
    )

    pm, meta = block_store.load_block(name)
    spec = meta.get("spec") or {}
    lead, _harms = select_vocal_tracks(pm)
    notes = monophonic_line(lead)
    note_list = [[int(p), round(s, 4), round(e, 4)] for (p, s, e) in notes]

    # Strip [Section] header lines so they aren't sung/highlighted as words
    # (and don't shift the word→note alignment — the melody was composed from
    # the content lines only).
    import re as _re
    lyrics = meta.get("lyrics") or ""
    sung_lyrics = "\n".join(
        ln for ln in lyrics.splitlines()
        if not _re.match(r"^\s*\[.*\]\s*$", ln)
    )
    words = []
    for seg in align_words_to_notes(sung_lyrics, notes):
        start = float(seg["start"])
        dur = sum(float(d) for (_p, d) in seg["notes"])
        words.append({"text": seg["text"], "start": round(start, 4),
                      "end": round(start + dur, 4)})
    return {
        "duration": float(pm.get_end_time()),
        "tempo": float(spec.get("tempo") or meta.get("tempo") or 120.0),
        "key": spec.get("key") or meta.get("key") or "C",
        "scale": spec.get("scale") or meta.get("scale") or "major",
        "notes": note_list,        # [[pitch, start_sec, end_sec], ...]
        "words": words,            # [{text, start, end}, ...]
        "lyrics": lyrics,
        "has_lead": bool(note_list),
    }


def vocal_guide_audio(name: str) -> str:
    """Render the block's Lead Vocal track in isolation — the guide melody the
    user sings along to in karaoke. Returns the MP3 path (reuses the cached
    per-track render)."""
    from src.daw_integration.generic import blocks as block_store

    pm, _meta = block_store.load_block(name)
    idx = None
    for i, inst in enumerate(pm.instruments):
        nm = (inst.name or "").lower()
        if "lead vocal" in nm or (not inst.is_drum and inst.program in (52, 53, 54)):
            idx = i
            break
    if idx is None:
        raise ValueError("no Lead Vocal track to use as a guide")
    return block_part_audio(name, idx)


def song_score_data(title: str) -> dict:
    """Practice-chart score-data for a saved SONG (a timeline of blocks).

    Tempo-aware per section: each block's chords are detected at the block's OWN
    tempo (via extract_score_data on the block), then stitched onto the song
    timeline with the same cumulative offsets block_concat uses — so the chart
    and cursor stay locked to the audio even when blocks have different tempos.
    Each timeline entry becomes a labelled section."""
    from src.daw_integration.generic import blocks as block_store
    from src.daw_integration.generic import songs as song_store
    from src.daw_integration.generic.chord_analysis import extract_score_data

    timeline = song_store.load_song_timeline(title).get("timeline") or []
    if not timeline:
        raise ValueError("song has no blocks")

    spans: list[dict] = []
    sections: list[dict] = []
    cursor = 0.0          # seconds into the song
    bar_off = 0           # bars into the song
    key = scale = None
    first_tempo = None
    ts = [4, 4]

    for entry in timeline:
        try:
            pm_b, meta_b = block_store.load_block(entry["block_name"])
        except Exception:
            continue
        bscore = extract_score_data(pm_b, meta_b)
        bs = bscore["bar_seconds"]
        bbars = int(bscore["bars"])
        if not bbars or bs <= 0:
            continue
        if key is None:
            key, scale = bscore["key"], bscore["scale"]
            first_tempo, ts = bscore["tempo"], bscore["time_signature"]

        repeat = float(entry.get("repeat") or 1)
        full = int(repeat)
        rem = round((repeat - full) * bbars)
        sec_start_time, sec_start_bar = cursor, bar_off

        def emit(max_bar: int, time_off: float, bar_offset: int):
            for sp in bscore["chord_spans"]:
                if sp["start_bar"] >= max_bar:
                    continue
                eb = min(sp["end_bar"], max_bar - 1)
                spans.append({
                    **sp,
                    "start_bar": sp["start_bar"] + bar_offset,
                    "end_bar": eb + bar_offset,
                    "start_time": round(sp["start_time"] + time_off, 4),
                    "end_time": round(min(sp["end_time"], max_bar * bs) + time_off, 4),
                })

        for _ in range(full):
            emit(bbars, cursor, bar_off)
            cursor += bbars * bs
            bar_off += bbars
        if rem > 0:
            emit(rem, cursor, bar_off)
            cursor += rem * bs
            bar_off += rem

        sections.append({
            "label": entry["block_name"], "role": "section",
            "start_bar": sec_start_bar, "end_bar": max(sec_start_bar, bar_off - 1),
            "start_time": round(sec_start_time, 4), "end_time": round(cursor, 4),
        })

    return {
        "key": key or "C", "scale": scale or "major",
        "tempo": float(first_tempo or 120.0), "time_signature": list(ts),
        "bars": bar_off, "bar_seconds": round(cursor / bar_off, 4) if bar_off else 0.0,
        "beats_per_bar": int(ts[0]),
        "sections": sections, "chords": [], "chord_spans": spans,
    }


def _ensure_song_audio(title: str):
    """Render a saved song once, caching BOTH a WAV and an MP3 under data/songs
    (the WAV is used for gapless-ish section looping — seeking a WAV has no MP3
    decoder-priming gap). Returns (wav_path, mp3_path)."""
    import shutil
    import tempfile
    from src.daw_integration.generic import block_concat
    from src.daw_integration.generic import blocks as block_store
    from src.daw_integration.generic import songs as song_store
    from src.audio_processing.render.pipeline import render_to_audio

    song_yaml = song_store._path(title)
    safe = song_store._safe_name(title)
    wav = song_store.SONGS_DIR / f"{safe}.wav"
    mp3 = song_store.SONGS_DIR / f"{safe}.mp3"

    def fresh(p: Path) -> bool:
        return p.exists() and (not song_yaml.exists()
                               or p.stat().st_mtime >= song_yaml.stat().st_mtime)

    if fresh(wav) and fresh(mp3):
        return wav, mp3

    timeline = song_store.load_song_timeline(title).get("timeline") or []
    if not timeline:
        raise ValueError("song has no blocks")
    pm, _info = block_concat.concat_blocks(timeline)
    tmp = Path(tempfile.mkdtemp())
    midi_path = tmp / "song.mid"
    pm.write(str(midi_path))
    render = render_to_audio(midi=midi_path, output_dir=tmp / "render",
                             with_stems=False, master_preset="default")
    song_store.SONGS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy(str(render.mix_path), str(wav))
    except Exception:  # noqa: BLE001 — wav is an optimisation, not required
        pass
    if not block_store.write_preview_mp3(Path(render.mix_path), mp3):
        raise RuntimeError("could not render song preview")
    return wav, mp3


def ensure_song_preview(title: str) -> str:
    """Cached MP3 for a saved song (for streaming playback)."""
    return str(_ensure_song_audio(title)[1])


def ensure_song_wav(title: str) -> str:
    """Cached WAV for a saved song (for clean section looping)."""
    return str(_ensure_song_audio(title)[0])


# Fast/dense vocal lines (rap) read far better on the rough/TTS engine than the
# studio SVS, so we suggest "rough" for sections whose median sung note is short.
_DENSE_NOTE_SEC = 0.18
_DENSE_MIN_NOTES = 4


def section_voices(name: str) -> list[dict]:
    """Per-section voice info for the per-section engine picker: each
    ``spec.sections`` entry with how dense its vocal line is and a suggested
    engine (``rough`` for dense/rap-like sections, else ``studio``). Returns
    ``[]`` when the block has no section structure to switch between."""
    from src.daw_integration.generic import blocks as block_store
    from src.models.vocals.lyrics import monophonic_line, select_vocal_tracks

    pm, meta = block_store.load_block(name)
    spec = meta.get("spec") or {}
    sections = spec.get("sections") or []
    if not sections:
        return []
    ts = meta.get("time_signature") or [4, 4]
    tempo = float(spec.get("tempo") or meta.get("tempo") or 120.0)
    barlen = int(ts[0]) * 60.0 / tempo

    lead, _harms = select_vocal_tracks(pm)
    notes = monophonic_line(lead)  # (pitch, start, end) in seconds

    out: list[dict] = []
    for s in sections:
        sb, eb = int(s.get("start_bar") or 0), int(s.get("end_bar") or 0)
        t0, t1 = sb * barlen, (eb + 1) * barlen
        durs = sorted(e - st for (_p, st, e) in notes if t0 <= st < t1)
        n = len(durs)
        median = durs[n // 2] if n else 0.0
        dense = n >= _DENSE_MIN_NOTES and median < _DENSE_NOTE_SEC
        out.append({
            "label": s.get("label") or s.get("role") or "Section",
            "role": s.get("role") or "verse",
            "start_bar": sb, "end_bar": eb,
            "n_notes": n,
            "dense": dense,
            "suggested": "rough" if dense else "studio",
        })
    return out


def vocal_guide_midi(name: str):
    """Write the block's composed vocal (Lead + any harmonies) to a standalone
    MIDI **guide** — the target a user loads into their own DAW's Auto-Tune /
    Melodyne to tune a real take onto the composed melody. Returns the file
    path, or ``None`` if the block has no vocal melody yet."""
    import pretty_midi
    from src.daw_integration.generic import blocks as block_store
    from src.models.vocals.lyrics import select_vocal_instruments

    pm, meta = block_store.load_block(name)
    lead, harms = select_vocal_instruments(pm)
    if lead is None:
        return None
    out = pretty_midi.PrettyMIDI(initial_tempo=float(meta.get("tempo") or 120.0))

    def _copy(inst, track_name, program):
        ni = pretty_midi.Instrument(program=program, name=track_name)
        ni.notes = [pretty_midi.Note(velocity=n.velocity, pitch=n.pitch,
                                     start=n.start, end=n.end) for n in inst.notes]
        return ni

    out.instruments.append(_copy(lead, "Lead Vocal Guide", 53))
    for h in harms:
        out.instruments.append(_copy(h, h.name or "Harmony Guide", 52))
    guide_dir = API_OUT / "_guides"
    guide_dir.mkdir(parents=True, exist_ok=True)
    path = guide_dir / f"{block_store._safe_name(name)}_vocal_guide.mid"
    out.write(str(path))
    return path


def list_voices() -> list[str]:
    """Clear English macOS ``say`` voices (filters out the novelty ones)."""
    import subprocess
    try:
        out = subprocess.run(["say", "-v", "?"], capture_output=True, text=True, check=True).stdout
    except Exception:  # noqa: BLE001
        return []
    novelty = {"bad news", "bahh", "bells", "boing", "bubbles", "cellos", "good news",
               "jester", "organ", "superstar", "trinoids", "whisper", "wobble", "zarvox"}
    voices = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 2 or "en_" not in line:
            continue
        # voice name is everything before the locale token
        name = line[: line.index("en_")].strip().split("(")[0].strip()
        if name and name.lower() not in novelty and name not in voices:
            voices.append(name)
    return voices[:24]


_PITCH_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def _chord_roots_per_bar(pm, tempo: float, beats_per_bar: int, bars: int) -> list:
    """Best-effort per-bar chord root (note name) from the Chords/Piano track,
    so a melody can be composed to fit the harmony. None for empty bars."""
    try:
        if bars <= 0:
            return []
        track = None
        for inst in pm.instruments:
            nm = (inst.name or "").lower()
            if not inst.is_drum and inst.notes and ("chord" in nm or "piano" in nm or "key" in nm):
                track = inst
                break
        if track is None:
            for inst in pm.instruments:
                if not inst.is_drum and inst.notes:
                    track = inst
                    break
        if track is None:
            return []
        barlen = beats_per_bar * 60.0 / tempo
        by_bar: dict = {}
        for n in track.notes:
            by_bar.setdefault(int(n.start // barlen), []).append(n.pitch)
        return [_PITCH_NAMES[min(by_bar[b]) % 12] if by_bar.get(b) else None
                for b in range(bars)]
    except Exception:  # noqa: BLE001
        return []


def melody_request_params(name: str, lyrics: str) -> dict:
    """Context for a 'compose a vocal melody from these lyrics' request. Carries
    everything needed to write a full-song melody that fits the arrangement:
    per-line syllables, key/scale/tempo/meter/bars, the SECTION BAR RANGES, and
    the per-bar CHORD roots — so the answerer doesn't have to re-derive them."""
    import re
    from src.daw_integration.generic import blocks as block_store
    from src.models.vocals.lyrics import count_syllables
    pm, meta = block_store.load_block(name)
    spec = meta.get("spec") or {}
    lines = [ln.strip() for ln in (lyrics or "").splitlines() if ln.strip()]
    syllables = [sum(count_syllables(w) for w in re.findall(r"[A-Za-z']+", ln)) for ln in lines]
    ts = meta.get("time_signature") or [4, 4]
    tempo = float(spec.get("tempo") or meta.get("tempo") or 120.0)
    bars = int(meta.get("bars") or 0)
    return {
        "lyrics": lyrics,
        "lines": lines,
        "syllables_per_line": syllables,
        "genre": spec.get("genre"),   # drives the engine's melody style/techniques
        "key": spec.get("key") or "C",
        "scale": spec.get("scale") or "major",
        "tempo": tempo,
        "time_signature": [int(ts[0]), int(ts[1])],
        "beats_per_bar": int(ts[0]),
        "bars": bars,
        # Section bar ranges (start_bar/end_bar) — not just roles — so phrases
        # can be timed into each section. start_beat of bar B = B * beats_per_bar.
        "sections": [
            {"role": s.get("role"), "label": s.get("label"),
             "start_bar": s.get("start_bar"), "end_bar": s.get("end_bar")}
            for s in (spec.get("sections") or [])
        ],
        # Per-bar chord root from the harmony track, to write a fitting melody.
        "chords_per_bar": _chord_roots_per_bar(pm, tempo, int(ts[0]), bars),
    }


def apply_melody_plan(name: str, plan: dict, lyrics: str = "") -> dict:
    """Write a composed vocal melody (+ optional harmony) into a block,
    replacing any existing vocal tracks, then re-render the preview. ``plan``
    is ``{"tempo": bpm, "lead": [[midi, start_beat, dur_beat], ...],
    "harmony": [...]}`` (beats are converted to seconds at ``tempo``)."""
    import shutil

    import pretty_midi
    from src.daw_integration.generic import blocks as block_store

    pm, meta = block_store.load_block(name)
    tempo = float((plan or {}).get("tempo") or meta.get("tempo") or 120.0)
    spb = 60.0 / tempo

    # Back up the current MIDI before we overwrite it (cheap insurance).
    midi_path = block_store._midi_path(name)
    if midi_path.exists():
        try:
            shutil.copy2(midi_path, midi_path.with_suffix(".mid.bak"))
        except OSError:
            pass

    # Drop ONLY actual vocal tracks (so they're replaced) — identified by a
    # voice GM program (Choir/Voice 52-54) or a vocal name. Never an
    # instrument like piano/guitar/bass, even if it's the highest-pitched
    # track (that mistake once deleted a block's piano).
    _voice_programs = {52, 53, 54}
    _vocal_hints = ("vocal", "choir", "ooh", "aah")

    def _is_vocal(inst) -> bool:
        nm = (inst.name or "").lower()
        return (not inst.is_drum) and (
            inst.program in _voice_programs or any(h in nm for h in _vocal_hints))

    pm.instruments = [i for i in pm.instruments if not _is_vocal(i)]

    def _add(track: str, program: int, notes) -> int:
        inst = pretty_midi.Instrument(program=program, name=track)
        for item in notes or []:
            pitch, start_beat, dur_beat = int(item[0]), float(item[1]), float(item[2])
            if dur_beat <= 0:
                continue
            inst.notes.append(pretty_midi.Note(
                velocity=90, pitch=max(0, min(127, pitch)),
                start=start_beat * spb, end=(start_beat + dur_beat) * spb))
        if inst.notes:
            pm.instruments.append(inst)
        return len(inst.notes)

    n_lead = _add("Lead Vocal", 53, (plan or {}).get("lead"))
    n_harm = _add("Backing Vocals", 52, (plan or {}).get("harmony"))
    if not n_lead:
        raise ValueError("melody plan produced no lead notes")

    ts = meta.get("time_signature") or [4, 4]
    spec = meta.get("spec") or None
    if spec is not None:
        insts = list(spec.get("instruments") or [])
        for iid in (["vocal_lead"] + (["vocal_harmony"] if n_harm else [])):
            if iid not in insts:
                insts.append(iid)
        spec["instruments"] = insts
    block_store.save_block(
        name, pm, tempo=tempo, time_signature=(int(ts[0]), int(ts[1])),
        bars=int(meta.get("bars") or 0), overwrite=True, spec=spec,
        tags=meta.get("tags"))
    if lyrics:
        try:
            block_store.set_lyrics(name, lyrics)
        except Exception:  # noqa: BLE001
            pass
    return {"lead_notes": n_lead, "harmony_notes": n_harm, "tempo": tempo}


def phonetic_for_lyrics(lyrics: str) -> str:
    """Auto-generate the editable phonetic (ARPABET) version of a lyric — the
    layer the user tweaks per word to fix the SVS's diction."""
    from src.models.vocals.lyrics import to_phonetic
    return to_phonetic(lyrics or "")


def run_block_vocals(name: str, lyrics: str, voice: str, engine_name: str,
                     progress, job_id: str, harmonies: bool = True,
                     clarity: bool = False, phonetic: str = "",
                     section_engines: "list | None" = None) -> dict:
    """Render a sung vocal over a block and mix it with the block's
    instrumental. Reuses the block's existing HQ WAV when present.

    ``section_engines`` is an optional per-section voice map (each item has
    ``start_bar``/``end_bar``/``engine``) — sections sing with their own engine
    (rap verses on rough/TTS, hooks on the studio SVS) while ``engine_name`` is
    the fallback for anything uncovered."""
    import numpy as np
    import soundfile as sf
    from src.daw_integration.generic import blocks as block_store
    from src.models.vocals import RoughEngine, get_engine, render_vocals
    from src.models.vocals.render import section_time_ranges

    pm, _meta = block_store.load_block(name)
    progress("Synthesizing vocal…", 0.25)
    try:
        engine = get_engine(engine_name, voice)
    except Exception as exc:  # noqa: BLE001 — studio voicebank missing etc.
        logger.warning("vocal engine %r unavailable (%s) — using rough", engine_name, exc)
        engine = RoughEngine(voice or "")

    # Resolve a per-section engine map into render_vocals' engine_ranges,
    # caching one engine object per distinct name (studio is a shared singleton).
    engine_ranges = None
    if section_engines:
        ts = _meta.get("time_signature") or [4, 4]
        tempo = float((_meta.get("spec") or {}).get("tempo") or _meta.get("tempo") or 120.0)
        _cache: dict[str, object] = {}

        def _resolve(nm: str):
            if nm not in _cache:
                try:
                    _cache[nm] = get_engine(nm, voice)
                except Exception:  # noqa: BLE001
                    _cache[nm] = engine
            return _cache[nm]

        rows = [(se["start_bar"], se["end_bar"], se["engine"])
                for se in section_engines]
        engine_ranges = [(t0, t1, _resolve(nm))
                         for (t0, t1, nm) in section_time_ranges(rows, tempo, int(ts[0]))]

    voc, sr = render_vocals(pm, lyrics, voice=voice or "", engine=engine,
                            harmonies=harmonies, clarity=clarity, phonetic=phonetic,
                            engine_ranges=engine_ranges)

    job_dir = API_OUT / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    _prune_old_job_dirs()

    progress("Mixing with the instrumental…", 0.7)
    # Build the backing WITHOUT the tracks we just sang, so the soundfont
    # melody / harmony doesn't double the sung vocal. The cached HQ WAV bakes
    # every track in, so it's only safe to reuse when there's nothing to drop.
    from src.models.vocals.lyrics import select_vocal_instruments
    lead_inst, harm_insts = select_vocal_instruments(pm)

    # Engrave a vocal score — lead (with the lyrics under the melody) + any
    # harmony staves → PDF full score + separate parts, zipped. Soft-fails if
    # LilyPond is absent. Done before the instrumental prune below mutates pm.
    pdf_zip = None
    if lead_inst is not None:
        try:
            import pretty_midi
            spec = _meta.get("spec") or {}
            vpm = pretty_midi.PrettyMIDI(
                initial_tempo=float(_meta.get("tempo") or spec.get("tempo") or 120.0))
            for vi in (lead_inst, *harm_insts):
                vpm.instruments.append(vi)
            vocal_mid = job_dir / "vocal_parts.mid"
            vpm.write(str(vocal_mid))
            from src.scoring.pdf_export import export_zip
            pdf_zip = export_zip(
                vocal_mid, job_dir / "vocal_score.zip",
                key=str(spec.get("key") or "C"),
                scale=str(spec.get("scale") or "major"),
                tempo=float(_meta.get("tempo") or 120.0),
                title=f"{name} — Vocals", lead_lyrics=lyrics,
            )
        except Exception as exc:  # noqa: BLE001 — LilyPond missing / engrave error
            logger.warning("vocal score export failed for %s: %s", name, exc)
            pdf_zip = None

    drop = {id(lead_inst)} if lead_inst is not None else set()
    if harmonies:
        drop |= {id(i) for i in harm_insts}
    wav_path = block_store._wav_path(name)
    if not drop and wav_path.exists():
        inst, isr = sf.read(str(wav_path), dtype="float32")
    else:
        pm.instruments = [i for i in pm.instruments if id(i) not in drop]
        if pm.instruments:
            from src.audio_processing.render.pipeline import render_to_audio
            inst_mid = job_dir / "instrumental.mid"
            pm.write(str(inst_mid))
            r = render_to_audio(midi=str(inst_mid), output_dir=job_dir / "inst", with_stems=False)
            inst, isr = sf.read(str(r.mix_path), dtype="float32")
        else:
            inst, isr = np.zeros((1, 2), dtype="float32"), sr
    if voc.size and sr != isr:
        import librosa
        voc = librosa.resample(voc, orig_sr=sr, target_sr=isr)
    if inst.ndim == 1:
        inst = np.stack([inst, inst], axis=1)
    vstereo = np.stack([voc, voc], axis=1) if voc.size else np.zeros((1, 2), dtype=np.float32)
    n = max(len(inst), len(vstereo))

    def _pad(a):
        o = np.zeros((n, 2), dtype=np.float32)
        o[: len(a)] = a
        return o

    # Make the band leave room for the lead (presence-band dip + sidechain
    # ducking under the vocal) so the lyric stays intelligible, then sit the
    # vocal slightly hotter on top.
    if vstereo.size > 1:
        from src.models.vocals.render import carve_for_vocal
        inst = carve_for_vocal(inst, voc, isr)
    mix = _pad(inst) * 0.82 + _pad(vstereo) * 1.0
    peak = float(np.max(np.abs(mix))) if mix.size else 0.0
    if peak > 0:
        mix = mix * (0.97 / peak)
    mix_wav = job_dir / "vocal_mix.wav"
    sf.write(str(mix_wav), mix, isr)
    mix_mp3 = job_dir / "vocal_mix.mp3"
    served_mix = str(mix_mp3) if block_store.write_preview_mp3(mix_wav, mix_mp3) else str(mix_wav)

    served_stem = None
    if voc.size:
        stem_wav = job_dir / "vocal.wav"
        sf.write(str(stem_wav), voc, isr)
        stem_mp3 = job_dir / "vocal.mp3"
        served_stem = str(stem_mp3) if block_store.write_preview_mp3(stem_wav, stem_mp3) else str(stem_wav)

    try:
        block_store.set_lyrics(name, lyrics)
    except Exception:  # noqa: BLE001
        pass

    # Persist this render as a take on the block so the user can re-select or
    # delete past generations (soft-fail — a save hiccup shouldn't lose the job).
    take_id = None
    try:
        take = block_store.save_vocal_take(
            name, mix=served_mix, vocal=served_stem,
            score=str(pdf_zip) if pdf_zip else None,
            lyrics=lyrics, engine=engine_name, voice=voice, harmonies=harmonies,
            clarity=clarity, phonetic=phonetic, section_engines=section_engines or [],
        )
        take_id = take.get("id")
    except Exception as exc:  # noqa: BLE001
        logger.warning("could not persist vocal take for %s: %s", name, exc)

    progress("Done.", 1.0)
    return {
        "block": name, "engine": engine_name, "voice": voice, "take_id": take_id,
        "_paths": {
            "audio_mp3": served_mix, "audio_wav": str(mix_wav),
            "vocal_mp3": served_stem,
            "pdf": str(pdf_zip) if pdf_zip else None,
            "midi": str(block_store._midi_path(name)),
        },
    }


def run_autotune(name: str, audio_path: str, progress, job_id: str, *,
                 mode: str = "natural", strength: float = 0.85,
                 to_key: bool = False) -> dict:
    """Pitch-correct an uploaded/recorded vocal onto the block's composed
    melody (or its key/scale) and mix it with the instrumental, saved as a
    take. The tuned **real voice** replaces the synth one — so the backing is
    built without the synth vocal tracks (no doubling)."""
    import librosa
    import numpy as np
    import soundfile as sf
    from src.daw_integration.generic import blocks as block_store
    from src.models.vocals.autotune import autotune, targets_from_block
    from src.models.vocals.lyrics import select_vocal_instruments
    from src.models.vocals.render import carve_for_vocal

    pm, meta = block_store.load_block(name)
    spec = meta.get("spec") or {}
    key, scale = (spec.get("key") or "C"), (spec.get("scale") or "major")

    progress("Loading take…", 0.15)
    vocal, sr = librosa.load(audio_path, sr=None, mono=True)   # handles wav/webm/m4a via ffmpeg
    vocal = np.asarray(vocal, dtype=np.float32)

    targets = None if to_key else (targets_from_block(name) or None)
    progress("Tuning to the melody…" if targets else "Tuning to the key…", 0.4)
    voc = autotune(vocal, sr, targets=targets, key=key, scale=scale,
                   mode=mode, strength=strength)
    try:
        from src.models.vocals.render import _apply_fx
        voc = _apply_fx(voc, sr)              # presence/clarity vocal chain
    except Exception:  # noqa: BLE001
        pass

    job_dir = API_OUT / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    _prune_old_job_dirs()

    progress("Mixing with the instrumental…", 0.7)
    # Backing WITHOUT the synth vocal tracks, so they don't double the real voice.
    lead_inst, harm_insts = select_vocal_instruments(pm)
    drop = {id(i) for i in harm_insts}
    if lead_inst is not None:
        drop.add(id(lead_inst))
    wav_path = block_store._wav_path(name)
    if not drop and wav_path.exists():
        inst, isr = sf.read(str(wav_path), dtype="float32")
    else:
        pm.instruments = [i for i in pm.instruments if id(i) not in drop]
        if pm.instruments:
            from src.audio_processing.render.pipeline import render_to_audio
            inst_mid = job_dir / "instrumental.mid"
            pm.write(str(inst_mid))
            r = render_to_audio(midi=str(inst_mid), output_dir=job_dir / "inst", with_stems=False)
            inst, isr = sf.read(str(r.mix_path), dtype="float32")
        else:
            inst, isr = np.zeros((1, 2), dtype="float32"), sr
    if voc.size and sr != isr:
        voc = librosa.resample(voc, orig_sr=sr, target_sr=isr)
    if inst.ndim == 1:
        inst = np.stack([inst, inst], axis=1)
    vstereo = np.stack([voc, voc], axis=1) if voc.size else np.zeros((1, 2), dtype=np.float32)
    n = max(len(inst), len(vstereo))

    def _pad(a):
        o = np.zeros((n, 2), dtype=np.float32)
        o[: len(a)] = a
        return o

    if vstereo.size > 1:
        inst = carve_for_vocal(inst, voc, isr)
    mix = _pad(inst) * 0.82 + _pad(vstereo) * 1.0
    peak = float(np.max(np.abs(mix))) if mix.size else 0.0
    if peak > 0:
        mix = mix * (0.97 / peak)
    mix_wav = job_dir / "vocal_mix.wav"
    sf.write(str(mix_wav), mix, isr)
    mix_mp3 = job_dir / "vocal_mix.mp3"
    served_mix = str(mix_mp3) if block_store.write_preview_mp3(mix_wav, mix_mp3) else str(mix_wav)

    served_stem = None
    if voc.size:
        stem_wav = job_dir / "vocal.wav"
        sf.write(str(stem_wav), voc, isr)
        stem_mp3 = job_dir / "vocal.mp3"
        served_stem = str(stem_mp3) if block_store.write_preview_mp3(stem_wav, stem_mp3) else str(stem_wav)

    take_id = None
    try:
        take = block_store.save_vocal_take(
            name, mix=served_mix, vocal=served_stem,
            lyrics=meta.get("lyrics") or "", engine="autotune",
            voice=("to-key" if targets is None else "to-melody"))
        take_id = take.get("id")
    except Exception as exc:  # noqa: BLE001
        logger.warning("could not persist autotune take for %s: %s", name, exc)

    progress("Done.", 1.0)
    return {
        "block": name, "engine": "autotune", "take_id": take_id,
        "_paths": {"audio_mp3": served_mix, "audio_wav": str(mix_wav),
                   "vocal_mp3": served_stem, "midi": str(block_store._midi_path(name))},
    }


def _default_progression(scale: str) -> list[str]:
    minor = (scale or "").lower() in (
        "minor", "natural_minor", "aeolian", "dorian", "phrygian",
        "harmonic_minor", "melodic_minor")
    return ["i", "VI", "III", "VII"] if minor else ["I", "V", "vi", "IV"]


def generate_part(req) -> dict:
    """Generate ONE DAW-channel part (MIDI note-list + optional rendered WAV)
    that fits the given musical context — the host-agnostic brain the VST/DAW
    bridges call. ``req`` is a GeneratePartRequest."""
    import shutil
    import uuid
    from src.daw_integration.generic.midi_export import MidiExporter
    from src.daw_integration.generic.styles import STYLES

    ts = req.time_signature or [4, 4]
    tempo = float(req.tempo or 120.0)
    bars = max(1, int(req.bars or 4))
    key, scale = (req.key or "C"), (req.scale or "major")
    target = (req.target or "melody").lower()
    preset = STYLES.get(req.genre or "")
    prog = list(req.progression) or _default_progression(scale)
    prog = (prog * (bars // len(prog) + 1))[:bars]      # cover every bar

    # Per-part modifiers: explicit request value > genre/preset default > builtin.
    voicing = req.voicing or (preset.voicing if preset else "triad")
    chord_rhythm = req.chord_rhythm or (preset.chord_rhythm if preset else "pad")
    bass_pattern = req.bass_pattern or (preset.bass_pattern if preset else "root_fifth")
    drum_pattern = req.drum_pattern or (preset.drum_pattern if preset else "basic_rock")
    melody_style = req.melody_style or (preset.melody_style if preset else "motif")
    phrase_shape = req.phrase_shape or "arc"

    octave = int(req.octave) if req.octave is not None else None
    dens = float(req.note_density) if req.note_density is not None else None

    midi = MidiExporter(tempo=tempo, time_signature=(int(ts[0]), int(ts[1])))
    if target == "chords":
        kw = dict(key=key, progression=prog, bars=bars, scale_name=scale,
                  voicing=voicing, rhythm=chord_rhythm)
        if octave is not None:
            kw["octave"] = octave
        midi.add_chord_progression(**kw)
        track_name = "Chords"
    elif target == "bass":
        kw = dict(key=key, progression=prog, bars=bars, scale_name=scale,
                  pattern=bass_pattern, seed=req.seed)
        if octave is not None:
            kw["octave"] = octave
        if dens is not None:
            kw["density"] = dens
        midi.add_bass_line(**kw)
        track_name = "Bass"
    elif target in ("melody", "lead"):
        kw = dict(key=key, scale_name=scale, bars=bars, progression=prog,
                  melody_style=melody_style, phrase_shape=phrase_shape,
                  seed=req.seed, track_name="Melody")
        if octave is not None:
            kw["octave"] = octave
        if dens is not None:
            kw["note_density"] = dens
        midi.add_melody(**kw)
        track_name = "Melody"
    elif target == "drums":
        kw = dict(pattern=drum_pattern, bars=bars, seed=req.seed)
        if dens is not None:
            kw["density"] = dens
        midi.add_drum_pattern(**kw)
        track_name = "Drums"
    else:
        raise ValueError(f"unknown target {target!r} (chords|bass|melody|lead|drums)")

    track = next((t for t in midi.tracks if t.name == track_name),
                 midi.tracks[-1] if midi.tracks else None)
    spb = 60.0 / tempo
    notes = [[int(n.pitch), round(n.start / spb, 4), round(max(0.01, n.end - n.start) / spb, 4)]
             for n in (track.notes if track else [])]

    parts_root = API_OUT / "_parts"
    parts_root.mkdir(parents=True, exist_ok=True)
    # prune: keep the 30 newest part dirs (WAVs add up; disk runs tight)
    olds = sorted([d for d in parts_root.iterdir() if d.is_dir()],
                  key=lambda p: p.stat().st_mtime)[:-30]
    for d in olds:
        shutil.rmtree(d, ignore_errors=True)

    part_id = uuid.uuid4().hex[:12]
    part_dir = parts_root / part_id
    part_dir.mkdir(parents=True, exist_ok=True)
    midi.save(part_dir / "part.mid")

    out = {
        "part_id": part_id, "target": target, "tempo": tempo, "bars": bars,
        "time_signature": [int(ts[0]), int(ts[1])], "key": key, "scale": scale,
        "progression": prog, "n_notes": len(notes), "notes": notes,
        "midi_url": f"/api/parts/{part_id}/part.mid",
    }
    if (req.output or "both") in ("wav", "both"):
        try:
            from src.audio_processing.render.pipeline import render_to_audio
            from src.daw_integration.generic import blocks as block_store
            r = render_to_audio(midi=str(part_dir / "part.mid"),
                                output_dir=part_dir / "render", with_stems=False)
            wav = part_dir / "part.wav"
            shutil.copy2(r.mix_path, wav)
            mp3 = part_dir / "part.mp3"
            served = "part.mp3" if block_store.write_preview_mp3(wav, mp3) else "part.wav"
            out["wav_url"] = f"/api/parts/{part_id}/{served}"
        except Exception as exc:  # noqa: BLE001
            logger.warning("part WAV render failed: %s", exc)
    return out


def generate_arrangement(req) -> dict:
    """Generate a FULL arrangement — multiple parts on one shared timeline,
    written as a single multi-track MIDI (one track per part). Imported once
    into a DAW, it lays out drums/bass/chords/melody on their own tracks (the
    closest thing to 'write to channels' Logic allows). Returns the multi-track
    midi_url + a rendered mix WAV."""
    import shutil
    import uuid
    from src.daw_integration.generic.midi_export import MidiExporter
    from src.daw_integration.generic.styles import STYLES

    ts = req.time_signature or [4, 4]
    tempo = float(req.tempo or 120.0)
    bars = max(1, int(req.bars or 4))
    key, scale = (req.key or "C"), (req.scale or "major")
    preset = STYLES.get(req.genre or "")
    prog = list(req.progression) or _default_progression(scale)
    prog = (prog * (bars // len(prog) + 1))[:bars]
    parts = [p.lower() for p in (req.parts or ["drums", "bass", "chords", "melody"])]

    midi = MidiExporter(tempo=tempo, time_signature=(int(ts[0]), int(ts[1])))
    if "chords" in parts:
        midi.add_chord_progression(key=key, progression=prog, bars=bars, scale_name=scale,
            voicing=(preset.voicing if preset else "triad"),
            rhythm=(preset.chord_rhythm if preset else "pad"))
    if "bass" in parts:
        midi.add_bass_line(key=key, progression=prog, bars=bars, scale_name=scale,
            pattern=(preset.bass_pattern if preset else "root_fifth"), seed=req.seed)
    if "drums" in parts:
        midi.add_drum_pattern(pattern=(preset.drum_pattern if preset else "basic_rock"),
            bars=bars, seed=req.seed)
    if "melody" in parts:
        midi.add_melody(key=key, scale_name=scale, bars=bars, progression=prog,
            melody_style=(preset.melody_style if preset else "motif"),
            seed=req.seed, track_name="Melody")

    spb = 60.0 / tempo
    tracks, merged = [], []
    for t in midi.tracks:
        ns = [[int(n.pitch), round(n.start / spb, 4), round(max(0.01, n.end - n.start) / spb, 4)]
              for n in t.notes]
        tracks.append({"track": t.name, "n_notes": len(ns), "notes": ns})
        merged += ns
    merged.sort(key=lambda x: x[1])

    parts_root = API_OUT / "_parts"
    parts_root.mkdir(parents=True, exist_ok=True)
    for d in sorted([d for d in parts_root.iterdir() if d.is_dir()],
                    key=lambda p: p.stat().st_mtime)[:-30]:
        shutil.rmtree(d, ignore_errors=True)
    part_id = uuid.uuid4().hex[:12]
    part_dir = parts_root / part_id
    part_dir.mkdir(parents=True, exist_ok=True)
    midi.save(part_dir / "part.mid")

    out = {
        "part_id": part_id, "target": "arrangement", "tempo": tempo, "bars": bars,
        "time_signature": [int(ts[0]), int(ts[1])], "key": key, "scale": scale,
        "progression": prog, "tracks": tracks, "n_notes": len(merged), "notes": merged,
        "midi_url": f"/api/parts/{part_id}/part.mid",
    }
    if (req.output or "both") in ("wav", "both"):
        try:
            from src.audio_processing.render.pipeline import render_to_audio
            from src.daw_integration.generic import blocks as block_store
            r = render_to_audio(midi=str(part_dir / "part.mid"),
                                output_dir=part_dir / "render", with_stems=False)
            wav = part_dir / "part.wav"
            shutil.copy2(r.mix_path, wav)
            mp3 = part_dir / "part.mp3"
            served = "part.mp3" if block_store.write_preview_mp3(wav, mp3) else "part.wav"
            out["wav_url"] = f"/api/parts/{part_id}/{served}"
        except Exception as exc:  # noqa: BLE001
            logger.warning("arrangement WAV render failed: %s", exc)
    return out


def part_file(part_id: str, filename: str):
    """Path to a generated part's artifact (validated), or None."""
    if filename not in ("part.mid", "part.wav", "part.mp3"):
        return None
    p = API_OUT / "_parts" / part_id / filename
    return p if p.exists() else None


# Per-part modifier choices (mirror the web app's curated lists / the engine).
_PO_VOICINGS = ["triad", "seventh", "ninth", "sixth", "add9", "sus2", "sus4",
                "power", "open5", "drop2", "quartal", "quintal", "shell",
                "rootless", "sus4_add9"]
_PO_CHORD_RHYTHMS = ["pad", "pulse_quarter", "stabs_8th", "charleston",
                     "funk_comp", "disco_stabs", "off_skank", "dotted_8ths",
                     "elton_octaves", "van_halen_chug", "waltz_strum",
                     "compound_6_8_strum", "tresillo", "clave_son_3side",
                     "clave_son_2side", "rumba_clave", "bossa_comp", "montuno_2_3",
                     "arpeggio_up", "arpeggio_down", "arpeggio_16th", "alberti"]
_PO_BASS = ["root", "root_fifth", "walking", "walking_swing", "funk_16ths",
            "offbeat", "disco_octave", "palm_mute_8ths", "flea_slap", "geddy_lee",
            "bootsy_slap", "waltz_bass", "tumbao", "reggaeton_dembow_bass"]
_PO_MELODY_STYLES = ["motif", "riff", "chord_tone", "pentatonic", "blues",
                     "raga_yaman", "maqam_hijaz", "gamelan_slendro", "hirajoshi",
                     "random"]
_PO_PHRASE_SHAPES = ["arc", "rise", "fall", "valley", "plateau", "call_response"]


def part_options() -> dict:
    """The valid per-part modifier choices for the VST/DAW "smart dropdown".
    Drum patterns come straight from the engine's 4/4 source of truth; the rest
    mirror the curated lists. Each modifier carries its options + a default."""
    from src.daw_integration.generic.midi_export import DRUM_PATTERNS_4_4
    return {
        "chords": {
            "voicing": {"options": _PO_VOICINGS, "default": "triad"},
            "rhythm":  {"options": _PO_CHORD_RHYTHMS, "default": "pad"},
        },
        "bass":   {"pattern": {"options": _PO_BASS, "default": "root_fifth"}},
        "drums":  {"pattern": {"options": list(DRUM_PATTERNS_4_4.keys()), "default": "basic_rock"}},
        "melody": {
            "style":        {"options": _PO_MELODY_STYLES, "default": "motif"},
            "phrase_shape": {"options": _PO_PHRASE_SHAPES, "default": "arc"},
        },
        "lead": {
            "style":        {"options": _PO_MELODY_STYLES, "default": "motif"},
            "phrase_shape": {"options": _PO_PHRASE_SHAPES, "default": "arc"},
        },
    }


def _save_unique_block(block_store, base_name: str, pm, *,
                       tempo: float, time_signature, bars: int,
                       spec: dict | None = None) -> str:
    name = _unique_block_name(block_store, base_name)
    block_store.save_block(name, pm, tempo=float(tempo),
                           time_signature=time_signature, bars=int(bars),
                           overwrite=False, spec=spec)
    return name
