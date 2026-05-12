"""Regression tests for the music-theory primitives + melody-quality upgrades.

Covers Track A from the melody-quality plan:

- Catalog shape — every entry parseable, scale degrees in range, etc.
- ``phrase_shape`` produces position-weighted contours (arc rises into peak,
  fall descends monotonically, etc.).
- ``cadence`` forcing snaps the final melody note to the cadence's target
  pitch class regardless of which scale degree the random walker landed on.
- ``motif_development`` injects a step shift on the right block.
- ``harmony_rule="voice_leading_smooth"`` reduces total inter-note motion
  vs. unsmoothed parallel harmonisation.
"""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.daw_integration.generic.midi_export import (
    CADENCES,
    HARMONY_OPS,
    MELODIC_LICKS,
    MOTIF_DEVELOPMENT_OPS,
    MidiExporter,
    NoteEvent,
    PHRASE_CONTOURS,
    PHRASE_FORMS,
    SCALES,
    TENSION_OPS,
    Track,
)


# ---------------------------------------------------------------------------
# Catalog shape
# ---------------------------------------------------------------------------

class CadenceCatalogTests(unittest.TestCase):

    def test_every_cadence_has_required_fields(self):
        for name, spec in CADENCES.items():
            with self.subTest(cadence=name):
                self.assertIn("chords", spec)
                self.assertIn("melody", spec)
                self.assertIn("emotion", spec)
                self.assertEqual(len(spec["melody"]), 2,
                                 "cadence melody tuple should be (penult, final)")
                penult, final = spec["melody"]
                self.assertGreaterEqual(penult, 1)
                self.assertLessEqual(penult, 14)
                self.assertGreaterEqual(final, 1)
                self.assertLessEqual(final, 14)

    def test_chord_list_nonempty(self):
        for name, spec in CADENCES.items():
            self.assertGreaterEqual(len(spec["chords"]), 2,
                                    f"{name} needs at least 2 chords")


class MelodicLicksCatalogTests(unittest.TestCase):

    def test_every_lick_has_events_genre_emotion(self):
        for name, spec in MELODIC_LICKS.items():
            with self.subTest(lick=name):
                self.assertIn("events", spec)
                self.assertIn("genre", spec)
                self.assertIn("emotion", spec)
                self.assertGreater(len(spec["events"]), 0)
                # Each event = (beat_offset, scale_degree, duration)
                for ev in spec["events"]:
                    self.assertEqual(len(ev), 3)
                    beat, deg, dur = ev
                    self.assertGreaterEqual(beat, 0.0)
                    self.assertGreaterEqual(deg, 1)
                    self.assertLessEqual(deg, 14)
                    self.assertGreater(dur, 0.0)


class TensionOpsCatalogTests(unittest.TestCase):

    def test_every_tension_op_has_type_and_description(self):
        for name, spec in TENSION_OPS.items():
            with self.subTest(op=name):
                self.assertIn("type", spec)
                self.assertIn("description", spec)


class PhraseFormsCatalogTests(unittest.TestCase):

    def test_every_form_has_bars_structure_shape(self):
        for name, spec in PHRASE_FORMS.items():
            with self.subTest(form=name):
                self.assertIn("bars", spec)
                self.assertIn("structure", spec)
                self.assertIn("melody_shape", spec)
                self.assertIn(spec["bars"], (4, 6, 8, 16, 32))


class ContourAndDevCatalogsTests(unittest.TestCase):

    def test_phrase_contours_is_nonempty_list(self):
        self.assertIsInstance(PHRASE_CONTOURS, list)
        self.assertIn("arc", PHRASE_CONTOURS)
        self.assertIn("rise", PHRASE_CONTOURS)
        self.assertIn("fall", PHRASE_CONTOURS)

    def test_motif_development_ops_includes_basics(self):
        self.assertIn("repeat", MOTIF_DEVELOPMENT_OPS)
        self.assertIn("sequence_up", MOTIF_DEVELOPMENT_OPS)
        self.assertIn("inversion", MOTIF_DEVELOPMENT_OPS)
        self.assertIn("cadence", MOTIF_DEVELOPMENT_OPS)


class HarmonyOpsCatalogTests(unittest.TestCase):

    def test_voice_leading_smooth_is_present(self):
        self.assertIn("voice_leading_smooth", HARMONY_OPS)
        self.assertIn("description", HARMONY_OPS["voice_leading_smooth"])

    def test_every_harmony_op_has_priority(self):
        for name, spec in HARMONY_OPS.items():
            self.assertIn("priority", spec)
            self.assertIsInstance(spec["priority"], int)


# ---------------------------------------------------------------------------
# Phrase-shape contour
# ---------------------------------------------------------------------------

