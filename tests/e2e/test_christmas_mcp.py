"""End to end: over the MCP server (stdio, as Claude Code launches it), make a
short track in each Christmas style on a public-domain carol and check the
real audio: the background loudness, no clipping, and that every instrument
in the band actually sounds; then render a two-song playlist mix."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

TUNES = {
    "christmas_jazz_trio_full": "silent_night",
    "christmas_swing_full": "jingle_bells",
    "christmas_orchestral_full": "the_first_noel",
    "christmas_fireside_full": "what_child_is_this",
    "christmas_choir_full": "angels_we_have_heard",
    "christmas_pop_full": "deck_the_halls",
}


def _payload(result) -> dict:
    assert not result.isError, result.content
    return json.loads(result.content[0].text)


async def _session_run() -> dict:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import get_default_environment, stdio_client

    env = get_default_environment()
    if os.environ.get("AI_MUSIC_INSTRUMENTS"):
        env["AI_MUSIC_INSTRUMENTS"] = os.environ["AI_MUSIC_INSTRUMENTS"]
    params = StdioServerParameters(command=sys.executable, args=[str(PROJECT_ROOT / "scripts" / "run_mcp.py")],
                                   cwd=tempfile.gettempdir(), env=env)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            names = {t.name for t in (await session.list_tools()).tools}
            options = _payload(await session.call_tool("describe_options", {}))
            songs = {}
            for i, (genre, tune) in enumerate(TUNES.items()):
                songs[genre] = _payload(await session.call_tool("generate_song", {
                    "genre": genre, "tune": tune, "seed": 11 + i, "length_seconds": 40, "with_stems": True,
                    "with_pdf": False}))
            mix = _payload(await session.call_tool("christmas_mix", {
                "count": 2, "min_track_seconds": 30, "max_track_seconds": 35, "crossfade": 2,
                "name": "e2e-christmas-mix", "seed": 3}))
            refused = await session.call_tool("generate_song", {"genre": "christmas_pop_full",
                                                                "tune": "White Christmas"})
            return {"names": names, "options": options, "songs": songs, "mix": mix, "refused": refused}


class ChristmasOverMcp(unittest.TestCase):

    def test_a_short_track_per_style_and_a_mix(self):
        import numpy as np
        import soundfile as sf

        from src.api.service import API_OUT
        from src.audio_processing.render.loudness import integrated_lufs
        from src.composition.instruments import INSTRUMENT_REGISTRY
        from src.daw_integration.generic.styles import STYLES

        r: dict = {}
        try:
            r = asyncio.run(asyncio.wait_for(_session_run(), timeout=900))
            self.assertIn("christmas_mix", r["names"])
            self.assertIn("christmas", r["options"])
            for genre, res in r["songs"].items():
                self.assertEqual(res["status"], "done", res)
                self.assertEqual(res["tune"], TUNES[genre])
                x, sr = sf.read(res["files"]["audio_wav"], always_2d=True)
                self.assertGreater(len(x) / sr, 25, genre)
                self.assertAlmostEqual(integrated_lufs(x.T.astype("float32"), sr), -16.0, delta=0.7, msg=genre)
                self.assertLess(float(np.abs(x).max()), 0.99, genre)
                stems = {Path(p).stem.lower(): p for p in res["files"].get("stems", [])}
                for inst in STYLES[genre].default_instruments:
                    label = INSTRUMENT_REGISTRY[inst].label.lower().replace(" ", "_").replace("(", "_").replace(")", "_")
                    hits = [p for name, p in stems.items()
                            if name.startswith(label) or (inst == "drum_kit" and name == "brushes")]
                    self.assertTrue(hits, f"{genre}: no stem for {inst} in {sorted(stems)}")
                    loudest = max(float(np.abs(sf.read(p, always_2d=True)[0]).max()) for p in hits)
                    self.assertGreater(loudest, 1e-3, f"{genre}: {inst} is silent")
            mix = r["mix"]
            self.assertEqual(mix["status"], "done", mix)
            self.assertEqual(len(mix["tracks"]), 2)
            self.assertTrue(Path(mix["files"]["audio_mp3"]).exists())
            self.assertTrue(r["refused"].isError)
        finally:
            for res in (r.get("songs") or {}).values():
                if res.get("job_id"):
                    shutil.rmtree(API_OUT / res["job_id"], ignore_errors=True)
            out = PROJECT_ROOT / "data" / "outputs" / "playlists"
            for f in out.glob("e2e-christmas-mix.*"):
                f.unlink()


if __name__ == "__main__":
    unittest.main(verbosity=2)
