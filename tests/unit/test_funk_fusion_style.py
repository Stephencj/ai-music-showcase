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
                  "Synth Lead": (69, 92), "Electric Piano": (48, 80)}
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

    def test_lead_sits_above_the_trumpet(self):
        lead = np.median([n.pitch for n in self.tracks["Synth Lead"].notes])
        tpt = np.median([n.pitch for n in self.tracks["Trumpet"].notes])
        self.assertGreaterEqual(lead - tpt, 7)

    def test_lead_runs_up_into_the_chorus(self):
        verse_end = 12 * self.bar                        # intro 4 + verse 8 in the default song
        run = [n for n in self.tracks["Synth Lead"].notes if verse_end - self.bar - 0.02 <= n.start < verse_end]
        self.assertGreaterEqual(len(run), 6)
        pitches = [n.pitch for n in sorted(run, key=lambda n: n.start)]
        self.assertEqual(pitches, sorted(pitches))
        self.assertGreater(pitches[-1] - pitches[0], 7)
        self.assertLess(max(n.start for n in run), verse_end - self.bar / 16 * 2 + 0.02)

    def test_synth_lead_plays_short(self):
        step = self.bar / 16
        lead = self.tracks["Synth Lead"].notes
        last = max(n.start for n in lead)
        body = [n for n in lead if n.start < last - 0.01]
        self.assertTrue(body)
        self.assertLessEqual(max(n.end - n.start for n in body), 4 * step * 0.82 + 0.015)   # + humanised timing

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
        beat4 = 17 * self.bar + 12 * self.bar / 16 - 0.02
        self.assertTrue(any(n.start < beat4 for n in riff))
        self.assertTrue(all(n.end - n.start < 0.06 for n in riff if n.start >= beat4))   # only the swipe
        pickup = [n for n in self.notes_in("Drum kit", 17) if n.pitch == 38
                  and n.start >= 17 * self.bar + 12 * self.bar / 16 - 0.02]
        self.assertGreaterEqual(len(pickup), 4)
        final = self.notes_in("Synth Lead", 18)
        self.assertEqual([n.pitch % 12 for n in final], [self.tonic_pc])
        # ...after a swipe up the keys over the snare pickup, landing on it.
        swipe = [n for n in self.notes_in("Synth Lead", 17)
                 if n.start >= 17 * self.bar + 12 * self.bar / 16 - 0.02]
        self.assertGreaterEqual(len(swipe), 5)
        self.assertEqual([n.pitch for n in swipe], sorted(n.pitch for n in swipe))
        self.assertLess(final[0].pitch - swipe[-1].pitch, 4)
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
    HITS = (4.891, 7.94, 13.671, 19.748, 99.0)  # 13.671 opens the chorus; the last is past the end

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

    def lead_between(self, a, b):
        return sorted((n for n in self.tracks["Synth Lead"].notes if a - 0.005 <= n.start < b),
                      key=lambda n: n.start)

    def test_lead_swipes_up_into_a_mid_section_downbeat_hit(self):
        hit = self.snapped(self.HITS[3])
        gliss = self.lead_between(hit - 4 * self.step, hit - 0.012)   # a note humanised onto the hit is the landing
        self.assertGreaterEqual(len(gliss), 6)
        pitches = [n.pitch for n in gliss]
        self.assertEqual(pitches, sorted(pitches))
        self.assertLess(max(n.end - n.start for n in gliss), 0.06)      # separate, swiped notes

    def test_lead_rips_down_off_the_sections_opening_hit(self):
        hit = self.snapped(self.HITS[2])
        rip = self.lead_between(hit + 2 * self.step, hit + 6 * self.step)
        self.assertGreaterEqual(len(rip), 6)
        pitches = [n.pitch for n in rip]
        self.assertEqual(pitches, sorted(pitches, reverse=True))
        self.assertGreaterEqual(pitches[0] - pitches[-1], 12)

    def test_hits_past_the_end_are_ignored(self):
        end = max(n.end for t in self.tracks.values() for n in t.notes)
        self.assertLess(end, 30.0)


