"""Song tools: everything a model needs to work through songs with the studio.

One shared module behind every model-facing surface:

- the MCP server (``src/serve/mcp_tools.py``, stdio for Claude Code and SSE
  at ``/mcp``), which registers each function in :data:`TOOLS`;
- the HTTP tool endpoint (``src/api/tools_routes.py``, ``/api/tools``), which
  the local AI gateway calls.

The tools reuse the REST route and service functions (``src/api/routes.py``,
``src/api/service.py``); nothing here re-implements the engine. Each tool
returns a plain JSON-friendly dict. A tool raises :class:`ToolError` with a
message written for the model when the call can't be done.

The docstrings and parameter descriptions are what a model reads to choose
options, so they spell out what each option sounds like.

Jobs run in the process that started them. Every generation a tool starts is
recorded under ``data/outputs/song_tools/`` (its parameters, then its result),
so :func:`revise` and the file tools keep working after a restart.
"""

from __future__ import annotations

import difflib
import inspect
import json
import logging
import subprocess
import threading
import time
from pathlib import Path
from typing import Annotated, Any, Optional

from fastapi import HTTPException
from pydantic import Field

from src.api import arrangement as arrangement_mod
from src.api import routes, service
from src.api.jobs import registry
from src.api.schemas import (
    BlockVersionRequest,
    FolderCreateRequest,
    FolderItemsRequest,
    FolderMoveRequest,
    FolderReorderRequest,
    FolderUpdateRequest,
    GenerateRequest,
    LibrarySaveRequest,
    RenameRequest,
    SaveBlockFromJobRequest,
    SongRenderRequest,
    SongSaveRequest,
    TagsRequest,
    VideoScoreRequest,
)
from src.composition import song_plan
from src.composition import christmas
from src.composition import lyrics as _lyrics
from src.composition.carols import carol_catalog
from src.composition.funk_fusion import ARRANGEMENT_INSTRUMENTS, ARRANGEMENT_VARIANTS
from src.daw_integration.generic import blocks as block_store
from src.daw_integration.generic.styles import STYLES

logger = logging.getLogger("ai_music_studio.song_tools")

RECORDS_DIR = service.PROJECT_ROOT / "data" / "outputs" / "song_tools"
DEFAULT_TIMEOUT_S = 900

# Styles whose techniques read each option (others ignore it).
CHRISTMAS_STYLES = tuple(christmas.STYLE_IDS)
ARRANGEMENT_STYLES = ("funk_fusion_full",) + CHRISTMAS_STYLES
HIT_STYLES = ("funk_fusion_full", "neo_soul_full")
SAMPLED_LEAD_STYLES = ("funk_fusion_full", "fusion_full", "neo_soul_full")

HIT_STYLE_OPTIONS = {
    "punch": "Exactly on the hit; the band breathes around it (an 8th-note gap before downbeat hits). Dramatic.",
    "groove": "On the next beat, inside the groove; the band keeps playing. Smoother, musically intentional.",
}
SOUND_OPTIONS = {
    "sampled": "Real-instrument sample libraries where installed (Rhodes, basses, kit, horns, strings, guitar).",
    "gm": "The General MIDI soundfont for every part. Thinner, but every program is available.",
}
CHAPTER_LEADS = {
    "synth_lead": "The chosen lead_patch voice (synth, horns, trumpet, guitar...).",
    "lead_guitar": "The overdriven fusion guitar stack.",
}

RECIPES = [
    {"name": "Quiet background bed under a narrated video (the final SunsoftERP 'What's new' cut)",
     "tool": "score_video",
     "args": {"genre": "funk_fusion_full", "base_tempo": 120, "hits": [],
              "arrangement": "hits_only,calm_keys,calm_bass,bass_flare,pocket_drums,brushes,soar,no_falloff",
              "extra_instruments": ["string_section", "french_horn"], "target_lufs": -25,
              "chapters": [{"start": 0, "roles": ["chorus"], "intro": False}, "...one per video chapter"]},
     "why": "Steady and unobtrusive: no stabs, no lead, gentle pocket drums on brushes, strings that soar, "
            "and an ending that rings out instead of a comic fall-off. -25 LUFS sits under speech."},
    {"name": "Upbeat video-game funk (the original sizzle reel)",
     "tool": "score_video",
     "args": {"genre": "funk_fusion_full", "base_tempo": 145, "seed": 52, "lead_patch": "guitar_stack",
              "hit_style": "groove", "curate_hits": True, "min_hit_gap": 5.0},
     "why": "Full band with slap bass, Rhodes chops, horn stabs on curated caption hits and a guitar lead."},
    {"name": "70s horn hits, no lead",
     "tool": "generate_song",
     "args": {"genre": "funk_fusion_full", "arrangement": "hits_only", "hits": [4.0, 8.0, 12.0]},
     "why": "Less complex, more impact: the band only lands the hits together."},
    {"name": "Simplest calm loop",
     "tool": "generate_song",
     "args": {"genre": "funk_fusion_full", "arrangement": "hits_only,calm", "tempo": 120},
     "why": "Plain 8th hats, root/fifth bass, sustained Rhodes."},
]


