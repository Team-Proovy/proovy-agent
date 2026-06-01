"""Async video job persistence and queue contracts."""

from proovy_agent.features.video.jobs.artifacts import (
    NoopVideoArtifactUrlResolver,
    VideoArtifactUrlResolver,
)
from proovy_agent.features.video.jobs.client import (
    CloudRunVideoJobClient,
    NoopVideoTaskQueue,
    VideoJobClient,
    VideoJobClientError,
    VideoJobEnqueueError,
    VideoTaskQueue,
)
from proovy_agent.features.video.jobs.factory import (
    create_video_artifact_url_resolver,
    create_video_job_client,
)
from proovy_agent.features.video.jobs.repository import (
    InMemoryVideoJobRepository,
    InvalidRetrySourceError,
    PostgresVideoJobRepository,
    RetryAlreadyUsedError,
    VideoJobNotFoundError,
    VideoJobRepository,
    VideoJobStoreError,
)
from proovy_agent.features.video.jobs.user_diagnostic import build_user_diagnostic

__all__ = [
    "CloudRunVideoJobClient",
    "InMemoryVideoJobRepository",
    "InvalidRetrySourceError",
    "NoopVideoArtifactUrlResolver",
    "NoopVideoTaskQueue",
    "PostgresVideoJobRepository",
    "RetryAlreadyUsedError",
    "VideoArtifactUrlResolver",
    "VideoJobClient",
    "VideoJobClientError",
    "VideoJobEnqueueError",
    "VideoJobNotFoundError",
    "VideoJobRepository",
    "VideoJobStoreError",
    "VideoTaskQueue",
    "build_user_diagnostic",
    "create_video_artifact_url_resolver",
    "create_video_job_client",
]
