"""End to end: drive the MCP server over stdio (scripts/run_mcp.py, exactly
as Claude Code launches it) to make a short funk_fusion_full track, revise
it, and export it — and get real audio files back."""

from __future__ import annotations

import asyncio
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def _payload(result) -> dict:
    assert not result.isError, result.content
    return json.loads(result.content[0].text)


async def _session_run(out_dir: Path) -> dict:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(command=sys.executable,
                                   args=[str(PROJECT_ROOT / "scripts" / "run_mcp.py")],
                                   cwd=tempfile.gettempdir())       # any cwd, like a client would
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            names = {t.name for t in (await session.list_tools()).tools}
            options = _payload(await session.call_tool("describe_options", {}))
            first = _payload(await session.call_tool("generate_song", {
                "genre": "funk_fusion_full", "seed": 52, "arrangement": "hits_only,calm",
                "sections": ["intro", "verse", "outro"], "section_overrides": {"verse": {"bars": 4}},
            }))
            revised = _payload(await session.call_tool("revise", {
                "job_id": first["job_id"], "changes": {"arrangement_add": ["brushes"], "tempo": 124}}))
            exported = _payload(await session.call_tool("export_audio", {
                "source": revised["job_id"], "dest_dir": str(out_dir), "name": "e2e", "target_lufs": -25}))
            bad = await session.call_tool("generate_song", {"arrangement": "loudest"})
            return {"names": names, "options": options, "first": first, "revised": revised,
                    "exported": exported, "bad": bad}


class McpStdioEndToEnd(unittest.TestCase):

    def test_generate_revise_export_over_stdio(self):
        import soundfile as sf
        from src.api.service import API_OUT
        from src.serve.song_tools import RECORDS_DIR

        out_dir = Path(tempfile.mkdtemp(prefix="mcp_e2e_"))
        r: dict = {}
        try:
            r = asyncio.run(asyncio.wait_for(_session_run(out_dir), timeout=600))
            self.assertIn("generate_song", r["names"])
            self.assertIn("score_video", r["names"])
            self.assertTrue(r["options"]["arrangement_variants"]["variants"])

            first = r["first"]
            self.assertEqual(first["status"], "done", first)
            wav = Path(first["files"]["audio_wav"])
            self.assertTrue(wav.exists())
            info = sf.info(str(wav))
            self.assertGreater(info.duration, 10)
            self.assertTrue(Path(first["files"]["audio_mp3"]).exists())

            rev = r["revised"]
            self.assertEqual(rev["status"], "done", rev)
            self.assertEqual(rev["seed"], 52)
            self.assertEqual(rev["revised_from"], first["job_id"])
            self.assertIn("brushes", rev["params"]["arrangement"])

            files = r["exported"]["files"]
            self.assertTrue(Path(files["wav"]).exists() and Path(files["mp3"]).exists())
            self.assertAlmostEqual(r["exported"]["lufs"], -25, delta=0.6)

            self.assertTrue(r["bad"].isError)
            self.assertIn("Valid:", r["bad"].content[0].text)
        finally:
            shutil.rmtree(out_dir, ignore_errors=True)
            for res in (r.get("first"), r.get("revised")):
                if res and res.get("job_id"):
                    shutil.rmtree(API_OUT / res["job_id"], ignore_errors=True)
                    (RECORDS_DIR / f"{res['job_id']}.json").unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
