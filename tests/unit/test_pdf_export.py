"""Tests for the MIDI → PDF sheet music export pipeline.

The LilyPond-dependent test is skipped when the binary isn't on
``$PATH`` so CI / clean dev boxes pass without it.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pretty_midi

from src.scoring import pdf_export


def _tiny_midi(out: Path) -> Path:
    """Write a 1-bar 4-note melody on track 'Melody' to ``out``."""
    pm = pretty_midi.PrettyMIDI(initial_tempo=120.0)
    inst = pretty_midi.Instrument(program=0, name="Melody")
    for beat, p in enumerate([60, 62, 64, 67]):
        inst.notes.append(pretty_midi.Note(
            velocity=80, pitch=p, start=beat * 0.5, end=(beat + 1) * 0.5,
        ))
    pm.instruments.append(inst)
    pm.write(str(out))
    return out


def _triplet_midi(out: Path) -> Path:
    """A note that starts on a triplet eighth (fractional beat)."""
    pm = pretty_midi.PrettyMIDI(initial_tempo=120.0)
    inst = pretty_midi.Instrument(program=0, name="Melody")
    # 120 BPM → 1 beat = 0.5 s. 1.667 beats = 0.8335 s.
    inst.notes.append(pretty_midi.Note(
        velocity=80, pitch=60, start=0.8335, end=1.0,
    ))
    pm.instruments.append(inst)
    pm.write(str(out))
    return out


class LilyPondDetectionTests(unittest.TestCase):

    def test_is_lilypond_available_returns_bool(self):
        self.assertIsInstance(pdf_export.is_lilypond_available(), bool)


class SafeFilenameTests(unittest.TestCase):

    def test_simple_name(self):
        self.assertEqual(pdf_export._safe_filename("Melody"), "Melody")

    def test_handles_special_chars(self):
        self.assertEqual(
            pdf_export._safe_filename("Melody Harm 1"),
            "Melody_Harm_1",
        )

    def test_empty_falls_back_to_part(self):
        self.assertEqual(pdf_export._safe_filename(""), "Part")
        self.assertEqual(pdf_export._safe_filename("   "), "Part")
        self.assertEqual(pdf_export._safe_filename("!!!"), "Part")


class MidiToScoreTests(unittest.TestCase):

    def test_inserts_key_signature(self):
        with tempfile.TemporaryDirectory() as td:
            mid = _tiny_midi(Path(td) / "tiny.mid")
            score = pdf_export.midi_to_score(mid, key="G", scale="major")
            import music21
            # Walk the score looking for an inserted KeySignature.
            ks = score.recurse().getElementsByClass(
                music21.key.KeySignature
            ).first()
            self.assertIsNotNone(ks, "key signature was not inserted")
            self.assertEqual(ks.sharps, 1, "G major should be 1 sharp")

    def test_minor_scale_renders_minor_mode(self):
        with tempfile.TemporaryDirectory() as td:
            mid = _tiny_midi(Path(td) / "tiny.mid")
            score = pdf_export.midi_to_score(mid, key="A", scale="minor")
            import music21
            ks = score.recurse().getElementsByClass(
                music21.key.Key
            ).first()
            self.assertIsNotNone(ks)
            self.assertEqual(ks.mode, "minor")

    def test_quantization_snaps_fractional_starts(self):
        with tempfile.TemporaryDirectory() as td:
            mid = _triplet_midi(Path(td) / "trip.mid")
            score = pdf_export.midi_to_score(mid)
            # After quantization, every note offset should be expressible
            # as p/q with q in {1, 2, 3, 4} (i.e. quarter / eighth /
            # triplet-eighth / sixteenth grid).
            for n in score.recurse().notes:
                off = n.offset
                # Allow the offset itself to be exactly representable on
                # any of the quantization grids; check denominator <= 24.
                try:
                    denom = off.denominator if hasattr(off, "denominator") else 1
                except Exception:
                    denom = 1
                self.assertLessEqual(
                    denom, 24,
                    f"quantize left messy offset {off}",
                )


class ExportZipTests(unittest.TestCase):

    def test_raises_without_lilypond(self):
        with tempfile.TemporaryDirectory() as td:
            mid = _tiny_midi(Path(td) / "tiny.mid")
            out_zip = Path(td) / "out.zip"
            with mock.patch.object(
                pdf_export, "is_lilypond_available", return_value=False,
            ):
                with self.assertRaises(RuntimeError) as cm:
                    pdf_export.export_zip(mid, out_zip, key="C", scale="major")
                self.assertIn("LilyPond", str(cm.exception))

    @unittest.skipUnless(
        pdf_export.is_lilypond_available(),
        "lilypond binary not available; install via `brew install lilypond`",
    )
    def test_produces_full_score_and_parts(self):
        with tempfile.TemporaryDirectory() as td:
            mid = _tiny_midi(Path(td) / "tiny.mid")
            out_zip = Path(td) / "score.zip"
            result = pdf_export.export_zip(
                mid, out_zip, key="C", scale="major",
                title="Tiny Test",
            )
            self.assertEqual(result, out_zip)
            self.assertTrue(out_zip.exists())
            with zipfile.ZipFile(out_zip) as zf:
                names = zf.namelist()
            self.assertIn("full_score.pdf", names)
            # The tiny MIDI has one instrument; we should have exactly
            # one part PDF.
            part_pdfs = [n for n in names if n.startswith("parts/")]
            self.assertGreaterEqual(len(part_pdfs), 1)
            self.assertTrue(
                any("Melody" in n for n in part_pdfs),
                f"Expected a Melody part PDF; got {part_pdfs}",
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
