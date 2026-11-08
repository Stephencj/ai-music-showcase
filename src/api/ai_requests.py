"""File-based queue for AI generation requests answered by a Claude Code
watch-loop (no API key required).

Flow: the app enqueues a request (e.g. "draft lyrics for this block, fitting
these phrase syllable counts"); an external Claude Code session polls
``GET /ai/requests?status=pending``, composes the answer, and POSTs it back
to ``/ai/requests/{id}/answer``. The app polls ``/ai/requests/{id}`` until it
flips to ``answered``.

Requests live as one JSON file each under ``data/ai_requests/`` so the app
and the (separate-process) Claude Code session see the same state over HTTP.

Liveness: every poll for pending work records a heartbeat (``beat``), and an
answerer ``claim``s a request before working on it, so a caller that can fall
back elsewhere (song plans → local model) knows quickly when nobody is
listening instead of waiting out a long timeout.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Optional

AI_REQ_DIR = Path("data/ai_requests")
_MAX_AGE_SEC = 6 * 3600   # prune answered/stale requests after 6h
_BEAT_FILE = "answerers.beat"   # not *.json, so list_requests never sees it


def _path(rid: str) -> Path:
    return AI_REQ_DIR / f"{rid}.json"


def _write(p: Path, rec) -> None:
    """Atomic write: the app and the answerer poll these files while they
    change, and a half-written file would read as missing."""
    tmp = p.with_name(f".{p.name}.{uuid.uuid4().hex[:6]}.tmp")
    tmp.write_text(json.dumps(rec, indent=2))
    os.replace(tmp, p)


def _read(p: Path) -> Optional[dict]:
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return None


def enqueue(kind: str, block: str, params: dict) -> dict:
    """Create a pending request. ``kind`` is e.g. ``"lyrics"``; ``params``
    carries everything the answerer needs (phrase syllable counts, theme…)."""
    AI_REQ_DIR.mkdir(parents=True, exist_ok=True)
    _prune()
    rid = uuid.uuid4().hex[:12]
    rec = {
        "id": rid, "kind": kind, "block": block, "params": params,
        "status": "pending", "answer": None, "error": None,
        "created": time.time(), "answered": None,
    }
    _write(_path(rid), rec)
    return rec


def get(rid: str) -> Optional[dict]:
    p = _path(rid)
    return _read(p) if p.exists() else None


def list_requests(status: Optional[str] = None,
                  kinds: Optional[set[str]] = None) -> list[dict]:
    """All requests (optionally filtered by status and kind), oldest first."""
    if not AI_REQ_DIR.exists():
        return []
    out: list[dict] = []
    for f in AI_REQ_DIR.glob("*.json"):
        rec = _read(f)
        if rec and (status is None or rec.get("status") == status) \
                and (not kinds or rec.get("kind") in kinds):
            out.append(rec)
    out.sort(key=lambda r: r.get("created", 0))
    return out


def claim(rid: str, by: str = "") -> Optional[dict]:
    """Mark a pending request as being worked on (``claimed``). Returns the
    record, or None when it's unknown or no longer pending (someone else got
    it, or the caller gave up on it)."""
    rec = get(rid)
    if rec is None or rec.get("status") != "pending":
        return None
    rec["status"] = "claimed"
    rec["claimed_by"] = by
    rec["claimed"] = time.time()
    _write(_path(rid), rec)
    return rec


def withdraw(rid: str) -> bool:
    """The caller stopped waiting: drop a still-pending request so a late
    answerer doesn't do work nobody will read. Returns True if withdrawn."""
    rec = get(rid)
    if rec is None or rec.get("status") != "pending":
        return False
    try:
        _path(rid).unlink()
    except OSError:
        return False
    return True


def beat(who: str, kinds: Optional[set[str]] = None) -> None:
    """Record that an answerer just polled (for ``kinds``; None = any kind)."""
    AI_REQ_DIR.mkdir(parents=True, exist_ok=True)
    beats = _beats()
    beats[who or "anon"] = {"at": time.time(), "kinds": sorted(kinds) if kinds else None}
    _write(AI_REQ_DIR / _BEAT_FILE, beats)


def answerer_alive(kind: str, max_age: float = 30.0) -> bool:
    """Has an answerer that handles ``kind`` polled within ``max_age`` s?"""
    now = time.time()
    return any(now - float(b.get("at") or 0) <= max_age
               and (not b.get("kinds") or kind in b["kinds"])
               for b in _beats().values())


def _beats() -> dict:
    rec = _read(AI_REQ_DIR / _BEAT_FILE)
    return rec if isinstance(rec, dict) else {}


def answer(rid: str, content, error: Optional[str] = None) -> Optional[dict]:
    """Record an answer (or error) for a request. Returns the updated record."""
    rec = get(rid)
    if rec is None:
        return None
    rec["status"] = "error" if error else "answered"
    rec["answer"] = content
    rec["error"] = error
    rec["answered"] = time.time()
    _write(_path(rid), rec)
    return rec


def _prune() -> None:
    """Drop requests older than ``_MAX_AGE_SEC`` so the queue stays small."""
    if not AI_REQ_DIR.exists():
        return
    now = time.time()
    for f in AI_REQ_DIR.glob("*.json"):
        rec = _read(f)
        if not rec or now - rec.get("created", now) > _MAX_AGE_SEC:
            try:
                f.unlink()
            except OSError:
                pass