class ToolError(Exception):
    """A tool could not run; the message tells the model what to fix."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _call(fn, *args, **kwargs):
    """Run a route function, turning its HTTP errors into ToolErrors."""
    try:
        return fn(*args, **kwargs)
    except HTTPException as exc:
        raise ToolError(str(exc.detail)) from None
    except FileNotFoundError as exc:
        raise ToolError(f"Not found: {exc}") from None


def _suggest(name: str, choices) -> str:
    close = difflib.get_close_matches(name, list(choices), n=3, cutoff=0.5)
    return f" Did you mean {', '.join(close)}?" if close else ""


def _check_genre(genre: str) -> None:
    if genre not in STYLES:
        raise ToolError(f"Unknown genre {genre!r}.{_suggest(genre, STYLES)} Call list_styles for the ids.")


def _catalog(genre: str) -> tuple[dict, dict]:
    """(variant descriptions, variant -> instruments) for a style."""
    if genre in CHRISTMAS_STYLES:
        return christmas.ARRANGEMENT_VARIANTS, christmas.ARRANGEMENT_INSTRUMENTS
    return ARRANGEMENT_VARIANTS, ARRANGEMENT_INSTRUMENTS


def _variants(arrangement: str, genre: str = "funk_fusion_full") -> list[str]:
    """Split and validate a comma-separated arrangement string."""
    catalog, _ = _catalog(genre)
    names = [a.strip() for a in (arrangement or "").replace("+", ",").split(",") if a.strip()]
    bad = [n for n in names if n not in catalog]
    if bad:
        from src.audio_processing.render.lead_voices import LEAD_VOICES
        hints = "".join(f" {b!r} is a lead voice: set lead_patch={b!r}." if b in LEAD_VOICES
                        else _suggest(b, catalog) for b in bad)
        raise ToolError(f"Unknown arrangement variant(s) {bad} for {genre}.{hints} "
                        f"Valid: {', '.join(catalog)}.")
    return names


def _check_lead(lead_patch: str) -> None:
    from src.audio_processing.render.lead_voices import LEAD_VOICES
    if lead_patch in ARRANGEMENT_VARIANTS:
        raise ToolError(f"{lead_patch!r} is an arrangement variant, not a lead voice: add it to arrangement. "
                        f"Lead voices: {', '.join(LEAD_VOICES)}.")
    if lead_patch and lead_patch not in LEAD_VOICES:
        raise ToolError(f"Unknown lead_patch {lead_patch!r}.{_suggest(lead_patch, LEAD_VOICES)} "
                        f"Valid: {', '.join(LEAD_VOICES)}.")


def _check_hit_style(hit_style: str) -> None:
    if hit_style and hit_style not in HIT_STYLE_OPTIONS:
        raise ToolError(f"hit_style must be one of {list(HIT_STYLE_OPTIONS)}, not {hit_style!r}.")


def _needed_instruments(variants: list[str], genre: str = "funk_fusion_full") -> list[str]:
    needs = _catalog(genre)[1]
    out: list[str] = []
    for v in variants:
        out += [i for i in needs.get(v, ()) if i not in out]
    return out


def _check_tune(genre: str, tune: str) -> str:
    """A valid tune id for Christmas styles ("" for other styles)."""
    if not tune:
        return ""
    if genre not in CHRISTMAS_STYLES:
        raise ToolError(f"tune only works with the Christmas styles ({', '.join(CHRISTMAS_STYLES)}), not {genre!r}.")
    if christmas.denied_song(tune):
        raise ToolError(f"{tune!r} is a copyrighted song and can't be arranged. Use a public-domain carol "
                        f"({', '.join(carol_catalog())}) or 'original'.")
    if tune == "original":
        return tune
    from src.composition.carols import carol
    t = carol(tune)
    if t is None:
        raise ToolError(f"Unknown carol {tune!r}.{_suggest(tune, carol_catalog())} "
                        f"Carols: {', '.join(carol_catalog())}, or 'original'.")
    return t.id


def _record_path(job_id: str) -> Path:
    return RECORDS_DIR / f"{job_id}.json"


def _load_record(job_id: str) -> Optional[dict]:
    p = _record_path(job_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return None


def _write_record(job_id: str, record: dict) -> None:
    RECORDS_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _record_path(job_id).with_suffix(".tmp")
    tmp.write_text(json.dumps(record, indent=1, default=str))
    tmp.replace(_record_path(job_id))


def _start_record(job_id: str, kind: str, params: dict, parent: Optional[str] = None) -> None:
    _write_record(job_id, {"job_id": job_id, "kind": kind, "params": params, "parent": parent,
                           "created": time.time(), "status": "running"})

    def _persist_when_done() -> None:
        while True:
            job = registry.get(job_id)
            if job is None or job.status in ("done", "error"):
                break
            time.sleep(0.5)
        rec = _load_record(job_id) or {}
        if job is not None:
            rec.update(status=job.status, error=job.error,
                       result=job.result if job.status == "done" else None, finished=time.time())
            _write_record(job_id, rec)

    threading.Thread(target=_persist_when_done, name=f"record-{job_id}", daemon=True).start()


def _job(job_id: str):
    """The job, re-registering a recorded finished one after a restart."""
    job = registry.get(job_id)
    if job is not None:
        return job
    rec = _load_record(job_id)
    if rec and rec.get("status") == "done" and rec.get("result"):
        return registry.adopt(job_id, rec["result"])
    if rec and rec.get("status") == "error":
        raise ToolError(f"Job {job_id} failed: {rec.get('error')}")
    raise ToolError(f"Unknown job {job_id!r}. Jobs started by these tools are listed by list_jobs.")


def _audio_seconds(path: Optional[str]) -> Optional[float]:
    if not path or not Path(path).exists():
        return None
    try:
        import soundfile as sf
        return round(sf.info(path).duration, 2)
    except Exception:  # noqa: BLE001
        return None


def _files(result: dict) -> dict:
    paths = result.get("_paths", {}) or {}
    files = {"audio_wav": paths.get("audio_wav"), "audio_mp3": paths.get("audio_mp3"),
             "midi": paths.get("midi"), "pdf_zip": paths.get("pdf"), "timing": paths.get("timing")}
    if paths.get("audio_wav"):
        here = Path(paths["audio_wav"]).parent
        for stems in (here / "stems", here / "render" / "stems"):
            if stems.is_dir():
                files["stems"] = sorted(str(p) for p in stems.glob("*.wav"))
    return {k: v for k, v in files.items() if v}


def _summary(job) -> dict:
    out: dict[str, Any] = {"job_id": job.id, "status": job.status,
                           "progress": round(job.progress, 2), "message": job.message}
    if job.error:
        out["error"] = job.error
    rec = _load_record(job.id)
    if rec:
        out["kind"] = rec.get("kind")
        if rec.get("parent"):
            out["revised_from"] = rec["parent"]
    if job.status == "done":
        res = job.result
        for k, v in res.items():
            if k.startswith("_"):
                continue
            if k == "summary" and isinstance(v, str) and len(v) > 1200:
                v = v[:1200] + "…"
            out[k] = v
        out["files"] = _files(res)
        out["duration_seconds"] = _audio_seconds(out["files"].get("audio_wav"))
    return out


def _shown_params(kind: Optional[str], params: dict) -> dict:
    """The options a job actually set (anything not at its tool's default)."""
    fn = {"generate": "generate_song", "score_video": "score_video", "render_song": "render_song"}.get(kind or "")
    defaults = {}
    if fn:
        defaults = {n: p.default for n, p in inspect.signature(TOOLS_BY_NAME[fn]).parameters.items()}
    return {k: v for k, v in params.items() if v not in ("", None, [], {}) and defaults.get(k, object()) != v}


def _wait(job_id: str, timeout_s: float) -> dict:
    job = _job(job_id)
    deadline = time.time() + max(1.0, float(timeout_s))
    while job.status not in ("done", "error") and time.time() < deadline:
        time.sleep(0.25)
    out = _summary(job)
    if job.status not in ("done", "error"):
        out["note"] = f"Still {job.status} after {timeout_s:.0f}s; call wait_for_job again."
    return out


def _resolve_audio(source: str) -> Path:
    """A job id, a block name, or a path to an audio file → that audio file."""
    source = (source or "").strip()
    if not source:
        raise ToolError("Give a source: a job_id, a block name, or a path to a .wav/.mp3.")
    p = Path(source).expanduser()
    if p.suffix.lower() in (".wav", ".mp3", ".flac", ".aif", ".aiff") and p.exists():
        return p
    if registry.get(source) is not None or _load_record(source) is not None:
        files = _files(_job(source).result) if _job(source).status == "done" else {}
        wav = files.get("audio_wav") or files.get("audio_mp3")
        if not wav:
            raise ToolError(f"Job {source} has no audio yet (status {_job(source).status}).")
        return Path(wav)
    if block_store._midi_path(source).exists():
        wav = block_store.ensure_preview_wav(source)
        if wav:
            return Path(wav)
        raise ToolError(f"Block {source!r} has no audio and could not be rendered.")
    raise ToolError(f"{source!r} is not a job id, a block name, or an existing audio file.")


# ---------------------------------------------------------------------------
# Discover
# ---------------------------------------------------------------------------

def list_styles(
    query: Annotated[str, Field(description="Optional filter on id or name, e.g. 'funk', 'jazz', 'full'.")] = "",
) -> list[dict]:
    """List the song styles (the `genre` ids generate_song and score_video take).

    Ids ending in `_full` / `_full_song` are complete multi-section songs.
    `funk_fusion_full` is the flagship: arrangement variants, hit points and
    the full lead-voice set. The `christmas_*_full` styles (swing, jazz trio,
    orchestral, fireside, choir, pop) play public-domain carols or original
    tunes with their own variants (see describe_options).
    """
    out: list[dict] = []
    q = query.strip().lower()
    for key, preset in STYLES.items():
        if q and q not in key.lower() and q not in preset.name.lower():
            continue
        out.append({
            "name": key,
            "label": preset.name,
            "default_bars": int(preset.default_bars),
            "key": preset.key,
            "scale": preset.scale,
            "tempo": float(preset.tempo),
            "has_rhythm_variants": bool(preset.rhythm_variants),
            "rhythm_variants": list((preset.rhythm_variants or {}).keys()),
            "default_instruments": list(preset.default_instruments or []),
            "sound": getattr(preset, "sound", None) or "gm",
            "arrangement_variants": key in ARRANGEMENT_STYLES,
            "hits": key in HIT_STYLES,
        })
    return sorted(out, key=lambda d: d["name"])


def list_genres() -> dict:
    """The genre wheel: genre families, each with genres that map to a style id
    and the section roles each one plays natively."""
    return routes.list_genres()


def list_instruments() -> list[dict]:
    """Instrument ids by family (for generate_song `instruments` /
    `extra_instruments`, section `instruments` masks, and score_video
    `extra_instruments`)."""
    return routes.list_instruments()


def describe_options() -> dict:
    """Every generation option with a plain-English description: Funk Fusion
    arrangement variants, lead voices, hit styles, sounds, master presets,
    section roles and per-section override keys, video chapter fields, and
    proven recipes. Read this before choosing options for generate_song,
    score_video or revise."""
    from src.audio_processing.render import MASTER_PRESETS
    from src.audio_processing.render.lead_voices import DEFAULT_VOICE, LEAD_VOICES

    return {
        "arrangement_variants": {
            "applies_to": list(ARRANGEMENT_STYLES),
            "how": "Comma-separated, combine freely, e.g. 'hits_only,calm_keys,simple_bass,brushes'. "
                   "Empty = the full energetic arrangement (slap bass, riffs, lead, stabs).",
            "bass_ladder": "calm_bass (simplest) < simple_bass < pocket_bass < default slap bass (busiest)",
            # One variant per group (one per part); "calm" stands for its parts.
            "exclusive": [list(g) for g in song_plan.engine_for("funk_fusion_full").exclusive],
            "expands": {k: list(v) for k, v in song_plan.engine_for("funk_fusion_full").expands.items()},
            "variants": [{"name": n, "description": d, "needs_instruments": list(ARRANGEMENT_INSTRUMENTS.get(n, ()))}
                         for n, d in ARRANGEMENT_VARIANTS.items()],
        },
        "lead_voices": {
            "applies_to": list(SAMPLED_LEAD_STYLES),
            "default": DEFAULT_VOICE,
            "voices": {name: v.label for name, v in LEAD_VOICES.items()},
        },
        "hit_styles": {"applies_to": list(HIT_STYLES), "styles": HIT_STYLE_OPTIONS,
                       "hits": "Seconds from the start of the song (score_video: seconds into the video). "
                               "Snapped to the nearest 16th."},
        "sounds": SOUND_OPTIONS,
        "master_presets": list(MASTER_PRESETS.keys()),
        "section_roles": list(arrangement_mod.SECTION_ORDER),
        "section_overrides": {
            "shape": "{role: {key: value}}, e.g. {'verse': {'bars': 4, 'energy': 0.7}}",
            "keys": {
                "bars": "Section length in bars (1-64).",
                "energy": "0.4 (sparse) to 1.5 (big).",
                "feature_lead": "true = the lead/solo plays in this section.",
                "key": "This section's key, e.g. 'F'.",
                "scale": "major / minor / dorian ...",
                "tempo": "This section's tempo (40-260).",
                "progression": "Roman numerals, one per bar, e.g. ['ii7','V7','Imaj7','VI7'].",
                "instruments": "Instrument ids that play in this section (a subset of the band).",
                "lead": "Christmas styles: the instrument id that carries the tune in this section (a band member "
                        "that can play it, e.g. move it off a silenced choir to 'organ_church'). A finished "
                        "song's sections list who has it (melody) and who could (melody_options).",
                "knobs": "Engine knobs, e.g. {'drum_fill': 0.2}.",
            },
        },
        "video_chapter_fields": {
            "start": "Seconds into the video where the chapter begins (required).",
            "card": "Length of a title card at its start (seconds).",
            "roles": "Section roles the chapter plays, split evenly, e.g. ['verse','chorus'].",
            "key": "Key for this chapter (e.g. modulate up for the last chapter).",
            "lead": CHAPTER_LEADS,
            "intro": "true = drums build into the riff over the title card. Default: only the first chapter.",
            "arrangement": "Overrides the score's arrangement for this chapter.",
            "label": "Free text.",
        },
        "christmas": {
            "styles": dict(christmas.STYLE_INFO),
            "tunes": {"carols": carol_catalog(),
                      "original": "An original Christmas-feel tune written from the seed (AABA: ii-V turnarounds, "
                                  "secondary dominants, diminished passing chords, IV-iv-I, suspensions).",
                      "not_allowed": "Copyrighted songs (White Christmas, Let It Snow, Rudolph, Sleigh Ride, "
                                     "...) are refused; only public-domain carols or originals."},
            "arrangement_variants": [{"name": n, "description": d,
                                      "needs_instruments": list(christmas.ARRANGEMENT_INSTRUMENTS.get(n, ()))}
                                     for n, d in christmas.ARRANGEMENT_VARIANTS.items()],
            "form": "Intro (the tune's last phrase), a soft first pass, fuller passes (countermelody, sparkle), an "
                    "interlude, a last pass that may lift a half step, a tag and a held, slowing ending.",
            "length": "length_seconds 120-300 picks the number of passes of the tune.",
            "loudness": f"Delivered at {christmas.DEFAULT_LUFS:g} LUFS by default (background-ready; YouTube plays "
                        "at about -14). Pass target_lufs to change it.",
            "playlist": "christmas_mix renders N songs (styles, keys, tempos, tunes and seeds varied) crossfaded "
                        "into one WAV/MP3 with a tracklist, e.g. total_minutes=60 for an hour of ambience.",
            "backing_tracks": "Sing-along backing tracks: arrangement 'backing_track' (no melody) or "
                              "'guide_melody' (melody very quiet), with a one-bar recorded hi-hat count-in and "
                              "one verse per pass. Each render saves a timing JSON (files.timing: bars, beats, "
                              "chords in the rendered key, sections, phrases, lyric line and syllable times; "
                              "docs/backing_tracks.md). backing_tracks renders one carol in several keys at "
                              "once (default C D F G Bb + low/high voice presets) into data/outputs/backing/.",
            "lyrics": {tid: bool(_lyrics.load(tid)) for tid in carol_catalog()},
            "recipes": [
                {"name": "Cozy jazz trio, Silent Night", "tool": "generate_song",
                 "args": {"genre": "christmas_jazz_trio_full", "tune": "silent_night", "length_seconds": 180}},
                {"name": "Warm orchestral Jingle Bells with sleigh bells", "tool": "generate_song",
                 "args": {"genre": "christmas_orchestral_full", "tune": "jingle_bells",
                          "arrangement": "strings_ending"}},
                {"name": "An hour of Christmas ambience", "tool": "christmas_mix",
                 "args": {"total_minutes": 60, "target_lufs": -16}},
                {"name": "Silent Night backing track in G (sing along)", "tool": "generate_song",
                 "args": {"genre": "christmas_jazz_trio_full", "tune": "silent_night", "key": "G",
                          "arrangement": "backing_track"}},
                {"name": "Silent Night backing tracks in every key, with and without a guide", "tool": "backing_tracks",
                 "args": {"tune": "silent_night", "genre": "christmas_orchestral_full", "both": True}},
            ],
        },
        "recipes": RECIPES,
    }


def christmas_mix(
    total_minutes: Annotated[float, Field(description="Length of the mix in minutes (e.g. 60 for an hour of "
                                                      "ambience). Or give count.")] = 0,
    count: Annotated[int, Field(description="Number of songs (0 = from total_minutes).")] = 0,
    styles: Annotated[list[str], Field(description="Christmas style ids to rotate (empty = all six): "
                                                   + ", ".join(christmas.STYLE_IDS))] = [],  # noqa: B006
    tunes: Annotated[list[str], Field(description="Carol ids to draw from (empty = every carol); each plays once "
                                                  "before any repeats.")] = [],  # noqa: B006
    originals: Annotated[float, Field(description="Share of original tunes (0-1).")] = 0.4,
    min_track_seconds: Annotated[float, Field(description="Shortest song.")] = 150,
    max_track_seconds: Annotated[float, Field(description="Longest song.")] = 240,
    crossfade: Annotated[float, Field(description="Seconds of equal-power crossfade between songs.")] = 4.0,
    target_lufs: Annotated[float, Field(description="Loudness of the whole mix (YouTube plays at about -14; "
                                                     "-16 suits background listening).")] = -16.0,
    arrangement: Annotated[str, Field(description="Christmas variants for every song, e.g. 'less_busy,warmer'.")] = "",
    seed: Annotated[int, Field(description="Same seed = the same running order and songs.")] = 1,
    name: Annotated[str, Field(description="File name for the mix (in data/outputs/playlists).")] = "christmas-mix",
    formats: Annotated[list[str], Field(description="'mp3' (320 kbps) and/or 'wav' (24-bit; about 150 MB per "
                                                    "15 minutes).")] = ["mp3"],  # noqa: B006
    wait: Annotated[bool, Field(description="Wait for the whole mix (about 10-20 s of rendering per song).")] = True,
    timeout_s: int = 3600,
) -> dict:
    """Render one seamless Christmas playlist: songs generated in varied
    styles, keys, tempos and tunes (carols and originals), each levelled to
    the same loudness and joined with gentle crossfades into one file.
    Returns the files, the tracklist (with start times) and YouTube-style
    chapter lines."""
    params = {k: v for k, v in locals().items() if k not in ("wait", "timeout_s")}
    from src.api.schemas import ChristmasMixRequest
    bad = [f for f in formats if f not in ("mp3", "wav")]
    if bad or not formats:
        raise ToolError("formats must be a list of 'mp3' and/or 'wav'.")
    if count <= 0 and total_minutes <= 0:
        raise ToolError("Give total_minutes (e.g. 60) or count.")
    for t in tunes:
        _check_tune(styles[0] if styles else CHRISTMAS_STYLES[0], t)
    _variants(arrangement, CHRISTMAS_STYLES[0])
    req = ChristmasMixRequest(total_minutes=total_minutes, count=count, styles=list(styles), tunes=list(tunes),
                              originals=originals, min_track_seconds=min_track_seconds,
                              max_track_seconds=max_track_seconds, crossfade=crossfade, target_lufs=target_lufs,
                              arrangement=arrangement, seed=seed, name=name, formats=list(formats))
    job_id = _call(routes.christmas_mix, req)["job_id"]
    _start_record(job_id, "christmas_mix", params)
    return _wait(job_id, timeout_s) if wait else {"job_id": job_id, "status": "running"}


def backing_tracks(
    tune: Annotated[str, Field(description="Carol id (silent_night, jingle_bells, ...; see describe_options).")],
    genre: Annotated[str, Field(description="Christmas style id: " + ", ".join(christmas.STYLE_IDS))]
    = "christmas_orchestral_full",
    keys: Annotated[list[str], Field(description="Keys to render, e.g. ['C','G','Bb'], plus 'low' / 'high' for "
                                                 "the voice presets (the melody in a comfortable low or high "
                                                 "range). Empty = C, D, F, G, Bb, low, high (a minor carol uses "
                                                 "the relative minors).")] = [],  # noqa: B006
    tempo: Annotated[float, Field(description="BPM; 0 = the style's pick for the carol (the same for every "
                                              "key).")] = 0,
    seed: Annotated[int, Field(description="Same seed = the same arrangement in every key.")] = 1,
    guide_melody: Annotated[bool, Field(description="Keep the melody very quiet as a guide.")] = False,
    both: Annotated[bool, Field(description="Render each key twice: plain and with the guide melody.")] = False,
    length_seconds: Annotated[float, Field(description="0 = one pass per verse of the carol (up to four).")] = 0,
    arrangement: Annotated[str, Field(description="Other Christmas variants, e.g. 'less_busy,warmer'.")] = "",
    target_lufs: Annotated[float, Field(description="Delivered loudness.")] = -16.0,
    wait: Annotated[bool, Field(description="Wait for every key (about 20-60 s of rendering each).")] = True,
    timeout_s: int = 3600,
) -> dict:
    """Render one carol as a sing-along backing track in several keys at
    once: no melody (or a very quiet guide), a one-bar count-in on a recorded
    hi-hat, a clear intro and held ending, one verse per pass. Each key gets
    an MP3 and a timing JSON (bars, beats, chords in that key, sections,
    lyric line/syllable times) in data/outputs/backing/<carol>/, plus an
    index of every key and voice preset."""
    params = {k: v for k, v in locals().items() if k not in ("wait", "timeout_s")}
    from src.api.schemas import BackingTracksRequest
    from src.composition import backing as backing_mod
    from src.composition.carols import carol
    _check_genre(genre)
    if genre not in CHRISTMAS_STYLES:
        raise ToolError(f"Backing tracks are Christmas styles only ({', '.join(CHRISTMAS_STYLES)}).")
    tid = _check_tune(genre, tune)
    if tid in ("", "original") or carol(tid) is None:
        raise ToolError(f"Backing tracks need a carol ({', '.join(carol_catalog())}).")
    for k in keys:
        if str(k).lower() not in backing_mod.VOICE_PRESETS:
            try:
                backing_mod.key_pc(k)
            except ValueError as exc:
                raise ToolError(str(exc)) from None
    _variants(arrangement, genre)
    req = BackingTracksRequest(tune=tid, genre=genre, keys=list(keys), tempo=tempo or None, seed=seed,
                               guide_melody=guide_melody, both=both, length_seconds=length_seconds or None,
                               arrangement=arrangement, target_lufs=target_lufs)
    job_id = _call(routes.backing_tracks, req)["job_id"]
    _start_record(job_id, "backing_tracks", params)
    return _wait(job_id, timeout_s) if wait else {"job_id": job_id, "status": "running"}


def list_techniques(
    instrument: Annotated[str, Field(description="chords / bass / melody / drums")] = "",
    role: Annotated[str, Field(description="intro / verse / chorus / bridge / outro")] = "",
    tag: Annotated[str, Field(description="Technique family tag, e.g. 'funk_rock', 'funk_fusion'")] = "",
) -> list[dict]:
    """Low-level playing techniques in the bank (used by compose_song's
    technique_overrides). Most work never needs these."""
    from src.composition import BANK
    out = BANK.all_techniques()
    if instrument:
        out = [t for t in out if instrument in t.instruments]
    if role:
        out = [t for t in out if role in t.section_roles]
    if tag:
        out = [t for t in out if tag in t.tags]
    return [t.to_dict() for t in out]


def inspect_technique(name: Annotated[str, Field(description="Technique name from list_techniques")]) -> dict:
    """Full metadata for one technique."""
    from src.composition import BANK
    t = BANK.get(name)
    if t is None:
        return {"error": f"unknown technique {name!r}"}
    return t.to_dict()


def compose_song(
    genre: Annotated[str, Field(description="Style id (list_styles)")] = "pop",
    seed: int = 0,
    technique_overrides: Annotated[Optional[dict[str, str]], Field(
        description="Pin techniques per cell: {'verse:bass': 'funk_walk'}")] = None,
    enabled_instruments: Annotated[Optional[list[str]], Field(
        description="Parts to play, e.g. ['chords','bass','drums']")] = None,
    key: str = "",
    scale: str = "",
    tempo: float = 0.0,
    bars: int = 0,
    swing: float = -1.0,
) -> dict:
    """Quick technique-level MIDI sketch with a low-fi preview (no sampled
    render, no job). Use generate_song for real, finished tracks; use this only
    to pin specific techniques per section."""
    from src.composition.song_composer import compose_song as _compose_song
    kwargs: dict[str, Any] = {"genre": genre, "seed": int(seed),
                              "technique_overrides": technique_overrides or None}
    if enabled_instruments:
        kwargs["enabled_instruments"] = tuple(enabled_instruments)
    if key:
        kwargs["key"] = key
    if scale:
        kwargs["scale"] = scale
    if tempo and tempo > 0:
        kwargs["tempo"] = float(tempo)
    if bars and bars > 0:
        kwargs["bars"] = int(bars)
    if swing >= 0:
        kwargs["swing"] = float(swing)
    return _compose_song(**kwargs)


# ---------------------------------------------------------------------------
# Generate
# ---------------------------------------------------------------------------

def _check_sections(sections: list[str], overrides: dict) -> None:
    roles = arrangement_mod.SECTION_ORDER
    bad = [r for r in list(sections or []) + list((overrides or {}).keys()) if r not in roles]
    if bad:
        raise ToolError(f"Unknown section role(s) {bad}. Roles: {', '.join(roles)}. "
                        "(A lead instrument is chosen with lead_patch, not a section.)")


def _fit_length(genre: str, params: dict) -> dict:
    """Section bar overrides that bring the song to about ``length_seconds``
    (Christmas styles plan their own length from the tune instead)."""
    overrides = {r: dict(o) for r, o in (params.get("section_overrides") or {}).items()}
    seconds = float(params.get("length_seconds") or 0)
    if seconds <= 0 or genre in CHRISTMAS_STYLES:
        return overrides
    tempo = float(params.get("tempo") or STYLES[genre].tempo)
    return arrangement_mod.fit_length(genre, list(params.get("sections") or []), overrides, tempo, seconds)


def _submit_generate(params: dict, parent: Optional[str] = None) -> str:
    genre = params.get("genre") or "funk_fusion_full"
    _check_genre(genre)
    variants = _variants(params.get("arrangement", ""), genre)
    _check_style_supports(genre, params)
    tune = _check_tune(genre, params.get("tune") or "")
    _check_lead(params.get("lead_patch", ""))
    _check_hit_style(params.get("hit_style", ""))
    _check_sections(params.get("sections") or [], params.get("section_overrides") or {})
    preset = STYLES[genre]
    instruments = list(params.get("instruments") or [])
    extras = list(params.get("extra_instruments") or []) + _needed_instruments(variants, genre)
    if extras:
        base = instruments or list(preset.default_instruments or [])
        instruments = base + [i for i in extras if i not in base]
    name = (params.get("save_as_block") or "").strip()
    xmas = genre in CHRISTMAS_STYLES
    req = GenerateRequest(
        genre=genre,
        key=params.get("key") or None,
        scale=params.get("scale") or None,
        tempo=params.get("tempo") or None,
        progression=list(params.get("progression") or []),
        seed=params.get("seed") or None,
        swing=float(params["swing"]) if params.get("swing") is not None and params["swing"] >= 0 else None,
        instruments=instruments,
        sections=list(params.get("sections") or []),
        section_presets=dict(params.get("section_presets") or {}),
        section_overrides=_fit_length(genre, params),
        hits=list(params.get("hits") or []),
        with_stems=bool(params.get("with_stems")),
        with_pdf=bool(params.get("with_pdf")),
        master_preset=params.get("master_preset") or "default",
        sound=params.get("sound") or None,
        lead_patch=params.get("lead_patch") or None,
        hit_style=params.get("hit_style") or None,
        arrangement=",".join(variants) or None,
        target_lufs=params.get("target_lufs"),
        tune=tune or None,
        length_seconds=(float(params["length_seconds"]) if xmas and params.get("length_seconds") else None),
        save_as_block=bool(name),
        block_name=name or None,
    )
    job_id = _call(routes.generate, req)["job_id"]
    _start_record(job_id, "generate", params, parent)
    return job_id


def _check_style_supports(genre: str, params: dict) -> None:
    """Options a style would silently ignore are errors, so a model notices."""
    if params.get("arrangement") and genre not in ARRANGEMENT_STYLES:
        raise ToolError(f"Arrangement variants only work with genre {' / '.join(ARRANGEMENT_STYLES)}, not "
                        f"{genre!r}. Use genre 'funk_fusion_full' (or a Christmas style) or drop arrangement.")
    if params.get("hits") and genre not in HIT_STYLES:
        raise ToolError(f"hits only land in {' / '.join(HIT_STYLES)}, not {genre!r}. Change genre or drop hits.")


def generate_song(
    genre: Annotated[str, Field(description="Style id from list_styles. 'funk_fusion_full' is the flagship.")] = "funk_fusion_full",
    seed: Annotated[int, Field(description="0 = random (the result reports the seed used). Same seed + same options = "
                                           "the same song; a new seed = a new song in the same style.")] = 0,
    arrangement: Annotated[str, Field(description="Arrangement variants for the style, comma-separated: Funk "
                                                  "Fusion e.g. 'hits_only,calm_keys,simple_bass'; Christmas e.g. "
                                                  "'sleigh_bells,warmer'. See describe_options.")] = "",
    tune: Annotated[str, Field(description="Christmas styles only: a public-domain carol id (silent_night, "
                                           "jingle_bells, deck_the_halls, ...; see describe_options) or "
                                           "'original' / empty for an original Christmas-feel tune.")] = "",
    target_lufs: Annotated[Optional[float], Field(description="Delivered loudness (integrated LUFS). None = as "
                                                              "mastered (Christmas styles: -16, background-"
                                                              "ready; YouTube plays at about -14).")] = None,
    hits: Annotated[list[float], Field(description="Hit points in seconds from the start: the band lands an accent "
                                                   "there (Funk Fusion, neo-soul).")] = [],  # noqa: B006
    hit_style: Annotated[str, Field(description="'punch' (exact, dramatic) or 'groove' (next beat, inside the "
                                                "groove). Empty = punch.")] = "",
    lead_patch: Annotated[str, Field(description="Lead voice: punch/sonic (synth), ewi, layered, horns, trumpet, "
                                                 "guitar, guitar_high, guitar_stack, guitar_clean, trumpet_guitar.")] = "",
    tempo: Annotated[float, Field(description="BPM; 0 = the style's tempo (funk_fusion_full: 140).")] = 0,
    length_seconds: Annotated[float, Field(description="About how long the song should be, in seconds (sections "
                                                       "are scaled to fit; Christmas styles plan whole passes of "
                                                       "the tune, so 120-300 s lands within about a pass). "
                                                       "0 = the style's natural length (~1 min for "
                                                       "funk_fusion_full, ~2.5 min for Christmas).")] = 0,
    key: Annotated[str, Field(description="e.g. 'Eb', 'F#'; empty = the style's key.")] = "",
    scale: Annotated[str, Field(description="major / minor / dorian ...; empty = the style's.")] = "",
    sections: Annotated[list[str], Field(description="Section roles to include, e.g. ['intro','verse','chorus',"
                                                     "'outro']. Empty = the style's full form.")] = [],  # noqa: B006
    section_overrides: Annotated[dict[str, dict], Field(description="Per-role changes, e.g. {'verse': {'bars': 4, "
                                                                    "'energy': 0.7}}. Keys in describe_options.")] = {},  # noqa: B006
    section_presets: Annotated[dict[str, str], Field(description="Role -> another style id for that section's "
                                                                 "feel, e.g. {'bridge': 'neo_soul_full'}.")] = {},  # noqa: B006
    progression: Annotated[list[str], Field(description="Roman numerals per bar for the whole song; empty = the "
                                                        "style picks per section.")] = [],  # noqa: B006
    instruments: Annotated[list[str], Field(description="Replace the band with these instrument ids "
                                                        "(list_instruments). Empty = the style's band.")] = [],  # noqa: B006
    extra_instruments: Annotated[list[str], Field(description="Add these to the band, e.g. ['string_section',"
                                                              "'french_horn']. Variants that need instruments "
                                                              "add them automatically.")] = [],  # noqa: B006
    swing: Annotated[float, Field(description="0-1; -1 = the style's swing.")] = -1,
    sound: Annotated[str, Field(description="'sampled' or 'gm'; empty = the style's default.")] = "",
    master_preset: Annotated[str, Field(description="default / loud / cinematic / transparent")] = "default",
    with_stems: Annotated[bool, Field(description="Also write one WAV per instrument.")] = False,
    with_pdf: Annotated[bool, Field(description="Also engrave a PDF score (zip). Adds a few seconds.")] = False,
    save_as_block: Annotated[str, Field(description="Name to save the result as a library block (empty = don't).")] = "",
    wait: Annotated[bool, Field(description="Wait for the render (usually seconds) and return the files.")] = True,
    timeout_s: Annotated[int, Field(description="Longest to wait when wait=true.")] = DEFAULT_TIMEOUT_S,
) -> dict:
    """Compose and render a song: MIDI -> mixed, mastered WAV + MP3 (optional
    stems, PDF score, saved block).

    Returns the job summary: job_id, seed, key/tempo/bars, sections, and
    `files` (absolute paths to audio_wav, audio_mp3, midi...). With wait=false
    it returns the job_id at once; use wait_for_job.

    Choosing options: start from describe_options (its `recipes` are proven
    settings). For calmer / background music use arrangement variants such as
    'hits_only,calm' and a slower tempo; for more energy leave arrangement
    empty. For a length, set length_seconds (or pick fewer sections, e.g.
    sections=['intro','verse','outro']). To iterate, call revise with the job_id and only the
    options to change (it keeps the seed so only those options differ).
    """
    params = {k: v for k, v in locals().items() if k not in ("wait", "timeout_s")}
    job_id = _submit_generate(params)
    out = _wait(job_id, timeout_s) if wait else {"job_id": job_id, "status": "running"}
    if lead_patch and "hits_only" in _variants(arrangement):
        out["notes"] = ["hits_only has no lead, so lead_patch is not heard; drop hits_only to hear it."]
    return out


def _submit_score(params: dict, parent: Optional[str] = None) -> str:
    genre = params.get("genre") or "funk_fusion_full"
    _check_genre(genre)
    variants = _variants(params.get("arrangement", ""), genre)
    _check_style_supports(genre, params)
    tune = _check_tune(genre, params.get("tune") or "")
    for ch in params.get("chapters") or []:
        if isinstance(ch, dict) and ch.get("arrangement"):
            variants += [v for v in _variants(ch["arrangement"]) if v not in variants]
    _check_lead(params.get("lead_patch", ""))
    _check_hit_style(params.get("hit_style", ""))
    duration = float(params.get("duration") or 0)
    video = (params.get("video_path") or "").strip()
    if duration <= 0 and video:
        duration = video_duration(video)
    if duration <= 0:
        raise ToolError("Give the video's duration in seconds, or a video_path to read it from.")
    chapters = params.get("chapters") or [{"start": 0.0, "roles": ["verse", "chorus"]}]
    extras = list(params.get("extra_instruments") or [])
    extras += [i for i in _needed_instruments(variants) if i not in extras]
    try:
        req = VideoScoreRequest(
            duration=duration, chapters=chapters, hits=list(params.get("hits") or []),
            genre=genre, seed=int(params.get("seed") or 52),
            base_tempo=float(params.get("base_tempo") or 158.0),
            lead_patch=params.get("lead_patch") or None, with_stems=bool(params.get("with_stems")),
            hit_style=params.get("hit_style") or "groove",
            curate_hits=bool(params.get("curate_hits", True)),
            min_hit_gap=float(params.get("min_hit_gap") or 3.0),
            offset=float(params.get("offset") or 0.0),
            arrangement=",".join(_variants(params.get("arrangement", ""))),
            target_lufs=params.get("target_lufs"),
            extra_instruments=extras, stops=list(params.get("stops") or []),
        )
    except Exception as exc:  # pydantic validation → a message the model can act on
        raise ToolError(f"Bad score_video arguments: {exc}") from None
    job_id = _call(routes.score_video, req)["job_id"]
    _start_record(job_id, "score_video", {**params, "duration": duration}, parent)
    return job_id


def video_duration(path: str) -> float:
    p = Path(path).expanduser()
    if not p.exists():
        raise ToolError(f"No video at {path}")
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                              "-of", "default=nw=1:nk=1", str(p)],
                             capture_output=True, text=True, timeout=30, check=True)
        return float(out.stdout.strip())
    except (subprocess.SubprocessError, ValueError, FileNotFoundError) as exc:
        raise ToolError(f"Could not read the video's duration: {exc}") from None


