"""Factories for video worker infrastructure."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING
import uuid

from proovy_agent.features.video.jobs.repository import (
    PostgresVideoJobRepository,
)
from proovy_agent.features.video.worker.runner import VideoWorkerRunner
from proovy_agent.features.video.worker.sandbox import ManimRenderSandbox, RenderSandboxConfig

if TYPE_CHECKING:
    from proovy_agent.common.config import Settings


def create_video_worker_runner(settings: Settings) -> VideoWorkerRunner:
    """Create the default worker runner for the current runtime settings."""
    if not settings.database_url:
        raise RuntimeError("database_url must be set for video worker")

    repository = PostgresVideoJobRepository(settings.database_url)
    render_sandbox = ManimRenderSandbox(
        RenderSandboxConfig(
            workspace_root=settings.video_render_workspace_root,
            manim_binary=settings.video_render_manim_binary,
            manim_quality_flag=settings.video_render_manim_quality_flag,
            timeout_seconds=settings.video_render_timeout_seconds,
            memory_limit_mb=settings.video_render_memory_limit_mb,
            file_size_limit_mb=settings.video_render_file_size_limit_mb,
            process_limit=settings.video_render_process_limit,
            workspace_size_limit_mb=settings.video_render_workspace_size_limit_mb,
            require_non_root=settings.video_render_require_non_root,
            require_landlock=settings.video_render_require_landlock,
        )
    )
    return VideoWorkerRunner(
        repository,
        instance_id=settings.video_worker_instance_id or _default_instance_id(),
        lease_stale_after_seconds=settings.video_job_lease_stale_after_seconds,
        heartbeat_interval_seconds=settings.video_job_heartbeat_interval_seconds,
        cancel_poll_interval_seconds=settings.video_cancel_poll_interval_seconds,
        job_max_runtime_seconds=settings.video_job_max_runtime_seconds,
        render_sandbox=render_sandbox,
    )


def _default_instance_id() -> str:
    revision = os.environ.get("K_REVISION", "").strip()
    hostname = os.environ.get("HOSTNAME", "").strip()
    if revision and hostname:
        return f"{revision}:{hostname}"
    if hostname:
        return hostname
    return f"local-{uuid.uuid4()}"
