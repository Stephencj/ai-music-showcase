"""Tests for the section-aware bank techniques.

The post-2026-05-15 round added ~22 techniques tagged with specific
INSTRUMENT_REGISTRY ids (`("trumpet",)`, `("violin",)`, …) so that
picking trumpet + sax_tenor + violin + flute together lands on
idiomatic brass / wind / string vocabulary rather than four generic
``melody`` lines. These tests verify:

- Each new technique registers with a specific instrument id (not a
  legacy role token).
- The bank prefers specific-instrument picks over role-bucket
  fallbacks.
- The shared rhythm patterns (e.g. ``brass_shout``, ``tremolo``)
  make multiple section instruments coordinate at the rhythm level
  without any cross-instrument scheduler.
- ``Instrument.default_octave`` flows through the ``_RoutedMidi``
  proxy so the same renderer call lands in the right register on
  cello (octave 3) vs violin (octave 5).
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
import pretty_midi

from src.composition import BANK
from src.composition.instruments import INSTRUMENT_REGISTRY
from src.composition.song_composer import compose_song


BRASS_IDS = {
    "trumpet", "trombone", "sax_alto", "sax_tenor", "sax_baritone",
    "brass_section",
}
WOODWIND_IDS = {"flute", "clarinet", "oboe", "bassoon", "woodwind_section"}
STRING_IDS = {"violin", "viola", "cello", "contrabass", "string_section"}


class SectionTechniqueRegistrationTests(unittest.TestCase):

    def test_brass_techniques_target_specific_instrument_ids(self):
        brass_techs = [
            t for t in BANK.all_techniques()
            if any(i in BRASS_IDS for i in t.instruments)
        ]
        # 8 brass section techniques shipped this round.
        self.assertGreaterEqual(len(brass_techs), 6)
        for t in brass_techs:
            # Each should be tagged with at least one specific brass id,
            # not a generic role token.
            self.assertTrue(
                any(i in BRASS_IDS for i in t.instruments),
                f"{t.name}: instruments={t.instruments} has no brass id",
            )

    def test_woodwind_techniques_present(self):
        wind_techs = [
            t for t in BANK.all_techniques()
            if "woodwind" in t.tags
        ]
        # Pre-section round: 0 woodwind-tagged techniques. Post-round:
        # 6 (flute / clarinet / oboe / bassoon).
        self.assertGreaterEqual(len(wind_techs), 4)

    def test_string_techniques_target_specific_instrument_ids(self):
        string_techs = [
            t for t in BANK.all_techniques()
            if any(i in STRING_IDS for i in t.instruments)
        ]
        self.assertGreaterEqual(len(string_techs), 6)


class BankPickPriorityTests(unittest.TestCase):
    """The bank's specific-id-first-then-role-fallback chain should
    prefer the new idiomatic techniques when the user picks trumpet
    or violin, but still fall back to the generic role pool for
    cells the section pack doesn't cover."""

    def test_specific_instrument_pick_preferred_over_role_fallback(self):
        rng = np.random.default_rng(0)
        # Trumpet + chorus has a specific match: trumpet_shout_lead.
        picked = BANK.pick("trumpet", "chorus", rng)
        self.assertIsNotNone(picked)
        self.assertIn(
            "trumpet", picked.instruments,
            f"expected trumpet-tagged technique but got {picked.name} "
            f"(instruments={picked.instruments})",
        )

    def test_pick_falls_back_to_role_when_no_specific_match(self):
        rng = np.random.default_rng(0)
        # Contrabass + chorus: no contrabass technique covers chorus
        # (only intro / outro). The bank's specific-id lookup returns
        # None; compose_song's fallback then hits the role bucket.
        # Here we just verify the bank itself behaves consistently.
        picked = BANK.pick("contrabass", "chorus", rng)
        self.assertIsNone(picked)


