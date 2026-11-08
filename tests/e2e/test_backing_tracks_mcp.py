"""End to end: over the MCP server (stdio, as Claude Code launches it), render
one carol as a backing track in two keys with the backing_tracks tool and
check the real files: an MP3 and a timing JSON per key, the count-in heard
before the band, the band (no melody) at the background loudness, chords
named in each key, and lyric lines timed inside the audio. The files are
removed afterwards (lyric text is never read here: only counts and times)."""

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

TUNE, GENRE, KEYS = "deck_the_halls", "christmas_fireside_full", ["C", "G"]


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
            res = _payload(await session.call_tool("backing_tracks", {
                "tune": TUNE, "genre": GENRE, "keys": KEYS, "seed": 7, "length_seconds": 50}))
            bad = await session.call_tool("backing_tracks", {"tune": "original"})
            return {"names": names, "res": res, "bad": bad}


class BackingTracksOverMcp(unittest.TestCase):

    def test_one_carol_in_two_keys(self):
        import numpy as np
        import soundfile as sf

        from src.audio_processing.render.loudness import integrated_lufs
        from src.composition import lyrics

        r: dict = {}
        try:
            r = asyncio.run(asyncio.wait_for(_session_run(), timeout=1200))
            self.assertIn("backing_tracks", r["names"])
            self.assertTrue(r["bad"].isError)
            res = r["res"]
            self.assertEqual(res["status"], "done", res)
            renders = res["renders"]
            self.assertEqual([x["key"] for x in renders], KEYS)
            self.assertEqual(len({x["tempo"] for x in renders}), 1)          # one tempo for every key
            index = json.loads(Path(res["index"]).read_text())
            self.assertEqual(len(index["renders"]), 2)
            lyr = lyrics.load(TUNE)
            for x in renders:
                with self.subTest(key=x["key"]):
                    mp3, tpath = Path(x["mp3"]), Path(x["timing"])
                    self.assertTrue(mp3.is_file() and mp3.suffix == ".mp3")
                    self.assertEqual(mp3.parent, PROJECT_ROOT / "data" / "outputs" / "backing" / TUNE)
                    self.assertFalse(list(mp3.parent.glob("*.wav")))          # MP3s only
                    tm = json.loads(tpath.read_text())
                    self.assertEqual(tm["audio"], mp3.name)
                    self.assertEqual(tm["key"], x["key"])
                    self.assertEqual(tm["variant"], "backing_track")
                    audio, sr = sf.read(str(mp3), always_2d=True)
                    seconds = audio.shape[0] / sr
                    self.assertAlmostEqual(seconds, tm["duration"], delta=1.0)
                    # Background loudness, no clipping.
                    self.assertAlmostEqual(integrated_lufs(audio.T.astype(np.float32), sr), -16.0, delta=1.5)
                    self.assertLess(float(np.abs(audio).max()), 1.0)
                    # The count-in: hi-hat clicks in the first bar (on the beats), the band after.
                    mono = np.abs(audio).mean(axis=1)
                    ci = tm["count_in"]
                    for c in ci["clicks"]:
                        a = int(c * sr)
                        self.assertGreater(float(mono[a:a + int(0.08 * sr)].max()), 0.01, c)
                    gap = mono[int((ci["clicks"][-1] + 0.25) * sr):int((ci["end"] - 0.05) * sr)]
                    if gap.size:
                        self.assertLess(float(gap.mean()), float(mono[int(ci["end"] * sr):].mean()))
                    # Chords in the key; lyrics inside the audio.
                    self.assertEqual(tm["chords"][0]["symbol"], x["key"])
                    lines = tm["lyrics"]["lines"]
                    self.assertTrue(tm["lyrics"]["available"] and lines)
                    for ln in lines:
                        self.assertEqual(len(ln["syllables"]), len(lyr.syllables(ln["line"])))
                        self.assertGreater(ln["start"], ci["end"])
                        self.assertLess(ln["end"], seconds)
            c_chords = {c["symbol"] for c in json.loads(Path(renders[0]["timing"]).read_text())["chords"]}
            g_chords = {c["symbol"] for c in json.loads(Path(renders[1]["timing"]).read_text())["chords"]}
            self.assertIn("G7", c_chords)
            self.assertIn("D7", g_chords)
        finally:
            for x in (r.get("res") or {}).get("renders", []):
                for p in (x.get("mp3"), x.get("timing")):
                    if p:
                        Path(p).unlink(missing_ok=True)
            idx = (r.get("res") or {}).get("index")
            if idx:
                Path(idx).unlink(missing_ok=True)
            d = PROJECT_ROOT / "data" / "outputs" / "backing" / TUNE
            if d.is_dir() and not any(d.iterdir()):
                shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
