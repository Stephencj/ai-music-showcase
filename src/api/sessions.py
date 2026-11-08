"""Create sessions: a song's thread, kept on the server so it survives a
reload, another device and a restart, and so "New song" archives instead of
clearing.

A session is one song: its title, the messages of the thread (your
description, feedback and timeline edits, the app's replies) and the versions
they made (v1, v2, …). Each version is a /generate job: its plan (a
GenerateRequest body, seed included), the job id while it lives, what changed
and who interpreted it. One JSON file per session at
``data/sessions/<id>.json``, written atomically.

Every finished version is saved as a block automatically (``<title> vN``,
tagged ``auto-saved``, linked back to its session), so it's in the Practice
pool and its audio outlives the job. The Library only lists what you save to
it. A version's audio also goes to a small render cache
(``data/sessions/renders/``, oldest pruned past a size limit). After a
restart a version's job is re-registered from its block or the cache; when
both are gone it is rendered again on demand from its plan + seed (the same
seed makes the same song).
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import tempfile
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from src.daw_integration.generic import blocks as block_store
from src.daw_integration.generic import library as library_store

from .jobs import registry

logger = logging.getLogger("ai_music_studio.api.sessions")

SESSIONS_DIR = Path("data/sessions")
RENDERS_DIR = SESSIONS_DIR / "renders"
AUTO_TAG = "auto-saved"
# The render cache's size limit (MB); the oldest versions go first.
CACHE_LIMIT_MB = float(os.environ.get("AI_MUSIC_SESSION_CACHE_MB", "400"))
TITLE_LIMIT = 32

_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
# Version fields the server owns: a client's copy never overwrites them.
_SERVER_OWNED = ("block", "savedAs", "audio", "seed", "finalized")
_TERMINAL = ("done", "error")

_locks: dict[str, threading.RLock] = {}
_locks_guard = threading.Lock()
_watching: set[tuple[str, int, str]] = set()
_ids = iter(range(1, 1 << 62))


class SessionError(ValueError):
    """A request that can't be done (shown to the user as is)."""


class SessionNotFound(SessionError):
    pass


# ---------------------------------------------------------------------------
# Names
# ---------------------------------------------------------------------------
def clean_title(text: Optional[str], limit: int = TITLE_LIMIT) -> str:
    """A song title fit for a block name: no ellipsis, cut at a word
    boundary, never empty."""
    t = re.sub(r"\s+", " ", re.sub(r"…|\.{3,}", " ", text or "")).strip(" .,;:-–—")
    if len(t) > limit:
        head = t[:limit + 1]
        t = head.rsplit(" ", 1)[0] if " " in head else t[:limit]
        t = t.rstrip(" .,;:-–—")
    return t or "Song"


def version_block_name(title: Optional[str], n: int) -> str:
    return f"{clean_title(title)} v{n}"


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------
def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _new_id() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]


def _msg_id() -> str:
    return f"{int(time.time() * 1000):x}-s{next(_ids)}"


def _path(sid: str) -> Path:
    if not isinstance(sid, str) or not _ID_RE.match(sid):
        raise SessionNotFound(f"No session {sid!r}")
    return SESSIONS_DIR / f"{sid}.json"


def _lock(sid: str) -> threading.RLock:
    with _locks_guard:
        return _locks.setdefault(sid, threading.RLock())


def _read(sid: str) -> dict:
    p = _path(sid)
    if not p.exists():
        raise SessionNotFound(f"No session {sid!r}")
    with open(p, "r") as f:
        return json.load(f)


def _write(s: dict, touch: bool = True) -> None:
    """Write a session atomically: a temp file in the same folder, then a
    rename, so a reader (or a crash) never sees half a file."""
    if touch:
        s["updated"] = _now()
    p = _path(s["id"])
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=f".{p.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(s, f, ensure_ascii=False, indent=1)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o644)
        os.replace(tmp, p)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def exists(sid: Optional[str]) -> bool:
    try:
        return bool(sid) and _path(sid).exists()
    except SessionNotFound:
        return False


# ---------------------------------------------------------------------------
# Merging a client's copy
# ---------------------------------------------------------------------------
def _public(result: Any) -> Optional[dict]:
    if not isinstance(result, dict):
        return None
    return {k: v for k, v in result.items() if not k.startswith("_")}