def score_video(
    chapters: Annotated[list[dict], Field(description="One per video chapter, in order: {start (s, required), "
                                                      "roles, card, key, lead, intro, arrangement, label}. Each "
                                                      "chapter starts on a downbeat (tempo nudged up to 8%). "
                                                      "Empty = one chapter of verse+chorus.")] = [],  # noqa: B006
    duration: Annotated[float, Field(description="Video length in seconds (0 = read it from video_path).")] = 0,
    video_path: Annotated[str, Field(description="Path to the video (used for its duration; export_audio can "
                                                 "put the score onto it).")] = "",
    hits: Annotated[list[float], Field(description="Seconds into the video for accents (captions, cuts). [] = no "
                                                   "stabs at all.")] = [],  # noqa: B006
    genre: Annotated[str, Field(description="Style id; video scoring is built around 'funk_fusion_full'.")] = "funk_fusion_full",
    seed: Annotated[int, Field(description="Same seed = same riffs and parts.")] = 52,
    base_tempo: Annotated[float, Field(description="Target BPM; chapters are nudged around it. 120 = relaxed, "
                                                   "145 = upbeat, 158 = driving.")] = 158.0,
    arrangement: Annotated[str, Field(description="Arrangement variants for the whole score (comma-separated; "
                                                  "see describe_options). A chapter's own arrangement overrides.")] = "",
    lead_patch: Annotated[str, Field(description="Lead voice for 'synth_lead' chapters (see describe_options).")] = "",
    hit_style: Annotated[str, Field(description="'groove' (default, smoother) or 'punch'.")] = "groove",
    curate_hits: Annotated[bool, Field(description="Thin hits musically: none at chapter changes, skip each "
                                                   "chapter's first caption, keep min_hit_gap apart.")] = True,
    min_hit_gap: Annotated[float, Field(description="Seconds between curated hits.")] = 3.0,
    target_lufs: Annotated[Optional[float], Field(description="Loudness of the delivered score. None = as "
                                                              "mastered (~-12). Background under speech: -23 to "
                                                              "-28 (-25 is typical).")] = None,
    extra_instruments: Annotated[list[str], Field(description="Added to the band, e.g. ['string_section',"
                                                              "'french_horn'].")] = [],  # noqa: B006
    offset: Annotated[float, Field(description="Video time of music time 0 (negative = a pickup before the "
                                               "video starts).")] = 0.0,
    stops: Annotated[list[list[float]], Field(description="Band stops [[start, end], ...] in video seconds.")] = [],  # noqa: B006
    with_stems: bool = False,
    wait: bool = True,
    timeout_s: int = DEFAULT_TIMEOUT_S,
) -> dict:
    """Score a whole video chapter by chapter as one continuous mix, fitted to
    the video's exact length. Returns the job summary with per-chapter tempos,
    the hits that were used, the loudness, and `files`.

    Use export_audio with video_path to lay the score onto the video. Iterate
    with revise (e.g. changes={'arrangement_add': ['brushes']}).
    """
    params = {k: v for k, v in locals().items() if k not in ("wait", "timeout_s")}
    job_id = _submit_score(params)
    return _wait(job_id, timeout_s) if wait else {"job_id": job_id, "status": "running"}


