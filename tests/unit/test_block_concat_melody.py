"""Regression tests for the melody-plan override in block_concat.

When a saved block has a sibling ``{name}_melody.yaml``, the rendered
song must use the plan's melody (not the block's stored MIDI melody).
Harmony tags in the plan should appear as an additional Harmony track.
Plans for one block must not affect other blocks in the same timeline.
"""

import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pretty_midi

from src.daw_integration.generic import block_concat
from src.daw_integration.generic import blocks as block_store
from src.daw_integration.generic import melody_plan as mp


def _save_simple_block(name: str, *, melody_pitch: int = 60) -> None:
    """Write a minimal block (Chords + Melody) to BLOCKS_DIR. The melody
    is a single-pitch line — tests can later swap it via a sibling plan
    and verify the swap landed."""
    pm = pretty_midi.PrettyMIDI(initial_tempo=120.0)
    pm.time_signature_changes.append(pretty_midi.TimeSignature(4, 4, 0.0))

    chords = pretty_midi.Instrument(program=0, is_drum=False, name="Chords")
    chords.notes.append(pretty_midi.Note(80, 48, 0.0, 1.0))   # C3
    chords.notes.append(pretty_midi.Note(80, 52, 0.0, 1.0))   # E3
    chords.notes.append(pretty_midi.Note(80, 55, 0.0, 1.0))   # G3
    pm.instruments.append(chords)

    melody = pretty_midi.Instrument(program=0, is_drum=False, name="Melody")
    for beat in range(4):
        melody.notes.append(pretty_midi.Note(
            90, melody_pitch, beat * 0.5, (beat + 1) * 0.5,
        ))
    pm.instruments.append(melody)

    block_store.save_block(
        name=name, pm=pm, tempo=120.0, time_signature=(4, 4),
        bars=1, overwrite=True, write_wav=False,
    )


def _block_yaml(name: str) -> Path:
    return block_store.BLOCKS_DIR / f"{block_store._safe_name(name)}.yaml"


def _block_mid(name: str) -> Path:
    return block_store.BLOCKS_DIR / f"{block_store._safe_name(name)}.mid"


def _block_plan_yaml(name: str) -> Path:
    return block_store.BLOCKS_DIR / f"{block_store._safe_name(name)}_melody.yaml"


