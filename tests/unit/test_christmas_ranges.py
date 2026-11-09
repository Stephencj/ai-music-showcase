"""Every Christmas part stays inside what its instrument can play
(christmas.PLAYABLE): the melody by its octave, other parts folded. The
audit found the swing style's alto sax melody at MIDI 85 (the alto tops out
at Ab5, 80)."""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pretty_midi  # noqa: E402

from src.composition import christmas  # noqa: E402
from src.composition.carols import CAROLS  # noqa: E402
from src.composition.instruments import INSTRUMENT_REGISTRY  # noqa: E402
from src.composition.song_composer import compose_song  # noqa: E402
from src.daw_integration.generic.styles import STYLES  # noqa: E402

PERCUSSION = {"Sleigh Bells", "Shaker", christmas.COUNT_IN_TRACK}


def _track_instruments() -> dict[str, str]:
    """Track name → instrument id, for every track the Christmas parts write."""
    out = {"Organ": "organ_church", "Organ Pedal Bass": "organ_church"}
    for inst in christmas.PLAYABLE:
        obj = INSTRUMENT_REGISTRY.get(inst)
        label = getattr(obj, "label", None) or inst.replace("_", " ").title()
        for name in (inst.replace("_", " ").title(), label, f"{label} Melody", f"Guide Melody ({label})"):
            out.setdefault(name, inst)
    return out


def compose(genre, tune, key=None, seed=5, arrangement="", length=60):
    band = christmas.band_for(list(STYLES[genre].default_instruments), arrangement)
    plan = christmas.plan_song(genre, seed=seed, tune=tune, key=key, length_seconds=length,
                               arrangement=arrangement, instruments=band)
    d = tempfile.mkdtemp(prefix="xmas_range_")
    try:
        out = compose_song(genre=genre, sections=plan["sections"], seed=seed, key=plan["key"], scale=plan["scale"],
                           tempo=plan["tempo"], time_signature=plan["time_signature"], arrangement=arrangement,
                           enabled_instruments=tuple(band), output_dir=Path(d), skip_audio=True)
        return pretty_midi.PrettyMIDI(out["midi_path"])
    finally:
        shutil.rmtree(d, ignore_errors=True)


class PartRangeTests(unittest.TestCase):

    def assert_in_range(self, pm, what):
        names = _track_instruments()
        for tr in pm.instruments:
            if tr.is_drum or tr.name in PERCUSSION or not tr.notes:
                continue
            self.assertIn(tr.name, names, f"{what}: no range known for track {tr.name!r}")
            lo, hi = christmas.PLAYABLE[names[tr.name]]
            bad = sorted({n.pitch for n in tr.notes if not lo <= n.pitch <= hi})
            self.assertFalse(bad, f"{what}: {tr.name} plays {bad} outside {lo}-{hi}")

    def test_every_style_and_carol_in_its_keys(self):
        for genre in christmas.STYLE_IDS:
            keys = christmas.STYLE_DEFAULTS[christmas.substyle(genre)]["keys"]
            for i, tune in enumerate(CAROLS + ("original",)):
                key = keys[i % len(keys)]
                with self.subTest(genre=genre, tune=tune, key=key):
                    arr = "sleigh_bells,choir_pad,celesta_ending,key_change" if i % 2 else ""
                    self.assert_in_range(compose(genre, tune, key=key, seed=3 + i, arrangement=arr),
                                         f"{genre} {tune} in {key}")

    def test_swing_alto_sax_melody_tops_out_at_ab5(self):
        for key in ("F", "Bb", "Eb", "G", "A", "B", "C", "D", "E"):
            with self.subTest(key=key):
                pm = compose("christmas_swing_full", "jingle_bells", key=key, length=150,
                             arrangement="key_change")
                alto = [n.pitch for t in pm.instruments if t.name.startswith("Alto Sax") for n in t.notes]
                self.assertTrue(alto)
                self.assertLessEqual(max(alto), 80)
                self.assertGreaterEqual(min(alto), 49)

    def test_orchestral_lead_stays_singable(self):
        """The calm styles' flute and violins keep the tune at or under E6
        (88): originals in C, D or Eb used to put it an octave up, to C7."""
        for i, key in enumerate(("C", "D", "Eb", "F", "G", "Bb")):
            for seed in (1, 2, 4, 6):
                arr = "key_change" if (i + seed) % 2 else ""
                with self.subTest(key=key, seed=seed, arrangement=arr):
                    pm = compose("christmas_orchestral_full", "original", key=key, seed=seed, arrangement=arr)
                    lead = [n.pitch for t in pm.instruments if t.name.endswith("Melody")
                            and t.name.split()[0] in ("Flute", "Violin", "String") for n in t.notes]
                    self.assertTrue(lead)
                    self.assertLessEqual(max(lead), christmas._COMFORT_TOP["flute"])

    def test_fold(self):
        from src.daw_integration.generic.midi_export import NoteEvent
        notes = christmas.in_range([NoteEvent(85, 0, 1, 80), NoteEvent(70, 1, 2, 80), NoteEvent(40, 2, 3, 80)],
                                   "sax_alto")
        self.assertEqual([n.pitch for n in notes], [73, 70, 52])


if __name__ == "__main__":
    unittest.main()
