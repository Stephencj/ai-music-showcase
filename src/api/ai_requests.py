"""File-based queue for AI generation requests answered by a Claude Code
watch-loop (no API key required).

Flow: the app enqueues a request (e.g. "draft lyrics for this block, fitting
these phrase syllable counts"); an external Claude Code session polls
``GET /ai/requests?status=pending``, composes the answer, and POSTs it back
to ``/ai/requests/{id}/answer``. The app polls ``/ai/requests/{id}`` until it
flips to ``answered``.

Requests live as one JSON file each under ``data/ai_requests/`` so the app
and the (separate-process) Claude Code session see the same state over HTTP.
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Optional

AI_REQ_DIR = Path("data/ai_requests")
_MAX_AGE_SEC = 6 * 3600   # prune answered/stale requests after 6h


def _path(rid: str) -> Path:
    return AI_REQ_DIR / f"{rid}.json"


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
    _path(rid).write_text(json.dumps(rec, indent=2))
    return rec


def get(rid: str) -> Optional[dict]:
    p = _path(rid)
    return _read(p) if p.exists() else None


def list_requests(status: Optional[str] = None) -> list[dict]:
    """All requests (optionally filtered by status), oldest first."""
    if not AI_REQ_DIR.exists():
        return []
    out: list[dict] = []
    for f in AI_REQ_DIR.glob("*.json"):
        rec = _read(f)
        if rec and (status is None or rec.get("status") == status):
            out.append(rec)
    out.sort(key=lambda r: r.get("created", 0))
    return out


def answer(rid: str, content, error: Optional[str] = None) -> Optional[dict]:
    """Record an answer (or error) for a request. Returns the updated record."""
    rec = get(rid)
    if rec is None:
        return None
    rec["status"] = "error" if error else "answered"
    rec["answer"] = content
    rec["error"] = error
    rec["answered"] = time.time()
    _path(rid).write_text(json.dumps(rec, indent=2))
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