def _merge_version(cur: dict, new: dict) -> dict:
    """A client's copy of a version onto the stored one. The plan is the
    client's; the job's outcome is the server's once it knows it (and only a
    copy of the same job may report on it); block / library links and the
    audio state are the server's."""
    out = dict(cur)
    same_job = not cur.get("jobId") or new.get("jobId") == cur.get("jobId")
    for k, v in new.items():
        if k in _SERVER_OWNED and cur.get(k) is not None:
            continue
        if k == "jobId" and cur.get("jobId"):
            continue
        if k in ("status", "result", "error", "progress", "message") and (
                not same_job or cur.get("status") in _TERMINAL):
            continue
        out[k] = _public(v) if k == "result" else v
    return out


def _merge_items(s: dict, msgs: Optional[list] = None, versions: Optional[list] = None) -> None:
    if msgs is not None:
        mine = {m.get("id"): m for m in s["msgs"]}
        theirs = [m for m in msgs if isinstance(m, dict) and m.get("id")]
        ids = {m["id"] for m in theirs}
        # The client's order (it holds the thread), then any the server added.
        s["msgs"] = [{**mine.get(m["id"], {}), **m} for m in theirs] + \
            [m for m in s["msgs"] if m.get("id") not in ids]
    if versions is not None:
        by_n = {v["n"]: v for v in s["versions"]}
        for v in versions:
            if not isinstance(v, dict) or not isinstance(v.get("n"), int):
                continue
            if v["n"] in by_n:
                by_n[v["n"]] = _merge_version(by_n[v["n"]], v)
            else:
                by_n[v["n"]] = {k: (_public(x) if k == "result" else x) for k, x in v.items()}
        s["versions"] = [by_n[n] for n in sorted(by_n)]
    # A version keeps what changed and who read it (from the reply that made it).
    for m in s["msgs"]:
        n = m.get("version")
        v = next((x for x in s["versions"] if x["n"] == n), None) if n is not None else None
        if v is not None:
            if m.get("changes") and not v.get("changes"):
                v["changes"] = list(m["changes"])
            if m.get("interpreter") and not v.get("interpreter"):
                v["interpreter"] = m["interpreter"]
    for v in s["versions"]:
        seed = (v.get("plan") or {}).get("seed") or (v.get("result") or {}).get("seed")
        if seed and not v.get("seed"):
            v["seed"] = seed
        # A version saved to the library before auto-save: that block is its audio.
        if v.get("savedAs") and not v.get("block"):
            v["block"] = v["savedAs"]


# ---------------------------------------------------------------------------
# Jobs: follow, finalize (auto-save + cache), adopt after a restart, re-render
# ---------------------------------------------------------------------------
def _job_result_public(job_id: str) -> Optional[dict]:
    from . import routes
    try:
        return routes.job_status(job_id).get("result")
    except Exception:  # noqa: BLE001 — unknown job
        return None


def _watch(sid: str, n: int, job_id: str) -> None:
    """Finalize a version when its job ends, even if no client is watching."""
    key = (sid, n, job_id)
    if key in _watching:
        return
    _watching.add(key)

    def run() -> None:
        try:
            while True:
                job = registry.get(job_id)
                if job is None:
                    return
                if job.status in _TERMINAL:
                    try:
                        finalize(sid, n)
                    except SessionError:
                        pass
                    return
                time.sleep(1.0)
        finally:
            _watching.discard(key)

    threading.Thread(target=run, name=f"session-{sid}-v{n}", daemon=True).start()


def _block_ok(name: Optional[str]) -> bool:
    return bool(name) and block_store._midi_path(name).exists()


def _render_dir(sid: str, n: int) -> Path:
    return RENDERS_DIR / sid / f"v{n}"


def _cache_render(sid: str, n: int, result: dict) -> None:
    """Keep a version's audio (MP3) and MIDI in the render cache."""
    paths = result.get("_paths") or {}
    midi, mp3 = paths.get("midi"), paths.get("audio_mp3")
    if not midi or not mp3 or not Path(midi).exists() or not Path(mp3).exists():
        return
    d = _render_dir(sid, n)
    try:
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True)
        shutil.copyfile(midi, d / "song.mid")
        shutil.copyfile(mp3, d / "mix.mp3")
    except OSError as exc:
        logger.warning("session %s v%d: couldn't cache the render: %s", sid, n, exc)
        shutil.rmtree(d, ignore_errors=True)
        return
    prune_cache(keep=d)


def _dir_size(d: Path) -> int:
    return sum(p.stat().st_size for p in d.rglob("*") if p.is_file())


