"""Persistent pipeline state, idempotency keys and duplicate-upload protection.

One JSON file per job in ``state/jobs/<job_id>.json``. The job ID is derived from the
video file's SHA-256 (plus an optional user idempotency key), so running the same
pipeline config twice resolves to the same job and never uploads twice.

``state/uploads_index.json`` maps file SHA-256 → video ID across all jobs, so the same
file is caught even under a different config or title.

Writes are atomic (temp file + ``os.replace``) and a per-job lock file stops two
processes from driving the same job at once.

Job status lifecycle::

    PENDING → VALIDATED → UPLOADING → UPLOADED → THUMBNAIL_SET → VERIFIED → COMPLETED
                             │
                             └─(interrupted / ambiguous)→ UPLOAD_UNCERTAIN
    any → FAILED (with error) ; UPLOAD_UNCERTAIN → NEEDS_MANUAL_CHECK when remote check is inconclusive
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .exceptions import YTAOSError

STATUSES = [
    "PENDING",
    "VALIDATED",
    "UPLOADING",
    "UPLOAD_UNCERTAIN",
    "UPLOADED",
    "THUMBNAIL_SET",
    "VERIFIED",
    "COMPLETED",
    "FAILED",
    "NEEDS_MANUAL_CHECK",
]
TERMINAL = {"COMPLETED"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: str | Path, chunk: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def make_job_id(file_sha256: str, idempotency_key: str | None = None) -> str:
    base = file_sha256 + ("|" + idempotency_key if idempotency_key else "")
    return hashlib.sha256(base.encode()).hexdigest()[:16]


def _atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False, default=str)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


class JobLocked(YTAOSError):
    exit_code = 11


class StateStore:
    def __init__(self, state_dir: str | Path):
        self.dir = Path(state_dir)
        self.jobs_dir = self.dir / "jobs"
        self.index_path = self.dir / "uploads_index.json"

    # ----- jobs -------------------------------------------------------------------
    def job_path(self, job_id: str) -> Path:
        return self.jobs_dir / f"{job_id}.json"

    def load(self, job_id: str) -> dict | None:
        p = self.job_path(job_id)
        if not p.exists():
            return None
        return json.loads(p.read_text(encoding="utf-8"))

    def create(self, job_id: str, **fields: Any) -> dict:
        job = {
            "job_id": job_id,
            "status": "PENDING",
            "created_at": _now(),
            "updated_at": _now(),
            "video_id": None,
            "steps": {},
            "history": [],
        }
        job.update(fields)
        self.save(job)
        return job

    def save(self, job: dict) -> None:
        job["updated_at"] = _now()
        _atomic_write_json(self.job_path(job["job_id"]), job)

    def transition(self, job: dict, status: str, note: str = "", **fields: Any) -> dict:
        if status not in STATUSES:
            raise ValueError(f"unknown status {status}")
        job["history"].append({"at": _now(), "from": job.get("status"), "to": status, "note": note})
        job["status"] = status
        job.update(fields)
        self.save(job)
        return job

    def step(self, job: dict, name: str, status: str, **detail: Any) -> dict:
        job["steps"][name] = {"status": status, "at": _now(), **detail}
        self.save(job)
        return job

    def list_jobs(self) -> list[dict]:
        if not self.jobs_dir.exists():
            return []
        jobs = []
        for p in sorted(self.jobs_dir.glob("*.json")):
            try:
                jobs.append(json.loads(p.read_text(encoding="utf-8")))
            except ValueError:
                continue
        return sorted(jobs, key=lambda j: j.get("updated_at", ""), reverse=True)

    @contextmanager
    def lock(self, job_id: str) -> Iterator[None]:
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        lock_path = self.jobs_dir / f"{job_id}.lock"
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            raise JobLocked(
                f"Job {job_id} is locked by another run ({lock_path}). If no other run is active, delete the lock file."
            ) from None
        try:
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            yield
        finally:
            try:
                lock_path.unlink()
            except FileNotFoundError:
                pass

    # ----- duplicate index ----------------------------------------------------------
    def _index(self) -> dict:
        if not self.index_path.exists():
            return {}
        try:
            return json.loads(self.index_path.read_text(encoding="utf-8"))
        except ValueError:
            return {}

    def find_upload(self, file_sha256: str) -> dict | None:
        return self._index().get(file_sha256)

    def record_upload(self, file_sha256: str, video_id: str, job_id: str | None, title: str) -> None:
        idx = self._index()
        idx[file_sha256] = {"video_id": video_id, "job_id": job_id, "title": title, "at": _now()}
        _atomic_write_json(self.index_path, idx)
