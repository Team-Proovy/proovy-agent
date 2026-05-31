"""User-safe diagnostic helpers for video job status responses."""

from proovy_agent.features.video.models import (
    UserDiagnostic,
    UserErrorCode,
    VideoJob,
    VideoJobStatus,
)


def build_user_diagnostic(
    job: VideoJob,
    *,
    final_video_url: str | None = None,
    can_user_retry: bool = False,
) -> UserDiagnostic | None:
    """Map persisted job fields into the safe user diagnostic skeleton."""
    if job.status is VideoJobStatus.SUCCEEDED:
        if final_video_url is None:
            return None
        return UserDiagnostic(final_video_url=final_video_url)

    if job.status not in {VideoJobStatus.FAILED, VideoJobStatus.CANCELED}:
        return None

    return UserDiagnostic(
        stage_failed=job.error_stage,
        user_error_code=job.user_error_code or UserErrorCode.UNKNOWN,
        retriable=can_user_retry,
        partial_segments_completed=job.progress.get("segments_done"),
    )
