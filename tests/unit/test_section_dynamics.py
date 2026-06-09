"""Tests for per-section dynamics (verse pulled back vs chorus full)."""
import unittest

import pretty_midi

import src.composition.builtins  # noqa: F401
from src.composition.song_composer import compose_song
from src.daw_integration.generic.midi_export import MidiExporter
from src.daw_integration.generic.styles import STYLES


class TestScaleRegion(unittest.TestCase):
    def test_scales_only_target_region(self):
        m = MidiExporter(tempo=120)
        m.add_melody("C", "major", bars=8, octave=5, seed=1,
                     progression=["I", "V"], velocity_range=(90, 90))
        m.scale_region_velocity(0, 4, 0.5)   # first 4 bars halved
        bar = m.bar_duration
        early = [n.velocity for n in m.tracks[0].notes if n.start < 4 * bar]
        late = [n.velocity for n in m.tracks[0].notes if n.start >= 4 * bar]
        self.assertTrue(early and late)
        self.assertLess(max(early), min(late))   # scaled region quieter

    def test_drum_factor_independent(self):
        m = MidiExporter(tempo=120)
        m.add_drum_pattern("basic_rock", bars=4, velocity=100)
        m.scale_region_velocity(0, 4, 0.5, drum_factor=1.0)  # drums untouched
        self.assertTrue(all(n.velocity == 100 or n.velocity > 50
                            for n in m.tracks[0].notes))


class TestSectionDynamicsIntegration(unittest.TestCase):
    def test_chorus_louder_than_verse(self):
        genre = "pop_full_song"
        out = compose_song(genre=genre, seed=5, skip_audio=True,
                           enabled_instruments=tuple(STYLES[genre].default_instruments))
        pm = pretty_midi.PrettyMIDI(out["midi_path"])
        bar = 60.0 / STYLES[genre].tempo * 4
        # Section bars from the preset's Full song variant.
        rows = STYLES[genre].rhythm_variants["Full song"]
        verse = next(r for r in rows if r["label"].startswith("Verse"))
        chorus = next(r for r in rows if r["label"].startswith("Chorus"))

        def mean_vel(row):
            lo, hi = row["start_bar"] * bar, (row["end_bar"] + 1) * bar
            vels = [n.velocity for inst in pm.instruments if not inst.is_drum
                    for n in inst.notes if lo <= n.start < hi]
            return sum(vels) / max(1, len(vels))

        self.assertGreater(mean_vel(chorus), mean_vel(verse),
                           "chorus should be louder than verse")


if __name__ == "__main__":
    unittest.main()
