"""Health-check endpoint + LAN-IP startup banner.

The endpoint serves three purposes:

  - The iOS app pings it to verify a host is reachable before loading
    the Gradio UI in WebView (avoids a 30-second WebView timeout if
    the user typed the wrong URL).
  - The mDNS advertiser only registers when the route comes up.
  - The Docker ``HEALTHCHECK`` directive uses it to mark the container
    healthy.
"""

from __future__ import annotations

import socket
from typing import Iterable

from fastapi import FastAPI


VERSION = "0.1.0"


def register_healthz(api: FastAPI) -> None:
    """Mount the ``/healthz`` route on the given FastAPI app."""

    @api.get("/healthz")
    def _healthz() -> dict:
        return {
            "status": "ok",
            "service": "ai-music-studio",
            "version": VERSION,
            "host": socket.gethostname(),
        }


def lan_ips() -> list[str]:
    """Best-effort enumeration of the host's LAN IPv4 addresses.

    Returns non-loopback addresses likely reachable from the iPhone on
    the same Wi-Fi. Order: best-guess primary first, then any aliases.
    """
    ips: list[str] = []
    try:
        # Trick: opening a UDP socket to a non-local address reveals the
        # interface the OS would use to reach the outside world — no
        # actual packets are sent.
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            primary = s.getsockname()[0]
            if primary and not primary.startswith("127."):
                ips.append(primary)
    except OSError:
        pass

    try:
        _, _, addresses = socket.gethostbyname_ex(socket.gethostname())
        for addr in addresses:
            if addr and not addr.startswith("127.") and addr not in ips:
                ips.append(addr)
    except OSError:
        pass

    return ips


def print_banner(port: int, *, token_set: bool, extra: Iterable[str] = ()) -> None:
    """Print the startup banner with reachable URLs.

    ``extra`` lets the caller add notes (e.g. share URL, container hint).
    """
    bar = "─" * 60
    print()
    print(bar)
    print(" AI Music Studio")
    print(bar)
    print(f" Local:     http://127.0.0.1:{port}")
    for ip in lan_ips():
        print(f" LAN:       http://{ip}:{port}")
    print(f" Health:    /healthz")
    if token_set:
        print(" Auth:      ENABLED (X-AI-Music-Token or Basic Auth)")
    else:
        print(" Auth:      DISABLED (set AI_MUSIC_AUTH_TOKEN to enable)")
    for line in extra:
        print(f" {line}")
    print(bar)
    print()
