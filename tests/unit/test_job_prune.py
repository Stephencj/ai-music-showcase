"""Pruning old job dirs never loses work: only jobs saved to a block (or
split into blocks) count against the limit and get pruned, oldest first;
unsaved jobs and the caches (``_guides``, ``_regen``, any ``_*`` dir) stay.
A batch session lost renders that pruning removed before they were saved."""

from __future__ import annotations

import os
import shutil
import tempfile
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
        d = self.api / name
        (d / "render").mkdir(parents=True)
        (d / "song.mid").write_bytes(b"")
        if saved:
            service.mark_job_saved(d / "song.mid")
        t = 1_700_000_000 - age
        os.utime(d, (t, t))
        return d

    def test_only_saved_jobs_are_pruned_oldest_first(self):
        saved = [self._job(f"saved{i}", age=100 - i, saved=True) for i in range(5)]
        unsaved = [self._job(f"unsaved{i}", age=200 + i) for i in range(5)]
        service._prune_old_job_dirs(keep=2)
        self.assertEqual(sorted(p.name for p in self.api.iterdir()),
                         sorted([p.name for p in unsaved] + ["saved3", "saved4"]))

    def test_caches_are_never_pruned(self):
        caches = [self.api / n for n in ("_guides", "_regen", "_mix_previews", "_live_stems", "_other")]
        for d in caches:
            d.mkdir()
            (d / service._SAVED_MARK).touch()          # even a marked cache stays
            os.utime(d, (1, 1))
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