def prune_cache(limit_mb: Optional[float] = None, keep: Optional[Path] = None) -> list[str]:
    """Drop the oldest cached renders until the cache fits ``limit_mb``."""
    limit = (CACHE_LIMIT_MB if limit_mb is None else limit_mb) * 1024 * 1024
    if not RENDERS_DIR.exists():
        return []
    dirs = [d for s in RENDERS_DIR.iterdir() if s.is_dir() for d in s.iterdir() if d.is_dir()]
    sizes = {d: _dir_size(d) for d in dirs}
    total = sum(sizes.values())
    removed: list[str] = []
    for d in sorted(dirs, key=lambda d: d.stat().st_mtime):
        if total <= limit:
            break
        if keep is not None and d == keep:
            continue
        shutil.rmtree(d, ignore_errors=True)
        total -= sizes[d]
        removed.append(f"{d.parent.name}/{d.name}")
        if not any(d.parent.iterdir()):
            d.parent.rmdir()
    return removed


def _sources(sid: str, v: dict) -> Optional[dict]:
    """Where a version's audio still is: its block, else the render cache."""
    for name in (v.get("block"), v.get("savedAs")):
        if not _block_ok(name):
            continue
        wav, mp3 = block_store._wav_path(name), block_store._preview_path(name)
        paths = {"midi": str(block_store._midi_path(name)),
                 "audio_wav": str(wav) if wav.exists() else None,
                 "audio_mp3": str(mp3) if mp3.exists() else None}
        if paths["audio_wav"] or paths["audio_mp3"]:
            return paths
    d = _render_dir(sid, v["n"])
    if (d / "song.mid").exists() and (d / "mix.mp3").exists():
        return {"midi": str(d / "song.mid"), "audio_mp3": str(d / "mix.mp3"), "audio_wav": None}
    return None


def _adopt(sid: str, v: dict) -> bool:
    """Re-register a finished version's job from its block or the cache, so
    every job route (audio, peaks, split, save) serves it again."""
    paths = _sources(sid, v)
    if not paths:
        return False
    r = dict(v.get("result") or {})
    secs = r.get("sections") or []
    cursor, split = 0, []
    for s in secs:
        bars = int(s.get("bars") or 0)
        split.append({"start_bar": cursor, "end_bar": cursor + bars - 1,
                      "label": s.get("label"), "role": s.get("role")})
        cursor += bars
    meta = block_store.read_meta(v["block"]) if _block_ok(v.get("block")) else None
    peaks_dir = _render_dir(sid, v["n"]) / "peaks"
    peaks_dir.mkdir(parents=True, exist_ok=True)
    result = {k: x for k, x in r.items() if k != "urls"}
    result.update({
        "saved_block": v.get("block"), "section_blocks": [],
        "_paths": paths,
        "_split": {"tempo": r.get("tempo"), "time_signature": r.get("time_signature") or [4, 4],
                   "sections": split},
        "_spec": (meta or {}).get("spec"),
        "_peaks_dir": str(peaks_dir),
    })
    jid = v.get("jobId") or f"s-{sid}-v{v['n']}"
    registry.adopt(jid, result)
    v["jobId"] = jid
    v["result"] = _job_result_public(jid) or r
    return True


def _hydrate(s: dict) -> bool:
    """Bring each version's job up to date with this process; True when the
    session changed."""
    changed = False
    for v in s["versions"]:
        job = registry.get(v["jobId"]) if v.get("jobId") else None
        if v.get("status") == "running":
            if v.get("jobId") and job is None:
                v.update(status="error", error="Interrupted (the server restarted)")
                changed = True
            elif job is not None and job.status in _TERMINAL:
                changed |= _finalize_locked(s, v)
            elif job is not None:
                _watch(s["id"], v["n"], v["jobId"])
        if v.get("status") == "done":
            ok = (job is not None and job.status == "done") or _adopt(s["id"], v)
            if ok and v.get("audio"):
                v.pop("audio")
                changed = True
            elif not ok:
                if v.get("audio") != "missing":
                    changed = True
                v["audio"] = "missing"
                if isinstance(v.get("result"), dict):
                    v["result"]["urls"] = {**(v["result"].get("urls") or {}), "audio": None,
                                           "audio_hifi": None, "midi": None}
    return changed


