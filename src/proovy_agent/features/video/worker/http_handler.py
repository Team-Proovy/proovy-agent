"""HTTP handler for Cloud Tasks video worker dispatch."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, field_validator

from proovy_agent.common.config import settings
from proovy_agent.features.video.jobs.repository import VideoJobNotFoundError
from proovy_agent.features.video.models import (
    VideoJobStatus,  # noqa: TC001 - Pydantic response model needs runtime type
)
from proovy_agent.features.video.worker.factory import create_video_worker_runner
from proovy_agent.features.video.worker.runner import (
    VideoWorkerRetryableError,
    VideoWorkerRunStatus,
)

router = APIRouter(prefix="/jobs")


class RunVideoJobRequest(BaseModel):
    """Cloud Tasks payload for one video job."""

    job_id: str

    @field_validator("job_id")
    @classmethod
    def job_id_not_empty(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("job_id must not be empty")
        return stripped


class RunVideoJobResponse(BaseModel):
    """Response body for a worker job invocation."""

    job_id: str
    outcome: VideoWorkerRunStatus
    job_status: VideoJobStatus | None
    attempt_id: str | None = None


def _get_video_worker_runner(request: Request):
    runner = getattr(request.app.state, "video_worker_runner", None)
    if runner is not None:
        return runner
    try:
        runner = create_video_worker_runner(settings)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="video worker runner is not initialized",
        ) from exc
    request.app.state.video_worker_runner = runner
    return runner


@router.post("/run", response_model=RunVideoJobResponse)
async def run_video_job(payload: RunVideoJobRequest, request: Request) -> RunVideoJobResponse:
    """Run one queued video job from a Cloud Tasks HTTP push."""
    runner = _get_video_worker_runner(request)
    try:
        result = await runner.run(payload.job_id)
    except VideoJobNotFoundError as exc:
        raise HTTPException(status_code=404, detail="video job not found") from exc
    except VideoWorkerRetryableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="video worker retry requested",
        ) from exc

    return RunVideoJobResponse(
        job_id=result.job_id,
        outcome=result.status,
        job_status=result.job_status,
        attempt_id=result.attempt_id,
    )