class LeadPatchTest(unittest.TestCase):
    def test_named_patches_render(self):
        from src.audio_processing.render.sfz import Note as SNote
        from src.audio_processing.render.synth_lead import LEAD_PATCHES, render_lead
        self.assertEqual(set(LEAD_PATCHES), {"punch", "ewi", "layered"})
        for name, patch in LEAD_PATCHES.items():
            out = render_lead([SNote(72, 0.0, 0.4, 100)], 44100, patch=patch)
            self.assertGreater(float(np.abs(out).max()), 0.05, name)
            self.assertFalse(np.isnan(out).any(), name)

    def test_layered_lead_adds_the_trumpet_when_installed(self):
        from src.audio_processing.render.sfz import Note as SNote
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "vsco2-ce").mkdir()
            sf.write(str(root / "vsco2-ce" / "t.wav"),
                     (0.5 * np.sin(2 * np.pi * 220 * np.arange(44100) / 44100)).astype(np.float32), 44100)
            (root / "vsco2-ce" / "trumpet_sus.sfz").write_text("<region> sample=t.wav pitch_keycenter=57")
            notes = [SNote(69, 0.0, 0.5, 100)]
            plain = sampled.SampledRenderer(root=root, lead_patch="punch")._lead(notes, 0)
            layered = sampled.SampledRenderer(root=root, lead_patch="layered")._lead(notes, 0)
            spec = lambda x: np.abs(np.fft.rfft(x.mean(axis=0)[2000:20000]))
            f = np.fft.rfftfreq(18000, 1 / 44100)
            band = (f > 215) & (f < 225)                        # the trumpet an octave below A4
            self.assertGreater(spec(layered)[band].max(), 3 * spec(plain)[band].max())


