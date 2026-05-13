"""Tests for the Playback tab — source listing, MIDI base64 transport,
note-click formatting, HTML scaffold."""

from __future__ import annotations

import base64
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pretty_midi

import app
from src.playback.playback_html import build_playback_html


def _tiny_midi(out: Path) -> Path:
    pm = pretty_midi.PrettyMIDI(initial_tempo=120.0)
    inst = pretty_midi.Instrument(program=0, name="Melody")
    for beat, p in enumerate([60, 62, 64, 67]):
        inst.notes.append(pretty_midi.Note(
            velocity=80, pitch=p, start=beat * 0.5, end=(beat + 1) * 0.5,
        ))
    pm.instruments.append(inst)
    pm.write(str(out))
    return out


class ListPlaybackSourcesTests(unittest.TestCase):

    def setUp(self):
        self.prior_state = dict(app._state)

    def tearDown(self):
        app._state.clear()
        app._state.update(self.prior_state)

    def test_compose_appears_when_state_has_midi_path(self):
        with tempfile.TemporaryDirectory() as td:
            mid = _tiny_midi(Path(td) / "x.mid")
            app._state["midi_path"] = mid
            with mock.patch.object(
                app.block_store, "list_blocks", return_value=[],
            ):
                sources = app._list_playback_sources()
        labels = [s[0] for s in sources]
        ids = [s[1] for s in sources]
        self.assertIn("Latest compose", labels)
        self.assertIn("compose", ids)

    def test_each_block_appears_in_choices(self):
        app._state["midi_path"] = None
        fake_blocks = [{"name": "verse"}, {"name": "chorus"}]
        with mock.patch.object(
            app.block_store, "list_blocks", return_value=fake_blocks,
        ):
            sources = app._list_playback_sources()
        ids = [s[1] for s in sources]
        self.assertIn("block:verse", ids)
        self.assertIn("block:chorus", ids)

    def test_compose_missing_when_no_midi_path(self):
        """When neither a recent compose nor a saved song exists, the
        dropdown should be empty."""
        app._state["midi_path"] = None
        with mock.patch.object(
            app.block_store, "list_blocks", return_value=[],
        ), mock.patch.object(
            Path, "exists", return_value=False,
        ):
            sources = app._list_playback_sources()
        # No compose, no blocks, no song → empty.
        labels = [s[0] for s in sources]
        self.assertNotIn("Latest compose", labels)


class ReadMidiB64Tests(unittest.TestCase):

    def test_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            mid = _tiny_midi(Path(td) / "x.mid")
            b64 = app._read_midi_b64(mid)
            self.assertGreater(len(b64), 0)
            decoded = base64.b64decode(b64)
            self.assertEqual(decoded, mid.read_bytes())


class LoadMidiForPlaybackTests(unittest.TestCase):

    def setUp(self):
        self.prior_state = dict(app._state)

    def tearDown(self):
        app._state.clear()
        app._state.update(self.prior_state)

    def test_compose_returns_b64(self):
        with tempfile.TemporaryDirectory() as td:
            mid = _tiny_midi(Path(td) / "x.mid")
            app._state["midi_path"] = mid
            b64 = app._load_midi_for_playback("compose")
            self.assertGreater(len(b64), 100)
            self.assertEqual(base64.b64decode(b64), mid.read_bytes())

    def test_unknown_source_returns_empty(self):
        self.assertEqual(app._load_midi_for_playback("nonsense"), "")
        self.assertEqual(app._load_midi_for_playback(""), "")


class OnNoteEventTests(unittest.TestCase):

    def test_formats_pitch_duration_bar_beat(self):
        payload = json.dumps({
            "pitch": "G4", "midi": 67,
            "durQuarters": 0.5, "barIdx": 2, "beatIdx": 1.5,
            "trackName": "Melody",
        })
        out = app._on_playback_note_event(payload)
        self.assertIn("G4", out)
        self.assertIn("8th", out)
        self.assertIn("bar 3", out)
        # 1.5 + 1.0 = 2.5
        self.assertIn("beat 2.5", out)
        self.assertIn("Melody", out)

    def test_synthesizes_pitch_from_midi_number(self):
        payload = json.dumps({"midi": 60, "durQuarters": 1.0,
                              "barIdx": 0, "beatIdx": 0})
        out = app._on_playback_note_event(payload)
        # MIDI 60 = C4 (middle C).
        self.assertIn("C4", out)
        self.assertIn("quarter", out)

    def test_empty_returns_prompt(self):
        out = app._on_playback_note_event("")
        self.assertIn("Click a note", out)

    def test_bad_json_returns_prompt(self):
        out = app._on_playback_note_event("not-json")
        self.assertIn("Click a note", out)


class BuildPlaybackHtmlTests(unittest.TestCase):

    def test_contains_alphatab_script_and_initial_midi(self):
        html = build_playback_html("ABCDEF==")
        self.assertIn("/static/alphatab/alphaTab.min.js", html)
        self.assertIn("/static/alphatab/playback.js", html)
        self.assertIn('data-initial-midi="ABCDEF=="', html)
        # The hidden-bridge element ids the JS expects:
        for el in (
            'id="alphaTab"', "pb-play", "pb-pause", "pb-stop",
            "pb-tempo", "pb-use-hq", "pb-hq-audio",
        ):
            self.assertIn(el, html, f"missing {el!r} in playback HTML")

    def test_empty_initial_midi_is_valid(self):
        html = build_playback_html("")
        self.assertIn('data-initial-midi=""', html)


if __name__ == "__main__":
    unittest.main(verbosity=2)
