"""Per-style idiom variants — verify each StylePreset's optional
``chord_variant`` / ``bass_variant`` / ``melody_variant`` dicts flow
through compose_midi and audibly change the generated MIDI for the
genres they're declared on.

Phase 2 covers the wiring: variant dict → generator kwarg → MIDI
output. Phase 1 already locked the generator behaviors themselves
(approach tones, common-tone voice leading, etc.).
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import app
from src.daw_integration.generic.styles import STYLES


def _reset_state():
    app._state.clear()
    app._state.update({
        "ai_wav_path": None, "midi_wav_path": None,
        "midi_path": None, "model": None,
    })


def _compose(style: str):
    _reset_state()
    app.compose_midi(
        style=style, key="C", scale="major", tempo=120, time_sig="4/4",
        bars=4, enable_chords=True, enable_bass=True, enable_melody=True,
        enable_drums=False, bass_pattern="walking_swing",
        drum_pattern="basic_rock", voicing="triad", swing=0.0,
        chord_rhythm="pad", melody_style="motif", seed=42,
        progression_text="I V vi IV", extras=None,
        chord_octave=3, bass_octave=3, melody_octave=5,
        drum_grid_state=None, random_variation=False,
    )
    import pretty_midi
    return pretty_midi.PrettyMIDI(app._state["midi_path"])


class StylePresetVariantShapeTests(unittest.TestCase):
    """The 6 styles we curated should carry variant kwargs; the rest
    keep their defaults (None). This guards against accidental
    deletion of the variants in future preset edits."""

    EXPECTED_WITH_VARIANTS = {"pop", "funk", "jazz_fusion", "country", "bossa_nova"}

    def test_curated_styles_have_variants(self):
        for name in self.EXPECTED_WITH_VARIANTS:
            preset = STYLES[name]
            has_any = any([
                preset.chord_variant,
                preset.bass_variant,
                preset.melody_variant,
            ])
            self.assertTrue(
                has_any,
                f"{name} should have at least one variant declared",
            )

    def test_jazz_fusion_enables_approach_tones(self):
        v = STYLES["jazz_fusion"].bass_variant or {}
        self.assertTrue(v.get("approach_tones"))

    def test_country_uses_rise_contour(self):
        v = STYLES["country"].melody_variant or {}
        self.assertEqual(v.get("phrase_shape"), "rise")

    def test_metal_keeps_fresh_voicings(self):
        """Metal's chunky parallel power chords are intentional —
        no common-tone smoothing variant."""
        self.assertIsNone(STYLES["metal"].chord_variant)


class StyleVariantDispatchTests(unittest.TestCase):
    """End-to-end through compose_midi: jazz_fusion's bass approach
    tones produce different MIDI than the same progression in pop
    (which doesn't enable approach tones)."""

    def _bass_4th_beat_pitch_class(self, pm):
        """Return the pitch class of the 4th-beat bass note in bar 0.
        Uses 120 BPM 4/4 timing → 2s per bar, 0.5s per beat."""
        for inst in pm.instruments:
            if "bass" in (inst.name or "").lower():
                hits = sorted(
                    (n for n in inst.notes
                     if 1.45 < n.start < 1.6),
                    key=lambda n: n.start,
                )
                if hits:
                    return hits[0].pitch % 12
        return None

    def test_jazz_bass_4th_beat_differs_from_pop(self):
        """Jazz fusion → approach tones on. Pop → off (different
        chord_variant, no bass_variant)."""
        pm_jazz = _compose("jazz_fusion")
        pm_pop = _compose("pop")
        jazz_pc = self._bass_4th_beat_pitch_class(pm_jazz)
        pop_pc = self._bass_4th_beat_pitch_class(pm_pop)
        # Both styles should produce 4th-beat hits given walking_swing.
        # The pitch class should differ because jazz uses leading-tone
        # to next chord (V→G = pc 7, leading tone = F# pc 6) while pop
        # keeps within-chord passing tone (root + 5 = F pc 5).
        self.assertIsNotNone(jazz_pc)
        self.assertIsNotNone(pop_pc)
        # We don't pin to specific pcs (depends on bass_pattern), but
        # we DO assert they differ. If they match, the variant didn't
        # apply.
        self.assertNotEqual(
            jazz_pc, pop_pc,
            f"jazz approach tone should differ from pop's plain pass "
            f"(both got pc={jazz_pc})",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
