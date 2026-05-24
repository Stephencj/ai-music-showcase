"""Env-driven launcher for the Gradio app.

Reads ``AI_MUSIC_HOST`` / ``AI_MUSIC_PORT`` / ``AI_MUSIC_AUTH_TOKEN`` /
``AI_MUSIC_SHARE`` from the environment, mounts the Gradio Blocks onto
a FastAPI app (so we can attach ``/healthz`` and the token middleware),
advertises the service over mDNS, and starts uvicorn.

Falls back to Gradio's native ``.launch()`` only when ``share=True`` —
Gradio's share tunnel doesn't compose cleanly with ``mount_gradio_app``.
"""

from __future__ import annotations

import logging
import os
from typing import Callable, Optional

import gradio as gr

from .admin import register_admin
from .auth import IPAwareAuthMiddleware, get_token, gradio_auth_callable
from .discovery import MdnsAdvertiser
from .health import VERSION, print_banner, register_healthz


logger = logging.getLogger("ai_music_studio.launcher")


def _resolve_host_port() -> tuple[str, int]:
    host = os.environ.get("AI_MUSIC_HOST", "0.0.0.0").strip() or "0.0.0.0"
    try:
        port = int(os.environ.get("AI_MUSIC_PORT", "7860"))
    except ValueError:
        port = 7860
    return host, port


def _share_enabled() -> bool:
    return os.environ.get("AI_MUSIC_SHARE", "").lower() in ("1", "true", "yes")


