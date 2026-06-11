"""Modal-colour progression pass + per-section mode realization.

Pins that (1) modal scales lean into their signature chord and soften the
functional dominant toward the modal v, (2) major is left alone, and (3) a
multi-preset section composes in its OWN mode over the shared tonic — so its
chords and melody don't clash (the "out of tune" cross-relation fix).
"""

import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.composition.pacing import modal_color
from src.api.arrangement import build_sections
from src.composition.song_composer import compose_song


def _stems(prog, scale, seed):
    rng = np.random.default_rng(seed)
    return [s for s, _ in modal_color(prog, scale, rng)]


class ModalColorTests(unittest.TestCase):
    def test_major_is_untouched(self):
        prog = [("I", 1), ("V", 1), ("vi", 1), ("IV", 1)]
        for seed in range(8):
            self.assertEqual(_stems(prog, "major", seed), ["I", "V", "vi", "IV"])

    def test_dominant_softened_in_modal_scales(self):
        # Across seeds, a modal scale should turn the functional V into v at
        # least sometimes (and never the reverse).
        prog = [("i", 1), ("iv", 1), ("V", 1), ("i", 1)]
        softened = any("v" in _stems(prog, "dorian", s) and "V" not in _stems(prog, "dorian", s)
                       for s in range(12))
        self.assertTrue(softened)

    def test_colour_chord_appears(self):
        # Phrygian's colour is the bII (written "II", realized on the b2 degree).
        prog = [("i", 1), ("i", 1), ("iv", 1), ("i", 1)]
        got = any("II" in _stems(prog, "phrygian", s) for s in range(12))
        self.assertTrue(got)

    def test_harmonic_minor_not_modal(self):
        prog = [("i", 1), ("V", 1), ("i", 1), ("V", 1)]
        for seed in range(6):
            self.assertEqual(_stems(prog, "harmonic_minor", seed),
                             ["i", "V", "i", "V"])


class PerSectionModeTests(unittest.TestCase):
    def test_aeolian_chorus_has_no_major_third(self):
        # A hip-hop (minor) chorus inside a pop (major) song must realize in
        # aeolian — no major-3rd (E natural over a C tonic) cross-relation.
        secs = build_sections("pop", ["intro", "verse", "chorus", "bridge", "outro"],
                              {"chorus": "hip_hop_full"})
        out = compose_song(genre="pop", sections=secs, seed=3, key="C",
                           enabled_instruments=("drum_kit", "electric_bass", "piano"),
                           tempo=120.0, output_dir=Path(tempfile.mkdtemp()), skip_audio=True)
        import pretty_midi
        pm = pretty_midi.PrettyMIDI(out["midi_path"])
        ch = next(s for s in secs if s["role"] == "chorus")
        barlen = 4 * 60.0 / 120.0
        t0, t1 = ch["start_bar"] * barlen, (ch["end_bar"] + 1) * barlen
        pcs = {n.pitch % 12 for i in pm.instruments if not i.is_drum
               for n in i.notes if t0 <= n.start < t1}
        self.assertIn(3, pcs)         # Eb (minor 3rd) present
        self.assertNotIn(4, pcs)      # E natural (major 3rd) absent


if __name__ == "__main__":
    unittest.main()
