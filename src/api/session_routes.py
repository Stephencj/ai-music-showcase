"""Create sessions over REST (``/api/sessions``): the song threads behind
Create's Session and Timeline, kept on the server (src/api/sessions.py)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from . import sessions
from .schemas import SessionBody, SessionFromBlockRequest, SessionRenameRequest, SessionReviseRequest

router = APIRouter(prefix="/sessions")


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except sessions.SessionNotFound as exc:
        raise HTTPException(404, str(exc))
    except sessions.SessionError as exc:
        raise HTTPException(400, str(exc))


@router.get("")
def list_sessions(limit: int = 0) -> dict:
    """Past songs, most recent first: title, dates, style, version count and
    the latest version's audio."""
    return {"sessions": sessions.list_sessions(limit)}


@router.post("")
def create_session(req: SessionBody) -> dict:
    """A new session; with ``msgs`` / ``versions`` it brings a thread over
    (the browser's old local copy)."""
    return _call(sessions.create, req.title or "", req.interpreter, req.msgs, req.versions)


@router.post("/from-block")
def session_from_block(req: SessionFromBlockRequest) -> dict:
    """Open a block in the Timeline: its own session, or a new one whose v1 is
    the block (``{session, version}``)."""
    return _call(sessions.from_block, req.block)


@router.get("/{sid}")
def get_session(sid: str) -> dict:
    return _call(sessions.get, sid)


@router.put("/{sid}")
def update_session(sid: str, req: SessionBody) -> dict:
    """Merge the client's copy: messages by id, versions by number (the job's
    outcome and the block / library links stay the server's)."""
    return _call(sessions.update, sid, req.title, req.interpreter, req.msgs, req.versions)


@router.post("/{sid}/append")
def append_to_session(sid: str, req: SessionBody) -> dict:
    return _call(sessions.append, sid, req.msgs, req.versions)


@router.post("/{sid}/rename")
def rename_session(sid: str, req: SessionRenameRequest) -> dict:
    return _call(sessions.rename, sid, req.title)


@router.delete("/{sid}")
def delete_session(sid: str) -> dict:
    """Delete a song's thread; its auto-saved versions leave Practice unless
    they're in the library."""
    return _call(sessions.delete, sid)


@router.post("/{sid}/versions/{n}/finalize")
def finalize_version(sid: str, n: int) -> dict:
    """A finished version's result, auto-saved block and cached render."""
    return {"version": _call(sessions.finalize, sid, n)}


@router.post("/{sid}/versions/{n}/render")
def render_version(sid: str, n: int) -> dict:
    """Render a version again from its plan + seed when its audio is gone."""
    return {"version": _call(sessions.render, sid, n)}


@router.post("/{sid}/versions/{n}/library")
def save_version_to_library(sid: str, n: int) -> dict:
    """Save a version to the library (linked to this session)."""
    return _call(sessions.save_to_library, sid, n)


@router.post("/{sid}/revise")
def revise_session(sid: str, req: SessionReviseRequest) -> dict:
    """Plain-English feedback → the next version in this thread (same seed)."""
    return _call(sessions.revise, sid, req.feedback, req.wait)
