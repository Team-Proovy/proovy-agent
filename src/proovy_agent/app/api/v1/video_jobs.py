"""Video job creation and progress API."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from proovy_agent.app.schemas.video_jobs import (
    CreateVideoJobRequest,
    VideoJobProgressResponse,
)
from proovy_agent.features.video.jobs import (
    NoopVideoArtifactUrlResolver,
    VideoArtifactUrlResolver,
    VideoJobClient,
    build_user_diagnostic,
)
from proovy_agent.features.video.models import VideoJob, VideoJobStatus

router = APIRouter(prefix="/video-jobs")
logger = logging.getLogger(__name__)


def get_video_job_client(request: Request) -> VideoJobClient:
    """Return the app-level video job client."""
    client = getattr(request.app.state, "video_job_client", None)
    if client is None:
        raise HTTPException(status_code=503, detail="video job client is not initialized")
    return client


def get_video_artifact_url_resolver(request: Request) -> VideoArtifactUrlResolver:
    """Return the artifact URL resolver for successful video jobs."""
    return getattr(
        request.app.state,
        "video_artifact_url_resolver",
        NoopVideoArtifactUrlResolver(),
    )


async def _resolve_final_video_url(
    job: VideoJob,
    resolver: VideoArtifactUrlResolver,
) -> str | None:
    if job.status is not VideoJobStatus.SUCCEEDED or job.artifact_object_key is None:
        return None
    try:
        return await resolver.final_video_url(job.artifact_object_key)
    except Exception:
        logger.exception("영상 artifact signed URL 생성 실패: job_id=%s", job.id)
        return None


@router.post(
    "",
    status_code=status.HTTP_410_GONE,
)
async def create_video_job(
    _payload: CreateVideoJobRequest,
) -> None:
    """Reject direct job creation; VideoNode owns create/capture/enqueue."""
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="video jobs must be created by VideoNode",
    )


@router.get("/{job_id}", response_model=VideoJobProgressResponse)
async def get_video_job_progress(
    job_id: str,
    user_id: str = Query(..., description="사용자 ID"),
    client: VideoJobClient = Depends(get_video_job_client),
    artifact_url_resolver: VideoArtifactUrlResolver = Depends(get_video_artifact_url_resolver),
) -> VideoJobProgressResponse:
    """Return the latest progress for a single video job."""
    job = await client.get_progress(job_id, user_id=user_id)
    if job is None:
        raise HTTPException(status_code=404, detail="video job not found")

    can_user_retry = await client.can_user_retry(job)
    final_video_url = await _resolve_final_video_url(job, artifact_url_resolver)
    return VideoJobProgressResponse.from_job(
        job,
        can_user_retry=can_user_retry,
        user_diagnostic=build_user_diagnostic(
            job,
            final_video_url=final_video_url,
            can_user_retry=can_user_retry,
        ),
    )
