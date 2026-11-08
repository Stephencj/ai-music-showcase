"""Jazz Fusion (Full song): strict fusion techniques, straight time, ranges,
and the sampled-sound routing."""

import os
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pretty_midi

import src.composition  # noqa: F401  (registers the technique bank)
from src.audio_processing.render import sampled
from src.composition.song_composer import compose_song
from src.composition.techniques import BANK
from src.daw_integration.generic.styles import STYLES


def _compose(seed: int = 3):
    td = tempfile.TemporaryDirectory()
    res = compose_song(genre="fusion_full", seed=seed, output_dir=Path(td.name), skip_audio=True)
    pm = pretty_midi.PrettyMIDI(res["midi_path"])
    return td, res, pm


class FusionCompositionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.td, cls.res, cls.pm = _compose()

    @classmethod
    def tearDownClass(cls):
        cls.td.cleanup()

    def test_every_cell_uses_a_fusion_technique(self):
        names = {s["technique"] for s in self.res["selections"]}
        self.assertTrue(names)
        self.assertTrue(all(n.startswith("fusion_") for n in names), names)

    def test_band_and_programs(self):
        by_drum = {i.is_drum: i for i in self.pm.instruments}
        programs = {i.program for i in self.pm.instruments if not i.is_drum}
        self.assertIn(True, by_drum)
        self.assertTrue({4, 33}.issubset(programs), programs)   # Rhodes, finger bass
        self.assertTrue(programs & {64, 65, 66, 67}, programs)    # a sax

    def test_parts_stay_in_their_instruments_ranges(self):
        for inst in self.pm.instruments:
            pitches = [n.pitch for n in inst.notes]
            if inst.is_drum:
                continue
            if inst.program in (32, 33, 34, 35, 36, 37):
                self.assertGreaterEqual(min(pitches), 28)
                self.assertLessEqual(max(pitches), 55)
            elif inst.program in (64, 65, 66, 67):
                self.assertGreaterEqual(min(pitches), 58)
                self.assertLessEqual(max(pitches), 80)

    def test_straight_sixteenths_not_swung(self):
        tempo = STYLES["fusion_full"].tempo
        step = 60.0 / tempo / 4
        drums = next(i for i in self.pm.instruments if i.is_drum)
        offsets = [((n.start / step) - round(n.start / step)) * step for n in drums.notes]
        # Humanised by a few ms, never pushed to a swung 8th (~step/3 late).
        self.assertLess(float(np.percentile(np.abs(offsets), 95)), 0.015)

    def test_seed_is_deterministic(self):
        td, _, pm2 = _compose()
        try:
            a = [(n.pitch, round(n.start, 4)) for i in self.pm.instruments for n in i.notes]
            b = [(n.pitch, round(n.start, 4)) for i in pm2.instruments for n in i.notes]
            self.assertEqual(a, b)
        finally:
            td.cleanup()


class StrictPickTest(unittest.TestCase):
    def test_strict_keeps_only_tagged_candidates(self):
        rng = np.random.default_rng(0)
        for _ in range(50):
            t = BANK.pick("drums", "verse", rng, preferred_tags=("fusion",), strict=True)
            self.assertIn("fusion", t.tags)

    def test_strict_falls_back_when_nothing_is_tagged(self):
        rng = np.random.default_rng(0)
        self.assertIsNotNone(BANK.pick("drums", "verse", rng, preferred_tags=("no_such_tag",), strict=True))


class SampledRoutingTest(unittest.TestCase):
    def test_style_default_and_explicit_choice(self):
        old = os.environ.pop("AI_MUSIC_SOUND", None)
        try:
            self.assertEqual(sampled.resolve_sound(None, "fusion_full"), "sampled")
            self.assertEqual(sampled.resolve_sound(None, "pop_full_song"), "gm")
            self.assertEqual(sampled.resolve_sound("gm", "fusion_full"), "gm")
            self.assertEqual(sampled.resolve_sound(None, None), "gm")
        finally:
            if old is not None:
                os.environ["AI_MUSIC_SOUND"] = old

    def test_track_mapping(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.assertIsNone(sampled.sampled_for(4, False, root))     # not installed
            self.assertEqual(sampled.sampled_for(81, False, root).id, "synth_lead")   # built in
            for inst in sampled.SAMPLED_INSTRUMENTS:
                if inst.engine != "sfz":
                    continue
                p = root / inst.sfz
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text("")
            self.assertEqual(sampled.sampled_for(4, False, root).id, "rhodes")
            self.assertEqual(sampled.sampled_for(33, False, root).id, "electric_bass")
            self.assertIsNone(sampled.sampled_for(38, False, root))    # synth bass stays GM
            self.assertEqual(sampled.sampled_for(0, True, root).id, "drum_kit")
            self.assertEqual(sampled.sampled_for(65, False, root).id, "alto_sax")
            self.assertEqual(sampled.sampled_for(0, False, root).id, "grand_piano")
            self.assertEqual(sampled.sampled_for(32, False, root).id, "upright_bass")
            self.assertIsNone(sampled.sampled_for(24, False, root))    # nylon guitar stays GM

    def test_missing_libraries_fall_back_to_the_soundfont(self):
        from src.daw_integration.generic.midi_export import MidiExporter, NoteEvent
        midi = MidiExporter(tempo=120, time_signature=(4, 4))
        midi.add_notes([NoteEvent(60, 0.0, 0.5, 100)], track_name="Keys", program=4)
        with tempfile.TemporaryDirectory() as td:
            with sampled.SampledRenderer(root=Path(td)) as r:
                stems = r.render_stems(midi).stems
        self.assertEqual([s.name for s in stems], ["Keys"])
        self.assertGreater(float(np.abs(stems[0].audio).max()), 0.0)


if __name__ == "__main__":
    unittest.main()
