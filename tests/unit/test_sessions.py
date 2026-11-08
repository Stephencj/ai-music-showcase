"""Create sessions on the server (src/api/sessions.py): atomic storage, the
browser-thread migration, merging a client's copy, auto-saving every finished
version as a Practice block, the render cache, re-registering versions after
a restart and rendering them again on demand, opening a library block in the
Timeline, and the REST routes."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import pretty_midi
import soundfile as sf
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.api import jobs, routes, sessions  # noqa: E402
from src.api import session_routes  # noqa: E402
from src.daw_integration.generic import blocks, library  # noqa: E402

XMAS_SPEC = {
    "genre": "christmas_pop_full", "key": "A", "scale": "major", "tempo": 89.0,
    "time_signature": [4, 4], "seed": 446200, "swing": None, "instruments": [],
    "section_presets": {}, "section_overrides": {},
    "sections": [{"start_bar": 0, "end_bar": 3, "label": "Intro", "role": "intro", "energy": 0.62},
                 {"start_bar": 4, "end_bar": 35, "label": "Final 1", "role": "chorus", "energy": 0.92},
                 {"start_bar": 36, "end_bar": 42, "label": "Outro", "role": "outro", "energy": 0.8}],
    "progression": [], "section": None, "tune": "original", "arrangement": "",
}


def _pm(seconds: float = 2.0) -> pretty_midi.PrettyMIDI:
    pm = pretty_midi.PrettyMIDI()
    inst = pretty_midi.Instrument(program=0)
    inst.notes.append(pretty_midi.Note(velocity=90, pitch=60, start=0.0, end=seconds))
    pm.instruments.append(inst)
    return pm


class _Base(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.dir = Path(self.td.name)
        for target, attr, value in (
            (sessions, "SESSIONS_DIR", self.dir / "sessions"),
            (sessions, "RENDERS_DIR", self.dir / "sessions" / "renders"),
            (blocks, "BLOCKS_DIR", self.dir / "blocks"),
            (library, "LIBRARY_DIR", self.dir / "library"),
        ):
            p = mock.patch.object(target, attr, value)
            p.start()
            self.addCleanup(p.stop)
        # A fresh job registry: a "restart" is just another fresh one.
        self.registry = jobs.JobRegistry()
        for mod in (sessions, routes):
            p = mock.patch.object(mod, "registry", self.registry)
            p.start()
            self.addCleanup(p.stop)
        # No background watchers in tests; finalize is called explicitly.
        p = mock.patch.object(sessions, "_watch")
        p.start()
        self.addCleanup(p.stop)

    def finished_job(self, seed: int = 1234, n_secs: int = 2) -> str:
        """A done generation job with real files (MIDI, WAV, MP3)."""
        job = self.registry.create()
        d = self.dir / "outputs" / job.id
        d.mkdir(parents=True)
        midi = d / "song.mid"
        _pm(n_secs).write(str(midi))
        t = np.arange(44100 * n_secs) / 44100
        tone = (0.3 * np.sin(2 * np.pi * 440 * t)).astype("float32")
        wav = d / "mix.wav"
        sf.write(wav, np.stack([tone, tone], axis=1), 44100)
        mp3 = d / "mix.mp3"
        self.assertTrue(blocks.write_preview_mp3(wav, mp3))
        job.status, job.progress = "done", 1.0
        job.result = {
            "seed": seed, "genre": "funk_fusion_full", "bars": 2, "key": "Eb", "scale": "major",
            "tempo": 120.0, "time_signature": [4, 4], "summary": "",
            "sections": [{"label": "Intro", "role": "intro", "bars": 1},
                         {"label": "Verse", "role": "verse", "bars": 1}],
            "saved_block": None, "section_blocks": [],
            "_paths": {"midi": str(midi), "audio_wav": str(wav), "audio_mp3": str(mp3), "pdf": None},
            "_split": {"tempo": 120.0, "time_signature": [4, 4], "sections": [
                {"start_bar": 0, "end_bar": 0, "label": "Intro", "role": "intro"},
                {"start_bar": 1, "end_bar": 1, "label": "Verse", "role": "verse"}]},
            "_spec": {"genre": "funk_fusion_full", "seed": seed, "sections": []},
        }
        return job.id

    def thread(self, job_id: str, title: str = "Background bed for a product video") -> dict:
        return sessions.create(title=title, msgs=[
            {"id": "m1", "role": "user", "text": title},
            {"id": "m2", "role": "app", "kind": "describe", "interpreter": "rules", "version": 1},
        ], versions=[{"n": 1, "plan": {"genre": "funk_fusion_full"}, "jobId": job_id,
                      "status": "done", "progress": 1, "message": ""}])


class NamingTests(unittest.TestCase):
    def test_clean_title_cuts_at_a_word_without_an_ellipsis(self):
        self.assertEqual(sessions.clean_title("Background bed for a…"), "Background bed for a")
        long = "A funk fusion background bed for a product video with horns"
        t = sessions.clean_title(long)
        self.assertLessEqual(len(t), sessions.TITLE_LIMIT)
        self.assertTrue(long.startswith(t))
        self.assertTrue(long[len(t)] == " ", "cut at a word boundary")
        self.assertNotIn("…", t)
        self.assertEqual(sessions.clean_title(""), "Song")
        self.assertEqual(sessions.clean_title("Supercalifragilisticexpialidocious" * 2)[:5], "Super")

    def test_version_block_name(self):
        self.assertEqual(sessions.version_block_name("Background bed for a…", 3), "Background bed for a v3")
        self.assertEqual(sessions.version_block_name(None, 1), "Song v1")


class StorageTests(_Base):
    def test_atomic_write_never_leaves_half_a_file(self):
        s = sessions.create(title="Keep me", msgs=[{"id": "a", "role": "user", "text": "hi"}])
        p = sessions._path(s["id"])
        before = p.read_text()
        with mock.patch.object(sessions.json, "dump", side_effect=RuntimeError("disk full")):
            with self.assertRaises(RuntimeError):
                sessions.update(s["id"], title="Broken")
        self.assertEqual(p.read_text(), before)
        self.assertEqual(json.loads(before)["title"], "Keep me")
        self.assertEqual([x.name for x in p.parent.iterdir() if x.name.endswith(".tmp")], [])

    def test_bad_ids_are_not_found(self):
        for sid in ("../etc", "", "a/b"):
            with self.assertRaises(sessions.SessionNotFound):
                sessions.get(sid)

    def test_list_skips_empty_and_sorts_newest_first(self):
        sessions.create(title="")
        a = sessions.create(title="A", msgs=[{"id": "1", "role": "user", "text": "a"}])
        b = sessions.create(title="B", msgs=[{"id": "1", "role": "user", "text": "b"}])
        with mock.patch.object(sessions, "_now", return_value="2099-01-01T00:00:00"):
            sessions.rename(a["id"], "A renamed")
        rows = sessions.list_sessions()
        self.assertEqual([r["id"] for r in rows], [a["id"], b["id"]])
        self.assertEqual(rows[0]["title"], "A renamed")


class MigrationAndMergeTests(_Base):
    def test_browser_thread_migrates_with_its_library_saves(self):
        legacy = {
            "title": "Old song", "interpreter": "claude",
            "msgs": [{"id": "x1", "role": "user", "text": "funk"},
                     {"id": "x2", "role": "app", "kind": "describe", "version": 1, "interpreter": "claude"},
                     {"id": "x3", "role": "app", "kind": "revise", "version": 2, "changes": ["tempo: 120 → 100"]}],
            "versions": [
                {"n": 1, "plan": {"genre": "funk_fusion_full", "seed": 7}, "jobId": "gone1", "status": "done",
                 "progress": 1, "message": "", "savedAs": "Old song v1",
                 "result": {"seed": 7, "urls": {"audio": "/api/jobs/gone1/audio"}, "_paths": {"midi": "/x"}}},
                {"n": 2, "plan": {"genre": "funk_fusion_full", "seed": 7, "tempo": 100}, "jobId": "gone2",
                 "status": "done", "progress": 1, "message": ""},
            ],
        }
        s = sessions.create(**legacy)
        stored = json.loads(sessions._path(s["id"]).read_text())
        v1, v2 = stored["versions"]
        self.assertEqual(v1["block"], "Old song v1")              # its library block is its audio
        self.assertNotIn("_paths", v1["result"])                   # private job fields stay out
        self.assertEqual(v2["changes"], ["tempo: 120 → 100"])
        self.assertEqual(v2["seed"], 7)
        # The jobs died with the old process and there's no audio left: re-render on demand.
        self.assertEqual(v2["audio"], "missing")
        self.assertEqual([m["id"] for m in stored["msgs"]], ["x1", "x2", "x3"])

    def test_client_copy_never_overwrites_server_fields(self):
        jid = self.finished_job()
        s = self.thread(jid)
        sessions.finalize(s["id"], 1)
        block = sessions.get(s["id"])["versions"][0]["block"]
        # A stale client copy: still "running", no block, and an extra message.
        out = sessions.update(s["id"], msgs=[{"id": "m1", "role": "user", "text": "edited"},
                                             {"id": "m3", "role": "user", "text": "more"}],
                              versions=[{"n": 1, "plan": {"genre": "funk_fusion_full", "seed": 1234}, "jobId": jid,
                                         "status": "running", "progress": 0.5, "block": None}])
        v = out["versions"][0]
        self.assertEqual(v["status"], "done")
        self.assertEqual(v["block"], block)
        self.assertEqual([m["id"] for m in out["msgs"]], ["m1", "m3", "m2"])
        self.assertEqual(out["msgs"][0]["text"], "edited")

    def test_a_copy_of_an_old_job_cant_report_on_a_new_one(self):
        cur = {"n": 1, "jobId": "new", "status": "running"}
        merged = sessions._merge_version(cur, {"n": 1, "jobId": "old", "status": "done", "result": {"seed": 1}})
        self.assertEqual((merged["jobId"], merged["status"]), ("new", "running"))
        self.assertNotIn("result", merged)


class FinalizeTests(_Base):
    def test_finished_version_is_auto_saved_for_practice_and_cached(self):
        jid = self.finished_job()
        s = self.thread(jid, title="Background bed for a…")
        v = sessions.finalize(s["id"], 1)
        self.assertEqual(v["block"], "Background_bed_for_a_v1")
        meta = blocks.read_meta(v["block"])
        self.assertIn(sessions.AUTO_TAG, meta["tags"])
        self.assertEqual(meta["session"], {"id": s["id"], "version": 1})
        self.assertTrue(blocks._preview_path(v["block"]).exists())    # playable in Practice
        self.assertEqual(library.list_entries(), [])                    # not in the Library
        cache = sessions._render_dir(s["id"], 1)
        self.assertTrue((cache / "mix.mp3").exists() and (cache / "song.mid").exists())
        self.assertEqual(v["seed"], 1234)
        self.assertEqual(v["plan"]["seed"], 1234)
        # Idempotent: a second finalize makes no second block.
        sessions.finalize(s["id"], 1)
        self.assertEqual([b["name"] for b in blocks.list_blocks()], ["Background_bed_for_a_v1"])

    def test_save_to_library_links_the_block(self):
        jid = self.finished_job()
        s = self.thread(jid, title="Bed")
        r = sessions.save_to_library(s["id"], 1)
        self.assertEqual(r["entry"]["block_name"], "Bed_v1")
        self.assertEqual(r["entry"]["title"], "Bed v1")
        self.assertEqual(r["version"]["savedAs"], "Bed_v1")
        self.assertEqual(sessions.timeline_status(blocks.read_meta("Bed_v1"))["session_id"], s["id"])

    def test_restart_readopts_from_the_block_then_the_cache_then_renders_again(self):
        jid = self.finished_job()
        s = self.thread(jid, title="Bed")
        sessions.finalize(s["id"], 1)
        # Restart: the job registry is empty again.
        fresh = jobs.JobRegistry()
        with mock.patch.object(sessions, "registry", fresh), mock.patch.object(routes, "registry", fresh):
            v = sessions.get(s["id"])["versions"][0]
            self.assertNotIn("audio", v)
            self.assertEqual(fresh.get(jid).result["_paths"]["midi"], str(blocks._midi_path("Bed_v1")))
            self.assertEqual(routes.job_status(jid)["result"]["urls"]["audio"], f"/api/jobs/{jid}/audio")
        # Block deleted: the render cache still has it.
        blocks.delete_block("Bed_v1")
        fresh = jobs.JobRegistry()
        with mock.patch.object(sessions, "registry", fresh), mock.patch.object(routes, "registry", fresh):
            v = sessions.get(s["id"])["versions"][0]
            self.assertNotIn("audio", v)
            self.assertTrue(fresh.get(jid).result["_paths"]["audio_mp3"].endswith("mix.mp3"))
            peaks = routes.job_peaks(jid, 32)
            self.assertEqual(len(peaks["peaks"]), 32)
        # Cache gone too: the version says so and renders again from its plan + seed.
        sessions.prune_cache(limit_mb=0)
        fresh = jobs.JobRegistry()
        with mock.patch.object(sessions, "registry", fresh), mock.patch.object(routes, "registry", fresh):
            v = sessions.get(s["id"])["versions"][0]
            self.assertEqual(v["audio"], "missing")
            self.assertIsNone(v["result"]["urls"]["audio"])
            with mock.patch.object(routes, "generate", return_value={"job_id": "rerender1"}) as gen:
                v = sessions.render(s["id"], 1)
            body = gen.call_args.args[0]
            self.assertEqual(body.seed, 1234)
            self.assertEqual(body.genre, "funk_fusion_full")
            self.assertEqual((v["jobId"], v["status"]), ("rerender1", "running"))
            self.assertNotIn("audio", v)

    def test_cache_is_pruned_oldest_first(self):
        for sid, size in (("s-old", 3), ("s-mid", 3), ("s-new", 3)):
            d = sessions.RENDERS_DIR / sid / "v1"
            d.mkdir(parents=True)
            (d / "mix.mp3").write_bytes(b"x" * size * 1024 * 1024)
        import os
        import time
        now = time.time()
        for k, sid in enumerate(("s-old", "s-mid", "s-new")):
            os.utime(sessions.RENDERS_DIR / sid / "v1", (now - 100 + k, now - 100 + k))
        removed = sessions.prune_cache(limit_mb=7)
        self.assertEqual(removed, ["s-old/v1"])
        self.assertFalse((sessions.RENDERS_DIR / "s-old").exists())
        self.assertTrue((sessions.RENDERS_DIR / "s-new" / "v1").exists())

    def test_delete_removes_auto_saved_versions_but_keeps_library_ones(self):
        j1, j2 = self.finished_job(), self.finished_job()
        s = sessions.create(title="Bed", versions=[
            {"n": 1, "plan": {"genre": "funk_fusion_full"}, "jobId": j1, "status": "done"},
            {"n": 2, "plan": {"genre": "funk_fusion_full"}, "jobId": j2, "status": "done"}])
        sessions.finalize(s["id"], 1)
        sessions.finalize(s["id"], 2)
        sessions.save_to_library(s["id"], 2)
        out = sessions.delete(s["id"])
        self.assertEqual(out["blocks_removed"], ["Bed_v1"])
        self.assertIsNone(blocks.read_meta("Bed_v1"))
        self.assertNotIn("session", blocks.read_meta("Bed_v2"))       # kept, unlinked
        self.assertFalse(sessions.exists(s["id"]))
        self.assertFalse((sessions.RENDERS_DIR / s["id"]).exists())


class FromBlockTests(_Base):
    def save_block(self, name: str, spec) -> None:
        blocks.save_block(name, _pm(), tempo=89, time_signature=(4, 4), bars=43, spec=spec, write_wav=False)
        sr = 22050
        t = np.arange(sr * 2) / sr
        sf.write(blocks._wav_path(name), np.sin(2 * np.pi * 220 * t).astype("float32"), sr)

    def test_christmas_sample_opens_as_v1_with_its_audio_and_seed(self):
        self.save_block("Xmas_Original_(Pop)", XMAS_SPEC)
        r = sessions.from_block("Xmas_Original_(Pop)")
        s, v = r["session"], r["session"]["versions"][0]
        self.assertEqual(r["version"], 1)
        self.assertEqual(s["title"], "Xmas Original (Pop)")
        self.assertEqual(v["plan"]["tune"], "original")
        self.assertEqual(v["plan"]["seed"], 446200)
        self.assertNotIn("key", v["plan"])                 # the tune's own key (asking would re-draw)
        self.assertEqual([x["role"] for x in v["result"]["sections"]], ["intro", "chorus", "outro"])
        self.assertEqual([x["bars"] for x in v["result"]["sections"]], [4, 32, 7])
        self.assertEqual(v["block"], "Xmas_Original_(Pop)")
        self.assertEqual(self.registry.get(v["jobId"]).result["_paths"]["audio_wav"],
                         str(blocks._wav_path("Xmas_Original_(Pop)")))
        self.assertEqual(s["msgs"][0]["kind"], "opened")
        # Linked: opening it again goes back to the same session.
        self.assertEqual(sessions.from_block("Xmas_Original_(Pop)")["session"]["id"], s["id"])
        # Deleting that session keeps the user's own block, just unlinked.
        sessions.delete(s["id"])
        self.assertIsNotNone(blocks.read_meta("Xmas_Original_(Pop)"))
        self.assertNotIn("session", blocks.read_meta("Xmas_Original_(Pop)"))

    def test_blocks_without_a_spec_say_why(self):
        self.save_block("Hummed", None)
        self.assertEqual(sessions.timeline_status(blocks.read_meta("Hummed")),
                         {"ok": False, "reason": "No generation settings were saved with it"})
        with self.assertRaises(sessions.SessionError):
            sessions.from_block("Hummed")
        self.save_block("Guessed", {"genre": "pop", "inferred": True})
        self.assertFalse(sessions.timeline_status(blocks.read_meta("Guessed"))["ok"])


class SongToolTests(FromBlockTests):
    """The MCP / HTTP song tools that let Claude continue a song's thread."""

    def test_open_list_get_and_revise_a_session(self):
        from src.api import describe
        from src.serve import song_tools
        self.save_block("Xmas_Original_(Pop)", XMAS_SPEC)
        opened = song_tools.call("open_block_as_session", {"block": "Xmas_Original_(Pop)"})
        sid = opened["session_id"]
        self.assertEqual(opened["versions"][0]["sections"][1], "Final 1 (32 bars)")
        self.assertEqual([r["id"] for r in song_tools.call("list_sessions", {})], [sid])
        revised = {"plan": {**opened["versions"][0]["plan"], "arrangement": "sleigh_bells"},
                   "summary": "Added sleigh bells", "changes": ["arrangement: +sleigh_bells"],
                   "notes": [], "interpreter": "rules"}
        job2 = self.registry.create()
        job2.status = "running"
        with mock.patch.object(describe, "revise", return_value=revised) as rev, \
                mock.patch.object(routes, "generate", return_value={"job_id": job2.id}) as gen:
            out = song_tools.call("revise_session", {"session": sid, "feedback": "add sleigh bells", "wait": False})
        self.assertEqual(rev.call_args.args[0]["seed"], 446200)
        self.assertEqual(gen.call_args.args[0].seed, 446200)           # same seed: only the change differs
        self.assertEqual(gen.call_args.args[0].tune, "original")
        self.assertEqual((out["version"]["n"], out["version"]["made_from"], out["version"]["status"]), (2, 1, "running"))
        thread = song_tools.call("get_session", {"session": sid})
        self.assertEqual([m["role"] for m in thread["messages"]], ["app", "user", "app"])
        self.assertEqual(thread["messages"][2]["version"], 2)
        self.assertEqual(thread["versions"][1]["changes"], ["arrangement: +sleigh_bells"])
        with self.assertRaises(song_tools.ToolError):
            song_tools.call("get_session", {"session": "nope"})


