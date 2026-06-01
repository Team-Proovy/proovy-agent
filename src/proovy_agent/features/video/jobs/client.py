"""Queue client contract for asynchronous video jobs."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from proovy_agent.features.video.models import StageName, UserErrorCode, VideoJobStatus

if TYPE_CHECKING:
    from collections.abc import Mapping

    from proovy_agent.features.video.jobs.repository import VideoJobRepository
    from proovy_agent.features.video.models import VideoJob, VideoJobInput


class VideoJobClientError(Exception):
    """Base error for queue client operations."""


class VideoJobEnqueueError(VideoJobClientError):
    """Raised when a persisted job could not be enqueued."""

    def __init__(self, job_id: str) -> None:
        super().__init__(f"failed to enqueue video job: {job_id}")
        self.job_id = job_id


class VideoTaskQueue(Protocol):
    """Backend-specific queue adapter.

    Tests can provide a fake implementation; production can replace this with
    Cloud Tasks without changing API or graph callers.

    Real queue adapters must make enqueue idempotent and only raise after they
    have reconciled ambiguous backend failures and know that no task exists.
    """

    async def enqueue(self, job: VideoJob) -> None:
        """Create the backend task for a job."""

    async def delete(self, cloud_tasks_name: str) -> None:
        """Best-effort delete for not-yet-dispatched tasks."""


class NoopVideoTaskQueue:
    """Development queue adapter that records no external task."""

    async def enqueue(self, job: VideoJob) -> None:
        return None

    async def delete(self, cloud_tasks_name: str) -> None:
        return None


class VideoJobClient(Protocol):
    """Application-facing async video job contract."""

    async def create_and_enqueue(
        self,
        *,
        user_id: str,
        thread_id: str,
        input_snapshot: VideoJobInput | None = None,
        retry_source_job_id: str | None = None,
    ) -> VideoJob:
        """Persist a queued job and enqueue a backend task."""

    async def get_progress(self, job_id: str, *, user_id: str | None = None) -> VideoJob | None:
        """Return one job for a hot progress endpoint."""

    async def can_user_retry(self, job: VideoJob) -> bool:
        """Whether the job can be used as a source for one user retry."""

    async def update_progress(
        self,
        job_id: str,
        *,
        stage: StageName | None = None,
        progress: Mapping[str, int] | None = None,
        status: VideoJobStatus | None = None,
    ) -> VideoJob:
        """Write a compact progress update."""

    async def finalize(
        self,
        job_id: str,
        *,
        status: VideoJobStatus,
        artifact_object_key: str | None = None,
        error_stage: StageName | None = None,
        user_error_code: UserErrorCode | None = None,
        error_detail: str | None = None,
        cost: Mapping[str, float] | None = None,
    ) -> VideoJob:
        """Finalize a job as succeeded, failed, or canceled."""

    async def cancel(self, job_id: str) -> VideoJob:
        """Request cancellation of a job."""


class CloudRunVideoJobClient:
    """Video job client for a Cloud Run worker launched through a queue."""

    def __init__(
        self,
        repository: VideoJobRepository,
        queue: VideoTaskQueue | None = None,
    ) -> None:
        self._repository = repository
        self._queue = queue or NoopVideoTaskQueue()

    async def create_and_enqueue(
        self,
        *,
        user_id: str,
        thread_id: str,
        input_snapshot: VideoJobInput | None = None,
        retry_source_job_id: str | None = None,
    ) -> VideoJob:
        job = await self._repository.create(
            user_id=user_id,
            thread_id=thread_id,
            input_snapshot=input_snapshot,
            retry_source_job_id=retry_source_job_id,
        )
        try:
            await self._queue.enqueue(job)
        except Exception as exc:
            await self._repository.finalize(
                job.id,
                status=VideoJobStatus.FAILED,
                error_stage=StageName.ENQUEUE,
                user_error_code=UserErrorCode.INFRASTRUCTURE_ENQUEUE_FAILED,
                error_detail=exc.__class__.__name__,
            )
            raise VideoJobEnqueueError(job.id) from exc
        return job

    async def get_progress(self, job_id: str, *, user_id: str | None = None) -> VideoJob | None:
        job = await self._repository.get(job_id)
        if job is None:
            return None
        if user_id is not None and job.user_id != user_id:
            return None
        return job

    async def can_user_retry(self, job: VideoJob) -> bool:
        if job.status not in {VideoJobStatus.FAILED, VideoJobStatus.CANCELED}:
            return False
        if job.retry_source_job_id is not None:
            return False
        return not await self._repository.has_retry_for_source(job.id)

    async def update_progress(
        self,
        job_id: str,
        *,
        stage: StageName | None = None,
        progress: Mapping[str, int] | None = None,
        status: VideoJobStatus | None = None,
    ) -> VideoJob:
        return await self._repository.update_progress(
            job_id,
            stage=stage,
            progress=progress,
            status=status,
        )

    async def finalize(
        self,
        job_id: str,
        *,
        status: VideoJobStatus,
        artifact_object_key: str | None = None,
        error_stage: StageName | None = None,
        user_error_code: UserErrorCode | None = None,
        error_detail: str | None = None,
        cost: Mapping[str, float] | None = None,
    ) -> VideoJob:
        return await self._repository.finalize(
            job_id,
            status=status,
            artifact_object_key=artifact_object_key,
            error_stage=error_stage,
            user_error_code=user_error_code,
            error_detail=error_detail,
            cost=cost,
        )

    async def cancel(self, job_id: str) -> VideoJob:
        job = await self._repository.request_cancel(job_id)
        if job.status is VideoJobStatus.QUEUED:
            await self._queue.delete(job.cloud_tasks_name)
        return job
