"""Funk Fusion (Full song): the band riff, horn parts, ranges, mix, brass maps."""

import importlib.util
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pretty_midi
import soundfile as sf

import src.composition  # noqa: F401  (registers the technique bank)
from src.api.arrangement import build_sections
from src.audio_processing.render import sampled
from src.audio_processing.render.pipeline import _with_profile_tracks
from src.audio_processing.render.profiles import MIX_PROFILES, resolve_profile
from src.composition.song_composer import compose_song
from src.daw_integration.generic.midi_export import MidiExporter, NoteEvent
from src.daw_integration.generic.styles import STYLES

GENRE = "funk_fusion_full"


def _compose(seed=5):
    td = tempfile.TemporaryDirectory()
    preset = STYLES[GENRE]
    res = compose_song(genre=GENRE, sections=build_sections(GENRE, [], None, None), seed=seed,
                       enabled_instruments=tuple(preset.default_instruments),
                       output_dir=Path(td.name), skip_audio=True)
    return td, res, pretty_midi.PrettyMIDI(res["midi_path"])


class FunkFusionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.td, cls.res, cls.pm = _compose()
        cls.tracks = {i.name: i for i in cls.pm.instruments}
        cls.bar = 4 * 60.0 / STYLES[GENRE].tempo

    @classmethod
    def tearDownClass(cls):
        cls.td.cleanup()

    def test_every_part_plays_its_own_funk_fusion_pattern(self):
        names = {s["technique"] for s in self.res["selections"]}
        self.assertTrue(all(n.startswith("funk_fusion_") for n in names), names)
        played = {s["instrument"] for s in self.res["selections"]}
        self.assertEqual(played, set(STYLES[GENRE].default_instruments))

    def test_tracks_and_ranges(self):
        self.assertEqual(set(self.tracks), {"Drum kit", "Electric Bass", "Electric Piano",
                                            "Trumpet", "Trombone", "Synth Lead"})
        ranges = {"Electric Bass": (28, 55), "Trumpet": (55, 84), "Trombone": (40, 72),
                  "Synth Lead": (58, 86), "Electric Piano": (48, 80)}
        for name, (lo, hi) in ranges.items():
            pitches = [n.pitch for n in self.tracks[name].notes]
            self.assertGreaterEqual(min(pitches), lo, name)
            self.assertLessEqual(max(pitches), hi, name)

    def test_intro_is_drums_building_into_the_band_riff(self):
        intro_end = 4 * self.bar
        riff_start = 3 * self.bar - 0.02
        for name, track in self.tracks.items():
            early = [n for n in track.notes if n.start < riff_start]
            if name == "Drum kit":
                build = [n for n in early if 2 * self.bar - 0.02 <= n.start]
                self.assertTrue(any(n.pitch in (45, 47, 50) for n in build))   # tom build
            else:
                self.assertFalse(early, name)
            self.assertTrue(any(riff_start <= n.start < intro_end for n in track.notes), name)

        def onsets(name):
            return {round(n.start / (self.bar / 16)) for n in self.tracks[name].notes if n.start < intro_end}

        bass, sax, trumpet = onsets("Electric Bass"), onsets("Synth Lead"), onsets("Trumpet")
        self.assertGreater(len(bass & sax) / len(sax), 0.8)        # bass and sax play it together
        self.assertGreater(len(trumpet & sax) / len(sax), 0.8)

    def test_trumpet_sits_above_trombone(self):
        tpt = np.median([n.pitch for n in self.tracks["Trumpet"].notes])
        tbn = np.median([n.pitch for n in self.tracks["Trombone"].notes])
        self.assertGreater(tpt, tbn)

    def test_seed_changes_the_riff(self):
        td, _, pm2 = _compose(seed=12)
        try:
            a = [n.pitch for n in self.tracks["Synth Lead"].notes[:12]]
            b = [n.pitch for n in {i.name: i for i in pm2.instruments}["Synth Lead"].notes[:12]]
            self.assertNotEqual(a, b)
        finally:
            td.cleanup()


