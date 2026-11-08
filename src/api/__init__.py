"""Thin HTTP API over the proven music engine.

This package exposes the *same* pure functions the Gradio buttons call
(``compose_song``, ``render_to_audio``, ``export_zip``, ``concat_blocks``,
``save_block``) as a clean JSON/REST surface for the cross-platform
frontend — no engine logic is re-implemented here, and there is no shared
global ``_state`` (every request carries its own parameters).

Mounted onto the existing FastAPI app in ``src/serve/launcher.py`` so it
reuses the token auth middleware, mDNS discovery, and health endpoints.
"""

from .routes import router  # noqa: F401
from .tools_routes import router as _tools_router

# The song tools over HTTP (/api/tools) for non-MCP clients such as the local AI.
router.include_router(_tools_router)

__all__ = ["router"]