def _gen_melody(*, phrase_shape, bars=8, seed=42, cadence=None):
    m = MidiExporter(tempo=120, time_signature=(4, 4))
    m.add_melody(
        key="C", scale_name="major", bars=bars, octave=5, seed=seed,
        progression=["I", "V", "vi", "IV"] * (bars // 4),
        melody_style="motif",
        phrase_shape=phrase_shape, cadence=cadence,
    )
    return [n.pitch for n in m.tracks[0].notes]


def _mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


class PhraseContourShapeTests(unittest.TestCase):

    def test_arc_peaks_in_middle(self):
        pitches = _gen_melody(phrase_shape="arc", bars=8)
        n = len(pitches)
        self.assertGreater(n, 8)
        first_q = _mean(pitches[:n // 4])
        mid = _mean(pitches[n // 2: 3 * n // 4])
        # Mid-phrase should be >= first quarter (arc rises into peak).
        self.assertGreaterEqual(mid, first_q,
                                f"arc mid {mid:.1f} should be ≥ first-quarter {first_q:.1f}")

    def test_rise_ends_higher_than_starts(self):
        pitches = _gen_melody(phrase_shape="rise", bars=8)
        first = _mean(pitches[:len(pitches) // 4])
        last = _mean(pitches[3 * len(pitches) // 4:])
        self.assertGreater(last, first,
                           f"rise last-quarter {last:.1f} should be > first {first:.1f}")

    def test_fall_ends_lower_than_starts(self):
        pitches = _gen_melody(phrase_shape="fall", bars=8)
        first = _mean(pitches[:len(pitches) // 4])
        last = _mean(pitches[3 * len(pitches) // 4:])
        self.assertLess(last, first,
                        f"fall last-quarter {last:.1f} should be < first {first:.1f}")


# ---------------------------------------------------------------------------
# Cadence forcing
# ---------------------------------------------------------------------------

class CadenceForcingTests(unittest.TestCase):

    def test_authentic_v_i_lands_on_tonic(self):
        pitches = _gen_melody(
            phrase_shape="arc", bars=8, cadence="authentic_v_i",
        )
        # Last note's pitch class is C (0) since key=C
        self.assertEqual(pitches[-1] % 12, 0)

    def test_plagal_iv_i_lands_on_tonic(self):
        pitches = _gen_melody(
            phrase_shape="rise", bars=4, cadence="plagal_iv_i",
        )
        self.assertEqual(pitches[-1] % 12, 0)

    def test_deceptive_v_vi_lands_on_six(self):
        # vi of C major = A (pitch class 9)
        pitches = _gen_melody(
            phrase_shape="arc", bars=4, cadence="deceptive_v_vi",
        )
        self.assertEqual(pitches[-1] % 12, 9)

    def test_half_cadence_iv_v_lands_on_five(self):
        # V of C major = G (pitch class 7)
        pitches = _gen_melody(
            phrase_shape="arc", bars=4, cadence="half_iv_v",
        )
        self.assertEqual(pitches[-1] % 12, 7)

    def test_no_cadence_does_not_force(self):
        # Without a cadence, the final pitch is wherever the walker landed —
        # we only verify it doesn't crash and we still get notes.
        pitches = _gen_melody(phrase_shape="plateau", bars=4, cadence=None)
        self.assertGreater(len(pitches), 0)


# ---------------------------------------------------------------------------
# Motif development — affects pitch shift on per-block basis
# ---------------------------------------------------------------------------

class MotifDevelopmentTests(unittest.TestCase):

    def test_sequence_up_lifts_pitches(self):
        # Same seed, same progression, but motif development "sequence_up"
        # in the 2nd block should make block-2 average pitch higher than
        # block-1 average.
        m = MidiExporter(tempo=120, time_signature=(4, 4))
        m.add_melody(
            key="C", scale_name="major", bars=4, octave=5, seed=42,
            progression=["I", "I", "I", "I"],
            melody_style="motif",
            phrase_shape="plateau",       # remove phrase-bias confound
            cadence=None,
            motif_development=["repeat", "sequence_up"],
        )
        pitches = [n.pitch for n in m.tracks[0].notes]
        n = len(pitches)
        block1 = _mean(pitches[:n // 2])
        block2 = _mean(pitches[n // 2:])
        self.assertGreater(block2, block1,
                           f"sequence_up should lift block 2 ({block2:.1f}) "
                           f"above block 1 ({block1:.1f})")


# ---------------------------------------------------------------------------
# Voice-leading smoothing
# ---------------------------------------------------------------------------

class HarmonySmoothingTests(unittest.TestCase):

    def _melody_with_leaps(self):
        m = MidiExporter(tempo=120, time_signature=(4, 4))
        mel = Track(name="Melody", program=0)
        # Deliberately wide-leap melody (octave jumps)
        for beat, pitch in enumerate([60, 84, 62, 81, 65, 79, 67, 76]):
            mel.notes.append(
                NoteEvent(pitch, beat * 0.5, (beat + 1) * 0.5, 90),
            )
        m.tracks.append(mel)
        return m

    def _harm_leaps(self, rule):
        m = self._melody_with_leaps()
        m.add_harmony(
            source_track="Melody", style="follow",
            key="C", scale_name="major", progression=["I", "V"],
            harmony_rule=rule,
        )
        harm = next(t for t in m.tracks if "Harm" in t.name)
        return [abs(harm.notes[i + 1].pitch - harm.notes[i].pitch)
                for i in range(len(harm.notes) - 1)]

    def test_smoothing_reduces_total_motion(self):
        smoothed = self._harm_leaps("voice_leading_smooth")
        raw = self._harm_leaps(None)
        self.assertLess(sum(smoothed), sum(raw),
                        f"smoothed total {sum(smoothed)} should be < raw {sum(raw)}")

    def test_smoothing_caps_max_leap(self):
        smoothed = self._harm_leaps("voice_leading_smooth")
        # On a wide-leap melody we can't always stay within 2 semitones
        # (no chord tone exists there), but we should never exceed half
        # the unsmoothed max.
        raw = self._harm_leaps(None)
        self.assertLess(max(smoothed), max(raw) / 2 + 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
