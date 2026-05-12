"""Server control endpoints for remote restart from the iOS app.

Today there's one route — ``POST /admin/restart`` — but the module is
the natural home for anything else the user might trigger remotely
(stop, version-bump, log-tail, etc.).

Restart works by scheduling a ``SIGTERM`` to our own pid a quarter
second after the HTTP response is queued. Uvicorn catches SIGTERM and
runs a graceful shutdown; the macOS LaunchAgent (``KeepAlive=true``)
then respawns the process within ~1s — so the iPhone reload that
follows finds a healthy ``/healthz`` again.

Auth: always required, regardless of client IP. Restart is dangerous
enough that we don't want the LAN bypass that the rest of the API
enjoys. When ``AI_MUSIC_AUTH_TOKEN`` is unset we return 403 with a
hint explaining the configuration step.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .auth import TOKEN_HEADER, _decode_basic_auth


logger = logging.getLogger("ai_music_studio.admin")


# Delay between scheduling the response and firing SIGTERM. The
# response needs a moment to flush back to the client; 250ms is a
# comfortable margin that's also short enough to feel snappy.
_RESTART_DELAY_S = 0.25


def _check_auth(request: Request, token: str) -> bool:
    header = request.headers.get(TOKEN_HEADER, "")
    if header and header == token:
        return True
    basic = _decode_basic_auth(request.headers.get("Authorization", ""))
    return basic is not None and basic[1] == token


def register_admin(api: FastAPI, *, token: str) -> None:
    """Mount the admin routes on the given FastAPI app.

    Pass in the resolved auth token (from ``auth.get_token()``) at
    launch time. When ``token`` is empty, restart still gets a route —
    but it returns 403 explaining why. This keeps the iOS error UI
    deterministic regardless of server-side config.
    """

    @api.post("/admin/restart")
    async def _restart(request: Request) -> JSONResponse:
        if not token:
            return JSONResponse(
                {
                    "detail": (
                        "Restart requires AI_MUSIC_AUTH_TOKEN to be set "
                        "on the server."
                    ),
                },
                status_code=403,
            )
        if not _check_auth(request, token):
            return JSONResponse(
                {"detail": "Missing or invalid auth token."},
                status_code=401,
                headers={"WWW-Authenticate": 'Basic realm="ai-music"'},
            )

        pid = os.getpid()
        loop = asyncio.get_event_loop()
        loop.call_later(_RESTART_DELAY_S, _send_sigterm, pid)
        logger.warning(
            "admin restart requested by %s — sending SIGTERM to pid %d in %.2fs",
            request.client.host if request.client else "<unknown>",
            pid,
            _RESTART_DELAY_S,
        )
        return JSONResponse(
            {"status": "restarting", "pid": pid, "delay_s": _RESTART_DELAY_S},
            status_code=202,
        )


def _send_sigterm(pid: int) -> None:
    """Helper extracted for test stubbing."""
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        # Already gone; nothing to do.
        pass