def revise(
    job_id: Annotated[str, Field(description="The job to start from (generate_song, score_video or render_song).")],
    changes: Annotated[dict[str, Any], Field(description="Only the options to change, with the same names the "
                                                         "original tool takes, e.g. {'tempo': 120, 'lead_patch': "
                                                         "'horns'}. Extra keys: 'arrangement_add' / "
                                                         "'arrangement_remove' (lists of variants).")] = {},  # noqa: B006
    new_seed: Annotated[bool, Field(description="true = a fresh seed (a different take); false = keep the seed so "
                                                "only the changed options differ.")] = False,
    wait: bool = True,
    timeout_s: int = DEFAULT_TIMEOUT_S,
) -> dict:
    """Re-generate from a previous job with some options changed. The new job
    remembers its parent (revised_from), so a chain of revisions can be
    followed with list_jobs."""
    rec = _load_record(job_id)
    if not rec:
        raise ToolError(f"No recorded request for job {job_id!r}; only jobs started by these tools can be revised.")
    params = dict(rec.get("params") or {})
    changes = dict(changes or {})
    add = changes.pop("arrangement_add", []) or []
    remove = changes.pop("arrangement_remove", []) or []
    if isinstance(add, str):
        add = [add]
    if isinstance(remove, str):
        remove = [remove]
    params.update(changes)
    if add or remove:
        g = params.get("genre") or "funk_fusion_full"
        current = _variants(params.get("arrangement", ""), g)
        current = [v for v in current if v not in remove] + \
            [v for v in _variants(",".join(add), g) if v not in current]
        params["arrangement"] = ",".join(current)
    kind = rec.get("kind")
    if new_seed:
        params["seed"] = 0 if kind == "generate" else int(time.time()) % 1_000_000
    elif kind == "generate" and not params.get("seed"):
        # A random seed: reuse the one the job drew (its record may not have the result yet).
        job = _job(job_id)
        params["seed"] = (job.result.get("seed") if job.status == "done" else None) or 0
    if kind == "generate":
        new_id = _submit_generate(params, parent=job_id)
    elif kind == "score_video":
        new_id = _submit_score(params, parent=job_id)
    elif kind == "render_song":
        new_id = _submit_render(params, parent=job_id)
    else:
        raise ToolError(f"Can't revise a {kind!r} job.")
    out = _wait(new_id, timeout_s) if wait else {"job_id": new_id, "status": "running"}
    out["revised_from"] = job_id
    out["params"] = _shown_params(kind, params)
    return out


