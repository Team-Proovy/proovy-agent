"""Factories for video job infrastructure."""

from proovy_agent.common.config import Settings
from proovy_agent.features.video.jobs.client import CloudRunVideoJobClient, NoopVideoTaskQueue
from proovy_agent.features.video.jobs.repository import (
    InMemoryVideoJobRepository,
    PostgresVideoJobRepository,
)


def create_video_job_client(settings: Settings) -> CloudRunVideoJobClient:
    """Create the default video job client for the current runtime settings."""
    if settings.database_url:
        repository = PostgresVideoJobRepository(settings.database_url)
    else:
        repository = InMemoryVideoJobRepository()
    return CloudRunVideoJobClient(repository=repository, queue=NoopVideoTaskQueue())
