"""The shared song tools (src/serve/song_tools.py) on real, short renders:
generate → revise → files → loudness → export (incl. onto a video), video
scoring, stems, blocks/versions, the arrangement catalog, and the HTTP tool
endpoint the local AI uses."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.api.jobs import registry
from src.composition import funk_fusion
from src.daw_integration.generic import blocks as block_store
from src.serve import song_tools
from src.serve.song_tools import ToolError

# A short Funk Fusion take: intro, a 4-bar verse, outro (about 17 s).
SHORT = dict(genre="funk_fusion_full", seed=52, sections=["intro", "verse", "outro"],
             section_overrides={"verse": {"bars": 4}})


class _Isolated(unittest.TestCase):
    """Job records go to a temp dir; job output dirs are removed afterwards."""

    @classmethod
    def setUpClass(cls):
        cls._records = Path(tempfile.mkdtemp(prefix="song_tools_rec_"))
        cls._orig_records = song_tools.RECORDS_DIR
        song_tools.RECORDS_DIR = cls._records
        cls.out = Path(tempfile.mkdtemp(prefix="song_tools_out_"))
        cls.jobs: list[str] = []

    @classmethod
    def tearDownClass(cls):
        song_tools.RECORDS_DIR = cls._orig_records
        shutil.rmtree(cls._records, ignore_errors=True)
        shutil.rmtree(cls.out, ignore_errors=True)
        from src.api.service import API_OUT
        for j in cls.jobs:
            shutil.rmtree(API_OUT / j, ignore_errors=True)

    def gen(self, **kw):
        res = song_tools.generate_song(**{**SHORT, **kw})
        self.jobs.append(res["job_id"])
        self.assertEqual(res["status"], "done", res)
        return res


class CatalogTests(unittest.TestCase):

    def test_catalog_matches_the_variants_the_code_reads(self):
        src = Path(funk_fusion.__file__).read_text()
        used = set(re.findall(r'"([a-z_]+)" (?:not )?in _arrangement\(ctx\)', src))
        used |= {f"calm_{p}" for p in re.findall(r'_calm\(ctx, "([a-z]+)"\)', src)}
        used |= set(re.findall(r'return "([a-z_]+)" in _arrangement', src))
        used |= {"calm"}
        self.assertTrue(used)
        self.assertEqual(used - set(funk_fusion.ARRANGEMENT_VARIANTS), set(),
                         "variant read by funk_fusion.py but missing from ARRANGEMENT_VARIANTS")
        self.assertEqual(set(funk_fusion.ARRANGEMENT_VARIANTS) - used, set(),
                         "catalogued variant that no code reads")

    def test_unknown_variant_is_rejected_with_a_suggestion(self):
        with self.assertRaises(ToolError) as cm:
            song_tools.generate_song(genre="funk_fusion_full", arrangement="hits_only,pocket_drum", wait=False)
        self.assertIn("pocket_drums", str(cm.exception))

    def test_unknown_genre_lead_and_hit_style(self):
        with self.assertRaises(ToolError) as cm:
            song_tools.generate_song(genre="funk_fusion", wait=False)
        self.assertIn("funk_fusion_full", str(cm.exception))
        with self.assertRaises(ToolError):
            song_tools.generate_song(lead_patch="kazoo", wait=False)
        with self.assertRaises(ToolError) as cm:                  # a variant given as a lead voice
            song_tools.generate_song(lead_patch="brushes", wait=False)
        self.assertIn("arrangement", str(cm.exception))
        with self.assertRaises(ToolError) as cm:                  # a lead voice given as a variant
            song_tools.generate_song(arrangement="calm,horns", wait=False)
        self.assertIn("lead_patch", str(cm.exception))
        with self.assertRaises(ToolError):
            song_tools.generate_song(hit_style="smash", wait=False)

    def test_call_validates_and_coerces_like_mcp(self):
        out = song_tools.call("list_styles", {"query": "neo"})
        self.assertTrue(any(s["name"] == "neo_soul_full" for s in out))
        with self.assertRaises(ToolError) as cm:
            song_tools.call("generate_song", {"genre": "funk_fusion_full", "bogus": 1})
        self.assertIn("bogus", str(cm.exception))
        with self.assertRaises(ToolError):
            song_tools.call("generate_song", {"tempo": "fast"})
        with self.assertRaises(ToolError) as cm:                  # null means "not given"
            song_tools.call("generate_song", {"genre": None, "arrangement": None, "lead_patch": "kazoo"})
        self.assertIn("kazoo", str(cm.exception))
        with self.assertRaises(ToolError):
            song_tools.call("no_such_tool", {})


class GenerateReviseTests(_Isolated):

    def test_generate_revise_files_loudness_export(self):
        first = self.gen(arrangement="hits_only,calm")
        self.assertEqual(first["seed"], 52)
        self.assertEqual(first["bars"], 10)
        wav = Path(first["files"]["audio_wav"])
        self.assertTrue(wav.exists())
        self.assertTrue(Path(first["files"]["midi"]).exists())
        self.assertGreater(first["duration_seconds"], 10)

        # Revise: keeps the seed, swaps one variant, records its parent.
        rev = song_tools.revise(first["job_id"], {"tempo": 120,
                                                  "arrangement_add": ["brushes"],
                                                  "arrangement_remove": ["calm"]})
        self.jobs.append(rev["job_id"])
        self.assertEqual(rev["status"], "done", rev)
        self.assertEqual(rev["seed"], 52)
        self.assertEqual(rev["tempo"], 120.0)
        self.assertEqual(rev["revised_from"], first["job_id"])
        self.assertEqual(rev["params"]["arrangement"], "hits_only,brushes")
        listed = song_tools.list_jobs(limit=5)
        self.assertEqual(listed[0]["job_id"], rev["job_id"])
        self.assertEqual(listed[0]["revised_from"], first["job_id"])

        # A new seed is a different take.
        other = song_tools.revise(first["job_id"], {}, new_seed=True)
        self.jobs.append(other["job_id"])
        self.assertNotEqual(other["seed"], 52)

        files = song_tools.get_job_files(rev["job_id"])
        self.assertTrue(Path(files["files"]["audio_wav"]).exists())

        loud = song_tools.measure_loudness(rev["job_id"])
        self.assertLess(loud["lufs"], -5)
        self.assertGreater(loud["duration_seconds"], 10)

        out = song_tools.export_audio(rev["job_id"], dest_dir=str(self.out), name="bed", target_lufs=-25)
        self.assertAlmostEqual(out["lufs"], -25, delta=0.6)
        self.assertTrue(Path(out["files"]["wav"]).exists())
        self.assertTrue(Path(out["files"]["mp3"]).exists())
        self.assertAlmostEqual(song_tools.measure_loudness(out["files"]["wav"])["lufs"], -25, delta=0.6)
        with self.assertRaises(ToolError):                      # no silent overwrite
            song_tools.export_audio(rev["job_id"], dest_dir=str(self.out), name="bed")

    def test_job_survives_a_restart(self):
        res = self.gen(arrangement="hits_only,calm_keys,simple_bass")
        # Wait for the record writer, then forget the in-memory job.
        import time
        for _ in range(40):
            if (song_tools._load_record(res["job_id"]) or {}).get("result"):
                break
            time.sleep(0.1)
        with registry._lock:
            registry._jobs.pop(res["job_id"])
        again = song_tools.job_status(res["job_id"])
        self.assertEqual(again["status"], "done")
        self.assertEqual(again["files"]["audio_wav"], res["files"]["audio_wav"])

    def test_extra_instruments_from_variants(self):
        # The French horn plays in choruses, so give the take one.
        res = self.gen(arrangement="hits_only,calm,soar", sections=["intro", "chorus", "outro"],
                       section_overrides={"chorus": {"bars": 4}})
        midi = res["files"]["midi"]
        import pretty_midi
        names = {i.name for i in pretty_midi.PrettyMIDI(midi).instruments}
        self.assertTrue(any("String" in n for n in names), names)
        self.assertTrue(any("Horn" in n for n in names), names)

    def test_options_a_style_would_ignore_are_errors(self):
        with self.assertRaises(ToolError) as cm:
            song_tools.generate_song(genre="funk", arrangement="calm", wait=False)
        self.assertIn("funk_fusion_full", str(cm.exception))
        with self.assertRaises(ToolError):
            song_tools.generate_song(genre="pop", hits=[2.0], wait=False)

    def test_length_seconds_and_section_roles(self):
        res = self.gen(arrangement="hits_only,calm", tempo=120, length_seconds=30,
                       sections=[], section_overrides={})
        self.assertAlmostEqual(res["bars"], 15, delta=2)          # 30 s at 120 BPM
        with self.assertRaises(ToolError) as cm:
            song_tools.generate_song(sections=["intro", "guitar_lead"], wait=False)
        self.assertIn("lead_patch", str(cm.exception))

    def test_unknown_job(self):
        with self.assertRaises(ToolError):
            song_tools.job_status("nope")
        with self.assertRaises(ToolError):
            song_tools.revise("nope", {})


class ScoreVideoTests(_Isolated):

    def test_score_onto_a_video(self):
        video = self.out / "clip.mp4"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                        "color=c=blue:s=160x90:d=12", "-pix_fmt", "yuv420p", str(video)], check=True)
        res = song_tools.score_video(
            video_path=str(video), base_tempo=120, hits=[], target_lufs=-25,
            arrangement="hits_only,calm_keys,calm_bass,pocket_drums,no_falloff",
            chapters=[{"start": 0, "roles": ["chorus"], "intro": False},
                      {"start": 6.0, "roles": ["verse"]}])
        self.jobs.append(res["job_id"])
        self.assertEqual(res["status"], "done", res)
        self.assertAlmostEqual(res["duration_seconds"], 12.0, delta=0.1)
        self.assertAlmostEqual(res["loudness_lufs"], -25, delta=0.6)
        self.assertEqual(len(res["chapters"]), 2)

        rev = song_tools.revise(res["job_id"], {"arrangement_add": ["brushes"]})
        self.jobs.append(rev["job_id"])
        self.assertEqual(rev["status"], "done", rev)
        self.assertIn("brushes", rev["params"]["arrangement"])

        out = song_tools.export_audio(rev["job_id"], dest_dir=str(self.out), name="scored",
                                      formats=["mp3"], video_path=str(video))
        mp4 = Path(out["files"]["mp4"])
        self.assertTrue(mp4.exists())
        self.assertFalse((self.out / "scored.wav").exists())       # only what was asked for
        probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type",
                                "-of", "csv=p=0", str(mp4)], capture_output=True, text=True)
        self.assertEqual(sorted(probe.stdout.split()), ["audio", "video"])

    def test_needs_a_duration(self):
        with self.assertRaises(ToolError):
            song_tools.score_video(chapters=[{"start": 0}], wait=False)


class BlockTests(_Isolated):

    def setUp(self):
        self.name = f"song-tools-test-{uuid.uuid4().hex[:6]}"
        self.made: list[str] = []

    def tearDown(self):
        for n in self.made:
            try:
                block_store.delete_block(n)
            except Exception:  # noqa: BLE001
                pass
            shutil.rmtree(block_store.BLOCKS_DIR / f"{block_store._safe_name(n)}.versions", ignore_errors=True)

    def test_save_rename_tag_versions_stems(self):
        res = self.gen(arrangement="hits_only,calm")
        saved = song_tools.save_block(res["job_id"], self.name)["name"]
        self.made.append(saved)
        listed = song_tools.list_blocks(query=self.name)
        self.assertEqual(listed[0]["name"], block_store._safe_name(saved))
        self.assertEqual(listed[0]["genre"], "funk_fusion_full")

        snap = song_tools.snapshot_block_version(saved, label="first take")
        vid = snap["version"]["id"]
        versions = song_tools.list_block_versions(saved)
        self.assertIn(vid, [v["id"] for v in versions["versions"]])
        restored = song_tools.restore_block_version(saved, vid)
        self.assertTrue(restored)

        tags = song_tools.set_block_tags(saved, ["mcp-test"])
        self.assertEqual(tags["tags"], ["mcp-test"])
        self.assertEqual(song_tools.list_blocks(tag="mcp-test")[0]["name"], block_store._safe_name(saved))

        new = song_tools.rename_block(saved, self.name + "-b")["name"]
        self.made.append(new)
        self.assertTrue(block_store._midi_path(new).exists())

        stems = song_tools.render_stems(res["job_id"])
        self.assertTrue(Path(stems["mix"]).exists())
        self.assertGreaterEqual(len(stems["stems"]), 3)

        with self.assertRaises(ToolError):
            song_tools.rename_block("no-such-block-xyz", "x")


class HttpEndpointTests(_Isolated):

    def test_tools_over_http(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from src.api import router

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        listing = client.get("/api/tools").json()
        names = [t["name"] for t in listing]
        self.assertIn("generate_song", names)
        gen = next(t for t in listing if t["name"] == "generate_song")
        self.assertIn("arrangement", gen["input_schema"]["properties"])

        r = client.post("/api/tools/generate_song", json={**SHORT, "arrangement": "hits_only,calm",
                                                          "tempo": "120"})
        self.assertEqual(r.status_code, 200, r.text)
        res = r.json()["result"]
        self.jobs.append(res["job_id"])
        self.assertEqual(res["status"], "done")
        self.assertIn("audio", res["urls"])
        audio = client.get(res["urls"]["audio"].replace("http://testserver", ""))
        self.assertEqual(audio.status_code, 200)
        self.assertGreater(len(audio.content), 10_000)

        bad = client.post("/api/tools/generate_song", json={"arrangement": "loud"})
        self.assertEqual(bad.status_code, 400)
        self.assertIn("Valid:", bad.json()["detail"])
        self.assertEqual(client.post("/api/tools/nope", json={}).status_code, 404)


if __name__ == "__main__":
    unittest.main(verbosity=2)
