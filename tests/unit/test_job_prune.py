"""Pruning old job dirs never loses recent work: jobs saved to a block (or
split into blocks) count against the limit and get pruned, oldest first;
unsaved jobs stay until nothing has touched them for a week; the caches
(``_guides``, ``_regen``, any ``_*`` dir) always stay. A batch session lost
renders that pruning removed before they were saved."""

from __future__ import annotations

import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import pretty_midi

from src.api import service


class JobPruneTests(unittest.TestCase):

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="prune_"))
        self.api = self.root / "api"
        self.api.mkdir()
        patcher = mock.patch.object(service, "API_OUT", self.api)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(shutil.rmtree, self.root, True)

    def _job(self, name: str, age: int, saved: bool = False) -> Path:
        """A job dir last touched ``age`` seconds ago (everything in it too)."""
        d = self.api / name
        (d / "render").mkdir(parents=True)
        (d / "song.mid").write_bytes(b"")
        if saved:
            service.mark_job_saved(d / "song.mid")
        t = time.time() - age
        for p in [*d.rglob("*"), d]:
            os.utime(p, (t, t))
        return d

    def test_only_saved_jobs_are_pruned_oldest_first(self):
        saved = [self._job(f"saved{i}", age=100 - i, saved=True) for i in range(5)]
        unsaved = [self._job(f"unsaved{i}", age=200 + i) for i in range(5)]
        service._prune_old_job_dirs(keep=2)
        self.assertEqual(sorted(p.name for p in self.api.iterdir()),
                         sorted([p.name for p in unsaved] + ["saved3", "saved4"]))

    def test_unsaved_jobs_go_after_a_week_untouched(self):
        day = 86400
        old = self._job("old_unsaved", age=8 * day)
        fresh = self._job("fresh_unsaved", age=6 * day)
        stale_saved = self._job("old_saved", age=30 * day, saved=True)
        touched = self._job("old_but_rerendered", age=9 * day)
        (touched / "render" / "mix.wav").write_bytes(b"")          # touched just now
        self.assertEqual(service.expired_unsaved_jobs(), [old])
        service._prune_old_job_dirs(keep=10)
        self.assertFalse(old.exists())
        self.assertTrue(fresh.exists() and stale_saved.exists() and touched.exists())
        self.assertEqual(service.expired_unsaved_jobs(ttl_days=5), [fresh])

    def test_caches_are_never_pruned(self):
        caches = [self.api / n for n in ("_guides", "_regen", "_mix_previews", "_live_stems", "_other")]
        for d in caches:
            d.mkdir()
            (d / service._SAVED_MARK).touch()          # even a marked cache stays
            os.utime(d / service._SAVED_MARK, (1, 1))
            os.utime(d, (1, 1))
        stale = self.api / "_stale_cache"                  # an unmarked, years-old cache stays too
        stale.mkdir()
        os.utime(stale, (1, 1))
        caches.append(stale)
        self._job("saved", age=0, saved=True)
        service._prune_old_job_dirs(keep=0)
        self.assertTrue(all(d.is_dir() for d in caches))
        self.assertFalse((self.api / "saved").exists())

    def test_marking_ignores_paths_outside_the_jobs(self):
        outside = self.root / "elsewhere" / "x.mid"
        outside.parent.mkdir()
        service.mark_job_saved(outside)
        self.assertFalse((outside.parent / service._SAVED_MARK).exists())
        job = self._job("job", age=0)
        service.mark_job_saved(job / "render" / "mix.wav")         # a nested file marks its job
        self.assertTrue((job / service._SAVED_MARK).exists())

    def test_saving_a_job_as_a_block_marks_it(self):
        job = self._job("gen", age=0)
        pm = pretty_midi.PrettyMIDI()
        inst = pretty_midi.Instrument(0, name="Piano")
        inst.notes.append(pretty_midi.Note(80, 60, 0.0, 1.0))
        pm.instruments.append(inst)
        pm.write(str(job / "song.mid"))
        from src.daw_integration.generic import blocks as block_store
        with mock.patch.object(block_store, "save_block") as save, \
                mock.patch.object(service, "_unique_block_name", lambda _s, n: n):
            service.save_job_as_block({"_paths": {"midi": str(job / "song.mid")}, "tempo": 100, "bars": 1}, "Gen")
        save.assert_called_once()
        self.assertTrue((job / service._SAVED_MARK).exists())


if __name__ == "__main__":
    unittest.main()
