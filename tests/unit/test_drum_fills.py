"""Tests for transition drum fills (last bar of a section)."""
import unittest

from src.daw_integration.generic.midi_export import GM_DRUMS, MidiExporter

_TOMS = {GM_DRUMS["tom_low"], GM_DRUMS["tom_mid"], GM_DRUMS["tom_high"]}


def _drum_notes(bars=8, fill_prob=0.0, seed=1):
    m = MidiExporter(tempo=120)  # 4/4
    m.add_drum_pattern(pattern="basic_rock", bars=bars, seed=seed,
                       fill_last_bar=(fill_prob > 0), fill_prob=fill_prob)
    return m.tracks[0].notes, m.bar_duration


class TestDrumFills(unittest.TestCase):
    def test_no_fill_when_disabled(self):
        notes, _ = _drum_notes(fill_prob=0.0)
        self.assertFalse(any(n.pitch in _TOMS for n in notes),
                         "basic_rock has no toms; a tom means a stray fill")

    def test_fill_changes_last_bar(self):
        """A fill rewrites the last bar's back half (different from plain)."""
        plain, bd = _drum_notes(bars=8, fill_prob=0.0)
        filled, _ = _drum_notes(bars=8, fill_prob=1.0, seed=3)
        back_half = 7 * bd + 2 * (bd / 4)  # last bar, beat 2 onward (4/4)
        plain_bh = sorted((round(n.start, 4), n.pitch) for n in plain if n.start >= back_half - 1e-6)
        filled_bh = sorted((round(n.start, 4), n.pitch) for n in filled if n.start >= back_half - 1e-6)
        self.assertNotEqual(plain_bh, filled_bh, "fill did not change the last bar")
        self.assertTrue(filled_bh, "fill produced no hits in the last bar")

    def test_toms_appear_across_seeds(self):
        """Most fills are tom fills, so toms show up across several seeds."""
        seen = False
        for seed in range(1, 12):
            notes, _ = _drum_notes(bars=8, fill_prob=1.0, seed=seed)
            if any(n.pitch in _TOMS for n in notes):
                seen = True
                break
        self.assertTrue(seen, "no tom fills across 11 seeds")

    def test_groove_intact_in_earlier_bars(self):
        """Fills only touch the last bar — earlier bars are unchanged."""
        plain, bd = _drum_notes(bars=8, fill_prob=0.0)
        filled, _ = _drum_notes(bars=8, fill_prob=1.0, seed=3)
        cutoff = 7 * bd
        plain_early = sorted((round(n.start, 4), n.pitch) for n in plain if n.start < cutoff - 1e-6)
        filled_early = sorted((round(n.start, 4), n.pitch) for n in filled if n.start < cutoff - 1e-6)
        self.assertEqual(plain_early, filled_early)

    def test_short_section_not_filled(self):
        notes, _ = _drum_notes(bars=1, fill_prob=1.0)
        self.assertFalse(any(n.pitch in _TOMS for n in notes))

    def test_deterministic(self):
        a, _ = _drum_notes(bars=8, fill_prob=0.7, seed=9)
        b, _ = _drum_notes(bars=8, fill_prob=0.7, seed=9)
        self.assertEqual([(round(n.start, 4), n.pitch) for n in a],
                         [(round(n.start, 4), n.pitch) for n in b])


if __name__ == "__main__":
    unittest.main()