class RouteTests(_Base):
    def setUp(self):
        super().setUp()
        api = FastAPI()
        api.include_router(routes.router)
        api.include_router(session_routes.router, prefix="/api")
        self.client = TestClient(api)

    def test_crud(self):
        c = self.client
        r = c.post("/api/sessions", json={"title": "Hello", "msgs": [{"id": "1", "role": "user", "text": "hi"}]})
        self.assertEqual(r.status_code, 200)
        sid = r.json()["id"]
        self.assertEqual(c.get(f"/api/sessions/{sid}").json()["title"], "Hello")
        r = c.put(f"/api/sessions/{sid}", json={"msgs": [{"id": "1", "role": "user", "text": "hi"},
                                                         {"id": "2", "role": "app", "kind": "describe"}]})
        self.assertEqual(len(r.json()["msgs"]), 2)
        r = c.post(f"/api/sessions/{sid}/append", json={"msgs": [{"role": "user", "text": "more"}]})
        self.assertEqual(len(r.json()["msgs"]), 3)
        self.assertTrue(r.json()["msgs"][2]["id"])
        self.assertEqual(c.post(f"/api/sessions/{sid}/rename", json={"title": "Bye"}).json()["title"], "Bye")
        self.assertEqual(c.post(f"/api/sessions/{sid}/rename", json={"title": " "}).status_code, 400)
        rows = c.get("/api/sessions").json()["sessions"]
        self.assertEqual([(x["id"], x["title"], x["version_count"]) for x in rows], [(sid, "Bye", 0)])
        self.assertEqual(c.delete(f"/api/sessions/{sid}").json()["deleted"], sid)
        self.assertEqual(c.get(f"/api/sessions/{sid}").status_code, 404)
        self.assertEqual(c.post("/api/sessions/from-block", json={"block": "nope"}).status_code, 404)

    def test_library_and_blocks_say_whether_they_open_in_the_timeline(self):
        blocks.save_block("Hummed", _pm(), tempo=90, time_signature=(4, 4), bars=1, write_wav=False)
        library.add_entry("Hummed")
        lib = self.client.get("/api/library").json()["library"]
        self.assertEqual(lib[0]["timeline"]["ok"], False)
        listed = self.client.get("/api/blocks").json()
        self.assertEqual(listed[0]["timeline"]["reason"], "No generation settings were saved with it")


if __name__ == "__main__":
    unittest.main()
