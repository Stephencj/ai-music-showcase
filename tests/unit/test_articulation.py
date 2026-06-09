"""Tests for the pitch-bend / vibrato articulation layer on MidiExporter.

These are data-level tests (no FluidSynth) — a separate render spike
confirmed FluidSynth honours the emitted pretty_midi pitch_bends.
"""
import unittest

from src.daw_integration.generic.midi_export import (
    BendEvent,
    MidiExporter,
)


def _bends_of(pm, inst_index=0):
    return pm.instruments[inst_index].pitch_bends


class TestArticulation(unittest.TestCase):
    def test_half_bend_endpoints(self):
        """A 0->1 semitone bend (within the +/-2 default range) ends near +4096."""
        m = MidiExporter(tempo=120)
        m.add_articulated_note("Lead", pitch=60, start=0.0, dur=1.0,
                               program=29, bend=(0.0, 1.0), reset_after=False)
        pm = m.build()
        bends = _bends_of(pm)
        self.assertGreater(len(bends), 2)
        # range = 2 st -> 1 st == half deflection == 4096.
        peak = max(b.pitch for b in bends)
        self.assertAlmostEqual(peak, 4096, delta=40)
        # starts at ~0.
        first = min(bends, key=lambda b: b.time)
        self.assertAlmostEqual(first.pitch, 0, delta=40)

    def test_whole_bend_hits_full_deflection(self):
        """A 0->2 semitone bend reaches the +/-2 range's full +8191."""
        m = MidiExporter(tempo=120)
        m.add_articulated_note("Lead", pitch=60, start=0.0, dur=1.0,
                               program=29, bend=(0.0, 2.0), reset_after=False)
        pm = m.build()
        peak = max(b.pitch for b in _bends_of(pm))
        self.assertGreaterEqual(peak, 8000)
        self.assertLessEqual(peak, 8191)

    def test_oversized_bend_widens_range_via_rpn(self):
        """A 3-semitone bend must widen the range (RPN) so it doesn't clip."""
        m = MidiExporter(tempo=120)
        m.add_articulated_note("Lead", pitch=60, start=0.0, dur=1.0,
                               program=29, bend=(0.0, 3.0), reset_after=False)
        pm = m.build()
        ccs = pm.instruments[0].control_changes
        # RPN pitch-bend-sensitivity setup present: CC101=0, CC100=0, CC6=range.
        cc_nums = {(c.number, c.value) for c in ccs}
        self.assertIn((101, 0), cc_nums)
        self.assertIn((100, 0), cc_nums)
        self.assertTrue(any(c.number == 6 and c.value >= 3 for c in ccs))
        # 3 st of a 3-st range == full deflection, not clipped below.
        peak = max(b.pitch for b in _bends_of(pm))
        self.assertGreaterEqual(peak, 8000)

    def test_prebend_vs_bend_release_differ_in_order(self):
        """Pre-bend starts high and releases; bend-up starts low and rises."""
        up = MidiExporter(tempo=120)
        up.add_articulated_note("L", 60, 0.0, 1.0, bend=(0.0, 2.0), reset_after=False)
        up_b = sorted(_bends_of(up.build()), key=lambda b: b.time)

        pre = MidiExporter(tempo=120)
        pre.add_articulated_note("L", 60, 0.0, 1.0, bend=(2.0, 0.0), reset_after=False)
        pre_b = sorted(_bends_of(pre.build()), key=lambda b: b.time)

        self.assertLess(up_b[0].pitch, up_b[-1].pitch)    # rises
        self.assertGreater(pre_b[0].pitch, pre_b[-1].pitch)  # releases

    def test_vibrato_oscillates_around_zero(self):
        m = MidiExporter(tempo=120)
        m.add_articulated_note("L", 60, 0.0, 1.5, program=29,
                               vibrato={"depth_st": 0.4, "rate_hz": 6.0})
        vals = [b.pitch for b in _bends_of(m.build())]
        self.assertGreater(len(vals), 4)
        self.assertGreater(max(vals), 100)   # swings up
        self.assertLess(min(vals), -100)     # and down

    def test_reset_after_returns_wheel_to_zero(self):
        m = MidiExporter(tempo=120)
        m.add_articulated_note("L", 60, 0.0, 1.0, bend=(0.0, 2.0), reset_after=True)
        bends = sorted(_bends_of(m.build()), key=lambda b: b.time)
        self.assertAlmostEqual(bends[-1].pitch, 0, delta=40)

    def test_bends_preserved_on_per_track_stem(self):
        """iter_single_track_pms (the render path) must carry bends through."""
        m = MidiExporter(tempo=120)
        m.add_articulated_note("Lead", 60, 0.0, 1.0, program=29, bend=(0.0, 1.0))
        m.add_chord_progression("C", ["I", "V"], bars=2)
        stems = dict(m.iter_single_track_pms())
        self.assertIn("Lead", stems)
        self.assertGreater(len(stems["Lead"].instruments[0].pitch_bends), 2)
        # A plain chord track has no bends.
        self.assertEqual(len(stems["Chords"].instruments[0].pitch_bends), 0)

    def test_plain_notes_emit_no_bends(self):
        """Non-articulated tracks must be byte-for-byte unchanged (no bends/ccs)."""
        m = MidiExporter(tempo=120)
        m.add_melody("C", "pentatonic_minor", bars=2, octave=5)
        inst = m.build().instruments[0]
        self.assertEqual(len(inst.pitch_bends), 0)
        self.assertEqual(len(inst.control_changes), 0)


if __name__ == "__main__":
    unittest.main()
