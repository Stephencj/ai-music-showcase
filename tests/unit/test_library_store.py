"""Tests for the sheet-music library store (``data/library/<id>.yaml``).

The store mirrors the songs sidecar convention: one YAML per saved piece,
the directory is the index. These tests point ``LIBRARY_DIR`` at a temp
dir so nothing touches the real library.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.daw_integration.generic import library as lib


class LibraryStoreTests(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_dir = lib.LIBRARY_DIR
        lib.LIBRARY_DIR = Path(self._tmp.name) / "library"

    def tearDown(self):
        lib.LIBRARY_DIR = self._orig_dir
        self._tmp.cleanup()

    def test_empty_library_lists_nothing(self):
        self.assertEqual(lib.list_entries(), [])

    def test_add_then_list_and_get(self):
        entry = lib.add_entry("Frijole Blues", collection="blues")
        self.assertEqual(entry["block_name"], "Frijole Blues")
        self.assertEqual(entry["id"], "Frijole_Blues")     # spaces → underscores
        self.assertEqual(entry["title"], "Frijole Blues")  # defaults to block name
        self.assertEqual(entry["collection"], "blues")
        self.assertFalse(entry["favorite"])
        self.assertTrue(entry["added"])

        listed = lib.list_entries()
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["id"], "Frijole_Blues")
        self.assertEqual(lib.get_entry("Frijole_Blues")["block_name"], "Frijole Blues")

    def test_add_is_idempotent_and_preserves_added_and_favorite(self):
        first = lib.add_entry("Walking Compton")
        lib.set_favorite("Walking_Compton", True)
        # Re-add with a new title/collection — must not duplicate, must keep
        # the original timestamp and the favorite flag.
        again = lib.add_entry("Walking Compton", title="Walkin'", collection="rap")
        self.assertEqual(len(lib.list_entries()), 1)
        self.assertEqual(again["added"], first["added"])
        self.assertTrue(again["favorite"])
        self.assertEqual(again["title"], "Walkin'")
        self.assertEqual(again["collection"], "rap")

    def test_favorite_toggle(self):
        lib.add_entry("Song A")
        self.assertTrue(lib.set_favorite("Song_A", True)["favorite"])
        self.assertFalse(lib.set_favorite("Song_A", False)["favorite"])

    def test_favorite_missing_raises(self):
        with self.assertRaises(FileNotFoundError):
            lib.set_favorite("nope", True)

    def test_delete(self):
        lib.add_entry("Song B")
        self.assertTrue(lib.delete_entry("Song_B"))
        self.assertEqual(lib.list_entries(), [])
        self.assertFalse(lib.delete_entry("Song_B"))   # already gone

    def test_add_requires_block_name(self):
        with self.assertRaises(ValueError):
            lib.add_entry("   ")

    def test_list_is_newest_first(self):
        # Write two entries with explicit timestamps to assert ordering.
        lib.add_entry("Old")
        lib.get_entry("Old")  # sanity
        old = lib.get_entry("Old")
        old["added"] = "2020-01-01T00:00:00"
        lib._write(lib._path("Old"), old)
        lib.add_entry("New")
        new = lib.get_entry("New")
        new["added"] = "2026-01-01T00:00:00"
        lib._write(lib._path("New"), new)
        ids = [e["id"] for e in lib.list_entries()]
        self.assertEqual(ids, ["New", "Old"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
