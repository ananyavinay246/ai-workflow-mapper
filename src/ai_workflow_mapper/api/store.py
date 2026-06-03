"""Thread-safe in-memory job store for local development."""

import threading
import uuid
from datetime import datetime, timezone
from typing import Any

from .models import JobOutput


_store: dict[str, JobOutput] = {}
_lock = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_job(request_id: str) -> str:
    job_id = str(uuid.uuid4())
    job = JobOutput(
        job_id=job_id,
        status="accepted",
        result=None,
        metadata={"request_id": request_id, "created_at": _now(), "updated_at": _now()},
    )
    with _lock:
        _store[job_id] = job
    return job_id


def get_job(job_id: str) -> JobOutput | None:
    with _lock:
        return _store.get(job_id)


def update_job(job_id: str, **fields: Any) -> None:
    with _lock:
        job = _store.get(job_id)
        if job is None:
            return
        data = job.model_dump()
        data.update(fields)
        data["metadata"] = {**data.get("metadata", {}), "updated_at": _now()}
        _store[job_id] = JobOutput.model_validate(data)
