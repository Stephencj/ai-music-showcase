"""Optional shared-secret authentication for the AI Music Studio server.

When ``AI_MUSIC_AUTH_TOKEN`` is set:

  - The Gradio UI gates behind HTTP Basic Auth using the token as password
    (any non-empty username). iOS ``WKWebView`` supplies these via
    ``URLAuthenticationChallenge`` handlers.
  - The ``/healthz`` route requires either Basic Auth or an
    ``X-AI-Music-Token`` header. The iOS health-check uses the header.

When the env var is empty (the default for local-only dev), no auth is
applied — preserving today's frictionless localhost workflow.
"""

from __future__ import annotations

import base64
import os
from typing import Callable, Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response


TOKEN_HEADER = "X-AI-Music-Token"


def get_token() -> str:
    """Read the shared-secret token from the environment. Empty string
    means auth is disabled."""
    return os.environ.get("AI_MUSIC_AUTH_TOKEN", "").strip()


def gradio_auth_callable(token: str) -> Optional[Callable[[str, str], bool]]:
    """Return a callable suitable for Gradio's ``auth=`` kwarg, or None
    when the token is empty (Gradio interprets ``None`` as "no auth")."""
    if not token:
        return None

    def _check(username: str, password: str) -> bool:
        # We don't bind to a specific username — the iOS app can supply
        # anything (e.g. "ios" or "user"). The token is the secret.
        return password == token

    return _check


def _decode_basic_auth(header_value: str) -> Optional[tuple[str, str]]:
    if not header_value or not header_value.lower().startswith("basic "):
        return None
    try:
        encoded = header_value.split(" ", 1)[1]
        decoded = base64.b64decode(encoded).decode("utf-8")
        if ":" not in decoded:
            return None
        user, password = decoded.split(":", 1)
        return user, password
    except Exception:
        return None


class TokenMiddleware(BaseHTTPMiddleware):
    """Gates configured paths with either ``X-AI-Music-Token`` header or
    HTTP Basic Auth (password = token).

    Only applies when a non-empty token is set. Only protects the paths
    in ``protected_paths`` (default: ``["/healthz"]``) — the Gradio UI
    paths are gated by Gradio's own ``auth=`` callable instead, so the
    WebSocket / queue / static-asset paths keep working.
    """

    def __init__(self, app, *, token: str,
                 protected_paths: Optional[list[str]] = None) -> None:
        super().__init__(app)
        self.token = token
        self.protected_paths = protected_paths or ["/healthz"]

    async def dispatch(self, request: Request, call_next) -> Response:
        if not self.token:
            return await call_next(request)
        if not any(request.url.path.startswith(p) for p in self.protected_paths):
            return await call_next(request)

        header = request.headers.get(TOKEN_HEADER, "")
        if header and header == self.token:
            return await call_next(request)

        basic = _decode_basic_auth(request.headers.get("Authorization", ""))
        if basic is not None and basic[1] == self.token:
            return await call_next(request)

        return JSONResponse(
            {"detail": "Missing or invalid auth token."},
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="ai-music"'},
        )