def _finalize_locked(s: dict, v: dict) -> bool:
    job = registry.get(v["jobId"]) if v.get("jobId") else None
    if job is None or job.status not in _TERMINAL or v.get("finalized") == job.id:
        return False
    v["finalized"] = job.id
    if job.status == "error":
        v.update(status="error", error=job.error or "Generation failed")
        return True
    v.update(status="done", progress=1, message="done", error=None)
    v["result"] = _job_result_public(job.id) or v.get("result")
    seed = (v.get("plan") or {}).get("seed") or (v["result"] or {}).get("seed")
    if seed:
        v["seed"] = seed
        v["plan"] = {**(v.get("plan") or {}), "seed": seed}
    v.pop("audio", None)
    if not _block_ok(v.get("block")):
        from . import service
        try:
            name = block_store._safe_name(service.save_job_as_block(
                job.result, version_block_name(s.get("title"), v["n"]), tags=[AUTO_TAG]))
            block_store.set_session(name, {"id": s["id"], "version": v["n"]})
            v["block"] = name
        except Exception as exc:  # noqa: BLE001 — the version still plays from its job
            logger.warning("session %s v%d: auto-save failed: %s", s["id"], v["n"], exc)
    _cache_render(s["id"], v["n"], job.result)
    return True


def finalize(sid: str, n: int) -> dict:
    """Record a version's finished job: its result and seed, the auto-saved
    block (``<title> vN``, the Practice pool) and the cached render.
    Idempotent; returns the version."""
    with _lock(sid):
        s = _read(sid)
        v = _version(s, n)
        if _finalize_locked(s, v):
            _write(s)
        return v


def render(sid: str, n: int) -> dict:
    """A version whose audio is gone, rendered again from its plan + seed
    (the same song). Returns the version, now running a new job."""
    from . import routes
    from .schemas import GenerateRequest
    with _lock(sid):
        s = _read(sid)
        _hydrate(s)
        v = _version(s, n)
        if v.get("status") == "running" or (v.get("status") == "done" and not v.get("audio")):
            return v
        plan = dict(v.get("plan") or {})
        if v.get("seed") and not plan.get("seed"):
            plan["seed"] = v["seed"]
        job_id = routes.generate(GenerateRequest(**plan_request(plan)))["job_id"]
        v.update(jobId=job_id, status="running", progress=0, message="Rendering again…", error=None)
        v.pop("audio", None)
        v.pop("finalized", None)
        _write(s)
        _watch(sid, n, job_id)
        return v


def plan_request(plan: dict) -> dict:
    """A plan as a /generate body (what the Create screen sends)."""
    return {**plan, "instruments": plan.get("instruments") or [], "sections": plan.get("sections") or [],
            "with_pdf": False, "with_stems": False, "master_preset": "default"}


def _version(s: dict, n: int) -> dict:
    v = next((x for x in s["versions"] if x["n"] == n), None)
    if v is None:
        raise SessionNotFound(f"Session {s['id']} has no v{n}")
    return v


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------
def _after_change(s: dict) -> None:
    for v in s["versions"]:
        if v.get("status") == "running" and v.get("jobId"):
            _watch(s["id"], v["n"], v["jobId"])


def create(title: str = "", interpreter: Optional[str] = None,
           msgs: Optional[list] = None, versions: Optional[list] = None) -> dict:
    """A new session (empty, or a thread brought over from the browser)."""
    s = {"id": _new_id(), "title": (title or "").strip(), "created": _now(), "updated": _now(),
         "interpreter": interpreter, "msgs": [], "versions": []}
    with _lock(s["id"]):
        _merge_items(s, msgs or [], versions or [])
        _hydrate(s)
        _write(s)
        _after_change(s)
        return s


def get(sid: str) -> dict:
    with _lock(sid):
        s = _read(sid)
        if _hydrate(s):
            _write(s, touch=False)
        return s


def update(sid: str, title: Optional[str] = None, interpreter: Optional[str] = None,
           msgs: Optional[list] = None, versions: Optional[list] = None) -> dict:
    """Merge a client's copy of the thread (see ``_merge_version``)."""
    with _lock(sid):
        s = _read(sid)
        if title is not None:
            s["title"] = title.strip()
        if interpreter is not None:
            s["interpreter"] = interpreter
        _merge_items(s, msgs, versions)
        _hydrate(s)
        _write(s)
        _after_change(s)
        return s


def append(sid: str, msgs: Optional[list] = None, versions: Optional[list] = None) -> dict:
    """Add messages / versions after the ones there (by id / number)."""
    with _lock(sid):
        s = _read(sid)
        new_msgs = [{**m, "id": m.get("id") or _msg_id()} for m in (msgs or []) if isinstance(m, dict)]
        _merge_items(s, s["msgs"] + new_msgs, versions or [])
        _hydrate(s)
        _write(s)
        _after_change(s)
        return s


