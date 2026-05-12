"""Locate a usable SoundFont (.sf2/.sf3) for FluidSynth rendering.

Resolution order:

1. Explicit path passed by the caller.
2. Path from env var ``AI_MUSIC_SOUNDFONT``.
3. Any ``*.sf3`` / ``*.sf2`` in ``data/soundfonts/`` (preferring the largest
   file — bigger soundfonts are typically higher quality).
4. The ``TimGM6mb.sf2`` bundled with the ``pretty_midi`` package as a final
   fallback (low quality but always present).

Use :func:`resolve_soundfont` to get a path, and
:func:`download_default` to one-shot fetch ``MuseScore_General.sf3`` into
``data/soundfonts/`` if no high-quality soundfont is on disk yet.
"""

from __future__ import annotations

import logging
import os
import urllib.request
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SOUNDFONT_DIR = PROJECT_ROOT / "data" / "soundfonts"

# MuseScore General is ~38 MB, freely licensed (MIT-style), and is the
# best-quality general-purpose SF3 we can reliably download.
MUSESCORE_GENERAL_URL = (
    "https://ftp.osuosl.org/pub/musescore/soundfont/"
    "MuseScore_General/MuseScore_General.sf3"
)
MUSESCORE_GENERAL_NAME = "MuseScore_General.sf3"


class SoundfontNotFoundError(RuntimeError):
    """Raised when no usable soundfont can be located."""


def _bundled_pretty_midi_sf2() -> Optional[Path]:
    """Return the ``TimGM6mb.sf2`` shipped with pretty_midi, if present."""
    try:
        import pretty_midi  # noqa: F401
    except ImportError:
        return None
    pm_dir = Path(pretty_midi.__file__).parent
    candidate = pm_dir / "TimGM6mb.sf2"
    return candidate if candidate.exists() else None


def _largest_local_soundfont(search_dir: Path) -> Optional[Path]:
    """Return the largest .sf3/.sf2 in ``search_dir`` (recursive), or None."""
    if not search_dir.exists():
        return None
    candidates = [
        p for p in search_dir.rglob("*")
        if p.is_file() and p.suffix.lower() in (".sf2", ".sf3")
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda p: p.stat().st_size, reverse=True)
    return candidates[0]


def resolve_soundfont(
    explicit: Optional[str | Path] = None,
    *,
    search_dir: Optional[Path] = None,
) -> Path:
    """Resolve a soundfont path using the documented fallback chain.

    Args:
        explicit: A user-provided path (CLI flag, UI input). If set and the
            file exists, it wins.
        search_dir: Directory to scan for local soundfonts. Defaults to
            ``data/soundfonts/`` at the project root.

    Returns:
        A resolved path that exists on disk.

    Raises:
        SoundfontNotFoundError: if no soundfont can be found anywhere.
    """
    if explicit:
        p = Path(explicit).expanduser().resolve()
        if p.exists():
            logger.info("soundfont: using explicit %s", p)
            return p
        raise SoundfontNotFoundError(f"Explicit soundfont not found: {p}")

    env_path = os.environ.get("AI_MUSIC_SOUNDFONT")
    if env_path:
        p = Path(env_path).expanduser().resolve()
        if p.exists():
            logger.info("soundfont: using $AI_MUSIC_SOUNDFONT %s", p)
            return p
        logger.warning("$AI_MUSIC_SOUNDFONT set to missing path: %s", p)

    sd = (search_dir or DEFAULT_SOUNDFONT_DIR).resolve()
    local = _largest_local_soundfont(sd)
    if local:
        logger.info("soundfont: using local %s (%.1f MB)",
                    local, local.stat().st_size / 1e6)
        return local

    bundled = _bundled_pretty_midi_sf2()
    if bundled:
        logger.warning(
            "soundfont: falling back to bundled TimGM6mb.sf2 — quality is "
            "low. Run download_default() or drop a high-quality .sf2/.sf3 "
            "into %s for better results.",
            sd,
        )
        return bundled

    raise SoundfontNotFoundError(
        f"No soundfont found. Place a .sf2/.sf3 in {sd}, set "
        f"$AI_MUSIC_SOUNDFONT, or call download_default()."
    )


def download_default(
    target_dir: Optional[Path] = None,
    *,
    overwrite: bool = False,
) -> Path:
    """Download MuseScore General SF3 (~38 MB) into ``target_dir``.

    Args:
        target_dir: Where to place the file. Defaults to
            ``data/soundfonts/``.
        overwrite: If True, redownload even when the file already exists.

    Returns:
        Path to the downloaded soundfont.
    """
    target_dir = (target_dir or DEFAULT_SOUNDFONT_DIR).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    out = target_dir / MUSESCORE_GENERAL_NAME

    if out.exists() and not overwrite:
        logger.info("soundfont: %s already present, skipping download", out)
        return out

    logger.info("soundfont: downloading %s → %s", MUSESCORE_GENERAL_URL, out)
    urllib.request.urlretrieve(MUSESCORE_GENERAL_URL, out)  # nosec - https URL
    logger.info("soundfont: downloaded %.1f MB", out.stat().st_size / 1e6)
    return out