def job_status(job_id: Annotated[str, Field(description="A job_id from a generate/score/render tool.")]) -> dict:
    """Status and progress of a job; when done, its details and files."""
    return _summary(_job(job_id))


def wait_for_job(
    job_id: Annotated[str, Field(description="A job_id from a generate/score/render tool.")],
    timeout_s: Annotated[int, Field(description="Longest to wait, in seconds.")] = DEFAULT_TIMEOUT_S,
) -> dict:
    """Block until a job finishes (or the timeout), then return its summary."""
    return _wait(job_id, timeout_s)


def get_job_files(job_id: Annotated[str, Field(description="A finished job's id.")]) -> dict:
    """Absolute paths of a finished job's files (audio_wav, audio_mp3, midi,
    pdf_zip, stems) plus the audio length."""
    job = _job(job_id)
    if job.status != "done":
        raise ToolError(f"Job {job_id} is {job.status}, not done.")
    files = _files(job.result)
    return {"job_id": job_id, "files": files, "duration_seconds": _audio_seconds(files.get("audio_wav"))}


def list_jobs(limit: Annotated[int, Field(description="How many, newest first.")] = 10) -> list[dict]:
    """Recent jobs started by these tools, newest first: what was asked, its
    status, its parent (if a revision) and its audio file."""
    recs = []
    if RECORDS_DIR.exists():
        for p in RECORDS_DIR.glob("*.json"):
            try:
                recs.append(json.loads(p.read_text()))
            except (OSError, ValueError):
                continue
    recs.sort(key=lambda r: r.get("created", 0), reverse=True)
    out = []
    for r in recs[:max(1, int(limit))]:
        job = registry.get(r["job_id"])
        status = job.status if job is not None else r.get("status")
        params = _shown_params(r.get("kind"), r.get("params") or {})
        res = (job.result if job is not None and job.status == "done" else r.get("result")) or {}
        out.append({"job_id": r["job_id"], "kind": r.get("kind"), "status": status,
                    "created": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r.get("created", 0))),
                    "revised_from": r.get("parent"), "params": params,
                    "seed": res.get("seed"), "audio_wav": _files(res).get("audio_wav")})
    return out


