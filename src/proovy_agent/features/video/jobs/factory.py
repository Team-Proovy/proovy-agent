"""Factories for video job infrastructure."""

from proovy_agent.common.config import Settings
from proovy_agent.features.video.jobs.artifacts import NoopVideoArtifactUrlResolver
from proovy_agent.features.video.jobs.client import (
    CloudRunVideoJobClient,
    CloudTasksVideoTaskQueue,
    NoopVideoTaskQueue,
    VideoTaskQueue,
)
from proovy_agent.features.video.jobs.repository import (
    InMemoryVideoJobRepository,
    PostgresVideoJobRepository,
)


def create_video_job_client(settings: Settings) -> CloudRunVideoJobClient:
    """Create the default video job client for the current runtime settings."""
    if settings.database_url:
        repository = PostgresVideoJobRepository(settings.database_url)
    elif settings.debug:
        repository = InMemoryVideoJobRepository()
        return CloudRunVideoJobClient(repository=repository, queue=NoopVideoTaskQueue())
    else:
        raise RuntimeError("database_url must be set for video jobs outside debug mode")
    return CloudRunVideoJobClient(repository=repository, queue=_create_video_task_queue(settings))


def _create_video_task_queue(settings: Settings) -> VideoTaskQueue:
    if settings.video_cloud_tasks_queue_path and settings.video_worker_url:
        if not settings.video_worker_auth_token:
            raise RuntimeError(
                "VIDEO_WORKER_AUTH_TOKEN must be configured with the video Cloud Tasks queue"
            )
        return CloudTasksVideoTaskQueue(
            queue_path=settings.video_cloud_tasks_queue_path,
            worker_url=settings.video_worker_url,
            worker_auth_token=settings.video_worker_auth_token,
            oidc_service_account_email=settings.video_cloud_tasks_oidc_service_account_email,
        )
    if settings.debug:
        return NoopVideoTaskQueue()
    raise RuntimeError(
        "video Cloud Tasks queue must be configured outside debug mode "
        "(VIDEO_CLOUD_TASKS_QUEUE_PATH and VIDEO_WORKER_URL)"
    )


def create_video_artifact_url_resolver(
    settings: Settings,
) -> NoopVideoArtifactUrlResolver:
    """Create the default video artifact URL resolver."""
    return NoopVideoArtifactUrlResolver()
