#!/usr/bin/env python3
"""Launch the AI Music MCP server over stdio.

Register with Claude Code::

    claude mcp add ai-music -- \
        /Users/stephencjuliano/Documents/ai-music/.venv/bin/python \
        /Users/stephencjuliano/Documents/ai-music/scripts/run_mcp.py

The same tools are also mounted at ``/mcp`` on the FastAPI launcher
for remote / SSE clients — see ``src/serve/launcher.py``.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path


# Make ``src.*`` imports work when the script is launched from any cwd.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def main() -> None:
    # MCP stdio uses stdout as the transport — log to stderr so the
    # protocol stays clean.
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    from src.serve.mcp_tools import mcp
    mcp.run()


if __name__ == "__main__":
    main()