class OneBarRiffTest(unittest.TestCase):
    """A tight 30 s cut: 1-bar riff intro, 1-bar turnaround, riff + hit ending."""

    @classmethod
    def setUpClass(cls):
        cls.td = tempfile.TemporaryDirectory()
        secs = build_sections(GENRE, ["intro", "verse", "chorus", "outro"], None,
                              {"intro": {"bars": 1}, "verse": {"bars": 8},
                               "chorus": {"bars": 8}, "outro": {"bars": 2}})
        res = compose_song(genre=GENRE, sections=secs, seed=5, tempo=152,
                           enabled_instruments=tuple(STYLES[GENRE].default_instruments),
                           output_dir=Path(cls.td.name), skip_audio=True)
        cls.tracks = {i.name: i for i in pretty_midi.PrettyMIDI(res["midi_path"]).instruments}
        cls.bar = 4 * 60.0 / 152
        cls.tonic_pc = 3                                   # Eb

    @classmethod
    def tearDownClass(cls):
        cls.td.cleanup()

    def notes_in(self, name, bar):
        return [n for n in self.tracks[name].notes
                if bar * self.bar - 0.02 <= n.start < (bar + 1) * self.bar - 0.02]

    def test_layout_is_nineteen_bars(self):
        end = max(n.end for t in self.tracks.values() for n in t.notes)
        self.assertLess(end, 19 * self.bar + 0.5)
        self.assertTrue(self.notes_in("Drum kit", 18))

    def test_riff_moments_are_one_bar_and_resolve(self):
        # Bar 16 (the chorus's last) is the turnaround, bar 17 the outro riff:
        # bass and sax together, the sax ending on the tonic.
        # Bar 16 (the chorus's last) is the turnaround: bass and lead together,
        # the lead ending on the tonic.
        lead = self.notes_in("Synth Lead", 16)
        bass = {round(n.start / (self.bar / 16)) for n in self.notes_in("Electric Bass", 16)}
        self.assertTrue(lead)
        self.assertGreater(len({round(n.start / (self.bar / 16)) for n in lead} & bass) / len(lead), 0.8)
        self.assertEqual(lead[-1].pitch % 12, self.tonic_pc)
        # Bar 17, the ending riff, stops before beat 4 (the drums pick up) and
        # the lead resolves to the tonic on the final hit.
        riff = self.notes_in("Synth Lead", 17)
        self.assertTrue(riff)
        self.assertTrue(all(n.start < 17 * self.bar + 12 * self.bar / 16 - 0.02 for n in riff))
        pickup = [n for n in self.notes_in("Drum kit", 17) if n.pitch == 38
                  and n.start >= 17 * self.bar + 12 * self.bar / 16 - 0.02]
        self.assertGreaterEqual(len(pickup), 4)
        final = self.notes_in("Synth Lead", 18)
        self.assertEqual([n.pitch % 12 for n in final], [self.tonic_pc])
        # The trumpet plays the riff as one line but stabs in two-note chords,
        # so only bars 16 and 17 of the chorus/outro are riff bars.
        def stacked(bar):
            onsets = [round(n.start / (self.bar / 16)) for n in self.notes_in("Trumpet", bar)]
            return any(onsets.count(o) > 1 for o in onsets)
        self.assertTrue(stacked(15) or stacked(14))
        self.assertFalse(stacked(16))
        self.assertFalse(stacked(17))

    def test_final_bar_is_one_band_hit(self):
        hit = 18 * self.bar
        for name, track in self.tracks.items():
            late = [n for n in track.notes if n.start >= hit - 0.02]
            self.assertTrue(all(abs(n.start - hit) < 0.03 for n in late), name)


