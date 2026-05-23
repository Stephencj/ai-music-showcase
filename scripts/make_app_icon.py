#!/usr/bin/env python3
"""Generate the AI Music app icon — a white eighth note on a violet→blue
gradient — at 1024×1024.

Pure Pillow (no SVG rasterizer needed). Renders at 3× supersample for
crisp anti-aliased edges, then downscales with Lanczos. Used as the
single source of truth for every platform's icon:

  - iOS  : ios/AiMusic/Assets.xcassets/AppIcon.appiconset/AppIcon.png
  - master: assets/icon/eighth_note_1024.png  (reused by PWA / Tauri)

Run:  python3 scripts/make_app_icon.py
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

FINAL = 1024
SS = 3                      # supersample factor
S = FINAL * SS

# Brand gradient (top-left → bottom-right): violet → blue.
TOP = (124, 58, 237)       # #7C3AED
BOT = (37, 99, 235)        # #2563EB
NOTE = (255, 255, 255, 255)

ROOT = Path(__file__).resolve().parent.parent
IOS_ICON = ROOT / "ios/AiMusic/Assets.xcassets/AppIcon.appiconset/AppIcon.png"
MASTER = ROOT / "assets/icon/eighth_note_1024.png"


def _sc(p: tuple[float, float]) -> tuple[float, float]:
    return (p[0] * SS, p[1] * SS)


def _bezier(p0, p1, p2, n: int = 80):
    out = []
    for i in range(n + 1):
        t = i / n
        x = (1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t * t * p2[0]
        y = (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t * t * p2[1]
        out.append((x, y))
    return out


def _gradient_bg() -> Image.Image:
    xx, yy = np.meshgrid(np.linspace(0, 1, S), np.linspace(0, 1, S))
    t = (xx + yy) / 2.0
    bg = np.zeros((S, S, 3), dtype=np.float32)
    for i in range(3):
        bg[..., i] = TOP[i] + (BOT[i] - TOP[i]) * t
    return Image.fromarray(bg.astype(np.uint8), "RGB").convert("RGBA")


def _eighth_note() -> Image.Image:
    """A white eighth note (♪) drawn full-canvas (transparent elsewhere).
    Coordinates are in FINAL space; _sc scales to supersample space."""
    layer = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)

    # Stem — vertical bar on the right of the notehead, going up.
    stem = [(498, 300), (548, 300), (548, 690), (498, 690)]
    d.polygon([_sc(p) for p in stem], fill=NOTE)

    # Flag — a single quaver flag sweeping right & down off the stem top.
    # Built from an outer (right-bulging) curve and an inner return curve
    # so the filled region reads as a sail.
    outer = _bezier((548, 296), (760, 360), (612, 540))
    inner = _bezier((612, 540), (612, 420), (548, 410))
    d.polygon([_sc(p) for p in outer] + [_sc(p) for p in inner], fill=NOTE)

    # Notehead — an oval, tilted up-to-the-right like real notation.
    head = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    hd = ImageDraw.Draw(head)
    cx, cy, rx, ry = 405, 700, 158, 116
    hd.ellipse([_sc((cx - rx, cy - ry)), _sc((cx + rx, cy + ry))], fill=NOTE)
    head = head.rotate(20, center=_sc((cx, cy)), resample=Image.BICUBIC)
    layer = Image.alpha_composite(layer, head)
    return layer


def build() -> Image.Image:
    img = _gradient_bg()
    note = _eighth_note()

    # Soft drop shadow for depth.
    shadow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    shadow.paste((20, 20, 60, 130), mask=note.getchannel("A"))
    shadow = shadow.filter(ImageFilter.GaussianBlur(SS * 6))
    img.alpha_composite(shadow, (SS * 7, SS * 9))

    img.alpha_composite(note)
    return img.convert("RGB").resize((FINAL, FINAL), Image.LANCZOS)


def main() -> None:
    icon = build()
    for out in (IOS_ICON, MASTER):
        out.parent.mkdir(parents=True, exist_ok=True)
        icon.save(out)
        print(f"wrote {out.relative_to(ROOT)}  ({out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
