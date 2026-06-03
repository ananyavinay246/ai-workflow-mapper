"""FastAPI router implementing the three openapi.yaml endpoints."""

from fastapi import APIRouter

from .models import JobInput, JobOutput
from .processor import process
from .store import create_job, get_job, update_job


router = APIRouter()


class JobNotFoundError(Exception):
    def __init__(self, job_id: str) -> None:
        self.job_id = job_id
        super().__init__(f"Job not found: {job_id}")


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "ai_workflow_mapper"}


@router.post("/jobs", status_code=202, response_model=JobOutput, response_model_exclude_none=True)
def submit_job(body: JobInput) -> JobOutput:
    job_id = create_job(body.request_id)
    try:
        result = process(body)
        update_job(job_id, status="succeeded", result=result)
    except Exception as exc:  # noqa: BLE001
        update_job(job_id, status="failed", result={"error": str(exc)})
    job = get_job(job_id)
    assert job is not None  # always present — we just created it
    return job


@router.get("/jobs/{job_id}", response_model=JobOutput, response_model_exclude_none=True)
def get_job_status(job_id: str) -> JobOutput:
    job = get_job(job_id)
    if job is None:
        raise JobNotFoundError(job_id)
    return job