def launch(blocks: gr.Blocks, *,
           on_shutdown: Optional[Callable[[], None]] = None) -> None:
    """Start the Gradio Blocks under uvicorn with the AI-Music server
    glue (healthz, mDNS, optional auth)."""
    host, port = _resolve_host_port()
    token = get_token()
    share = _share_enabled()
    auth = gradio_auth_callable(token)

    if share:
        # Gradio's share tunnel is the easiest fallback when the user
        # really wants a public URL without setting up Tailscale. We
        # skip the FastAPI wrapper here because mount_gradio_app +
        # share don't co-exist cleanly.
        logger.info("AI_MUSIC_SHARE is set — falling back to native gr.launch(share=True)")
        print_banner(port, token_set=bool(token),
                     extra=["Mode:      share (gradio.live tunnel)"])
        blocks.launch(server_name=host, server_port=port, share=True,
                      auth=auth, show_error=True)
        return

    try:
        from fastapi import FastAPI
        import uvicorn
    except ImportError as e:
        raise RuntimeError(
            "FastAPI and uvicorn are required for the AI-Music launcher. "
            "They ship with Gradio — `pip install gradio` should pull both."
        ) from e

    api = FastAPI(title="AI Music Studio")
    register_healthz(api)
    register_admin(api, token=token)
    if token:
        # The middleware is the SOLE auth gate now — it handles HTTP +
        # WebSocket and skips trusted IPs. Gradio's own `auth=` is
        # only used by the `share=True` fallback path above.
        api.add_middleware(IPAwareAuthMiddleware, token=token)

    # CORS so the bundled Android app (loaded from a virtual https origin)
    # can call /api cross-origin. Added AFTER the auth middleware so it wraps
    # OUTERMOST and answers preflight OPTIONS before auth sees them. Auth is
    # still enforced (by IP / token) on the actual requests.
    try:
        from fastapi.middleware.cors import CORSMiddleware
        api.add_middleware(
            CORSMiddleware,
            # Just the bundled Android app's virtual origin — not "*".
            allow_origins=["https://appassets.androidplatform.net"],
            allow_methods=["*"],
            allow_headers=["*"],
            allow_credentials=False,
        )
    except Exception:
        logger.exception("could not add CORS middleware")

    # Thin REST API for the cross-platform frontend — calls the same engine
    # functions the Gradio buttons call. Mounted before the Gradio app so
    # /api/* resolves here; inherits the token middleware above.
    try:
        from src.api import router as api_router
        api.include_router(api_router)
    except Exception:
        logger.exception("could not mount /api router — Gradio UI still boots")

    # Mount vendored JS (AlphaTab etc.) before mount_gradio_app so the
    # routing intent is explicit. /static/alphatab/ is whitelisted in
    # the auth middleware so the iOS WebView can fetch the library
    # off-LAN without the token shaking hands on every file.
    from pathlib import Path as _Path
    from fastapi.staticfiles import StaticFiles
    _static_dir = _Path(__file__).resolve().parents[2] / "static"
    if _static_dir.exists():
        api.mount("/static", StaticFiles(directory=str(_static_dir)),
                  name="static")

    # New cross-platform web app (React/Vite). Built bundle is served at
    # /app so an iPhone/desktop client can load it straight from the Mac
    # (and Capacitor/Tauri later bundle the same dist/). html=True makes it
    # an SPA fallback. Built via `cd web && npm run build`.
    _web_dist = _Path(__file__).resolve().parents[2] / "web" / "dist"
    if _web_dist.exists():
        api.mount("/app", StaticFiles(directory=str(_web_dist), html=True),
                  name="webapp")

    # MCP server (SSE transport) — same auth middleware as the rest of
    # the FastAPI app, so off-LAN clients need the token. Stdio
    # transport is a separate process; see scripts/run_mcp.py.
    try:
        from src.serve.mcp_tools import mcp as _mcp
        api.mount("/mcp", _mcp.sse_app())
    except Exception:
        logger.exception("could not mount MCP /mcp — server will still boot")

    # AlphaTab + the Playback bridge must load in <head>; the browser
    # spec says scripts injected via innerHTML (which is how gr.HTML
    # ends up rendering) are silently ignored, so script tags inside
    # the Playback tab's HTML payload never executed before this fix.
    try:
        from src.playback.playback_html import build_playback_head
        playback_head = build_playback_head()
    except Exception:
        logger.exception("could not assemble playback head — playback will be inert")
        playback_head = ""

    # Whitelist data/outputs so the Playback tab can iframe the
    # FluidSynth-rendered HQ WAV (the Gradio default allowlist
    # only auto-passes files it handed out as component outputs,
    # but the audio URL is generated server-side and returned as
    # a plain string into a hidden Textbox).
    _project_root = _Path(__file__).resolve().parents[2]
    allowed_paths = [
        str(_project_root / "data" / "outputs"),
        str(_project_root / "data" / "blocks"),
    ]

    # iPhone responsiveness: stack wide rows vertically on narrow
    # viewports (390 pt iPhone width is the target). `elem_classes`
    # on the row is the stable selector — survives Gradio version
    # bumps because it's a public API. Desktop layout is untouched.
    responsive_css = (
        "@media (max-width: 500px) {"
        "  .compose-row-grid {"
        "    flex-direction: column !important;"
        "    gap: .5rem !important;"
        "  }"
        "  .compose-row-grid > * {"
        "    min-width: 0 !important;"
        "    width: 100% !important;"
        "    max-width: 100% !important;"
        "  }"
        # Family accordions on iPhone: stack vertically, full-width,
        # with bigger tap targets for each instrument checkbox.
        "  .instrument-family {"
        "    width: 100% !important;"
        "    margin-bottom: .35rem !important;"
        "  }"
        "  .instrument-family .wrap,"
        "  .instrument-family .gradio-checkboxgroup {"
        "    flex-direction: column !important;"
        "    gap: .25rem !important;"
        "  }"
        "  .instrument-family label {"
        "    padding: .4rem 0 !important;"
        "    min-height: 36px !important;"
        "    font-size: 0.95rem !important;"
        "  }"
        # iOS Safari: when the on-screen keyboard is open, Gradio
        # dropdown popups (Key / Scale / Voicing / Chord-rhythm /
        # Style) extend to their natural height and disappear behind
        # the keyboard. Capping their max-height keeps them scrollable
        # and within reach.
        "  ul[role='listbox'],"
        "  .options,"
        "  .dropdown-menu,"
        "  .gradio-dropdown ul {"
        "    max-height: 40vh !important;"
        "    overflow-y: auto !important;"
        "  }"
        "}"
    )

    gr.mount_gradio_app(
        api, blocks, path="/",
        head=playback_head,
        allowed_paths=allowed_paths,
        css=responsive_css,
    )

    advertiser = MdnsAdvertiser()
    advertiser.start(port=port, version=VERSION)

    print_banner(port, token_set=bool(token))

    try:
        uvicorn.run(api, host=host, port=port, log_level="info")
    finally:
        advertiser.close()
        if on_shutdown is not None:
            try:
                on_shutdown()
            except Exception:
                logger.exception("on_shutdown hook raised")
