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
    def test_minor_chorus_lands_on_relative_degree(self):
        # A hip-hop (minor) chorus inside a pop song in C major realizes on the
        # relative degree (A minor, the vi) so it stays diatonic to C major —
        # no out-of-key clash. The OLD behaviour (parallel C minor, with Eb/Ab)
        # introduced accidentals; the relative key keeps everything in one key.
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
        cmaj = {0, 2, 4, 5, 7, 9, 11}
        notes = [n for i in pm.instruments if not i.is_drum
                 for n in i.notes if t0 <= n.start < t1]
        off = sum(1 for n in notes if n.pitch % 12 not in cmaj)
        self.assertTrue(notes)
        # The chorus is diatonic to C major (its own A-minor key shares the
        # signature) — only incidental chromatic colour, no Eb/Ab clash.
        self.assertLess(off / len(notes), 0.10, "chorus drifts out of the C-major key")


if __name__ == "__main__":
    unittest.main()
