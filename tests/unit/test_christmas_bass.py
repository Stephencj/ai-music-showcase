"""Something holds the bass under every Christmas style, for as long as the
chord does.

Two bugs left it thin: the fireside's cello is its only bass, and it leaves
the roots when it takes the tune or a countermelody (pass 2, the final
pass), so a soft upright now plucks them there. And a note humanised a few
ms ahead of its chord was clipped to the previous chord's end, a blip:
about a third of every style's bass notes."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np  # noqa: E402

from src.composition import christmas  # noqa: E402
from tests.unit.test_christmas_ranges import compose  # noqa: E402

BASS_TRACKS = ("Upright Bass", "Contrabass", "Electric Bass", "Cello", "Organ Pedal Bass")


def _bass_notes(pm):
    return [n for t in pm.instruments if t.name in BASS_TRACKS for n in t.notes if n.pitch <= 50]


class ChristmasBassTests(unittest.TestCase):

    def test_no_bass_note_is_clipped_to_a_blip(self):
        for genre in christmas.STYLE_IDS:
            for seed in (1, 6):
                with self.subTest(genre=genre, seed=seed):
                    notes = _bass_notes(compose(genre, "original", seed=seed, length=90))
                    self.assertTrue(notes)
                    short = [(round(n.start, 2), n.pitch) for n in notes if n.end - n.start < 0.15]
                    self.assertFalse(short, f"bass notes clipped short: {short[:8]}")

    def test_fireside_bass_holds_when_the_cello_leaves_the_roots(self):
        for seed in (1, 2, 6, 105702):
            with self.subTest(seed=seed):
                pm = compose("christmas_fireside_full", "original", seed=seed, length=90)
                notes = _bass_notes(pm)
                start = min(n.start for n in notes)
                end = max(n.end for t in pm.instruments for n in t.notes)
                grid = np.arange(start, end, 0.05)
                on = np.zeros(len(grid), bool)
                for n in notes:
                    on |= (grid >= n.start) & (grid < n.end)
                self.assertGreaterEqual(on.mean(), 0.85, "the bass drops out")
                upright = [t for t in pm.instruments if t.name == "Upright Bass"]
                self.assertTrue(upright and upright[0].notes, "no upright where the cello leaves the roots")


if __name__ == "__main__":
    unittest.main()