class ConcatMelodyPlanTests(unittest.TestCase):

    def setUp(self):
        # Use unique names so we don't clobber the user's real blocks
        self.block_a = "_test_concat_plan_a"
        self.block_b = "_test_concat_plan_b"
        _save_simple_block(self.block_a, melody_pitch=60)   # C4
        _save_simple_block(self.block_b, melody_pitch=64)   # E4

    def tearDown(self):
        for n in (self.block_a, self.block_b):
            for path in (_block_yaml(n), _block_mid(n), _block_plan_yaml(n)):
                if path.exists():
                    path.unlink()

    def _melody_pitches(self, pm: pretty_midi.PrettyMIDI) -> list[int]:
        mel = next(
            (i for i in pm.instruments
             if not i.is_drum and "melody" in (i.name or "").lower()),
            None,
        )
        return sorted(n.pitch for n in mel.notes) if mel else []

    def _harmony_pitches(self, pm: pretty_midi.PrettyMIDI) -> list[int]:
        harm = next(
            (i for i in pm.instruments
             if not i.is_drum and "harmony" in (i.name or "").lower()),
            None,
        )
        return sorted(n.pitch for n in harm.notes) if harm else []

    def test_no_plan_uses_stored_melody(self):
        out_pm, info = block_concat.concat_blocks([
            {"block_name": self.block_a, "repeat": 1},
        ])
        # block_a's stored melody is all-C4 (pitch 60)
        self.assertEqual(set(self._melody_pitches(out_pm)), {60})
        self.assertNotIn("🎵", info["summary"])

    def test_sibling_plan_replaces_melody(self):
        # Write a plan that uses E4 (64) and G4 (67) instead of the stored C4
        plan = mp.MelodyPlan(
            bars=1, time_signature=(4, 4), key="C", scale="major", tempo=120,
            notes=[
                mp.MelodyNote(bar=0, beat=0.0, pitch=64, duration=2.0),
                mp.MelodyNote(bar=0, beat=2.0, pitch=67, duration=2.0),
            ],
        )
        mp.to_yaml(plan, _block_plan_yaml(self.block_a))

        out_pm, info = block_concat.concat_blocks([
            {"block_name": self.block_a, "repeat": 1},
        ])
        # Stored 60 is gone; plan's 64 and 67 are present
        pitches = set(self._melody_pitches(out_pm))
        self.assertNotIn(60, pitches, "stored melody should be replaced")
        self.assertEqual(pitches, {64, 67})
        # Info summary marks the plan was applied
        self.assertIn("🎵", info["summary"])

    def test_plan_for_one_block_only(self):
        # Plan attached to block_a; block_b stays untouched
        plan = mp.MelodyPlan(
            bars=1, time_signature=(4, 4), key="C", scale="major", tempo=120,
            notes=[mp.MelodyNote(bar=0, beat=0.0, pitch=72, duration=2.0)],
        )
        mp.to_yaml(plan, _block_plan_yaml(self.block_a))

        out_pm, info = block_concat.concat_blocks([
            {"block_name": self.block_a, "repeat": 1},
            {"block_name": self.block_b, "repeat": 1},
        ])
        pitches = set(self._melody_pitches(out_pm))
        # block_a → plan (72); block_b → stored (64)
        self.assertIn(72, pitches)
        self.assertIn(64, pitches)
        self.assertNotIn(60, pitches, "block_a's stored melody was replaced")

    def test_plan_with_harmony_tag_appends_harmony_track(self):
        plan = mp.MelodyPlan(
            bars=1, time_signature=(4, 4), key="C", scale="major", tempo=120,
            notes=[
                mp.MelodyNote(bar=0, beat=0.0, pitch=60, duration=1.0),
                mp.MelodyNote(bar=0, beat=1.0, pitch=64, duration=1.0),
                mp.MelodyNote(bar=0, beat=2.0, pitch=67, duration=1.0),
                mp.MelodyNote(bar=0, beat=3.0, pitch=72, duration=1.0),
            ],
            harmonies=[
                mp.HarmonyTag(start_bar=0, end_bar=1, preset="queen"),
            ],
        )
        mp.to_yaml(plan, _block_plan_yaml(self.block_a))

        out_pm, _ = block_concat.concat_blocks([
            {"block_name": self.block_a, "repeat": 1},
        ])
        # Harmony track should be present (Queen preset adds notes above melody)
        harm = self._harmony_pitches(out_pm)
        self.assertGreater(len(harm), 0,
                           "harmony tag should produce a Harmony track")

    def test_broken_plan_falls_back_to_stored_melody(self):
        # Write a syntactically valid but semantically broken plan
        bad_path = _block_plan_yaml(self.block_a)
        bad_path.write_text("not: a valid plan\nbars: not_a_number\n")

        # concat shouldn't raise; it should fall back to the stored melody
        out_pm, info = block_concat.concat_blocks([
            {"block_name": self.block_a, "repeat": 1},
        ])
        # Stored melody (all 60) is intact
        self.assertEqual(set(self._melody_pitches(out_pm)), {60})
        self.assertNotIn("🎵", info["summary"])


class ApplyHelperTests(unittest.TestCase):

    def test_apply_keeps_non_melody_instruments(self):
        # Build a block with three tracks; only "Melody" should be replaced
        pm = pretty_midi.PrettyMIDI(initial_tempo=120.0)
        pm.time_signature_changes.append(pretty_midi.TimeSignature(4, 4, 0.0))
        for name in ("Chords", "Bass", "Melody"):
            inst = pretty_midi.Instrument(program=0, is_drum=False, name=name)
            inst.notes.append(pretty_midi.Note(80, 60, 0.0, 1.0))
            pm.instruments.append(inst)

        plan = mp.MelodyPlan(
            bars=1, time_signature=(4, 4), key="C", scale="major", tempo=120,
            notes=[mp.MelodyNote(bar=0, beat=0.0, pitch=72, duration=1.0)],
        )

        new_pm = block_concat._apply_melody_plan_to_block(pm, plan)
        names = sorted(i.name for i in new_pm.instruments)
        self.assertIn("Chords", names)
        self.assertIn("Bass", names)
        self.assertIn("Melody", names)
        mel = next(i for i in new_pm.instruments if i.name == "Melody")
        # Replaced — pitch is now 72 from the plan, not 60 from the block
        self.assertEqual(mel.notes[0].pitch, 72)
        # And the OTHER tracks are untouched
        bass = next(i for i in new_pm.instruments if i.name == "Bass")
        self.assertEqual(bass.notes[0].pitch, 60)


if __name__ == "__main__":
    unittest.main(verbosity=2)