# ---------------------------------------------------------------------------
# Render + loudness
# ---------------------------------------------------------------------------

def _submit_render(params: dict, parent: Optional[str] = None) -> str:
    timeline = list(params.get("timeline") or [])
    title = (params.get("song_title") or "").strip()
    if title and not timeline:
        timeline = _call(routes.load_song, title).get("timeline") or []
    if not timeline:
        raise ToolError("Give a timeline [{block_name, repeat}, ...] or the song_title of a saved song.")
    job_id = _call(routes.render_song, SongRenderRequest(timeline=timeline, with_pdf=bool(params.get("with_pdf"))))["job_id"]
    _start_record(job_id, "render_song", params, parent)
    return job_id


def render_song(
    timeline: Annotated[list[dict], Field(description="Blocks in order: [{'block_name': 'Intro', 'repeat': 1}, "
                                                      "...]")] = [],  # noqa: B006
    song_title: Annotated[str, Field(description="Or the title of a saved song (list_songs).")] = "",
    with_pdf: bool = False,
    wait: bool = True,
    timeout_s: int = DEFAULT_TIMEOUT_S,
) -> dict:
    """Join library blocks into one song and render it (MIDI + mixed audio,
    optional PDF). Returns the job summary with `files`."""
    params = {k: v for k, v in locals().items() if k not in ("wait", "timeout_s")}
    job_id = _submit_render(params)
    return _wait(job_id, timeout_s) if wait else {"job_id": job_id, "status": "running"}


def measure_loudness(
    source: Annotated[str, Field(description="A job_id, a block name, or a path to a .wav/.mp3.")],
) -> dict:
    """Integrated loudness (LUFS, BS.1770), true-ish sample peak (dBFS) and
    length of an audio file. Mastered tracks sit near -12 LUFS; background
    music under speech near -25."""
    import numpy as np
    import soundfile as sf
    from src.audio_processing.render.loudness import integrated_lufs

    path = _resolve_audio(source)
    audio, sr = sf.read(str(path), always_2d=True)
    audio = audio.T.astype("float32")
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    return {"path": str(path), "lufs": round(integrated_lufs(audio, sr), 1),
            "peak_dbfs": round(20 * np.log10(peak), 1) if peak > 0 else None,
            "duration_seconds": round(audio.shape[1] / sr, 2), "sample_rate": sr}


# ---------------------------------------------------------------------------
# Blocks, versions, stems, library, songs
# ---------------------------------------------------------------------------

def list_blocks(
    query: Annotated[str, Field(description="Optional filter on the block name.")] = "",
    tag: Annotated[str, Field(description="Optional tag/collection filter.")] = "",
    limit: int = 50,
) -> list[dict]:
    """Saved blocks (songs and sections in the library), newest first."""
    q = query.strip().lower()
    out = []
    for b in routes.list_blocks():
        if q and q not in str(b.get("name", "")).lower():
            continue
        if tag and tag not in (b.get("tags") or []):
            continue
        spec = b.get("spec") or {}
        out.append({"name": b.get("name"), "bars": b.get("bars"), "tempo": b.get("tempo"),
                    "duration_seconds": b.get("duration_seconds"), "tags": b.get("tags") or [],
                    "created": b.get("created"), "genre": spec.get("genre"), "seed": spec.get("seed")})
    out.sort(key=lambda d: str(d.get("created") or ""), reverse=True)
    return out[:max(1, int(limit))]


def save_block(
    job_id: Annotated[str, Field(description="A finished generate/render job.")],
    name: Annotated[str, Field(description="Block name.")],
    overwrite: Annotated[bool, Field(description="Replace a block with this name (else a number is added).")] = False,
) -> dict:
    """Save a finished job's song as a library block (so it can be versioned,
    tagged, joined into songs, and opened in the app)."""
    _job(job_id)
    return _call(routes.save_block_from_job, SaveBlockFromJobRequest(job_id=job_id, name=name, overwrite=overwrite))


def rename_block(name: str, new_name: str) -> dict:
    """Rename a block."""
    return _call(routes.rename_block, name, RenameRequest(new_name=new_name))


def set_block_tags(
    name: str,
    tags: Annotated[list[str], Field(description="The full tag list (replaces the old one).")],
) -> dict:
    """Set a block's tags (collections)."""
    return _call(routes.set_block_tags, name, TagsRequest(tags=tags))


def list_block_versions(name: str) -> dict:
    """A block's saved versions (newest first) and which one is active."""
    return _call(routes.list_block_versions, name)


def snapshot_block_version(name: str, label: str = "", note: str = "") -> dict:
    """Save the block's current state as a version (before risky edits)."""
    return _call(routes.snapshot_block_version, name, BlockVersionRequest(label=label, note=note))


def restore_block_version(name: str, version_id: str) -> dict:
    """Make a saved version the live block (the current state is snapshotted first)."""
    return _call(routes.restore_block_version, name, version_id)


