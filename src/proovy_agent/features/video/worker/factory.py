"""Factories for video worker infrastructure."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING
import uuid

from proovy_agent.features.video.jobs.repository import (
    InMemoryVideoJobRepository,
    PostgresVideoJobRepository,
)
from proovy_agent.features.video.worker.runner import VideoWorkerRunner

if TYPE_CHECKING:
    from proovy_agent.common.config import Settings


def create_video_worker_runner(settings: Settings) -> VideoWorkerRunner:
    """Create the default worker runner for the current runtime settings."""
    if settings.database_url:
        repository = PostgresVideoJobRepository(settings.database_url)
    elif settings.debug:
        repository = InMemoryVideoJobRepository()
    else:
        raise RuntimeError("database_url must be set for video worker outside debug mode")

    return VideoWorkerRunner(
        repository,
        instance_id=settings.video_worker_instance_id or _default_instance_id(),
        lease_stale_after_seconds=settings.video_job_lease_stale_after_seconds,
        heartbeat_interval_seconds=settings.video_job_heartbeat_interval_seconds,
        cancel_poll_interval_seconds=settings.video_cancel_poll_interval_seconds,
        job_max_runtime_seconds=settings.video_job_max_runtime_seconds,
    )


def _default_instance_id() -> str:
    revision = os.environ.get("K_REVISION", "").strip()
    hostname = os.environ.get("HOSTNAME", "").strip()
    if revision and hostname:
        return f"{revision}:{hostname}"
    if hostname:
        return hostname
    return f"local-{uuid.uuid4()}"
