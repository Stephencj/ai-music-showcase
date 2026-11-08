#!/usr/bin/env python3
"""Launch the AI Music MCP server over stdio.

Register with Claude Code (user scope, from the main checkout)::

    claude mcp add --scope user ai-music -- \
        /Users/stephencjuliano/Documents/ai-music/.venv/bin/python \
        /Users/stephencjuliano/Documents/ai-music/scripts/run_mcp.py

The same tools are also mounted at ``/mcp`` on the FastAPI launcher
for remote / SSE clients — see ``src/serve/launcher.py``.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path


# Make ``src.*`` imports work when the script is launched from any cwd.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def main() -> None:
    # The studio's stores use paths relative to the repo (data/blocks, ...),
    # and an MCP client launches this from wherever it happens to be.
    os.chdir(PROJECT_ROOT)
    # MCP stdio uses stdout as the transport — log to stderr so the
    # protocol stays clean.
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    # The protocol owns the real stdout. Point fd 1 at stderr so a stray
    # print anywhere in the engine (Python or a C library) can't corrupt it.
    protocol_out = os.fdopen(os.dup(sys.stdout.fileno()), "wb", buffering=0)
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())

    import anyio
    from io import TextIOWrapper
    from mcp.server.stdio import stdio_server
    from src.serve.mcp_tools import mcp

    async def serve() -> None:
        out = anyio.wrap_file(TextIOWrapper(protocol_out, encoding="utf-8", write_through=True))
        async with stdio_server(stdout=out) as (read_stream, write_stream):
            server = mcp._mcp_server
            await server.run(read_stream, write_stream, server.create_initialization_options())

    anyio.run(serve)


if __name__ == "__main__":
    main()
