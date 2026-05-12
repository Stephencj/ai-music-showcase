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

    gr.mount_gradio_app(api, blocks, path="/")

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
