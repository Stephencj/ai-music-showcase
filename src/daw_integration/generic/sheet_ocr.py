"""Text recognition for sheet-music images — the bits oemer ignores.

oemer reads *notes*; it can't read text, so the tempo marking, title, and any
lyrics are lost. This module runs a plain OCR pass (Tesseract, via the
``tesseract`` binary that ships through Homebrew) to recover:

  - ``tempo``  — the metronome mark (e.g. "♩ = 130"), so playback runs at the
                 marked speed instead of a default guess. This is the single
                 biggest practical win — OMR alone always misses tempo.
  - ``title``  — the piece name, used to name the saved block.
  - ``composer`` and the raw text, surfaced for reference / future lyric use.

OCR is best-effort: if Tesseract isn't installed or reads nothing, callers fall
back to their previous behaviour (it never blocks a scan).
"""

from __future__ import annotations

import logging
import re
from typing import Optional

logger = logging.getLogger("ai_music_studio.sheet_ocr")

# A tempo marking after the note glyph: "= 130", "♩=92", "J = 100" (Tesseract
# often mis-reads the quarter-note glyph as J/d/. — so we anchor on the "=").
_TEMPO_RE = re.compile(r"=\s*([0-9]{2,3})")


def _alpha_ratio(s: str) -> float:
    letters = sum(c.isalpha() for c in s)
    return letters / len(s) if s else 0.0


def _extract_tempo(im) -> Optional[int]:
    """Read the metronome BPM from the top band of the score.

    Tempo marks are small and sit just above the first staff, so we crop the
    top strip, upscale it, and OCR a couple of page-segmentation modes. Returns
    a sane BPM (40–300) or None.
    """
    import pytesseract

    W, H = im.size
    band = im.crop((0, int(H * 0.05), W, int(H * 0.24)))
    band = band.resize((band.width * 3, band.height * 3))
    for psm in (6, 11):
        try:
            txt = pytesseract.image_to_string(band, config=f"--psm {psm}")
        except Exception:
            return None
        for m in _TEMPO_RE.finditer(txt):
            n = int(m.group(1))
            if 40 <= n <= 300:
                return n
    return None


def _extract_title(lines: list[str]) -> Optional[str]:
    """First text-like line (the title sits at the very top of the page)."""
    for ln in lines:
        # Skip pure numbers (bar numbers) and OCR garbage (mostly symbols).
        if len(ln) >= 4 and _alpha_ratio(ln) >= 0.6 and any(c.isalpha() for c in ln):
            return ln
    return None


def extract_metadata(image_path: str) -> dict:
    """Best-effort {title, composer, tempo, raw_text} from a score image.

    Always returns a dict; missing fields are None. Never raises — OCR is an
    enhancement, not a hard dependency of scanning.
    """
    out = {"title": None, "composer": None, "tempo": None, "raw_text": ""}
    try:
        import pytesseract
        from PIL import Image, ImageOps
    except Exception as exc:  # noqa: BLE001 — pytesseract/PIL not importable
        logger.info("sheet OCR unavailable: %s", exc)
        return out

    try:
        im = ImageOps.exif_transpose(Image.open(image_path)).convert("L")
        full = pytesseract.image_to_string(im)
    except Exception as exc:  # noqa: BLE001 — e.g. tesseract binary missing
        logger.info("sheet OCR failed (is the tesseract binary installed?): %s", exc)
        return out

    out["raw_text"] = full
    lines = [l.strip() for l in full.splitlines() if l.strip()]
    out["title"] = _extract_title(lines)
    # Composer is conventionally the next text line after the title (often
    # right-aligned). Best-effort only.
    if out["title"] and out["title"] in lines:
        idx = lines.index(out["title"])
        for ln in lines[idx + 1:]:
            if len(ln) >= 3 and _alpha_ratio(ln) >= 0.6:
                out["composer"] = ln
                break
    out["tempo"] = _extract_tempo(im)
    return out
