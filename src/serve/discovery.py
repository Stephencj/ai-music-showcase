"""mDNS / Bonjour advertisement so the iOS app discovers the Mac
running AI Music Studio on Wi-Fi without typing an IP address.

Service name: ``_ai-music._tcp.local``.
TXT record carries the running version + hostname so the iOS UI can
display a friendly identifier in the discovery list.
"""

from __future__ import annotations

import logging
import socket
from typing import Optional


logger = logging.getLogger("ai_music_studio.discovery")


SERVICE_TYPE = "_ai-music._tcp.local."


class MdnsAdvertiser:
    """Owns a zeroconf instance + registered service. Idempotent close()
    so it's safe to call from atexit hooks even if registration failed."""

    def __init__(self) -> None:
        self._zeroconf = None
        self._service_info = None

    def start(self, *, port: int, version: str = "0.1.0",
              instance_name: Optional[str] = None) -> None:
        try:
            from zeroconf import IPVersion, ServiceInfo, Zeroconf
        except ImportError:
            logger.warning(
                "zeroconf not installed; skipping mDNS advertisement. "
                "Install it via `pip install zeroconf` to enable LAN "
                "auto-discovery from the iOS app."
            )
            return

        hostname = socket.gethostname()
        # Bonjour-friendly instance name (avoids dots/spaces in the
        # leading segment; users see this in the iOS picker).
        safe_host = hostname.split(".")[0].replace(" ", "-")
        instance = instance_name or f"AI Music Studio on {safe_host}"
        # Zeroconf appends the service type, so the full name is
        # "<instance>._ai-music._tcp.local."
        full_name = f"{instance}.{SERVICE_TYPE}"

        addresses = []
        try:
            # Prefer the IP reachable from the outside world.
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                addresses.append(socket.inet_aton(s.getsockname()[0]))
        except OSError:
            pass
        if not addresses:
            try:
                _, _, ips = socket.gethostbyname_ex(hostname)
                for ip in ips:
                    if not ip.startswith("127."):
                        addresses.append(socket.inet_aton(ip))
            except OSError:
                pass
        if not addresses:
            logger.warning("No non-loopback IP found; mDNS advertisement skipped.")
            return

        info = ServiceInfo(
            type_=SERVICE_TYPE,
            name=full_name,
            addresses=addresses,
            port=port,
            properties={
                b"version": version.encode("utf-8"),
                b"hostname": hostname.encode("utf-8"),
                b"path": b"/",
            },
            server=f"{safe_host}.local.",
        )

        try:
            zc = Zeroconf(ip_version=IPVersion.V4Only)
            zc.register_service(info)
        except Exception as e:
            logger.warning("Failed to register mDNS service: %s", e)
            return

        self._zeroconf = zc
        self._service_info = info
        logger.info("Advertising %s on port %d via mDNS", full_name, port)

    def close(self) -> None:
        info = self._service_info
        zc = self._zeroconf
        self._service_info = None
        self._zeroconf = None
        if zc is None:
            return
        try:
            if info is not None:
                zc.unregister_service(info)
        except Exception:
            logger.exception("Failed to unregister mDNS service")
        try:
            zc.close()
        except Exception:
            logger.exception("Failed to close zeroconf")
