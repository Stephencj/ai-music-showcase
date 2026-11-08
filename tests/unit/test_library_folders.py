"""Library folders: the store (``data/library/folders.yaml``), the
/api/library/folders routes, and the MCP folder tools.

Everything points ``LIBRARY_DIR`` at a temp dir and stubs the block-exists
check, so nothing touches the real library or needs real blocks.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.daw_integration.generic import library as lib
from src.daw_integration.generic import library_folders as lf


class _TempLibrary(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_dir = lib.LIBRARY_DIR
        lib.LIBRARY_DIR = Path(self._tmp.name) / "library"
        self.blocks = Path(self._tmp.name) / "blocks"
        self.blocks.mkdir()
        from src.api import routes
        self._midi = mock.patch.object(routes.block_store, "_midi_path",
                                       side_effect=lambda name: self.blocks / f"{name}.mid")
        self._midi.start()

    def tearDown(self):
        self._midi.stop()
        lib.LIBRARY_DIR = self._orig_dir
        self._tmp.cleanup()

    def block(self, name: str) -> str:
        (self.blocks / f"{name}.mid").write_bytes(b"MThd")
        return name

    def ids(self, ref: str) -> list[str]:
        return [e["id"] for e in lf.get_folder(ref)["items"]]


class FolderStoreTests(_TempLibrary):

    def test_create_nest_and_list_with_counts(self):
        lf.create_folder("Videos")
        mix = lf.create_folder("Christmas Mix 1", parent="Videos", description="1-hour cozy mix")
        self.assertEqual(mix["path"], "Videos / Christmas Mix 1")
        self.assertEqual(mix["description"], "1-hour cozy mix")
        lf.create_folder("Archive")
        lib.add_entry("A")
        lf.add_items(mix["id"], ["A"])
        listed = lf.list_folders()
        self.assertEqual([f["path"] for f in listed["folders"]],
                         ["Archive", "Videos", "Videos / Christmas Mix 1"])
        self.assertEqual(listed["folders"][2]["item_count"], 1)
        self.assertEqual(listed["folders"][1]["subfolders"], [mix["id"]])
        self.assertEqual(listed["unfiled"]["item_count"], 0)

    def test_nesting_is_one_level_and_names_are_unique_per_parent(self):
        lf.create_folder("Videos")
        lf.create_folder("Mix", parent="Videos")
        with self.assertRaises(lf.FolderError):
            lf.create_folder("Deeper", parent="Videos / Mix")
        with self.assertRaises(lf.FolderError):
            lf.create_folder("videos")
        lf.create_folder("Archive")
        lf.create_folder("Mix", parent="Archive")   # same name, other parent: fine
        with self.assertRaises(lf.FolderError):     # ambiguous by bare name
            lf.get_folder("Mix")
        self.assertEqual(lf.get_folder("Videos/Mix")["path"], "Videos / Mix")
        for bad in ("", "a/b", "Unfiled"):
            with self.assertRaises(lf.FolderError):
                lf.create_folder(bad)

    def test_rename_describe_and_reparent(self):
        lf.create_folder("Videos")
        f = lf.create_folder("Mix")
        out = lf.update_folder(f["id"], name="Mix 1", description="carols", parent="Videos")
        self.assertEqual(out["path"], "Videos / Mix 1")
        self.assertEqual(out["description"], "carols")
        self.assertEqual(out["id"], f["id"])        # id is stable across renames
        with self.assertRaises(lf.FolderError):     # Videos has children → stays top level
            lf.update_folder("Videos", parent="Videos / Mix 1")
        self.assertEqual(lf.update_folder(f["id"], parent="")["path"], "Mix 1")

    def test_order_add_position_reorder(self):
        f = lf.create_folder("Mix")["id"]
        for n in "ABCD":
            lib.add_entry(n)
        lf.add_items(f, ["A", "B", "C"])
        lf.add_items(f, ["D"], position=1)
        lf.add_items(f, ["A"])                       # already there: keeps its place
        self.assertEqual(self.ids(f), ["A", "D", "B", "C"])
        lf.reorder(f, ["C", "A"])                    # unlisted keep relative order after
        self.assertEqual(self.ids(f), ["C", "A", "D", "B"])
        with self.assertRaises(lf.FolderError):
            lf.reorder(f, ["Z"])
        with self.assertRaises(lf.FolderError):
            lf.add_items(f, ["nope"])

    def test_copy_move_remove_and_unfiled(self):
        a = lf.create_folder("A")["id"]
        b = lf.create_folder("B")["id"]
        lib.add_entry("S1")
        lib.add_entry("S2")
        self.assertEqual(lf.get_folder("unfiled")["item_count"], 2)
        lf.add_items(a, ["S1", "S2"])
        lf.add_items(b, ["S1"])                      # copy: in both now
        self.assertEqual([p["path"] for p in lf.folders_by_entry()["S1"]], ["A", "B"])
        moved = lf.move_item("S2", b)                # move: out of every other folder
        self.assertEqual([p["path"] for p in moved["folders"]], ["B"])
        self.assertEqual(self.ids(b), ["S1", "S2"])
        lf.move_item("S1", b, position=1)            # already there: repositioned
        self.assertEqual(self.ids(b), ["S2", "S1"])
        lf.move_item("S1", "Unfiled")
        self.assertEqual(self.ids("unfiled"), ["S1"])
        lf.remove_item(b, "S2")
        self.assertEqual(lf.get_folder("unfiled")["item_count"], 2)
        with self.assertRaises(lf.FolderError):
            lf.remove_item(b, "S2")

    def test_delete_folder_keeps_songs_and_promotes_subfolders(self):
        lf.create_folder("Videos")
        sub = lf.create_folder("Mix", parent="Videos")["id"]
        other = lf.create_folder("Keep")["id"]
        lf.create_folder("Mix")                      # name clash for the promoted one
        lib.add_entry("S1")
        lib.add_entry("S2")
        lf.add_items("Videos", ["S1", "S2"])
        lf.add_items(other, ["S2"])
        out = lf.delete_folder("Videos")
        self.assertEqual(out["now_unfiled"], ["S1"])
        self.assertEqual(out["promoted"], [sub])
        self.assertEqual(lf.get_folder(sub)["path"], "Mix (2)")
        self.assertEqual(len(lib.list_entries()), 2)          # no song deleted
        self.assertEqual(self.ids("unfiled"), ["S1"])
        with self.assertRaises(lf.FolderError):
            lf.delete_folder("unfiled")

    def test_deleting_an_entry_drops_its_memberships(self):
        f = lf.create_folder("Mix")["id"]
        lib.add_entry("S1")
        lf.add_items(f, ["S1"])
        lib.delete_entry("S1")
        self.assertEqual(lf.get_folder(f)["item_count"], 0)
        self.assertNotIn("S1", yaml.safe_load(lf._file().read_text())["folders"][0]["items"])


class MigrationTests(_TempLibrary):

    def test_collections_become_folders_once(self):
        for i, (name, coll) in enumerate([("Silent Night", "Christmas samples"),
                                           ("Jingle", "Christmas samples"),
                                           ("Blues", "Videos/Blues Mix"), ("Loose", "")]):
            e = lib.add_entry(name, collection=coll)
            lib._write(lib._path(e["id"]), {**e, "added": f"2026-11-0{i + 1}T00:00:00"})
        self.assertFalse(lf._file().exists())
        listed = lf.list_folders()                   # first read migrates + saves
        self.assertTrue(lf._file().exists())
        paths = {f["path"]: f["item_count"] for f in listed["folders"]}
        self.assertEqual(paths, {"Christmas samples": 2, "Videos": 0, "Videos / Blues Mix": 1})
        self.assertEqual(self.ids("Christmas samples"), ["Silent_Night", "Jingle"])  # added order
        self.assertEqual(self.ids("unfiled"), ["Loose"])
        # Collection fields stay as they were (compatible with older clients).
        self.assertEqual(lib.get_entry("Silent_Night")["collection"], "Christmas samples")

        # Moving one out sticks: the migration doesn't re-file it.
        lf.move_item("Jingle", "unfiled")
        self.assertEqual(self.ids("Christmas samples"), ["Silent_Night"])
        self.assertEqual(self.ids("unfiled"), ["Loose", "Jingle"])     # newest first

        # A client that only sets collection (an old server) still gets filed.
        lib.add_entry("Deck", collection="Christmas samples")
        self.assertEqual(self.ids("Christmas samples"), ["Silent_Night", "Deck"])
        # ...and re-collecting an entry files it into the new folder too.
        lib.add_entry("Deck", collection="Archive")
        self.assertEqual(self.ids("Archive"), ["Deck"])


class AtomicWriteTests(_TempLibrary):

    def test_write_replaces_atomically_and_leaves_no_temp_files(self):
        lf.create_folder("Mix")
        p = lf._file()
        before = p.read_text()

        def boom(*a, **k):
            raise RuntimeError("disk full")

        with mock.patch.object(lib.yaml, "safe_dump", side_effect=boom):
            with self.assertRaises(RuntimeError):
                lf.create_folder("Other")
        self.assertEqual(p.read_text(), before)      # old file intact
        leftovers = [n for n in os.listdir(p.parent) if n.endswith(".tmp")]
        self.assertEqual(leftovers, [])
        self.assertEqual([f["name"] for f in lf.list_folders()["folders"]], ["Mix"])

    def test_folders_file_is_not_an_entry(self):
        lf.create_folder("Mix")
        lib.add_entry("S1")
        self.assertEqual([e["id"] for e in lib.list_entries()], ["S1"])
        # A block literally named "folders" can't clobber the folders file.
        lib.add_entry("folders")
        self.assertEqual(lf.list_folders()["folders"][0]["name"], "Mix")
        self.assertEqual(lib.get_entry("folders")["block_name"], "folders")

    def test_concurrent_writers_lose_nothing(self):
        import threading
        names = [f"F{i}" for i in range(20)]
        threads = [threading.Thread(target=lf.create_folder, args=(n,)) for n in names]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sorted(f["name"] for f in lf.list_folders()["folders"]), sorted(names))


class FolderRouteTests(_TempLibrary):

    def setUp(self):
        super().setUp()
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from src.api import routes
        app = FastAPI()
        app.include_router(routes.router)
        self.c = TestClient(app)

    def test_folder_routes_end_to_end(self):
        c = self.c
        r = c.post("/api/library/folders", json={"name": "Videos"})
        self.assertEqual(r.status_code, 200, r.text)
        mix = c.post("/api/library/folders", json={"name": "Mix 1", "parent": "Videos",
                                                   "description": "cozy"}).json()["folder"]
        self.assertEqual(c.post("/api/library/folders", json={"name": "Mix 1", "parent": "Videos"}
                                ).status_code, 400)

        # add_to_library straight into a folder
        self.block("Song A")
        r = c.post("/api/library", json={"block_name": "Song A", "folder": mix["id"]})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["entry"]["folders"], [{"id": mix["id"], "path": "Videos / Mix 1"}])
        self.assertEqual(c.post("/api/library", json={"block_name": "Song A", "folder": "Nope"}
                                ).status_code, 400)

        # add by block name (auto-added to the library) at a position
        self.block("Song B")
        r = c.post(f"/api/library/folders/{mix['id']}/items", json={"block_names": ["Song B"], "position": 0})
        self.assertEqual(r.json()["folder"]["item_count"], 2)
        self.assertEqual(c.post(f"/api/library/folders/{mix['id']}/items",
                                json={"block_names": ["ghost"]}).status_code, 404)

        got = c.get(f"/api/library/folders/{mix['id']}").json()["folder"]
        self.assertEqual([e["id"] for e in got["items"]], ["Song_B", "Song_A"])
        self.assertTrue(got["items"][0]["audio_url"].endswith("/Song%20B/audio"))
        self.assertTrue(got["items"][0]["pdf_url"].endswith("/pdf/full"))

        r = c.put(f"/api/library/folders/{mix['id']}/order", json={"entry_ids": ["Song_A", "Song_B"]})
        self.assertEqual(r.json()["folder"]["items"], ["Song_A", "Song_B"])

        r = c.patch(f"/api/library/folders/{mix['id']}", json={"name": "Christmas Mix 1"})
        self.assertEqual(r.json()["folder"]["path"], "Videos / Christmas Mix 1")

        r = c.post("/api/library/move", json={"entry_id": "Song_B", "to_folder": "Videos"})
        self.assertEqual(r.json()["folders"], [{"id": "videos", "path": "Videos"}])
        r = c.delete(f"/api/library/folders/{mix['id']}/items/Song_A")
        self.assertEqual(r.json()["folder"]["item_count"], 0)

        lst = c.get("/api/library").json()["library"]
        self.assertEqual({e["id"]: [f["path"] for f in e["folders"]] for e in lst},
                         {"Song_A": [], "Song_B": ["Videos"]})
        self.assertEqual(c.get("/api/library/folders/unfiled").json()["folder"]["item_count"], 1)

        r = c.delete("/api/library/folders/videos")
        self.assertEqual(r.json()["now_unfiled"], ["Song_B"])
        self.assertEqual(c.get("/api/library/folders/videos").status_code, 404)
        folders = c.get("/api/library/folders").json()
        self.assertEqual([f["path"] for f in folders["folders"]], ["Christmas Mix 1"])
        self.assertEqual(folders["unfiled"]["item_count"], 2)
        self.assertEqual(len(c.get("/api/library").json()["library"]), 2)


class FolderToolTests(_TempLibrary):

    def test_tools_flow_and_errors(self):
        from src.serve import song_tools as t

        for n in ("list_folders", "create_folder", "rename_folder", "delete_folder", "get_folder",
                  "add_to_folder", "move_to_folder", "remove_from_folder", "reorder_folder"):
            self.assertIn(n, t.TOOLS_BY_NAME)
            self.assertGreater(len(t.TOOLS_BY_NAME[n].__doc__ or ""), 40, n)

        t.call("create_folder", {"name": "Videos"})
        mix = t.call("create_folder", {"name": "Christmas Mix 1", "parent": "Videos",
                                       "description": "1 hour"})
        self.block("Silent Night")
        self.block("Jingle Bells")
        saved = t.call("add_to_library", {"block_name": "Silent Night", "folder": "Videos / Christmas Mix 1"})
        self.assertEqual(saved["entry"]["folders"], ["Videos / Christmas Mix 1"])
        got = t.call("add_to_folder", {"folder": "Christmas Mix 1", "items": ["Jingle Bells"]})
        self.assertEqual([i["block_name"] for i in got["items"]], ["Silent Night", "Jingle Bells"])
        got = t.call("reorder_folder", {"folder": mix["id"], "order": ["Jingle Bells"]})
        self.assertEqual([i["id"] for i in got["items"]], ["Jingle_Bells", "Silent_Night"])
        moved = t.call("move_to_folder", {"item": "Silent Night", "to_folder": "Videos"})
        self.assertEqual([f["path"] for f in moved["folders"]], ["Videos"])
        t.call("remove_from_folder", {"folder": "Videos", "item": "Silent_Night"})
        self.assertEqual(t.call("get_folder", {"folder": "Unfiled"})["item_count"], 1)
        renamed = t.call("rename_folder", {"folder": mix["id"], "new_name": "Cozy Mix",
                                           "description": "upload Dec 1"})
        self.assertEqual((renamed["path"], renamed["description"]), ("Videos / Cozy Mix", "upload Dec 1"))
        lib_list = t.call("list_library")
        self.assertEqual({e["id"]: e["folders"] for e in lib_list},
                         {"Silent_Night": [], "Jingle_Bells": ["Videos / Cozy Mix"]})
        listed = t.call("list_folders")
        self.assertEqual([f["path"] for f in listed["folders"]], ["Videos", "Videos / Cozy Mix"])
        out = t.call("delete_folder", {"folder": "Videos / Cozy Mix"})
        self.assertEqual(out["now_unfiled"], ["Jingle_Bells"])

        with self.assertRaises(t.ToolError) as cm:
            t.call("get_folder", {"folder": "Nope"})
        self.assertIn("Folders: Videos", str(cm.exception))
        with self.assertRaises(t.ToolError):
            t.call("add_to_folder", {"folder": "Videos", "items": ["no such block"]})


if __name__ == "__main__":
    unittest.main(verbosity=2)