def rename(sid: str, title: str) -> dict:
    if not (title or "").strip():
        raise SessionError("Give the song a name")
    return update(sid, title=title)


def delete(sid: str) -> dict:
    """Delete a session and its cached renders. Its auto-saved versions leave
    the Practice pool too, unless you saved them to the library; any other
    block it was opened from just loses the link."""
    removed: list[str] = []
    with _lock(sid):
        s = _read(sid)
        for v in s["versions"]:
            name = v.get("block")
            meta = block_store.read_meta(name) if name else None
            if not meta or (meta.get("session") or {}).get("id") != sid:
                continue
            in_library = library_store._path(library_store._safe_id(name)).exists()
            if AUTO_TAG in (meta.get("tags") or []) and not in_library:
                block_store.delete_block(name)
                removed.append(block_store._safe_name(name))
            else:
                block_store.set_session(name, None)
        _path(sid).unlink(missing_ok=True)
        shutil.rmtree(RENDERS_DIR / sid, ignore_errors=True)
    return {"deleted": sid, "blocks_removed": removed}


def summary(s: dict) -> dict:
    """A history row: title, dates, style, how many versions, the latest."""
    from src.daw_integration.generic.styles import STYLES
    from urllib.parse import quote
    done = [v for v in s["versions"] if v.get("status") == "done"]
    latest = done[-1] if done else (s["versions"][-1] if s["versions"] else None)
    genre = ((latest or {}).get("plan") or {}).get("genre")
    audio = None
    if latest and latest.get("status") == "done":
        b = latest.get("block")
        if _block_ok(b) and (block_store._preview_path(b).exists() or block_store._wav_path(b).exists()):
            audio = f"/api/blocks/{quote(block_store._safe_name(b))}/audio"
        elif not latest.get("audio"):
            audio = ((latest.get("result") or {}).get("urls") or {}).get("audio")
    return {
        "id": s["id"], "title": s.get("title") or "Untitled song",
        "created": s.get("created"), "updated": s.get("updated"),
        "genre": genre, "style": STYLES[genre].name if genre in STYLES else genre,
        "version_count": len(s["versions"]),
        "latest": {"n": latest["n"], "status": latest.get("status"), "block": latest.get("block"),
                   "audio_url": audio} if latest else None,
    }


def list_sessions(limit: int = 0) -> list[dict]:
    """Every song with a thread, most recently worked on first."""
    if not SESSIONS_DIR.exists():
        return []
    out = []
    for p in SESSIONS_DIR.glob("*.json"):
        try:
            with open(p, "r") as f:
                s = json.load(f)
        except (OSError, ValueError):
            continue
        if s.get("msgs") or s.get("versions"):
            out.append(summary(s))
    out.sort(key=lambda r: r.get("updated") or "", reverse=True)
    return out[:limit] if limit else out


# ---------------------------------------------------------------------------
# Library links
# ---------------------------------------------------------------------------
def save_to_library(sid: str, n: int) -> dict:
    """Put a version in the library (its auto-saved block, linked back to
    this session). Returns ``{version, entry}``."""
    with _lock(sid):
        s = _read(sid)
        v = _version(s, n)
        _finalize_locked(s, v)
        if not _block_ok(v.get("block")):
            raise SessionError("This version has no audio yet")
        entry = library_store.add_entry(v["block"], title=version_block_name(s.get("title"), n))
        v["savedAs"] = v["block"]
        meta = block_store.read_meta(v["block"]) or {}
        if not meta.get("session"):
            block_store.set_session(v["block"], {"id": sid, "version": n})
        _write(s)
        return {"version": v, "entry": entry}


def timeline_status(meta: Optional[dict]) -> dict:
    """Whether a block opens in the Timeline (``ok``), and if not, why."""
    from src.composition.song_plan import PlanError
    from src.daw_integration.generic.styles import STYLES
    if not meta:
        return {"ok": False, "reason": "No such block"}
    link = meta.get("session") or {}
    if exists(link.get("id")):
        return {"ok": True, "session_id": link["id"]}
    spec = meta.get("spec")
    try:
        if not isinstance(spec, dict) or not spec.get("genre"):
            raise PlanError("No generation settings were saved with it")
        if spec.get("inferred"):
            raise PlanError("Its settings were guessed, not saved")
        if spec["genre"] not in STYLES:
            raise PlanError(f"Its style ({spec['genre']}) is no longer available")
    except PlanError as exc:
        return {"ok": False, "reason": str(exc)}
    return {"ok": True}


