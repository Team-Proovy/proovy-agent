"""Thread restoration API."""

from fastapi import APIRouter, Depends, Query

from proovy_agent.app.api.v1.video_jobs import (
    build_video_job_response,
    get_video_artifact_url_resolver,
    get_video_job_client,
)
from proovy_agent.app.schemas.threads import ThreadStateResponse
from proovy_agent.common.config import settings
from proovy_agent.features.video.jobs import VideoArtifactUrlResolver, VideoJobClient

router = APIRouter(prefix="/threads")


@router.get("/{thread_id}", response_model=ThreadStateResponse)
async def get_thread_state(
    thread_id: str,
    user_id: str = Query(..., description="사용자 ID"),
    client: VideoJobClient = Depends(get_video_job_client),
    artifact_url_resolver: VideoArtifactUrlResolver = Depends(get_video_artifact_url_resolver),
) -> ThreadStateResponse:
    """Restore low-frequency thread state, including the latest video job status."""
    await client.sweep_stuck_jobs(
        user_id=user_id,
        running_stale_after_seconds=settings.video_stuck_job_threshold_seconds,
        queued_stale_after_seconds=settings.video_queued_task_check_seconds,
    )
    latest_job = await client.get_latest_for_thread(user_id=user_id, thread_id=thread_id)
    video_jobs = []
    if latest_job is not None:
        video_jobs.append(
            await build_video_job_response(
                latest_job,
                client=client,
                artifact_url_resolver=artifact_url_resolver,
            )
        )
    return ThreadStateResponse(user_id=user_id, thread_id=thread_id, video_jobs=video_jobs)
