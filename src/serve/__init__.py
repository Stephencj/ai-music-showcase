"""Server-side glue for exposing the Gradio app over the LAN + remote
networks. Pure-Python, framework-agnostic helpers used only by app.py's
launcher.

- ``discovery`` — mDNS/Bonjour advertisement (Zeroconf), so the iOS app
  can find the Mac on Wi-Fi without typing an IP.
- ``auth`` — token middleware + Gradio Basic Auth callable.
- ``health`` — /healthz route + LAN-IP startup banner.
- ``launcher`` — env-driven launch wrapper that ties it all together.
"""