def from_block(name: str) -> dict:
    """Open a block in the Timeline: its session when it came from one, else a
    new session whose v1 is the block itself (its audio and seed), planned
    from its spec so timeline edits regenerate it. Returns ``{session,
    version}``."""
    from src.composition.song_plan import PlanError, plan_chips, plan_from_spec
    meta = block_store.read_meta(name)
    if not meta:
        raise SessionNotFound(f"No block {name!r}")
    name = meta.get("name") or block_store._safe_name(name)
    link = meta.get("session") or {}
    if exists(link.get("id")):
        s = get(link["id"])
        n = link.get("version") if any(v["n"] == link.get("version") for v in s["versions"]) else None
        return {"session": s, "version": n}
    try:
        plan = plan_from_spec(meta.get("spec"))
    except PlanError as exc:
        raise SessionError(f"Can't open “{name}” in the timeline: {exc}") from None
    try:
        title = library_store.get_entry(name).get("title") or name
    except FileNotFoundError:
        title = name
    title = title.replace("_", " ").strip()
    spec = meta["spec"]
    ts = spec.get("time_signature") or meta.get("time_signature") or [4, 4]
    result = {
        "seed": spec.get("seed"), "genre": spec["genre"], "bars": meta.get("bars"),
        "key": spec.get("key"), "scale": spec.get("scale") or "major",
        "tempo": spec.get("tempo") or meta.get("tempo"), "time_signature": list(ts),
        "summary": "", "saved_block": name, "section_blocks": [],
        "sections": [{"label": x.get("label") or x["role"].capitalize(), "role": x["role"],
                      "bars": int(x["end_bar"]) - int(x["start_bar"]) + 1}
                     for x in spec.get("sections") or [] if x.get("role")],
        **({"tune": spec["tune"]} if spec.get("tune") else {}),
    }
    v1 = {"n": 1, "plan": plan, "jobId": None, "status": "done", "progress": 1, "message": "",
          "result": result, "block": name, "seed": plan.get("seed"), "origin": "library"}
    msg = {"id": _msg_id(), "role": "app", "kind": "opened", "text": f"Opened “{title}” from your library",
           "chips": plan_chips(plan), "version": 1}
    s = create(title=title, msgs=[msg], versions=[v1])
    block_store.set_session(name, {"id": s["id"], "version": 1})
    return {"session": s, "version": 1}


# ---------------------------------------------------------------------------
# Continuing a thread on the server (the song tools)
# ---------------------------------------------------------------------------
def revise(sid: str, feedback: str, wait: bool = True, timeout_s: float = 900) -> dict:
    """Plain-English feedback on a session's latest finished version → the
    revised plan (same seed) → the next version in the same thread."""
    from . import describe, routes
    from .schemas import GenerateRequest
    feedback = (feedback or "").strip()
    if not feedback:
        raise SessionError("Say what should change")
    s = get(sid)
    base = next((v for v in reversed(s["versions"]) if v.get("status") == "done"), None)
    if base is None:
        raise SessionError("This song has no finished version to change yet")
    plan = dict(base.get("plan") or {})
    seed = base.get("seed") or plan.get("seed")
    if seed:
        plan["seed"] = seed
    r = describe.revise(plan, feedback)
    changes = r.get("changes") or []
    user = {"id": _msg_id(), "role": "user", "text": feedback}
    reply = {"id": _msg_id(), "role": "app", "kind": "revise", "text": r.get("summary"),
             "changes": changes, "notes": r.get("notes") or [], "interpreter": r.get("interpreter")}
    out = {"session_id": sid, "summary": r.get("summary"), "changes": changes,
           "notes": r.get("notes") or [], "interpreter": r.get("interpreter")}
    if not changes:
        append(sid, msgs=[user, reply])
        return {**out, "version": None}
    new_plan = {**r["plan"], **({"seed": seed} if seed else {})}
    job_id = routes.generate(GenerateRequest(**plan_request(new_plan)))["job_id"]
    with _lock(sid):
        s = _read(sid)
        n = max((v["n"] for v in s["versions"]), default=0) + 1
        reply["version"] = n
        version = {"n": n, "plan": new_plan, "from": base["n"], "jobId": job_id, "status": "running",
                   "progress": 0, "message": "Starting…"}
        append(sid, msgs=[user, reply], versions=[version])
    if wait:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            job = registry.get(job_id)
            if job is None or job.status in _TERMINAL:
                break
            time.sleep(0.5)
        finalize(sid, n)
    return {**out, "version": _version(get(sid), n)}
