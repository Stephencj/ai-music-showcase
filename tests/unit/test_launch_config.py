"""Regression tests for the env-driven launch wrapper + auth middleware.

Covers:

- ``get_token`` + ``gradio_auth_callable`` — empty env → ``None`` (no
  auth); set env → callable that accepts any username with the matching
  password.
- ``IPAwareAuthMiddleware`` — trusted client IPs bypass auth; untrusted
  IPs (Tailscale CGNAT range) need ``X-AI-Music-Token`` header or Basic
  Auth. WebSocket scopes use the same logic, rejected with close 4401.
- ``get_trusted_cidrs`` — defaults match the documented LAN ranges,
  env override parses, malformed CIDRs are ignored, ``100.64.0.0/10``
  is NOT in the default set (regression guard for Tailscale auth).
- ``/healthz`` route presence and shape.
- ``launcher._resolve_host_port`` — defaults + env overrides.
- ``MdnsAdvertiser`` is import-safe even when zeroconf isn't installed.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.serve import auth as auth_mod
from src.serve import discovery as discovery_mod
from src.serve import health as health_mod
from src.serve import launcher as launcher_mod


# ---------------------------------------------------------------------------
# auth.get_token + gradio_auth_callable
# ---------------------------------------------------------------------------

class GetTokenTests(unittest.TestCase):

    def test_empty_env_returns_empty_string(self):
        with mock.patch.dict("os.environ", {"AI_MUSIC_AUTH_TOKEN": ""}, clear=False):
            self.assertEqual(auth_mod.get_token(), "")

    def test_strips_whitespace(self):
        with mock.patch.dict("os.environ", {"AI_MUSIC_AUTH_TOKEN": "  hunter2  "}):
            self.assertEqual(auth_mod.get_token(), "hunter2")

    def test_unset_returns_empty(self):
        env = {k: v for k, v in __import__("os").environ.items()
               if k != "AI_MUSIC_AUTH_TOKEN"}
        with mock.patch.dict("os.environ", env, clear=True):
            self.assertEqual(auth_mod.get_token(), "")


class GradioAuthCallableTests(unittest.TestCase):

    def test_empty_token_returns_none(self):
        self.assertIsNone(auth_mod.gradio_auth_callable(""))

    def test_callable_accepts_matching_password(self):
        check = auth_mod.gradio_auth_callable("hunter2")
        assert check is not None
        self.assertTrue(check("anyone", "hunter2"))
        self.assertTrue(check("", "hunter2"))

    def test_callable_rejects_wrong_password(self):
        check = auth_mod.gradio_auth_callable("hunter2")
        assert check is not None
        self.assertFalse(check("user", "wrong"))
        self.assertFalse(check("user", ""))


# ---------------------------------------------------------------------------
# TokenMiddleware
# ---------------------------------------------------------------------------

def _build_app(token: str) -> FastAPI:
    """Test fixture FastAPI app with /healthz, /public, /assets/*, and a
    /ws echo socket — covers the path shapes the middleware needs to
    gate (HTTP, static-asset paths, WebSocket)."""
    api = FastAPI()
    health_mod.register_healthz(api)

    @api.get("/public")
    def _public():
        return {"ok": True}

    @api.get("/assets/{path:path}")
    def _assets(path: str):
        return {"asset": path}

    @api.websocket("/ws")
    async def _ws(websocket):
        await websocket.accept()
        msg = await websocket.receive_text()
        await websocket.send_text(f"echo:{msg}")
        await websocket.close()

    if token:
        api.add_middleware(auth_mod.IPAwareAuthMiddleware, token=token)
    return api


class IPAwareAuthHTTPTests(unittest.TestCase):

    # Starlette 1.0's TestClient defaults the client tuple to the
    # literal string ``"testclient"`` (not a parseable IP), which our
    # middleware can't recognise as trusted. Tests that need a trusted
    # source explicitly pass `client=("127.0.0.1", 0)`.

    def test_no_token_no_gating(self):
        client = TestClient(_build_app(""))
        self.assertEqual(client.get("/healthz").status_code, 200)
        self.assertEqual(client.get("/public").status_code, 200)
        self.assertEqual(client.get("/assets/foo.js").status_code, 200)

    def test_trusted_loopback_skips_auth(self):
        client = TestClient(_build_app("hunter2"), client=("127.0.0.1", 0))
        self.assertEqual(client.get("/healthz").status_code, 200)
        self.assertEqual(client.get("/public").status_code, 200)
        self.assertEqual(client.get("/assets/foo.js").status_code, 200)

    def test_unparseable_client_treated_as_untrusted(self):
        """The default TestClient ``client="testclient"`` shape — and any
        real Unix-socket peer — has no parseable IP, so the middleware
        treats it as untrusted. Auth is required."""
        client = TestClient(_build_app("hunter2"))  # default "testclient"
        self.assertEqual(client.get("/healthz").status_code, 401)
        r = client.get("/healthz", headers={"X-AI-Music-Token": "hunter2"})
        self.assertEqual(r.status_code, 200)

    def test_untrusted_ip_requires_token(self):
        """Tailscale CGNAT range source must auth."""
        client = TestClient(
            _build_app("hunter2"), client=("100.64.1.5", 0),
        )
        # Naked request → 401
        r = client.get("/healthz")
        self.assertEqual(r.status_code, 401)
        self.assertIn("Basic", r.headers.get("www-authenticate", ""))
        # Header pass → 200
        r = client.get("/healthz", headers={"X-AI-Music-Token": "hunter2"})
        self.assertEqual(r.status_code, 200)
        # Basic Auth pass → 200
        r = client.get("/healthz", auth=("ios", "hunter2"))
        self.assertEqual(r.status_code, 200)
        # Wrong password → 401
        r = client.get("/healthz", auth=("ios", "wrong"))
        self.assertEqual(r.status_code, 401)

    def test_untrusted_ip_gating_covers_all_paths(self):
        """Static assets + arbitrary routes are all gated when the
        client is outside the trusted ranges."""
        client = TestClient(
            _build_app("hunter2"), client=("100.64.1.5", 0),
        )
        for path in ["/healthz", "/public", "/assets/foo.js"]:
            with self.subTest(path=path):
                self.assertEqual(client.get(path).status_code, 401)
                r = client.get(
                    path, headers={"X-AI-Music-Token": "hunter2"},
                )
                self.assertEqual(r.status_code, 200)

    def test_env_override_can_revoke_loopback_trust(self):
        """Override the trusted set to only 10.0.0.0/8 → loopback
        clients (127.0.0.1) no longer skip auth."""
        with mock.patch.dict(
            "os.environ", {"AI_MUSIC_TRUSTED_CIDRS": "10.0.0.0/8"},
        ):
            client = TestClient(_build_app("hunter2"), client=("127.0.0.1", 0))
            r = client.get("/healthz")
            self.assertEqual(r.status_code, 401)
            r = client.get("/healthz", headers={"X-AI-Music-Token": "hunter2"})
            self.assertEqual(r.status_code, 200)

    def test_malformed_cidr_does_not_crash(self):
        """Bad CIDR entries are logged and skipped — the valid ones
        still apply."""
        with mock.patch.dict(
            "os.environ",
            {"AI_MUSIC_TRUSTED_CIDRS": "not-a-cidr,127.0.0.0/8,also-bad"},
        ):
            client = TestClient(_build_app("hunter2"), client=("127.0.0.1", 0))
            self.assertEqual(client.get("/healthz").status_code, 200)


class IPAwareAuthWebSocketTests(unittest.TestCase):
    """Drive the middleware's WS path directly with a synthetic ASGI
    scope. Starlette 1.0's ``TestClient.websocket_connect`` has a
    regression that surfaces every connection as ``WebSocketDisconnect``
    on ``__enter__`` — testing the middleware in isolation sidesteps
    the harness and proves the auth logic on its own."""

    def _ws_scope(self, client_ip: str, *, token_header: str = "") -> dict:
        headers = []
        if token_header:
            headers.append((b"x-ai-music-token", token_header.encode()))
        return {
            "type": "websocket",
            "client": (client_ip, 12345),
            "headers": headers,
            "path": "/ws",
            "extensions": {"websocket.http.response": {}},
        }

    async def _drive(self, scope: dict, token: str):
        captured: list[dict] = []

        async def inner(scope, receive, send):
            await send({"type": "websocket.accept"})

        async def send(msg):
            captured.append(msg)

        async def receive():
            return {"type": "websocket.connect"}

        mw = auth_mod.IPAwareAuthMiddleware(inner, token=token)
        await mw(scope, receive, send)
        return captured

    def _run(self, coro):
        import asyncio
        return asyncio.run(coro)

    def test_trusted_loopback_passes_through(self):
        out = self._run(self._drive(self._ws_scope("127.0.0.1"), "hunter2"))
        self.assertEqual(out, [{"type": "websocket.accept"}])

    def test_no_token_passes_through(self):
        out = self._run(self._drive(self._ws_scope("100.64.1.5"), ""))
        self.assertEqual(out, [{"type": "websocket.accept"}])

    def test_untrusted_no_token_rejects_with_extension(self):
        out = self._run(self._drive(self._ws_scope("100.64.1.5"), "hunter2"))
        # Used the modern websocket.http.response extension (a 401
        # rather than a close), so two send() messages — start + body.
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["type"], "websocket.http.response.start")
        self.assertEqual(out[0]["status"], 401)
        self.assertEqual(out[1]["type"], "websocket.http.response.body")

    def test_untrusted_no_token_no_extension_uses_close_code(self):
        scope = self._ws_scope("100.64.1.5")
        scope["extensions"] = {}  # simulate older ASGI versions
        out = self._run(self._drive(scope, "hunter2"))
        self.assertEqual(out, [{"type": "websocket.close", "code": 4401}])

    def test_untrusted_with_token_passes_through(self):
        out = self._run(self._drive(
            self._ws_scope("100.64.1.5", token_header="hunter2"),
            "hunter2",
        ))
        self.assertEqual(out, [{"type": "websocket.accept"}])

    def test_untrusted_with_basic_auth_passes_through(self):
        import base64
        encoded = base64.b64encode(b"ios:hunter2").decode()
        scope = self._ws_scope("100.64.1.5")
        scope["headers"].append(
            (b"authorization", f"Basic {encoded}".encode()),
        )
        out = self._run(self._drive(scope, "hunter2"))
        self.assertEqual(out, [{"type": "websocket.accept"}])


class TrustedCidrParsingTests(unittest.TestCase):

    def test_defaults_match_documented_lan_ranges(self):
        env = {k: v for k, v in __import__("os").environ.items()
               if k != "AI_MUSIC_TRUSTED_CIDRS"}
        with mock.patch.dict("os.environ", env, clear=True):
            cidrs = auth_mod.get_trusted_cidrs()
        strings = [str(c) for c in cidrs]
        self.assertEqual(strings, [
            "127.0.0.0/8",
            "10.0.0.0/8",
            "172.16.0.0/12",
            "192.168.0.0/16",
        ])

    def test_env_override_parsed(self):
        with mock.patch.dict(
            "os.environ", {"AI_MUSIC_TRUSTED_CIDRS": " 10.0.0.0/8 , 192.168.5.0/24 "},
        ):
            cidrs = auth_mod.get_trusted_cidrs()
        self.assertEqual(
            [str(c) for c in cidrs],
            ["10.0.0.0/8", "192.168.5.0/24"],
        )

    def test_tailscale_cgnat_not_in_defaults(self):
        """Regression guard: 100.64.0.0/10 must NOT be in the trusted
        defaults — Tailscale peers should always auth."""
        env = {k: v for k, v in __import__("os").environ.items()
               if k != "AI_MUSIC_TRUSTED_CIDRS"}
        with mock.patch.dict("os.environ", env, clear=True):
            cidrs = auth_mod.get_trusted_cidrs()
        import ipaddress
        tailscale = ipaddress.ip_address("100.64.1.5")
        self.assertFalse(
            any(tailscale in c for c in cidrs),
            "Tailscale range slipped into trusted CIDR defaults",
        )


# ---------------------------------------------------------------------------
# /healthz shape
# ---------------------------------------------------------------------------

class HealthzShapeTests(unittest.TestCase):

    def test_healthz_returns_expected_fields(self):
        api = FastAPI()
        health_mod.register_healthz(api)
        client = TestClient(api)
        body = client.get("/healthz").json()
        for key in ("status", "service", "version", "host"):
            self.assertIn(key, body)
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["service"], "ai-music-studio")

    def test_lan_ips_returns_a_list(self):
        ips = health_mod.lan_ips()
        self.assertIsInstance(ips, list)
        for ip in ips:
            self.assertFalse(ip.startswith("127."),
                             f"loopback IP leaked into LAN list: {ip}")


# ---------------------------------------------------------------------------
# launcher env resolution
# ---------------------------------------------------------------------------

class ResolveHostPortTests(unittest.TestCase):

    def test_defaults_when_env_unset(self):
        env = {k: v for k, v in __import__("os").environ.items()
               if k not in ("AI_MUSIC_HOST", "AI_MUSIC_PORT")}
        with mock.patch.dict("os.environ", env, clear=True):
            host, port = launcher_mod._resolve_host_port()
        self.assertEqual(host, "0.0.0.0")
        self.assertEqual(port, 7860)

    def test_env_overrides(self):
        with mock.patch.dict("os.environ",
                             {"AI_MUSIC_HOST": "127.0.0.1",
                              "AI_MUSIC_PORT": "8123"}):
            host, port = launcher_mod._resolve_host_port()
        self.assertEqual(host, "127.0.0.1")
        self.assertEqual(port, 8123)

    def test_invalid_port_falls_back_to_default(self):
        with mock.patch.dict("os.environ", {"AI_MUSIC_PORT": "not-a-number"}):
            _, port = launcher_mod._resolve_host_port()
        self.assertEqual(port, 7860)


class ShareEnabledTests(unittest.TestCase):

    def test_truthy_values(self):
        for val in ("1", "true", "TRUE", "yes", "Yes"):
            with mock.patch.dict("os.environ", {"AI_MUSIC_SHARE": val}):
                self.assertTrue(launcher_mod._share_enabled(), val)

    def test_falsy_values(self):
        for val in ("", "0", "false", "no", "off"):
            with mock.patch.dict("os.environ", {"AI_MUSIC_SHARE": val}):
                self.assertFalse(launcher_mod._share_enabled(), val)


# ---------------------------------------------------------------------------
# MdnsAdvertiser import safety
# ---------------------------------------------------------------------------

class MdnsAdvertiserSafetyTests(unittest.TestCase):

    def test_start_without_zeroconf_does_not_raise(self):
        """If zeroconf isn't installed, start() should log a warning
        and silently return — not crash the app launch."""
        advertiser = discovery_mod.MdnsAdvertiser()
        # Force the ImportError path by patching the import.
        real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __import__

        def fake_import(name, *args, **kwargs):
            if name == "zeroconf":
                raise ImportError("simulated missing zeroconf")
            return real_import(name, *args, **kwargs)

        with mock.patch("builtins.__import__", side_effect=fake_import):
            advertiser.start(port=7860)  # must not raise

        # close() must be idempotent + safe even when start failed
        advertiser.close()
        advertiser.close()

    def test_close_before_start_is_noop(self):
        advertiser = discovery_mod.MdnsAdvertiser()
        advertiser.close()  # must not raise


if __name__ == "__main__":
    unittest.main(verbosity=2)
