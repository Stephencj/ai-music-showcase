"""Smoke tests for the MCP server.

The tools are plain functions in src/serve/song_tools.py (re-exported by
mcp_tools); we test those directly so the assertions stay independent of
the MCP transport, and check the FastMCP registration separately."""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.serve import mcp_tools, song_tools


class IntrospectionTests(unittest.TestCase):

    def test_list_styles_returns_dicts(self):
        out = mcp_tools.list_styles()
        self.assertIsInstance(out, list)
        self.assertGreater(len(out), 0)
        first = out[0]
        for key in ("name", "label", "default_bars", "key", "scale",
                    "tempo", "has_rhythm_variants", "rhythm_variants"):
            self.assertIn(key, first)

    def test_list_styles_query_and_flags(self):
        out = mcp_tools.list_styles(query="funk_fusion")
        names = [s["name"] for s in out]
        self.assertIn("funk_fusion_full", names)
        ff = next(s for s in out if s["name"] == "funk_fusion_full")
        self.assertTrue(ff["arrangement_variants"])
        self.assertTrue(ff["hits"])

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

    def test_describe_options_covers_every_variant(self):
        out = mcp_tools.describe_options()
        names = {v["name"] for v in out["arrangement_variants"]["variants"]}
        self.assertIn("hits_only", names)
        self.assertIn("pocket_drums", names)
        self.assertTrue(all(v["description"] for v in out["arrangement_variants"]["variants"]))
        self.assertIn("guitar_stack", out["lead_voices"]["voices"])
        self.assertIn("groove", out["hit_styles"]["styles"])
        self.assertTrue(out["recipes"])


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


class RegistrationTests(unittest.TestCase):

    def test_every_song_tool_is_registered_with_a_description(self):
        tools = asyncio.run(mcp_tools.mcp.list_tools())
        by_name = {t.name: t for t in tools}
        self.assertEqual(set(by_name), {fn.__name__ for fn in song_tools.TOOLS})
        for t in tools:
            self.assertGreater(len(t.description or ""), 10, t.name)

    def test_generate_song_schema_describes_its_options(self):
        tools = {t.name: t for t in asyncio.run(mcp_tools.mcp.list_tools())}
        gen = tools["generate_song"]
        props = gen.inputSchema["properties"]
        for opt in ("genre", "seed", "arrangement", "hits", "hit_style", "lead_patch", "tempo",
                    "sections", "section_overrides", "extra_instruments", "wait"):
            self.assertIn(opt, props)
            self.assertTrue(props[opt].get("description"), opt)
        # The variant catalog is spelled out in the tool description itself.
        for variant in song_tools.ARRANGEMENT_VARIANTS:
            self.assertIn(variant, gen.description)
        self.assertNotIn("\n    ", gen.description)          # dedented

    def test_calling_a_tool_through_mcp(self):
        result = asyncio.run(mcp_tools.mcp.call_tool("list_styles", {"query": "neo_soul"}))
        text = result[0][0].text if isinstance(result, tuple) else result[0].text
        self.assertIn("neo_soul_full", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
