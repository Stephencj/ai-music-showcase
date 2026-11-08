"""MCP server exposing the studio's song tools to LLMs.

The tools themselves live in :mod:`src.serve.song_tools` (shared with the
local AI's HTTP tool endpoint, ``/api/tools``); this module only registers
them with FastMCP. Two transports ship side-by-side:

- **stdio** — the standard MCP pattern for local LLM clients. Launch
  with ``python scripts/run_mcp.py``; registered with Claude Code as
  ``claude mcp add --scope user ai-music -- <venv>/bin/python <repo>/scripts/run_mcp.py``.

- **SSE** — mounted at ``/mcp`` on the existing FastAPI launcher so a
  remote LLM (or a session on a different machine) can hit the same
  tools. Inherits ``IPAwareAuthMiddleware`` for off-LAN auth.
"""

from __future__ import annotations

import functools
import inspect
import logging

import anyio
from mcp.server.fastmcp import FastMCP

from src.serve import song_tools
from src.serve.song_tools import (  # noqa: F401 — re-exported for callers and tests
    TOOLS,
    compose_song,
    describe_options,
    inspect_technique,
    list_styles,
    list_techniques,
)


logger = logging.getLogger(__name__)


INSTRUCTIONS = """\
AI Music Studio: compose, render, revise and deliver songs.
Start with describe_options (every option explained, plus proven recipes) and
list_styles. generate_song makes a song; score_video scores a whole video by
chapter. Iterate with revise(job_id, changes) — it keeps the seed so only the
changed options differ. export_audio delivers files (target loudness, or onto a
video). Results carry absolute file paths."""

mcp = FastMCP("ai-music-studio", instructions=INSTRUCTIONS)


def _threaded(fn):
    """Run a (blocking) tool on a worker thread so the server stays responsive
    while a song renders. The signature and docstring stay the tool's own."""
    @functools.wraps(fn)
    async def runner(**kwargs):
        return await anyio.to_thread.run_sync(functools.partial(fn, **kwargs))
    return runner


for _fn in TOOLS:
    mcp.add_tool(_threaded(_fn), name=_fn.__name__, description=inspect.cleandoc(_fn.__doc__ or ""))
