"""Logic Pro integration.

Logic Pro has no public CLI / AppleScript bounce API, so we ship a folder
that's optimized for *manual* finishing — drag the per-track ``.mid``
files onto a fresh Logic project, swap in your favorite Alchemy / EXS
patches using the recommended-instrument map in ``LOGIC_README.md``, and
bounce.

Public API:

- :class:`LogicSessionBundle` — assemble + write the bundle.
"""

from .bundle import LogicSessionBundle

__all__ = ["LogicSessionBundle"]
