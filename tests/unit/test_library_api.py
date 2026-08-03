"""HTTP-level tests for the /api/library routes and the bare-PDF route.

Mounts the real API router on a bare FastAPI app (same approach as
test_admin_restart) with a temp library dir. The block-existence check is
stubbed so these run fast without LilyPond or real block files; actual PDF
engraving is covered in test_pdf_export.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import routes
from src.daw_integration.generic import library as lib


def _app() -> FastAPI:
    api = FastAPI()
    api.include_router(routes.router)
    return api


class LibraryApiTests(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_dir = lib.LIBRARY_DIR
        lib.LIBRARY_DIR = Path(self._tmp.name) / "library"
        self.client = TestClient(_app())
        # Pretend every referenced block has a MIDI on disk.
        self._exists = mock.patch.object(
            routes.block_store, "_midi_path",
            side_effect=lambda name: Path(self._tmp.name) / f"{name}.mid",
        )
        # Create the fake midi files so .exists() is True.
        Path(self._tmp.name, "Frijole Blues.mid").write_bytes(b"MThd")

    def tearDown(self):
        lib.LIBRARY_DIR = self._orig_dir
        self._tmp.cleanup()

    def test_empty_library(self):
        r = self.client.get("/api/library")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"library": []})

    def test_add_list_favorite_delete_flow(self):
        with self._exists:
            # add
            r = self.client.post("/api/library", json={"block_name": "Frijole Blues",
                                                        "collection": "blues"})
            self.assertEqual(r.status_code, 200, r.text)
            entry = r.json()["entry"]
            self.assertEqual(entry["id"], "Frijole_Blues")
            # asset URLs are attached and point at the block's endpoints
            self.assertEqual(entry["pdf_url"], "/api/blocks/Frijole%20Blues/pdf/full")
            self.assertEqual(entry["audio_url"], "/api/blocks/Frijole%20Blues/audio")
            self.assertIn("musicxml_url", entry)

            # list
            lst = self.client.get("/api/library").json()["library"]
            self.assertEqual(len(lst), 1)
            self.assertEqual(lst[0]["id"], "Frijole_Blues")

            # favorite on, then off
            self.assertTrue(self.client.post("/api/library/Frijole_Blues/favorite")
                            .json()["entry"]["favorite"])
            self.assertFalse(self.client.post("/api/library/Frijole_Blues/favorite",
                                              params={"favorite": "false"})
                             .json()["entry"]["favorite"])

            # delete
            self.assertEqual(self.client.delete("/api/library/Frijole_Blues").status_code, 200)
            self.assertEqual(self.client.get("/api/library").json(), {"library": []})

    def test_add_unknown_block_404(self):
        with self._exists:
            r = self.client.post("/api/library", json={"block_name": "does not exist"})
            self.assertEqual(r.status_code, 404)

    def test_favorite_missing_404(self):
        r = self.client.post("/api/library/ghost/favorite")
        self.assertEqual(r.status_code, 404)

    def test_delete_missing_404(self):
        r = self.client.delete("/api/library/ghost")
        self.assertEqual(r.status_code, 404)

    def test_pdf_full_missing_block_404(self):
        # No stub here: a truly absent block MIDI must 404 (not 503/engrave).
        with mock.patch.object(routes.block_store, "_midi_path",
                               return_value=Path(self._tmp.name) / "absent.mid"):
            r = self.client.get("/api/blocks/absent/pdf/full")
            self.assertEqual(r.status_code, 404)


class BlockPartsApiTests(unittest.TestCase):
    """The per-instrument score endpoints. A pre-extracted score dir stands in
    for the (slow, LilyPond) engraving so these stay fast and hermetic."""

    NAME = "TestBlock"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        # A fake block MIDI so the existence check passes.
        (root / f"{self.NAME}.mid").write_bytes(b"MThd")
        # A pre-engraved score dir: full + two parts. Because full_score.pdf
        # already exists, _block_score_dir skips engraving entirely.
        score = root / "api" / "_blocks" / f"{self.NAME}_score"
        (score / "parts").mkdir(parents=True)
        (score / "full_score.pdf").write_bytes(b"%PDF-1.4 full")
        (score / "parts" / "Melody.pdf").write_bytes(b"%PDF-1.4 melody")
        (score / "parts" / "Upright_Bass.pdf").write_bytes(b"%PDF-1.4 bass")

        self.client = TestClient(_app())
        self._patches = [
            mock.patch.object(routes.service, "API_OUT", root / "api"),
            mock.patch.object(routes.block_store, "_midi_path",
                              side_effect=lambda n: root / f"{n}.mid"),
            mock.patch.object(routes.block_store, "_safe_name", side_effect=lambda n: n),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self._tmp.cleanup()

    def test_parts_lists_full_and_each_instrument(self):
        r = self.client.get(f"/api/blocks/{self.NAME}/parts")
        self.assertEqual(r.status_code, 200, r.text)
        parts = r.json()["parts"]
        self.assertEqual(parts[0], {
            "id": "full", "name": "Full score",
            "url": f"/api/blocks/{self.NAME}/pdf/full"})
        ids = [p["id"] for p in parts]
        self.assertIn("Melody", ids)
        self.assertIn("Upright_Bass", ids)
        # Underscores become spaces in the display name.
        bass = next(p for p in parts if p["id"] == "Upright_Bass")
        self.assertEqual(bass["name"], "Upright Bass")
        self.assertEqual(bass["url"], f"/api/blocks/{self.NAME}/pdf/part/Upright_Bass")

    def test_full_and_part_pdfs_served(self):
        full = self.client.get(f"/api/blocks/{self.NAME}/pdf/full")
        self.assertEqual(full.status_code, 200)
        self.assertEqual(full.headers["content-type"], "application/pdf")
        self.assertTrue(full.content.startswith(b"%PDF-"))

        part = self.client.get(f"/api/blocks/{self.NAME}/pdf/part/Melody")
        self.assertEqual(part.status_code, 200)
        self.assertEqual(part.content, b"%PDF-1.4 melody")

    def test_unknown_part_404(self):
        r = self.client.get(f"/api/blocks/{self.NAME}/pdf/part/Trombone")
        self.assertEqual(r.status_code, 404)

    def test_part_traversal_is_blocked(self):
        # A crafted id must not escape the parts/ dir even if such a file exists.
        r = self.client.get(f"/api/blocks/{self.NAME}/pdf/part/..%2Ffull_score")
        self.assertIn(r.status_code, (404, 400))


if __name__ == "__main__":
    unittest.main(verbosity=2)
