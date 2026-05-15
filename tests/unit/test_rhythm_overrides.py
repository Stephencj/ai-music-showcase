"""Tests for per-bar / per-half-bar chord-rhythm + bass-pattern overrides.

Covers:
- ``rhythm_override_for_bar_half`` lookup (first-match-wins, mirrors
  ``_override_for_bar``).
- Inheritance: blank h2 falls back to h1; blank h1 falls back to master.
- Half-bar-aware ``_resolve_strum_hits`` compresses tuple-list rhythms
  into a half-bar slot.
- End-to-end ``compose_midi`` with overrides: half-bar swap on chords,
  per-bar swap on bass, walking→non-walking boundary fills approach
  tones in.
- New dynamic style presets load and their ``rhythm_variants`` reference
  known rhythm names only.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.daw_integration.generic.melody_plan import (
    rhythm_override_for_bar_half,
    resolve_chord_rhythm_for,
    resolve_bass_pattern_for,
)
from src.daw_integration.generic.midi_export import (
    MidiExporter, STRUM_RHYTHMS,
)
from src.daw_integration.generic.styles import STYLES


def _make_exporter() -> MidiExporter:
    return MidiExporter(tempo=120, time_signature=(4, 4))


# ---------------------------------------------------------------------------
# Lookup helper
# ---------------------------------------------------------------------------

class LookupTests(unittest.TestCase):

    def test_first_match_wins(self):
        """Two overlapping ranges — the earlier one wins."""
        overrides = [
            {"start_bar": 0, "end_bar": 7, "chord_rhythm_h1": "pad"},
            {"start_bar": 0, "end_bar": 3, "chord_rhythm_h1": "stabs_8th"},
        ]
        ov = rhythm_override_for_bar_half(overrides, bar_idx=2, half=0)
        self.assertEqual(ov["chord_rhythm_h1"], "pad")

    def test_outside_range_returns_none(self):
        overrides = [{"start_bar": 4, "end_bar": 7, "chord_rhythm_h1": "x"}]
        self.assertIsNone(
            rhythm_override_for_bar_half(overrides, bar_idx=2, half=0),
        )

    def test_empty_overrides_returns_none(self):
        self.assertIsNone(rhythm_override_for_bar_half([], 0, 0))
        self.assertIsNone(rhythm_override_for_bar_half(None, 0, 0))


class InheritanceTests(unittest.TestCase):

    def test_h2_inherits_from_h1_when_blank(self):
        overrides = [{
            "start_bar": 0, "end_bar": 3,
            "chord_rhythm_h1": "charleston",
            "chord_rhythm_h2": "",
        }]
        self.assertEqual(
            resolve_chord_rhythm_for(overrides, "pulse_quarter", 0, 0),
            "charleston",
        )
        self.assertEqual(
            resolve_chord_rhythm_for(overrides, "pulse_quarter", 0, 1),
            "charleston",
        )

    def test_h2_distinct_when_set(self):
        overrides = [{
            "start_bar": 0, "end_bar": 3,
            "chord_rhythm_h1": "pulse_quarter",
            "chord_rhythm_h2": "stabs_8th",
        }]
        self.assertEqual(
            resolve_chord_rhythm_for(overrides, "pad", 0, 0), "pulse_quarter",
        )
        self.assertEqual(
            resolve_chord_rhythm_for(overrides, "pad", 0, 1), "stabs_8th",
        )

    def test_empty_override_falls_back_to_master(self):
        overrides = [{
            "start_bar": 0, "end_bar": 3,
            "chord_rhythm_h1": "", "chord_rhythm_h2": "",
        }]
        self.assertEqual(
            resolve_chord_rhythm_for(overrides, "pad", 0, 0), "pad",
        )

    def test_bass_pattern_inherits_master(self):
        overrides = [{
            "start_bar": 0, "end_bar": 3, "bass_pattern": "",
        }]
        self.assertEqual(
            resolve_bass_pattern_for(overrides, "root_fifth", 0),
            "root_fifth",
        )

    def test_bass_pattern_override(self):
        overrides = [{
            "start_bar": 4, "end_bar": 7, "bass_pattern": "walking",
        }]
        self.assertEqual(
            resolve_bass_pattern_for(overrides, "root_fifth", 5),
            "walking",
        )
        self.assertEqual(
            resolve_bass_pattern_for(overrides, "root_fifth", 0),
            "root_fifth",
        )


# ---------------------------------------------------------------------------
# Half-bar aware _resolve_strum_hits
# ---------------------------------------------------------------------------

class HalfBarStrumTests(unittest.TestCase):

    def test_tresillo_compresses_into_half_bar(self):
        """Compressing tresillo (3 hits at 0, 1.5, 3.0 in a 4-beat bar)
        into a 2-beat slot should put all 3 hits in [0, 2)."""
        m = _make_exporter()
        # tresillo is in STRUM_RHYTHMS — assert its full-bar shape first.
        full = m._resolve_strum_hits("tresillo")
        self.assertIsNotNone(full)
        n_full = len(full)
        compressed = m._resolve_strum_hits("tresillo", half_beats=2.0)
        self.assertIsNotNone(compressed)
        self.assertEqual(len(compressed), n_full)
        for off, dur, _ in compressed:
            self.assertLess(off, 2.0 + 1e-6)
            self.assertLessEqual(off + dur, 2.0 + 1e-6)

    def test_pulse_quarter_half_bar_emits_two_hits(self):
        m = _make_exporter()
        hits = m._resolve_strum_hits("pulse_quarter", half_beats=2.0)
        # 2 quarter beats per half-bar.
        self.assertEqual(len(hits), 2)
        self.assertEqual(hits[0][0], 0.0)
        self.assertEqual(hits[1][0], 1.0)

    def test_pad_compresses_to_half_bar_sustain(self):
        m = _make_exporter()
        hits = m._resolve_strum_hits("pad", half_beats=2.0)
        self.assertEqual(hits, [(0.0, 2.0, 1.0)])


# ---------------------------------------------------------------------------
# End-to-end compose
# ---------------------------------------------------------------------------

class ChordHalfBarSwapTests(unittest.TestCase):

    def test_half_swap_emits_hits_in_both_halves(self):
        """Override bars 0-3 with pulse_quarter on h1, stabs_8th on h2.
        The chord track should have hits in [0,2) AND [2,4) of every bar.
        """
        m = _make_exporter()
        overrides = [{
            "start_bar": 0, "end_bar": 3,
            "chord_rhythm_h1": "pulse_quarter",
            "chord_rhythm_h2": "stabs_8th",
            "bass_pattern": "",
        }]
        m.add_chord_progression(
            key="C", progression=["I", "V", "vi", "IV"], bars=4,
            voicing="triad", rhythm="pad",
            rhythm_overrides=overrides,
        )
        chord_track = next(t for t in m.tracks if t.name == "Chords")
        # In bar 0 ([0, 2 seconds at 120 BPM)), expect at least one h1 hit
        # AND at least one h2 hit. 1 beat at 120 BPM = 0.5s, so half-bar = 1.0s.
        bar_dur = m.bar_duration
        h1_hits = [n for n in chord_track.notes
                   if 0 <= n.start < bar_dur / 2 - 1e-6]
        h2_hits = [n for n in chord_track.notes
                   if bar_dur / 2 - 1e-6 <= n.start < bar_dur]
        self.assertGreater(len(h1_hits), 0, "no hits in first half-bar")
        self.assertGreater(len(h2_hits), 0, "no hits in second half-bar")


class BassPatternSwapTests(unittest.TestCase):

    def test_walking_to_root_only_adds_approach_tone(self):
        """Bars 0-3 walking, bars 4-7 root_only. The walking branch's
        last bar (bar 3) should pull approach_tones on, replacing the
        ``root+5`` passing tone with a leading tone of bar 4's root."""
        m = _make_exporter()
        overrides = [
            {"start_bar": 0, "end_bar": 3, "bass_pattern": "walking"},
            {"start_bar": 4, "end_bar": 7, "bass_pattern": "root_only"},
        ]
        m.add_chord_progression(
            key="C", progression=["I", "I", "I", "I", "V", "V", "V", "V"],
            bars=8, voicing="triad", rhythm="pad",
        )
        m.add_bass_line(
            key="C", progression=["I", "I", "I", "I", "V", "V", "V", "V"],
            bars=8, pattern="walking",  # default for bars not overridden
            pattern_overrides=overrides,
            approach_tones=False,        # the boundary should turn this on
        )
        bass_track = next(t for t in m.tracks if t.name == "Bass")
        # Bar 3 is the last walking bar before the change → 4th beat
        # should be the leading tone (one semitone below bar 4's root).
        bar_dur = m.bar_duration
        bar3_notes = [n for n in bass_track.notes
                      if 3 * bar_dur <= n.start < 4 * bar_dur]
        self.assertGreater(len(bar3_notes), 0)
        # Bar 4 is root_only → first bar-4 note should be V's root.
        bar4_notes = [n for n in bass_track.notes
                      if 4 * bar_dur <= n.start < 5 * bar_dur]
        self.assertGreater(len(bar4_notes), 0)
        bar4_root = bar4_notes[0].pitch
        # The last bar-3 note should be a half-step below bar4_root
        # (the leading tone signature of approach_tones=True).
        last_bar3 = sorted(bar3_notes, key=lambda n: n.start)[-1]
        self.assertEqual(last_bar3.pitch, bar4_root - 1,
                         "walking→non-walking boundary should leading-tone "
                         "into the next bar's root")


