"""Tests for block version control (``data/blocks/<name>.versions/``).

Points BLOCKS_DIR at a temp dir and fabricates a block's live files, so no
real blocks are touched and no LilyPond/FluidSynth is needed.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import yaml

from src.daw_integration.generic import blocks as block_store
from src.daw_integration.generic import block_versions as bv


class BlockVersionsTests(unittest.TestCase):
    NAME = "TestBlock"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig = block_store.BLOCKS_DIR
        block_store.BLOCKS_DIR = Path(self._tmp.name)
        self._write_live(midi=b"MIDI-A", n_notes=100, mp3=b"MP3-A")

    def tearDown(self):
        block_store.BLOCKS_DIR = self._orig
        self._tmp.cleanup()

    # --- helpers ---------------------------------------------------------
    def _write_live(self, *, midi: bytes, n_notes: int, mp3: bytes | None):
        block_store._midi_path(self.NAME).write_bytes(midi)
        block_store._preview_path(self.NAME).write_bytes(mp3 or b"")
        meta = {"name": self.NAME, "n_notes": n_notes, "bars": 4, "tempo": 120,
                "instruments": [{"name": "Drum kit"}, {"name": "Bass"}]}
        with open(block_store._yaml_path(self.NAME), "w") as f:
            yaml.safe_dump(meta, f)

    def _live_midi(self) -> bytes:
        return block_store._midi_path(self.NAME).read_bytes()

    # --- tests -----------------------------------------------------------
    def test_no_versions_initially(self):
        out = bv.list_versions(self.NAME)
        self.assertEqual(out, {"versions": [], "active": None})

    def test_snapshot_captures_files_and_marks_active(self):
        v = bv.snapshot_version(self.NAME, label="First take")
        vdir = bv._versions_dir(self.NAME) / v["id"]
        self.assertTrue((vdir / "block.mid").exists())
        self.assertTrue((vdir / "meta.yaml").exists())
        self.assertTrue((vdir / "preview.mp3").exists())
        self.assertEqual(v["label"], "First take")
        self.assertEqual(v["source"], "manual")
        self.assertEqual(v["summary"]["n_notes"], 100)
        self.assertEqual(v["summary"]["instruments"], ["Drum kit", "Bass"])

        out = bv.list_versions(self.NAME)
        self.assertEqual(len(out["versions"]), 1)
        self.assertEqual(out["active"], v["id"])
        self.assertTrue(out["versions"][0]["active"])

    def test_snapshot_without_preview(self):
        block_store._preview_path(self.NAME).unlink()
        v = bv.snapshot_version(self.NAME)
        self.assertFalse(v["has_preview"])
        self.assertIsNone(bv.version_preview_path(self.NAME, v["id"]))

    def test_pre_edit_snapshot_is_not_active(self):
        v = bv.snapshot_version(self.NAME, source="pre-edit", make_active=False)
        self.assertEqual(v["label"], "Before edit")
        self.assertIsNone(bv.list_versions(self.NAME)["active"])

    def test_restore_swaps_live_files_and_preserves_current(self):
        # Version 1 = state A.
        v1 = bv.snapshot_version(self.NAME, label="A")
        self.assertEqual(self._live_midi(), b"MIDI-A")
        # Mutate the live block to state B (as an edit would).
        self._write_live(midi=b"MIDI-B", n_notes=200, mp3=b"MP3-B")

        # Restore version 1 → live becomes A again, and B is auto-snapshotted.
        result = bv.restore_version(self.NAME, v1["id"])
        self.assertEqual(result["restored"], v1["id"])
        self.assertIn("snapshot_of_previous", result)
        self.assertEqual(self._live_midi(), b"MIDI-A")            # restored
        self.assertEqual(block_store._preview_path(self.NAME).read_bytes(), b"MP3-A")

        out = bv.list_versions(self.NAME)
        self.assertEqual(len(out["versions"]), 2)                 # A + auto-snap of B
        self.assertEqual(out["active"], v1["id"])                 # A is active now
        # The auto-snapshot preserved state B so it isn't lost.
        prev = bv._versions_dir(self.NAME) / result["snapshot_of_previous"]
        self.assertEqual((prev / "block.mid").read_bytes(), b"MIDI-B")

    def test_restore_invalidates_wav_and_peaks(self):
        v1 = bv.snapshot_version(self.NAME)
        block_store._wav_path(self.NAME).write_bytes(b"WAV-stale")
        block_store._peaks_path(self.NAME).write_text("[0.1]")
        bv.restore_version(self.NAME, v1["id"])
        self.assertFalse(block_store._wav_path(self.NAME).exists())
        self.assertFalse(block_store._peaks_path(self.NAME).exists())

    def test_delete_version_clears_active(self):
        v = bv.snapshot_version(self.NAME)
        self.assertTrue(bv.delete_version(self.NAME, v["id"]))
        out = bv.list_versions(self.NAME)
        self.assertEqual(out["versions"], [])
        self.assertIsNone(out["active"])
        self.assertFalse(bv.delete_version(self.NAME, v["id"]))   # already gone

    def test_snapshot_missing_block_raises(self):
        with self.assertRaises(FileNotFoundError):
            bv.snapshot_version("ghost")

    def test_restore_missing_version_raises(self):
        with self.assertRaises(FileNotFoundError):
            bv.restore_version(self.NAME, "nope")

    def test_version_id_traversal_sanitized(self):
        # A crafted id can't escape the versions dir.
        self.assertIsNone(bv.version_preview_path(self.NAME, "../../etc/passwd"))
        self.assertFalse(bv.delete_version(self.NAME, "../../etc"))

    def _fake_vocal_take(self, take_id: str, created: str, **meta):
        import json
        d = block_store._vocals_dir(self.NAME) / take_id
        d.mkdir(parents=True, exist_ok=True)
        (d / "mix.mp3").write_bytes(b"MP3")
        payload = {"id": take_id, "created": created, "engine": "studio",
                   "voice": "tiger_amy", "harmonies": True, "lyrics": "la la",
                   "files": {"mix": "mix.mp3"}}
        payload.update(meta)
        (d / "meta.json").write_text(json.dumps(payload))

    def test_preview_take_pointer(self):
        self._fake_vocal_take("20260101-000000-000", "2026-01-01T00:00:00")
        block_store.set_preview_take(self.NAME, "20260101-000000-000")
        p = block_store.active_preview_audio(self.NAME)
        self.assertIsNotNone(p)
        self.assertEqual(Path(p).read_bytes(), b"MP3")   # the take's mix
        self.assertEqual(bv._read_meta(self.NAME).get("preview_take"), "20260101-000000-000")
        # Clearing reverts the pointer (instrumental preview).
        block_store.set_preview_take(self.NAME, None)
        self.assertIsNone(bv._read_meta(self.NAME).get("preview_take"))

    def test_preview_take_missing_take_raises(self):
        with self.assertRaises(FileNotFoundError):
            block_store.set_preview_take(self.NAME, "does-not-exist")

    def test_history_merges_versions_and_vocal_takes_newest_first(self):
        # A version at an early time, a vocal take later.
        v = bv.snapshot_version(self.NAME, label="gen")
        # Force the version's created earlier than the take for a deterministic order.
        vdir = bv._versions_dir(self.NAME) / v["id"]
        import json
        vj = json.loads((vdir / "version.json").read_text())
        vj["created"] = "2020-01-01T00:00:00"
        (vdir / "version.json").write_text(json.dumps(vj))
        self._fake_vocal_take("20260101-000000-000", "2026-01-01T00:00:00")

        out = bv.history(self.NAME)
        kinds = [i["kind"] for i in out["history"]]
        self.assertEqual(kinds, ["vocal", "version"])   # newest (vocal) first
        vocal = out["history"][0]
        self.assertEqual(vocal["label"], "Sung · studio · amy")  # tiger_ stripped
        self.assertEqual(vocal["files"], {"mix": "mix.mp3"})
        self.assertEqual(vocal["lyrics"], "la la")
        version = out["history"][1]
        self.assertEqual(version["kind"], "version")
        self.assertEqual(version["label"], "gen")
        self.assertEqual(out["active"], v["id"])


class BlockVersionApiTests(unittest.TestCase):
    """HTTP surface for the version routes, over a temp BLOCKS_DIR."""

    NAME = "ApiBlock"

    def setUp(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from src.api import routes

        self._tmp = tempfile.TemporaryDirectory()
        self._orig = block_store.BLOCKS_DIR
        block_store.BLOCKS_DIR = Path(self._tmp.name)
        block_store._midi_path(self.NAME).write_bytes(b"MIDI-A")
        block_store._preview_path(self.NAME).write_bytes(b"MP3-A")
        block_store._wav_path(self.NAME).write_bytes(b"WAV-A")   # so instrumental resolves
        with open(block_store._yaml_path(self.NAME), "w") as f:
            yaml.safe_dump({"name": self.NAME, "n_notes": 10, "instruments": []}, f)

        api = FastAPI()
        api.include_router(routes.router)
        self.client = TestClient(api)

    def tearDown(self):
        block_store.BLOCKS_DIR = self._orig
        self._tmp.cleanup()

    def _fake_take(self, tid: str, created: str):
        import json
        d = block_store._vocals_dir(self.NAME) / tid
        d.mkdir(parents=True, exist_ok=True)
        (d / "mix.mp3").write_bytes(b"TAKE-MIX")
        (d / "meta.json").write_text(json.dumps(
            {"id": tid, "created": created, "files": {"mix": "mix.mp3"}}))

    def test_preview_take_switches_block_audio(self):
        # Default: the block plays its instrumental preview.
        self.assertEqual(self.client.get(f"/api/blocks/{self.NAME}/audio").content, b"MP3-A")
        self._fake_take("20260101-000000-000", "2026-01-01T00:00:00")
        r = self.client.post(f"/api/blocks/{self.NAME}/preview-take",
                             json={"take_id": "20260101-000000-000"})
        self.assertEqual(r.status_code, 200, r.text)
        # Now the block's play endpoint serves the chosen take's mix.
        self.assertEqual(self.client.get(f"/api/blocks/{self.NAME}/audio").content, b"TAKE-MIX")
        # Clearing reverts to the instrumental.
        self.client.post(f"/api/blocks/{self.NAME}/preview-take", json={"take_id": None})
        self.assertEqual(self.client.get(f"/api/blocks/{self.NAME}/audio").content, b"MP3-A")

    def test_history_exposes_preview_take(self):
        self._fake_take("20260101-000000-000", "2026-01-01T00:00:00")
        self.client.post(f"/api/blocks/{self.NAME}/preview-take",
                         json={"take_id": "20260101-000000-000"})
        h = self.client.get(f"/api/blocks/{self.NAME}/history").json()
        self.assertEqual(h["preview_take"], "20260101-000000-000")

    def test_snapshot_list_restore_delete_over_http(self):
        # empty
        self.assertEqual(self.client.get(f"/api/blocks/{self.NAME}/versions").json(),
                         {"versions": [], "active": None})
        # snapshot
        r = self.client.post(f"/api/blocks/{self.NAME}/versions", json={"label": "v1"})
        self.assertEqual(r.status_code, 200, r.text)
        vid = r.json()["version"]["id"]
        # list shows it active
        listing = self.client.get(f"/api/blocks/{self.NAME}/versions").json()
        self.assertEqual(listing["active"], vid)
        self.assertEqual(len(listing["versions"]), 1)
        # preview serves the mp3
        pv = self.client.get(f"/api/blocks/{self.NAME}/versions/{vid}/preview")
        self.assertEqual(pv.status_code, 200)
        self.assertEqual(pv.headers["content-type"], "audio/mpeg")
        # mutate live, then restore
        block_store._midi_path(self.NAME).write_bytes(b"MIDI-B")
        rr = self.client.post(f"/api/blocks/{self.NAME}/versions/{vid}/restore")
        self.assertEqual(rr.status_code, 200)
        self.assertEqual(block_store._midi_path(self.NAME).read_bytes(), b"MIDI-A")
        # delete
        self.assertEqual(self.client.delete(f"/api/blocks/{self.NAME}/versions/{vid}").status_code, 200)

    def test_restore_missing_404(self):
        r = self.client.post(f"/api/blocks/{self.NAME}/versions/ghost/restore")
        self.assertEqual(r.status_code, 404)

    def test_snapshot_missing_block_404(self):
        r = self.client.post("/api/blocks/ghost/versions", json={})
        self.assertEqual(r.status_code, 404)


if __name__ == "__main__":
    unittest.main(verbosity=2)
