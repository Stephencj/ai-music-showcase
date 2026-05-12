"""Regression tests for the env-driven launch wrapper + auth middleware.

Covers:

- ``get_token`` + ``gradio_auth_callable`` — empty env → ``None`` (no
  auth); set env → callable that accepts any username with the matching
  password.
- ``TokenMiddleware`` — protected paths return 401 without a token
  header / Basic Auth; pass with either; non-protected paths are never
  gated.
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

def _build_app_with_middleware(token: str) -> FastAPI:
    api = FastAPI()
    health_mod.register_healthz(api)

    @api.get("/public")
    def _public():
        return {"ok": True}

    if token:
        api.add_middleware(auth_mod.TokenMiddleware, token=token)
    return api


class TokenMiddlewareTests(unittest.TestCase):

    def test_no_token_no_gating(self):
        client = TestClient(_build_app_with_middleware(""))
        self.assertEqual(client.get("/healthz").status_code, 200)
        self.assertEqual(client.get("/public").status_code, 200)

    def test_healthz_requires_token_header_or_basic_auth(self):
        client = TestClient(_build_app_with_middleware("hunter2"))
        # Naked request → 401
        r = client.get("/healthz")
        self.assertEqual(r.status_code, 401)
        # Token header → 200
        r = client.get("/healthz", headers={"X-AI-Music-Token": "hunter2"})
        self.assertEqual(r.status_code, 200)
        # Basic Auth with token as password → 200
        r = client.get("/healthz", auth=("ios", "hunter2"))
        self.assertEqual(r.status_code, 200)
        # Basic Auth with wrong password → 401
        r = client.get("/healthz", auth=("ios", "wrong"))
        self.assertEqual(r.status_code, 401)

    def test_non_protected_paths_skip_middleware(self):
        client = TestClient(_build_app_with_middleware("hunter2"))
        # /public isn't in protected_paths, so the middleware lets it pass.
        self.assertEqual(client.get("/public").status_code, 200)


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