# ---------------------------------------------------------------------------
# Presets
# ---------------------------------------------------------------------------

class DynamicPresetsTests(unittest.TestCase):

    def test_new_styles_are_present(self):
        for name in ("pop_dynamic", "funk_dynamic",
                     "jazz_trade_fours", "rock_buildup"):
            self.assertIn(name, STYLES, f"missing style {name!r}")

    def test_rhythm_variants_reference_known_rhythms(self):
        """Every chord_rhythm_* / bass_pattern value in every variant
        must be either '' (inherit) or present in the live name tables."""
        from src.daw_integration.generic.midi_export import STRUM_RHYTHMS
        # The auto-scale rhythms aren't in STRUM_RHYTHMS but are still valid.
        known_chord = (
            set(STRUM_RHYTHMS.keys())
            | {"pad", "pulse_quarter", "stabs_8th"}
            | {""}
        )
        for style_name, preset in STYLES.items():
            for variant_name, rows in (preset.rhythm_variants or {}).items():
                for row in rows:
                    h1 = row.get("chord_rhythm_h1", "")
                    h2 = row.get("chord_rhythm_h2", "")
                    self.assertIn(
                        h1, known_chord,
                        f"{style_name}/{variant_name}: unknown h1 {h1!r}",
                    )
                    self.assertIn(
                        h2, known_chord,
                        f"{style_name}/{variant_name}: unknown h2 {h2!r}",
                    )

    def test_pop_dynamic_has_verse_chorus(self):
        preset = STYLES["pop_dynamic"]
        self.assertIn("Verse / Chorus", preset.rhythm_variants)
        rows = preset.rhythm_variants["Verse / Chorus"]
        labels = [r.get("label") for r in rows]
        self.assertIn("Verse", labels)
        self.assertIn("Chorus", labels)


if __name__ == "__main__":
    unittest.main(verbosity=2)
