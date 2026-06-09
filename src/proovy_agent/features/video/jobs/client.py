"""Queue client contract for asynchronous video jobs."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import logging
from typing import TYPE_CHECKING, Protocol

from google.api_core.exceptions import AlreadyExists, NotFound
from google.cloud import tasks_v2

from proovy_agent.features.video.models import StageName, UserErrorCode, VideoJobStatus

if TYPE_CHECKING:
    from collections.abc import Mapping
    from decimal import Decimal
    from uuid import UUID

    from proovy_agent.features.video.jobs.repository import VideoJobRepository
    from proovy_agent.features.video.models import VideoJob, VideoJobInput

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class VideoCreditCapture:
    """Credit capture that must happen before a backend task is dispatched."""

    hold_id: UUID
    amount: Decimal


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


class CloudTasksVideoTaskQueue:
    """Cloud Tasks HTTP target adapter for video worker dispatch."""

    def __init__(
        self,
        *,
        queue_path: str,
        worker_url: str,
        worker_auth_token: str = "",
        oidc_service_account_email: str = "",
        client: tasks_v2.CloudTasksClient | None = None,
    ) -> None:
        self._queue_path = queue_path.rstrip("/")
        self._worker_url = worker_url
        self._worker_auth_token = worker_auth_token
        self._oidc_service_account_email = oidc_service_account_email
        self._client = client
        if not self._queue_path:
            raise ValueError("queue_path must not be empty")
        if not self._worker_url:
            raise ValueError("worker_url must not be empty")

    async def enqueue(self, job: VideoJob) -> None:
        await asyncio.to_thread(self._create_task, job)

    async def delete(self, cloud_tasks_name: str) -> None:
        await asyncio.to_thread(self._delete_task, cloud_tasks_name)

    def _create_task(self, job: VideoJob) -> None:
        task_name = self._task_path(job.cloud_tasks_name)
        headers = {"Content-Type": "application/json"}
        if self._worker_auth_token:
            headers["X-Proovy-Worker-Token"] = self._worker_auth_token

        http_request = tasks_v2.HttpRequest(
            http_method=tasks_v2.HttpMethod.POST,
            url=self._worker_url,
            headers=headers,
            body=json.dumps({"job_id": job.id}).encode("utf-8"),
        )
        if self._oidc_service_account_email:
            http_request.oidc_token = tasks_v2.OidcToken(
                service_account_email=self._oidc_service_account_email,
                audience=self._worker_url,
            )

        task = tasks_v2.Task(
            name=task_name,
            http_request=http_request,
        )
        try:
            self._tasks_client().create_task(parent=self._queue_path, task=task)
        except AlreadyExists:
            return
        except Exception:
            if self._task_absence_confirmed(task_name):
                raise
            return

    def _delete_task(self, cloud_tasks_name: str) -> None:
        try:
            self._tasks_client().delete_task(name=self._task_path(cloud_tasks_name))
        except NotFound:
            return

    def _task_absence_confirmed(self, task_name: str) -> bool:
        try:
            self._tasks_client().get_task(name=task_name)
        except NotFound:
            return True
        except Exception:
            logger.warning(
                "Cloud Tasks create_task 실패 후 get_task 확인이 모호해 queued 상태로 둡니다: %s",
                task_name,
                exc_info=True,
            )
        return False

    def _tasks_client(self) -> tasks_v2.CloudTasksClient:
        if self._client is None:
            self._client = tasks_v2.CloudTasksClient()
        return self._client

    def _task_path(self, cloud_tasks_name: str) -> str:
        task_id = cloud_tasks_name.rsplit("/", maxsplit=1)[-1]
        return f"{self._queue_path}/tasks/{task_id}"


class VideoJobClient(Protocol):
    """Application-facing async video job contract."""

    async def create_and_enqueue(
        self,
        *,
        user_id: str,
        thread_id: str,
        input_snapshot: VideoJobInput | None = None,
        retry_source_job_id: str | None = None,
        credit_capture: VideoCreditCapture | None = None,
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
        credit_capture: VideoCreditCapture | None = None,
    ) -> VideoJob:
        job = await self._repository.create(
            user_id=user_id,
            thread_id=thread_id,
            input_snapshot=input_snapshot,
            retry_source_job_id=retry_source_job_id,
            credit_capture=credit_capture,
        )
        try:
            await self._queue.enqueue(job)
        except Exception as exc:
            await self._repository.mark_enqueue_failed(
                job.id,
                error_detail=exc.__class__.__name__,
                refund_amount=credit_capture.amount if credit_capture is not None else None,
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
            try:
                await self._queue.delete(job.cloud_tasks_name)
            except Exception:
                logger.exception(
                    "영상 작업 큐 삭제 실패: job_id=%s cloud_tasks_name=%s",
                    job.id,
                    job.cloud_tasks_name,
                )
        return job