class HitPointTest(unittest.TestCase):
    """Accents at given times (e.g. a stab on each caption of a video)."""

    TEMPO = 158
    HITS = (4.891, 7.94, 13.671, 99.0)          # the last is past the song's end

    @classmethod
    def setUpClass(cls):
        cls.td = tempfile.TemporaryDirectory()
        secs = build_sections(GENRE, ["intro", "verse", "chorus", "outro"], None,
                              {"intro": {"bars": 3}, "verse": {"bars": 6},
                               "chorus": {"bars": 8}, "outro": {"bars": 2}})
        res = compose_song(genre=GENRE, sections=secs, seed=5, tempo=cls.TEMPO, hits=list(cls.HITS),
                           enabled_instruments=tuple(STYLES[GENRE].default_instruments),
                           output_dir=Path(cls.td.name), skip_audio=True)
        cls.tracks = {i.name: i for i in pretty_midi.PrettyMIDI(res["midi_path"]).instruments}
        cls.step = 60.0 / cls.TEMPO / 4

    @classmethod
    def tearDownClass(cls):
        cls.td.cleanup()

    def snapped(self, t):
        return round(t / self.step) * self.step

    def at(self, name, t, tol=0.012):
        return [n for n in self.tracks[name].notes if abs(n.start - t) <= tol]

    def test_band_lands_each_hit_on_the_nearest_sixteenth(self):
        for t in self.HITS[:3]:
            hit = self.snapped(t)
            self.assertLessEqual(abs(hit - t), self.step / 2)
            self.assertGreaterEqual(len(self.at("Trumpet", hit)), 2, t)
            self.assertGreaterEqual(len(self.at("Trombone", hit)), 2, t)
            self.assertIn(49, {n.pitch for n in self.at("Drum kit", hit)}, t)       # crash
            self.assertTrue(self.at("Electric Piano", hit), t)

    def test_other_stabs_keep_clear_of_a_hit(self):
        hit = self.snapped(self.HITS[1])
        near = [n for n in self.tracks["Trumpet"].notes
                if 0.012 < abs(n.start - hit) <= 3 * self.step]
        self.assertFalse(near)

    def test_band_breathes_before_a_downbeat_hit(self):
        hit = self.snapped(self.HITS[2])                      # 13.671 s = bar 9's downbeat
        for name, track in self.tracks.items():
            early = [n for n in track.notes if hit - 2 * self.step - 0.004 <= n.start < hit - 0.012]
            self.assertFalse(early, name)
            gap = hit - 2 * self.step
            ringing = [n for n in track.notes if n.start < gap and n.end > gap + 0.002]
            self.assertFalse(ringing, name)

    def test_hits_past_the_end_are_ignored(self):
        end = max(n.end for t in self.tracks.values() for n in t.notes)
        self.assertLess(end, 30.0)


class FunkMixTest(unittest.TestCase):
    def test_profile_resolves_and_sets_the_sax_level(self):
        profile = resolve_profile(GENRE)
        self.assertIs(profile, MIX_PROFILES["funk_fusion"])
        midi = MidiExporter(tempo=140, time_signature=(4, 4))
        for name, prog in (("Alto Sax", 65), ("Trumpet", 56), ("Electric Piano", 4)):
            midi.add_notes([NoteEvent(60, 0, 1, 100)], track_name=name, program=prog)
        mix = _with_profile_tracks({"Trumpet": {"pan": -0.5}}, profile, midi)
        self.assertEqual(mix["Alto Sax"]["gain_db"], -3.5)
        self.assertEqual(mix["Trumpet"]["pan"], -0.5)                  # the producer's choice wins
        self.assertNotIn("Electric Piano", mix)

    def test_no_overrides_leaves_track_mix_alone(self):
        midi = MidiExporter(tempo=120, time_signature=(4, 4))
        self.assertIsNone(_with_profile_tracks(None, MIX_PROFILES["pop"], midi))


class BrassMappingTest(unittest.TestCase):
    def test_brass_programs_map_to_the_horn_libraries(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for inst in sampled.SAMPLED_INSTRUMENTS:
                if inst.engine != "sfz":
                    continue
                p = root / inst.sfz
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text("")
            self.assertEqual(sampled.sampled_for(61, False, root).id, "horn_section")
            self.assertEqual(sampled.sampled_for(56, False, root).id, "trumpet")
            self.assertEqual(sampled.sampled_for(57, False, root).id, "trombone")
            self.assertIsNone(sampled.sampled_for(62, False, root))    # synth brass stays GM

    def test_make_brass_sfz_maps_names_an_octave_up(self):
        spec = importlib.util.spec_from_file_location(
            "make_brass_sfz", Path(__file__).resolve().parents[2] / "scripts/setup/make_brass_sfz.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            for folder, prefix in (("Trumpet/stac", "Sum_SHTrumpet_stac"),
                                   ("Tenor Trombone/stac", "tenortbn_stac")):
                d = base / "Brass" / folder
                d.mkdir(parents=True)
                for note in ("A3", "C4"):
                    for v in (1, 2):
                        sf.write(str(d / f"{prefix}_{note}_v{v}_rr1.wav"), np.zeros(10, dtype=np.float32), 44100)
            mod.main(str(base))
            text = (base / "trumpet_stac.sfz").read_text()
            self.assertIn("pitch_keycenter=69", text)          # file "A3" sounds as A4
            self.assertIn("pitch_keycenter=72", text)
            self.assertIn("lovel=1 hivel=63", text)
            self.assertIn("lovel=64 hivel=127", text)
            horns = (base / "horns_stac.sfz").read_text()
            self.assertIn("Tenor Trombone/stac", horns)
            self.assertIn("Trumpet/stac", horns)
            self.assertFalse((base / "trombone_sus.sfz").exists())   # nothing to map, no file


if __name__ == "__main__":
    unittest.main()
