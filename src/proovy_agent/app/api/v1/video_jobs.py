"""Video job creation and progress API."""

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from proovy_agent.app.schemas.video_jobs import (
    CreateVideoJobRequest,
    CreateVideoJobResponse,
    VideoJobProgressResponse,
)
from proovy_agent.features.video.jobs import (
    InvalidRetrySourceError,
    NoopVideoArtifactUrlResolver,
    RetryAlreadyUsedError,
    VideoArtifactUrlResolver,
    VideoJobClient,
    VideoJobEnqueueError,
    build_user_diagnostic,
)
from proovy_agent.features.video.models import VideoJob, VideoJobStatus

router = APIRouter(prefix="/video-jobs")


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
    return await resolver.final_video_url(job.artifact_object_key)


@router.post(
    "",
    response_model=CreateVideoJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_video_job(
    payload: CreateVideoJobRequest,
    client: VideoJobClient = Depends(get_video_job_client),
) -> CreateVideoJobResponse:
    """Create a queued video job and return its progress handle."""
    try:
        job = await client.create_and_enqueue(
            user_id=payload.user_id,
            thread_id=payload.thread_id,
            input_snapshot=payload.input_snapshot,
            retry_source_job_id=payload.retry_source_job_id,
        )
    except RetryAlreadyUsedError as exc:
        raise HTTPException(status_code=409, detail="retry already used") from exc
    except InvalidRetrySourceError as exc:
        raise HTTPException(status_code=400, detail="invalid retry source") from exc
    except VideoJobEnqueueError as exc:
        raise HTTPException(status_code=503, detail="video job enqueue failed") from exc

    return CreateVideoJobResponse(
        job_id=job.id,
        status=job.status,
        progress_url=f"/api/v1/video-jobs/{job.id}",
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
