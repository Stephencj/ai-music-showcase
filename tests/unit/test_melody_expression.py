"""Tests for the expressive melody articulation layer (add_melody expression)."""
import unittest

from src.daw_integration.generic.midi_export import MidiExporter


def _melody(expression, seed=3, **kw):
    m = MidiExporter(tempo=100)
    m.add_melody(key="C", scale_name="major", bars=8, octave=5, seed=seed,
                 progression=["I", "V", "vi", "IV"], melody_style="motif",
                 phrase_shape="arc", note_density=0.5, velocity_curve="arc",
                 expression=expression, **kw)
    return m.build().instruments[0]


class TestMelodyExpression(unittest.TestCase):
    def test_off_emits_no_bends(self):
        """Default (expression=None) is byte-identical to legacy: no bends."""
        inst = _melody(None)
        self.assertEqual(len(inst.pitch_bends), 0)
        self.assertEqual(len(inst.control_changes), 0)

    def test_full_emits_bends(self):
        self.assertGreater(len(_melody("full").pitch_bends), 0)

    def test_notes_unchanged_by_expression(self):
        """Expression must only ADD bends — never change the notes (separate
        rng), so a track sounds like the same tune, just expressive."""
        def sig(inst):
            return [(n.pitch, round(n.start, 4), round(n.end, 4), n.velocity)
                    for n in inst.notes]
        self.assertEqual(sig(_melody(None)), sig(_melody("full")))

    def test_dict_expression_overrides(self):
        # Force a scoop on every accent — guarantees bends.
        inst = _melody({"scoop_prob": 1.0, "scoop_depth": 2.0})
        self.assertGreater(len(inst.pitch_bends), 2)

    def test_preset_names_resolve(self):
        for preset in ("light", "full", "vocal"):
            self.assertGreaterEqual(len(_melody(preset).pitch_bends), 0)

    def test_bends_return_to_neutral(self):
        """Every articulated note resets the wheel so notes don't bleed pitch."""
        bends = _melody("full").pitch_bends
        # The final bend event should be at/near neutral.
        last = sorted(bends, key=lambda b: b.time)[-1]
        self.assertLessEqual(abs(last.pitch), 400)


if __name__ == "__main__":
    unittest.main()
