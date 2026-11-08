#!/usr/bin/env python3
"""Answer the app's "describe / revise my song" requests with Claude.

The app queues each request (src/api/ai_requests.py) with the full prompt in
it: ``params.system`` is src/composition/song_plan_guide.md plus the live
catalog, ``params.user`` the description or the feedback with the current
plan. This loop polls the queue, claims a request, asks Claude Code headless
(``claude -p``, your normal Claude login, no API key) and posts the plan back.
The app treats the polling as a heartbeat: while this runs, Describe uses
Claude; when it stops, the app falls back to the local model within seconds.

    .venv/bin/python scripts/claude_answerer.py              # live app on :7860
    .venv/bin/python scripts/claude_answerer.py --api http://127.0.0.1:7961
    .venv/bin/python scripts/claude_answerer.py --model sonnet --once

See docs/describe.md for the interactive-session alternative.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.composition.song_plan import PlanError, parse_model_output  # noqa: E402

KINDS = "describe,revise"
NAME = "claude-cli"


def _call(api: str, path: str, body: dict | None = None, method: str | None = None, timeout: float = 15) -> dict:
    headers = {"Content-Type": "application/json"}
    token = os.environ.get("AI_MUSIC_AUTH_TOKEN")
    if token:
        headers["X-AI-Music-Token"] = token
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(api + path, data=data, headers=headers,
                                 method=method or ("POST" if data is not None else "GET"))
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode() or "{}")


def ask_claude(system: str, user: str, command: list[str], model: str | None, timeout: float) -> str:
    """One headless Claude Code turn: no tools, no MCP servers, no saved
    session; the guide is the whole system prompt. Returns Claude's text."""
    cmd = list(command) + ["-p", "--output-format", "json", "--tools", "",
                           "--strict-mcp-config", "--no-session-persistence",
                           "--system-prompt", system]
    if model:
        cmd += ["--model", model]
    with tempfile.TemporaryDirectory() as td:     # no project context to load
        proc = subprocess.run(cmd, input=user, capture_output=True, text=True, timeout=timeout, cwd=td)
    if proc.returncode != 0:
        raise RuntimeError(f"claude exited {proc.returncode}: {(proc.stderr or proc.stdout)[-400:]}")
    try:
        out = json.loads(proc.stdout)
    except ValueError:
        return proc.stdout
    if isinstance(out, dict):
        if out.get("is_error"):
            raise RuntimeError(f"claude error: {str(out.get('result'))[:400]}")
        return str(out.get("result") or "")
    return proc.stdout


def handle(api: str, rec: dict, command: list[str], model: str | None, timeout: float) -> str:
    rid = rec["id"]
    try:
        _call(api, f"/api/ai/requests/{rid}/claim?answerer={NAME}", {}, method="POST")
    except urllib.error.HTTPError as exc:
        if exc.code == 409:
            return "taken"
        raise
    params = rec.get("params") or {}
    try:
        text = ask_claude(params["system"], params["user"], command, model, timeout)
        plan, summary = parse_model_output(text)
        _call(api, f"/api/ai/requests/{rid}/answer", {"answer": {"plan": plan, "summary": summary}})
        return "answered"
    except (PlanError, RuntimeError, KeyError, subprocess.TimeoutExpired, OSError) as exc:
        _call(api, f"/api/ai/requests/{rid}/answer", {"error": str(exc)[:500]})
        return f"error: {exc}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--api", default=os.environ.get("AI_MUSIC_API", "http://127.0.0.1:7860"))
    ap.add_argument("--model", default=os.environ.get("CLAUDE_ANSWERER_MODEL"))
    ap.add_argument("--command", default=os.environ.get("CLAUDE_ANSWERER_CMD", "claude"),
                    help="the Claude Code CLI (tests point this at a stub)")
    ap.add_argument("--interval", type=float, default=2.0)
    ap.add_argument("--timeout", type=float, default=170.0, help="seconds per Claude answer")
    ap.add_argument("--once", action="store_true", help="answer what's pending, then exit")
    args = ap.parse_args()
    command = shlex.split(args.command)
    print(f"claude answerer: polling {args.api} for {KINDS} (Ctrl-C to stop)", flush=True)
    while True:
        try:
            pending = _call(args.api, f"/api/ai/requests?status=pending&kind={KINDS}&answerer={NAME}")
            for rec in pending.get("requests", []):
                t0 = time.time()
                outcome = handle(args.api, rec, command, args.model, args.timeout)
                print(f"{time.strftime('%H:%M:%S')} {rec.get('kind')} {rec['id']}: {outcome} "
                      f"({time.time() - t0:.1f}s)", flush=True)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            print(f"{time.strftime('%H:%M:%S')} poll failed: {exc}", flush=True)
        if args.once:
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
