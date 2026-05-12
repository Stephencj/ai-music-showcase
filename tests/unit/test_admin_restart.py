"""Tests for the ``/admin/restart`` server-control endpoint.

The route's job is small but load-bearing: when the iOS Settings →
Restart button fires, the server must reply with 202, schedule a
SIGTERM, and let uvicorn drain in the brief window before the
LaunchAgent respawns it. Auth is mandatory — restart is too dangerous
to let LAN clients trigger without a token.
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

from src.serve import admin as admin_mod


def _app(token: str) -> FastAPI:
    api = FastAPI()
    admin_mod.register_admin(api, token=token)
    return api


class AdminRestartTests(unittest.TestCase):

    def test_no_token_set_returns_403(self):
        client = TestClient(_app(""))
        r = client.post("/admin/restart")
        self.assertEqual(r.status_code, 403)
        self.assertIn("AI_MUSIC_AUTH_TOKEN", r.json()["detail"])

    def test_missing_auth_returns_401(self):
        client = TestClient(_app("hunter2"))
        r = client.post("/admin/restart")
        self.assertEqual(r.status_code, 401)
        self.assertIn("Basic", r.headers.get("www-authenticate", ""))

    def test_wrong_token_returns_401(self):
        client = TestClient(_app("hunter2"))
        r = client.post(
            "/admin/restart", headers={"X-AI-Music-Token": "wrong"},
        )
        self.assertEqual(r.status_code, 401)

    def test_valid_header_schedules_sigterm_and_returns_202(self):
        client = TestClient(_app("hunter2"))
        with mock.patch.object(admin_mod, "_send_sigterm") as send:
            # Patch call_later to fire immediately so we can assert the
            # sigterm scheduler was invoked with our helper.
            real_get_event_loop = admin_mod.asyncio.get_event_loop
            captured = {}

            class FakeLoop:
                def call_later(self, delay, fn, *args):
                    captured["delay"] = delay
                    captured["fn"] = fn
                    captured["args"] = args

            with mock.patch.object(
                admin_mod.asyncio, "get_event_loop", lambda: FakeLoop(),
            ):
                r = client.post(
                    "/admin/restart",
                    headers={"X-AI-Music-Token": "hunter2"},
                )
                _ = real_get_event_loop  # silence unused

            self.assertEqual(r.status_code, 202)
            body = r.json()
            self.assertEqual(body["status"], "restarting")
            self.assertIn("pid", body)
            # The scheduler was handed our helper.
            self.assertIs(captured.get("fn"), admin_mod._send_sigterm)
            self.assertGreater(captured.get("delay", 0), 0)
            # Helper itself wasn't called yet (the fake loop dropped it).
            send.assert_not_called()

    def test_valid_basic_auth_returns_202(self):
        client = TestClient(_app("hunter2"))

        class NoopLoop:
            def call_later(self, *_a, **_k):
                pass

        with mock.patch.object(
            admin_mod.asyncio, "get_event_loop", lambda: NoopLoop(),
        ):
            r = client.post("/admin/restart", auth=("ios", "hunter2"))
        self.assertEqual(r.status_code, 202)

    def test_send_sigterm_handles_missing_pid(self):
        """``_send_sigterm`` swallows ProcessLookupError so a stale
        scheduled call after the process exits doesn't bubble up."""
        with mock.patch.object(
            admin_mod.os, "kill", side_effect=ProcessLookupError,
        ):
            # Must not raise.
            admin_mod._send_sigterm(999999)


if __name__ == "__main__":
    unittest.main(verbosity=2)
