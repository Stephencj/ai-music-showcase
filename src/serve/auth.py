"""Optional shared-secret authentication for the AI Music Studio server.

When ``AI_MUSIC_AUTH_TOKEN`` is set:

  - Requests from trusted IP ranges (LAN / loopback by default) skip
    auth entirely. The user's home Wi-Fi is treated as trusted.
  - Requests from any other IP range (Tailscale CGNAT 100.64.0.0/10 in
    particular, or the public Internet via gradio.live) require either
    an ``X-AI-Music-Token`` header or HTTP Basic Auth where the
    password equals the token.
  - The same rule applies to WebSocket upgrades — Gradio's queue runs
    over WebSocket, so HTTP-only middleware isn't enough.

When the env var is empty (the default for local-only dev), no auth is
applied — preserving today's frictionless localhost workflow.
"""

from __future__ import annotations

import base64
import ipaddress
import logging
import os
from typing import Callable, Optional


logger = logging.getLogger("ai_music_studio.auth")


TOKEN_HEADER = "X-AI-Music-Token"

DEFAULT_TRUSTED_CIDRS: tuple[str, ...] = (
    "127.0.0.0/8",
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
)


def get_token() -> str:
    """Read the shared-secret token from the environment. Empty string
    means auth is disabled."""
    return os.environ.get("AI_MUSIC_AUTH_TOKEN", "").strip()


def get_trusted_cidrs() -> list[ipaddress._BaseNetwork]:
    """Parse ``AI_MUSIC_TRUSTED_CIDRS`` (comma-separated) into network
    objects. Falls back to the documented default LAN ranges. Malformed
    entries are logged and skipped — the app keeps booting even if the
    user typos a CIDR."""
    raw = os.environ.get("AI_MUSIC_TRUSTED_CIDRS", "").strip()
    items = (
        [s.strip() for s in raw.split(",") if s.strip()]
        if raw
        else list(DEFAULT_TRUSTED_CIDRS)
    )
    out: list[ipaddress._BaseNetwork] = []
    for s in items:
        try:
            out.append(ipaddress.ip_network(s, strict=False))
        except ValueError:
            logger.warning(
                "ignoring bad CIDR in AI_MUSIC_TRUSTED_CIDRS: %r", s,
            )
    return out


def gradio_auth_callable(token: str) -> Optional[Callable[[str, str], bool]]:
    """Return a callable suitable for Gradio's ``auth=`` kwarg, or None
    when the token is empty. Used by the ``share=True`` fallback path
    in the launcher — Gradio's share tunnel can't be wrapped in our
    middleware, so it gets its own Basic Auth callback. The mounted-app
    path uses :class:`IPAwareAuthMiddleware` instead."""
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


def _client_ip(scope: dict) -> Optional[ipaddress._BaseAddress]:
    """Pull the client's IP from an ASGI scope. ``scope["client"]`` is a
    ``(host, port)`` tuple or ``None`` (e.g. Unix-socket peers)."""
    client = scope.get("client")
    if not client:
        return None
    try:
        return ipaddress.ip_address(client[0])
    except (ValueError, TypeError):
        return None


def _is_trusted(
    ip: Optional[ipaddress._BaseAddress],
    networks: list[ipaddress._BaseNetwork],
) -> bool:
    if ip is None:
        return False
    return any(ip in n for n in networks)


def _header_value(scope: dict, name: bytes) -> str:
    """Look up a header by lowercase byte name in an ASGI scope."""
    target = name.lower()
    for k, v in scope.get("headers", []):
        if k.lower() == target:
            return v.decode("latin-1", "replace")
    return ""


_HTTP_401_BODY = b'{"detail":"Missing or invalid auth token."}'


class IPAwareAuthMiddleware:
    """Raw ASGI middleware that gates HTTP and WebSocket traffic.

    Pass-through cases (no auth check at all):
        - The configured token is empty.
        - The ASGI scope is ``lifespan`` (uvicorn startup/shutdown
          machinery; gating it would hang the server).
        - The scope type is neither ``http`` nor ``websocket``.
        - The client IP belongs to ``trusted_cidrs`` — LAN / loopback
          by default, which keeps the home Wi-Fi experience
          frictionless.

    Otherwise, the request is allowed through only if it bears an
    ``X-AI-Music-Token`` header equal to the token, or an
    ``Authorization: Basic <base64>`` whose password matches.

    HTTP rejection: JSON 401 with ``WWW-Authenticate: Basic``.
    WebSocket rejection: prefer the modern ``websocket.http.response``
    ASGI extension to send a real 401, fall back to ``websocket.close``
    with code ``4401`` (private-use range — distinguishable from the
    generic 1008 policy violation in logs).
    """

    def __init__(
        self,
        app,
        *,
        token: str,
        trusted_cidrs: Optional[list[ipaddress._BaseNetwork]] = None,
    ) -> None:
        self.app = app
        self.token = token
        self.trusted = (
            trusted_cidrs if trusted_cidrs is not None else get_trusted_cidrs()
        )

    async def __call__(self, scope, receive, send) -> None:
        # Lifecycle and non-network scopes pass through unconditionally.
        if not self.token or scope.get("type") == "lifespan":
            await self.app(scope, receive, send)
            return
        if scope.get("type") not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        if _is_trusted(_client_ip(scope), self.trusted):
            await self.app(scope, receive, send)
            return

        if self._token_ok(scope):
            await self.app(scope, receive, send)
            return

        if scope["type"] == "http":
            await self._send_http_401(send)
        else:
            await self._reject_websocket(scope, send)

    def _token_ok(self, scope) -> bool:
        if _header_value(scope, b"x-ai-music-token") == self.token:
            return True
        basic = _decode_basic_auth(_header_value(scope, b"authorization"))
        return basic is not None and basic[1] == self.token

    async def _send_http_401(self, send) -> None:
        await send({
            "type": "http.response.start",
            "status": 401,
            "headers": [
                (b"content-type", b"application/json"),
                (b"www-authenticate", b'Basic realm="ai-music"'),
            ],
        })
        await send({
            "type": "http.response.body",
            "body": _HTTP_401_BODY,
        })

    async def _reject_websocket(self, scope, send) -> None:
        extensions = scope.get("extensions") or {}
        if "websocket.http.response" in extensions:
            await send({
                "type": "websocket.http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"www-authenticate", b'Basic realm="ai-music"'),
                ],
            })
            await send({
                "type": "websocket.http.response.body",
                "body": _HTTP_401_BODY,
            })
        else:
            await send({"type": "websocket.close", "code": 4401})
