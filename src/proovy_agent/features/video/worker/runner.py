"""Worker runner for asynchronous video jobs."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Protocol
import uuid

from proovy_agent.features.video.exceptions import PipelineError, classify_failure
from proovy_agent.features.video.jobs.repository import VideoJobNotFoundError, VideoJobRepository
from proovy_agent.features.video.models import (
    StageName,
    UserErrorCode,
    VideoJob,
    VideoJobStatus,
    VideoPipelineJob,
    VideoPipelineResult,
)
from proovy_agent.features.video.pipeline import (
    SegmentProgressEvent,
    StageContext,
    StageEvent,
)
from proovy_agent.features.video.pipeline import (
    run_job as run_pipeline_job,
)

if TYPE_CHECKING:
    from collections.abc import Mapping


class PipelineRunner(Protocol):
    """Callable contract for the staged video pipeline."""

    async def __call__(
        self,
        job: VideoPipelineJob,
        *,
        ctx: StageContext,
    ) -> VideoPipelineResult:
        """Run the pipeline for one job."""


_STAGES: tuple[StageName, ...] = (
    StageName.SOLVE,
    StageName.SCRIPTIFY,
    StageName.TTS,
    StageName.RENDER,
    StageName.COMPOSE,
)
_STAGE_INDEX: Mapping[StageName, int] = {stage: index for index, stage in enumerate(_STAGES)}


class VideoWorkerRunStatus(StrEnum):
    """Outcome of one worker invocation."""

    COMPLETED = "completed"
    CANCELED = "canceled"
    FAILED = "failed"
    RETRY_REQUESTED = "retry_requested"
    SELF_FENCED = "self_fenced"
    SKIPPED = "skipped"


@dataclass(frozen=True, slots=True)
class VideoWorkerRunResult:
    """Summary returned by a worker invocation and HTTP handler."""

    job_id: str
    status: VideoWorkerRunStatus
    job_status: VideoJobStatus | None
    attempt_id: str | None = None


class VideoWorkerError(Exception):
    """Base error for worker execution."""


class VideoWorkerRetryableError(VideoWorkerError):
    """Raised when Cloud Tasks should retry the current job."""

    def __init__(self, job_id: str) -> None:
        super().__init__(f"video worker retry requested: {job_id}")
        self.job_id = job_id


class _LeaseLostError(VideoWorkerError):
    """Raised when this worker no longer owns the job lease."""


class _CancelRequestedError(VideoWorkerError):
    """Raised when the persisted cancel flag asks the worker to stop."""


class _WorkerProgressWriter:
    """Translate pipeline events into user-facing progress writes."""

    def __init__(
        self,
        *,
        repository: VideoJobRepository,
        job_id: str,
        cancel_event: asyncio.Event,
    ) -> None:
        self._repository = repository
        self._job_id = job_id
        self._cancel_event = cancel_event
        self.current_stage: StageName | None = None

    async def handle_stage_event(self, event: StageEvent) -> None:
        self.current_stage = event.stage
        await self._repository.update_progress(
            self._job_id,
            status=VideoJobStatus.RUNNING,
            stage=event.stage,
            progress=_stage_progress(event),
        )
        if event.status == "completed":
            await self.sync_cancel_event()
        elif event.status == "started" and await self.sync_cancel_event():
            raise asyncio.CancelledError

    async def handle_segment_progress(self, event: SegmentProgressEvent) -> None:
        self.current_stage = event.stage
        await self._repository.update_progress(
            self._job_id,
            status=VideoJobStatus.RUNNING,
            stage=event.stage,
            progress=_segment_progress(event),
        )
        if await self.sync_cancel_event():
            raise asyncio.CancelledError

    async def sync_cancel_event(self) -> bool:
        job = await self._repository.get(self._job_id)
        if job is None:
            raise VideoJobNotFoundError(self._job_id)
        if job.cancel_requested and job.status not in {
            VideoJobStatus.SUCCEEDED,
            VideoJobStatus.FAILED,
            VideoJobStatus.CANCELED,
        }:
            self._cancel_event.set()
            return True
        return False


class VideoWorkerRunner:
    """Acquire a job lease, run pipeline stages, and persist progress."""

    def __init__(
        self,
        repository: VideoJobRepository,
        *,
        instance_id: str,
        lease_stale_after_seconds: int = 480,
        heartbeat_interval_seconds: float = 60.0,
        cancel_poll_interval_seconds: float = 10.0,
        job_max_runtime_seconds: float = 1200.0,
        pipeline_runner: PipelineRunner = run_pipeline_job,
    ) -> None:
        self._repository = repository
        self._instance_id = instance_id
        self._lease_stale_after_seconds = lease_stale_after_seconds
        self._heartbeat_interval_seconds = heartbeat_interval_seconds
        self._cancel_poll_interval_seconds = cancel_poll_interval_seconds
        self._job_max_runtime_seconds = job_max_runtime_seconds
        self._pipeline_runner = pipeline_runner

    async def run(self, job_id: str) -> VideoWorkerRunResult:
        """Run one video job if this worker can acquire its lease."""
        attempt_id = str(uuid.uuid4())
        job = await self._repository.acquire_lease(
            job_id,
            instance_id=self._instance_id,
            attempt_id=attempt_id,
            lease_stale_after_seconds=self._lease_stale_after_seconds,
        )
        if job is None:
            skipped = await self._repository.get(job_id)
            return VideoWorkerRunResult(
                job_id=job_id,
                status=VideoWorkerRunStatus.SKIPPED,
                job_status=skipped.status if skipped is not None else None,
            )

        active_attempt_id = job.active_attempt_id or attempt_id
        cancel_event = asyncio.Event()
        progress_writer = _WorkerProgressWriter(
            repository=self._repository,
            job_id=job_id,
            cancel_event=cancel_event,
        )
        if await progress_writer.sync_cancel_event():
            canceled = await self._finalize_canceled(job_id)
            return VideoWorkerRunResult(
                job_id=job_id,
                status=VideoWorkerRunStatus.CANCELED,
                job_status=canceled.status,
                attempt_id=active_attempt_id,
            )

        ctx = StageContext(
            cancel_event=cancel_event,
            progress_handler=progress_writer.handle_stage_event,
            segment_progress_handler=progress_writer.handle_segment_progress,
        )
        pipeline_job = VideoPipelineJob(
            job_id=job.id,
            input_snapshot=job.input_snapshot,
            attempt_id=active_attempt_id,
        )

        try:
            result = await self._run_pipeline_with_watchers(
                pipeline_job,
                ctx=ctx,
                progress_writer=progress_writer,
            )
        except _LeaseLostError:
            return VideoWorkerRunResult(
                job_id=job_id,
                status=VideoWorkerRunStatus.SELF_FENCED,
                job_status=VideoJobStatus.RUNNING,
                attempt_id=active_attempt_id,
            )
        except (_CancelRequestedError, asyncio.CancelledError):
            canceled = await self._finalize_canceled(job_id)
            return VideoWorkerRunResult(
                job_id=job_id,
                status=VideoWorkerRunStatus.CANCELED,
                job_status=canceled.status,
                attempt_id=active_attempt_id,
            )
        except Exception as exc:
            if classify_failure(exc) == "transient":
                await self._repository.release_lease(job_id, instance_id=self._instance_id)
                raise VideoWorkerRetryableError(job_id) from exc

            failed = await self._finalize_failed(
                job_id,
                exc=exc,
                fallback_stage=progress_writer.current_stage,
            )
            return VideoWorkerRunResult(
                job_id=job_id,
                status=VideoWorkerRunStatus.FAILED,
                job_status=failed.status,
                attempt_id=active_attempt_id,
            )

        if await self._repository.heartbeat_lease(job_id, instance_id=self._instance_id) is None:
            return VideoWorkerRunResult(
                job_id=job_id,
                status=VideoWorkerRunStatus.SELF_FENCED,
                job_status=VideoJobStatus.RUNNING,
                attempt_id=active_attempt_id,
            )

        succeeded = await self._repository.finalize(
            job_id,
            status=VideoJobStatus.SUCCEEDED,
            artifact_object_key=_final_artifact_key(
                job_id,
                attempt_id=active_attempt_id,
                output_path=result.final_video.output_path,
            ),
        )
        released = await self._repository.release_lease(job_id, instance_id=self._instance_id)
        final_job = released or succeeded
        return VideoWorkerRunResult(
            job_id=job_id,
            status=VideoWorkerRunStatus.COMPLETED,
            job_status=final_job.status,
            attempt_id=active_attempt_id,
        )

    async def _run_pipeline_with_watchers(
        self,
        job: VideoPipelineJob,
        *,
        ctx: StageContext,
        progress_writer: _WorkerProgressWriter,
    ) -> VideoPipelineResult:
        pipeline_task = asyncio.create_task(
            asyncio.wait_for(
                self._pipeline_runner(job, ctx=ctx),
                timeout=self._job_max_runtime_seconds,
            )
        )
        heartbeat_task = asyncio.create_task(self._heartbeat_loop(job.job_id))
        cancel_task = asyncio.create_task(self._cancel_poll_loop(progress_writer))
        tasks = {pipeline_task, heartbeat_task, cancel_task}
        try:
            done, _pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            if pipeline_task in done:
                return await pipeline_task
            for task in done:
                await task
            raise RuntimeError("worker watcher completed without a result")
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _heartbeat_loop(self, job_id: str) -> None:
        while True:
            await asyncio.sleep(self._heartbeat_interval_seconds)
            if (
                await self._repository.heartbeat_lease(
                    job_id,
                    instance_id=self._instance_id,
                )
                is None
            ):
                raise _LeaseLostError

    async def _cancel_poll_loop(self, progress_writer: _WorkerProgressWriter) -> None:
        while True:
            await asyncio.sleep(self._cancel_poll_interval_seconds)
            if await progress_writer.sync_cancel_event():
                raise _CancelRequestedError

    async def _finalize_canceled(self, job_id: str) -> VideoJob:
        canceled = await self._repository.finalize(job_id, status=VideoJobStatus.CANCELED)
        released = await self._repository.release_lease(job_id, instance_id=self._instance_id)
        return released or canceled

    async def _finalize_failed(
        self,
        job_id: str,
        *,
        exc: Exception,
        fallback_stage: StageName | None,
    ) -> VideoJob:
        error_stage = fallback_stage
        user_error_code = UserErrorCode.UNKNOWN
        if isinstance(exc, PipelineError):
            error_stage = exc.stage or error_stage
            user_error_code = exc.user_error_code

        failed = await self._repository.finalize(
            job_id,
            status=VideoJobStatus.FAILED,
            error_stage=error_stage,
            user_error_code=user_error_code,
            error_detail=type(exc).__name__,
        )
        released = await self._repository.release_lease(job_id, instance_id=self._instance_id)
        return released or failed


def _stage_progress(event: StageEvent) -> dict[str, int]:
    stage_index = _STAGE_INDEX[event.stage]
    stages_completed = stage_index + 1 if event.status == "completed" else stage_index
    return {
        "stages_completed": stages_completed,
        "stages_total": len(_STAGES),
        "stage_index": stage_index + 1,
    }


def _segment_progress(event: SegmentProgressEvent) -> dict[str, int]:
    stage_index = _STAGE_INDEX[event.stage]
    return {
        "stages_completed": stage_index,
        "stages_total": len(_STAGES),
        "stage_index": stage_index + 1,
        "segments_done": event.segment_index,
        "segments_total": event.segment_total,
    }


def _final_artifact_key(job_id: str, *, attempt_id: str, output_path: str) -> str:
    filename = PurePosixPath(output_path).name or "final.mp4"
    return f"video-jobs/{job_id}/attempts/{attempt_id}/{filename}"