class LeadVoiceTest(unittest.TestCase):
    def test_voices(self):
        from src.audio_processing.render.lead_voices import LEAD_VOICES, voice
        self.assertTrue({"punch", "sonic", "ewi", "layered", "horns", "trumpet", "guitar",
                         "trumpet_guitar", "guitar_high", "guitar_stack"} <= set(LEAD_VOICES))
        blend = {(l.sfz, l.drive_db > 0) for l in LEAD_VOICES["trumpet_guitar"].layers}
        self.assertEqual(blend, {("trumpet_sus", False), ("guitar_twang", True)})
        self.assertIs(voice("sonic"), voice("punch"))                # the saved synth
        self.assertIs(voice(None), voice("punch"))
        self.assertIs(voice("nope"), voice("punch"))

    def test_fusion_overdrive_saturates_without_turning_to_fuzz(self):
        sr = 44100
        t = np.arange(sr) / sr
        quiet = np.vstack([0.1 * np.sin(2 * np.pi * 220 * t) * np.exp(-2 * t)] * 2).astype(np.float32)
        out = sampled._amp(quiet, 16.0, sr).mean(axis=0)[2000:30000]
        crest = 20 * np.log10(np.abs(out).max() / np.sqrt((out ** 2).mean()))
        spec = np.abs(np.fft.rfft(out * np.hanning(len(out))))
        freqs = np.fft.rfftfreq(len(out), 1 / sr)
        fund = spec[(freqs > 210) & (freqs < 230)].max()
        third = spec[(freqs > 650) & (freqs < 670)].max()
        self.assertGreater(third / fund, 0.05)        # it really distorts, even from a quiet sample
        self.assertGreater(crest, 4.0)                # but isn't squared off into fuzz

    def test_every_voice_register_is_known_to_the_composer(self):
        from src.audio_processing.render.lead_voices import LEAD_VOICES
        from src.composition.funk_fusion import _LEAD_REGISTER, _voice_register
        for name, v in LEAD_VOICES.items():
            self.assertIn(v.register, _LEAD_REGISTER, name)
            self.assertEqual(_voice_register(name), v.register, name)

    def test_octave_layers_fold_back_into_the_instruments_range(self):
        from src.audio_processing.render.lead_voices import LeadLayer
        from src.audio_processing.render.sfz import Note as SNote
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            gdir = root / "karoryfer.black-and-green-guitars" / "Programs"
            gdir.mkdir(parents=True)
            sf.write(str(gdir / "g.wav"), (0.5 * np.sin(2 * np.pi * 440 * np.arange(22050) / 44100)).astype(np.float32), 44100)
            (gdir / "04-green_twang.sfz").write_text("<region> sample=g.wav lokey=40 hikey=86 pitch_keycenter=69")
            r = sampled.SampledRenderer(root=root)
            out = r._lead_layer(LeadLayer("sfz", sfz="guitar_twang", octave=1), [SNote(81, 0.0, 0.3, 100)], 0)
            self.assertIsNotNone(out)                        # 93 is above the top: folds to 81, not silence
            self.assertGreater(float(np.abs(out).max()), 0.05)

    def test_horn_voice_plays_lower_than_the_synth(self):
        def lead_median(voice_name):
            td = tempfile.TemporaryDirectory()
            try:
                res = compose_song(genre=GENRE, sections=build_sections(GENRE, [], None, None), seed=5,
                                   enabled_instruments=tuple(STYLES[GENRE].default_instruments),
                                   lead_voice=voice_name, output_dir=Path(td.name), skip_audio=True)
                pm = pretty_midi.PrettyMIDI(res["midi_path"])
                return float(np.median([n.pitch for i in pm.instruments if i.name == "Synth Lead" for n in i.notes]))
            finally:
                td.cleanup()
        self.assertGreaterEqual(lead_median(None) - lead_median("horns"), 6)
        self.assertLessEqual(lead_median("trumpet"), 76)

    def test_sampled_voice_mixes_its_layers_and_short_notes_use_staccato(self):
        from src.audio_processing.render.sfz import Note as SNote
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "vsco2-ce").mkdir()
            def tone(name, hz):
                sf.write(str(root / "vsco2-ce" / name),
                         (0.5 * np.sin(2 * np.pi * hz * np.arange(44100) / 44100)).astype(np.float32), 44100)
            tone("long.wav", 440.0)
            tone("short.wav", 660.0)                                    # tells the two libraries apart
            (root / "vsco2-ce" / "trumpet_sus.sfz").write_text("<region> sample=long.wav pitch_keycenter=69")
            (root / "vsco2-ce" / "trumpet_stac.sfz").write_text("<region> sample=short.wav pitch_keycenter=69")
            r = sampled.SampledRenderer(root=root, lead_patch="trumpet")
            short = r._lead([SNote(69, 0.0, 0.1, 100)], 0)
            long = r._lead([SNote(69, 0.0, 0.5, 100)], 0)
            def peak_hz(x):
                seg = x.mean(axis=0)[:4000] * np.hanning(4000)
                return float(np.fft.rfftfreq(1 << 16, 1 / 44100)[np.argmax(np.abs(np.fft.rfft(seg, 1 << 16)))])
            self.assertAlmostEqual(peak_hz(short), 660.0, delta=15)
            self.assertAlmostEqual(peak_hz(long), 440.0, delta=15)

    def test_missing_libraries_fall_back_to_the_synth(self):
        from src.audio_processing.render.sfz import Note as SNote
        with tempfile.TemporaryDirectory() as td:
            out = sampled.SampledRenderer(root=Path(td), lead_patch="horns")._lead([SNote(72, 0.0, 0.3, 100)], 0)
            self.assertGreater(float(np.abs(out).max()), 0.05)


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

    def test_lead_gets_the_tight_chain_only_in_this_profile(self):
        from src.audio_processing.render.effects import NAMED_CHAINS
        self.assertEqual(MIX_PROFILES["funk_fusion"].family_chains, {"lead": "tight_lead"})
        board = NAMED_CHAINS["tight_lead"]()
        reverb = [p for p in board if type(p).__name__ == "Reverb"][0]
        self.assertLess(reverb.wet_level, 0.25)
        self.assertFalse(MIX_PROFILES["pop"].family_chains)

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
