"""Re-renders of saved MIDI (block previews, mix previews, live stems, part
audio) sound like the generation: the block's style picks the sampled
instruments, lead voice and mix. Also: notes outside a sampled instrument's
range fold into it instead of going silent, and one GM program can pick a
library by the track's role."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np
import pretty_midi
import soundfile as sf

from src.audio_processing.render import pipeline, sampled
from src.audio_processing.render.sfz import Note, load_sfz
from src.daw_integration.generic import blocks


def _pm():
    pm = pretty_midi.PrettyMIDI()
    inst = pretty_midi.Instrument(program=82, name="Synth Lead Melody")
    inst.notes.append(pretty_midi.Note(velocity=90, pitch=72, start=0.0, end=1.0))
    pm.instruments.append(inst)
    return pm


class StyleRenderArgsTest(unittest.TestCase):
    def test_no_genre_is_the_plain_render(self):
        self.assertEqual(pipeline.style_render_args(None), {"master_preset": "default"})
        self.assertEqual(pipeline.style_render_args({"seed": 1}, "loud"), {"master_preset": "loud"})

    def test_christmas_gets_its_style_lead_and_gentle_master(self):
        args = pipeline.style_render_args({"genre": "christmas_pop_full"})
        self.assertEqual(args["style_name"], "christmas_pop_full")
        self.assertEqual(args["lead_patch"], "guitar_clean")
        self.assertIsNone(args["master_preset"])            # the profile's "transparent"
        self.assertEqual(pipeline.style_lufs({"genre": "christmas_pop_full"}), -16.0)
        # An explicit master and a saved lead voice win.
        args = pipeline.style_render_args({"genre": "christmas_pop_full", "lead_patch": "trumpet"}, "loud")
        self.assertEqual((args["lead_patch"], args["master_preset"]), ("trumpet", "loud"))

    def test_other_styles_keep_their_master(self):
        args = pipeline.style_render_args({"genre": "funk_fusion_full"})
        self.assertEqual(args, {"style_name": "funk_fusion_full", "master_preset": "default"})
        self.assertIsNone(pipeline.style_lufs({"genre": "funk_fusion_full"}))


class BlockPreviewRendersInStyleTest(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.dir = Path(td.name)
        p = mock.patch.object(blocks, "BLOCKS_DIR", self.dir / "blocks")
        p.start()
        self.addCleanup(p.stop)

    def _fake_render(self, calls):
        def render(midi, output_dir, **kw):
            calls.append(kw)
            out = Path(output_dir)
            out.mkdir(parents=True, exist_ok=True)
            t = np.arange(44100) / 44100
            tone = (0.3 * np.sin(2 * np.pi * 440 * t)).astype("float32")
            sf.write(out / "mix.wav", np.stack([tone, tone], axis=1), 44100)
            return SimpleNamespace(mix_path=out / "mix.wav")
        return render

    def test_save_and_rerender_use_the_block_spec(self):
        calls = []
        with mock.patch.object(pipeline, "render_to_audio", self._fake_render(calls)):
            blocks.save_block("Carol", _pm(), tempo=100, time_signature=(4, 4), bars=1,
                              spec={"genre": "christmas_pop_full"})
            self.assertIsNotNone(blocks.rerender_block_wav("Carol"))
        self.assertEqual(len(calls), 2)
        for kw in calls:
            self.assertEqual(kw["style_name"], "christmas_pop_full")
            self.assertEqual(kw["lead_patch"], "guitar_clean")
        self.assertEqual(blocks.block_spec("Carol"), {"genre": "christmas_pop_full"})

    def test_block_without_spec_renders_plain(self):
        calls = []
        with mock.patch.object(pipeline, "render_to_audio", self._fake_render(calls)):
            blocks.save_block("Plain", _pm(), tempo=100, time_signature=(4, 4), bars=1)
        self.assertNotIn("style_name", calls[0])
        self.assertIsNone(blocks.block_spec("Plain"))


class RangeFoldTest(unittest.TestCase):
    def _sfz(self, lo, hi):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        root = Path(td.name)
        sf.write(root / "s.wav", np.zeros((100, 2), dtype="float32"), 44100)
        (root / "i.sfz").write_text(f"<region> sample=s.wav lokey={lo} hikey={hi} pitch_keycenter={lo}\n")
        return load_sfz(root / "i.sfz")

    def test_notes_above_and_below_fold_by_octaves(self):
        inst = self._sfz(49, 80)                        # an alto sax's sounding range
        notes = [Note(83, 0, 1, 80), Note(60, 1, 2, 80), Note(40, 2, 3, 80), Note(97, 3, 4, 80)]
        self.assertEqual([n.pitch for n in sampled.fold_into_range(notes, inst)], [71, 60, 52, 73])


class NameRoutingTest(unittest.TestCase):
    def test_role_picks_a_library_for_one_program(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for spec in sampled.SAMPLED_INSTRUMENTS:
                if spec.sfz:
                    (root / spec.sfz).parent.mkdir(parents=True, exist_ok=True)
                    (root / spec.sfz).write_text("")
            self.assertEqual(sampled.sampled_for(19, False, root, "Organ Pedal Bass").id, "organ_pedal")
            self.assertEqual(sampled.sampled_for(19, False, root, "Organ (Church)").id, "church_organ")
            self.assertEqual(sampled.sampled_for(66, False, root, "Tenor Sax Melody").id, "tenor_sax_melody")
            self.assertEqual(sampled.sampled_for(66, False, root, "Tenor Sax").id, "tenor_sax")
            self.assertEqual(sampled.sampled_for(65, False, root, "Alto Sax Melody").id, "alto_sax")
            (root / "vcsl-extra/tenor_sax_nv.sfz").unlink()
            (root / "vcsl-extra/tenor_sax_vib.sfz").unlink()
            self.assertEqual(sampled.sampled_for(66, False, root, "Tenor Sax").id, "alto_sax")


if __name__ == "__main__":
    unittest.main()