def render_stems(
    source: Annotated[str, Field(description="A finished job_id or a block name.")],
) -> dict:
    """Render one WAV per instrument (stems) plus the mix, with the same sound
    and lead voice the song was made with. Returns their paths."""
    from src.audio_processing.render.pipeline import render_to_audio, style_render_args

    style = lead = None
    if registry.get(source) is not None or _load_record(source) is not None:
        job = _job(source)
        if job.status != "done":
            raise ToolError(f"Job {source} is {job.status}, not done.")
        midi = (job.result.get("_paths") or {}).get("midi")
        rec = _load_record(source) or {}
        style = job.result.get("genre") or (rec.get("params") or {}).get("genre")
        lead = (rec.get("params") or {}).get("lead_patch") or None
        out_dir = Path(midi).parent / "stems_render"
    elif block_store._midi_path(source).exists():
        midi = str(block_store._midi_path(source))
        _, meta = block_store.load_block(source)
        style = (meta.get("spec") or {}).get("genre")
        lead = style_render_args(meta.get("spec")).get("lead_patch")
        out_dir = service.API_OUT / f"stems_{block_store._safe_name(source)}"
    else:
        raise ToolError(f"{source!r} is not a finished job or a block.")
    if not midi or not Path(midi).exists():
        raise ToolError("No MIDI to render stems from.")
    if style and style not in STYLES:
        style = None
    render = render_to_audio(midi=midi, output_dir=out_dir, with_stems=True,
                             style_name=style, lead_patch=lead)
    return {"mix": str(render.mix_path),
            "stems": {track: str(p) for track, p in (render.stem_paths or {}).items()}}


def list_library() -> list[dict]:
    """The sheet-music library (what Stephen reviews in the app's Library tab):
    saved pieces with their block names and the folders each is filed in."""
    return [{**_entry_brief(e), "note": e.get("note"), "added": e.get("added")}
            for e in routes.list_library()["library"]]


def add_to_library(
    block_name: Annotated[str, Field(description="The saved block to add (see list_blocks).")],
    title: Annotated[str, Field(description="Display title (default: the block name).")] = "",
    collection: str = "",
    note: Annotated[str, Field(description="A note shown with the piece.")] = "",
    folder: Annotated[str, Field(description="Folder to file it in: id, path ('Videos / Christmas Mix 1') "
                                             "or unique name. It goes at the end of the folder's order. "
                                             "Create the folder first with create_folder.")] = "",
) -> dict:
    """Add a block to the sheet-music library so it shows up in the app's
    Library tab for review, optionally straight into a folder. Re-adding a
    block keeps its favorite flag and folders. (``collection`` is the legacy
    grouping; prefer ``folder``.)"""
    res = _call(routes.add_to_library, LibrarySaveRequest(block_name=block_name, title=title or None,
                                                          collection=collection, note=note, folder=folder))
    return {"saved": res["saved"], "entry": _entry_brief(res["entry"])}


# --- Library folders -------------------------------------------------------

_FOLDER_REF = ("A folder id, its path ('Videos / Christmas Mix 1'), or its name when unique. "
               "'Unfiled' means songs in no folder.")
_ITEM_REF = "A library entry id or a block name."


def _entry_brief(e: dict) -> dict:
    return {"id": e.get("id"), "title": e.get("title"), "block_name": e.get("block_name"),
            "favorite": e.get("favorite"), "folders": [f["path"] for f in e.get("folders") or []]}


def _entry_id(item: str) -> str:
    from src.daw_integration.generic import library as library_store
    return library_store._safe_id(item)


def list_folders() -> dict:
    """Library folders (one per video, e.g. 'Videos / Christmas Mix 1'), with
    item counts. Top-level folders come first, each followed by its
    subfolders; ``unfiled`` counts library songs that are in no folder."""
    return _call(routes.list_library_folders)


def create_folder(
    name: Annotated[str, Field(description="Folder name (no '/'). Unique among its siblings.")],
    parent: Annotated[str, Field(description="Make it a subfolder of this top-level folder "
                                             "(one level deep). Empty = top level.")] = "",
    description: Annotated[str, Field(description="What the folder is for, e.g. the video it "
                                                  "becomes ('1-hour cozy Christmas mix, upload Dec 1').")] = "",
) -> dict:
    """Create a library folder, e.g. one per YouTube video. Use parent to nest
    it (e.g. name='Christmas Mix 1', parent='Videos'). Returns the folder with
    its id."""
    return _call(routes.create_library_folder,
                 FolderCreateRequest(name=name, parent=parent, description=description))["folder"]


def rename_folder(
    folder: Annotated[str, Field(description=_FOLDER_REF)],
    new_name: Annotated[str, Field(description="New name (empty = keep the name).")] = "",
    description: Annotated[Optional[str], Field(description="New description (omit to keep it).")] = None,
    parent: Annotated[Optional[str], Field(description="Move it under this top-level folder; '' = to "
                                                       "the top level; omit to keep it where it is.")] = None,
) -> dict:
    """Rename a library folder, and/or change its description or parent.
    Its songs and their order don't change."""
    return _call(routes.update_library_folder, folder,
                 FolderUpdateRequest(name=new_name or None, description=description, parent=parent))["folder"]


def delete_folder(folder: Annotated[str, Field(description=_FOLDER_REF)]) -> dict:
    """Delete a library folder. Never deletes songs: they stay in the library
    (in Unfiled if they're in no other folder), and its subfolders move to
    the top level. Returns which songs became unfiled."""
    return _call(routes.delete_library_folder, folder)


def get_folder(folder: Annotated[str, Field(description=_FOLDER_REF)]) -> dict:
    """A folder's details and its songs in track order (the order the video
    plays them), each with id, title, block name and all folders it's in."""
    f = _call(routes.get_library_folder, folder)["folder"]
    return {**f, "items": [_entry_brief(e) for e in f["items"]]}


def add_to_folder(
    folder: Annotated[str, Field(description=_FOLDER_REF)],
    items: Annotated[list[str], Field(description="Songs to add, each a library entry id or a block "
                                                  "name. A block that isn't in the library yet is added "
                                                  "to it first.")],
    position: Annotated[Optional[int], Field(description="0-based place to insert them (default: the end).")] = None,
) -> dict:
    """Put songs into a folder (a copy: they stay in any other folders too).
    Songs already in the folder keep their place. Use move_to_folder to move
    instead of copy."""
    from src.daw_integration.generic import library as library_store

    entry_ids, block_names = [], []
    for item in items:
        try:
            entry_ids.append(library_store.get_entry(item)["id"])
        except FileNotFoundError:
            block_names.append(item)
    res = _call(routes.add_library_folder_items, folder,
                FolderItemsRequest(entry_ids=entry_ids, block_names=block_names, position=position))
    return get_folder(res["folder"]["id"])


def move_to_folder(
    item: Annotated[str, Field(description=_ITEM_REF)],
    to_folder: Annotated[str, Field(description=_FOLDER_REF + " Moving to 'Unfiled' takes it out of folders.")],
    from_folder: Annotated[str, Field(description="Only take it out of this folder (empty = out of every "
                                                  "other folder).")] = "",
    position: Annotated[Optional[int], Field(description="0-based place in the destination (default: end).")] = None,
) -> dict:
    """Move a library song into another folder. Returns the folders it's in now."""
    return _call(routes.move_library_entry, FolderMoveRequest(
        entry_id=_entry_id(item), to_folder=to_folder, from_folder=from_folder, position=position))


def remove_from_folder(
    folder: Annotated[str, Field(description=_FOLDER_REF)],
    item: Annotated[str, Field(description=_ITEM_REF)],
) -> dict:
    """Take a song out of one folder. The song stays in the library."""
    return _call(routes.remove_library_folder_item, folder, _entry_id(item))["folder"]


def reorder_folder(
    folder: Annotated[str, Field(description=_FOLDER_REF)],
    order: Annotated[list[str], Field(description="Songs (entry ids or block names) in the new order. "
                                                  "Any you leave out keep their order after these.")],
) -> dict:
    """Set the track order of a folder (the order the video plays them).
    Returns the folder with its songs in the new order."""
    res = _call(routes.reorder_library_folder, folder,
                FolderReorderRequest(entry_ids=[_entry_id(i) for i in order]))
    return get_folder(res["folder"]["id"])


def list_songs() -> dict:
    """Saved songs (timelines of blocks) — render one with render_song."""
    return routes.list_songs()


