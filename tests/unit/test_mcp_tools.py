"""Smoke tests for the MCP tools.

Each tool is a plain Python function under `@mcp.tool()`; we test the
underlying functions directly so the assertions stay independent of
the MCP transport choice."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.serve import mcp_tools


class IntrospectionTests(unittest.TestCase):

    def test_list_styles_returns_dicts(self):
        out = mcp_tools.list_styles()
        self.assertIsInstance(out, list)
        self.assertGreater(len(out), 0)
        first = out[0]
        for key in ("name", "label", "default_bars", "key", "scale",
                    "tempo", "has_rhythm_variants", "rhythm_variants"):
            self.assertIn(key, first)

    def test_list_techniques_no_filter_returns_all(self):
        out = mcp_tools.list_techniques()
        self.assertGreaterEqual(len(out), 30)

    def test_list_techniques_filter_by_instrument(self):
        chords = mcp_tools.list_techniques(instrument="chords")
        for t in chords:
            self.assertIn("chords", t["instruments"])

    def test_list_techniques_filter_by_role(self):
        intros = mcp_tools.list_techniques(role="intro")
        for t in intros:
            self.assertIn("intro", t["section_roles"])

    def test_list_techniques_filter_by_tag(self):
        funk_rock = mcp_tools.list_techniques(tag="funk_rock")
        self.assertGreater(len(funk_rock), 0)
        for t in funk_rock:
            self.assertIn("funk_rock", t["tags"])

    def test_inspect_technique_known(self):
        out = mcp_tools.inspect_technique(name="funk_walk")
        self.assertEqual(out["name"], "funk_walk")
        self.assertNotIn("error", out)

    def test_inspect_technique_unknown_returns_error_dict(self):
        out = mcp_tools.inspect_technique(name="not_real")
        self.assertIn("error", out)


class ComposeSongToolTests(unittest.TestCase):

    def test_compose_song_writes_paths(self):
        # The MCP tool delegates to compose_song(); writing to the
        # default output dir is fine for a smoke test (data/outputs/app).
        out = mcp_tools.compose_song(
            genre="pop", seed=42, bars=4,
        )
        self.assertTrue(out["midi_path"])
        self.assertTrue(Path(out["midi_path"]).exists())
        self.assertTrue(out["summary"])
        self.assertGreater(len(out["selections"]), 0)

    def test_compose_song_with_overrides(self):
        out = mcp_tools.compose_song(
            genre="pop_full_song", seed=99,
            technique_overrides={"verse:bass": "funk_walk"},
        )
        verse_bass = [
            s for s in out["selections"]
            if s["section_role"] == "verse" and s["instrument"] == "bass"
        ]
        for s in verse_bass:
            self.assertEqual(s["technique"], "funk_walk")


class GetLastComposeTests(unittest.TestCase):

    def test_get_last_compose_after_compose(self):
        # Run a compose first so there's something to find.
        mcp_tools.compose_song(genre="pop", seed=1, bars=4)
        out = mcp_tools.get_last_compose()
        self.assertTrue(out["exists"])
        self.assertTrue(out["midi_path"])
        self.assertGreater(out["size_bytes"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
