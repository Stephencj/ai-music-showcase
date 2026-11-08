"""End to end: over the MCP server (stdio, as Claude Code launches it), make a
short song, save it as a block, and file it in library folders — create a
video folder, add the block, reorder, move it, then clean everything up."""

from __future__ import annotations

import asyncio
import json
import shutil
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

TAG = f"e2e-folders-{uuid.uuid4().hex[:6]}"


def _payload(result):
    assert not result.isError, result.content
    return json.loads(result.content[0].text)


async def _session_run(made: dict) -> dict:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(command=sys.executable, args=[str(PROJECT_ROOT / "scripts" / "run_mcp.py")],
                                   cwd=tempfile.gettempdir())
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            r: dict = {"names": {t.name for t in (await session.list_tools()).tools}}
            call = lambda name, args: session.call_tool(name, args)  # noqa: E731

            gen = _payload(await call("generate_song", {
                "genre": "funk_fusion_full", "seed": 52, "sections": ["intro", "verse", "outro"],
                "section_overrides": {"verse": {"bars": 4}}, "with_pdf": False}))
            made["job"] = gen["job_id"]
            block = _payload(await call("save_block", {"job_id": gen["job_id"], "name": f"{TAG} take"}))["name"]
            made["blocks"].append(block)

            parent = _payload(await call("create_folder", {"name": f"{TAG} Videos"}))
            made["folders"].append(parent["id"])
            mix = _payload(await call("create_folder", {"name": "Mix 1", "parent": parent["id"],
                                                        "description": "e2e video"}))
            made["folders"].append(mix["id"])
            r["mix"] = mix
            # The generated block isn't in the library yet: add_to_folder adds it.
            r["added"] = _payload(await call("add_to_folder", {"folder": mix["path"], "items": [block]}))
            made["entries"].append(r["added"]["items"][0]["id"])
            # A second song (an existing entry this time) so there is an order to change.
            second = _payload(await call("add_to_library", {"block_name": block, "title": "dup check"}))
            r["second"] = second
            r["reordered"] = _payload(await call("reorder_folder", {"folder": mix["id"], "order": [block]}))
            r["moved"] = _payload(await call("move_to_folder", {"item": block, "to_folder": parent["id"]}))
            r["mix_after"] = _payload(await call("get_folder", {"folder": mix["id"]}))
            r["parent_after"] = _payload(await call("get_folder", {"folder": parent["path"]}))
            r["listing"] = _payload(await call("list_folders", {}))
            r["bad"] = await call("get_folder", {"folder": f"{TAG} nope"})
            r["deleted"] = _payload(await call("delete_folder", {"folder": parent["id"]}))
            made["folders"].remove(parent["id"])
            r["unfiled"] = _payload(await call("get_folder", {"folder": "Unfiled"}))
            return r


class FoldersOverMcp(unittest.TestCase):

    def test_create_add_reorder_move_over_stdio(self):
        from src.api.service import API_OUT
        from src.daw_integration.generic import blocks as block_store
        from src.daw_integration.generic import library as lib
        from src.daw_integration.generic import library_folders as lf

        # The server runs from the repo root; clean up the same directories.
        orig = lib.LIBRARY_DIR, block_store.BLOCKS_DIR
        lib.LIBRARY_DIR = PROJECT_ROOT / "data" / "library"
        block_store.BLOCKS_DIR = PROJECT_ROOT / "data" / "blocks"
        made: dict = {"blocks": [], "folders": [], "entries": [], "job": None}
        try:
            r = asyncio.run(asyncio.wait_for(_session_run(made), timeout=600))
            for n in ("list_folders", "create_folder", "rename_folder", "delete_folder", "get_folder",
                      "add_to_folder", "move_to_folder", "remove_from_folder", "reorder_folder"):
                self.assertIn(n, r["names"])
            block = made["blocks"][0]
            self.assertEqual(r["mix"]["path"], f"{TAG} Videos / Mix 1")
            self.assertEqual([i["block_name"] for i in r["added"]["items"]], [block])
            self.assertEqual(r["second"]["entry"]["folders"], [r["mix"]["path"]])   # re-add keeps folders
            self.assertEqual([i["block_name"] for i in r["reordered"]["items"]], [block])
            self.assertEqual([f["path"] for f in r["moved"]["folders"]], [f"{TAG} Videos"])
            self.assertEqual(r["mix_after"]["items"], [])
            self.assertEqual([i["block_name"] for i in r["parent_after"]["items"]], [block])
            paths = [f["path"] for f in r["listing"]["folders"]]
            self.assertLess(paths.index(f"{TAG} Videos"), paths.index(f"{TAG} Videos / Mix 1"))
            self.assertTrue(r["bad"].isError)
            self.assertIn("No folder", r["bad"].content[0].text)
            self.assertIn(made["entries"][0], r["deleted"]["now_unfiled"])
            self.assertIn(made["entries"][0], [i["id"] for i in r["unfiled"]["items"]])
            self.assertTrue(block_store._midi_path(block).exists())       # songs are never deleted
        finally:
            for fid in made["folders"]:
                try:
                    lf.delete_folder(fid)
                except lf.FolderError:
                    pass
            for eid in made["entries"]:
                lib.delete_entry(eid)
            for b in made["blocks"]:
                try:
                    block_store.delete_block(b)
                except Exception:  # noqa: BLE001
                    pass
                shutil.rmtree(block_store.BLOCKS_DIR / f"{block_store._safe_name(b)}.versions",
                              ignore_errors=True)
            if made["job"]:
                shutil.rmtree(API_OUT / made["job"], ignore_errors=True)
            lib.LIBRARY_DIR, block_store.BLOCKS_DIR = orig


if __name__ == "__main__":
    unittest.main(verbosity=2)