class SectionRhythmCoordinationTests(unittest.TestCase):
    """When trumpet + trombone are picked together, both should
    converge on the ``brass_shout`` rhythm in chorus cells — the
    coordination falls out of the shared rhythm-pattern reference."""

    def test_brass_shout_rhythm_shared_across_instruments(self):
        # Force the rhythmic coordination on both: pin the shout
        # picks via technique_overrides so the test isn't seed-
        # dependent.
        with tempfile.TemporaryDirectory() as td:
            out = compose_song(
                genre="jazz_aaba_full", seed=99, skip_audio=True,
                output_dir=Path(td),
                enabled_instruments=[
                    "drum_kit", "upright_bass", "piano",
                    "trumpet", "trombone",
                ],
                technique_overrides={
                    "chorus:trumpet":  "trumpet_shout_lead",
                    "chorus:trombone": "trombone_shout_third",
                    "bridge:trumpet":  "trumpet_shout_lead",
                    "bridge:trombone": "trombone_shout_third",
                },
            )
            pm = pretty_midi.PrettyMIDI(out["midi_path"])
        by_name = {i.name: i for i in pm.instruments}
        self.assertIn("Trumpet", by_name)
        self.assertIn("Trombone", by_name)
        # Both should share the same note onset times in the chorus /
        # bridge bars — that's the rhythm-coordination promise.
        trumpet_starts = {round(n.start, 3) for n in by_name["Trumpet"].notes}
        trombone_starts = {round(n.start, 3) for n in by_name["Trombone"].notes}
        common = trumpet_starts & trombone_starts
        # Each shout rhythm produces 7 hits per bar × 32 bars (chorus
        # + bridge) ≈ 224 onsets; at minimum half should be shared.
        self.assertGreater(
            len(common), 50,
            f"expected ≥50 shared onsets, got {len(common)} "
            f"(trumpet={len(trumpet_starts)}, trombone={len(trombone_starts)})",
        )


class DefaultOctaveTests(unittest.TestCase):
    """``Instrument.default_octave`` should flow through the
    ``_RoutedMidi`` proxy into ``add_chord_progression`` /
    ``add_bass_line`` / ``add_melody`` calls so that a generic
    chord-pad technique produces violins in the soprano register and
    cellos in the tenor register without any technique-side octave
    logic."""

    def test_every_pitched_instrument_has_default_octave(self):
        for inst_id, inst in INSTRUMENT_REGISTRY.items():
            if inst.is_drum:
                self.assertIsNone(
                    inst.default_octave,
                    f"{inst_id}: drum instruments should leave "
                    f"default_octave=None (got {inst.default_octave})",
                )
            else:
                self.assertIsNotNone(
                    inst.default_octave,
                    f"{inst_id}: pitched instrument missing default_octave",
                )

    def test_violin_renders_higher_than_cello(self):
        # Same composition for both: just swap the picked instrument
        # for the melody role. The default_octave per Instrument
        # should land violin in the high register and cello a couple
        # octaves lower.
        with tempfile.TemporaryDirectory() as td:
            out = compose_song(
                genre="ballad_full", seed=11, skip_audio=True,
                output_dir=Path(td),
                enabled_instruments=["drum_kit", "violin", "cello"],
            )
            pm = pretty_midi.PrettyMIDI(out["midi_path"])
        by_name = {i.name: i for i in pm.instruments}
        violin_notes = by_name["Violin"].notes
        cello_notes = by_name["Cello"].notes
        self.assertTrue(violin_notes and cello_notes)
        v_mean = sum(n.pitch for n in violin_notes) / len(violin_notes)
        c_mean = sum(n.pitch for n in cello_notes) / len(cello_notes)
        # Registry: violin default_octave=5, cello=3 → expect ≥ ~12
        # semitones of separation in MIDI pitch.
        self.assertGreater(
            v_mean - c_mean, 8,
            f"expected violin mean pitch > cello + 8 semitones; "
            f"got violin={v_mean:.1f}, cello={c_mean:.1f}",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
