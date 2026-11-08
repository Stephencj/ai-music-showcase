"""In-memory background-job registry for long generations (compose → HQ
render → PDF). A job runs on a daemon thread; the heavy work is C/IO bound
(FluidSynth, LilyPond) so threads give real concurrency. Clients poll
``GET /api/jobs/{id}`` or stream ``/events``."""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable, Optional

logger = logging.getLogger("ai_music_studio.api.jobs")


@dataclass
class Job:
    id: str
    status: str = "pending"        # pending | running | done | error
    progress: float = 0.0          # 0.0 – 1.0
    message: str = ""
    result: dict = field(default_factory=dict)
    error: Optional[str] = None
    created: float = field(default_factory=time.time)


class JobRegistry:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def create(self) -> Job:
        job = Job(id=uuid.uuid4().hex[:12])
        with self._lock:
            self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def adopt(self, job_id: str, result: dict) -> Job:
        """Register an already-finished job from a saved result (e.g. one made
        before a restart), so the job routes can serve its files again."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                job = Job(id=job_id, status="done", progress=1.0, message="done", result=dict(result))
                self._jobs[job_id] = job
            return job

    def run(self, job: Job, target: Callable[[Callable[[str, float], None]], dict]) -> None:
        """Run ``target(progress_cb)`` on a daemon thread, recording its
        return dict as ``job.result`` (or the exception as ``job.error``)."""
        def _progress(message: str, frac: float) -> None:
            job.message = message
            job.progress = max(0.0, min(1.0, float(frac)))

        def _runner() -> None:
            job.status = "running"
            try:
                job.result = target(_progress) or {}
                job.status = "done"
                job.progress = 1.0
                job.message = "done"
            except Exception as exc:  # noqa: BLE001 — surface to the client
                job.error = str(exc)
                job.status = "error"
                logger.exception("generation job %s failed", job.id)

        threading.Thread(target=_runner, name=f"gen-{job.id}", daemon=True).start()


registry = JobRegistry()
