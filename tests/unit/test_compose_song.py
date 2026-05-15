"""End-to-end tests for ``compose_song`` (the TechniqueBank pipeline)."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.composition.song_composer import compose_song


class ComposeSongDefaultTests(unittest.TestCase):

    def test_default_pop_produces_midi(self):
        with tempfile.TemporaryDirectory() as td:
            out = compose_song(
                genre="pop", seed=42, skip_audio=True,
                output_dir=Path(td),
            )
        self.assertTrue(out["midi_path"])
        self.assertTrue(out["selections"])
        self.assertTrue(out["summary"])
        # Defaults: pop's default_bars=8; selections cover at least 4
        # instruments × N sections.
        instruments = {s["instrument"] for s in out["selections"]}
        self.assertEqual(instruments, {"chords", "bass", "melody", "drums"})

    def test_funk_full_song_summary_mentions_sections(self):
        with tempfile.TemporaryDirectory() as td:
            out = compose_song(
                genre="funk_full_song", seed=7, skip_audio=True,
                output_dir=Path(td),
            )
        # The "Full song" rhythm_variant ships 6 named sections.
        unique_sections = {s["section_label"] for s in out["selections"]}
        self.assertGreaterEqual(len(unique_sections), 4)


class SeedBehaviourTests(unittest.TestCase):

    def test_same_seed_same_selections(self):
        with tempfile.TemporaryDirectory() as td:
            a = compose_song(
                genre="pop_full_song", seed=42, skip_audio=True,
                output_dir=Path(td) / "a",
            )
            b = compose_song(
                genre="pop_full_song", seed=42, skip_audio=True,
                output_dir=Path(td) / "b",
            )
        names_a = [s["technique"] for s in a["selections"]]
        names_b = [s["technique"] for s in b["selections"]]
        self.assertEqual(names_a, names_b)

    def test_different_seed_can_differ(self):
        """Two different seeds should pick at least one different
        technique. The bank ships >=2 candidates in many cells, so this
        succeeds in expectation; loop a handful of seed pairs to dodge
        flake."""
        with tempfile.TemporaryDirectory() as td:
            any_diff = False
            base = compose_song(
                genre="pop_full_song", seed=42, skip_audio=True,
                output_dir=Path(td) / "base",
            )
            base_picks = [s["technique"] for s in base["selections"]]
            for offset in (1, 2, 3, 7, 11):
                out = compose_song(
                    genre="pop_full_song", seed=42 + offset, skip_audio=True,
                    output_dir=Path(td) / f"alt_{offset}",
                )
                if [s["technique"] for s in out["selections"]] != base_picks:
                    any_diff = True
                    break
        self.assertTrue(
            any_diff,
            "Bumping the seed by up to 11 produced identical picks — "
            "TechniqueBank coverage may be too thin",
        )


class TechniqueOverridesTests(unittest.TestCase):

    def test_role_override_pins_pick(self):
        with tempfile.TemporaryDirectory() as td:
            out = compose_song(
                genre="pop_full_song", seed=99, skip_audio=True,
                output_dir=Path(td),
                technique_overrides={"verse:bass": "funk_walk"},
            )
        verse_bass = [
            s for s in out["selections"]
            if s["section_role"] == "verse" and s["instrument"] == "bass"
        ]
        self.assertTrue(verse_bass)
        for s in verse_bass:
            self.assertEqual(s["technique"], "funk_walk")


class EnabledInstrumentsTests(unittest.TestCase):
    """``compose_song`` must honour the track-enable filter — disabled
    instruments never get a technique picked."""

    def test_melody_disabled_produces_no_melody_selections(self):
        with tempfile.TemporaryDirectory() as td:
            out = compose_song(
                genre="pop_full_song", seed=42, skip_audio=True,
                output_dir=Path(td),
                enabled_instruments=("chords", "bass", "drums"),
            )
        instruments_used = {s["instrument"] for s in out["selections"]}
        self.assertNotIn("melody", instruments_used)
        self.assertEqual(
            instruments_used, {"chords", "bass", "drums"},
        )

    def test_only_drums_produces_drums_only(self):
        with tempfile.TemporaryDirectory() as td:
            out = compose_song(
                genre="pop_full_song", seed=42, skip_audio=True,
                output_dir=Path(td),
                enabled_instruments=("drums",),
            )
        instruments_used = {s["instrument"] for s in out["selections"]}
        self.assertEqual(instruments_used, {"drums"})

    def test_default_includes_all_instruments(self):
        """Backwards compat: omitting enabled_instruments runs the
        original 4-instrument pipeline."""
        with tempfile.TemporaryDirectory() as td:
            out = compose_song(
                genre="pop_full_song", seed=42, skip_audio=True,
                output_dir=Path(td),
            )
        instruments_used = {s["instrument"] for s in out["selections"]}
        self.assertEqual(
            instruments_used, {"chords", "bass", "melody", "drums"},
        )


class PerInstrumentRoutingTests(unittest.TestCase):
    """When ``enabled_instruments`` carries registry ids (rather than
    legacy role tokens), each enabled instrument must land on its own
    MIDI track at the correct GM patch."""

    def test_specific_instruments_get_their_own_tracks(self):
        import pretty_midi
        with tempfile.TemporaryDirectory() as td:
            out = compose_song(
                genre="jazz_aaba_full", seed=42, skip_audio=True,
                output_dir=Path(td),
                enabled_instruments=[
                    "piano", "upright_bass", "drum_kit",
                    "sax_tenor", "trumpet",
                ],
            )
            pm = pretty_midi.PrettyMIDI(out["midi_path"])
        names = {inst.name for inst in pm.instruments}
        self.assertEqual(
            names,
            {"Piano", "Upright Bass", "Drum kit", "Tenor Sax", "Trumpet"},
        )
        by_name = {inst.name: inst for inst in pm.instruments}
        self.assertEqual(by_name["Piano"].program, 0)
        self.assertEqual(by_name["Upright Bass"].program, 32)
        self.assertTrue(by_name["Drum kit"].is_drum)
        self.assertEqual(by_name["Tenor Sax"].program, 66)
        self.assertEqual(by_name["Trumpet"].program, 56)

    def test_section_composite_collapses_to_one_track(self):
        import pretty_midi
        with tempfile.TemporaryDirectory() as td:
            out = compose_song(
                genre="jazz_aaba_full", seed=42, skip_audio=True,
                output_dir=Path(td),
                enabled_instruments=["drum_kit", "brass_section"],
            )
            pm = pretty_midi.PrettyMIDI(out["midi_path"])
        names = {inst.name for inst in pm.instruments}
        self.assertEqual(names, {"Drum kit", "Brass Section"})
        by_name = {inst.name: inst for inst in pm.instruments}
        self.assertEqual(by_name["Brass Section"].program, 61)

    def test_picking_member_drops_composite(self):
        """Selecting ``brass_section`` AND ``trumpet`` should expand to
        just trumpet — composite is dropped to avoid double-rendering."""
        import pretty_midi
        with tempfile.TemporaryDirectory() as td:
            out = compose_song(
                genre="jazz_aaba_full", seed=42, skip_audio=True,
                output_dir=Path(td),
                enabled_instruments=["drum_kit", "brass_section", "trumpet"],
            )
            pm = pretty_midi.PrettyMIDI(out["midi_path"])
        names = {inst.name for inst in pm.instruments}
        self.assertNotIn("Brass Section", names)
        self.assertIn("Trumpet", names)


class FunkRockPreferredTagsTests(unittest.TestCase):
    """A song composed against a full-song preset should over-weight
    techniques in the bank tagged with that preset key (or a related
    funk_rock tag for the funk-flavoured presets)."""

    def test_funk_full_song_pulls_funk_rock_starter(self):
        with tempfile.TemporaryDirectory() as td:
            out = compose_song(
                genre="funk_full_song", seed=3, skip_audio=True,
                output_dir=Path(td),
            )
        # At least one funk_rock-tagged technique should land somewhere.
        names = {s["technique"] for s in out["selections"]}
        funk_rock_names = {
            "nebulous_intro_chords", "nebulous_intro_bass",
            "funk_rock_verse_chords", "funk_rock_verse_bass",
            "funk_rock_chorus_chords", "funk_rock_chorus_bass",
            "funk_rock_bridge_chords", "funk_rock_bridge_bass",
            "funk_rock_outro_riff_pass", "funk_rock_outro_drums_fade",
        }
        self.assertTrue(
            names & funk_rock_names,
            f"No funk_rock starter techniques selected; picks={names}",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