def save_song(
    title: str,
    timeline: Annotated[list[dict], Field(description="[{'block_name': 'Intro', 'repeat': 1}, ...]")],
    overwrite: bool = False,
) -> dict:
    """Save a timeline of blocks as a named song."""
    return _call(routes.save_song, SongSaveRequest(title=title, timeline=timeline, overwrite=overwrite))


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def export_audio(
    source: Annotated[str, Field(description="A job_id, a block name, or a path to a .wav/.mp3.")],
    dest_dir: Annotated[str, Field(description="Folder to write into.")] = "~/Downloads",
    name: Annotated[str, Field(description="File name without extension (default: style-seed-job).")] = "",
    formats: Annotated[list[str], Field(description="Any of 'wav' (24-bit), 'mp3' (320k).")] = ["wav", "mp3"],  # noqa: B006
    target_lufs: Annotated[Optional[float], Field(description="Normalise to this loudness first (e.g. -25 for a "
                                                              "background bed). None = keep as is.")] = None,
    video_path: Annotated[str, Field(description="Also write an .mp4 of this video with the audio replaced by "
                                                 "the song.")] = "",
    overwrite: bool = False,
) -> dict:
    """Deliver a song: copy it out of the studio as WAV/MP3 (optionally at a
    target loudness) and optionally onto a video as an MP4. Job folders are
    pruned after a while, so export anything worth keeping."""
    import soundfile as sf
    from src.audio_processing.render.loudness import integrated_lufs, normalize

    src = _resolve_audio(source)
    dest = Path(dest_dir).expanduser()
    dest.mkdir(parents=True, exist_ok=True)
    if not name:
        rec = _load_record(source) or {}
        res = rec.get("result") or {}
        genre = res.get("genre") or (rec.get("params") or {}).get("genre") or ""
        name = "-".join(str(x) for x in (genre, res.get("seed"), source if rec else src.stem) if x)
    name = name.replace("/", "_").strip() or "song"
    bad = [f for f in formats if f not in ("wav", "mp3")]
    if bad or not formats:
        raise ToolError("formats must be a list of 'wav' and/or 'mp3'.")

    targets = {f: dest / f"{name}.{f}" for f in formats}
    if video_path:
        targets["mp4"] = dest / f"{name}.mp4"
    clash = [str(p) for p in targets.values() if p.exists()]
    if clash and not overwrite:
        raise ToolError(f"Already exists: {clash}. Pass overwrite=true or another name.")

    audio, sr = sf.read(str(src), always_2d=True)
    audio = audio.T.astype("float32")
    if target_lufs is not None:
        audio, _ = normalize(audio, sr, float(target_lufs))
    lufs = round(integrated_lufs(audio, sr), 1)
    wav = targets.get("wav") or (service.API_OUT / f"_export_{name}.wav")
    sf.write(str(wav), audio.T, sr, subtype="PCM_24")
    try:
        if "mp3" in targets and not block_store.write_preview_mp3(wav, targets["mp3"], bitrate="320k"):
            raise ToolError("MP3 encoding failed (is ffmpeg installed?).")
        if video_path:
            video = Path(video_path).expanduser()
            if not video.exists():
                raise ToolError(f"No video at {video_path}")
            cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-i", str(wav),
                   "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-b:a", "256k",
                   "-shortest", str(targets["mp4"])]
            run = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            if run.returncode != 0:
                raise ToolError(f"ffmpeg could not write the video: {run.stderr.strip()[-400:]}")
    finally:
        if "wav" not in targets:
            wav.unlink(missing_ok=True)
    return {"files": {k: str(v) for k, v in targets.items()}, "lufs": lufs,
            "duration_seconds": round(audio.shape[1] / sr, 2)}


# --- Create sessions (the app's song threads) -------------------------------

_SESSION_REF = "A session id from list_sessions (or the id open_block_as_session returned)."


def _session_call(fn, *args, **kwargs):
    from src.api import sessions
    try:
        return fn(*args, **kwargs)
    except sessions.SessionError as exc:
        raise ToolError(str(exc)) from None


def _version_brief(v: dict) -> dict:
    r = v.get("result") or {}
    return {"n": v["n"], "status": v.get("status"), "made_from": v.get("from"), "seed": v.get("seed"),
            "plan": v.get("plan"), "changes": v.get("changes") or [], "interpreter": v.get("interpreter"),
            "job_id": v.get("jobId"), "block": v.get("block"), "in_library": bool(v.get("savedAs")),
            "audio": "missing (render again)" if v.get("audio") else ("ok" if v.get("status") == "done" else None),
            "error": v.get("error"),
            "sections": [f"{x['label']} ({x['bars']} bars)" for x in r.get("sections") or []],
            "key": r.get("key"), "tempo": r.get("tempo")}


def list_sessions(limit: Annotated[int, Field(description="How many, most recent first (0 = all).")] = 20) -> list[dict]:
    """Stephen's songs in the app's Create screen (its History): one thread
    per song, with its style, how many versions and the latest one. Continue
    one with revise_session."""
    from src.api import sessions
    return sessions.list_sessions(limit)


def get_session(session: Annotated[str, Field(description=_SESSION_REF)]) -> dict:
    """One song's whole thread: what was asked and answered, and every
    version (its plan, seed, what changed, its block in Practice)."""
    from src.api import sessions
    s = _session_call(sessions.get, session)
    return {"id": s["id"], "title": s.get("title"), "created": s.get("created"), "updated": s.get("updated"),
            "messages": [{k: m[k] for k in ("role", "kind", "text", "changes", "notes", "version") if m.get(k)}
                         for m in s["msgs"]],
            "versions": [_version_brief(v) for v in s["versions"]]}


def open_block_as_session(
    block: Annotated[str, Field(description="A block name (list_blocks / list_library).")],
) -> dict:
    """Open a saved block as a song thread, the way the app's Library →
    Open in Timeline does: the block's own session if it came from one,
    else a new session whose v1 is the block (its audio and seed) planned
    from its saved settings, ready for revise_session."""
    from src.api import sessions
    r = _session_call(sessions.from_block, block)
    s = r["session"]
    return {"session_id": s["id"], "title": s.get("title"), "version": r.get("version"),
            "versions": [_version_brief(v) for v in s["versions"]]}


def revise_session(
    session: Annotated[str, Field(description=_SESSION_REF)],
    feedback: Annotated[str, Field(description="What to change, in plain English, e.g. 'quieter, simpler "
                                               "bass, no trumpet stabs'.")],
    wait: Annotated[bool, Field(description="Wait for the new version's render.")] = True,
    timeout_s: Annotated[int, Field(description="Longest to wait when wait=true.")] = DEFAULT_TIMEOUT_S,
) -> dict:
    """Continue a song's thread in the app: feedback on its latest version →
    the revised plan (same seed, so only what you asked for changes) → the
    next version, added to the same session (Stephen sees it in Create and
    it joins Practice). Returns what changed and the new version."""
    from src.api import sessions
    out = _session_call(sessions.revise, session, feedback, wait, timeout_s)
    if out.get("version"):
        out["version"] = _version_brief(out["version"])
    return out


def _options_doc() -> str:
    """The option catalog, appended to the generating tools' descriptions so a
    model sees every choice without another call."""
    from src.audio_processing.render.lead_voices import LEAD_VOICES
    lines = ["", "", "Arrangement variants (funk_fusion_full; combine with commas):"]
    lines += [f"- {n}: {d}" for n, d in ARRANGEMENT_VARIANTS.items()]
    lines += ["", "Christmas arrangement variants (christmas_* styles):"]
    lines += [f"- {n}: {d}" for n, d in christmas.ARRANGEMENT_VARIANTS.items()]
    lines += ["", "Christmas tunes (tune): " + ", ".join(carol_catalog()) + ", original"]
    lines += ["", "Lead voices (lead_patch):"]
    lines += [f"- {n}: {v.label}" for n, v in LEAD_VOICES.items()]
    lines += ["", "hit_style:"] + [f"- {k}: {v}" for k, v in HIT_STYLE_OPTIONS.items()]
    return "\n".join(lines)


for _fn in (generate_song, score_video, revise):
    _fn.__doc__ = inspect.cleandoc(_fn.__doc__ or "") + _options_doc()


# ---------------------------------------------------------------------------
# Registry — the order here is the order models see the tools in.
# ---------------------------------------------------------------------------

TOOLS = [
    # discover
    describe_options, list_styles, list_genres, list_instruments,
    # generate + iterate
    generate_song, christmas_mix, backing_tracks, score_video, revise, job_status, wait_for_job, get_job_files, list_jobs,
    # render + loudness
    render_song, measure_loudness, render_stems,
    # library
    list_blocks, save_block, rename_block, set_block_tags,
    list_block_versions, snapshot_block_version, restore_block_version,
    list_library, add_to_library, list_songs, save_song,
    # Create sessions (song threads)
    list_sessions, get_session, open_block_as_session, revise_session,
    # library folders (one per video)
    list_folders, create_folder, rename_folder, delete_folder, get_folder,
    add_to_folder, move_to_folder, remove_from_folder, reorder_folder,
    # export
    export_audio,
    # low level
    list_techniques, inspect_technique, compose_song,
]
TOOLS_BY_NAME = {fn.__name__: fn for fn in TOOLS}


def call(name: str, args: Optional[dict] = None) -> Any:
    """Run a tool by name, validating and coercing ``args`` the same way the
    MCP server does (the HTTP endpoint's entry point)."""
    from mcp.server.fastmcp.utilities.func_metadata import func_metadata

    fn = TOOLS_BY_NAME.get(name)
    if fn is None:
        raise ToolError(f"Unknown tool {name!r}.{_suggest(name, TOOLS_BY_NAME)}")
    args = {k: v for k, v in (args or {}).items() if v is not None}     # null = "not given"
    accepted = list(inspect.signature(fn).parameters)
    unknown = [k for k in args if k not in accepted]
    if unknown:
        raise ToolError(f"{name} has no argument(s) {unknown}. It takes: {', '.join(accepted)}.")
    try:
        model = func_metadata(fn).arg_model.model_validate(args)
    except Exception as exc:  # pydantic ValidationError → a message the model can act on
        raise ToolError(f"Bad arguments for {name}: {exc}") from None
    return fn(**model.model_dump_one_level())

